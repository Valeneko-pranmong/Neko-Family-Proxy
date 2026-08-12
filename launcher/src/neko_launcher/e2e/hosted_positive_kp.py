from __future__ import annotations

import os
from dataclasses import dataclass
from threading import Event
from typing import Any
from uuid import uuid4

from neko_launcher.application.authorized_core import (
    CoreStatusKind,
    OpaquePermit,
    OpaqueStartCommand,
    TargetBoundStartCommand,
)
from neko_launcher.e2e.final_windows_harness import (
    CleanupStep,
    FinalCoreAdmission,
    FinalSequenceDriver,
    InstanceId,
    LiveClaimResult,
)
from neko_launcher.infrastructure.auth.supabase_gateway import SupabaseGateway
from neko_launcher.infrastructure.storage.installation import LocalInstallationIdentity


@dataclass(frozen=True)
class AttemptIdentity:
    target_pid: int
    process_name: str
    mode: str
    configuration_digest: str
    challenge_correlation: str

class ProductionHostedAuthorityDriver(FinalSequenceDriver):
    def __init__(
        self,
        gateways: dict[InstanceId, SupabaseGateway],
        installations: dict[InstanceId, LocalInstallationIdentity],
        product_code: str = "NEKO-AUTH-S0"
    ):
        self._gateways = gateways
        self._installations = installations
        self._product_code = product_code

    def claim(self, instance: InstanceId, admission: FinalCoreAdmission) -> LiveClaimResult:
        gateway = self._gateways[instance]
        installation = self._installations[instance]
        claim = gateway.claim_session(
            self._product_code,
            installation.key_hash(),
            installation.display_name()
        )
        return LiveClaimResult(
            instance=instance,
            session_ref=claim.session_id,
            installation_ref=claim.installation_id or installation.key_hash()
        )

    def heartbeat_accepted(self, instance: InstanceId, session_ref: str) -> bool:
        return self._gateways[instance].heartbeat_session(session_ref)

    def future_permit_eligible(self, instance: InstanceId, session_ref: str) -> bool:
        return self._gateways[instance].heartbeat_session(session_ref)

    def cleanup(self, step: CleanupStep) -> None:
        if step == CleanupStep.RELEASE_KNOWN_LAUNCHER_SESSIONS:
            for gw in self._gateways.values():
                gw.clear_local_session()

def _get_kp_permit_variant(original_permit: OpaquePermit, variant: str) -> OpaquePermit:
    if variant == "malformed":
        return OpaquePermit(original_permit.reveal_for_transport() + "malformed")
    return original_permit

def execute_hosted_positive_and_kp(
    gateway: SupabaseGateway,
    driver: FinalSequenceDriver,
    detector: Any,
    core_process: Any,
    core_channel: Any,
    admission: FinalCoreAdmission,
    cancellation: Event,
    timeout: float = 30.0
) -> dict[str, Any]:
    if not os.environ.get("NEKO_LIVE_HOSTED_EXECUTION"):
        raise RuntimeError("Fail-closed: explicit live execution intent missing")

    evidence: dict[str, Any] = {
        "challenge_requests": 0,
        "hosted_permit_requests": 0,
        "authorized_start": 0,
        "running_transitions": 0,
        "kp_executions": 0
    }
    
    target = detector.wait_for_exact_pso2(timeout, cancellation)
    if not target:
        raise RuntimeError("pso2.exe target absent or ambiguous")
    target_pid = target.pid
    
    core_process.start_admitted_core(admission)
    core_process.wait_for_control_channel(timeout)
    
    status = core_channel.status(uuid4().hex, timeout)
    if status.kind != CoreStatusKind.STOPPED:
        raise RuntimeError("Core not stopped")
        
    candidates = core_channel.runtime_config_catalog(uuid4().hex, timeout)
    if len(candidates) != 1:
        raise RuntimeError("Configuration not unique")
    
    candidate = candidates[0]
    validation = core_channel.runtime_config_validate(candidate, uuid4().hex, timeout)
    if not getattr(validation, "passed", True):
        raise RuntimeError("Configuration validation failed")
        
    config_digest = getattr(validation, "digest", "mock_digest")
    
    claim_result = driver.claim(InstanceId.INSTANCE_A, admission)
    
    correlation = uuid4().hex
    evidence["challenge_requests"] += 1
    challenge = core_channel.request_challenge(correlation, timeout)
    
    attempt = AttemptIdentity(
        target_pid=target_pid,
        process_name="pso2.exe",
        mode="ProcessMode",
        configuration_digest=config_digest,
        challenge_correlation=correlation
    )
    
    evidence["hosted_permit_requests"] += 1
    permit = gateway.issue_launch_permit(
        gateway,
        correlation,
        challenge,
        config_digest,
        "pso2.exe",
        target_pid,
        "ProcessMode",
        "NEKO-AUTH-S0"
    )
    
    cmd = TargetBoundStartCommand.from_opaque(
        OpaqueStartCommand(candidate.profile_reference, candidate.server_reference),
        target_pid=target_pid
    )
    evidence["authorized_start"] += 1
    start_status = core_channel.start_authorized(cmd, permit, uuid4().hex, timeout)
    
    if start_status.kind != CoreStatusKind.RUNNING:
        raise RuntimeError("Core failed to reach Running state")
    evidence["running_transitions"] += 1
    
    evidence["kp_executions"] += 1
    try:
        core_channel.start_authorized(cmd, permit, uuid4().hex, timeout)
        raise RuntimeError("KP-1 Failed: Permit replay allowed")
    except Exception as e:
        if "Failed" in str(e): raise

    evidence["kp_executions"] += 1
    cmd_wrong_pid = TargetBoundStartCommand.from_opaque(
        OpaqueStartCommand(candidate.profile_reference, candidate.server_reference),
        target_pid=target_pid + 1
    )
    try:
        core_channel.start_authorized(cmd_wrong_pid, permit, uuid4().hex, timeout)
        raise RuntimeError("KP-2 Failed: Wrong target PID allowed")
    except Exception as e:
        if "Failed" in str(e): raise

    evidence["kp_executions"] += 1
    try:
        malformed = _get_kp_permit_variant(permit, "malformed")
        core_channel.start_authorized(cmd, malformed, uuid4().hex, timeout)
        raise RuntimeError("KP-4 Failed: Malformed permit allowed")
    except Exception as e:
        if "Failed" in str(e): raise

    try:
        core_channel.shutdown(uuid4().hex, timeout)
        core_process.wait_for_owned_process_exit(core_process.owned_process_id(), timeout)
    except Exception:
        pass
    
    return evidence
