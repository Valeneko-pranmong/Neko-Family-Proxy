from __future__ import annotations

from dataclasses import dataclass
from threading import Event
import traceback

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    CoreControlError,
    CoreControlFailureCode,
    CoreShutdownError,
    CoreShutdownFailureCode,
    AuthorizedCoreOrchestrator,
    CoreChallenge,
    CoreStatus,
    CoreStatusKind,
    LaunchAccessContext,
    OpaquePermit,
    OpaqueStartCommand,
    OnlineHeartbeatLaunchPrecondition,
    OrchestrationTimeouts,
    PermitDiagnosticCode,
    TargetBoundStartCommand,
)


@dataclass(frozen=True)
class Target:
    pid: int = 42


def valid_access_context() -> LaunchAccessContext:
    return LaunchAccessContext(True, True, "session", "installation", object())


def valid_command() -> OpaqueStartCommand:
    return OpaqueStartCommand("profile-0", "server-0")


def test_target_bound_command_builds_exact_canonical_bytes_and_digest() -> None:
    command = TargetBoundStartCommand.from_opaque(valid_command(), target_pid=4242)

    assert command.canonical_bytes == (
        b"protocolVersion=2\n"
        b"mode=ProcessMode\n"
        b"processName=pso2.exe\n"
        b"targetPid=4242\n"
        b"profileReference=profile-0\n"
        b"serverReference=server-0\n"
    )
    assert command.configuration_digest == (
        "92ac70d0f9b100ba664f2bb205b2c042bc1058f779e94e759822d906ea880871"
    )


@pytest.mark.parametrize("target_pid", [True, 0, 4_294_967_296, "4242"])
def test_target_bound_command_rejects_invalid_pid_types_and_bounds(
    target_pid: object,
) -> None:
    with pytest.raises(AuthorizedCoreError, match="start configuration is unavailable"):
        TargetBoundStartCommand.from_opaque(
            valid_command(),
            target_pid=target_pid,  # type: ignore[arg-type]
        )


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
        self.live = False
        self.exit_code = 0
        self.exit_timeout = False

    def start_host_without_secrets(self) -> None:
        self.calls.append("host.start")
        self.live = True

    def wait_for_control_channel(self, timeout: float) -> None:
        self.calls.append("host.ready")

    def owned_process_id(self) -> int | None:
        return 4321 if self.live else None

    def wait_for_owned_process_exit(self, expected_pid: int, timeout: float) -> int:
        assert expected_pid == 4321
        self.calls.append("host.wait")
        if self.exit_timeout:
            raise TimeoutError
        self.live = False
        return self.exit_code

    def terminate_owned_process_after_timeout(
        self, expected_pid: int, timeout: float
    ) -> int:
        assert expected_pid == 4321
        self.calls.append("host.kill")
        self.live = False
        return 1


class FakeChannel:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.status = CoreStatus(CoreStatusKind.RUNNING)
        self.start_command: object | None = None

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
        self.start_command = command
        self.calls.append("core.start")
        return self.status

    def stop(self, correlation_id: str, timeout: float) -> CoreStatus:
        self.calls.append("core.stop")
        return CoreStatus(CoreStatusKind.STOPPED)

    def shutdown(self, correlation_id: str, timeout: float) -> CoreStatus:
        self.calls.append("core.shutdown")
        return CoreStatus(CoreStatusKind.STOPPED)


class FakeLaunchPrecondition:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.available = True

    def require_fresh(
        self,
        session_id: str,
        installation_key_hash: str,
        timeout: float,
    ) -> None:
        self.calls.append("backend.heartbeat")
        if not self.available:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.HEARTBEAT_UNAVAILABLE)


class FakePermitGateway:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.request: dict[str, object] | None = None

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
    ) -> OpaquePermit:
        self.request = {
            "authenticated_transport": authenticated_transport,
            "correlation_id": correlation_id,
            "challenge": challenge,
            "configuration_digest": configuration_digest,
            "process_name": process_name,
            "target_pid": target_pid,
            "mode": mode,
            "product": product,
            "scope": scope,
            "timeout": timeout,
        }
        self.calls.append("backend.permit")
        return OpaquePermit("sentinel-permit")


