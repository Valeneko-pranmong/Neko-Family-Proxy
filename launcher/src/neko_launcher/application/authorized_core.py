from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from re import fullmatch
from threading import Event, Lock
from time import monotonic
from typing import Callable, Protocol, TypeVar, cast, Any
from uuid import uuid4


class AuthorizedCoreErrorCode(str, Enum):
    ADAPTER_FAILURE = "AdapterFailure"
    AUTHORIZATION_CONTEXT_UNAVAILABLE = "AuthorizationContextUnavailable"
    CONFIGURATION_UNAVAILABLE = "ConfigurationUnavailable"
    DUPLICATE_START = "DuplicateStart"
    CANCELLED = "Cancelled"
    TARGET_UNAVAILABLE = "TargetUnavailable"
    TARGET_EXITED = "TargetExited"
    HEARTBEAT_UNAVAILABLE = "HeartbeatUnavailable"
    RUNNING_NOT_REACHED = "RunningNotReached"
    PERMIT_UNAVAILABLE = "PermitUnavailable"
    CHALLENGE_UNAVAILABLE = "ChallengeUnavailable"
    PROCESS_OBSERVATION_UNAVAILABLE = "ProcessObservationUnavailable"


class PermitDiagnosticCode(str, Enum):
    """Development-only categories that never contain credential material."""

    PERMIT_FUNCTION_NOT_FOUND = "PERMIT_FUNCTION_NOT_FOUND"
    PERMIT_HTTP_401 = "PERMIT_HTTP_401"
    PERMIT_HTTP_403 = "PERMIT_HTTP_403"
    PERMIT_HTTP_500 = "PERMIT_HTTP_500"
    PERMIT_INVALID_RESPONSE = "PERMIT_INVALID_RESPONSE"
    PERMIT_MISSING_FIELD = "PERMIT_MISSING_FIELD"
    PERMIT_TIMEOUT = "PERMIT_TIMEOUT"
    PERMIT_AUTH_SESSION_UNAVAILABLE = "PERMIT_AUTH_SESSION_UNAVAILABLE"
    PERMIT_UNAVAILABLE = "PERMIT_UNAVAILABLE"


_PUBLIC_ERROR_MESSAGES = {
    AuthorizedCoreErrorCode.ADAPTER_FAILURE: "authorized start failed",
    AuthorizedCoreErrorCode.AUTHORIZATION_CONTEXT_UNAVAILABLE: (
        "authorization context is unavailable"
    ),
    AuthorizedCoreErrorCode.CONFIGURATION_UNAVAILABLE: (
        "start configuration is unavailable"
    ),
    AuthorizedCoreErrorCode.DUPLICATE_START: "authorized start is already in progress",
    AuthorizedCoreErrorCode.CANCELLED: "authorized start was cancelled",
    AuthorizedCoreErrorCode.TARGET_UNAVAILABLE: "target process is unavailable",
    AuthorizedCoreErrorCode.TARGET_EXITED: "target process exited",
    AuthorizedCoreErrorCode.HEARTBEAT_UNAVAILABLE: "fresh heartbeat is unavailable",
    AuthorizedCoreErrorCode.RUNNING_NOT_REACHED: (
        "authorized start did not reach Running"
    ),
    AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE: "authorization permit is unavailable",
    AuthorizedCoreErrorCode.CHALLENGE_UNAVAILABLE: (
        "authorization challenge is unavailable"
    ),
    AuthorizedCoreErrorCode.PROCESS_OBSERVATION_UNAVAILABLE: (
        "target process observation is unavailable"
    ),
}


