from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sys
import threading
from typing import Any, Literal, Protocol

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from neko_launcher.updater.canonical_json import (  # noqa: E402
    canonical_json_dumps,
    canonical_json_loads,
)
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2  # noqa: E402

from derive_version import ReleaseAllocation, ReleaseTargetIntent  # noqa: E402
from production_sequence_ledger import (  # noqa: E402
    AuthenticatedHistorySnapshot,
    AuthenticatedProductionBinding,
    ReconciledSequenceAuthority,
    ReleaseAuthorityReconciliationRequired,
    ReleaseAuthorityStale,
    ReleaseProvenanceReconciliationRequired,
    SequenceAuthorityError,
    SequenceAuthoritySession,
    SequenceLedgerEvent,
    SequenceLedgerGenesis,
    initialize_genesis,
    open_authority_session,
    reconcile_ledger_with_authenticated_history,
)


class ProductionHistoryEvidenceMissing(SequenceAuthorityError):
    """Raised when expected historical release evidence is missing."""


class ProductionHistoryEvidenceChanged(SequenceAuthorityError):
    """Raised when historical release evidence has changed or does not match expectations."""


class AuthenticatedHistoryProvider(Protocol):
    def load(self) -> AuthenticatedHistorySnapshot: ...


@dataclass(frozen=True)
class AuthenticatedEnvelopeRecord:
    source_id: str
    source_kind: Literal["custody", "live_updates"]
    envelope_bytes: bytes
    provenance_source_commit: str | None


class CompositeAuthenticatedHistoryProvider:
    def __init__(
        self,
        *,
        enumerate_records: Callable[[], tuple[AuthenticatedEnvelopeRecord, ...]],
        trusted_public_keys: Mapping[str, bytes],
    ) -> None:
        self._enumerate_records = enumerate_records
        self._trusted_public_keys = trusted_public_keys

    def load(self) -> AuthenticatedHistorySnapshot:
        records = self._enumerate_records()
        bindings_by_sequence: dict[int, AuthenticatedProductionBinding] = {}
        provenance_by_sequence: dict[int, str] = {}
        live_updates_sequences: set[int] = set()

        for rec in records:
            if rec.source_kind not in ("custody", "live_updates"):
                raise ValueError(f"Unknown source_kind: {rec.source_kind!r}")

            if rec.source_kind == "live_updates" and rec.provenance_source_commit is not None:
                raise ValueError("Live updates record must have provenance_source_commit=None")

            try:
                env_doc = canonical_json_loads(rec.envelope_bytes)
            except Exception as err:
                raise ValueError(f"Malformed canonical JSON envelope for {rec.source_id}: {err}") from err

            release_set, payload_sha256 = verify_release_envelope_v2(env_doc, self._trusted_public_keys)
            seq = release_set.release_sequence
            rel_id = release_set.release_id
            key_id = env_doc["key_id"]
            envelope_sha256 = hashlib.sha256(rec.envelope_bytes).hexdigest()

            binding = AuthenticatedProductionBinding(
                sequence=seq,
                release_id=rel_id,
                payload_sha256=payload_sha256,
                envelope_sha256=envelope_sha256,
                key_id=key_id,
            )

            if seq in bindings_by_sequence:
                if bindings_by_sequence[seq] != binding:
                    raise ReleaseAuthorityReconciliationRequired(
                        f"Conflicting signed bindings for sequence {seq}: "
                        f"{bindings_by_sequence[seq]} vs {binding}"
                    )
            else:
                bindings_by_sequence[seq] = binding

            if rec.provenance_source_commit is not None:
                if seq in provenance_by_sequence:
                    if provenance_by_sequence[seq] != rec.provenance_source_commit:
                        raise ReleaseProvenanceReconciliationRequired(
                            f"Conflicting non-null provenance source commits for sequence {seq}: "
                            f"{provenance_by_sequence[seq]} vs {rec.provenance_source_commit}"
                        )
                else:
                    provenance_by_sequence[seq] = rec.provenance_source_commit

            if rec.source_kind == "live_updates":
                live_updates_sequences.add(seq)

        highest = max(bindings_by_sequence.keys()) if bindings_by_sequence else 0

        bindings_data = [
            {
                "envelope_sha256": b.envelope_sha256,
                "key_id": b.key_id,
                "payload_sha256": b.payload_sha256,
                "release_id": b.release_id,
                "sequence": b.sequence,
            }
            for seq, b in sorted(bindings_by_sequence.items())
        ]
        authenticated_bindings_sha256 = hashlib.sha256(canonical_json_dumps(bindings_data)).hexdigest()

        snapshot_data = {
            "authenticated_bindings": bindings_data,
            "live_updates_sequences": sorted(live_updates_sequences),
            "provenance_source_commit_by_sequence": {
                str(s): c for s, c in sorted(provenance_by_sequence.items())
            },
            "records": [
                {
                    "envelope_sha256": hashlib.sha256(r.envelope_bytes).hexdigest(),
                    "provenance_source_commit": r.provenance_source_commit,
                    "source_id": r.source_id,
                    "source_kind": r.source_kind,
                }
                for r in sorted(records, key=lambda r: (r.source_kind, r.source_id))
            ],
        }
        snapshot_sha256 = hashlib.sha256(canonical_json_dumps(snapshot_data)).hexdigest()

        return AuthenticatedHistorySnapshot(
            bindings_by_sequence=bindings_by_sequence,
            provenance_source_commit_by_sequence=provenance_by_sequence,
            live_updates_sequences=frozenset(live_updates_sequences),
            highest_authenticated_sequence=highest,
            authenticated_bindings_sha256=authenticated_bindings_sha256,
            snapshot_sha256=snapshot_sha256,
        )