def build_orchestrator(
    *, detector: FakeDetector | None = None
) -> tuple[
    AuthorizedCoreOrchestrator,
    list[str],
    FakeDetector,
    FakeChannel,
]:
    calls: list[str] = []
    actual_detector = detector or FakeDetector()
    channel = FakeChannel(calls)
    precondition = FakeLaunchPrecondition(calls)
    orchestrator = AuthorizedCoreOrchestrator(
        process=FakeProcess(calls),
        channel=channel,
        permits=FakePermitGateway(calls),
        precondition=precondition,
        detector=actual_detector,
        timeouts=OrchestrationTimeouts(1, 1, 1, 1, 1),
    )
    return orchestrator, calls, actual_detector, channel


def test_opaque_permit_never_reveals_value() -> None:
    permit = OpaquePermit("sentinel-permit")

    assert "sentinel-permit" not in repr(permit)
    assert "sentinel-permit" not in str(permit)
    assert permit.reveal_for_transport() == "sentinel-permit"


@pytest.mark.parametrize(
    ("profile_reference", "server_reference"),
    [
        ("", "server-0"),
        ("profile-0", ""),
        ("profile-0", "server.example.invalid:443"),
        ("profile-0", "method:password@server-0"),
        ("profile-0", "server-0000000"),
    ],
)
def test_invalid_opaque_references_fail_before_activation(
    profile_reference: str,
    server_reference: str,
) -> None:
    orchestrator, calls, detector, _ = build_orchestrator()

    with pytest.raises(AuthorizedCoreError, match="start configuration is unavailable"):
        orchestrator.start(
            OpaqueStartCommand(profile_reference, server_reference),
            valid_access_context(),
            Event(),
        )

    assert detector.wait_calls == 0
    assert calls == []


def test_backend_exception_detail_is_not_retained_in_public_failure() -> None:
    orchestrator, _, _, _ = build_orchestrator()

    def leak(*args: object, **kwargs: object) -> OpaquePermit:
        raise RuntimeError("sentinel-backend-token")

    orchestrator._permits.issue_launch_permit = leak  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    rendered = "".join(
        traceback.format_exception(
            type(raised.value), raised.value, raised.value.__traceback__
        )
    )
    assert "sentinel-backend-token" not in rendered


def test_permit_failure_preserves_only_sanitized_development_diagnostics() -> None:
    orchestrator, _, _, _ = build_orchestrator()

    def unavailable(*args: object, **kwargs: object) -> OpaquePermit:
        raise AuthorizedCoreError(
            AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE,
            diagnostic_code=PermitDiagnosticCode.PERMIT_FUNCTION_NOT_FOUND,
            diagnostic_context={
                "function": "issue_launch_permit",
                "http_status": 404,
                "access_token": "sentinel-secret",
            },
        )

    orchestrator._permits.issue_launch_permit = unavailable  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE
    assert raised.value.diagnostic_code is PermitDiagnosticCode.PERMIT_FUNCTION_NOT_FOUND
    assert raised.value.diagnostic_context["http_status"] == 404
    assert str(raised.value) == "authorization permit is unavailable"
    assert "sentinel-secret" not in str(raised.value)


def test_permit_adapter_cannot_spoof_a_public_condition_by_typed_code() -> None:
    orchestrator, _, _, _ = build_orchestrator()

    def spoof(*args: object, **kwargs: object) -> object:
        raise AuthorizedCoreError(AuthorizedCoreErrorCode.TARGET_EXITED)

    orchestrator._permits.issue_launch_permit = spoof  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE
    assert str(raised.value) == "authorized start failed"











def test_no_target_never_starts_core_or_requests_permit() -> None:
    orchestrator, calls, _, _ = build_orchestrator(detector=FakeDetector(target=None))

    with pytest.raises(AuthorizedCoreError, match="target process is unavailable"):
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert calls == []


@pytest.mark.parametrize(
    "access_context",
    [
        LaunchAccessContext(False, True, "session", "installation", object()),
        LaunchAccessContext(True, False, "session", "installation", object()),
        LaunchAccessContext(True, True, "", "installation", object()),
        LaunchAccessContext(True, True, "session", "", object()),
        LaunchAccessContext(True, True, "session", "installation", None),
    ],
)
def test_invalid_local_access_context_has_no_activation_side_effects(
    access_context: LaunchAccessContext,
) -> None:
    orchestrator, calls, detector, _ = build_orchestrator()

    with pytest.raises(AuthorizedCoreError, match="authorization context is unavailable"):
        orchestrator.start(valid_command(), access_context, Event())

    assert detector.wait_calls == 0
    assert calls == []





