from __future__ import annotations

from dataclasses import dataclass
from threading import Event
import traceback

import pytest

from neko_launcher.application.errors import HeartbeatAuthInvalid
from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    AuthorizedCoreFailureDomain,
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
    RuntimeConfigurationCandidate,
    TargetBoundStartCommand,
)
from neko_launcher.application.runtime_proxy_config import (
    LaunchAuthorizationBundle,
    OpaqueRuntimeCredential,
    RuntimeProxyConfig,
)

SENTINEL_PROXY_SECRET_42 = "SENTINEL_PROXY_SECRET_42"


def _make_test_runtime_config(**overrides: object) -> RuntimeProxyConfig:
    data = {
        "schema_version": 1,
        "config_version": 18,
        "endpoint_id": "japan-vps-1",
        "host": "127.0.0.1",
        "port": 8389,
        "protocol": "shadowsocks",
        "cipher": "aes-256-gcm",
        "credential": OpaqueRuntimeCredential(SENTINEL_PROXY_SECRET_42),
        "issued_at": 1000,
        "expires_at": 1120,
    }
    data.update(overrides)
    return RuntimeProxyConfig(**data)  # type: ignore[arg-type]


def _make_test_bundle(
    *,
    permit: str = "sentinel-permit",
    runtime_config: RuntimeProxyConfig | None = None,
) -> LaunchAuthorizationBundle:
    return LaunchAuthorizationBundle(
        permit=OpaquePermit(permit),
        runtime_config=runtime_config or _make_test_runtime_config(),
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
        self.timeout: float | None = None
        self.recheck_calls: list[str] = []

    def wait_for_exact_pso2(self, timeout: float, cancellation: Event) -> Target | None:
        self.wait_calls += 1
        self.timeout = timeout
        return self.target

    def is_same_target_still_running(self, target: Target) -> bool:
        self.recheck_calls.append("target.recheck")
        return self.running and target is self.target



class FakeProcess:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.live = False
        self.exit_code = 0
        self.exit_timeout = False
        self.control_channel_timeout: float | None = None
        self.process_exit_timeout: float | None = None
        self.terminate_timeout: float | None = None

    def start_host_without_secrets(self) -> None:
        self.calls.append("host.start")
        self.live = True

    def wait_for_control_channel(self, timeout: float) -> None:
        self.control_channel_timeout = timeout
        self.calls.append("host.ready")

    def owned_process_id(self) -> int | None:
        return 4321 if self.live else None

    def wait_for_owned_process_exit(self, expected_pid: int, timeout: float) -> int:
        assert expected_pid == 4321
        self.process_exit_timeout = timeout
        self.calls.append("host.wait")
        if self.exit_timeout:
            raise TimeoutError
        self.live = False
        return self.exit_code

    def terminate_owned_process_after_timeout(self, expected_pid: int, timeout: float) -> int:
        assert expected_pid == 4321
        self.terminate_timeout = timeout
        self.calls.append("host.kill")
        self.live = False
        return 1


class FakeChannel:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.status = CoreStatus(CoreStatusKind.RUNNING)
        self.start_command: object | None = None
        self.challenge_timeout: float | None = None
        self.start_timeout: float | None = None
        self.stop_timeout: float | None = None
        self.shutdown_timeout: float | None = None
        self.candidates = (RuntimeConfigurationCandidate("profile-17", "server-42"),)
        self.validated_candidate: RuntimeConfigurationCandidate | None = None
        self.discovery_calls: list[str] = []
        self.challenges: list[CoreChallenge] = []

    def runtime_config_catalog(
        self, correlation_id: str, timeout: float
    ) -> tuple[RuntimeConfigurationCandidate, ...]:
        self.discovery_calls.append("catalog")
        return self.candidates

    def runtime_config_validate(
        self,
        candidate: RuntimeConfigurationCandidate,
        correlation_id: str,
        timeout: float,
    ) -> RuntimeConfigurationCandidate:
        self.discovery_calls.append("validate")
        self.validated_candidate = candidate
        return candidate

    def request_challenge(self, correlation_id: str, timeout: float) -> CoreChallenge:
        self.challenge_timeout = timeout
        self.calls.append("core.challenge")
        challenge = CoreChallenge(f"challenge-{len(self.challenges) + 1}")
        self.challenges.append(challenge)
        return challenge

    def start_authorized(
        self,
        command: object,
        authorization: LaunchAuthorizationBundle,
        correlation_id: str,
        timeout: float,
    ) -> CoreStatus:
        assert "sentinel-permit" not in repr(authorization)
        assert SENTINEL_PROXY_SECRET_42 not in repr(authorization)
        assert SENTINEL_PROXY_SECRET_42 not in str(authorization)
        self.start_command = command
        self.start_authorization = authorization
        self.start_timeout = timeout
        self.calls.append("core.start")
        return self.status

    def stop(self, correlation_id: str, timeout: float) -> CoreStatus:
        self.stop_timeout = timeout
        self.calls.append("core.stop")
        return CoreStatus(CoreStatusKind.STOPPED)

    def shutdown(self, correlation_id: str, timeout: float) -> CoreStatus:
        self.shutdown_timeout = timeout
        self.calls.append("core.shutdown")
        return CoreStatus(CoreStatusKind.STOPPED)


class FakeLaunchPrecondition:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.available = True
        self.timeout: float | None = None

    def require_fresh(
        self,
        session_id: str,
        installation_key_hash: str,
        timeout: float,
    ) -> None:
        self.timeout = timeout
        self.calls.append("backend.heartbeat")
        if not self.available:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.HEARTBEAT_UNAVAILABLE)