_CUSTODY_INDEX_KEYS = frozenset({"schema_version", "entries"})
_CUSTODY_ENTRY_KEYS = frozenset(
    {"source_id", "source_kind", "envelope_relpath", "envelope_sha256", "provenance_source_commit"}
)


def load_custody_records(custody_root: Path) -> tuple[AuthenticatedEnvelopeRecord, ...]:
    index_file = custody_root / "history-index-v1.json"
    if not index_file.is_file():
        return ()

    index_bytes = index_file.read_bytes()
    try:
        index_doc = canonical_json_loads(index_bytes)
    except Exception as err:
        raise ValueError(f"Malformed JSON in custody index: {err}") from err

    if canonical_json_dumps(index_doc) != index_bytes:
        raise ValueError("history-index-v1.json contains non-canonical JSON")

    if not isinstance(index_doc, dict) or set(index_doc.keys()) != _CUSTODY_INDEX_KEYS:
        raise ValueError("history-index-v1.json violates closed schema")

    if index_doc["schema_version"] != 1:
        raise ValueError(f"Unsupported schema_version: {index_doc['schema_version']}")

    entries = index_doc["entries"]
    if not isinstance(entries, list):
        raise ValueError("history-index-v1.json entries must be a list")

    seen_source_ids: set[str] = set()
    records: list[AuthenticatedEnvelopeRecord] = []

    for entry in entries:
        if not isinstance(entry, dict) or set(entry.keys()) != _CUSTODY_ENTRY_KEYS:
            raise ValueError("custody entry violates closed schema")

        source_id = entry["source_id"]
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("Invalid source_id in custody entry")
        if source_id in seen_source_ids:
            raise ValueError(f"Duplicate source_id in custody index: {source_id}")
        seen_source_ids.add(source_id)

        if entry["source_kind"] != "custody":
            raise ValueError(f"Invalid source_kind in custody index: {entry['source_kind']}")

        relpath_str = entry["envelope_relpath"]
        if not isinstance(relpath_str, str):
            raise ValueError("envelope_relpath must be a string")
        rel_path = Path(relpath_str)
        if (
            rel_path.is_absolute()
            or ".." in rel_path.parts
            or rel_path.parts[0] != "envelopes"
            or len(rel_path.parts) != 2
        ):
            raise ValueError(f"envelope_relpath violates confinement: {relpath_str}")

        expected_envelope_sha = entry["envelope_sha256"]
        if rel_path.name != f"{expected_envelope_sha}.json":
            raise ValueError("envelope_relpath name mismatch with envelope_sha256")

        envelope_file = custody_root / rel_path
        if not envelope_file.is_file():
            raise ValueError(f"Custody envelope file missing: {envelope_file}")

        envelope_bytes = envelope_file.read_bytes()
        if hashlib.sha256(envelope_bytes).hexdigest() != expected_envelope_sha:
            raise ValueError(f"Envelope bytes mismatch for {envelope_file}")

        try:
            parsed_env = canonical_json_loads(envelope_bytes)
            if canonical_json_dumps(parsed_env) != envelope_bytes:
                raise ValueError("Envelope file is non-canonical JSON")
        except Exception as err:
            raise ValueError(f"Envelope file is non-canonical JSON: {err}") from err

        prov = entry["provenance_source_commit"]
        if prov is not None and (not isinstance(prov, str) or len(prov) != 40):
            raise ValueError(f"Invalid provenance_source_commit: {prov}")

        records.append(
            AuthenticatedEnvelopeRecord(
                source_id=source_id,
                source_kind="custody",
                envelope_bytes=envelope_bytes,
                provenance_source_commit=prov,
            )
        )

    return tuple(records)


