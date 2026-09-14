#!/usr/bin/env python3
"""Append-Only Production Sequence Authority Ledger and serialization session."""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sys
import threading
from typing import Any, Literal

# Add launcher/src to sys.path so neko_launcher modules can be imported
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from neko_launcher.updater.canonical_json import (  # noqa: E402
    canonical_json_dumps,
    canonical_json_loads,
)

_VALID_LIFECYCLE_STATUSES = frozenset(
    {"RESERVED", "SIGNED", "PUBLISHED", "FAILED", "RETIRED"}
)

_ALLOWED_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "START": frozenset({"RESERVED"}),
    "RESERVED": frozenset({"SIGNED", "FAILED"}),
    "SIGNED": frozenset({"PUBLISHED", "FAILED"}),
    "PUBLISHED": frozenset({"RETIRED"}),
    "FAILED": frozenset(),
    "RETIRED": frozenset(),
}

_IN_PROCESS_LOCKED_PATHS: set[Path] = set()
_IN_PROCESS_LOCK = threading.Lock()


class SequenceAuthorityError(Exception):
    """Base error for sequence authority ledger violations."""


class ReleaseAuthorityReconciliationRequired(SequenceAuthorityError):
    """Raised when authenticated history diverges from ledger authority."""

    def __init__(
        self,
        message: str = "RELEASE_AUTHORITY_RECONCILIATION_REQUIRED",
    ) -> None:
        super().__init__(f"RELEASE_AUTHORITY_RECONCILIATION_REQUIRED: {message}")


class ReleaseProvenanceReconciliationRequired(SequenceAuthorityError):
    """Raised when provenance source commit disagrees with recorded authority."""

    def __init__(
        self,
        message: str = "RELEASE_PROVENANCE_RECONCILIATION_REQUIRED",
    ) -> None:
        super().__init__(f"RELEASE_PROVENANCE_RECONCILIATION_REQUIRED: {message}")


class ReleaseAuthorityStale(SequenceAuthorityError):
    """Raised when authority state or lock is stale."""

    def __init__(self, message: str = "RELEASE_AUTHORITY_STALE") -> None:
        super().__init__(f"RELEASE_AUTHORITY_STALE: {message}")


class SequenceAuthorityLockError(ReleaseAuthorityStale):
    """Raised when ledger lock cannot be acquired or is already held."""


@dataclass(frozen=True)
class AuthenticatedProductionBinding:
    sequence: int
    release_id: str
    payload_sha256: str
    envelope_sha256: str
    key_id: str


@dataclass(frozen=True)
class AuthenticatedHistorySnapshot:
    bindings_by_sequence: Mapping[int, AuthenticatedProductionBinding]
    provenance_source_commit_by_sequence: Mapping[int, str]
    live_updates_sequences: frozenset[int]
    highest_authenticated_sequence: int
    authenticated_bindings_sha256: str
    snapshot_sha256: str


@dataclass(frozen=True)
class SequenceLedgerGenesis:
    record_type: Literal["GENESIS"]
    floor_binding: AuthenticatedProductionBinding
    floor_provenance_source_commit: str | None
    timestamp: str
    previous_entry_sha256: None


@dataclass(frozen=True)
class SequenceLedgerEvent:
    record_type: Literal["EVENT"]
    sequence: int
    release_id: str
    status: Literal["RESERVED", "SIGNED", "PUBLISHED", "FAILED", "RETIRED"]
    version: str
    channel: str
    source_commit: str
    component_set_sha256: str
    payload_sha256: str | None
    envelope_sha256: str | None
    key_id: str | None
    timestamp: str
    previous_entry_sha256: str


@dataclass(frozen=True)
class VerifiedSequenceLedger:
    genesis: SequenceLedgerGenesis
    events: tuple[SequenceLedgerEvent, ...]
    latest_entry_sha256: str


