from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import create_autospec
from unittest.mock import Mock

from neko_launcher.application.authorized_core import (
    CoreChallenge,
    CoreControlChannel,
    CoreStatus,
    CoreStatusKind,
    LaunchPermitGateway,
    OpaquePermit,
    RuntimeConfigurationCandidate,
)
from neko_launcher.domain.models import Entitlement, EntitlementStatus
from neko_launcher.e2e.final_windows_harness import InstanceId, LiveClaimResult
from neko_launcher.e2e.hosted_positive_kp import (
    RecordingPermitGateway,
    execute_hosted_positive_and_kp,
)


def test_recording_permit_gateway_delegates_only_lite_arguments() -> None:
    delegate = create_autospec(LaunchPermitGateway)
    delegate.issue_launch_permit.return_value = OpaquePermit("permit")
    gateway = RecordingPermitGateway(delegate)
    challenge = CoreChallenge("A" * 43)

    result = gateway.issue_launch_permit(
        authenticated_transport="transport",
        correlation_id="0123456789abcdef0123456789abcdef",
        challenge=challenge,
        timeout=10.0,
    )

    assert result.reveal_for_transport() == "permit"
    assert gateway.issued_count == 1
    delegate.issue_launch_permit.assert_called_once_with(
        "transport",
        "0123456789abcdef0123456789abcdef",
        challenge,
        10.0,
    )


def test_execute_hosted_lite_sequence_runs_only_challenge_bound_negatives(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEKO_LIVE_HOSTED_EXECUTION", "YES-I-UNDERSTAND")

    gateway = Mock()
    gateway.restore_session.return_value = object()
    gateway.issue_launch_permit.return_value = OpaquePermit("permit")

    driver = Mock()
    driver.claim.return_value = LiveClaimResult(
        instance=InstanceId.INSTANCE_A,
        session_ref="session-ref",
        installation_ref="installation-ref",
    )
    driver.heartbeat_accepted.return_value = True
    driver.claimed_entitlement.return_value = Entitlement(
        product_code="neko-family-proxy",
        status=EntitlementStatus.ACTIVE,
        valid_until=datetime.now(UTC) + timedelta(days=1),
        max_devices=1,
    )

    target = SimpleNamespace(pid=4242)
    detector = Mock()
    detector.wait_for_exact_pso2.return_value = target
    detector.is_same_target_still_running.return_value = True

    process_alive = True
    core_process = Mock()
    core_process.owned_process_id.side_effect = lambda: 5678 if process_alive else None

    def mark_exited(*_args, **_kwargs) -> int:
        nonlocal process_alive
        process_alive = False
        return 0

    core_process.wait_for_owned_process_exit.side_effect = mark_exited

    channel = create_autospec(CoreControlChannel)
    candidate = RuntimeConfigurationCandidate("profile-0", "server-0")
    channel.runtime_config_catalog.return_value = (candidate,)
    channel.runtime_config_validate.return_value = candidate
    channel.request_challenge.return_value = CoreChallenge("A" * 43)
    channel.start_authorized.side_effect = [
        CoreStatus(CoreStatusKind.RUNNING),
        CoreStatus(CoreStatusKind.FAILED, "AuthorizationInvalid"),
        CoreStatus(CoreStatusKind.FAILED, "AuthorizationInvalid"),
        CoreStatus(CoreStatusKind.FAILED, "AuthorizationExpired"),
    ]
    channel.stop.return_value = CoreStatus(CoreStatusKind.STOPPED)
    channel.status.return_value = CoreStatus(CoreStatusKind.STOPPED)
    channel.shutdown.return_value = CoreStatus(CoreStatusKind.STOPPED)

    monotonic_values = iter((0.0, 35.0))
    monkeypatch.setattr(
        "neko_launcher.e2e.hosted_positive_kp.time.monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr("neko_launcher.e2e.hosted_positive_kp.time.sleep", lambda _value: None)

    evidence = execute_hosted_positive_and_kp(
        gateway,
        driver,
        detector,
        core_process,
        channel,
        Mock(),
        Event(),
        SimpleNamespace(key_hash="a" * 64),
    )

    assert evidence["kp_executions"] == 3
    assert evidence["same_permit_new_challenge_denied"] == "PASS"
    assert evidence["tampered_permit_denied"] == "PASS"
    assert evidence["expired_permit_denied"] == "PASS"
    assert evidence["jti_replay_stage"] == "NO"
    assert channel.start_authorized.call_count == 4