class FakePermitGateway:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.request: dict[str, object] | None = None

    def issue_launch_authorization(
        self,
        authenticated_transport: object,
        correlation_id: str,
        challenge: CoreChallenge,
        timeout: float,
    ) -> LaunchAuthorizationBundle:
        self.request = {
            "authenticated_transport": authenticated_transport,
            "correlation_id": correlation_id,
            "challenge": challenge,
            "timeout": timeout,
        }
        self.calls.append("backend.permit")
        return _make_test_bundle()

    def issue_launch_permit(
        self,
        authenticated_transport: object,
        correlation_id: str,
        challenge: CoreChallenge,
        timeout: float,
    ) -> OpaquePermit:
        bundle = self.issue_launch_authorization(
            authenticated_transport,
            correlation_id,
            challenge,
            timeout,
        )
        return bundle.permit


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
        timeouts=OrchestrationTimeouts(
            target=1.0,
            control_channel=2.0,
            challenge=3.0,
            permit=4.0,
            start_response=5.0,
            stop_response=6.0,
            shutdown_response=7.0,
            process_exit=8.0,
        ),
    )
    return orchestrator, calls, actual_detector, channel


def test_opaque_permit_never_reveals_value() -> None:
    permit = OpaquePermit("sentinel-permit")

    assert "sentinel-permit" not in repr(permit)
    assert "sentinel-permit" not in str(permit)
    assert permit.reveal_for_transport() == "sentinel-permit"
    assert permit.diagnostic_length == len("sentinel-permit")

    with pytest.raises(AuthorizedCoreError) as exc_info:
        OpaquePermit("")
    assert exc_info.value.code is AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE


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

    def leak(*args: object, **kwargs: object) -> LaunchAuthorizationBundle:
        raise RuntimeError("sentinel-backend-token")

    orchestrator._permits.issue_launch_authorization = leak  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    rendered = "".join(
        traceback.format_exception(type(raised.value), raised.value, raised.value.__traceback__)
    )
    assert "sentinel-backend-token" not in rendered


def test_permit_failure_preserves_only_sanitized_development_diagnostics() -> None:
    orchestrator, _, _, _ = build_orchestrator()

    def unavailable(*args: object, **kwargs: object) -> LaunchAuthorizationBundle:
        raise AuthorizedCoreError(
            AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE,
            diagnostic_code=PermitDiagnosticCode.PERMIT_FUNCTION_NOT_FOUND,
            diagnostic_context={
                "function": "issue_launch_permit",
                "http_status": 404,
                "access_token": "sentinel-secret",
            },
        )

    orchestrator._permits.issue_launch_authorization = unavailable  # type: ignore[method-assign]

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

    orchestrator._permits.issue_launch_authorization = spoof  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE
    assert str(raised.value) == "authorized start failed"


def test_no_target_never_starts_core_or_requests_permit() -> None:
    orchestrator, calls, _, _ = build_orchestrator(detector=FakeDetector(target=None))

    with pytest.raises(AuthorizedCoreError, match="target process is unavailable") as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.retry_safe is True
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


def test_online_heartbeat_auth_invalid_is_authoritative_and_not_retry_safe() -> None:
    def reject_auth(*args: object) -> bool:
        raise HeartbeatAuthInvalid("refresh token rejected")

    precondition = OnlineHeartbeatLaunchPrecondition(reject_auth)

    with pytest.raises(AuthorizedCoreError) as raised:
        precondition.require_fresh("session", "installation", 2.0)

    assert raised.value.code is AuthorizedCoreErrorCode.AUTHORIZATION_INVALID
    assert raised.value.auth_invalid is True
    assert raised.value.retry_safe is False
    assert precondition.last_success_monotonic is None


def test_online_heartbeat_false_is_session_inactive_and_not_retry_safe() -> None:
    precondition = OnlineHeartbeatLaunchPrecondition(lambda *args: False)

    with pytest.raises(AuthorizedCoreError) as raised:
        precondition.require_fresh("session", "installation", 2.0)

    assert raised.value.code is AuthorizedCoreErrorCode.SESSION_INACTIVE
    assert raised.value.retry_safe is False
    assert precondition.last_success_monotonic is None


def test_failed_heartbeat_does_not_advance_previous_success_timestamp() -> None:
    results = iter([True, False])
    times = iter([123.0, 456.0])
    precondition = OnlineHeartbeatLaunchPrecondition(
        lambda *args: next(results),
        monotonic=lambda: next(times),
    )
    precondition.require_fresh("session", "installation", 2.0)

    with pytest.raises(AuthorizedCoreError) as raised:
        precondition.require_fresh("session", "installation", 2.0)

    assert raised.value.code is AuthorizedCoreErrorCode.SESSION_INACTIVE
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


