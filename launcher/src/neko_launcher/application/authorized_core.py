from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from re import fullmatch
from threading import Event, Lock
from time import monotonic
from typing import Callable, Protocol, TypeVar
from uuid import uuid4


class AuthorizedCoreError(RuntimeError):
    """Sanitized failure from an authorized Core start attempt."""


class OpaquePermit:
    """Sensitive permit whose normal representations never expose its value."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not value:
            raise AuthorizedCoreError("authorization permit is unavailable")
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
            raise AuthorizedCoreError("authorization challenge is unavailable")


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

    def require_available(self) -> None:
        if not (
            self.authenticated
            and self.entitlement_active
            and self.session_id
            and self.installation_key_hash
        ):
            raise AuthorizedCoreError("authorization context is unavailable")


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
            raise AuthorizedCoreError("start configuration is unavailable")


TargetT = TypeVar("TargetT")


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
        session_id: str,
        installation_key_hash: str,
        challenge: CoreChallenge,
        command: object,
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
            raise AuthorizedCoreError("fresh heartbeat is unavailable")
        self._last_success_monotonic = self._monotonic()


class ProcessTargetDetector(Protocol[TargetT]):
    def wait_for_exact_pso2(
        self, timeout: float, cancellation: Event
    ) -> TargetT | None: ...

    def is_same_target_still_running(self, target: TargetT) -> bool: ...


class AuthorizedCoreOrchestrator:
    """Single-flight, fail-closed orchestration independent of the draft wire protocol."""

    _PUBLIC_FAILURES = frozenset(
        {
            "authorization context is unavailable",
            "start configuration is unavailable",
            "authorized start is already in progress",
            "authorized start was cancelled",
            "target process is unavailable",
            "target process exited",
            "fresh heartbeat is unavailable",
            "authorized start did not reach Running",
        }
    )

    def __init__(
        self,
        *,
        process: CoreProcessAdapter,
        channel: CoreControlChannel,
        permits: LaunchPermitGateway,
        launch_precondition: LaunchPrecondition,
        detector: ProcessTargetDetector[object],
        timeouts: OrchestrationTimeouts,
    ) -> None:
        self._process = process
        self._channel = channel
        self._permits = permits
        self._launch_precondition = launch_precondition
        self._detector = detector
        self._timeouts = timeouts
        self._single_flight = Lock()

    def start(
        self,
        command: OpaqueStartCommand,
        access_context: LaunchAccessContext,
        cancellation: Event,
    ) -> CoreStatus:
        command.require_available()
        access_context.require_available()
        if not self._single_flight.acquire(blocking=False):
            raise AuthorizedCoreError("authorized start is already in progress")

        host_start_attempted = False
        status: CoreStatus | None = None
        failure: AuthorizedCoreError | None = None
        try:
            try:
                self._require_not_cancelled(cancellation)
                target = self._detector.wait_for_exact_pso2(
                    self._timeouts.target, cancellation
                )
                if target is None:
                    raise AuthorizedCoreError("target process is unavailable")
                self._require_not_cancelled(cancellation)

                self._launch_precondition.require_fresh(
                    access_context.session_id,
                    access_context.installation_key_hash,
                    self._timeouts.permit,
                )
                self._require_not_cancelled(cancellation)
                self._require_target(target)

                # Cleanup is safe for an unowned/no-process state and must run even
                # when an adapter creates the host and then reports a failure.
                host_start_attempted = True
                self._process.start_host_without_secrets()
                self._process.wait_for_control_channel(self._timeouts.control_channel)
                self._require_target(target)

                challenge = self._channel.request_challenge(
                    self._correlation_id(), self._timeouts.challenge
                )
                self._require_target(target)
                permit = self._permits.issue_launch_permit(
                    access_context.session_id,
                    access_context.installation_key_hash,
                    challenge,
                    command,
                    self._timeouts.permit,
                )
                self._require_not_cancelled(cancellation)
                self._require_target(target)

                status = self._channel.start_authorized(
                    command,
                    permit,
                    self._correlation_id(),
                    self._timeouts.start,
                )
                if status.kind is not CoreStatusKind.RUNNING:
                    raise AuthorizedCoreError(
                        "authorized start did not reach Running"
                    )
            except AuthorizedCoreError as exc:
                rendered_message = str(exc)
                public_message = (
                    rendered_message
                    if rendered_message in self._PUBLIC_FAILURES
                    else "authorized start failed"
                )
                failure = AuthorizedCoreError(public_message)
            except Exception:
                failure = AuthorizedCoreError("authorized start failed")

            if failure is not None and host_start_attempted:
                self._cleanup()
        finally:
            self._single_flight.release()

        if failure is not None:
            raise failure
        if status is None:
            raise AuthorizedCoreError("authorized start failed")
        return status

    def _require_target(self, target: object) -> None:
        if not self._detector.is_same_target_still_running(target):
            raise AuthorizedCoreError("target process exited")

    @staticmethod
    def _require_not_cancelled(cancellation: Event) -> None:
        if cancellation.is_set():
            raise AuthorizedCoreError("authorized start was cancelled")

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