@dataclass(frozen=True)
class ReconciledSequenceAuthority:
    authenticated_bindings_sha256: str
    history_snapshot_sha256: str
    genesis_floor_sequence: int
    latest_ledger_entry_sha256: str
    highest_authenticated_sequence: int
    highest_consumed_sequence: int
    next_unused_sequence: int
    recovery_action: Literal["SIGNED_APPEND_REQUIRED", "PUBLISHED_APPEND_REQUIRED"] | None = None
    recovery_sequence: int | None = None
    recovery_state: Literal["SIGNED_APPEND_REQUIRED", "PUBLISHED_APPEND_REQUIRED"] | None = None

    def __post_init__(self) -> None:
        if self.recovery_action is not None and self.recovery_state is None:
            object.__setattr__(self, "recovery_state", self.recovery_action)
        elif self.recovery_state is not None and self.recovery_action is None:
            object.__setattr__(self, "recovery_action", self.recovery_state)


def _genesis_to_dict(genesis: SequenceLedgerGenesis) -> dict[str, Any]:
    return {
        "floor_binding": {
            "envelope_sha256": genesis.floor_binding.envelope_sha256,
            "key_id": genesis.floor_binding.key_id,
            "payload_sha256": genesis.floor_binding.payload_sha256,
            "release_id": genesis.floor_binding.release_id,
            "sequence": genesis.floor_binding.sequence,
        },
        "floor_provenance_source_commit": genesis.floor_provenance_source_commit,
        "previous_entry_sha256": None,
        "record_type": "GENESIS",
        "timestamp": genesis.timestamp,
    }


def _event_to_dict(event: SequenceLedgerEvent) -> dict[str, Any]:
    return {
        "channel": event.channel,
        "component_set_sha256": event.component_set_sha256,
        "envelope_sha256": event.envelope_sha256,
        "key_id": event.key_id,
        "payload_sha256": event.payload_sha256,
        "previous_entry_sha256": event.previous_entry_sha256,
        "record_type": "EVENT",
        "release_id": event.release_id,
        "sequence": event.sequence,
        "source_commit": event.source_commit,
        "status": event.status,
        "timestamp": event.timestamp,
        "version": event.version,
    }


def latest_sequence_state(
    events: tuple[SequenceLedgerEvent, ...], sequence: int
) -> SequenceLedgerEvent | None:
    """Return the most recent event for the given sequence, or None."""
    for event in reversed(events):
        if event.sequence == sequence:
            return event
    return None


