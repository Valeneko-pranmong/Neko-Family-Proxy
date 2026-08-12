from __future__ import annotations

import os
from dataclasses import dataclass
from threading import Event
from typing import Any, Protocol
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
from neko_launcher.domain.models import entitlement_is_active
import time
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

class HostedPositiveAuthority(FinalSequenceDriver, Protocol):
    def claimed_entitlement(self, instance: InstanceId) -> Any: ...
    def claimed_session(self, instance: InstanceId) -> Any: ...

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
        self._claims: dict[InstanceId, Any] = {}

    def claim(self, instance: InstanceId, admission: FinalCoreAdmission) -> LiveClaimResult:
        gateway = self._gateways[instance]
        installation = self._installations[instance]
        claim = gateway.claim_session(
            self._product_code,
            installation.key_hash,
            installation.display_name
        )
        self._sessions[instance] = claim.session_id
        self._claims[instance] = claim
        return LiveClaimResult(
            instance=instance,
            session_ref=claim.session_id,
            installation_ref=claim.installation_id or installation.key_hash
        )

    def claimed_entitlement(self, instance: InstanceId) -> Any:
        return self._claims[instance].entitlement

    def claimed_session(self, instance: InstanceId) -> Any:
        return self._claims[instance]

    def heartbeat_accepted(self, instance: InstanceId, session_ref: str) -> bool:
        return self._gateways[instance].heartbeat_session(session_ref)

    def future_permit_eligible(self, instance: InstanceId, session_ref: str) -> bool:
        # Authority-only predicate, doesn't mean full permit eligibility
        return self._gateways[instance].heartbeat_session(session_ref)

    def cleanup(self, step: CleanupStep) -> None:
        if step == CleanupStep.RELEASE_KNOWN_LAUNCHER_SESSIONS:
            for instance, gw in self._gateways.items():
                if instance in self._sessions:
                    if not gw.release_session(self._sessions[instance]):
                        raise RuntimeError("CLEANUP_FAILED")

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
        self.challenge_count = 0

    def runtime_config_catalog(self, correlation_id: str, timeout: float) -> tuple[RuntimeConfigurationCandidate, ...]:
        return self.delegate.runtime_config_catalog(correlation_id, timeout)

    def runtime_config_validate(self, candidate: RuntimeConfigurationCandidate, correlation_id: str, timeout: float) -> RuntimeConfigurationCandidate:
        return self.delegate.runtime_config_validate(candidate, correlation_id, timeout)

    def request_challenge(self, correlation_id: str, timeout: float) -> CoreChallenge:
        self.challenge_count += 1
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
    driver: HostedPositiveAuthority,
    detector: ProcessTargetDetector,
    core_process: Any,
    core_channel: CoreControlChannel,
    admission: FinalCoreAdmission,
    cancellation: Event,
    installation: Any,
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
        "jti_replay_stage": "NO"
    }

    claim = None
    recording_channel = None

    try:
        try:
            core_process.start_admitted_core(admission)
            core_process.wait_for_control_channel(timeout)
        except Exception:
            raise RuntimeError("CORE_ADMISSION_FAILED")

        try:
            user = gateway.restore_session()
            authenticated = user is not None
            if not authenticated:
                raise RuntimeError("AUTH_SESSION_UNAVAILABLE")
        except Exception as e:
            if str(e) == "AUTH_SESSION_UNAVAILABLE":
                raise
            raise RuntimeError("AUTH_SESSION_UNAVAILABLE")

        try:
            claim = driver.claim(InstanceId.INSTANCE_A, admission)
            if not driver.heartbeat_accepted(InstanceId.INSTANCE_A, claim.session_ref):
                raise RuntimeError("SESSION_CLAIM_FAILED")
        except Exception as e:
            if str(e) == "SESSION_CLAIM_FAILED":
                raise
            raise RuntimeError("SESSION_CLAIM_FAILED")

        entitlement_active = entitlement_is_active(driver.claimed_entitlement(InstanceId.INSTANCE_A))
        if not entitlement_active:
            raise RuntimeError("ENTITLEMENT_UNAVAILABLE")

        recording_gateway = RecordingPermitGateway(gateway)
        recording_channel = RecordingCoreControlChannel(core_channel)
        recording_detector = RecordingTargetDetector(detector)

        access_context = LaunchAccessContext(
            authenticated=authenticated,
            entitlement_active=entitlement_active,
            session_id=claim.session_ref,
            installation_key_hash=installation.key_hash,
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

        try:
            status = orchestrator.start(None, access_context, cancellation)
            if status.kind != CoreStatusKind.RUNNING:
                raise RuntimeError("START_DENIED")
        except Exception as e:
            if str(e) == "START_DENIED":
                raise
            raise RuntimeError("START_DENIED")

        evidence["authorized_start"] = recording_channel.start_count
        evidence["hosted_permit_requests"] = recording_gateway.issued_count
        evidence["running_transitions"] = 1
        evidence["challenge_requests"] = recording_channel.challenge_count

        permit = recording_gateway.last_permit
        cmd = recording_channel.last_start_command
        if not permit or not cmd:
            raise RuntimeError("PERMIT_REQUEST_FAILED")

        target = recording_detector.last_target
        if not target:
            raise RuntimeError("TARGET_UNAVAILABLE")

        target_pid = getattr(target, "pid", None)
        if isinstance(target_pid, bool) or not isinstance(target_pid, int) or not (1 <= target_pid <= 4294967295):
            raise RuntimeError("TARGET_UNAVAILABLE")

        if not recording_detector.is_same_target_still_running(target):
            raise RuntimeError("TARGET_UNAVAILABLE")

        # Must STOP gracefully BEFORE KP execution
        try:
            stop_status = recording_channel.stop(uuid4().hex, timeout)
            if stop_status.kind != CoreStatusKind.STOPPED:
                raise RuntimeError("CLEANUP_FAILED")
        except Exception:
            raise RuntimeError("CLEANUP_FAILED")

        # KP-1: Replay same permit
        recording_channel.request_challenge(uuid4().hex, timeout)
        evidence["challenge_requests"] = recording_channel.challenge_count
        kp1_status = recording_channel.start_authorized(cmd, permit, uuid4().hex, timeout)
        try:
            require_typed_core_denial(kp1_status, "AuthorizationInvalid")
        except Exception:
            raise RuntimeError("KP_ASSERTION_FAILED")
        evidence["kp_executions"] += 1
        evidence["same_permit_reuse_denied"] = "READY"
        evidence["jti_replay_stage"] = "NO"

        # KP-2: Wrong Target PID
        recording_channel.request_challenge(uuid4().hex, timeout)
        evidence["challenge_requests"] = recording_channel.challenge_count
        cmd_wrong_pid = TargetBoundStartCommand.from_opaque(
            OpaqueStartCommand(cmd.profile_reference, cmd.server_reference),
            target_pid=target_pid + 1
        )
        kp2_status = recording_channel.start_authorized(cmd_wrong_pid, permit, uuid4().hex, timeout)
        try:
            require_typed_core_denial(kp2_status, "ConfigurationMismatch")
        except Exception:
            raise RuntimeError("KP_ASSERTION_FAILED")
        evidence["kp_executions"] += 1

        # KP-3: Wrong Configuration (digest mismatch)
        recording_channel.request_challenge(uuid4().hex, timeout)
        evidence["challenge_requests"] = recording_channel.challenge_count
        class FakeCommand:
            profile_reference = "profile-12345"
            server_reference = "server-12345"
            target_pid = cmd.target_pid
            process_name = cmd.process_name
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
        try:
            require_typed_core_denial(kp3_status, "ConfigurationMismatch")
        except Exception:
            raise RuntimeError("KP_ASSERTION_FAILED")
        evidence["kp_executions"] += 1
        evidence["wrong_configuration_kp"] = "READY"

        # KP-4: Malformed permit (actually Tampered)
        recording_channel.request_challenge(uuid4().hex, timeout)
        evidence["challenge_requests"] = recording_channel.challenge_count
        malformed = _get_kp_permit_variant(permit, "malformed")
        kp4_status = recording_channel.start_authorized(cmd, malformed, uuid4().hex, timeout)
        try:
            require_typed_core_denial(kp4_status, "AuthorizationInvalid")
        except Exception:
            raise RuntimeError("KP_ASSERTION_FAILED")
        evidence["kp_executions"] += 1
        evidence["malformed_rejection_layer"] = "PERMIT_VERIFIER"

        # KP-5: Real Expired permit proof
        start_wait = time.monotonic()
        time.sleep(35)
        elapsed = time.monotonic() - start_wait
        if elapsed < 30.0:
            raise RuntimeError("EXPIRY_WAIT_MONOTONIC_PROVEN FAILED")

        recording_channel.request_challenge(uuid4().hex, timeout)
        evidence["challenge_requests"] = recording_channel.challenge_count
        kp5_status = recording_channel.start_authorized(cmd, permit, uuid4().hex, timeout)
        try:
            require_typed_core_denial(kp5_status, "AuthorizationExpired")
        except Exception:
            raise RuntimeError("KP_ASSERTION_FAILED")
        evidence["kp_executions"] += 1
        evidence["expired_permit_proof"] = "READY"
        evidence["EXPIRY_WAIT_MONOTONIC_PROVEN"] = "YES"

    finally:
        core_cleanup_failed = False
        session_cleanup_failed = False

        try:
            expected_pid = core_process.owned_process_id()
            if expected_pid is not None:
                channel = recording_channel or core_channel

                try:
                    status = channel.status(uuid4().hex, timeout)
                    if status and status.kind == CoreStatusKind.RUNNING:
                        channel.stop(uuid4().hex, timeout)
                except Exception:
                    pass

                stop_status = channel.shutdown(uuid4().hex, timeout)
                if stop_status.kind != CoreStatusKind.STOPPED:
                    core_cleanup_failed = True

                code = core_process.wait_for_owned_process_exit(expected_pid, timeout)
                if code != 0:
                    core_cleanup_failed = True

                if core_process.owned_process_id() is not None:
                    core_cleanup_failed = True
        except Exception:
            core_cleanup_failed = True

        try:
            if claim and claim.session_ref:
                driver.cleanup(CleanupStep.RELEASE_KNOWN_LAUNCHER_SESSIONS)
        except Exception:
            session_cleanup_failed = True

        if core_cleanup_failed or session_cleanup_failed:
            raise RuntimeError("CLEANUP_FAILED")

    return evidence