def test_reconnect_start_obtains_a_fresh_challenge_and_one_fresh_permit() -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    permits = orchestrator._permits

    orchestrator.start(valid_command(), valid_access_context(), Event())
    first_request = dict(permits.request)  # type: ignore[arg-type,union-attr]
    orchestrator.stop()
    orchestrator.start(valid_command(), valid_access_context(), Event())
    second_request = dict(permits.request)  # type: ignore[arg-type,union-attr]

    assert channel.challenges == [CoreChallenge("challenge-1"), CoreChallenge("challenge-2")]
    assert first_request["challenge"] == channel.challenges[0]
    assert second_request["challenge"] == channel.challenges[1]
    assert first_request["correlation_id"] != second_request["correlation_id"]
    assert calls.count("backend.permit") == 2


def test_each_operation_uses_its_independent_timeout() -> None:
    orchestrator, _, detector, channel = build_orchestrator()

    orchestrator.start(valid_command(), valid_access_context(), Event())

    process = orchestrator._process
    permits = orchestrator._permits
    assert detector.timeout == 1.0
    assert process.control_channel_timeout == 2.0  # type: ignore[attr-defined]
    assert channel.challenge_timeout == 3.0
    assert permits.request is not None  # type: ignore[attr-defined]
    assert permits.request["timeout"] == 4.0  # type: ignore[attr-defined]
    assert channel.start_timeout == 5.0

    orchestrator.stop()
    assert channel.stop_timeout == 6.0

    orchestrator.shutdown()
    assert channel.shutdown_timeout == 7.0
    assert process.process_exit_timeout == 8.0  # type: ignore[attr-defined]


def test_start_past_old_boundary_does_not_trigger_busy_shutdown_cleanup() -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    old_generic_boundary = 1.0
    simulated_core_elapsed = 2.0
    orchestrator._timeouts = OrchestrationTimeouts(
        target=1.0,
        control_channel=1.0,
        challenge=1.0,
        permit=1.0,
        start_response=4.0,
        stop_response=2.0,
        shutdown_response=2.0,
        process_exit=1.0,
    )

    original_start = channel.start_authorized

    def controlled_slow_start(*args: object, **kwargs: object) -> CoreStatus:
        timeout = args[-1]
        assert isinstance(timeout, float)
        assert simulated_core_elapsed > old_generic_boundary
        assert simulated_core_elapsed < timeout
        return original_start(*args, **kwargs)  # type: ignore[arg-type]

    channel.start_authorized = controlled_slow_start  # type: ignore[method-assign]

    status = orchestrator.start(valid_command(), valid_access_context(), Event())

    assert status.kind is CoreStatusKind.RUNNING
    assert "core.shutdown" not in calls
    assert "host.wait" not in calls
    assert "host.kill" not in calls


def test_authorized_start_diagnostics_capture_only_safe_typed_result() -> None:
    from neko_launcher.application.diagnostics import (
        CoreDiagnosticsRecorder,
        NoopDiagnosticsSink,
    )

    orchestrator, _, _, _ = build_orchestrator()
    recorder = CoreDiagnosticsRecorder(NoopDiagnosticsSink())
    orchestrator._diagnostics = recorder

    orchestrator.start(valid_command(), valid_access_context(), Event())

    snapshot = recorder.snapshot()
    assert snapshot.pid == 4321
    assert snapshot.authorized_start_elapsed_ms is not None
    assert snapshot.authorized_start_failure_category == "START_TYPED_SUCCESS"
    assert snapshot.authorized_start_core_alive is True
    assert snapshot.authorized_start_transport_outcome == "START_TYPED_SUCCESS"


def test_successful_start_records_terminal_typed_running_stage() -> None:
    from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder

    class RecordingSink:
        def __init__(self) -> None:
            self.stages: list[tuple[str, dict[str, object]]] = []

        def begin_attempt(self, attempt_id: str) -> None:
            pass

        def record_stage(self, stage: str, **kwargs: object) -> None:
            self.stages.append((stage, kwargs))

        def record_process_event(self, event: str, **kwargs: object) -> None:
            pass

        def record_exception(self, exc: Exception, stage: str) -> None:
            pass

    orchestrator, _, _, _ = build_orchestrator()
    sink = RecordingSink()
    orchestrator._diagnostics = CoreDiagnosticsRecorder(sink)

    orchestrator.start(valid_command(), valid_access_context(), Event())

    assert sink.stages[-2:] == [
        ("RUNNING_VERIFY", {}),
        ("CORE_STATUS", {"status": "CoreStatus.RUNNING"}),
    ]