class AuthorizedCoreError(RuntimeError):
    """Typed sanitized failure from an authorized Core start attempt."""

    def __init__(
        self,
        code: AuthorizedCoreErrorCode | str,
        private_detail: str | None = None,
        *,
        diagnostic_code: PermitDiagnosticCode | None = None,
        diagnostic_context: dict[str, object] | None = None,
    ) -> None:
        # Legacy/adapter-owned text is never treated as a public condition.
        self.code = (
            code
            if isinstance(code, AuthorizedCoreErrorCode)
            else AuthorizedCoreErrorCode.ADAPTER_FAILURE
        )
        self.diagnostic_code = (
            diagnostic_code
            if isinstance(diagnostic_code, PermitDiagnosticCode)
            else None
        )
        self.diagnostic_context = self._validated_diagnostic_context(
            diagnostic_context or {}
        )
        super().__init__(_PUBLIC_ERROR_MESSAGES[self.code])

    @staticmethod
    def _validated_diagnostic_context(
        context: dict[str, object],
    ) -> dict[str, object]:
        validated: dict[str, object] = {}
        if context.get("function") == "issue_launch_permit":
            validated["function"] = "issue_launch_permit"
        if context.get("stage") == "PERMIT_REQUEST":
            validated["stage"] = "PERMIT_REQUEST"

        http_status = context.get("http_status")
        if isinstance(http_status, int) and 100 <= http_status <= 599:
            validated["http_status"] = http_status

        correlation_id = context.get("correlation_id")
        if isinstance(correlation_id, str) and fullmatch(
            r"[0-9a-f]{32}", correlation_id
        ):
            validated["correlation_id"] = correlation_id

        elapsed_ms = context.get("elapsed_ms")
        if isinstance(elapsed_ms, int) and 0 <= elapsed_ms <= 600_000:
            validated["elapsed_ms"] = elapsed_ms

        exception_class = context.get("exception_class")
        safe_exception_classes = {
            "ConnectError",
            "ConnectTimeout",
            "FunctionsFetchError",
            "FunctionsHttpError",
            "FunctionsRelayError",
            "NetworkError",
            "PoolTimeout",
            "ReadTimeout",
            "RemoteProtocolError",
            "TimeoutError",
            "WriteTimeout",
        }
        if exception_class in safe_exception_classes:
            validated["exception_class"] = exception_class
        return validated


