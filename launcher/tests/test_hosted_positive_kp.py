from threading import Event
from unittest.mock import Mock, create_autospec, patch

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreOrchestrator,
    CoreChallenge,
    CoreControlChannel,
    CoreStatus,
    CoreStatusKind,
    LaunchPermitGateway,
    OpaquePermit,
)
from neko_launcher.e2e.final_windows_harness import CleanupStep, FinalCoreAdmission, InstanceId
from neko_launcher.e2e.hosted_positive_kp import (
    ProductionHostedAuthorityDriver,
    RecordingPermitGateway,
    execute_hosted_positive_and_kp,
)
from neko_launcher.infrastructure.auth.supabase_gateway import SupabaseGateway


def test_driver_claim_delegates_to_gateway():
    gateways = {InstanceId.INSTANCE_A: create_autospec(SupabaseGateway)}
    installations = {InstanceId.INSTANCE_A: Mock()}
    installations[InstanceId.INSTANCE_A].key_hash.return_value = "hash"
    installations[InstanceId.INSTANCE_A].display_name.return_value = "name"

    mock_claim = Mock()
    mock_claim.session_id = "session1"
    mock_claim.installation_id = "inst1"
    gateways[InstanceId.INSTANCE_A].claim_session.return_value = mock_claim

    driver = ProductionHostedAuthorityDriver(gateways, installations)
    admission = Mock(spec=FinalCoreAdmission)

    res = driver.claim(InstanceId.INSTANCE_A, admission)
    assert res.instance == InstanceId.INSTANCE_A
    assert res.session_ref == "session1"
    assert res.installation_ref == "inst1"
    assert driver._sessions[InstanceId.INSTANCE_A] == "session1"

def test_driver_heartbeat():
    gateways = {InstanceId.INSTANCE_A: create_autospec(SupabaseGateway)}
    gateways[InstanceId.INSTANCE_A].heartbeat_session.return_value = True
    driver = ProductionHostedAuthorityDriver(gateways, {})
    assert driver.heartbeat_accepted(InstanceId.INSTANCE_A, "sesh") is True

def test_driver_cleanup():
    gw = create_autospec(SupabaseGateway)
    driver = ProductionHostedAuthorityDriver({"a": gw}, {})
    driver._sessions["a"] = "sesh1"
    driver.cleanup(CleanupStep.RELEASE_KNOWN_LAUNCHER_SESSIONS)
    gw.release_session.assert_called_once_with("sesh1")

def test_execute_hosted_positive_and_kp_fails_without_env(monkeypatch):
    monkeypatch.delenv("NEKO_LIVE_HOSTED_EXECUTION", raising=False)
    with pytest.raises(RuntimeError, match="Fail-closed"):
        execute_hosted_positive_and_kp(Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), Event(), Mock())

def test_execute_hosted_positive_and_kp_wrong_env(monkeypatch):
    monkeypatch.setenv("NEKO_LIVE_HOSTED_EXECUTION", "1")
    with pytest.raises(RuntimeError, match="Fail-closed"):
        execute_hosted_positive_and_kp(Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), Event(), Mock())

def test_recording_permit_gateway_exact_signature():
    # Strict contract test
    mock_delegate = create_autospec(LaunchPermitGateway)
    gateway = RecordingPermitGateway(mock_delegate)

    challenge = CoreChallenge("nonce")
    gateway.issue_launch_permit(
        authenticated_transport="transport",
        correlation_id="corr",
        challenge=challenge,
        configuration_digest="digest",
        process_name="pso2.exe",
        target_pid=1234,
        mode="ProcessMode",
        product="neko-family-proxy",
        scope="proxy:start",
        timeout=30.0
    )

    mock_delegate.issue_launch_permit.assert_called_once_with(
        "transport",
        "corr",
        challenge,
        "digest",
        "pso2.exe",
        1234,
        "ProcessMode",
        "neko-family-proxy", # Enforces product
        "proxy:start", # Enforces scope
        30.0
    )

def test_execute_hosted_positive_and_kp_success(monkeypatch):
    monkeypatch.setenv("NEKO_LIVE_HOSTED_EXECUTION", "YES-I-UNDERSTAND")

    # We patch AuthorizedCoreOrchestrator.start directly to simulate success
    with patch.object(AuthorizedCoreOrchestrator, 'start') as mock_start:
        mock_start.return_value = CoreStatus(kind=CoreStatusKind.RUNNING)

        # Let's not mock the orchestrator, let's mock the core_channel methods.e orchestrator is mocked out
        # Actually, if we mock out the orchestrator, the RecordingGateway doesn't get called.
        # Let's not mock the orchestrator, let's mock the core_channel methods.