def append_custody_record(
    custody_root: Path,
    record: AuthenticatedEnvelopeRecord,
    *,
    expected_index_sha256: str | None,
) -> str:
    if record.source_kind != "custody":
        raise ValueError("append_custody_record only accepts source_kind='custody'")

    try:
        parsed = canonical_json_loads(record.envelope_bytes)
        if canonical_json_dumps(parsed) != record.envelope_bytes:
            raise ValueError("record.envelope_bytes must be canonical JSON")
    except Exception as err:
        raise ValueError(f"record.envelope_bytes is not canonical JSON: {err}") from err

    envelope_sha256 = hashlib.sha256(record.envelope_bytes).hexdigest()
    index_file = custody_root / "history-index-v1.json"

    if index_file.is_file():
        current_index_bytes = index_file.read_bytes()
        current_index_sha = hashlib.sha256(current_index_bytes).hexdigest()
        if expected_index_sha256 is None:
            raise ValueError("stale index: expected_index_sha256 is None but index already exists")
        if expected_index_sha256 != current_index_sha:
            raise ValueError(
                f"stale index: expected {expected_index_sha256} but index sha is {current_index_sha}"
            )
        index_doc = canonical_json_loads(current_index_bytes)
        entries: list[dict[str, Any]] = list(index_doc.get("entries", []))
    else:
        if expected_index_sha256 is not None:
            raise ValueError("stale index: expected_index_sha256 must be None for first creation")
        entries = []
        current_index_sha = None

    # Idempotency / conflict checks
    for e in entries:
        if e["source_id"] == record.source_id:
            if (
                e["envelope_sha256"] == envelope_sha256
                and e["provenance_source_commit"] == record.provenance_source_commit
            ):
                return current_index_sha or ""
            raise ValueError(f"Conflicting entry for source_id {record.source_id}")

    envelopes_dir = custody_root / "envelopes"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    envelope_file = envelopes_dir / f"{envelope_sha256}.json"

    if envelope_file.is_file():
        existing_env_bytes = envelope_file.read_bytes()
        if existing_env_bytes != record.envelope_bytes:
            raise ValueError(f"Conflicting envelope bytes for {envelope_sha256}")
    else:
        temp_env = envelopes_dir / f"tmp_{envelope_sha256}_{os.getpid()}_{threading.get_ident()}.json"
        with open(temp_env, "wb") as f:
            f.write(record.envelope_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_env, envelope_file)
        if envelope_file.read_bytes() != record.envelope_bytes:
            raise ValueError("Envelope file readback failed")

    new_entry = {
        "envelope_relpath": f"envelopes/{envelope_sha256}.json",
        "envelope_sha256": envelope_sha256,
        "provenance_source_commit": record.provenance_source_commit,
        "source_id": record.source_id,
        "source_kind": "custody",
    }
    entries.append(new_entry)
    entries.sort(key=lambda item: item["source_id"])

    new_index_doc = {
        "entries": entries,
        "schema_version": 1,
    }
    new_index_bytes = canonical_json_dumps(new_index_doc)

    custody_root.mkdir(parents=True, exist_ok=True)
    temp_index = custody_root / f"tmp_index_{os.getpid()}_{threading.get_ident()}.json"
    with open(temp_index, "wb") as f:
        f.write(new_index_bytes)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_index, index_file)

    if index_file.read_bytes() != new_index_bytes:
        raise ValueError("Custody index readback failed")

    return hashlib.sha256(new_index_bytes).hexdigest()