class OpaquePermit:
    """Sensitive permit whose normal representations never expose its value."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not value:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE)
        self._value = value

    def __repr__(self) -> str:
        return "OpaquePermit(<redacted>)"

    __str__ = __repr__

    def reveal_for_transport(self) -> str:
        """Return the permit only at the direct transport serialization boundary."""
        return self._value


@dataclass(frozen=True)
class CoreChallenge:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.CHALLENGE_UNAVAILABLE)


class CoreStatusKind(str, Enum):
    RUNNING = "Running"
    STOPPED = "Stopped"
    FAILED = "Failed"


@dataclass(frozen=True)
class CoreStatus:
    kind: CoreStatusKind
    error_code: str | None = None


@dataclass(frozen=True)
class OrchestrationTimeouts:
    target: float
    control_channel: float
    challenge: float
    permit: float
    start: float

    def __post_init__(self) -> None:
        if any(value <= 0 for value in self.__dict__.values()):
            raise ValueError("orchestration timeouts must be positive")


@dataclass(frozen=True)
class LaunchAccessContext:
    """Local fail-fast facts; Backend authorization remains authoritative."""

    authenticated: bool
    entitlement_active: bool
    session_id: str
    installation_key_hash: str
    authenticated_transport: object | None

    def require_available(self) -> None:
        if not (
            self.authenticated
            and self.entitlement_active
            and self.session_id
            and self.installation_key_hash
            and self.authenticated_transport is not None
        ):
            raise AuthorizedCoreError(
                AuthorizedCoreErrorCode.AUTHORIZATION_CONTEXT_UNAVAILABLE
            )


@dataclass(frozen=True)
class OpaqueStartCommand:
    """Credential-free references for one canonical ProcessMode start."""

    profile_reference: str
    server_reference: str

    def require_available(self) -> None:
        if not (
            fullmatch(r"profile-[0-9]{1,6}", self.profile_reference)
            and fullmatch(r"server-[0-9]{1,6}", self.server_reference)
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.CONFIGURATION_UNAVAILABLE)


@dataclass(frozen=True)
class TargetBoundStartCommand:
    """Validated Protocol v2 command and its exact canonical configuration."""

    profile_reference: str
    server_reference: str
    target_pid: int
    process_name: str = "pso2.exe"
    mode: str = "ProcessMode"

    @classmethod
    def from_opaque(
        cls,
        command: OpaqueStartCommand,
        *,
        target_pid: int,
    ) -> TargetBoundStartCommand:
        command.require_available()
        if (
            isinstance(target_pid, bool)
            or not isinstance(target_pid, int)
            or not 1 <= target_pid <= 4_294_967_295
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.CONFIGURATION_UNAVAILABLE)
        return cls(command.profile_reference, command.server_reference, target_pid)

    @property
    def canonical_bytes(self) -> bytes:
        return (
            "protocolVersion=2\n"
            f"mode={self.mode}\n"
            f"processName={self.process_name}\n"
            f"targetPid={self.target_pid}\n"
            f"profileReference={self.profile_reference}\n"
            f"serverReference={self.server_reference}\n"
        ).encode("utf-8")

    @property
    def configuration_digest(self) -> str:
        return sha256(self.canonical_bytes).hexdigest()


TargetT = TypeVar("TargetT")
AdapterResultT = TypeVar("AdapterResultT")


class CoreProcessAdapter(Protocol):
    def start_host_without_secrets(self) -> None: ...

    def wait_for_control_channel(self, timeout: float) -> None: ...

    def stop_gracefully(self, timeout: float) -> bool: ...

    def kill_owned_process_after_timeout(self) -> None: ...


class CoreControlChannel(Protocol):
    def request_challenge(self, correlation_id: str, timeout: float) -> CoreChallenge: ...

    def start_authorized(
        self,
        command: object,
        permit: OpaquePermit,
        correlation_id: str,
        timeout: float,
    ) -> CoreStatus: ...

    def stop(self, correlation_id: str, timeout: float) -> CoreStatus: ...


class LaunchPermitGateway(Protocol):
    def issue_launch_permit(
        self,
        authenticated_transport: object,
        correlation_id: str,
        challenge: CoreChallenge,
        configuration_digest: str,
        process_name: str,
        target_pid: int,
        mode: str,
        product: str,
        scope: str,
        timeout: float,
    ) -> OpaquePermit: ...


class LaunchPrecondition(Protocol):
    """Online, fail-closed validation required before a Core host can start."""

    def require_fresh(
        self,
        session_id: str,
        installation_key_hash: str,
        timeout: float,
    ) -> None: ...


class OnlineHeartbeatLaunchPrecondition:
    """Runs a new online heartbeat for each admitted start attempt."""

    def __init__(
        self,
        probe: Callable[[str, str, float], bool],
        *,
        monotonic: Callable[[], float] = monotonic,
    ) -> None:
        self._probe = probe
        self._monotonic = monotonic
        self._last_success_monotonic: float | None = None

    @property
    def last_success_monotonic(self) -> float | None:
        return self._last_success_monotonic

    def require_fresh(
        self,
        session_id: str,
        installation_key_hash: str,
        timeout: float,
    ) -> None:
        try:
            alive = self._probe(session_id, installation_key_hash, timeout)
        except Exception:
            alive = False
        if not alive:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.HEARTBEAT_UNAVAILABLE)
        self._last_success_monotonic = self._monotonic()


class ProcessTargetDetector(Protocol[TargetT]):
    def wait_for_exact_pso2(
        self, timeout: float, cancellation: Event
    ) -> TargetT | None: ...

    def is_same_target_still_running(self, target: TargetT) -> bool: ...


class AuthorizedCoreOrchestrator:
    """Single-flight, fail-closed orchestration independent of the draft wire protocol."""

    def __init__(
        self,
        *,
        process: CoreProcessAdapter,
        channel: CoreControlChannel,
        permits: LaunchPermitGateway,
        precondition: LaunchPrecondition,
        detector: ProcessTargetDetector[object],
        timeouts: OrchestrationTimeouts,
        diagnostics: Any = None,
    ) -> None:
        self._process = process
        self._channel = channel
        self._permits = permits
        self._precondition = precondition
        self._detector = detector
        self._timeouts = timeouts
        self._single_flight = Lock()
        self._diagnostics = diagnostics

    def start(
        self,
        command: OpaqueStartCommand,
        access_context: LaunchAccessContext,
        cancellation: Event,
    ) -> CoreStatus:
        if self._diagnostics:
            from uuid import uuid4
            self._diagnostics.begin_attempt(f"DBG-{uuid4().hex[:6]}")

        if self._diagnostics:
            self._diagnostics.record_stage("COMMAND_VALIDATE")
        command.require_available()
        
        if self._diagnostics:
            self._diagnostics.record_stage("ACCESS_CONTEXT_VALIDATE")
        access_context.require_available()
        
        if not self._single_flight.acquire(blocking=False):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.DUPLICATE_START)

        host_start_attempted = False
        status: CoreStatus | None = None
        failure: AuthorizedCoreError | None = None
        try:
            try:
                self._require_not_cancelled(cancellation)
                
                if self._diagnostics:
                    self._diagnostics.record_stage("TARGET_WAIT")
                target = self._invoke_adapter(
                    lambda: self._detector.wait_for_exact_pso2(
                        self._timeouts.target, cancellation
                    ),
                    AuthorizedCoreErrorCode.TARGET_UNAVAILABLE,
                    stage="TARGET_WAIT",
                )
                if target is None:
                    raise AuthorizedCoreError(AuthorizedCoreErrorCode.TARGET_UNAVAILABLE)
                self._require_not_cancelled(cancellation)

                self._invoke_adapter(
                    lambda: self._precondition.require_fresh(
                        access_context.session_id,
                        access_context.installation_key_hash,
                        self._timeouts.permit,
                    ),
                    AuthorizedCoreErrorCode.HEARTBEAT_UNAVAILABLE,
                    stage="ACCESS_CONTEXT_VALIDATE",
                )
                self._require_not_cancelled(cancellation)
                self._require_target(target)

                # Cleanup is safe for an unowned/no-process state and must run even
                # when an adapter creates the host and then reports a failure.
                host_start_attempted = True
                
                if self._diagnostics:
                    self._diagnostics.record_stage("HOST_START")
                self._invoke_adapter(
                    self._process.start_host_without_secrets,
                    AuthorizedCoreErrorCode.ADAPTER_FAILURE,
                    stage="HOST_START",
                )
                
                if self._diagnostics:
                    self._diagnostics.record_stage("CONTROL_CHANNEL_WAIT")
                self._invoke_adapter(
                    lambda: self._process.wait_for_control_channel(
                        self._timeouts.control_channel
                    ),
                    AuthorizedCoreErrorCode.ADAPTER_FAILURE,
                    stage="CONTROL_CHANNEL_WAIT",
                )
                
                if self._diagnostics:
                    self._diagnostics.record_stage("TARGET_RECHECK")
                self._require_target(target)

                if self._diagnostics:
                    self._diagnostics.record_stage("CHALLENGE_REQUEST")
                challenge = self._invoke_adapter(
                    lambda: self._channel.request_challenge(
                        self._correlation_id(), self._timeouts.challenge
                    ),
                    AuthorizedCoreErrorCode.CHALLENGE_UNAVAILABLE,
                    stage="CHALLENGE_REQUEST",
                )
                self._require_target(target)
                
                if self._diagnostics:
                    self._diagnostics.record_stage("TARGET_BIND")
                target_bound_command = TargetBoundStartCommand.from_opaque(
                    command,
                    target_pid=self._target_pid(target),
                )
                
                if self._diagnostics:
                    self._diagnostics.record_stage("PERMIT_REQUEST")
                permit = self._invoke_adapter(
                    lambda: self._permits.issue_launch_permit(
                        access_context.authenticated_transport,
                        self._correlation_id(),
                        challenge,
                        target_bound_command.configuration_digest,
                        target_bound_command.process_name,
                        target_bound_command.target_pid,
                        target_bound_command.mode,
                        "neko-family-proxy",
                        "proxy:start",
                        self._timeouts.permit,
                    ),
                    AuthorizedCoreErrorCode.ADAPTER_FAILURE,
                    stage="PERMIT_REQUEST",
                )
                self._require_not_cancelled(cancellation)
                self._require_target(target)

                if self._diagnostics:
                    self._diagnostics.record_stage("AUTHORIZED_START")
                status = self._invoke_adapter(
                    lambda: self._channel.start_authorized(
                        target_bound_command,
                        permit,
                        self._correlation_id(),
                        self._timeouts.start,
                    ),
                    AuthorizedCoreErrorCode.ADAPTER_FAILURE,
                    stage="AUTHORIZED_START",
                )
                
                if self._diagnostics:
                    self._diagnostics.record_stage("RUNNING_VERIFY")
                if status.kind is not CoreStatusKind.RUNNING:
                    raise AuthorizedCoreError(AuthorizedCoreErrorCode.RUNNING_NOT_REACHED)
            except AuthorizedCoreError as exc:
                failure = AuthorizedCoreError(
                    exc.code,
                    diagnostic_code=exc.diagnostic_code,
                    diagnostic_context=exc.diagnostic_context,
                )
            except Exception as exc:
                if self._diagnostics:
                    self._diagnostics.record_exception(exc, "UNKNOWN_STAGE")
                failure = AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)

            if failure is not None and host_start_attempted:
                if self._diagnostics:
                    self._diagnostics.record_stage("CLEANUP")
                self._cleanup()
        finally:
            self._single_flight.release()

        if failure is not None:
            raise failure
        if status is None:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        return status

    @staticmethod
    def _target_pid(target: object) -> int:
        pid = getattr(target, "pid", None)
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.TARGET_UNAVAILABLE)
        return pid

    def _require_target(self, target: object) -> None:
        running = self._invoke_adapter(
            lambda: self._detector.is_same_target_still_running(target),
            AuthorizedCoreErrorCode.PROCESS_OBSERVATION_UNAVAILABLE,
            stage="TARGET_RECHECK",
        )
        if not running:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.TARGET_EXITED)

    def _invoke_adapter(
        self,
        operation: Callable[[], AdapterResultT],
        failure_code: AuthorizedCoreErrorCode,
        stage: str | None = None,
    ) -> AdapterResultT:
        failure: AuthorizedCoreError | None = None
        result: object = None
        try:
            result = operation()
        except Exception as exc:
            if self._diagnostics and stage:
                self._diagnostics.record_exception(exc, stage)
            if (
                stage == "PERMIT_REQUEST"
                and isinstance(exc, AuthorizedCoreError)
                and exc.code is AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE
                and isinstance(exc.diagnostic_code, PermitDiagnosticCode)
            ):
                failure = AuthorizedCoreError(
                    AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE,
                    diagnostic_code=exc.diagnostic_code,
                    diagnostic_context=exc.diagnostic_context,
                )
            else:
                failure = AuthorizedCoreError(failure_code)
        if failure is not None:
            raise failure
        return cast(AdapterResultT, result)

    @staticmethod
    def _require_not_cancelled(cancellation: Event) -> None:
        if cancellation.is_set():
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.CANCELLED)

    def stop(self) -> None:
        """Best-effort typed stop followed by bounded owned-process cleanup."""
        self._cleanup()

    def _cleanup(self) -> None:
        try:
            self._channel.stop(self._correlation_id(), self._timeouts.start)
        except Exception:
            pass
        try:
            stopped = self._process.stop_gracefully(self._timeouts.start)
        except Exception:
            stopped = False
        if not stopped:
            try:
                self._process.kill_owned_process_after_timeout()
            except Exception:
                pass

    @staticmethod
    def _correlation_id() -> str:
        return uuid4().hex