def test_online_heartbeat_precondition_records_only_a_successful_fresh_result() -> None:
    probe_calls: list[tuple[str, str, float]] = []

    def probe(session_id: str, installation_key_hash: str, timeout: float) -> bool:
        probe_calls.append((session_id, installation_key_hash, timeout))
        return True

    precondition = OnlineHeartbeatLaunchPrecondition(probe, monotonic=lambda: 123.0)

    precondition.require_fresh("session", "installation", 2.0)

    assert probe_calls == [("session", "installation", 2.0)]
    assert precondition.last_success_monotonic == 123.0


def test_online_heartbeat_precondition_sanitizes_probe_failure() -> None:
    def probe(*args: object) -> bool:
        raise RuntimeError("sentinel-heartbeat-detail")

    precondition = OnlineHeartbeatLaunchPrecondition(probe)

    with pytest.raises(AuthorizedCoreError) as raised:
        precondition.require_fresh("session", "installation", 2.0)

    assert str(raised.value) == "fresh heartbeat is unavailable"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert precondition.last_success_monotonic is None


def test_online_heartbeat_false_has_no_success_timestamp() -> None:
    precondition = OnlineHeartbeatLaunchPrecondition(lambda *args: False)

    with pytest.raises(AuthorizedCoreError, match="fresh heartbeat is unavailable"):
        precondition.require_fresh("session", "installation", 2.0)

    assert precondition.last_success_monotonic is None


def test_failed_heartbeat_does_not_advance_previous_success_timestamp() -> None:
    results = iter([True, False])
    times = iter([123.0, 456.0])
    precondition = OnlineHeartbeatLaunchPrecondition(
        lambda *args: next(results),
        monotonic=lambda: next(times),
    )
    precondition.require_fresh("session", "installation", 2.0)

    with pytest.raises(AuthorizedCoreError, match="fresh heartbeat is unavailable"):
        precondition.require_fresh("session", "installation", 2.0)

    assert precondition.last_success_monotonic == 123.0








def test_authorized_start_is_strictly_sequenced_and_requires_typed_running() -> None:
    orchestrator, calls, _, _ = build_orchestrator()

    status = orchestrator.start(valid_command(), valid_access_context(), Event())

    assert status.kind is CoreStatusKind.RUNNING
    assert calls == [
        "backend.heartbeat",
        "host.start",
        "host.ready",
        "core.challenge",
        "backend.permit",
        "core.start",
    ]


def test_challenge_transport_failure_is_typed_safe_pre_permit_failure() -> None:
    orchestrator, calls, _, _ = build_orchestrator()

    def fail_challenge(*args: object, **kwargs: object) -> CoreChallenge:
        raise RuntimeError("transient challenge transport failure")

    orchestrator._channel.request_challenge = fail_challenge  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.CHALLENGE_UNAVAILABLE
    assert "backend.permit" not in calls
    assert calls[-2:] == ["core.shutdown", "host.wait"]


def test_replaced_session_fails_before_core_host_start() -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    orchestrator._precondition.available = False  # type: ignore[attr-defined]

    with pytest.raises(AuthorizedCoreError, match="fresh heartbeat is unavailable"):
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert calls == ["backend.heartbeat"]


def test_cancellation_during_heartbeat_fails_before_core_host_start() -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    cancellation = Event()
    original_require_fresh = orchestrator._precondition.require_fresh

    def cancel_after_heartbeat(*args: object, **kwargs: object) -> None:
        original_require_fresh(*args, **kwargs)
        cancellation.set()

    orchestrator._precondition.require_fresh = cancel_after_heartbeat  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError, match="authorized start was cancelled"):
        orchestrator.start(valid_command(), valid_access_context(), cancellation)

    assert calls == ["backend.heartbeat"]


def test_authority_request_uses_target_binding_without_server_owned_identity_fields() -> None:
    orchestrator, _, _, channel = build_orchestrator()
    permits = orchestrator._permits

    orchestrator.start(valid_command(), valid_access_context(), Event())

    assert isinstance(channel.start_command, TargetBoundStartCommand)
    assert permits.request is not None  # type: ignore[attr-defined]
    request = permits.request  # type: ignore[attr-defined]
    assert request["target_pid"] == 42
    assert request["process_name"] == "pso2.exe"
    assert request["mode"] == "ProcessMode"
    assert request["product"] == "neko-family-proxy"
    assert request["scope"] == "proxy:start"
    assert request["configuration_digest"] == channel.start_command.configuration_digest
    assert set(request).isdisjoint({"sub", "sid", "iid", "lid", "installation_key_hash"})


