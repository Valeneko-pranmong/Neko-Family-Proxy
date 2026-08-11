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
    AUTHORIZATION_REQUIRED = "AuthorizationRequired"
    AUTHORIZATION_INVALID = "AuthorizationInvalid"
    AUTHORIZATION_EXPIRED = "AuthorizationExpired"
    AUTHORIZATION_REPLAY = "AuthorizationReplay"
    AUTHORIZATION_UNAVAILABLE = "AuthorizationUnavailable"
    SESSION_INACTIVE = "SessionInactive"
    ENTITLEMENT_INACTIVE = "EntitlementInactive"
    HEARTBEAT_STALE = "HeartbeatStale"
    CONFIGURATION_UNAVAILABLE = "ConfigurationUnavailable"
    CONFIGURATION_MISMATCH = "ConfigurationMismatch"
    DUPLICATE_START = "DuplicateStart"
    CANCELLED = "Cancelled"
    TARGET_UNAVAILABLE = "TargetUnavailable"
    TARGET_EXITED = "TargetExited"
    HEARTBEAT_UNAVAILABLE = "HeartbeatUnavailable"
    ALREADY_RUNNING = "AlreadyRunning"
    PROTOCOL_INVALID = "ProtocolInvalid"
    START_TIMEOUT = "StartTimeout"
    START_FAILED = "StartFailed"
    STOP_FAILED = "StopFailed"
    RUNNING_NOT_REACHED = "RunningNotReached"
    PERMIT_UNAVAILABLE = "PermitUnavailable"
    CHALLENGE_UNAVAILABLE = "ChallengeUnavailable"
    PROCESS_OBSERVATION_UNAVAILABLE = "ProcessObservationUnavailable"


class AuthorizedCoreFailureDomain(str, Enum):
    ADAPTER = "Adapter"
    AUTHORIZATION = "Authorization"
    AUTHORITY = "Authority"
    CONFIGURATION = "Configuration"
    TARGET = "Target"
    PROTOCOL = "Protocol"
    RUNTIME = "Runtime"


class CoreControlFailureCode(str, Enum):
    """Transport failures that matter to owned-host lifecycle decisions."""

    PIPE_UNAVAILABLE = "PipeUnavailable"
    PIPE_IDENTITY_MISMATCH = "PipeIdentityMismatch"
    PIPE_CLOSED = "PipeClosed"
    OPERATION_TIMEOUT = "OperationTimeout"
    RESPONSE_REJECTED = "ResponseRejected"


class CoreShutdownFailureCode(str, Enum):
    CORE_ALREADY_EXITED = "CORE_ALREADY_EXITED"
    PIPE_UNAVAILABLE = "PIPE_UNAVAILABLE"
    PIPE_IDENTITY_MISMATCH = "PIPE_IDENTITY_MISMATCH"
    SHUTDOWN_REJECTED = "SHUTDOWN_REJECTED"
    SHUTDOWN_TIMEOUT = "SHUTDOWN_TIMEOUT"
    PROCESS_EXIT_TIMEOUT = "PROCESS_EXIT_TIMEOUT"


class CoreShutdownError(RuntimeError):
    """Exact failure from an owned Core host shutdown attempt."""

    def __init__(
        self,
        code: CoreShutdownFailureCode,
        *,
        emergency_fallback_used: bool = False,
    ) -> None:
        self.code = code
        self.emergency_fallback_used = emergency_fallback_used
        super().__init__(code.value)