def test_permit_received_stage_records_actual_length_without_revealing_permit() -> None:
    from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder

    class RecordingSink:
        def __init__(self) -> None:
            self.stages: list[tuple[str, dict[str, object]]] = []

        def begin_attempt(self, attempt_id: str) -> None:
            pass

        def record_stage(self, stage: str, **kwargs: object) -> None:
            self.stages.append((stage, kwargs))

        def record_process_event(self, event: str, **kwargs: object) -> None:
            pass

        def record_exception(self, exc: Exception, stage: str) -> None:
            pass

    orchestrator, _, _, _ = build_orchestrator()
    sink = RecordingSink()
    orchestrator._diagnostics = CoreDiagnosticsRecorder(sink)

    raw_permit_secret = "sensitive-opaque-jwt-token-string-12345678"
    orchestrator._permits.issue_launch_authorization = (  # type: ignore[method-assign]
        lambda *args, **kwargs: _make_test_bundle(permit=raw_permit_secret)
    )

    orchestrator.start(valid_command(), valid_access_context(), Event())

    permit_received_stages = [
        (stage, kwargs) for stage, kwargs in sink.stages if stage == "PERMIT_RECEIVED"
    ]
    assert len(permit_received_stages) == 1
    stage_name, kwargs = permit_received_stages[0]
    assert kwargs.get("PERMIT_RECEIVED") is True
    assert kwargs.get("PERMIT_LENGTH") == len(raw_permit_secret)
    assert kwargs.get("RUNTIME_CONFIG_VERSION") == 18
    assert raw_permit_secret not in str(kwargs)
    assert SENTINEL_PROXY_SECRET_42 not in str(kwargs)
    assert SENTINEL_PROXY_SECRET_42 not in repr(sink.stages)


def test_typed_core_start_failure_records_core_error_code_in_diagnostics() -> None:
    from neko_launcher.application.diagnostics import (
        CoreDiagnosticsRecorder,
        NoopDiagnosticsSink,
    )

    orchestrator, calls, _, channel = build_orchestrator()
    recorder = CoreDiagnosticsRecorder(NoopDiagnosticsSink())
    orchestrator._diagnostics = recorder
    channel.status = CoreStatus(CoreStatusKind.FAILED, "AuthorizationInvalid")

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.AUTHORIZATION_INVALID
    snapshot = recorder.snapshot()
    assert snapshot.authorized_start_failure_category == "START_TYPED_FAILURE"
    assert snapshot.authorized_start_core_alive is True
    assert snapshot.authorized_start_transport_outcome == "START_TYPED_FAILURE"
    assert snapshot.authorized_start_core_error_code == "AuthorizationInvalid"
    assert calls[-2:] == ["core.shutdown", "host.wait"]


def test_untrusted_core_error_code_is_dropped_from_diagnostics() -> None:
    from neko_launcher.application.diagnostics import (
        CoreDiagnosticsRecorder,
        NoopDiagnosticsSink,
    )

    orchestrator, calls, _, channel = build_orchestrator()
    recorder = CoreDiagnosticsRecorder(NoopDiagnosticsSink())
    orchestrator._diagnostics = recorder
    channel.status = CoreStatus(CoreStatusKind.FAILED, "UNTRUSTED_UNKNOWN_ERROR")

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE
    snapshot = recorder.snapshot()
    assert snapshot.authorized_start_failure_category == "START_TYPED_FAILURE"
    assert snapshot.authorized_start_core_error_code is None


def test_successful_start_has_no_core_error_code_in_diagnostics() -> None:
    from neko_launcher.application.diagnostics import (
        CoreDiagnosticsRecorder,
        NoopDiagnosticsSink,
    )

    orchestrator, calls, _, channel = build_orchestrator()
    recorder = CoreDiagnosticsRecorder(NoopDiagnosticsSink())
    orchestrator._diagnostics = recorder

    orchestrator.start(valid_command(), valid_access_context(), Event())

    snapshot = recorder.snapshot()
    assert snapshot.authorized_start_failure_category == "START_TYPED_SUCCESS"
    assert snapshot.authorized_start_core_alive is True
    assert snapshot.authorized_start_transport_outcome == "START_TYPED_SUCCESS"
    assert snapshot.authorized_start_core_error_code is None



def test_start_timeout_diagnostics_distinguish_live_core_without_response() -> None:
    from neko_launcher.application.diagnostics import (
        CoreDiagnosticsRecorder,
        NoopDiagnosticsSink,
    )

    orchestrator, calls, _, _ = build_orchestrator()
    recorder = CoreDiagnosticsRecorder(NoopDiagnosticsSink())
    orchestrator._diagnostics = recorder

    def time_out(*args: object, **kwargs: object) -> CoreStatus:
        raise CoreControlError(CoreControlFailureCode.OPERATION_TIMEOUT)

    orchestrator._channel.start_authorized = time_out  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError):
        orchestrator.start(valid_command(), valid_access_context(), Event())

    snapshot = recorder.snapshot()
    assert snapshot.authorized_start_failure_category == "START_RESPONSE_TIMEOUT"
    assert snapshot.authorized_start_core_alive is True
    assert snapshot.authorized_start_transport_outcome == "CORE_ALIVE_NO_RESPONSE"
    assert calls[-2:] == ["core.shutdown", "host.wait"]


