from __future__ import annotations

from dataclasses import dataclass
from threading import Event
import traceback

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreOrchestrator,
    CoreChallenge,
    CoreStatus,
    CoreStatusKind,
    OpaquePermit,
    OrchestrationTimeouts,
)


@dataclass(frozen=True)
class Target:
    pid: int = 42


class FakeDetector:
    def __init__(self, *, target: Target | None = Target()) -> None:
        self.target = target
        self.running = True
        self.wait_calls = 0

    def wait_for_exact_pso2(self, timeout: float, cancellation: Event) -> Target | None:
        self.wait_calls += 1
        return self.target

    def is_same_target_still_running(self, target: Target) -> bool:
        return self.running and target is self.target


class FakeProcess:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def start_host_without_secrets(self) -> None:
        self.calls.append("host.start")

    def wait_for_control_channel(self, timeout: float) -> None:
        self.calls.append("host.ready")

    def stop_gracefully(self, timeout: float) -> bool:
        self.calls.append("host.stop")
        return True

    def kill_owned_process_after_timeout(self) -> None:
        self.calls.append("host.kill")


class FakeChannel:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.status = CoreStatus(CoreStatusKind.RUNNING)

    def request_challenge(self, correlation_id: str, timeout: float) -> CoreChallenge:
        self.calls.append("core.challenge")
        return CoreChallenge("challenge-value")

    def start_authorized(
        self,
        command: object,
        permit: OpaquePermit,
        correlation_id: str,
        timeout: float,
    ) -> CoreStatus:
        assert "sentinel-permit" not in repr(permit)
        self.calls.append("core.start")
        return self.status

    def stop(self, correlation_id: str, timeout: float) -> CoreStatus:
        self.calls.append("core.stop")
        return CoreStatus(CoreStatusKind.STOPPED)


class FakePermitGateway:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def issue_launch_permit(
        self,
        session_id: str,
        installation_key_hash: str,
        challenge: CoreChallenge,
        command: object,
        timeout: float,
    ) -> OpaquePermit:
        self.calls.append("backend.permit")
        return OpaquePermit("sentinel-permit")


def build_orchestrator(
    *, detector: FakeDetector | None = None
) -> tuple[AuthorizedCoreOrchestrator, list[str], FakeDetector, FakeChannel]:
    calls: list[str] = []
    actual_detector = detector or FakeDetector()
    channel = FakeChannel(calls)
    orchestrator = AuthorizedCoreOrchestrator(
        process=FakeProcess(calls),
        channel=channel,
        permits=FakePermitGateway(calls),
        detector=actual_detector,
        timeouts=OrchestrationTimeouts(1, 1, 1, 1, 1),
    )
    return orchestrator, calls, actual_detector, channel


def test_opaque_permit_never_reveals_value() -> None:
    permit = OpaquePermit("sentinel-permit")

    assert "sentinel-permit" not in repr(permit)
    assert "sentinel-permit" not in str(permit)
    assert permit.reveal_for_transport() == "sentinel-permit"


def test_backend_exception_detail_is_not_retained_in_public_failure() -> None:
    orchestrator, _, _, _ = build_orchestrator()

    def leak(*args: object, **kwargs: object) -> OpaquePermit:
        raise RuntimeError("sentinel-backend-token")

    orchestrator._permits.issue_launch_permit = leak  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(object(), "session", "installation", Event())

    rendered = "".join(
        traceback.format_exception(
            type(raised.value), raised.value, raised.value.__traceback__
        )
    )
    assert "sentinel-backend-token" not in rendered


def test_no_target_never_starts_core_or_requests_permit() -> None:
    orchestrator, calls, _, _ = build_orchestrator(detector=FakeDetector(target=None))

    with pytest.raises(AuthorizedCoreError, match="target process is unavailable"):
        orchestrator.start(object(), "session", "installation", Event())

    assert calls == []


def test_authorized_start_is_strictly_sequenced_and_requires_typed_running() -> None:
    orchestrator, calls, _, _ = build_orchestrator()

    status = orchestrator.start(object(), "session", "installation", Event())

    assert status.kind is CoreStatusKind.RUNNING
    assert calls == [
        "host.start",
        "host.ready",
        "core.challenge",
        "backend.permit",
        "core.start",
    ]


def test_target_exit_after_permit_fails_closed_and_cleans_up() -> None:
    orchestrator, calls, detector, _ = build_orchestrator()
    original = orchestrator._permits.issue_launch_permit

    def issue_and_exit(*args: object, **kwargs: object) -> OpaquePermit:
        permit = original(*args, **kwargs)
        detector.running = False
        return permit

    orchestrator._permits.issue_launch_permit = issue_and_exit  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError, match="target process exited"):
        orchestrator.start(object(), "session", "installation", Event())

    assert "core.start" not in calls
    assert calls[-2:] == ["core.stop", "host.stop"]


def test_non_running_start_response_fails_and_cleans_up() -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    channel.status = CoreStatus(CoreStatusKind.FAILED, "AuthorizationInvalid")

    with pytest.raises(AuthorizedCoreError, match="authorized start did not reach Running"):
        orchestrator.start(object(), "session", "installation", Event())

    assert calls[-2:] == ["core.stop", "host.stop"]


def test_cleanup_kills_only_owned_host_when_graceful_stop_fails() -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    channel.status = CoreStatus(CoreStatusKind.FAILED, "AuthorizationInvalid")
    orchestrator._process.stop_gracefully = lambda timeout: False  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError):
        orchestrator.start(object(), "session", "installation", Event())

    assert calls[-2:] == ["core.stop", "host.kill"]


def test_duplicate_start_is_rejected_without_a_second_flow() -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    assert orchestrator._single_flight.acquire(blocking=False)
    try:
        with pytest.raises(AuthorizedCoreError, match="already in progress"):
            orchestrator.start(object(), "session", "installation", Event())
    finally:
        orchestrator._single_flight.release()

    assert calls == []


def test_cancelled_attempt_does_not_start_host() -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    cancellation = Event()
    cancellation.set()

    with pytest.raises(AuthorizedCoreError, match="cancelled"):
        orchestrator.start(object(), "session", "installation", cancellation)

    assert calls == []