def verify_ledger(path: Path) -> VerifiedSequenceLedger:
    """Verify full cryptographic hash chain and append-only lifecycle of a sequence ledger."""
    ledger_path = Path(path).resolve()
    if not ledger_path.is_file():
        raise SequenceAuthorityError(f"Sequence ledger file not found: {ledger_path}")

    raw_bytes = ledger_path.read_bytes()
    if not raw_bytes:
        raise SequenceAuthorityError(f"Sequence ledger file is empty: {ledger_path}")

    lines = raw_bytes.splitlines()
    if not lines:
        raise SequenceAuthorityError(f"Sequence ledger contains no lines: {ledger_path}")

    genesis: SequenceLedgerGenesis | None = None
    events: list[SequenceLedgerEvent] = []
    latest_entry_sha256: str | None = None
    events_by_seq: dict[int, list[SequenceLedgerEvent]] = {}
    signed_fields_by_seq: dict[int, tuple[str, str, str]] = {}

    for line_idx, line in enumerate(lines, start=1):
        if not line:
            raise SequenceAuthorityError(f"Empty line encountered at line {line_idx}")

        try:
            doc = canonical_json_loads(line)
        except Exception as err:
            raise SequenceAuthorityError(
                f"Line {line_idx} is not valid canonical UTF-8 JSON: {err}"
            ) from err

        if canonical_json_dumps(doc) != line:
            raise SequenceAuthorityError(
                f"Line {line_idx} has formatting drift from strict canonical JSON"
            )

        if not isinstance(doc, dict) or "body" not in doc or "entry_sha256" not in doc:
            raise SequenceAuthorityError(
                f"Line {line_idx} missing 'body' or 'entry_sha256' wrapper"
            )

        body = doc["body"]
        entry_sha = doc["entry_sha256"]

        if not isinstance(body, dict) or not isinstance(entry_sha, str):
            raise SequenceAuthorityError(
                f"Line {line_idx} has invalid body/entry_sha256 structure"
            )

        computed_entry_sha = hashlib.sha256(canonical_json_dumps(body)).hexdigest()
        if entry_sha != computed_entry_sha:
            raise SequenceAuthorityError(
                f"Line {line_idx} entry_sha256 digest mismatch: expected {computed_entry_sha}, got {entry_sha}"
            )

        record_type = body.get("record_type")
        if line_idx == 1:
            if record_type != "GENESIS":
                raise SequenceAuthorityError(
                    f"First record in ledger must be GENESIS, got {record_type!r}"
                )
            if body.get("previous_entry_sha256") is not None:
                raise SequenceAuthorityError(
                    "Genesis record must have previous_entry_sha256=None"
                )

            raw_floor = body.get("floor_binding")
            if not isinstance(raw_floor, dict):
                raise SequenceAuthorityError("Genesis record missing floor_binding dict")

            floor_binding = AuthenticatedProductionBinding(
                sequence=int(raw_floor["sequence"]),
                release_id=str(raw_floor["release_id"]),
                payload_sha256=str(raw_floor["payload_sha256"]),
                envelope_sha256=str(raw_floor["envelope_sha256"]),
                key_id=str(raw_floor["key_id"]),
            )
            if floor_binding.sequence <= 0:
                raise SequenceAuthorityError("Genesis floor sequence must be positive")

            genesis = SequenceLedgerGenesis(
                record_type="GENESIS",
                floor_binding=floor_binding,
                floor_provenance_source_commit=body.get("floor_provenance_source_commit"),
                timestamp=str(body.get("timestamp", "")),
                previous_entry_sha256=None,
            )
            latest_entry_sha256 = entry_sha
        else:
            if record_type != "EVENT":
                raise SequenceAuthorityError(
                    f"Subsequent ledger record at line {line_idx} must be EVENT, got {record_type!r}"
                )
            assert genesis is not None
            assert latest_entry_sha256 is not None

            prev_sha = body.get("previous_entry_sha256")
            if prev_sha != latest_entry_sha256:
                raise SequenceAuthorityError(
                    f"Line {line_idx} previous_entry_sha256 chain broken: expected {latest_entry_sha256}, got {prev_sha}"
                )

            seq = int(body["sequence"])
            if seq <= genesis.floor_binding.sequence:
                raise SequenceAuthorityError(
                    f"Line {line_idx} sequence {seq} must be greater than genesis floor sequence {genesis.floor_binding.sequence}"
                )

            status = body.get("status")
            if status not in _VALID_LIFECYCLE_STATUSES:
                raise SequenceAuthorityError(
                    f"Line {line_idx} unknown lifecycle status {status!r}"
                )

            event = SequenceLedgerEvent(
                record_type="EVENT",
                sequence=seq,
                release_id=str(body["release_id"]),
                status=status,
                version=str(body["version"]),
                channel=str(body["channel"]),
                source_commit=str(body["source_commit"]),
                component_set_sha256=str(body["component_set_sha256"]),
                payload_sha256=body.get("payload_sha256"),
                envelope_sha256=body.get("envelope_sha256"),
                key_id=body.get("key_id"),
                timestamp=str(body.get("timestamp", "")),
                previous_entry_sha256=str(prev_sha),
            )

            # Validate lifecycle and immutability for this sequence
            seq_history = events_by_seq.setdefault(seq, [])
            if not seq_history:
                if event.status != "RESERVED":
                    raise SequenceAuthorityError(
                        f"First event for sequence {seq} must be RESERVED, got {event.status}"
                    )
            else:
                first_event = seq_history[0]
                # Immutability of allocation fields
                if event.release_id != first_event.release_id:
                    raise SequenceAuthorityError(
                        f"Sequence {seq} release_id changed from {first_event.release_id} to {event.release_id}"
                    )
                if event.version != first_event.version:
                    raise SequenceAuthorityError(
                        f"Sequence {seq} version changed from {first_event.version} to {event.version}"
                    )
                if event.channel != first_event.channel:
                    raise SequenceAuthorityError(
                        f"Sequence {seq} channel changed from {first_event.channel} to {event.channel}"
                    )
                if event.source_commit != first_event.source_commit:
                    raise SequenceAuthorityError(
                        f"Sequence {seq} source_commit changed from {first_event.source_commit} to {event.source_commit}"
                    )
                if event.component_set_sha256 != first_event.component_set_sha256:
                    raise SequenceAuthorityError(
                        f"Sequence {seq} component_set_sha256 changed from {first_event.component_set_sha256} to {event.component_set_sha256}"
                    )

                prev_event = seq_history[-1]
                allowed_next = _ALLOWED_STATUS_TRANSITIONS.get(prev_event.status, frozenset())
                if event.status not in allowed_next:
                    raise SequenceAuthorityError(
                        f"Illegal status transition for sequence {seq}: {prev_event.status} -> {event.status}"
                    )

            if event.status == "SIGNED":
                if not event.payload_sha256 or not event.envelope_sha256 or not event.key_id:
                    raise SequenceAuthorityError(
                        f"Sequence {seq} SIGNED event missing payload_sha256, envelope_sha256, or key_id"
                    )
                signed_fields_by_seq[seq] = (
                    event.payload_sha256,
                    event.envelope_sha256,
                    event.key_id,
                )

            if seq in signed_fields_by_seq:
                expected_p, expected_e, expected_k = signed_fields_by_seq[seq]
                if event.payload_sha256 != expected_p:
                    raise SequenceAuthorityError(
                        f"Sequence {seq} payload_sha256 changed after SIGNED: {expected_p} vs {event.payload_sha256}"
                    )
                if event.envelope_sha256 != expected_e:
                    raise SequenceAuthorityError(
                        f"Sequence {seq} envelope_sha256 changed after SIGNED: {expected_e} vs {event.envelope_sha256}"
                    )
                if event.key_id != expected_k:
                    raise SequenceAuthorityError(
                        f"Sequence {seq} key_id changed after SIGNED: {expected_k} vs {event.key_id}"
                    )

            seq_history.append(event)
            events.append(event)
            latest_entry_sha256 = entry_sha

    if genesis is None or latest_entry_sha256 is None:
        raise SequenceAuthorityError("Sequence ledger has no valid genesis record")

    return VerifiedSequenceLedger(
        genesis=genesis,
        events=tuple(events),
        latest_entry_sha256=latest_entry_sha256,
    )