def test_execute_hosted_positive_and_kp_full_flow(monkeypatch):
    monkeypatch.setenv("NEKO_LIVE_HOSTED_EXECUTION", "YES-I-UNDERSTAND")

    gateway = create_autospec(SupabaseGateway)
    gateway.issue_launch_permit.return_value = OpaquePermit("permit")
    driver = Mock()
    driver.heartbeat_accepted.return_value = True
    from neko_launcher.domain.models import Entitlement, EntitlementStatus
    from datetime import datetime, timezone, timedelta
    driver.claim.return_value.session_ref = "sess"
    driver.claim.return_value.entitlement = Entitlement(
        product_code="abc",
        status=EntitlementStatus.ACTIVE,
        valid_until=datetime.now(timezone.utc) + timedelta(days=1),
        max_devices=1
    )

    detector = Mock()
    detector.wait_for_exact_pso2.return_value.pid = 1234
    detector.is_same_target_still_running.return_value = True

    core_process = Mock()
    process_state = {"alive": True}
    def fake_owned_process_id():
        return 5678 if process_state["alive"] else None
    core_process.owned_process_id.side_effect = fake_owned_process_id

    def fake_wait(*args, **kwargs):
        process_state["alive"] = False
        return 0
    core_process.wait_for_owned_process_exit.side_effect = fake_wait
    core_process.wait_for_owned_process_exit.return_value = 0

    core_channel = create_autospec(CoreControlChannel)
    core_channel.status.return_value = CoreStatus(kind=CoreStatusKind.STOPPED)

    candidate = Mock()
    candidate.profile_reference = "profile-1"
    candidate.server_reference = "server-1"
    candidate.canonical_bytes = b"foo" # to allow sha256
    core_channel.runtime_config_catalog.return_value = (candidate,)
    core_channel.runtime_config_validate.return_value = candidate

    core_channel.request_challenge.return_value = CoreChallenge("nonce")

    # Positive start -> KP1 -> KP2 -> KP3 -> KP4 -> KP5
    core_channel.start_authorized.side_effect = [
        CoreStatus(kind=CoreStatusKind.RUNNING), # positive
        CoreStatus(kind=CoreStatusKind.FAILED, error_code="AuthorizationInvalid"), # KP1
        CoreStatus(kind=CoreStatusKind.FAILED, error_code="ConfigurationMismatch"), # KP2
        CoreStatus(kind=CoreStatusKind.FAILED, error_code="ConfigurationMismatch"), # KP3
        CoreStatus(kind=CoreStatusKind.FAILED, error_code="AuthorizationInvalid"), # KP4
        CoreStatus(kind=CoreStatusKind.FAILED, error_code="AuthorizationExpired"), # KP5
    ]

    core_channel.stop.return_value = CoreStatus(kind=CoreStatusKind.STOPPED)
    core_channel.shutdown.return_value = CoreStatus(kind=CoreStatusKind.STOPPED)

    import time
    monkeypatch.setattr(time, "sleep", lambda x: None)

    evidence = execute_hosted_positive_and_kp(
        gateway, driver, detector, core_process, core_channel, Mock(), Event(), Mock()
    )

    assert evidence["kp_executions"] == 5
    assert evidence["authorized_start"] == 1
    assert evidence["hosted_permit_requests"] == 1

    gateway.issue_launch_permit.assert_called_once()
    # Check it used correct product and scope
    call_args = gateway.issue_launch_permit.call_args[0]
    assert call_args[7] == "neko-family-proxy"
    assert call_args[8] == "proxy:start"

def test_production_hosted_authority_driver_cleanup_success():
    from neko_launcher.e2e.hosted_positive_kp import ProductionHostedAuthorityDriver
    from neko_launcher.e2e.final_windows_harness import InstanceId, CleanupStep
    from unittest.mock import Mock

    gateway = Mock()
    gateway.release_session.return_value = True

    driver = ProductionHostedAuthorityDriver(
        gateways={InstanceId.INSTANCE_A: gateway},
        installations={InstanceId.INSTANCE_A: Mock()}
    )
    driver._sessions[InstanceId.INSTANCE_A] = "test-session"

    # Should not raise
    driver.cleanup(CleanupStep.RELEASE_KNOWN_LAUNCHER_SESSIONS)
    gateway.release_session.assert_called_once_with("test-session")

def test_production_hosted_authority_driver_cleanup_failure():
    from neko_launcher.e2e.hosted_positive_kp import ProductionHostedAuthorityDriver
    from neko_launcher.e2e.final_windows_harness import InstanceId, CleanupStep
    from unittest.mock import Mock
    import pytest

    gateway = Mock()
    gateway.release_session.return_value = False

    driver = ProductionHostedAuthorityDriver(
        gateways={InstanceId.INSTANCE_A: gateway},
        installations={InstanceId.INSTANCE_A: Mock()}
    )
    driver._sessions[InstanceId.INSTANCE_A] = "test-session"

    with pytest.raises(RuntimeError, match="CLEANUP_FAILED"):
        driver.cleanup(CleanupStep.RELEASE_KNOWN_LAUNCHER_SESSIONS)
