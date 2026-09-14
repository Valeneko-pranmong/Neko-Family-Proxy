"""Canonical append-only Project Release-Audit Ledger and hash-chain verifier."""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import os
from pathlib import Path
import re
import sys
from typing import Any, Literal

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads  # noqa: E402

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

EVENT_TYPE_RETIREMENT_EVIDENCE_READY = "RETIREMENT_EVIDENCE_READY"
EVENT_TYPE_RETIREMENT_PRECONDITIONS_RECORDED = "RETIREMENT_PRECONDITIONS_RECORDED"
EVENT_TYPE_INSTALLER_REPOSITORY_DELETED = "INSTALLER_REPOSITORY_DELETED"

SUPPORTED_EVENT_TYPES = frozenset({
    EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
    EVENT_TYPE_RETIREMENT_PRECONDITIONS_RECORDED,
    EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
})

VERIFIED_DELETED_RESULT = "VERIFIED_DELETED"
QUALIFICATION_STATUS_KNOWN_BROKEN = "KNOWN_BROKEN_UNQUALIFIED"
OWNER_DISPOSITION_DELETE = "DELETE"

_EVENT_TOP_LEVEL_KEYS = frozenset({
    "event_type",
    "target_repository_id",
    "target_repository_node_id",
    "target_owner",
    "target_name",
    "evidence",
    "timestamp",
    "previous_entry_sha256",
})


class ReleaseAuditError(ValueError):
    """Base error for release audit ledger operations."""


class ReleaseAuditSchemaError(ReleaseAuditError):
    """Event or evidence schema validation failure."""


class ReleaseAuditHashChainError(ReleaseAuditError):
    """Ledger hash-chain or tamper validation failure."""


class ReleaseAuditStaleAppendError(ReleaseAuditError):
    """Stale append or previous hash mismatch at append time."""


class ReleaseAuditLocationError(ReleaseAuditError):
    """Ledger path location safety violation."""


@dataclass(frozen=True)
class ArtifactCustodyEvidence:
    """External custody evidence binding for broken historical Installer."""

    repository_id: int
    repository_node_id: str
    release_id: int
    release_tag: str
    asset_id: int
    asset_name: str
    size: int
    sha256: str
    custody_path: str
    captured_at: str
    known_broken_evidence_ref: str
    known_broken_evidence_sha256: str
    qualification_status: Literal["KNOWN_BROKEN_UNQUALIFIED"] = QUALIFICATION_STATUS_KNOWN_BROKEN

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError as err:
            raise KeyError(key) from err

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactCustodyEvidence:
        return cls(
            repository_id=data["repository_id"],
            repository_node_id=data["repository_node_id"],
            release_id=data["release_id"],
            release_tag=data["release_tag"],
            asset_id=data["asset_id"],
            asset_name=data["asset_name"],
            size=data["size"],
            sha256=data["sha256"],
            custody_path=data["custody_path"],
            captured_at=data["captured_at"],
            known_broken_evidence_ref=data["known_broken_evidence_ref"],
            known_broken_evidence_sha256=data["known_broken_evidence_sha256"],
            qualification_status=data.get("qualification_status", QUALIFICATION_STATUS_KNOWN_BROKEN),
        )


@dataclass(frozen=True)
class ReleaseAuditEvent:
    """Single immutable release audit event record."""

    event_type: str
    target_repository_id: int
    target_repository_node_id: str
    target_owner: str
    target_name: str
    evidence: dict[str, Any]
    timestamp: str
    previous_entry_sha256: str | None

    def __post_init__(self) -> None:
        validate_release_audit_event(self)


