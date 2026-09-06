"""Domain models, schema validation, and serialization for updater state and enrollment marker."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

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

MutationKind = Literal[
    "CREATE_STAGE",
    "WRITE_CANDIDATE",
    "PUBLISH_GENERATION",
    "STOP_OLD",
    "START_PROBATION",
]

Target = Literal[
    "stage",
    "generation",
    "old_process_family",
    "candidate_process_family",
]

TransactionStage = Literal[
    "ADMITTED",
    "BUILDING",
    "VERIFIED",
    "QUIESCING",
    "PROBATION",
]

MutationStatus = Literal["INTENT", "DONE"]

CleanupTarget = Literal["incoming", "staging"]
CleanupStatus = Literal["INTENT", "DONE", "SKIPPED"]

RollbackMode = Literal["precommit", "postcommit"]
RollbackStep = Literal[
    "DRAIN_INTENT",
    "DRAIN_DONE",
    "RESTORE_INTENT",
    "RESTORE_DONE",
]


@dataclass(frozen=True)
class Binding:
    release_sequence: int
    release_id: str
    payload_sha256: str


@dataclass(frozen=True)
class Generation:
    binding: Binding
    launcher_identity_sha256: str
    core_identity_sha256: str


@dataclass(frozen=True)
class DirectoryIdentity:
    volume_serial: str
    file_id: str
    parent_file_id: str


@dataclass(frozen=True)
class Mutation:
    kind: MutationKind
    target: Target
    status: MutationStatus


@dataclass(frozen=True)
class Transaction:
    id: str
    request_id: str
    candidate: Generation
    old: Generation | null
    incoming: DirectoryIdentity
    staging: DirectoryIdentity | null
    stage: TransactionStage
    mutation: Mutation | null


@dataclass(frozen=True)
class Cleanup:
    transaction_id: str
    request_id: str
    directory: DirectoryIdentity
    target: CleanupTarget
    status: CleanupStatus


@dataclass(frozen=True)
class Rollback:
    mode: RollbackMode
    target: Generation
    probation_id: str
    scratch: list[Cleanup]
    step: RollbackStep


@dataclass(frozen=True)
class State:
    schema_version: int
    revision: int
    installation_id: str
    helper_protocol: int
    enrollment_complete: bool
    phase: Phase
    committed: Generation | null
    previous: Generation | null
    highwater: Binding | null
    observed: Binding | null
    failed: Binding | null
    transaction: Transaction | null
    cleanup: list[Cleanup] | null
    rollback: Rollback | null
    last_error: str | null
    evidence: dict[str, str]


@dataclass(frozen=True)
class RootIdentity:
    volume_serial: str
    file_id: str


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


def serialize_state(state: State) -> bytes:
    """Serialize State into canonical UTF-8 JSON bytes."""
    raise NotImplementedError("serialize_state not implemented")


def deserialize_state(raw: bytes | str) -> State:
    """Deserialize canonical UTF-8 JSON into State with strict schema validation."""
    raise NotImplementedError("deserialize_state not implemented")


def serialize_marker(marker: EnrollmentMarker) -> bytes:
    """Serialize EnrollmentMarker into canonical UTF-8 JSON bytes."""
    raise NotImplementedError("serialize_marker not implemented")


def deserialize_marker(raw: bytes | str) -> EnrollmentMarker:
    """Deserialize canonical UTF-8 JSON into EnrollmentMarker with strict schema validation."""
    raise NotImplementedError("deserialize_marker not implemented")