def test_authorized_start_diagnostics_distinguish_owned_core_exit() -> None:
    from neko_launcher.application.diagnostics import (
        CoreDiagnosticsRecorder,
        NoopDiagnosticsSink,
    )

    orchestrator, calls, _, _ = build_orchestrator()
    recorder = CoreDiagnosticsRecorder(NoopDiagnosticsSink())
    orchestrator._diagnostics = recorder

    def exit_during_start(*args: object, **kwargs: object) -> CoreStatus:
        orchestrator._process.live = False  # type: ignore[attr-defined]
        raise CoreControlError(CoreControlFailureCode.PIPE_CLOSED)

    orchestrator._channel.start_authorized = exit_during_start  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError):
        orchestrator.start(valid_command(), valid_access_context(), Event())

    snapshot = recorder.snapshot()
    assert snapshot.authorized_start_failure_category == "CORE_EXITED"
    assert snapshot.authorized_start_core_alive is False
    assert snapshot.authorized_start_transport_outcome == "CORE_EXITED"
    assert calls == [
        "backend.heartbeat",
        "host.start",
        "host.ready",
        "core.challenge",
        "backend.permit",
    ]


def test_challenge_transport_failure_is_typed_safe_pre_permit_failure() -> None:
    orchestrator, calls, _, _ = build_orchestrator()

    def fail_challenge(*args: object, **kwargs: object) -> CoreChallenge:
        raise RuntimeError("transient challenge transport failure")

    orchestrator._channel.request_challenge = fail_challenge  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.CHALLENGE_UNAVAILABLE
    assert raised.value.retry_safe is True
    assert "backend.permit" not in calls
    assert calls[-2:] == ["core.shutdown", "host.wait"]


def test_replaced_session_fails_before_core_host_start() -> None:
    orchestrator, calls, _, _ = build_orchestrator()
    orchestrator._precondition.available = False  # type: ignore[attr-defined]

    with pytest.raises(AuthorizedCoreError, match="fresh heartbeat is unavailable") as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.retry_safe is True
    assert calls == ["backend.heartbeat"]


@pytest.mark.parametrize(
    "denial_code",
    [
        AuthorizedCoreErrorCode.AUTHORIZATION_INVALID,
        AuthorizedCoreErrorCode.SESSION_INACTIVE,
        AuthorizedCoreErrorCode.ENTITLEMENT_INACTIVE,
    ],
)
def test_authoritative_launch_precondition_denial_is_preserved_fail_closed(
    denial_code: AuthorizedCoreErrorCode,
) -> None:
    orchestrator, calls, _, _ = build_orchestrator()

    def deny(*args: object, **kwargs: object) -> None:
        raise AuthorizedCoreError(denial_code)

    orchestrator._precondition.require_fresh = deny  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is denial_code
    assert raised.value.retry_safe is False
    assert calls == []


def test_orchestrator_preserves_heartbeat_auth_invalid_provenance() -> None:
    orchestrator, calls, _, _ = build_orchestrator()

    def deny(*args: object, **kwargs: object) -> None:
        raise AuthorizedCoreError(
            AuthorizedCoreErrorCode.AUTHORIZATION_INVALID,
            auth_invalid=True,
        )

    orchestrator._precondition.require_fresh = deny  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.AUTHORIZATION_INVALID
    assert raised.value.auth_invalid is True
    assert calls == []


def test_core_authorization_invalid_does_not_gain_heartbeat_auth_provenance() -> None:
    orchestrator, _, _, channel = build_orchestrator()
    channel.status = CoreStatus(CoreStatusKind.FAILED, "AuthorizationInvalid")

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.AUTHORIZATION_INVALID
    assert raised.value.auth_invalid is False


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


def test_authority_request_uses_only_authenticated_transport_and_core_challenge() -> None:
    orchestrator, _, _, channel = build_orchestrator()
    permits = orchestrator._permits

    orchestrator.start(valid_command(), valid_access_context(), Event())

    assert isinstance(channel.start_command, TargetBoundStartCommand)
    assert permits.request is not None  # type: ignore[attr-defined]
    request = permits.request  # type: ignore[attr-defined]
    assert set(request) == {"authenticated_transport", "correlation_id", "challenge", "timeout"}


def test_unique_runtime_configuration_identity_is_frozen_for_runtime_start_only() -> None:
    orchestrator, calls, _, channel = build_orchestrator()

    orchestrator.start(valid_command(), valid_access_context(), Event())

    command = channel.start_command
    assert isinstance(command, TargetBoundStartCommand)
    assert (command.profile_reference, command.server_reference) == ("profile-17", "server-42")
    assert command.canonical_bytes == (
        b"protocolVersion=2\nmode=ProcessMode\nprocessName=pso2.exe\n"
        b"targetPid=42\nprofileReference=profile-17\nserverReference=server-42\n"
    )
    assert (
        command.configuration_digest
        == "ef428b54b3fcd87ff219e3d2ed45b9160bfad1f247de7c04e9cf9f7a4fd3f115"
    )
    assert channel.validated_candidate == RuntimeConfigurationCandidate("profile-17", "server-42")
    assert set(orchestrator._permits.request) == {  # type: ignore[attr-defined,arg-type]
        "authenticated_transport", "correlation_id", "challenge", "timeout"
    }
    assert channel.discovery_calls == ["catalog", "validate"]
    assert calls.index("backend.permit") < calls.index("core.start")