@dataclass(frozen=True)
class CoreShutdownResult:
    exit_code: int
    emergency_fallback_used: bool = False


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
    AuthorizedCoreErrorCode.AUTHORIZATION_REQUIRED: "start authorization is required",
    AuthorizedCoreErrorCode.AUTHORIZATION_INVALID: "start authorization is invalid",
    AuthorizedCoreErrorCode.AUTHORIZATION_EXPIRED: "start authorization expired",
    AuthorizedCoreErrorCode.AUTHORIZATION_REPLAY: "start authorization was already used",
    AuthorizedCoreErrorCode.AUTHORIZATION_UNAVAILABLE: "start authorization is unavailable",
    AuthorizedCoreErrorCode.SESSION_INACTIVE: "launcher session is inactive",
    AuthorizedCoreErrorCode.ENTITLEMENT_INACTIVE: "launcher entitlement is inactive",
    AuthorizedCoreErrorCode.HEARTBEAT_STALE: "launcher heartbeat is stale",
    AuthorizedCoreErrorCode.CONFIGURATION_UNAVAILABLE: ("start configuration is unavailable"),
    AuthorizedCoreErrorCode.CONFIGURATION_MISMATCH: "start configuration does not match",
    AuthorizedCoreErrorCode.DUPLICATE_START: "authorized start is already in progress",
    AuthorizedCoreErrorCode.CANCELLED: "authorized start was cancelled",
    AuthorizedCoreErrorCode.TARGET_UNAVAILABLE: "target process is unavailable",
    AuthorizedCoreErrorCode.TARGET_EXITED: "target process exited",
    AuthorizedCoreErrorCode.HEARTBEAT_UNAVAILABLE: "fresh heartbeat is unavailable",
    AuthorizedCoreErrorCode.ALREADY_RUNNING: "Core runtime is already running",
    AuthorizedCoreErrorCode.PROTOCOL_INVALID: "Core start protocol is invalid",
    AuthorizedCoreErrorCode.START_TIMEOUT: "Core start timed out",
    AuthorizedCoreErrorCode.START_FAILED: "Core start failed",
    AuthorizedCoreErrorCode.STOP_FAILED: "Core stop failed during start",
    AuthorizedCoreErrorCode.RUNNING_NOT_REACHED: ("authorized start did not reach Running"),
    AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE: "authorization permit is unavailable",
    AuthorizedCoreErrorCode.CHALLENGE_UNAVAILABLE: ("authorization challenge is unavailable"),
    AuthorizedCoreErrorCode.PROCESS_OBSERVATION_UNAVAILABLE: (
        "target process observation is unavailable"
    ),
}

_FAILURE_DOMAINS = {
    AuthorizedCoreErrorCode.ADAPTER_FAILURE: AuthorizedCoreFailureDomain.ADAPTER,
    AuthorizedCoreErrorCode.AUTHORIZATION_CONTEXT_UNAVAILABLE: (
        AuthorizedCoreFailureDomain.AUTHORIZATION
    ),
    AuthorizedCoreErrorCode.AUTHORIZATION_REQUIRED: AuthorizedCoreFailureDomain.AUTHORIZATION,
    AuthorizedCoreErrorCode.AUTHORIZATION_INVALID: AuthorizedCoreFailureDomain.AUTHORIZATION,
    AuthorizedCoreErrorCode.AUTHORIZATION_EXPIRED: AuthorizedCoreFailureDomain.AUTHORIZATION,
    AuthorizedCoreErrorCode.AUTHORIZATION_REPLAY: AuthorizedCoreFailureDomain.AUTHORIZATION,
    AuthorizedCoreErrorCode.AUTHORIZATION_UNAVAILABLE: AuthorizedCoreFailureDomain.AUTHORIZATION,
    AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE: AuthorizedCoreFailureDomain.AUTHORIZATION,
    AuthorizedCoreErrorCode.SESSION_INACTIVE: AuthorizedCoreFailureDomain.AUTHORITY,
    AuthorizedCoreErrorCode.ENTITLEMENT_INACTIVE: AuthorizedCoreFailureDomain.AUTHORITY,
    AuthorizedCoreErrorCode.HEARTBEAT_STALE: AuthorizedCoreFailureDomain.AUTHORITY,
    AuthorizedCoreErrorCode.HEARTBEAT_UNAVAILABLE: AuthorizedCoreFailureDomain.AUTHORITY,
    AuthorizedCoreErrorCode.CONFIGURATION_UNAVAILABLE: AuthorizedCoreFailureDomain.CONFIGURATION,
    AuthorizedCoreErrorCode.CONFIGURATION_MISMATCH: AuthorizedCoreFailureDomain.CONFIGURATION,
    AuthorizedCoreErrorCode.TARGET_UNAVAILABLE: AuthorizedCoreFailureDomain.TARGET,
    AuthorizedCoreErrorCode.TARGET_EXITED: AuthorizedCoreFailureDomain.TARGET,
    AuthorizedCoreErrorCode.PROCESS_OBSERVATION_UNAVAILABLE: AuthorizedCoreFailureDomain.TARGET,
    AuthorizedCoreErrorCode.PROTOCOL_INVALID: AuthorizedCoreFailureDomain.PROTOCOL,
    AuthorizedCoreErrorCode.CHALLENGE_UNAVAILABLE: AuthorizedCoreFailureDomain.PROTOCOL,
    AuthorizedCoreErrorCode.DUPLICATE_START: AuthorizedCoreFailureDomain.RUNTIME,
    AuthorizedCoreErrorCode.CANCELLED: AuthorizedCoreFailureDomain.RUNTIME,
    AuthorizedCoreErrorCode.ALREADY_RUNNING: AuthorizedCoreFailureDomain.RUNTIME,
    AuthorizedCoreErrorCode.START_TIMEOUT: AuthorizedCoreFailureDomain.RUNTIME,
    AuthorizedCoreErrorCode.START_FAILED: AuthorizedCoreFailureDomain.RUNTIME,
    AuthorizedCoreErrorCode.STOP_FAILED: AuthorizedCoreFailureDomain.RUNTIME,
    AuthorizedCoreErrorCode.RUNNING_NOT_REACHED: AuthorizedCoreFailureDomain.RUNTIME,
}

