from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

EXPECTED_LAUNCH_STAGES = (
    "GAME_PROCESS_DETECTED",
    "PROXY_START_REQUESTED",
    "COMMAND_VALIDATE",
    "ACCESS_CONTEXT_VALIDATE",
    "TARGET_WAIT",
    "HOST_START",
    "CONTROL_CHANNEL_WAIT",
    "RUNTIME_CONFIG_CATALOG",
    "RUNTIME_CONFIG_VALIDATE",
    "TARGET_RECHECK",
    "CHALLENGE_REQUEST",
    "TARGET_BIND",
    "PERMIT_REQUEST",
    "AUTHORIZED_START",
    "RUNNING_VERIFY",
)
EXPECTED_FINAL_CORE_STATUS = "CoreStatus.RUNNING"
CRITICAL_CORE_DLL_NAMES = frozenset(
    {
        "NekoProxyCore.dll",
        "NekoProxyCore.Core.dll",
        "NekoProxyCore.Legacy.dll",
        "NekoProxyCore.Windows.dll",
        "Netch.dll",
    }
)


class InstanceId(str, Enum):
    INSTANCE_A = "INSTANCE_A"
    INSTANCE_B = "INSTANCE_B"
    INSTANCE_C = "INSTANCE_C"


class RuntimeCatalogState(str, Enum):
    EMPTY = "EMPTY"
    UNIQUE = "UNIQUE"
    MULTIPLE = "MULTIPLE"


class FailureDomain(str, Enum):
    AUTHORITY = "AUTHORITY"
    AUTHORIZATION = "AUTHORIZATION"
    CONFIGURATION = "CONFIGURATION"