def test_orchestrator_order_and_target_recheck_around_authorization() -> None:
    order: list[str] = []
    orchestrator, calls, detector, channel = build_orchestrator()

    orig_req_challenge = channel.request_challenge
    def tracking_challenge(cid: str, timeout: float) -> CoreChallenge:
        order.append("core.challenge")
        return orig_req_challenge(cid, timeout)
    channel.request_challenge = tracking_challenge

    orig_issue_auth = orchestrator._permits.issue_launch_authorization
    def tracking_issue_auth(*args: object, **kwargs: object) -> LaunchAuthorizationBundle:
        order.append("backend.issue_launch_authorization")
        return orig_issue_auth(*args, **kwargs)
    orchestrator._permits.issue_launch_authorization = tracking_issue_auth  # type: ignore[method-assign]

    orig_target_check = detector.is_same_target_still_running
    def tracking_target_check(target: Target) -> bool:
        order.append("target.recheck")
        return orig_target_check(target)
    detector.is_same_target_still_running = tracking_target_check

    orig_start = channel.start_authorized
    def tracking_start(*args: object, **kwargs: object) -> CoreStatus:
        order.append("core.start")
        return orig_start(*args, **kwargs)
    channel.start_authorized = tracking_start

    status = orchestrator.start(valid_command(), valid_access_context(), Event())
    assert status.kind is CoreStatusKind.RUNNING

    # Required order:
    # 1. core.challenge
    # 2. backend.issue_launch_authorization
    # 3. target.recheck (final target identity recheck after auth and before start)
    # 4. core.start
    c_idx = order.index("core.challenge")
    auth_idx = order.index("backend.issue_launch_authorization")
    assert c_idx < auth_idx

    # Find the target.recheck that happens AFTER auth
    post_auth_rechecks = [i for i, step in enumerate(order) if step == "target.recheck" and i > auth_idx]
    assert len(post_auth_rechecks) >= 1
    start_idx = order.index("core.start")
    assert post_auth_rechecks[0] < start_idx


def test_authorization_failure_cleans_owned_host_and_never_calls_start() -> None:
    orchestrator, calls, _, channel = build_orchestrator()

    def fail_auth(*args: object, **kwargs: object) -> LaunchAuthorizationBundle:
        raise AuthorizedCoreError(
            AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE,
            diagnostic_code=PermitDiagnosticCode.PERMIT_HTTP_500,
            diagnostic_context={"http_status": 500},
        )

    orchestrator._permits.issue_launch_authorization = fail_auth  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE
    assert "core.start" not in calls
    assert calls[-2:] == ["core.shutdown", "host.wait"]


def test_runtime_config_invalid_failure_cleans_owned_host_and_never_calls_start() -> None:
    orchestrator, calls, _, channel = build_orchestrator()

    def invalid_bundle(*args: object, **kwargs: object) -> object:
        # returns an invalid object
        return object()

    orchestrator._permits.issue_launch_authorization = invalid_bundle  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE
    assert "core.start" not in calls
    assert calls[-2:] == ["core.shutdown", "host.wait"]


def test_diagnostics_records_only_runtime_config_version_never_secret() -> None:
    from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder

    class RecordingSink:
        def __init__(self) -> None:
            self.stages: list[tuple[str, dict[str, object]]] = []

        def begin_attempt(self, attempt_id: str) -> None:
            pass

        def record_stage(self, stage: str, **kwargs: object) -> None:
            self.stages.append((stage, kwargs))

        def record_process_event(self, event: str, **kwargs: object) -> None:
            pass

        def record_exception(self, exc: Exception, stage: str) -> None:
            pass

    orchestrator, _, _, _ = build_orchestrator()
    sink = RecordingSink()
    orchestrator._diagnostics = CoreDiagnosticsRecorder(sink)

    orchestrator.start(valid_command(), valid_access_context(), Event())

    recorded_stages = sink.stages
    # Verify SENTINEL_PROXY_SECRET_42 never leaked in any recorded stage
    for stage_name, kwargs in recorded_stages:
        assert SENTINEL_PROXY_SECRET_42 not in str(kwargs)
        assert SENTINEL_PROXY_SECRET_42 not in repr(kwargs)

    permit_stages = [kw for stage, kw in recorded_stages if stage == "PERMIT_RECEIVED"]
    assert len(permit_stages) == 1
    assert permit_stages[0].get("RUNTIME_CONFIG_VERSION") == 18
    assert permit_stages[0].get("PERMIT_RECEIVED") is True



