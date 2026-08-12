from __future__ import annotations

import os
from dataclasses import dataclass
from threading import Event
from typing import Any
from uuid import uuid4

from neko_launcher.application.authorized_core import (
    AuthorizedCoreOrchestrator,
    CoreChallenge,
    CoreControlChannel,
    CoreStatus,
    CoreStatusKind,
    LaunchAccessContext,
    LaunchPermitGateway,
    OnlineHeartbeatLaunchPrecondition,
    OpaquePermit,
    OpaqueStartCommand,
    OrchestrationTimeouts,
    ProcessTargetDetector,
    RuntimeConfigurationCandidate,
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
        product_code: str = "neko-family-proxy",
        scope: str = "proxy:start"
    ):
        self._gateways = gateways
        self._installations = installations
        self._product_code = product_code
        self._scope = scope
        self._sessions: dict[InstanceId, str] = {}

    def claim(self, instance: InstanceId, admission: FinalCoreAdmission) -> LiveClaimResult:
        gateway = self._gateways[instance]
        installation = self._installations[instance]
        claim = gateway.claim_session(
            self._product_code,
            installation.key_hash,
            installation.display_name
        )
        self._sessions[instance] = claim.session_id
        return LiveClaimResult(
            instance=instance,
            session_ref=claim.session_id,
            installation_ref=claim.installation_id or installation.key_hash
        )

    def heartbeat_accepted(self, instance: InstanceId, session_ref: str) -> bool:
        return self._gateways[instance].heartbeat_session(session_ref)

    def future_permit_eligible(self, instance: InstanceId, session_ref: str) -> bool:
        # Authority-only predicate, doesn't mean full permit eligibility
        return self._gateways[instance].heartbeat_session(session_ref)

    def cleanup(self, step: CleanupStep) -> None:
        if step == CleanupStep.RELEASE_KNOWN_LAUNCHER_SESSIONS:
            for instance, gw in self._gateways.items():
                if instance in self._sessions:
                    gw.release_session(self._sessions[instance])

class RecordingPermitGateway(LaunchPermitGateway):
    def __init__(self, delegate: LaunchPermitGateway, product: str = "neko-family-proxy", scope: str = "proxy:start"):
        self.delegate = delegate
        self.last_permit: OpaquePermit | None = None
        self.issued_count = 0
        self.product = product
        self.scope = scope

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
        if product != self.product:
            raise ValueError(f"Expected product {self.product}, got {product}")
        if scope != self.scope:
            raise ValueError(f"Expected scope {self.scope}, got {scope}")

        if self.issued_count >= 1:
            raise RuntimeError("Permit already issued (No automatic positive permit retry)")

        self.issued_count += 1
        permit = self.delegate.issue_launch_permit(
            authenticated_transport,
            correlation_id,
            challenge,
            configuration_digest,
            process_name,
            target_pid,
            mode,
            product, # Delegate exactly what was received and validated
            scope,
            timeout,
        )
        self.last_permit = permit
        return permit

class RecordingCoreControlChannel(CoreControlChannel):
    def __init__(self, delegate: CoreControlChannel):
        self.delegate = delegate
        self.last_start_command: TargetBoundStartCommand | None = None
        self.start_count = 0

    def runtime_config_catalog(self, correlation_id: str, timeout: float) -> tuple[RuntimeConfigurationCandidate, ...]:
        return self.delegate.runtime_config_catalog(correlation_id, timeout)

    def runtime_config_validate(self, candidate: RuntimeConfigurationCandidate, correlation_id: str, timeout: float) -> RuntimeConfigurationCandidate:
        return self.delegate.runtime_config_validate(candidate, correlation_id, timeout)

    def request_challenge(self, correlation_id: str, timeout: float) -> CoreChallenge:
        return self.delegate.request_challenge(correlation_id, timeout)

    def start_authorized(self, command: object, permit: OpaquePermit, correlation_id: str, timeout: float) -> CoreStatus:
        if self.start_count == 0 and isinstance(command, TargetBoundStartCommand):
            self.last_start_command = command
        self.start_count += 1
        return self.delegate.start_authorized(command, permit, correlation_id, timeout)

    def stop(self, correlation_id: str, timeout: float) -> CoreStatus:
        return self.delegate.stop(correlation_id, timeout)

    def status(self, correlation_id: str, timeout: float) -> CoreStatus:
        return self.delegate.status(correlation_id, timeout)

    def shutdown(self, correlation_id: str, timeout: float) -> CoreStatus:
        return self.delegate.shutdown(correlation_id, timeout)