_CORE_START_FAILURES = {
    "AuthorizationRequired": AuthorizedCoreErrorCode.AUTHORIZATION_REQUIRED,
    "AuthorizationInvalid": AuthorizedCoreErrorCode.AUTHORIZATION_INVALID,
    "AuthorizationExpired": AuthorizedCoreErrorCode.AUTHORIZATION_EXPIRED,
    "AuthorizationReplay": AuthorizedCoreErrorCode.AUTHORIZATION_REPLAY,
    "AuthorizationUnavailable": AuthorizedCoreErrorCode.AUTHORIZATION_UNAVAILABLE,
    "SessionInactive": AuthorizedCoreErrorCode.SESSION_INACTIVE,
    "EntitlementInactive": AuthorizedCoreErrorCode.ENTITLEMENT_INACTIVE,
    "HeartbeatStale": AuthorizedCoreErrorCode.HEARTBEAT_STALE,
    "ProcessNotFound": AuthorizedCoreErrorCode.TARGET_UNAVAILABLE,
    "ProcessExited": AuthorizedCoreErrorCode.TARGET_EXITED,
    "ConfigurationMismatch": AuthorizedCoreErrorCode.CONFIGURATION_MISMATCH,
    "AlreadyRunning": AuthorizedCoreErrorCode.ALREADY_RUNNING,
    "ProtocolInvalid": AuthorizedCoreErrorCode.PROTOCOL_INVALID,
    "StartTimeout": AuthorizedCoreErrorCode.START_TIMEOUT,
    "Cancelled": AuthorizedCoreErrorCode.CANCELLED,
    "StartFailed": AuthorizedCoreErrorCode.START_FAILED,
    "StopFailed": AuthorizedCoreErrorCode.STOP_FAILED,
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
        self.domain = _FAILURE_DOMAINS[self.code]
        self.diagnostic_code = (
            diagnostic_code if isinstance(diagnostic_code, PermitDiagnosticCode) else None
        )
        self.diagnostic_context = self._validated_diagnostic_context(diagnostic_context or {})
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
        if isinstance(correlation_id, str) and fullmatch(r"[0-9a-f]{32}", correlation_id):
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


class CoreControlError(AuthorizedCoreError):
    """Sanitized control-channel failure with a stable internal category."""

    def __init__(self, control_code: CoreControlFailureCode) -> None:
        self.control_code = control_code
        super().__init__(AuthorizedCoreErrorCode.ADAPTER_FAILURE)


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


def require_core_start_running(status: CoreStatus) -> None:
    """Preserve only allow-listed Core START failures; reject all other outcomes."""
    if status.kind is CoreStatusKind.FAILED:
        mapped = _CORE_START_FAILURES.get(status.error_code or "")
        if mapped is None:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        raise AuthorizedCoreError(mapped)
    if status.kind is not CoreStatusKind.RUNNING:
        raise AuthorizedCoreError(AuthorizedCoreErrorCode.RUNNING_NOT_REACHED)


@dataclass(frozen=True)
class OrchestrationTimeouts:
    target: float
    control_channel: float
    challenge: float
    permit: float
    start_response: float
    stop_response: float
    shutdown_response: float
    process_exit: float

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
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.AUTHORIZATION_CONTEXT_UNAVAILABLE)


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

    def owned_process_id(self) -> int | None: ...

    def wait_for_owned_process_exit(self, expected_pid: int, timeout: float) -> int: ...

    def terminate_owned_process_after_timeout(self, expected_pid: int, timeout: float) -> int: ...


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

    def status(self, correlation_id: str, timeout: float) -> CoreStatus: ...

    def shutdown(self, correlation_id: str, timeout: float) -> CoreStatus: ...


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
    def wait_for_exact_pso2(self, timeout: float, cancellation: Event) -> TargetT | None: ...

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
                    lambda: self._detector.wait_for_exact_pso2(self._timeouts.target, cancellation),
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
                    lambda: self._process.wait_for_control_channel(self._timeouts.control_channel),
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
                    lambda: self._start_authorized_with_diagnostics(
                        target_bound_command,
                        permit,
                        self._correlation_id(),
                    ),
                    AuthorizedCoreErrorCode.ADAPTER_FAILURE,
                    stage="AUTHORIZED_START",
                )

                if self._diagnostics:
                    self._diagnostics.record_stage("RUNNING_VERIFY")
                require_core_start_running(status)
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
                self._cleanup_owned_host_safely()
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

    def _start_authorized_with_diagnostics(
        self,
        command: TargetBoundStartCommand,
        permit: OpaquePermit,
        correlation_id: str,
    ) -> CoreStatus:
        started_at = monotonic()
        owned_pid = self._process.owned_process_id()
        try:
            status = self._channel.start_authorized(
                command,
                permit,
                correlation_id,
                self._timeouts.start_response,
            )
        except Exception as exc:
            alive = self._process.owned_process_id() == owned_pid and owned_pid is not None
            failure_category = "START_RESPONSE_REJECTED"
            transport_outcome = "START_RESPONSE_REJECTED"
            if not alive:
                failure_category = "CORE_EXITED"
                transport_outcome = "CORE_EXITED"
            elif isinstance(exc, CoreControlError):
                if exc.control_code is CoreControlFailureCode.OPERATION_TIMEOUT:
                    failure_category = "START_RESPONSE_TIMEOUT"
                    transport_outcome = "CORE_ALIVE_NO_RESPONSE"
                elif exc.control_code is CoreControlFailureCode.PIPE_IDENTITY_MISMATCH:
                    failure_category = "PIPE_IDENTITY_MISMATCH"
                    transport_outcome = "PIPE_IDENTITY_MISMATCH"
                elif exc.control_code in {
                    CoreControlFailureCode.PIPE_CLOSED,
                    CoreControlFailureCode.PIPE_UNAVAILABLE,
                }:
                    failure_category = "PIPE_CLOSED"
                    transport_outcome = "PIPE_CLOSED"
            self._record_authorized_start_result(
                started_at=started_at,
                failure_category=failure_category,
                core_pid=owned_pid,
                core_alive=alive,
                transport_outcome=transport_outcome,
            )
            raise

        classification = (
            "START_TYPED_SUCCESS"
            if status.kind is CoreStatusKind.RUNNING
            else "START_TYPED_FAILURE"
        )
        self._record_authorized_start_result(
            started_at=started_at,
            failure_category=classification,
            core_pid=owned_pid,
            core_alive=(self._process.owned_process_id() == owned_pid and owned_pid is not None),
            transport_outcome=classification,
        )
        return status

    def _record_authorized_start_result(
        self,
        *,
        started_at: float,
        failure_category: str,
        core_pid: int | None,
        core_alive: bool,
        transport_outcome: str,
    ) -> None:
        if not self._diagnostics:
            return
        elapsed_ms = max(0, int((monotonic() - started_at) * 1000))
        self._diagnostics.record_stage(
            "AUTHORIZED_START_RESULT",
            elapsed_ms=elapsed_ms,
            failure_category=failure_category,
            core_pid=core_pid,
            core_alive=core_alive,
            transport_outcome=transport_outcome,
        )

    @staticmethod
    def _require_not_cancelled(cancellation: Event) -> None:
        if cancellation.is_set():
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.CANCELLED)

    def stop(self) -> None:
        """Stop the proxy runtime only; keep the exact owned Core host alive."""
        status = self._channel.stop(self._correlation_id(), self._timeouts.stop_response)
        if status.kind is not CoreStatusKind.STOPPED:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)

    def has_owned_host(self) -> bool:
        return self._process.owned_process_id() is not None

    def shutdown(self) -> CoreShutdownResult:
        """Gracefully close the exact owned Core host using its trusted pipe."""
        expected_pid = self._process.owned_process_id()
        if expected_pid is None:
            raise CoreShutdownError(CoreShutdownFailureCode.CORE_ALREADY_EXITED)

        try:
            status = self._channel.shutdown(
                self._correlation_id(), self._timeouts.shutdown_response
            )
        except CoreControlError as exc:
            code = {
                CoreControlFailureCode.PIPE_UNAVAILABLE: (CoreShutdownFailureCode.PIPE_UNAVAILABLE),
                CoreControlFailureCode.PIPE_IDENTITY_MISMATCH: (
                    CoreShutdownFailureCode.PIPE_IDENTITY_MISMATCH
                ),
                CoreControlFailureCode.PIPE_CLOSED: (CoreShutdownFailureCode.SHUTDOWN_REJECTED),
                CoreControlFailureCode.OPERATION_TIMEOUT: (
                    CoreShutdownFailureCode.SHUTDOWN_TIMEOUT
                ),
                CoreControlFailureCode.RESPONSE_REJECTED: (
                    CoreShutdownFailureCode.SHUTDOWN_REJECTED
                ),
            }[exc.control_code]
            fallback_used = self._emergency_terminate_exact_child(expected_pid)
            raise CoreShutdownError(code, emergency_fallback_used=fallback_used) from None
        except Exception:
            fallback_used = self._emergency_terminate_exact_child(expected_pid)
            raise CoreShutdownError(
                CoreShutdownFailureCode.SHUTDOWN_REJECTED,
                emergency_fallback_used=fallback_used,
            ) from None

        if status.kind is not CoreStatusKind.STOPPED:
            fallback_used = self._emergency_terminate_exact_child(expected_pid)
            raise CoreShutdownError(
                CoreShutdownFailureCode.SHUTDOWN_REJECTED,
                emergency_fallback_used=fallback_used,
            )

        try:
            exit_code = self._process.wait_for_owned_process_exit(
                expected_pid, self._timeouts.process_exit
            )
        except Exception:
            fallback_used = self._emergency_terminate_exact_child(
                expected_pid, timeout_already_expired=True
            )
            raise CoreShutdownError(
                CoreShutdownFailureCode.PROCESS_EXIT_TIMEOUT,
                emergency_fallback_used=fallback_used,
            ) from None

        if exit_code != 0:
            raise CoreShutdownError(CoreShutdownFailureCode.SHUTDOWN_REJECTED)
        return CoreShutdownResult(exit_code=exit_code)

    def _cleanup_owned_host_safely(self) -> None:
        try:
            self.shutdown()
        except CoreShutdownError:
            # The original start error remains authoritative. shutdown() has
            # already applied the exact-child emergency cleanup policy.
            pass

    def _emergency_terminate_exact_child(
        self,
        expected_pid: int,
        *,
        timeout_already_expired: bool = False,
    ) -> bool:
        if not timeout_already_expired:
            try:
                self._process.wait_for_owned_process_exit(expected_pid, self._timeouts.process_exit)
            except Exception:
                pass
            else:
                return False
        try:
            self._process.terminate_owned_process_after_timeout(
                expected_pid, self._timeouts.process_exit
            )
        except Exception:
            return False
        return True

    @staticmethod
    def _correlation_id() -> str:
        return uuid4().hex