@pytest.mark.parametrize(
    ("candidates", "expected_code"),
    [
        ((), AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE),
        (
            (
                RuntimeConfigurationCandidate("profile-17", "server-42"),
                RuntimeConfigurationCandidate("profile-18", "server-43"),
            ),
            AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_SELECTION_REQUIRED,
        ),
    ],
)
def test_non_unique_runtime_catalog_fails_typed_before_permit(
    candidates: tuple[RuntimeConfigurationCandidate, ...],
    expected_code: AuthorizedCoreErrorCode,
) -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    channel.candidates = candidates

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is expected_code
    assert raised.value.domain is AuthorizedCoreFailureDomain.CONFIGURATION
    assert "core.challenge" not in calls
    assert "backend.permit" not in calls


def test_runtime_configuration_validation_failure_is_unavailable_before_permit() -> None:
    orchestrator, calls, _, channel = build_orchestrator()

    def reject(*_args: object) -> RuntimeConfigurationCandidate:
        raise RuntimeError("invalid catalog attestation")

    channel.runtime_config_validate = reject  # type: ignore[method-assign]
    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE
    assert "backend.permit" not in calls


def test_target_observation_failure_is_not_reported_as_target_exit() -> None:
    orchestrator, calls, detector, _ = build_orchestrator()

    def fail_observation(target: Target) -> bool:
        raise RuntimeError("transient process observation failure")

    detector.is_same_target_still_running = fail_observation  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.PROCESS_OBSERVATION_UNAVAILABLE
    assert calls == ["backend.heartbeat"]


def test_cancellation_set_by_authorization_discards_bundle_and_cleans_owned_host() -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    cancellation = Event()
    bundle = _make_test_bundle(permit="exact-bundle-permit")

    def issue_and_cancel(*args: object, **kwargs: object) -> LaunchAuthorizationBundle:
        cancellation.set()
        return bundle

    orchestrator._permits.issue_launch_authorization = issue_and_cancel  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), cancellation)

    assert raised.value.code is AuthorizedCoreErrorCode.CANCELLED
    assert "core.start" not in calls
    assert not hasattr(channel, "start_authorization")
    assert calls[-2:] == ["core.shutdown", "host.wait"]
    rendered = str(raised.value) + repr(raised.value)
    assert "exact-bundle-permit" not in rendered
    assert SENTINEL_PROXY_SECRET_42 not in rendered


def test_exact_authorization_bundle_identity_is_preserved_to_core_start() -> None:
    orchestrator, _, _, channel = build_orchestrator()
    bundle = _make_test_bundle(permit="exact-bundle-permit")
    orchestrator._permits.issue_launch_authorization = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: bundle
    )

    orchestrator.start(valid_command(), valid_access_context(), Event())

    assert channel.start_authorization is bundle


def test_target_exit_after_permit_fails_closed_and_cleans_up() -> None:
    orchestrator, calls, detector, _ = build_orchestrator()
    original = orchestrator._permits.issue_launch_authorization

    def issue_and_exit(*args: object, **kwargs: object) -> LaunchAuthorizationBundle:
        bundle = original(*args, **kwargs)
        detector.running = False
        return bundle

    orchestrator._permits.issue_launch_authorization = issue_and_exit  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError, match="target process exited"):
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert "core.start" not in calls
    assert calls[-2:] == ["core.shutdown", "host.wait"]