def test_target_observation_failure_is_not_reported_as_target_exit() -> None:
    orchestrator, calls, detector, _ = build_orchestrator()

    def fail_observation(target: Target) -> bool:
        raise RuntimeError("transient process observation failure")

    detector.is_same_target_still_running = fail_observation  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.PROCESS_OBSERVATION_UNAVAILABLE
    assert calls == ["backend.heartbeat"]


def test_target_exit_after_permit_fails_closed_and_cleans_up() -> None:
    orchestrator, calls, detector, _ = build_orchestrator()
    original = orchestrator._permits.issue_launch_permit

    def issue_and_exit(*args: object, **kwargs: object) -> OpaquePermit:
        permit = original(*args, **kwargs)
        detector.running = False
        return permit

    orchestrator._permits.issue_launch_permit = issue_and_exit  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError, match="target process exited"):
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert "core.start" not in calls
    assert calls[-2:] == ["core.shutdown", "host.wait"]


def test_non_running_start_response_fails_and_cleans_up() -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    channel.status = CoreStatus(CoreStatusKind.FAILED, "AuthorizationInvalid")

    with pytest.raises(AuthorizedCoreError, match="authorized start did not reach Running"):
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert calls[-2:] == ["core.shutdown", "host.wait"]


def test_cleanup_kills_only_owned_host_after_graceful_exit_timeout() -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    channel.status = CoreStatus(CoreStatusKind.FAILED, "AuthorizationInvalid")
    orchestrator._process.exit_timeout = True  # type: ignore[attr-defined]

    with pytest.raises(AuthorizedCoreError):
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert calls[-3:] == ["core.shutdown", "host.wait", "host.kill"]


def test_partial_host_start_failure_triggers_owned_process_cleanup() -> None:
    orchestrator, calls, _, _ = build_orchestrator()

    def partially_start_then_fail() -> None:
        calls.append("host.start")
        orchestrator._process.live = True  # type: ignore[attr-defined]
        raise RuntimeError("sentinel-partial-start-detail")

    orchestrator._process.start_host_without_secrets = partially_start_then_fail  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert str(raised.value) == "authorized start failed"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert calls[-2:] == ["core.shutdown", "host.wait"]


def test_owned_process_kill_failure_does_not_replace_sanitized_start_error() -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    channel.status = CoreStatus(CoreStatusKind.FAILED, "AuthorizationInvalid")

    orchestrator._process.exit_timeout = True  # type: ignore[attr-defined]

    def fail_kill(expected_pid: int, timeout: float) -> int:
        calls.append("host.kill")
        raise RuntimeError("sentinel-kill-detail")

    orchestrator._process.terminate_owned_process_after_timeout = fail_kill  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert str(raised.value) == "authorized start did not reach Running"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert calls[-2:] == ["host.wait", "host.kill"]


def test_public_stop_is_runtime_only_and_does_not_wait_for_host_exit() -> None:
    orchestrator, calls, _, _ = build_orchestrator()

    orchestrator.stop()

    assert calls == ["core.stop"]


def test_shutdown_waits_for_exact_owned_host_normal_exit() -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    orchestrator._process.live = True  # type: ignore[attr-defined]

    result = orchestrator.shutdown()

    assert result.exit_code == 0
    assert result.emergency_fallback_used is False
    assert calls == ["core.shutdown", "host.wait"]


def test_shutdown_rejects_unowned_or_already_exited_core() -> None:
    orchestrator, calls, _, _ = build_orchestrator()

    with pytest.raises(CoreShutdownError) as raised:
        orchestrator.shutdown()

    assert raised.value.code is CoreShutdownFailureCode.CORE_ALREADY_EXITED
    assert calls == []


