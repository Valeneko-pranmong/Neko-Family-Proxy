from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Event, Lock
from typing import Protocol, TypeVar
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
        detector: ProcessTargetDetector[object],
        timeouts: OrchestrationTimeouts,
    ) -> None:
        self._process = process
        self._channel = channel
        self._permits = permits
        self._detector = detector
        self._timeouts = timeouts
        self._single_flight = Lock()

    def start(
        self,
        command: object,
        session_id: str,
        installation_key_hash: str,
        cancellation: Event,
    ) -> CoreStatus:
        if not self._single_flight.acquire(blocking=False):
            raise AuthorizedCoreError("authorized start is already in progress")
        host_started = False
        try:
            self._require_not_cancelled(cancellation)
            if not session_id or not installation_key_hash:
                raise AuthorizedCoreError("authorization context is unavailable")

            target = self._detector.wait_for_exact_pso2(
                self._timeouts.target, cancellation
            )
            if target is None:
                raise AuthorizedCoreError("target process is unavailable")
            self._require_not_cancelled(cancellation)

            self._process.start_host_without_secrets()
            host_started = True
            self._process.wait_for_control_channel(self._timeouts.control_channel)
            self._require_target(target)

            challenge = self._channel.request_challenge(
                self._correlation_id(), self._timeouts.challenge
            )
            self._require_target(target)
            permit = self._permits.issue_launch_permit(
                session_id,
                installation_key_hash,
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
                raise AuthorizedCoreError("authorized start did not reach Running")
            return status
        except AuthorizedCoreError:
            if host_started:
                self._cleanup()
            raise
        except Exception:
            if host_started:
                self._cleanup()
            raise AuthorizedCoreError("authorized start failed") from None
        finally:
            self._single_flight.release()

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
            self._process.kill_owned_process_after_timeout()

    @staticmethod
    def _correlation_id() -> str:
        return uuid4().hex
