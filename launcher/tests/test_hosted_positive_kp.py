from threading import Event
from unittest.mock import Mock

import pytest

from neko_launcher.e2e.final_windows_harness import CleanupStep, FinalCoreAdmission, InstanceId
from neko_launcher.e2e.hosted_positive_kp import (
    ProductionHostedAuthorityDriver,
    execute_hosted_positive_and_kp,
)


def test_driver_claim_delegates_to_gateway():
    gateways = {InstanceId.INSTANCE_A: Mock()}
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

def test_driver_heartbeat():
    gateways = {InstanceId.INSTANCE_A: Mock()}
    gateways[InstanceId.INSTANCE_A].heartbeat_session.return_value = True
    driver = ProductionHostedAuthorityDriver(gateways, {})
    assert driver.heartbeat_accepted(InstanceId.INSTANCE_A, "sesh") is True

def test_driver_cleanup():
    gw = Mock()
    driver = ProductionHostedAuthorityDriver({"a": gw}, {})
    driver.cleanup(CleanupStep.RELEASE_KNOWN_LAUNCHER_SESSIONS)
    gw.clear_local_session.assert_called_once()

def test_execute_hosted_positive_and_kp_fails_without_env(monkeypatch):
    monkeypatch.delenv("NEKO_LIVE_HOSTED_EXECUTION", raising=False)
    with pytest.raises(RuntimeError, match="Fail-closed"):
        execute_hosted_positive_and_kp(Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), Event())

def test_execute_hosted_positive_and_kp_executes_sequence(monkeypatch):
    monkeypatch.setenv("NEKO_LIVE_HOSTED_EXECUTION", "1")
    
    gateway = Mock()
    driver = Mock()
    detector = Mock()
    detector.wait_for_exact_pso2.return_value.pid = 1234
    
    core_process = Mock()
    core_process.owned_process_id.return_value = 5678
    
    core_channel = Mock()
    status_mock = Mock()
    status_mock.kind.value = "STOPPED"
    status_mock.kind = status_mock # satisfy comparison
    core_channel.status.return_value = status_mock
    
    candidate = Mock()
    candidate.profile_reference = "profile-1"
    candidate.server_reference = "server-1"
    core_channel.runtime_config_catalog.return_value = [candidate]
    core_channel.runtime_config_validate.return_value.passed = True
    core_channel.runtime_config_validate.return_value.digest = "digest"
    
    running_status = Mock()
    # It compares kind directly in code: kind != CoreStatusKind.RUNNING
    # Since we can't easily mock Enum equality dynamically without importing it, we just let it pass
    
    class FakeStatus:
        def __init__(self, name):
            self.name = name
        @property
        def kind(self):
            class K:
                name = self.name
                value = self.name
                def __eq__(self, other):
                    return getattr(other, "name", str(other)) == self.name or str(other).endswith(self.name)
            return K()
    
    core_channel.status.return_value = FakeStatus("STOPPED")
    
    # Mock starts
    core_channel.start_authorized.side_effect = [
        FakeStatus("RUNNING"), # first valid
        Exception("Core rejected: KP-1"), # KP-1
        Exception("Core rejected: KP-2"), # KP-2
        Exception("Core rejected: KP-4"), # KP-4
    ]
    
    evidence = execute_hosted_positive_and_kp(
        gateway, driver, detector, core_process, core_channel, Mock(), Event()
    )
    
    assert evidence["kp_executions"] == 3
    assert evidence["authorized_start"] == 1
    assert evidence["running_transitions"] == 1
    assert evidence["challenge_requests"] == 1
    assert evidence["hosted_permit_requests"] == 1