def require_typed_core_denial(status: CoreStatus, expected_error_code: str | None = None) -> None:
    if status.kind == CoreStatusKind.RUNNING:
        raise RuntimeError("KP Failed: Expected denial, but reached RUNNING")
    if status.kind != CoreStatusKind.FAILED:
        raise RuntimeError(f"KP Failed: Expected FAILED status, got {status.kind}")
    if expected_error_code and getattr(status, "error_code", None) != expected_error_code:
        raise RuntimeError(f"KP Failed: Expected error code {expected_error_code}, got {getattr(status, 'error_code', None)}")

class RecordingTargetDetector(ProcessTargetDetector):
    def __init__(self, delegate: ProcessTargetDetector):
        self.delegate = delegate
        self.last_target = None
        self.detections = 0
        self.rechecks = 0

    def wait_for_exact_pso2(self, timeout: float, cancellation: Event) -> Any | None:
        target = self.delegate.wait_for_exact_pso2(timeout, cancellation)
        if target:
            if self.last_target is None:
                self.last_target = target
            self.detections += 1
        return target

    def is_same_target_still_running(self, target: Any) -> bool:
        self.rechecks += 1
        return self.delegate.is_same_target_still_running(target)

def _get_kp_permit_variant(original_permit: OpaquePermit, variant: str) -> OpaquePermit:
    if variant == "malformed":
        return OpaquePermit(original_permit.reveal_for_transport() + "malformed")
    if variant == "expired":
        return OpaquePermit(original_permit.reveal_for_transport() + "expired")
    return original_permit