def test_shutdown_classifies_pipe_identity_mismatch_and_fallback() -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    orchestrator._process.live = True  # type: ignore[attr-defined]
    orchestrator._process.exit_timeout = True  # type: ignore[attr-defined]

    def mismatch(*args: object, **kwargs: object) -> CoreStatus:
        raise CoreControlError(CoreControlFailureCode.PIPE_IDENTITY_MISMATCH)

    orchestrator._channel.shutdown = mismatch  # type: ignore[method-assign]

    with pytest.raises(CoreShutdownError) as raised:
        orchestrator.shutdown()

    assert raised.value.code is CoreShutdownFailureCode.PIPE_IDENTITY_MISMATCH
    assert raised.value.emergency_fallback_used is True
    assert calls == ["host.wait", "host.kill"]


@pytest.mark.parametrize(
    ("control_code", "shutdown_code"),
    [
        (
            CoreControlFailureCode.PIPE_UNAVAILABLE,
            CoreShutdownFailureCode.PIPE_UNAVAILABLE,
        ),
        (
            CoreControlFailureCode.OPERATION_TIMEOUT,
            CoreShutdownFailureCode.SHUTDOWN_TIMEOUT,
        ),
        (
            CoreControlFailureCode.RESPONSE_REJECTED,
            CoreShutdownFailureCode.SHUTDOWN_REJECTED,
        ),
    ],
)
def test_shutdown_maps_exact_control_failure_categories(
    control_code: CoreControlFailureCode,
    shutdown_code: CoreShutdownFailureCode,
) -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    orchestrator._process.live = True  # type: ignore[attr-defined]
    orchestrator._process.exit_timeout = True  # type: ignore[attr-defined]

    def fail(*args: object, **kwargs: object) -> CoreStatus:
        raise CoreControlError(control_code)

    orchestrator._channel.shutdown = fail  # type: ignore[method-assign]

    with pytest.raises(CoreShutdownError) as raised:
        orchestrator.shutdown()

    assert raised.value.code is shutdown_code
    assert raised.value.emergency_fallback_used is True
    assert calls == ["host.wait", "host.kill"]


def test_shutdown_classifies_process_exit_timeout_and_fallback() -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    orchestrator._process.live = True  # type: ignore[attr-defined]
    orchestrator._process.exit_timeout = True  # type: ignore[attr-defined]

    with pytest.raises(CoreShutdownError) as raised:
        orchestrator.shutdown()

    assert raised.value.code is CoreShutdownFailureCode.PROCESS_EXIT_TIMEOUT
    assert raised.value.emergency_fallback_used is True
    assert calls == ["core.shutdown", "host.wait", "host.kill"]


def test_orchestrator_exposes_no_alternate_unvalidated_start_entry() -> None:
    orchestrator, _, _, _ = build_orchestrator()

    assert not hasattr(orchestrator, "_start_admitted")


def test_duplicate_start_is_rejected_without_a_second_flow() -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    assert orchestrator._single_flight.acquire(blocking=False)
    try:
        with pytest.raises(AuthorizedCoreError, match="already in progress"):
            orchestrator.start(valid_command(), valid_access_context(), Event())
    finally:
        orchestrator._single_flight.release()

    assert calls == []


def test_cancelled_attempt_does_not_start_host() -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    cancellation = Event()
    cancellation.set()

    with pytest.raises(AuthorizedCoreError, match="cancelled"):
        orchestrator.start(valid_command(), valid_access_context(), cancellation)

    assert calls == []


def test_debug_mode_equivalence_on_failure() -> None:
    from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder, NoopDiagnosticsSink
    
    # Test OFF
    orchestrator_off, _, _, _ = build_orchestrator()
    def leak_off(*args: object, **kwargs: object) -> OpaquePermit:
        raise RuntimeError("backend_error")
    orchestrator_off._permits.issue_launch_permit = leak_off  # type: ignore
    with pytest.raises(AuthorizedCoreError) as raised_off:
        orchestrator_off.start(valid_command(), valid_access_context(), Event())
    
    # Test ON
    orchestrator_on, _, _, _ = build_orchestrator()
    recorder = CoreDiagnosticsRecorder(NoopDiagnosticsSink())
    orchestrator_on._diagnostics = recorder
    def leak_on(*args: object, **kwargs: object) -> OpaquePermit:
        raise RuntimeError("backend_error")
    orchestrator_on._permits.issue_launch_permit = leak_on  # type: ignore
    with pytest.raises(AuthorizedCoreError) as raised_on:
        orchestrator_on.start(valid_command(), valid_access_context(), Event())
        
    assert raised_off.value.code == raised_on.value.code
