"""Domain models, schema validation, and serialization for updater state and enrollment marker."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
import re
from typing import Any, Literal

from neko_launcher.application.software_update_models import InstalledReleaseSelector
from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads
from neko_launcher.updater.manifest_v2 import parse_release_v2, verify_release_envelope_v2

Phase = Literal[
    "ENROLLING",
    "IDLE",
    "PREPARING",
    "QUIESCING",
    "PROBATION",
    "ROLLING_BACK",
    "CLEANING",
    "REPAIR_REQUIRED",
]

VALID_PHASES = {
    "ENROLLING",
    "IDLE",
    "PREPARING",
    "QUIESCING",
    "PROBATION",
    "ROLLING_BACK",
    "CLEANING",
    "REPAIR_REQUIRED",
}

MutationKind = Literal[
    "CREATE_STAGE",
    "WRITE_CANDIDATE",
    "PUBLISH_GENERATION",
    "STOP_OLD",
    "START_PROBATION",
]

VALID_MUTATION_KINDS = {
    "CREATE_STAGE",
    "WRITE_CANDIDATE",
    "PUBLISH_GENERATION",
    "STOP_OLD",
    "START_PROBATION",
}

Target = Literal[
    "stage",
    "generation",
    "old_process_family",
    "candidate_process_family",
]

VALID_TARGETS = {
    "stage",
    "generation",
    "old_process_family",
    "candidate_process_family",
}

TransactionStage = Literal[
    "ADMITTED",
    "BUILDING",
    "VERIFIED",
    "QUIESCING",
    "PROBATION",
]

VALID_TRANSACTION_STAGES = {
    "ADMITTED",
    "BUILDING",
    "VERIFIED",
    "QUIESCING",
    "PROBATION",
}

MutationStatus = Literal["INTENT", "DONE"]
VALID_MUTATION_STATUSES = {"INTENT", "DONE"}

CleanupTarget = Literal["incoming", "staging"]
VALID_CLEANUP_TARGETS = {"incoming", "staging"}

CleanupStatus = Literal["INTENT", "DONE", "SKIPPED"]
VALID_CLEANUP_STATUSES = {"INTENT", "DONE", "SKIPPED"}

RollbackMode = Literal["precommit", "postcommit"]
VALID_ROLLBACK_MODES = {"precommit", "postcommit"}

RollbackStep = Literal[
    "DRAIN_INTENT",
    "DRAIN_DONE",
    "RESTORE_INTENT",
    "RESTORE_DONE",
]

VALID_ROLLBACK_STEPS = {
    "DRAIN_INTENT",
    "DRAIN_DONE",
    "RESTORE_INTENT",
    "RESTORE_DONE",
}

_HEX16_RE = re.compile(r"^[0-9a-f]{16}$")
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _assert_hex(val: str, expected_len: int, name: str) -> None:
    if not isinstance(val, str):
        raise ValueError(f"{name} must be a string")
    pattern = _HEX64_RE if expected_len == 64 else (_HEX32_RE if expected_len == 32 else _HEX16_RE)
    if not pattern.fullmatch(val):
        raise ValueError(f"Invalid hash or hex identifier for {name}: {val!r}")


def _assert_closed_keys(data: dict[str, Any], allowed_keys: set[str], model_name: str) -> None:
    keys = set(data.keys())
    extra = keys - allowed_keys
    if extra:
        raise ValueError(f"Unknown field: {next(iter(extra))} in {model_name}")
    missing = allowed_keys - keys
    if missing:
        raise ValueError(f"Missing required field: {next(iter(missing))} in {model_name}")


@dataclass(frozen=True)
class Binding:
    release_sequence: int
    release_id: str
    payload_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.release_sequence, int) or self.release_sequence < 1:
            raise ValueError("release_sequence must be a positive integer")
        if not isinstance(self.release_id, str) or not _RELEASE_ID_RE.fullmatch(self.release_id):
            raise ValueError("Invalid release_id grammar")
        _assert_hex(self.payload_sha256, 64, "payload_sha256")


@dataclass(frozen=True)
class Generation:
    binding: Binding
    launcher_identity_sha256: str
    core_identity_sha256: str
    selector: InstalledReleaseSelector | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.binding, Binding):
            raise ValueError("binding must be a Binding instance")
        _assert_hex(self.launcher_identity_sha256, 64, "launcher_identity_sha256")
        _assert_hex(self.core_identity_sha256, 64, "core_identity_sha256")
        if self.selector is not None:
            if not isinstance(self.selector, InstalledReleaseSelector):
                raise ValueError("selector must be an InstalledReleaseSelector or None")
            if self.selector.sequence != self.binding.release_sequence:
                raise ValueError(
                    f"selector.sequence {self.selector.sequence} does not match binding.release_sequence {self.binding.release_sequence}"
                )
            if self.selector.release_id != self.binding.release_id:
                raise ValueError(
                    f"selector.release_id {self.selector.release_id!r} does not match binding.release_id {self.binding.release_id!r}"
                )


@dataclass(frozen=True)
class DirectoryIdentity:
    volume_serial: str
    file_id: str
    parent_file_id: str

    def __post_init__(self) -> None:
        _assert_hex(self.volume_serial, 16, "volume_serial")
        _assert_hex(self.file_id, 32, "file_id")
        _assert_hex(self.parent_file_id, 32, "parent_file_id")


@dataclass(frozen=True)
class Mutation:
    kind: MutationKind
    target: Target
    status: MutationStatus

    def __post_init__(self) -> None:
        if self.kind not in VALID_MUTATION_KINDS:
            raise ValueError(f"Invalid mutation kind: {self.kind}")
        if self.target not in VALID_TARGETS:
            raise ValueError(f"Invalid mutation target: {self.target}")
        if self.status not in VALID_MUTATION_STATUSES:
            raise ValueError(f"Invalid mutation status: {self.status}")


@dataclass(frozen=True)
class Transaction:
    id: str
    request_id: str
    candidate: Generation
    old: Generation | None
    incoming: DirectoryIdentity
    staging: DirectoryIdentity | None
    stage: TransactionStage
    mutation: Mutation | None
    repair_components: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        _assert_hex(self.id, 32, "transaction id")
        _assert_hex(self.request_id, 32, "transaction request_id")
        if not isinstance(self.candidate, Generation):
            raise ValueError("candidate must be a Generation instance")
        if self.old is not None and not isinstance(self.old, Generation):
            raise ValueError("old must be a Generation instance or None")
        if not isinstance(self.incoming, DirectoryIdentity):
            raise ValueError("incoming must be a DirectoryIdentity instance")
        if self.staging is not None and not isinstance(self.staging, DirectoryIdentity):
            raise ValueError("staging must be a DirectoryIdentity instance or None")
        if self.stage not in VALID_TRANSACTION_STAGES:
            raise ValueError(f"Invalid transaction stage: {self.stage}")
        if self.mutation is not None and not isinstance(self.mutation, Mutation):
            raise ValueError("mutation must be a Mutation instance or None")
        if self.repair_components is not None:
            if not isinstance(self.repair_components, (tuple, list)) or not self.repair_components:
                raise ValueError("repair_components must be a non-empty tuple of component names")
            for c in self.repair_components:
                if c not in ("launcher", "core"):
                    raise ValueError(f"Invalid repair component: {c}")
            object.__setattr__(self, "repair_components", tuple(self.repair_components))


@dataclass(frozen=True)
class Cleanup:
    transaction_id: str
    request_id: str
    directory: DirectoryIdentity
    target: CleanupTarget
    status: CleanupStatus

    def __post_init__(self) -> None:
        _assert_hex(self.transaction_id, 32, "cleanup transaction_id")
        _assert_hex(self.request_id, 32, "cleanup request_id")
        if not isinstance(self.directory, DirectoryIdentity):
            raise ValueError("cleanup directory must be a DirectoryIdentity instance")
        if self.target not in VALID_CLEANUP_TARGETS:
            raise ValueError(f"Invalid cleanup target: {self.target}")
        if self.status not in VALID_CLEANUP_STATUSES:
            raise ValueError(f"Invalid cleanup status: {self.status}")


@dataclass(frozen=True)
class Rollback:
    mode: RollbackMode
    target: Generation
    probation_id: str
    scratch: list[Cleanup]
    step: RollbackStep

    def __post_init__(self) -> None:
        if self.mode not in VALID_ROLLBACK_MODES:
            raise ValueError(f"Invalid rollback mode: {self.mode}")
        if not isinstance(self.target, Generation):
            raise ValueError("rollback target must be a Generation instance")
        _assert_hex(self.probation_id, 32, "rollback probation_id")
        if not isinstance(self.scratch, list) or len(self.scratch) > 2:
            raise ValueError("rollback scratch must be a list of 0..2 Cleanup instances")
        for item in self.scratch:
            if not isinstance(item, Cleanup):
                raise ValueError("scratch entries must be Cleanup instances")
        if self.step not in VALID_ROLLBACK_STEPS:
            raise ValueError(f"Invalid rollback step: {self.step}")


@dataclass(frozen=True)
class State:
    schema_version: int
    revision: int
    installation_id: str
    helper_protocol: int
    enrollment_complete: bool
    phase: Phase
    committed: Generation | None
    previous: Generation | None
    highwater: Binding | None
    observed: Binding | None
    failed: Binding | None
    transaction: Transaction | None
    cleanup: list[Cleanup] | None
    rollback: Rollback | None
    last_error: str | None
    evidence: dict[str, str]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"Unsupported schema version: {self.schema_version}")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("revision must be a positive integer >= 1")
        _assert_hex(self.installation_id, 32, "installation_id")
        if self.helper_protocol != 1:
            raise ValueError(f"Unsupported helper protocol: {self.helper_protocol}")
        if not isinstance(self.enrollment_complete, bool):
            raise ValueError("enrollment_complete must be a boolean")
        if self.phase not in VALID_PHASES:
            raise ValueError(f"Invalid phase: {self.phase}")
        if self.cleanup is not None:
            if not isinstance(self.cleanup, list) or not (1 <= len(self.cleanup) <= 2):
                raise ValueError("cleanup must be null or a list of 1..2 Cleanup instances")
            for item in self.cleanup:
                if not isinstance(item, Cleanup):
                    raise ValueError("cleanup items must be Cleanup instances")
        if not isinstance(self.evidence, dict):
            raise ValueError("evidence must be a dictionary mapping payload SHA to base64 envelope")
        for k, v in self.evidence.items():
            _assert_hex(k, 64, "evidence key")
            if not isinstance(v, str):
                raise ValueError("evidence values must be base64 strings")


@dataclass(frozen=True)
class RootIdentity:
    volume_serial: str
    file_id: str

    def __post_init__(self) -> None:
        _assert_hex(self.volume_serial, 16, "volume_serial")
        _assert_hex(self.file_id, 32, "file_id")


@dataclass(frozen=True)
class EnrollmentMarker:
    schema_version: int
    installation_id: str
    root: RootIdentity
    helper_sha256: str
    helper_protocol: int
    keyset_sha256: str
    bootstrap_payload_sha256: str
    enrollment_status: Literal["PREPARED"]
    profile_id: str = "production"
    profile_envelope_sha256: str = "0" * 64

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"Unsupported schema version: {self.schema_version}")
        _assert_hex(self.installation_id, 32, "installation_id")
        if not isinstance(self.root, RootIdentity):
            raise ValueError("root must be a RootIdentity instance")
        _assert_hex(self.helper_sha256, 64, "helper_sha256")
        if self.helper_protocol != 1:
            raise ValueError(f"Unsupported helper protocol: {self.helper_protocol}")
        if not isinstance(self.profile_id, str) or not _RELEASE_ID_RE.fullmatch(self.profile_id):
            raise ValueError(f"Invalid profile_id: {self.profile_id!r}")
        _assert_hex(self.profile_envelope_sha256, 64, "profile_envelope_sha256")
        _assert_hex(self.keyset_sha256, 64, "keyset_sha256")
        _assert_hex(self.bootstrap_payload_sha256, 64, "bootstrap_payload_sha256")
        if self.enrollment_status != "PREPARED":
            raise ValueError(f"Invalid enrollment status: {self.enrollment_status}")


# --- Serialization & Deserialization Helpers ---

STATE_ALLOWED_KEYS = {
    "schema_version",
    "revision",
    "installation_id",
    "helper_protocol",
    "enrollment_complete",
    "phase",
    "committed",
    "previous",
    "highwater",
    "observed",
    "failed",
    "transaction",
    "cleanup",
    "rollback",
    "last_error",
    "evidence",
}

BINDING_ALLOWED_KEYS = {"release_sequence", "release_id", "payload_sha256"}
GENERATION_REQUIRED_KEYS = {"binding", "launcher_identity_sha256", "core_identity_sha256"}
GENERATION_ALLOWED_KEYS = GENERATION_REQUIRED_KEYS | {"selector"}
DIRECTORY_ID_ALLOWED_KEYS = {"volume_serial", "file_id", "parent_file_id"}
MUTATION_ALLOWED_KEYS = {"kind", "target", "status"}
TRANSACTION_ALLOWED_KEYS = {
    "id",
    "request_id",
    "candidate",
    "old",
    "incoming",
    "staging",
    "stage",
    "mutation",
    "repair_components",
}
CLEANUP_ALLOWED_KEYS = {"transaction_id", "request_id", "directory", "target", "status"}
ROLLBACK_ALLOWED_KEYS = {"mode", "target", "probation_id", "scratch", "step"}

MARKER_ALLOWED_KEYS = {
    "schema_version",
    "installation_id",
    "root",
    "helper_sha256",
    "helper_protocol",
    "profile_id",
    "profile_envelope_sha256",
    "keyset_sha256",
    "bootstrap_payload_sha256",
    "enrollment_status",
}
ROOT_ID_ALLOWED_KEYS = {"volume_serial", "file_id"}
SELECTOR_ALLOWED_KEYS = {
    "sequence",
    "release_id",
    "version",
    "tag_name",
    "target_commit",
}


def _parse_installed_release_selector(data: dict[str, Any]) -> InstalledReleaseSelector:
    if not isinstance(data, dict):
        raise ValueError("InstalledReleaseSelector payload must be a JSON object")
    _assert_closed_keys(data, SELECTOR_ALLOWED_KEYS, "InstalledReleaseSelector")
    return InstalledReleaseSelector(
        sequence=data["sequence"],
        release_id=data["release_id"],
        version=data["version"],
        tag_name=data["tag_name"],
        target_commit=data["target_commit"],
    )


def _parse_binding(data: dict[str, Any]) -> Binding:
    _assert_closed_keys(data, BINDING_ALLOWED_KEYS, "Binding")
    return Binding(**data)


def _parse_generation(data: dict[str, Any]) -> Generation:
    keys = set(data.keys())
    extra = keys - GENERATION_ALLOWED_KEYS
    if extra:
        raise ValueError(f"Unknown field: {next(iter(extra))} in Generation")
    missing = GENERATION_REQUIRED_KEYS - keys
    if missing:
        raise ValueError(f"Missing required field: {next(iter(missing))} in Generation")
    binding = _parse_binding(data["binding"])
    raw_sel = data.get("selector")
    selector = _parse_installed_release_selector(raw_sel) if raw_sel is not None else None
    return Generation(
        binding=binding,
        launcher_identity_sha256=data["launcher_identity_sha256"],
        core_identity_sha256=data["core_identity_sha256"],
        selector=selector,
    )


def _parse_directory_identity(data: dict[str, Any]) -> DirectoryIdentity:
    _assert_closed_keys(data, DIRECTORY_ID_ALLOWED_KEYS, "DirectoryIdentity")
    return DirectoryIdentity(**data)


def _parse_mutation(data: dict[str, Any]) -> Mutation:
    _assert_closed_keys(data, MUTATION_ALLOWED_KEYS, "Mutation")
    return Mutation(**data)


def _parse_transaction(data: dict[str, Any]) -> Transaction:
    _assert_closed_keys(data, TRANSACTION_ALLOWED_KEYS, "Transaction")
    candidate = _parse_generation(data["candidate"])
    old = _parse_generation(data["old"]) if data["old"] is not None else None
    incoming = _parse_directory_identity(data["incoming"])
    staging = _parse_directory_identity(data["staging"]) if data["staging"] is not None else None
    mutation = _parse_mutation(data["mutation"]) if data["mutation"] is not None else None
    repair_raw = data.get("repair_components")
    repair_components = tuple(repair_raw) if repair_raw is not None else None
    return Transaction(
        id=data["id"],
        request_id=data["request_id"],
        candidate=candidate,
        old=old,
        incoming=incoming,
        staging=staging,
        stage=data["stage"],
        mutation=mutation,
        repair_components=repair_components,
    )


def _parse_cleanup(data: dict[str, Any]) -> Cleanup:
    _assert_closed_keys(data, CLEANUP_ALLOWED_KEYS, "Cleanup")
    directory = _parse_directory_identity(data["directory"])
    return Cleanup(
        transaction_id=data["transaction_id"],
        request_id=data["request_id"],
        directory=directory,
        target=data["target"],
        status=data["status"],
    )


def _parse_rollback(data: dict[str, Any]) -> Rollback:
    _assert_closed_keys(data, ROLLBACK_ALLOWED_KEYS, "Rollback")
    target = _parse_generation(data["target"])
    scratch = [_parse_cleanup(c) for c in data["scratch"]]
    return Rollback(
        mode=data["mode"],
        target=target,
        probation_id=data["probation_id"],
        scratch=scratch,
        step=data["step"],
    )


def serialize_state(state: State) -> bytes:
    """Serialize State into canonical UTF-8 JSON bytes."""
    state_dict = asdict(state)
    return canonical_json_dumps(state_dict)


def deserialize_state(raw: bytes | str) -> State:
    """Deserialize canonical UTF-8 JSON into State with strict schema validation."""
    data = canonical_json_loads(raw)
    if not isinstance(data, dict):
        raise ValueError("State payload must be a JSON object")

    _assert_closed_keys(data, STATE_ALLOWED_KEYS, "State")

    committed = _parse_generation(data["committed"]) if data["committed"] is not None else None
    previous = _parse_generation(data["previous"]) if data["previous"] is not None else None
    highwater = _parse_binding(data["highwater"]) if data["highwater"] is not None else None
    observed = _parse_binding(data["observed"]) if data["observed"] is not None else None
    failed = _parse_binding(data["failed"]) if data["failed"] is not None else None
    transaction = (
        _parse_transaction(data["transaction"]) if data["transaction"] is not None else None
    )
    cleanup = [_parse_cleanup(c) for c in data["cleanup"]] if data["cleanup"] is not None else None
    rollback = _parse_rollback(data["rollback"]) if data["rollback"] is not None else None

    return State(
        schema_version=data["schema_version"],
        revision=data["revision"],
        installation_id=data["installation_id"],
        helper_protocol=data["helper_protocol"],
        enrollment_complete=data["enrollment_complete"],
        phase=data["phase"],
        committed=committed,
        previous=previous,
        highwater=highwater,
        observed=observed,
        failed=failed,
        transaction=transaction,
        cleanup=cleanup,
        rollback=rollback,
        last_error=data["last_error"],
        evidence=dict(data["evidence"]),
    )


def migrate_state(
    state: State,
    *,
    deterministic_selector: InstalledReleaseSelector | None = None,
    deterministic_commit: str | None = None,
    key_registry: Mapping[str, bytes] | None = None,
) -> State:
    """Migrate durable state to include exact installed release selector fail-closed."""
    if state.committed is None:
        return state

    if state.committed.selector is not None:
        return state

    if deterministic_selector is not None:
        if not isinstance(deterministic_selector, InstalledReleaseSelector):
            raise ValueError("deterministic_selector must be an InstalledReleaseSelector")
        if deterministic_selector.sequence != state.committed.binding.release_sequence:
            raise ValueError(
                f"Migration sequence mismatch: selector sequence {deterministic_selector.sequence} "
                f"!= committed sequence {state.committed.binding.release_sequence}"
            )
        if deterministic_selector.release_id != state.committed.binding.release_id:
            raise ValueError(
                f"Migration release_id mismatch: selector release_id {deterministic_selector.release_id!r} "
                f"!= committed release_id {state.committed.binding.release_id!r}"
            )
        migrated_gen = replace(state.committed, selector=deterministic_selector)
        return replace(state, committed=migrated_gen)

    if deterministic_commit is not None:
        if not isinstance(deterministic_commit, str) or not deterministic_commit.strip():
            raise ValueError("deterministic_commit must be a non-empty string")
        payload_sha = state.committed.binding.payload_sha256
        if payload_sha not in state.evidence:
            raise ValueError(
                "Migration failed: missing signed envelope evidence for committed payload"
            )

        try:
            envelope_bytes = base64.b64decode(state.evidence[payload_sha], validate=True)
            envelope_doc = canonical_json_loads(envelope_bytes)
        except Exception as exc:
            raise ValueError(f"Migration failed to decode envelope evidence: {exc}") from exc

        if key_registry is not None:
            try:
                release_set_v2, verified_payload_sha = verify_release_envelope_v2(
                    envelope_doc,
                    key_registry,
                )
                if verified_payload_sha != payload_sha:
                    raise ValueError("Migration failed: verified payload SHA mismatch")
            except Exception as exc:
                raise ValueError(f"Migration envelope verification failed: {exc}") from exc
        else:
            raw_payload = envelope_doc.get("payload", envelope_doc)
            if not isinstance(raw_payload, dict):
                raise ValueError("Migration envelope missing payload dictionary")
            release_set_v2 = parse_release_v2(raw_payload)

        if release_set_v2.release_sequence != state.committed.binding.release_sequence:
            raise ValueError("Migration failed: evidence release_sequence mismatch")
        if release_set_v2.release_id != state.committed.binding.release_id:
            raise ValueError("Migration failed: evidence release_id mismatch")

        launcher_comp = release_set_v2.components.get("launcher")
        if launcher_comp is None:
            raise ValueError("Migration failed: evidence missing launcher component")

        version = launcher_comp.version
        tag_name = f"v{version}"

        selector = InstalledReleaseSelector(
            sequence=state.committed.binding.release_sequence,
            release_id=state.committed.binding.release_id,
            version=version,
            tag_name=tag_name,
            target_commit=deterministic_commit,
        )
        migrated_gen = replace(state.committed, selector=selector)
        return replace(state, committed=migrated_gen)

    raise ValueError(
        "Migration failed: ambiguous historical state without deterministic selector or target_commit; "
        "cannot guess installed release identity"
    )


def serialize_marker(marker: EnrollmentMarker) -> bytes:
    """Serialize EnrollmentMarker into canonical UTF-8 JSON bytes."""
    marker_dict = asdict(marker)
    return canonical_json_dumps(marker_dict)


def deserialize_marker(raw: bytes | str) -> EnrollmentMarker:
    """Deserialize canonical UTF-8 JSON into EnrollmentMarker with strict schema validation."""
    data = canonical_json_loads(raw)
    if not isinstance(data, dict):
        raise ValueError("EnrollmentMarker payload must be a JSON object")

    _assert_closed_keys(data, MARKER_ALLOWED_KEYS, "EnrollmentMarker")
    root_dict = data["root"]
    if not isinstance(root_dict, dict):
        raise ValueError("EnrollmentMarker root must be a JSON object")
    _assert_closed_keys(root_dict, ROOT_ID_ALLOWED_KEYS, "RootIdentity")
    root = RootIdentity(**root_dict)

    return EnrollmentMarker(
        schema_version=data["schema_version"],
        installation_id=data["installation_id"],
        root=root,
        helper_sha256=data["helper_sha256"],
        helper_protocol=data["helper_protocol"],
        profile_id=data["profile_id"],
        profile_envelope_sha256=data["profile_envelope_sha256"],
        keyset_sha256=data["keyset_sha256"],
        bootstrap_payload_sha256=data["bootstrap_payload_sha256"],
        enrollment_status=data["enrollment_status"],
    )