def _validate_hex64(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _HEX64_RE.match(value):
        raise ReleaseAuditSchemaError(
            f"{field_name} must be a 64-character lowercase hex string, got {value!r}"
        )


def _validate_rfc3339(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _RFC3339_RE.match(value):
        raise ReleaseAuditSchemaError(
            f"{field_name} must be an RFC3339 UTC timestamp, got {value!r}"
        )


def _validate_custody_binding(custody_obj: Any) -> None:
    if is_dataclass(custody_obj) and not isinstance(custody_obj, type):
        c_dict = asdict(custody_obj)
    elif isinstance(custody_obj, dict):
        c_dict = custody_obj
    else:
        raise ReleaseAuditSchemaError(
            f"custody evidence must be a dict or ArtifactCustodyEvidence, got {type(custody_obj).__name__}"
        )

    ref = c_dict.get("known_broken_evidence_ref")
    if not isinstance(ref, str) or not ref.strip():
        raise ReleaseAuditSchemaError(
            "custody binding requires non-empty known_broken_evidence_ref"
        )

    sha = c_dict.get("known_broken_evidence_sha256")
    _validate_hex64(sha, "custody known_broken_evidence_sha256")

    qual = c_dict.get("qualification_status")
    if qual != QUALIFICATION_STATUS_KNOWN_BROKEN:
        raise ReleaseAuditSchemaError(
            f"custody qualification_status must be {QUALIFICATION_STATUS_KNOWN_BROKEN!r}, got {qual!r}"
        )

    # Validate additional custody fields if present
    if "repository_id" in c_dict:
        repo_id = c_dict["repository_id"]
        if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
            raise ReleaseAuditSchemaError("custody repository_id must be a positive integer")
    if "sha256" in c_dict:
        _validate_hex64(c_dict["sha256"], "custody sha256")
    if "captured_at" in c_dict:
        _validate_rfc3339(c_dict["captured_at"], "custody captured_at")


def validate_release_audit_event(event: ReleaseAuditEvent) -> None:
    """Validate full schema constraints for a ReleaseAuditEvent."""
    if event.event_type not in SUPPORTED_EVENT_TYPES:
        raise ReleaseAuditSchemaError(
            f"event_type {event.event_type!r} is not supported; allowed: {sorted(SUPPORTED_EVENT_TYPES)}"
        )

    if isinstance(event.target_repository_id, bool) or not isinstance(event.target_repository_id, int) or event.target_repository_id <= 0:
        raise ReleaseAuditSchemaError(
            f"target_repository_id must be a positive integer, got {event.target_repository_id!r}"
        )

    if not isinstance(event.target_repository_node_id, str) or not event.target_repository_node_id.strip():
        raise ReleaseAuditSchemaError("target_repository_node_id must be a non-empty string")

    if not isinstance(event.target_owner, str) or not event.target_owner.strip():
        raise ReleaseAuditSchemaError("target_owner must be a non-empty string")

    if not isinstance(event.target_name, str) or not event.target_name.strip():
        raise ReleaseAuditSchemaError("target_name must be a non-empty string")

    _validate_rfc3339(event.timestamp, "timestamp")

    if event.previous_entry_sha256 is not None:
        _validate_hex64(event.previous_entry_sha256, "previous_entry_sha256")

    if not isinstance(event.evidence, dict):
        raise ReleaseAuditSchemaError(
            f"evidence must be a dict, got {type(event.evidence).__name__}"
        )

    if event.event_type in (EVENT_TYPE_RETIREMENT_EVIDENCE_READY, EVENT_TYPE_RETIREMENT_PRECONDITIONS_RECORDED):
        _validate_retirement_evidence(event.evidence)
    elif event.event_type == EVENT_TYPE_INSTALLER_REPOSITORY_DELETED:
        _validate_deleted_evidence(event.evidence)


def _validate_retirement_evidence(evidence: dict[str, Any]) -> None:
    if "delete_authorized" in evidence:
        raise ReleaseAuditSchemaError(
            "delete_authorized field is forbidden; RETIREMENT_EVIDENCE_READY records evidence only "
            "and cannot authorize deletion"
        )

    # Forensic inventory digest
    forensic_digest = (
        evidence.get("forensic_inventory_digest")
        or evidence.get("complete_forensic_inventory_sha256")
        or evidence.get("forensic_inventory_sha256")
    )
    if not forensic_digest:
        raise ReleaseAuditSchemaError(
            "RETIREMENT_EVIDENCE_READY requires forensic inventory digest (e.g. forensic_inventory_digest)"
        )
    _validate_hex64(forensic_digest, "forensic inventory digest")

    # Custody binding
    custody = evidence.get("custody") or evidence.get("installer_custody") or evidence.get("artifact_custody")
    if custody is not None:
        _validate_custody_binding(custody)
    else:
        # Check if flattened custody fields exist
        if "known_broken_evidence_ref" not in evidence or "known_broken_evidence_sha256" not in evidence:
            raise ReleaseAuditSchemaError(
                "RETIREMENT_EVIDENCE_READY requires exact Installer custody binding "
                "(including known_broken_evidence_ref, known_broken_evidence_sha256, and qualification_status)"
            )
        _validate_custody_binding(evidence)

    # Dependency input digest
    dep_in = evidence.get("dependency_input_digest") or evidence.get("dependency_input_snapshot_sha256")
    if not dep_in:
        raise ReleaseAuditSchemaError("RETIREMENT_EVIDENCE_READY requires dependency_input_digest")
    _validate_hex64(dep_in, "dependency_input_digest")

    # Dependency result digest
    dep_res = evidence.get("dependency_result_digest") or evidence.get("dependency_audit_result_sha256")
    if not dep_res:
        raise ReleaseAuditSchemaError("RETIREMENT_EVIDENCE_READY requires dependency_result_digest")
    _validate_hex64(dep_res, "dependency_result_digest")

    # Replacement readiness digest
    rep_ready = evidence.get("replacement_readiness_digest") or evidence.get("replacement_readiness_sha256")
    if not rep_ready:
        raise ReleaseAuditSchemaError("RETIREMENT_EVIDENCE_READY requires replacement_readiness_digest")
    _validate_hex64(rep_ready, "replacement_readiness_digest")

    # Owner disposition
    disp = evidence.get("owner_disposition")
    if disp != OWNER_DISPOSITION_DELETE:
        raise ReleaseAuditSchemaError(
            f"RETIREMENT_EVIDENCE_READY requires owner_disposition={OWNER_DISPOSITION_DELETE!r}, got {disp!r}"
        )


def _validate_deleted_evidence(evidence: dict[str, Any]) -> None:
    result = evidence.get("result")
    if result != VERIFIED_DELETED_RESULT:
        raise ReleaseAuditSchemaError(
            f"INSTALLER_REPOSITORY_DELETED requires result={VERIFIED_DELETED_RESULT!r}, got {result!r}"
        )

    exec_time = evidence.get("execution_timestamp") or evidence.get("deleted_at")
    if not exec_time:
        raise ReleaseAuditSchemaError("INSTALLER_REPOSITORY_DELETED requires execution_timestamp")
    _validate_rfc3339(exec_time, "execution_timestamp")

    live_ver = (
        evidence.get("post_delete_live_verification_digest")
        or evidence.get("post_delete_verification_digest")
        or evidence.get("post_delete_live_verification_sha256")
    )
    if not live_ver:
        raise ReleaseAuditSchemaError(
            "INSTALLER_REPOSITORY_DELETED requires post_delete_live_verification_digest"
        )
    _validate_hex64(live_ver, "post_delete_live_verification_digest")

    dep_ver = (
        evidence.get("post_delete_dependency_verification_digest")
        or evidence.get("post_delete_dependency_digest")
        or evidence.get("post_delete_dependency_verification_sha256")
    )
    if not dep_ver:
        raise ReleaseAuditSchemaError(
            "INSTALLER_REPOSITORY_DELETED requires post_delete_dependency_verification_digest"
        )
    _validate_hex64(dep_ver, "post_delete_dependency_verification_digest")


def _normalize_obj(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return _normalize_obj(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _normalize_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_obj(x) for x in obj]
    return obj


def _event_to_dict(event: ReleaseAuditEvent) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "target_repository_id": event.target_repository_id,
        "target_repository_node_id": event.target_repository_node_id,
        "target_owner": event.target_owner,
        "target_name": event.target_name,
        "evidence": _normalize_obj(event.evidence),
        "timestamp": event.timestamp,
        "previous_entry_sha256": event.previous_entry_sha256,
    }


def serialize_event(event: ReleaseAuditEvent) -> bytes:
    """Serialize event to strict canonical JSON bytes."""
    doc = _event_to_dict(event)
    return canonical_json_dumps(doc)


def compute_entry_sha256(event: ReleaseAuditEvent) -> str:
    """Compute SHA-256 hex digest of an event's canonical JSON serialization."""
    return hashlib.sha256(serialize_event(event)).hexdigest()


def check_ledger_path_safety(path: Path, target_owner: str, target_name: str) -> None:
    """Ensure ledger path does not reside inside the target retiring repository."""
    resolved = path.resolve()
    target_lower = target_name.lower()
    owner_lower = target_owner.lower()

    for part in resolved.parts:
        part_lower = part.lower()
        if part_lower == target_lower:
            raise ReleaseAuditLocationError(
                f"Authoritative ledger path cannot reside inside retiring repository: {resolved}"
            )
        if part_lower in (f"{owner_lower}/{target_lower}", f"{owner_lower}\\{target_lower}", f"{owner_lower}-{target_lower}"):
            raise ReleaseAuditLocationError(
                f"Authoritative ledger path cannot reside inside retiring repository: {resolved}"
            )


def verify_release_audit_ledger(path: Path) -> tuple[ReleaseAuditEvent, ...]:
    """Verify integrity and hash-chain of an append-only release audit ledger file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Ledger file does not exist: {path}")
    if not path.is_file():
        raise ReleaseAuditError(f"Ledger path is not a regular file: {path}")
    if path.stat().st_size == 0:
        return ()

    raw_data = path.read_bytes()
    if not raw_data.endswith(b"\n"):
        raise ReleaseAuditHashChainError("Ledger file must terminate with LF")

    lines = raw_data.split(b"\n")
    if lines[-1] == b"":
        lines.pop()

    verified_events: list[ReleaseAuditEvent] = []
    prev_sha: str | None = None
    target_identity: tuple[int, str, str, str] | None = None

    for line_idx, line in enumerate(lines, start=1):
        if not line:
            raise ReleaseAuditHashChainError(f"Line {line_idx}: empty line in ledger")
        if b"\r" in line:
            raise ReleaseAuditHashChainError(f"Line {line_idx}: CRLF detected, must be LF only")

        try:
            doc = canonical_json_loads(line)
        except Exception as err:
            raise ReleaseAuditHashChainError(
                f"Line {line_idx}: invalid canonical JSON: {err}"
            ) from err

        if not isinstance(doc, dict):
            raise ReleaseAuditSchemaError(f"Line {line_idx}: record must be a JSON object")

        if set(doc.keys()) != _EVENT_TOP_LEVEL_KEYS:
            raise ReleaseAuditSchemaError(
                f"Line {line_idx}: top-level keys mismatch: got {set(doc.keys())}, expected {_EVENT_TOP_LEVEL_KEYS}"
            )

        event_prev_sha = doc["previous_entry_sha256"]
        if line_idx == 1:
            if event_prev_sha is not None:
                raise ReleaseAuditHashChainError(
                    f"Line 1: initial event must have previous_entry_sha256=None, got {event_prev_sha!r}"
                )
        else:
            if event_prev_sha != prev_sha:
                raise ReleaseAuditHashChainError(
                    f"Line {line_idx}: broken hash chain: record previous_entry_sha256={event_prev_sha!r} "
                    f"does not match previous computed SHA-256={prev_sha!r}"
                )

        event = ReleaseAuditEvent(
            event_type=doc["event_type"],
            target_repository_id=doc["target_repository_id"],
            target_repository_node_id=doc["target_repository_node_id"],
            target_owner=doc["target_owner"],
            target_name=doc["target_name"],
            evidence=doc["evidence"],
            timestamp=doc["timestamp"],
            previous_entry_sha256=event_prev_sha,
        )

        event_target = (
            event.target_repository_id,
            event.target_repository_node_id,
            event.target_owner,
            event.target_name,
        )
        if target_identity is None:
            target_identity = event_target
        elif event_target != target_identity:
            raise ReleaseAuditSchemaError(
                f"Line {line_idx}: target repository identity {event_target} "
                f"does not match initial ledger identity {target_identity}"
            )

        computed_sha = hashlib.sha256(canonical_json_dumps(doc)).hexdigest()
        prev_sha = computed_sha
        verified_events.append(event)

    return tuple(verified_events)


def append_release_audit_event(
    path: Path,
    event: ReleaseAuditEvent,
    expected_previous_sha256: str | None,
) -> str:
    """Append a validated event to the ledger and return its SHA-256 hash."""
    path = Path(path)
    check_ledger_path_safety(path, event.target_owner, event.target_name)
    validate_release_audit_event(event)

    if path.is_file() and path.stat().st_size > 0:
        existing_events = verify_release_audit_ledger(path)
        if not existing_events:
            tip_sha: str | None = None
        else:
            tip_sha = compute_entry_sha256(existing_events[-1])
    else:
        existing_events = ()
        tip_sha = None

    if tip_sha is None:
        if event.previous_entry_sha256 is not None:
            raise ReleaseAuditHashChainError(
                f"Initial event in ledger must have previous_entry_sha256=None, got {event.previous_entry_sha256!r}"
            )
        if expected_previous_sha256 is not None:
            raise ReleaseAuditStaleAppendError(
                f"Stale append: ledger is empty but expected_previous_sha256={expected_previous_sha256!r}"
            )
    else:
        if expected_previous_sha256 != tip_sha:
            raise ReleaseAuditStaleAppendError(
                f"Stale append: expected_previous_sha256={expected_previous_sha256!r} "
                f"does not match current ledger tip={tip_sha!r}"
            )
        if event.previous_entry_sha256 != expected_previous_sha256:
            raise ReleaseAuditHashChainError(
                f"Event previous_entry_sha256={event.previous_entry_sha256!r} "
                f"does not match expected_previous_sha256={expected_previous_sha256!r}"
            )

    if existing_events:
        first_ev = existing_events[0]
        if (
            event.target_repository_id != first_ev.target_repository_id
            or event.target_repository_node_id != first_ev.target_repository_node_id
            or event.target_owner != first_ev.target_owner
            or event.target_name != first_ev.target_name
        ):
            raise ReleaseAuditSchemaError(
                "Event target repository identity does not match existing ledger target repository"
            )

    serialized_bytes = serialize_event(event)
    new_entry_sha = hashlib.sha256(serialized_bytes).hexdigest()

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as f:
        f.write(serialized_bytes + b"\n")
        f.flush()
        os.fsync(f.fileno())

    return new_entry_sha