class AuthorityState(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    INACTIVE = "INACTIVE"


class CleanupStep(str, Enum):
    SHUTDOWN_EXACT_OWNED_CORES = "SHUTDOWN_EXACT_OWNED_CORES"
    RELEASE_KNOWN_LAUNCHER_SESSIONS = "RELEASE_KNOWN_LAUNCHER_SESSIONS"
    CLEAR_INSTANCE_LOCAL_AUTH = "CLEAR_INSTANCE_LOCAL_AUTH"
    DELETE_TEST_RECOVERY_RECORDS = "DELETE_TEST_RECOVERY_RECORDS"
    DELETE_TEST_LAUNCHER_SESSIONS = "DELETE_TEST_LAUNCHER_SESSIONS"
    DELETE_TEST_INSTALLATIONS = "DELETE_TEST_INSTALLATIONS"
    REVOKE_TEST_ENTITLEMENT = "REVOKE_TEST_ENTITLEMENT"
    DELETE_DISPOSABLE_USER = "DELETE_DISPOSABLE_USER"
    REMOVE_INSTANCE_TEMP_STATE = "REMOVE_INSTANCE_TEMP_STATE"
    REMOVE_SAFE_TEST_LOGS = "REMOVE_SAFE_TEST_LOGS"


@dataclass(frozen=True)
class SafeOpaqueId:
    kind: str
    digest: str

    @classmethod
    def from_uuid(cls, kind: str, value: str, *, run_salt: bytes) -> SafeOpaqueId:
        if re.fullmatch(r"[a-z][a-z0-9_]{0,31}", kind) is None:
            raise ValueError("opaque identifier kind is invalid")
        if not run_salt:
            raise ValueError("run salt is required")
        try:
            normalized = str(UUID(value))
        except (AttributeError, TypeError, ValueError):
            raise ValueError("identifier must be a UUID") from None
        digest = hashlib.sha256(
            run_salt + b"\0" + normalized.encode("ascii")
        ).hexdigest()[:16]
        return cls(kind=kind, digest=digest)

    def __str__(self) -> str:
        return f"{self.kind}_{self.digest}"

    __repr__ = __str__


@dataclass(frozen=True)
class AuthorityLossMetrics:
    replacement_to_authority_invalidation_ms: int
    authority_invalidation_to_core_exit_ms: int
    shutdown_request_to_core_exit_ms: int
    graceful_pass: bool


@dataclass(frozen=True)
class AuthorityLossTimeline:
    authority_replaced_at: datetime
    old_launcher_detected_at: datetime
    shutdown_requested_at: datetime
    core_exited_at: datetime
    graceful_shutdown: bool
    emergency_fallback_used: bool
    broad_kill_used: bool

    def validate_and_measure(self) -> AuthorityLossMetrics:
        timestamps = (
            self.authority_replaced_at,
            self.old_launcher_detected_at,
            self.shutdown_requested_at,
            self.core_exited_at,
        )
        if any(
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
            for value in timestamps
        ):
            raise ValueError("authority-loss timestamps must be UTC")
        if tuple(sorted(timestamps)) != timestamps:
            raise ValueError("authority-loss timestamps must be monotonic")
        if self.broad_kill_used:
            raise ValueError("broad process termination is forbidden")

        def elapsed_ms(start: datetime, end: datetime) -> int:
            return round((end - start).total_seconds() * 1000)

        graceful_pass = (
            self.graceful_shutdown
            and not self.emergency_fallback_used
            and not self.broad_kill_used
        )
        return AuthorityLossMetrics(
            replacement_to_authority_invalidation_ms=elapsed_ms(
                self.authority_replaced_at, self.old_launcher_detected_at
            ),
            authority_invalidation_to_core_exit_ms=elapsed_ms(
                self.old_launcher_detected_at, self.core_exited_at
            ),
            shutdown_request_to_core_exit_ms=elapsed_ms(
                self.shutdown_requested_at, self.core_exited_at
            ),
            graceful_pass=graceful_pass,
        )


def _require_commit(value: str, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"{label} must be a full lowercase commit SHA")


def _require_sha256(value: str, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} must be a full lowercase SHA-256")


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"artifact is unavailable: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ArtifactIdentityPlan:
    launcher_commit: str
    launcher_exe: Path
    launcher_exe_sha256: str
    core_commit: str
    core_manifest: Path
    core_manifest_sha256: str
    core_exe: Path
    core_exe_sha256: str
    critical_core_dll_sha256: dict[str, str]
    critical_core_dll_paths: tuple[Path, ...]

    @classmethod
    def capture(
        cls,
        *,
        launcher_commit: str,
        launcher_exe: Path,
        core_commit: str,
        core_manifest: Path,
        core_exe: Path,
        critical_core_dlls: tuple[Path, ...],
    ) -> ArtifactIdentityPlan:
        dll_names = {path.name for path in critical_core_dlls}
        if len(critical_core_dlls) != 5 or dll_names != CRITICAL_CORE_DLL_NAMES:
            raise ValueError("the exact five critical Core DLLs are required")
        plan = cls(
            launcher_commit=launcher_commit,
            launcher_exe=launcher_exe,
            launcher_exe_sha256=_sha256_file(launcher_exe),
            core_commit=core_commit,
            core_manifest=core_manifest,
            core_manifest_sha256=_sha256_file(core_manifest),
            core_exe=core_exe,
            core_exe_sha256=_sha256_file(core_exe),
            critical_core_dll_sha256={
                path.name: _sha256_file(path) for path in critical_core_dlls
            },
            critical_core_dll_paths=critical_core_dlls,
        )
        plan.validate()
        return plan

    def validate(self) -> None:
        _require_commit(self.launcher_commit, "Launcher commit")
        _require_commit(self.core_commit, "Core commit")
        if set(self.critical_core_dll_sha256) != CRITICAL_CORE_DLL_NAMES:
            raise ValueError("exactly five critical Core DLL hashes are required")
        if {path.name for path in self.critical_core_dll_paths} != CRITICAL_CORE_DLL_NAMES:
            raise ValueError("critical Core DLL paths do not match the hash set")

        expected: tuple[tuple[Path, str], ...] = (
            (self.launcher_exe, self.launcher_exe_sha256),
            (self.core_manifest, self.core_manifest_sha256),
            (self.core_exe, self.core_exe_sha256),
            *tuple(
                (path, self.critical_core_dll_sha256[path.name])
                for path in self.critical_core_dll_paths
            ),
        )
        for path, expected_hash in expected:
            _require_sha256(expected_hash, path.name)
            if _sha256_file(path) != expected_hash:
                raise ValueError(f"artifact bytes changed: {path.name}")


@dataclass(frozen=True)
class InstanceIsolation:
    instance: InstanceId
    windows_host_ref: str
    windows_user_ref: str
    credential_vault_ref: str
    local_app_data_root: str
    debug_log_root: str
    temporary_runtime_root: str
    process_ownership_ledger: str


@dataclass(frozen=True)
class ExecutionTopology:
    description: str
    instances: tuple[InstanceIsolation, ...]
    production_launcher_mutex: str
    production_core_pipe: str
    production_singletons_unchanged: bool

    @classmethod
    def separate_windows_vms(
        cls, instances: tuple[InstanceIsolation, ...]
    ) -> ExecutionTopology:
        return cls(
            description=(
                "three separate Windows VMs; one dedicated Windows user, Launcher, "
                "credential vault, and at most one production Core host per VM"
            ),
            instances=instances,
            production_launcher_mutex=r"Local\NekoFamilyProxyLauncher",
            production_core_pipe="NekoProxyCoreControl",
            production_singletons_unchanged=True,
        )


def validate_topology(topology: ExecutionTopology) -> None:
    if not topology.production_singletons_unchanged:
        raise ValueError("production singleton semantics must remain unchanged")
    if topology.production_launcher_mutex != r"Local\NekoFamilyProxyLauncher":
        raise ValueError("production Launcher mutex must remain unchanged")
    if topology.production_core_pipe != "NekoProxyCoreControl":
        raise ValueError("production Core pipe must remain unchanged")
    if tuple(item.instance for item in topology.instances) != tuple(InstanceId):
        raise ValueError("topology must define INSTANCE_A, INSTANCE_B, and INSTANCE_C")

    context_refs = {
        (item.windows_host_ref, item.windows_user_ref) for item in topology.instances
    }
    if len(context_refs) != len(InstanceId):
        raise ValueError("each Launcher instance needs an isolated Windows context")
    if len({item.credential_vault_ref for item in topology.instances}) != len(InstanceId):
        raise ValueError("each Launcher instance needs an isolated credential vault")
    for item in topology.instances:
        required = (
            item.windows_host_ref,
            item.windows_user_ref,
            item.credential_vault_ref,
            item.local_app_data_root,
            item.debug_log_root,
            item.temporary_runtime_root,
            item.process_ownership_ledger,
        )
        if not all(value.strip() for value in required):
            raise ValueError("instance isolation references must be non-empty")


@dataclass(frozen=True)
class ClaimObservation:
    instance: InstanceId
    session_ref: str
    installation_ref: str
    heartbeat_accepted: bool


@dataclass(frozen=True)
class DisplacedObservation:
    instance: InstanceId
    session_ref: str
    heartbeat_accepted: bool
    future_permit_eligible: bool


@dataclass(frozen=True)
class ExistingPermitWindow:
    issued_at: datetime
    expires_at: datetime
    raw_permit_recorded: bool = False

    def validate(self) -> None:
        if self.raw_permit_recorded:
            raise ValueError("raw launch permit evidence is forbidden")
        if any(
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
            for value in (self.issued_at, self.expires_at)
        ):
            raise ValueError("permit timestamps must be UTC")
        lifetime = (self.expires_at - self.issued_at).total_seconds()
        if not 0 < lifetime <= 30:
            raise ValueError("already-issued permit lifetime must be at most 30 seconds")


@dataclass(frozen=True)
class BackendAuthorityObservation:
    observed_at: datetime
    instance: InstanceId
    session_ref: str
    installation_ref: str
    authority_state: AuthorityState
    heartbeat_accepted: bool
    future_permit_eligible: bool
    authority_replaced_at: datetime | None = None
    authority_loss_detected_at: datetime | None = None
    existing_permit_window: ExistingPermitWindow | None = None

    def validate(self) -> None:
        _require_safe_ref(self.session_ref, "session reference")
        _require_safe_ref(self.installation_ref, "installation reference")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() != UTC.utcoffset(
            self.observed_at
        ):
            raise ValueError("authority observation timestamp must be UTC")
        if self.authority_state is AuthorityState.AUTHORITATIVE:
            valid = (
                self.heartbeat_accepted
                and self.future_permit_eligible
                and self.authority_replaced_at is None
                and self.authority_loss_detected_at is None
            )
        else:
            valid = (
                not self.heartbeat_accepted
                and not self.future_permit_eligible
                and self.authority_replaced_at is not None
                and self.authority_loss_detected_at is not None
                and self.authority_replaced_at <= self.authority_loss_detected_at
                and self.authority_loss_detected_at <= self.observed_at
            )
        if not valid:
            raise ValueError("authority observation contradicts latest-login-wins policy")
        if self.existing_permit_window is not None:
            self.existing_permit_window.validate()
            if (
                self.authority_replaced_at is not None
                and self.existing_permit_window.issued_at > self.authority_replaced_at
            ):
                raise ValueError("inactive session cannot receive a permit after replacement")


@dataclass(frozen=True)
class TransitionObservation:
    claim: ClaimObservation
    displaced: DisplacedObservation | None = None


@dataclass(frozen=True)
class LatestLoginWinsResult:
    authoritative_instance: InstanceId
    remembered_installation_count: int
    returning_instance_reclaimed: bool
    displaced_instances: tuple[InstanceId, ...]


def _require_safe_ref(value: str, label: str) -> None:
    if re.fullmatch(r"[a-z][a-z0-9_]{0,31}_[0-9a-f]{16}", value) is None:
        raise ValueError(f"{label} must be a sanitized opaque reference")


def validate_latest_login_wins(
    transitions: tuple[TransitionObservation, ...],
) -> LatestLoginWinsResult:
    expected_claims = (
        InstanceId.INSTANCE_A,
        InstanceId.INSTANCE_B,
        InstanceId.INSTANCE_C,
        InstanceId.INSTANCE_A,
    )
    if tuple(transition.claim.instance for transition in transitions) != expected_claims:
        raise ValueError("claim order must be INSTANCE_A -> INSTANCE_B -> INSTANCE_C -> INSTANCE_A")

    expected_displaced = (
        None,
        InstanceId.INSTANCE_A,
        InstanceId.INSTANCE_B,
        InstanceId.INSTANCE_C,
    )
    observed_displaced = tuple(
        transition.displaced.instance if transition.displaced is not None else None
        for transition in transitions
    )
    if observed_displaced != expected_displaced:
        raise ValueError("each successful claim must displace only the previous authority")
    if not all(transition.claim.heartbeat_accepted for transition in transitions):
        raise ValueError("every newest claim must accept heartbeat")
    if any(
        transition.displaced is not None
        and (
            transition.displaced.heartbeat_accepted
            or transition.displaced.future_permit_eligible
        )
        for transition in transitions
    ):
        raise ValueError("displaced sessions must lose heartbeat and future permit eligibility")

    sessions = tuple(transition.claim.session_ref for transition in transitions)
    installations = tuple(transition.claim.installation_ref for transition in transitions)
    for value in sessions:
        _require_safe_ref(value, "session reference")
    for value in installations:
        _require_safe_ref(value, "installation reference")
    if len(set(sessions)) != 4:
        raise ValueError("each successful claim must create a distinct Launcher session")
    if installations[0] != installations[3] or len(set(installations[:3])) != 3:
        raise ValueError("A/B/C installations must be distinct and A must retain its identity")
    for index in range(1, len(transitions)):
        displaced = transitions[index].displaced
        if displaced is None or displaced.session_ref != sessions[index - 1]:
            raise ValueError("displaced observation must identify the previous session")

    return LatestLoginWinsResult(
        authoritative_instance=transitions[-1].claim.instance,
        remembered_installation_count=len(set(installations)),
        returning_instance_reclaimed=True,
        displaced_instances=tuple(
            displaced for displaced in observed_displaced if displaced is not None
        ),
    )


@dataclass(frozen=True)
class RuntimeConfigGateObservation:
    state: RuntimeCatalogState
    candidate_count: int
    error_code: str | None
    validated_candidate: tuple[str, str] | None
    frozen_candidate: tuple[str, str] | None
    permit_calls: int
    first_or_any_fallback_used: bool = False

    def validate(self) -> None:
        if self.first_or_any_fallback_used:
            raise ValueError("runtime configuration fallback is forbidden")
        if self.permit_calls < 0:
            raise ValueError("permit call count cannot be negative")
        if self.state is RuntimeCatalogState.EMPTY:
            expected = (
                self.candidate_count == 0
                and self.error_code == "RUNTIME_CONFIGURATION_UNAVAILABLE"
                and self.validated_candidate is None
                and self.frozen_candidate is None
                and self.permit_calls == 0
            )
        elif self.state is RuntimeCatalogState.MULTIPLE:
            expected = (
                self.candidate_count > 1
                and self.error_code == "RUNTIME_CONFIGURATION_SELECTION_REQUIRED"
                and self.validated_candidate is None
                and self.frozen_candidate is None
                and self.permit_calls == 0
            )
        else:
            expected = (
                self.candidate_count == 1
                and self.error_code is None
                and self.validated_candidate is not None
                and self.validated_candidate == self.frozen_candidate
                and self.permit_calls == 1
            )
        if not expected:
            raise ValueError(f"invalid {self.state.value} runtime configuration gate evidence")


@dataclass(frozen=True)
class StageTraceObservation:
    stages: tuple[str, ...]
    final_core_status: str

    def validate_success(self) -> None:
        offset = 0
        for expected in EXPECTED_LAUNCH_STAGES:
            try:
                offset = self.stages.index(expected, offset) + 1
            except ValueError:
                raise ValueError(f"required Launcher stage is missing or out of order: {expected}")
        if self.final_core_status != EXPECTED_FINAL_CORE_STATUS:
            raise ValueError("final Core status must be CoreStatus.RUNNING")


_CORE_STAGE_PATTERN = re.compile(r"\[CORE\]\s+\[([A-Z][A-Z0-9_]*)\]")


def parse_launcher_stage_trace(log_text: str) -> StageTraceObservation:
    stages: list[str] = []
    final_core_status = ""
    for line in log_text.splitlines():
        match = _CORE_STAGE_PATTERN.search(line)
        if match is None:
            continue
        stage = match.group(1)
        if stage in EXPECTED_LAUNCH_STAGES:
            stages.append(stage)
        elif stage == "CORE_STATUS":
            status_match = re.search(r"(?:^|\s)status=(CoreStatus\.[A-Z]+)(?:\s|$)", line)
            if status_match is not None:
                final_core_status = status_match.group(1)
    return StageTraceObservation(tuple(stages), final_core_status)


@dataclass(frozen=True)
class CoreOwnershipObservation:
    launcher_owned_core_pid: int
    named_pipe_server_pid: int
    shutdown_requested_pid: int
    exited_core_pid: int
    unrelated_core_pids_before: frozenset[int]
    unrelated_core_pids_after: frozenset[int]
    taskkill_commands: tuple[str, ...]
    orphan_core_pids: frozenset[int]
    singleton_released: bool
    graceful_shutdown: bool
    emergency_fallback_used: bool

    def validate(self) -> None:
        pids = (
            self.launcher_owned_core_pid,
            self.named_pipe_server_pid,
            self.shutdown_requested_pid,
            self.exited_core_pid,
        )
        if any(isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 for pid in pids):
            raise ValueError("Core ownership PIDs must be positive integers")
        if len(set(pids)) != 1:
            raise ValueError("pipe, shutdown, and exit must bind to the exact owned Core PID")
        for command in self.taskkill_commands:
            lowered = command.lower()
            if "*" in command or "/im" in lowered or "nekoproxycore" in lowered:
                raise ValueError("wildcard or image-name Core termination is forbidden")
        if self.unrelated_core_pids_before != self.unrelated_core_pids_after:
            raise ValueError("unrelated Core processes changed")
        if self.orphan_core_pids:
            raise ValueError("owned Core process remained orphaned")
        if not self.singleton_released:
            raise ValueError("Core singleton was not released")
        if not self.graceful_shutdown or self.emergency_fallback_used:
            raise ValueError("emergency fallback cannot count as graceful PASS")


@dataclass(frozen=True)
class FailureExpectation:
    condition: str
    launcher_code: str
    domain: FailureDomain


FAILURE_MATRIX = (
    FailureExpectation("old A after B claim", "SESSION_INACTIVE", FailureDomain.AUTHORITY),
    FailureExpectation("old B after C claim", "SESSION_INACTIVE", FailureDomain.AUTHORITY),
    FailureExpectation("old C after A reclaim", "SESSION_INACTIVE", FailureDomain.AUTHORITY),
    FailureExpectation("SessionInactive", "SESSION_INACTIVE", FailureDomain.AUTHORITY),
    FailureExpectation("HeartbeatStale", "HEARTBEAT_STALE", FailureDomain.AUTHORITY),
    FailureExpectation("EntitlementInactive", "ENTITLEMENT_INACTIVE", FailureDomain.AUTHORITY),
    FailureExpectation(
        "AuthorizationInvalid", "AUTHORIZATION_INVALID", FailureDomain.AUTHORIZATION
    ),
    FailureExpectation(
        "ConfigurationMismatch", "CONFIGURATION_MISMATCH", FailureDomain.CONFIGURATION
    ),
    FailureExpectation(
        "runtime config EMPTY",
        "RUNTIME_CONFIGURATION_UNAVAILABLE",
        FailureDomain.CONFIGURATION,
    ),
    FailureExpectation(
        "runtime config MULTIPLE",
        "RUNTIME_CONFIGURATION_SELECTION_REQUIRED",
        FailureDomain.CONFIGURATION,
    ),
)


def validate_failure_matrix(matrix: tuple[FailureExpectation, ...] = FAILURE_MATRIX) -> None:
    required = {
        "old A after B claim",
        "old B after C claim",
        "old C after A reclaim",
        "SessionInactive",
        "HeartbeatStale",
        "EntitlementInactive",
        "AuthorizationInvalid",
        "ConfigurationMismatch",
        "runtime config EMPTY",
        "runtime config MULTIPLE",
    }
    if {entry.condition for entry in matrix} != required:
        raise ValueError("failure matrix is incomplete")
    if any(entry.launcher_code == "RUNNING_NOT_REACHED" for entry in matrix):
        raise ValueError("typed failures cannot collapse to RUNNING_NOT_REACHED")


@dataclass(frozen=True)
class SyntheticDataPlan:
    account_count: int
    account_disposable: bool
    entitlement_via_supported_admin_path: bool
    installation_instances: tuple[InstanceId, ...]
    installation_identity_from_production_vault: bool
    hosted_state_created_during_preparation: bool

    @classmethod
    def minimum(cls) -> SyntheticDataPlan:
        return cls(
            account_count=1,
            account_disposable=True,
            entitlement_via_supported_admin_path=True,
            installation_instances=tuple(InstanceId),
            installation_identity_from_production_vault=True,
            hosted_state_created_during_preparation=False,
        )

    def validate(self) -> None:
        if self.account_count != 1 or not self.account_disposable:
            raise ValueError("one disposable synthetic account is required")
        if not self.entitlement_via_supported_admin_path:
            raise ValueError("entitlement must use a supported Admin path")
        if self.installation_instances != tuple(InstanceId):
            raise ValueError("synthetic plan must cover installations A, B, and C")
        if not self.installation_identity_from_production_vault:
            raise ValueError("installation identity must come from production persistence")
        if self.hosted_state_created_during_preparation:
            raise ValueError("preparation must leave the hosted environment unchanged")


@dataclass(frozen=True)
class CleanupPlan:
    steps: tuple[CleanupStep, ...]
    known_synthetic_ids_only: bool
    broad_database_cleanup: bool

    @classmethod
    def deterministic(cls) -> CleanupPlan:
        return cls(
            steps=tuple(CleanupStep),
            known_synthetic_ids_only=True,
            broad_database_cleanup=False,
        )

    def validate(self) -> None:
        if self.steps != tuple(CleanupStep):
            raise ValueError("cleanup steps are missing or out of order")
        if not self.known_synthetic_ids_only or self.broad_database_cleanup:
            raise ValueError("cleanup must be scoped to exact synthetic identifiers")


@dataclass(frozen=True)
class FinalExecutionGates:
    historical_pso2_mode_recovered: bool
    runtime_catalog_state: RuntimeCatalogState
    hosted_core_running_kp_passed: bool

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.historical_pso2_mode_recovered:
            blockers.append("HISTORICAL_PSO2_MODE_SOURCE_REQUIRED")
        if self.runtime_catalog_state is not RuntimeCatalogState.UNIQUE:
            blockers.append("UNIQUE_RUNTIME_CONFIGURATION_REQUIRED")
        if not self.hosted_core_running_kp_passed:
            blockers.append("HOSTED_CORE_RUNNING_KP_REQUIRED")
        return tuple(blockers)

    def require_final_ready(self) -> None:
        blockers = self.blockers()
        if blockers:
            raise ValueError("final execution gates are closed: " + ", ".join(blockers))


@dataclass(frozen=True)
class PreparationAudit:
    permit_calls: int = 0
    authorized_core_start_calls: int = 0
    a_b_c_a_executed: bool = False

    def validate(self) -> None:
        if self.permit_calls != 0:
            raise ValueError("preparation consumed a hosted launch permit")
        if self.authorized_core_start_calls != 0:
            raise ValueError("preparation executed an authorized Core START")
        if self.a_b_c_a_executed:
            raise ValueError("preparation executed the final A -> B -> C -> A sequence")


@dataclass(frozen=True)
class LiveClaimResult:
    instance: InstanceId
    session_ref: str
    installation_ref: str


class FinalSequenceDriver(Protocol):
    def claim(self, instance: InstanceId) -> LiveClaimResult: ...

    def heartbeat_accepted(self, instance: InstanceId, session_ref: str) -> bool: ...

    def future_permit_eligible(self, instance: InstanceId, session_ref: str) -> bool: ...

    def cleanup(self, step: CleanupStep) -> None: ...


class FinalWindowsE2EHarness:
    """Gate-bound final transition runner; preparation never constructs this."""

    def __init__(
        self,
        *,
        gates: FinalExecutionGates,
        driver: FinalSequenceDriver,
    ) -> None:
        self._gates = gates
        self._driver = driver

    def run(self) -> LatestLoginWinsResult:
        self._gates.require_final_ready()
        transitions: list[TransitionObservation] = []
        previous: LiveClaimResult | None = None
        try:
            for instance in (
                InstanceId.INSTANCE_A,
                InstanceId.INSTANCE_B,
                InstanceId.INSTANCE_C,
                InstanceId.INSTANCE_A,
            ):
                claim = self._driver.claim(instance)
                if claim.instance is not instance:
                    raise ValueError("claim result belongs to the wrong Launcher instance")
                heartbeat_accepted = self._driver.heartbeat_accepted(
                    instance, claim.session_ref
                )
                displaced = None
                if previous is not None:
                    displaced = DisplacedObservation(
                        instance=previous.instance,
                        session_ref=previous.session_ref,
                        heartbeat_accepted=self._driver.heartbeat_accepted(
                            previous.instance, previous.session_ref
                        ),
                        future_permit_eligible=self._driver.future_permit_eligible(
                            previous.instance, previous.session_ref
                        ),
                    )
                transitions.append(
                    TransitionObservation(
                        claim=ClaimObservation(
                            instance=instance,
                            session_ref=claim.session_ref,
                            installation_ref=claim.installation_ref,
                            heartbeat_accepted=heartbeat_accepted,
                        ),
                        displaced=displaced,
                    )
                )
                previous = claim
            return validate_latest_login_wins(tuple(transitions))
        finally:
            cleanup_failed = False
            for step in CleanupStep:
                try:
                    self._driver.cleanup(step)
                except Exception:
                    cleanup_failed = True
            if cleanup_failed:
                raise ValueError("one or more scoped cleanup steps failed") from None


_FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "authorization",
        "raw_jwt",
        "jwt",
        "service_role_key",
        "service_role",
        "launch_permit",
        "permit",
        "password",
        "secret",
    }
)
_FORBIDDEN_EVIDENCE_VALUE_PATTERNS = (
    re.compile(r"\bauthorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:access_token|refresh_token|service_role(?:_key)?|password|secret)"
        r"\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
)


def assert_secret_safe_mapping(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).strip().lower() in _FORBIDDEN_EVIDENCE_KEYS:
                raise ValueError(f"secret-bearing evidence field is forbidden: {key}")
            assert_secret_safe_mapping(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            assert_secret_safe_mapping(nested)
    elif isinstance(value, str) and any(
        pattern.search(value) for pattern in _FORBIDDEN_EVIDENCE_VALUE_PATTERNS
    ):
        raise ValueError("secret-bearing evidence value is forbidden")


def default_preparation_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "phase": "PHASE 2.5-FINAL-WINDOWS-E2E-HARNESS-PREPARATION",
        "execution_topology": (
            "three separate Windows VMs; one dedicated Windows user, Launcher, "
            "credential vault, and at most one production Core host per VM"
        ),
        "instances": [instance.value for instance in InstanceId],
        "production_launcher_mutex": r"Local\NekoFamilyProxyLauncher",
        "production_core_pipe": "NekoProxyCoreControl",
        "production_singletons_unchanged": True,
        "required_stages": list(EXPECTED_LAUNCH_STAGES),
        "required_final_core_status": EXPECTED_FINAL_CORE_STATUS,
        "artifact_evidence_fields": [
            "launcher_commit_sha",
            "launcher_exe_sha256",
            "core_commit_sha",
            "core_manifest_sha256",
            "core_exe_sha256",
            *[f"critical_core_dll_sha256.{name}" for name in sorted(CRITICAL_CORE_DLL_NAMES)],
        ],
        "permit_semantics": {
            "already_issued_permit_max_seconds": 30,
            "replacement_blocks_future_permit_issuance": True,
            "retroactive_core_revocation_required": False,
        },
        "synthetic_data": {
            "account_count": 1,
            "disposable": True,
            "installation_instances": [instance.value for instance in InstanceId],
            "hosted_state_created_during_preparation": False,
        },
        "cleanup_steps": [step.value for step in CleanupStep],
        "failure_matrix": [
            {
                "condition": entry.condition,
                "launcher_code": entry.launcher_code,
                "domain": entry.domain.value,
            }
            for entry in FAILURE_MATRIX
        ],
        "final_execution_gates": {
            "historical_pso2_mode_recovered": False,
            "runtime_catalog_state": RuntimeCatalogState.EMPTY.value,
            "hosted_core_running_kp_passed": False,
        },
        "preparation_audit": {
            "permit_calls": 0,
            "authorized_core_start_calls": 0,
            "a_b_c_a_executed": False,
        },
    }
    assert_secret_safe_mapping(manifest)
    return manifest


def write_preparation_manifest(path: Path) -> None:
    manifest = default_preparation_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def validate_preparation_contract() -> None:
    SyntheticDataPlan.minimum().validate()
    CleanupPlan.deterministic().validate()
    validate_failure_matrix()
    PreparationAudit().validate()
    gates = FinalExecutionGates(
        historical_pso2_mode_recovered=False,
        runtime_catalog_state=RuntimeCatalogState.EMPTY,
        hosted_core_running_kp_passed=False,
    )
    if not gates.blockers():
        raise ValueError("preparation must not open final execution gates")
    assert_secret_safe_mapping(default_preparation_manifest())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preparation-only Final Windows E2E evidence harness"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser(
        "prepare", help="write a safe offline run manifest; never call Backend or Core START"
    )
    prepare.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "prepare":
        validate_preparation_contract()
        write_preparation_manifest(args.output)
        return 0
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