class SequenceAuthoritySession(AbstractContextManager["SequenceAuthoritySession"]):
    """Windows-locked serialization session for sequence authority operations."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._lock_file: Any | None = None
        self._is_locked: bool = False

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    def __enter__(self) -> SequenceAuthoritySession:
        with _IN_PROCESS_LOCK:
            if self.path in _IN_PROCESS_LOCKED_PATHS:
                raise SequenceAuthorityLockError(
                    f"Ledger lock already held in this process for {self.path}"
                )
            _IN_PROCESS_LOCKED_PATHS.add(self.path)

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = open(self.lock_path, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                self._lock_file.seek(0)
                if self._lock_file.tell() == 0:
                    self._lock_file.write(b"\x00")
                    self._lock_file.flush()
                self._lock_file.seek(0)
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._is_locked = True
        except (OSError, IOError) as err:
            with _IN_PROCESS_LOCK:
                _IN_PROCESS_LOCKED_PATHS.discard(self.path)
            try:
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None
            raise SequenceAuthorityLockError(
                f"Failed to acquire file lock for {self.path}: {err}"
            ) from err

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        try:
            if self._lock_file is not None and self._is_locked:
                if sys.platform == "win32":
                    import msvcrt

                    try:
                        self._lock_file.seek(0)
                        msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                else:
                    import fcntl

                    try:
                        fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
        finally:
            self._is_locked = False
            if self._lock_file is not None:
                try:
                    self._lock_file.close()
                except Exception:
                    pass
                self._lock_file = None
            with _IN_PROCESS_LOCK:
                _IN_PROCESS_LOCKED_PATHS.discard(self.path)

    def read_verified(self) -> VerifiedSequenceLedger:
        """Re-read and verify the ledger from disk without reacquiring the lock."""
        if not self._is_locked:
            raise SequenceAuthorityError("Session lock is not held")
        return verify_ledger(self.path)

    def append(self, event: SequenceLedgerEvent, expected_previous_sha256: str) -> str:
        """Append one validated event and fsync without reacquiring the lock."""
        if not self._is_locked:
            raise SequenceAuthorityError("Session lock is not held")

        ledger = self.read_verified()
        if expected_previous_sha256 != ledger.latest_entry_sha256:
            raise SequenceAuthorityError(
                f"Stale previous entry digest: expected {expected_previous_sha256}, current is {ledger.latest_entry_sha256}"
            )
        if event.previous_entry_sha256 != expected_previous_sha256:
            raise SequenceAuthorityError(
                f"Event previous_entry_sha256 {event.previous_entry_sha256} does not match expected {expected_previous_sha256}"
            )

        if event.sequence <= ledger.genesis.floor_binding.sequence:
            raise SequenceAuthorityError(
                f"Event sequence {event.sequence} must be greater than genesis floor {ledger.genesis.floor_binding.sequence}"
            )

        # Validate against existing sequence history in the ledger
        seq_events = [e for e in ledger.events if e.sequence == event.sequence]
        if not seq_events:
            if event.status != "RESERVED":
                raise SequenceAuthorityError(
                    f"First event for sequence {event.sequence} must be RESERVED, got {event.status}"
                )
        else:
            first_event = seq_events[0]
            if event.release_id != first_event.release_id:
                raise SequenceAuthorityError(
                    f"Sequence {event.sequence} release_id changed from {first_event.release_id} to {event.release_id}"
                )
            if event.version != first_event.version:
                raise SequenceAuthorityError(
                    f"Sequence {event.sequence} version changed from {first_event.version} to {event.version}"
                )
            if event.channel != first_event.channel:
                raise SequenceAuthorityError(
                    f"Sequence {event.sequence} channel changed from {first_event.channel} to {event.channel}"
                )
            if event.source_commit != first_event.source_commit:
                raise SequenceAuthorityError(
                    f"Sequence {event.sequence} source_commit changed from {first_event.source_commit} to {event.source_commit}"
                )
            if event.component_set_sha256 != first_event.component_set_sha256:
                raise SequenceAuthorityError(
                    f"Sequence {event.sequence} component_set_sha256 changed from {first_event.component_set_sha256} to {event.component_set_sha256}"
                )

            last_event = seq_events[-1]
            allowed_next = _ALLOWED_STATUS_TRANSITIONS.get(last_event.status, frozenset())
            if event.status not in allowed_next:
                raise SequenceAuthorityError(
                    f"Illegal status transition for sequence {event.sequence}: {last_event.status} -> {event.status}"
                )

            # If a signed event already exists, enforce immutability of signed fields
            signed_events = [e for e in seq_events if e.status == "SIGNED"]
            if signed_events:
                signed_ev = signed_events[0]
                if event.payload_sha256 != signed_ev.payload_sha256:
                    raise SequenceAuthorityError(
                        f"Sequence {event.sequence} payload_sha256 changed after SIGNED"
                    )
                if event.envelope_sha256 != signed_ev.envelope_sha256:
                    raise SequenceAuthorityError(
                        f"Sequence {event.sequence} envelope_sha256 changed after SIGNED"
                    )
                if event.key_id != signed_ev.key_id:
                    raise SequenceAuthorityError(
                        f"Sequence {event.sequence} key_id changed after SIGNED"
                    )

        if event.status == "SIGNED":
            if not event.payload_sha256 or not event.envelope_sha256 or not event.key_id:
                raise SequenceAuthorityError(
                    f"Sequence {event.sequence} SIGNED event missing payload_sha256, envelope_sha256, or key_id"
                )

        body_dict = _event_to_dict(event)
        body_bytes = canonical_json_dumps(body_dict)
        entry_sha256 = hashlib.sha256(body_bytes).hexdigest()

        record = {"body": body_dict, "entry_sha256": entry_sha256}
        line_bytes = canonical_json_dumps(record) + b"\n"

        with open(self.path, "a+b") as f:
            f.write(line_bytes)
            f.flush()
            os.fsync(f.fileno())

        return entry_sha256


def open_authority_session(path: Path) -> SequenceAuthoritySession:
    """Open and return a locked serialization session for the sequence ledger."""
    return SequenceAuthoritySession(path)


def initialize_genesis(
    session: SequenceAuthoritySession, genesis: SequenceLedgerGenesis
) -> str:
    """Initialize a new ledger file with its immutable genesis record.

    Legal only while session lock is held and only when the ledger file has no records.
    """
    if not isinstance(session, SequenceAuthoritySession):
        raise SequenceAuthorityError(
            "initialize_genesis requires an active SequenceAuthoritySession"
        )
    if not session.is_locked:
        raise SequenceAuthorityError("Session lock must be held to initialize genesis")

    if session.path.is_file() and session.path.stat().st_size > 0:
        raise SequenceAuthorityError(
            "Ledger file already has records; genesis is immutable and cannot be rewritten"
        )

    if genesis.record_type != "GENESIS":
        raise SequenceAuthorityError(
            f"Genesis record must have record_type='GENESIS', got {genesis.record_type!r}"
        )
    if genesis.previous_entry_sha256 is not None:
        raise SequenceAuthorityError(
            "Genesis record must have previous_entry_sha256=None"
        )
    if genesis.floor_binding.sequence <= 0:
        raise SequenceAuthorityError("Genesis floor sequence must be positive")

    body_dict = _genesis_to_dict(genesis)
    body_bytes = canonical_json_dumps(body_dict)
    entry_sha256 = hashlib.sha256(body_bytes).hexdigest()

    record = {"body": body_dict, "entry_sha256": entry_sha256}
    line_bytes = canonical_json_dumps(record) + b"\n"

    session.path.parent.mkdir(parents=True, exist_ok=True)
    with open(session.path, "wb") as f:
        f.write(line_bytes)
        f.flush()
        os.fsync(f.fileno())

    return entry_sha256


def append_event(
    path: Path, event: SequenceLedgerEvent, expected_previous_sha256: str
) -> str:
    """Convenience helper to append one event under a short-lived authority session."""
    with open_authority_session(path) as session:
        return session.append(event, expected_previous_sha256)


def reconcile_ledger_with_authenticated_history(
    *,
    ledger: VerifiedSequenceLedger,
    authenticated_history: AuthenticatedHistorySnapshot,
) -> ReconciledSequenceAuthority:
    """Reconcile verified ledger state with fresh authenticated production history."""
    floor_seq = ledger.genesis.floor_binding.sequence

    # Genesis floor binding must remain present and cryptographically identical forever
    if floor_seq not in authenticated_history.bindings_by_sequence:
        raise ReleaseAuthorityReconciliationRequired(
            f"Genesis floor sequence {floor_seq} missing from authenticated history"
        )

    history_floor = authenticated_history.bindings_by_sequence[floor_seq]
    if history_floor != ledger.genesis.floor_binding:
        raise ReleaseAuthorityReconciliationRequired(
            f"Genesis floor binding changed: history={history_floor} vs genesis={ledger.genesis.floor_binding}"
        )

    if ledger.genesis.floor_provenance_source_commit is not None:
        if floor_seq in authenticated_history.provenance_source_commit_by_sequence:
            prov = authenticated_history.provenance_source_commit_by_sequence[floor_seq]
            if prov is not None and prov != ledger.genesis.floor_provenance_source_commit:
                raise ReleaseProvenanceReconciliationRequired(
                    f"Genesis floor provenance mismatch: {prov} vs {ledger.genesis.floor_provenance_source_commit}"
                )

    recovery_action: Literal["SIGNED_APPEND_REQUIRED", "PUBLISHED_APPEND_REQUIRED"] | None = None
    recovery_seq: int | None = None

    # Check authenticated records above genesis floor
    for seq, auth_binding in sorted(authenticated_history.bindings_by_sequence.items()):
        if seq <= floor_seq:
            continue

        state = latest_sequence_state(ledger.events, seq)
        if state is None:
            raise ReleaseAuthorityReconciliationRequired(
                f"Authenticated sequence {seq} above genesis floor has no ledger allocation"
            )

        # Cryptographic fields check
        if auth_binding.release_id != state.release_id:
            raise ReleaseAuthorityReconciliationRequired(
                f"Sequence {seq} release_id mismatch: auth={auth_binding.release_id} vs ledger={state.release_id}"
            )
        if state.payload_sha256 is not None and auth_binding.payload_sha256 != state.payload_sha256:
            raise ReleaseAuthorityReconciliationRequired(
                f"Sequence {seq} payload_sha256 mismatch: auth={auth_binding.payload_sha256} vs ledger={state.payload_sha256}"
            )
        if state.envelope_sha256 is not None and auth_binding.envelope_sha256 != state.envelope_sha256:
            raise ReleaseAuthorityReconciliationRequired(
                f"Sequence {seq} envelope_sha256 mismatch: auth={auth_binding.envelope_sha256} vs ledger={state.envelope_sha256}"
            )
        if state.key_id is not None and auth_binding.key_id != state.key_id:
            raise ReleaseAuthorityReconciliationRequired(
                f"Sequence {seq} key_id mismatch: auth={auth_binding.key_id} vs ledger={state.key_id}"
            )

        # Provenance source commit check
        if seq in authenticated_history.provenance_source_commit_by_sequence:
            prov_commit = authenticated_history.provenance_source_commit_by_sequence[seq]
            if prov_commit is not None and prov_commit != state.source_commit:
                raise ReleaseProvenanceReconciliationRequired(
                    f"Sequence {seq} provenance source commit {prov_commit} disagrees with reserved {state.source_commit}"
                )

        # Recovery classification
        if state.status == "RESERVED":
            recovery_action = "SIGNED_APPEND_REQUIRED"
            recovery_seq = seq
        elif state.status == "SIGNED":
            if seq in authenticated_history.live_updates_sequences:
                recovery_action = "PUBLISHED_APPEND_REQUIRED"
                recovery_seq = seq
        elif state.status == "PUBLISHED":
            pass
        elif state.status in ("FAILED", "RETIRED"):
            if seq in authenticated_history.live_updates_sequences:
                raise ReleaseAuthorityReconciliationRequired(
                    f"Terminal sequence {seq} ({state.status}) present in live updates"
                )
        else:
            raise ReleaseAuthorityReconciliationRequired(
                f"Unknown ledger status {state.status} for sequence {seq}"
            )

    highest_authenticated = max(
        authenticated_history.bindings_by_sequence.keys(), default=floor_seq
    )
    consumed_sequences = [e.sequence for e in ledger.events]
    highest_consumed = max(consumed_sequences, default=floor_seq)
    next_unused = max(floor_seq, highest_authenticated, highest_consumed) + 1

    return ReconciledSequenceAuthority(
        authenticated_bindings_sha256=authenticated_history.authenticated_bindings_sha256,
        history_snapshot_sha256=authenticated_history.snapshot_sha256,
        genesis_floor_sequence=floor_seq,
        latest_ledger_entry_sha256=ledger.latest_entry_sha256,
        highest_authenticated_sequence=highest_authenticated,
        highest_consumed_sequence=highest_consumed,
        next_unused_sequence=next_unused,
        recovery_action=recovery_action,
        recovery_sequence=recovery_seq,
        recovery_state=recovery_action,
    )


def next_unused_sequence(authority: ReconciledSequenceAuthority) -> int:
    """Return next unused sequence from reconciled sequence authority."""
    return authority.next_unused_sequence