def bootstrap_sequence_ledger(
    *,
    ledger_path: Path,
    history_provider: AuthenticatedHistoryProvider,
    expected_floor: AuthenticatedProductionBinding,
    expected_floor_provenance_source_commit: str | None,
) -> SequenceLedgerGenesis:
    with open_authority_session(ledger_path) as session:
        if session.path.is_file() and session.path.stat().st_size > 0:
            verified = session.read_verified()
            if (
                verified.genesis.floor_binding != expected_floor
                or verified.genesis.floor_provenance_source_commit != expected_floor_provenance_source_commit
            ):
                raise ProductionHistoryEvidenceChanged(
                    "Existing ledger genesis does not match expected floor binding or provenance"
                )
            return verified.genesis

        snapshot = history_provider.load()

        if expected_floor.sequence not in snapshot.bindings_by_sequence:
            raise ProductionHistoryEvidenceMissing(
                f"Floor sequence {expected_floor.sequence} not found in authenticated history"
            )

        actual_floor = snapshot.bindings_by_sequence[expected_floor.sequence]
        if actual_floor != expected_floor:
            raise ProductionHistoryEvidenceChanged(
                f"Authenticated floor binding mismatch: expected {expected_floor}, got {actual_floor}"
            )

        if snapshot.highest_authenticated_sequence != expected_floor.sequence:
            raise ProductionHistoryEvidenceChanged(
                f"Authenticated history highest sequence ({snapshot.highest_authenticated_sequence}) "
                f"!= expected floor sequence ({expected_floor.sequence})"
            )

        actual_prov = snapshot.provenance_source_commit_by_sequence.get(expected_floor.sequence)
        if actual_prov != expected_floor_provenance_source_commit:
            raise ProductionHistoryEvidenceChanged(
                f"Floor provenance source commit mismatch: expected {expected_floor_provenance_source_commit}, "
                f"got {actual_prov}"
            )

        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        genesis = SequenceLedgerGenesis(
            record_type="GENESIS",
            floor_binding=expected_floor,
            floor_provenance_source_commit=expected_floor_provenance_source_commit,
            timestamp=now_ts,
            previous_entry_sha256=None,
        )

        initialize_genesis(session, genesis)
        verified = session.read_verified()
        if verified.genesis != genesis:
            raise SequenceAuthorityError("Genesis readback verification failed")
        return verified.genesis


def reserve_release_sequence(
    *,
    ledger_path: Path,
    history_provider: AuthenticatedHistoryProvider,
    target: ReleaseTargetIntent,
    source_commit: str,
    component_set_sha256: str,
) -> ReleaseAllocation:
    with open_authority_session(ledger_path) as session:
        if not session.path.is_file() or session.path.stat().st_size == 0:
            raise SequenceAuthorityError("Sequence ledger has not been initialized with genesis")

        verified = session.read_verified()
        snapshot = history_provider.load()

        authority = reconcile_ledger_with_authenticated_history(
            ledger=verified,
            authenticated_history=snapshot,
        )

        if authority.recovery_action is not None:
            raise ReleaseAuthorityReconciliationRequired(
                f"Ledger reconciliation required: {authority.recovery_action} for sequence {authority.recovery_sequence}"
            )

        next_seq = authority.next_unused_sequence
        release_id = f"stable-{next_seq:04d}"
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        event = SequenceLedgerEvent(
            record_type="EVENT",
            sequence=next_seq,
            release_id=release_id,
            status="RESERVED",
            version=target.target.lstrip("v"),
            channel="stable",
            source_commit=source_commit,
            component_set_sha256=component_set_sha256,
            payload_sha256=None,
            envelope_sha256=None,
            key_id=None,
            timestamp=now_ts,
            previous_entry_sha256=verified.latest_entry_sha256,
        )

        entry_sha256 = session.append(event, expected_previous_sha256=verified.latest_entry_sha256)
        re_verified = session.read_verified()
        if re_verified.latest_entry_sha256 != entry_sha256:
            raise SequenceAuthorityError("Append readback mismatch")

        return ReleaseAllocation(
            sequence=next_seq,
            release_id=release_id,
            ledger_entry_sha256=entry_sha256,
            component_set_sha256=component_set_sha256,
            authenticated_bindings_sha256=authority.authenticated_bindings_sha256,
            history_snapshot_sha256=authority.history_snapshot_sha256,
        )


def fresh_reconcile_locked(
    session: SequenceAuthoritySession,
    history_provider: AuthenticatedHistoryProvider,
) -> ReconciledSequenceAuthority:
    if not session.is_locked:
        raise ReleaseAuthorityStale("Session lock must be held for fresh reconciliation")
    verified = session.read_verified()
    snapshot = history_provider.load()
    return reconcile_ledger_with_authenticated_history(
        ledger=verified,
        authenticated_history=snapshot,
    )