@pytest.mark.parametrize(
    ("core_error", "launcher_code", "domain"),
    [
        (
            "AuthorizationRequired",
            AuthorizedCoreErrorCode.AUTHORIZATION_REQUIRED,
            AuthorizedCoreFailureDomain.AUTHORIZATION,
        ),
        (
            "AuthorizationInvalid",
            AuthorizedCoreErrorCode.AUTHORIZATION_INVALID,
            AuthorizedCoreFailureDomain.AUTHORIZATION,
        ),
        (
            "AuthorizationExpired",
            AuthorizedCoreErrorCode.AUTHORIZATION_EXPIRED,
            AuthorizedCoreFailureDomain.AUTHORIZATION,
        ),
        (
            "AuthorizationReplay",
            AuthorizedCoreErrorCode.AUTHORIZATION_REPLAY,
            AuthorizedCoreFailureDomain.AUTHORIZATION,
        ),
        (
            "AuthorizationUnavailable",
            AuthorizedCoreErrorCode.AUTHORIZATION_UNAVAILABLE,
            AuthorizedCoreFailureDomain.AUTHORIZATION,
        ),
        (
            "SessionInactive",
            AuthorizedCoreErrorCode.SESSION_INACTIVE,
            AuthorizedCoreFailureDomain.AUTHORITY,
        ),
        (
            "EntitlementInactive",
            AuthorizedCoreErrorCode.ENTITLEMENT_INACTIVE,
            AuthorizedCoreFailureDomain.AUTHORITY,
        ),
        (
            "HeartbeatStale",
            AuthorizedCoreErrorCode.HEARTBEAT_STALE,
            AuthorizedCoreFailureDomain.AUTHORITY,
        ),
        (
            "ConfigurationMismatch",
            AuthorizedCoreErrorCode.CONFIGURATION_MISMATCH,
            AuthorizedCoreFailureDomain.CONFIGURATION,
        ),
        (
            "ProcessNotFound",
            AuthorizedCoreErrorCode.TARGET_UNAVAILABLE,
            AuthorizedCoreFailureDomain.TARGET,
        ),
        (
            "ProcessExited",
            AuthorizedCoreErrorCode.TARGET_EXITED,
            AuthorizedCoreFailureDomain.TARGET,
        ),
        (
            "AlreadyRunning",
            AuthorizedCoreErrorCode.ALREADY_RUNNING,
            AuthorizedCoreFailureDomain.RUNTIME,
        ),
        (
            "ProtocolInvalid",
            AuthorizedCoreErrorCode.PROTOCOL_INVALID,
            AuthorizedCoreFailureDomain.PROTOCOL,
        ),
        (
            "StartTimeout",
            AuthorizedCoreErrorCode.START_TIMEOUT,
            AuthorizedCoreFailureDomain.RUNTIME,
        ),
        (
            "Cancelled",
            AuthorizedCoreErrorCode.CANCELLED,
            AuthorizedCoreFailureDomain.RUNTIME,
        ),
        (
            "StartFailed",
            AuthorizedCoreErrorCode.START_FAILED,
            AuthorizedCoreFailureDomain.RUNTIME,
        ),
        (
            "StopFailed",
            AuthorizedCoreErrorCode.STOP_FAILED,
            AuthorizedCoreFailureDomain.RUNTIME,
        ),
    ],
)
def test_typed_core_start_failure_preserves_safe_classification_and_cleans_up(
    core_error: str,
    launcher_code: AuthorizedCoreErrorCode,
    domain: AuthorizedCoreFailureDomain,
) -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    channel.status = CoreStatus(CoreStatusKind.FAILED, core_error)

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is launcher_code
    assert raised.value.domain is domain
    assert raised.value.retry_safe is False
    assert raised.value.code is not AuthorizedCoreErrorCode.RUNNING_NOT_REACHED
    assert calls[-2:] == ["core.shutdown", "host.wait"]


@pytest.mark.parametrize("error_code", [None, "UnknownCoreError", "raw secret detail"])
def test_missing_or_unknown_core_start_failure_fails_closed(
    error_code: str | None,
) -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    channel.status = CoreStatus(CoreStatusKind.FAILED, error_code)

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE
    assert error_code is None or error_code not in str(raised.value)
    assert calls[-2:] == ["core.shutdown", "host.wait"]


def test_running_not_reached_remains_only_for_non_failed_generic_status() -> None:
    orchestrator, calls, _, channel = build_orchestrator()
    channel.status = CoreStatus(CoreStatusKind.STOPPED)

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.RUNNING_NOT_REACHED
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

    assert raised.value.code is AuthorizedCoreErrorCode.AUTHORIZATION_INVALID
    assert raised.value.domain is AuthorizedCoreFailureDomain.AUTHORIZATION
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert calls[-2:] == ["host.wait", "host.kill"]


def test_unexpected_cleanup_adapter_failure_does_not_replace_typed_start_error() -> None:
    orchestrator, _, _, channel = build_orchestrator()
    channel.status = CoreStatus(CoreStatusKind.FAILED, "AuthorizationInvalid")
    owned_pid_calls = 0
    original_owned_process_id = orchestrator._process.owned_process_id

    def fail_during_cleanup() -> int | None:
        nonlocal owned_pid_calls
        owned_pid_calls += 1
        if owned_pid_calls == 3:
            raise RuntimeError("sentinel-cleanup-owned-pid-failure")
        return original_owned_process_id()

    orchestrator._process.owned_process_id = fail_during_cleanup  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        orchestrator.start(valid_command(), valid_access_context(), Event())

    assert raised.value.code is AuthorizedCoreErrorCode.AUTHORIZATION_INVALID
    assert raised.value.domain is AuthorizedCoreFailureDomain.AUTHORIZATION
    assert "sentinel-cleanup-owned-pid-failure" not in str(raised.value)
    assert owned_pid_calls == 3


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
        (
            CoreControlFailureCode.PIPE_CLOSED,
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

    def leak_off(*args: object, **kwargs: object) -> LaunchAuthorizationBundle:
        raise RuntimeError("backend_error")

    orchestrator_off._permits.issue_launch_authorization = leak_off  # type: ignore
    with pytest.raises(AuthorizedCoreError) as raised_off:
        orchestrator_off.start(valid_command(), valid_access_context(), Event())

    # Test ON
    orchestrator_on, _, _, _ = build_orchestrator()
    recorder = CoreDiagnosticsRecorder(NoopDiagnosticsSink())
    orchestrator_on._diagnostics = recorder

    def leak_on(*args: object, **kwargs: object) -> LaunchAuthorizationBundle:
        raise RuntimeError("backend_error")

    orchestrator_on._permits.issue_launch_authorization = leak_on  # type: ignore
    with pytest.raises(AuthorizedCoreError) as raised_on:
        orchestrator_on.start(valid_command(), valid_access_context(), Event())

    assert raised_off.value.code == raised_on.value.code