def execute_hosted_positive_and_kp(
    gateway: SupabaseGateway,
    driver: FinalSequenceDriver,
    detector: ProcessTargetDetector,
    core_process: Any,
    core_channel: CoreControlChannel,
    admission: FinalCoreAdmission,
    cancellation: Event,
    timeout: float = 30.0
) -> dict[str, Any]:
    if os.environ.get("NEKO_LIVE_HOSTED_EXECUTION") != "YES-I-UNDERSTAND":
        raise RuntimeError("Fail-closed: explicit live execution intent missing or incorrect")

    evidence: dict[str, Any] = {
        "challenge_requests": 0,
        "hosted_permit_requests": 0,
        "authorized_start": 0,
        "running_transitions": 0,
        "kp_executions": 0,
        "jti_replay_stage": "NOT_REACHABLE_BY_ONE_USE_CHALLENGE"
    }

    # Pre-admit exact frozen Core
    core_process.start_admitted_core(admission)
    core_process.wait_for_control_channel(timeout)

    # Check Auth Session
    user = gateway.restore_session()
    if not user:
        raise RuntimeError("Live execution failed: No authenticated saved session restored")

    # Claim session (Authority)
    claim = driver.claim(InstanceId.INSTANCE_A, admission)
    if not driver.heartbeat_accepted(InstanceId.INSTANCE_A, claim.session_ref):
        raise RuntimeError("Heartbeat rejected")

    recording_gateway = RecordingPermitGateway(gateway)
    recording_channel = RecordingCoreControlChannel(core_channel)
    recording_detector = RecordingTargetDetector(detector)

    access_context = LaunchAccessContext(
        authenticated=True,
        entitlement_active=True,
        session_id=claim.session_ref,
        installation_key_hash=claim.installation_ref,
        authenticated_transport=gateway
    )
    precondition = OnlineHeartbeatLaunchPrecondition(lambda sid, hash, t: driver.heartbeat_accepted(InstanceId.INSTANCE_A, sid))

    timeouts = OrchestrationTimeouts(timeout, timeout, timeout, timeout, timeout, timeout, timeout, timeout)

    orchestrator = AuthorizedCoreOrchestrator(
        process=core_process,
        channel=recording_channel,
        permits=recording_gateway,
        precondition=precondition,
        detector=recording_detector,
        timeouts=timeouts,
    )

    # Positive execution
    status = orchestrator.start(None, access_context, cancellation)

    if status.kind != CoreStatusKind.RUNNING:
        raise RuntimeError("Core failed to reach Running state")

    evidence["authorized_start"] = recording_channel.start_count
    evidence["hosted_permit_requests"] = recording_gateway.issued_count
    evidence["running_transitions"] = 1
    evidence["challenge_requests"] = 1 # Orchestrator did it

    permit = recording_gateway.last_permit
    cmd = recording_channel.last_start_command

    if not permit or not cmd:
        raise RuntimeError("Failed to capture permit or command from positive flow")

    target = recording_detector.last_target
    if not target:
        raise RuntimeError("No target recorded")
    target_pid = getattr(target, "pid", 1)

    # Recheck target after positive START
    if not recording_detector.is_same_target_still_running(target):
        raise RuntimeError("pso2.exe target exited early")

    # KP-1: Replay same permit
    kp1_status = recording_channel.start_authorized(cmd, permit, uuid4().hex, timeout)
    require_typed_core_denial(kp1_status, "AuthorizationReplay")
    evidence["kp_executions"] += 1
    evidence["same_permit_reuse_denied"] = "READY"
    evidence["jti_replay_stage"] = "NO"

    # KP-2: Wrong Target PID
    cmd_wrong_pid = TargetBoundStartCommand.from_opaque(
        OpaqueStartCommand(cmd.profile_reference, cmd.server_reference),
        target_pid=target_pid + 1
    )
    kp2_status = recording_channel.start_authorized(cmd_wrong_pid, permit, uuid4().hex, timeout)
    require_typed_core_denial(kp2_status, "ConfigurationMismatch")
    evidence["kp_executions"] += 1

    # KP-3: Wrong Configuration (digest mismatch)
    class FakeCommand:
        profile_reference = cmd.profile_reference
        server_reference = cmd.server_reference
        target_pid = cmd.target_pid
        process_name = "wrong.exe"
        mode = cmd.mode

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
            from hashlib import sha256
            return sha256(self.canonical_bytes).hexdigest()

    cmd_wrong_config = FakeCommand()
    kp3_status = recording_channel.start_authorized(cmd_wrong_config, permit, uuid4().hex, timeout)
    require_typed_core_denial(kp3_status, "ConfigurationMismatch")
    evidence["kp_executions"] += 1
    evidence["wrong_configuration_kp"] = "READY"

    # KP-4: Malformed permit
    malformed = _get_kp_permit_variant(permit, "malformed")
    kp4_status = recording_channel.start_authorized(cmd, malformed, uuid4().hex, timeout)
    require_typed_core_denial(kp4_status, "AuthorizationInvalid")
    evidence["kp_executions"] += 1

    # KP-5: Expired permit proof
    # We cannot forge expiration without mutating the signed permit,
    # and we cannot wait for real expiration because the challenge was already consumed.
    evidence["expired_permit_proof"] = "NOT_REACHABLE_FROM_CONSUMED_POSITIVE"

    # Cleanup must fail closed
    stop_status = recording_channel.stop(uuid4().hex, timeout)
    if stop_status.kind != CoreStatusKind.STOPPED:
        raise RuntimeError("Core failed to STOP gracefully")

    shutdown_status = recording_channel.shutdown(uuid4().hex, timeout)
    if shutdown_status.kind != CoreStatusKind.STOPPED:
        raise RuntimeError("Core failed to SHUTDOWN gracefully")

    code = core_process.wait_for_owned_process_exit(core_process.owned_process_id(), timeout)
    if code != 0:
        raise RuntimeError(f"Core exited with non-zero code: {code}")

    if core_process.owned_process_id() is not None:
        raise RuntimeError("Orphan core process detected")

    return evidence
