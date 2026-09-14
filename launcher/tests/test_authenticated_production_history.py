from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import threading
from typing import Any

import pytest

# Ensure scripts and launcher/src are in sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from neko_launcher.updater.canonical_json import canonical_json_dumps  # noqa: E402
try:
    from tests.software_update_helpers import (
        TEST_KEY_ID,
        get_test_key_registry,
        signed_envelope,
        valid_v2_release_document,
    )
except ImportError:
    from launcher.tests.software_update_helpers import (  # noqa: E402
        TEST_KEY_ID,
        get_test_key_registry,
        signed_envelope,
        valid_v2_release_document,
    )

from authenticated_production_history import (  # noqa: E402
    AuthenticatedEnvelopeRecord,
    CompositeAuthenticatedHistoryProvider,
    ProductionHistoryEvidenceChanged,
    ProductionHistoryEvidenceMissing,
    append_custody_record,
    bootstrap_sequence_ledger,
    load_custody_records,
    reserve_release_sequence,
)
from derive_version import (  # noqa: E402
    ReleaseAllocation,
    ReleaseTargetIntent,
    parse_release_target_data,
)
from production_sequence_ledger import (  # noqa: E402
    AuthenticatedHistorySnapshot,
    AuthenticatedProductionBinding,
    ReleaseAuthorityReconciliationRequired,
    ReleaseProvenanceReconciliationRequired,
    SequenceAuthorityError,
    SequenceAuthorityLockError,
    SequenceLedgerGenesis,
)


def _make_signed_envelope_bytes(
    sequence: int,
    release_id: str | None = None,
    key_id: str = TEST_KEY_ID,
    version: str = "5.1.2",
    channel: str = "stable",
) -> tuple[bytes, AuthenticatedProductionBinding]:
    rel_id = release_id or f"stable-{sequence:04d}"
    doc = valid_v2_release_document(
        sequence=sequence,
        release_id=rel_id,
        channel=channel,
        launcher_version=version,
        updater_version=version,
        core_version=version,
    )
    env_dict = signed_envelope(doc, key_id=key_id)
    env_bytes = canonical_json_dumps(env_dict)
    env_sha = hashlib.sha256(env_bytes).hexdigest()

    import base64
    payload_bytes = base64.b64decode(env_dict["payload_b64"])
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()

    binding = AuthenticatedProductionBinding(
        sequence=sequence,
        release_id=rel_id,
        payload_sha256=payload_sha,
        envelope_sha256=env_sha,
        key_id=key_id,
    )
    return env_bytes, binding


class FakeHistoryProvider:
    def __init__(self, snapshot: AuthenticatedHistorySnapshot) -> None:
        self._snapshot = snapshot
        self.load_calls: list[bool] = []
        self.session_to_check: Any = None

    def load(self) -> AuthenticatedHistorySnapshot:
        if self.session_to_check is not None:
            self.load_calls.append(bool(self.session_to_check.is_locked))
        else:
            self.load_calls.append(True)
        return self._snapshot


# Step 1: Tests against semantic intent vs legacy fields
def test_legacy_target_cannot_supply_sequence_or_repo_authority():
    legacy = {
        "stable": "v5.1.1",
        "target": "v5.1.2",
        "seq": 6,
        "stable_id": "stable-0006",
        "intent": "user_bug",
        "installer_repo": "Valeneko-pranmong/Neko-Family-Proxy-Installer",
    }
    with pytest.raises(ValueError, match="forbidden release-target field"):
        parse_release_target_data(legacy)


def test_semantic_target_plus_ledger_history_allocates_sequence(tmp_path: Path):
    target = ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug")

    # Bootstrap genesis at seq 7
    ledger_path = tmp_path / "ledger.jsonl"
    _env_bytes, floor_binding = _make_signed_envelope_bytes(7)
    floor_snapshot = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: floor_binding},
        provenance_source_commit_by_sequence={7: "c" * 40},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=7,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )
    bootstrap_provider = FakeHistoryProvider(floor_snapshot)
    bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=bootstrap_provider,
        expected_floor=floor_binding,
        expected_floor_provenance_source_commit="c" * 40,
    )

    history_provider = FakeHistoryProvider(floor_snapshot)
    allocation = reserve_release_sequence(
        ledger_path=ledger_path,
        history_provider=history_provider,
        target=target,
        source_commit="a" * 40,
        component_set_sha256="b" * 64,
    )
    assert allocation.sequence == 8
    assert allocation.release_id == "stable-0008"


# Step 2: Ledger highest=8 produces seq9 even when semantic version remains 5.1.2
def test_ledger_highest_8_produces_seq_9_even_when_semantic_version_remains_512(tmp_path: Path):
    target = ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug")
    ledger_path = tmp_path / "ledger.jsonl"

    _env_bytes7, binding7 = _make_signed_envelope_bytes(7)
    _env_bytes8, binding8 = _make_signed_envelope_bytes(8)

    # Genesis at 7
    bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=FakeHistoryProvider(
            AuthenticatedHistorySnapshot(
                bindings_by_sequence={7: binding7},
                provenance_source_commit_by_sequence={7: "c" * 40},
                live_updates_sequences=frozenset(),
                highest_authenticated_sequence=7,
                authenticated_bindings_sha256="b" * 64,
                snapshot_sha256="s" * 64,
            )
        ),
        expected_floor=binding7,
        expected_floor_provenance_source_commit="c" * 40,
    )

    # First reservation seq 8
    reserve_release_sequence(
        ledger_path=ledger_path,
        history_provider=FakeHistoryProvider(
            AuthenticatedHistorySnapshot(
                bindings_by_sequence={7: binding7},
                provenance_source_commit_by_sequence={7: "c" * 40},
                live_updates_sequences=frozenset(),
                highest_authenticated_sequence=7,
                authenticated_bindings_sha256="b" * 64,
                snapshot_sha256="s" * 64,
            )
        ),
        target=target,
        source_commit="a" * 40,
        component_set_sha256="b" * 64,
    )

    # Second reservation should produce seq 9 even though target is still 5.1.2!
    allocation = reserve_release_sequence(
        ledger_path=ledger_path,
        history_provider=FakeHistoryProvider(
            AuthenticatedHistorySnapshot(
                bindings_by_sequence={7: binding7},
                provenance_source_commit_by_sequence={7: "c" * 40},
                live_updates_sequences=frozenset(),
                highest_authenticated_sequence=7,
                authenticated_bindings_sha256="b" * 64,
                snapshot_sha256="s" * 64,
            )
        ),
        target=target,
        source_commit="e" * 40,
        component_set_sha256="f" * 64,
    )
    assert allocation.sequence == 9
    assert allocation.release_id == "stable-0009"


# Step 3: Comprehensive RED history-provider / controller tests
def test_bootstrap_and_reservation_load_history_provider_only_after_lock_acquired(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    _env_bytes7, binding7 = _make_signed_envelope_bytes(7)
    snapshot = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7},
        provenance_source_commit_by_sequence={7: "c" * 40},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=7,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )

    locked_during_load: list[bool] = []

    class LockCheckingProvider:
        def load(self) -> AuthenticatedHistorySnapshot:
            # Verify file exists and is locked by inspecting authority session lock
            # The ledger file lock is an OS file lock on ledger_path.with_suffix(".jsonl.lock")
            lock_path = ledger_path.with_suffix(".jsonl.lock")
            locked_during_load.append(lock_path.exists())
            return snapshot

    provider = LockCheckingProvider()
    bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=provider,
        expected_floor=binding7,
        expected_floor_provenance_source_commit="c" * 40,
    )
    assert len(locked_during_load) == 1
    assert locked_during_load[0] is True

    # Check reservation calls load inside lock
    reserve_release_sequence(
        ledger_path=ledger_path,
        history_provider=provider,
        target=ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug"),
        source_commit="a" * 40,
        component_set_sha256="b" * 64,
    )
    assert len(locked_during_load) == 2
    assert locked_during_load[1] is True


def test_seq7_exact_custody_initializes_one_genesis(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    _env_bytes7, binding7 = _make_signed_envelope_bytes(7)
    snapshot = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7},
        provenance_source_commit_by_sequence={7: "fb0d2e734ee611d75933ccd90cb82347c0b578bd"},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=7,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )
    provider = FakeHistoryProvider(snapshot)

    genesis = bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=provider,
        expected_floor=binding7,
        expected_floor_provenance_source_commit="fb0d2e734ee611d75933ccd90cb82347c0b578bd",
    )
    assert isinstance(genesis, SequenceLedgerGenesis)
    assert genesis.floor_binding == binding7

    # Second bootstrap returns exact matching genesis without mutation
    genesis2 = bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=provider,
        expected_floor=binding7,
        expected_floor_provenance_source_commit="fb0d2e734ee611d75933ccd90cb82347c0b578bd",
    )
    assert genesis2 == genesis


def test_missing_or_changed_seq7_before_genesis_hard_stops(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    _env_bytes7, binding7 = _make_signed_envelope_bytes(7)

    # Empty snapshot (missing seq7)
    empty_snapshot = AuthenticatedHistorySnapshot(
        bindings_by_sequence={},
        provenance_source_commit_by_sequence={},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=0,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )
    with pytest.raises((ProductionHistoryEvidenceMissing, ProductionHistoryEvidenceChanged)):
        bootstrap_sequence_ledger(
            ledger_path=ledger_path,
            history_provider=FakeHistoryProvider(empty_snapshot),
            expected_floor=binding7,
            expected_floor_provenance_source_commit="fb0d2e734ee611d75933ccd90cb82347c0b578bd",
        )
    assert not ledger_path.exists()

    # Changed binding (different payload)
    changed_binding = AuthenticatedProductionBinding(
        sequence=7,
        release_id=binding7.release_id,
        payload_sha256="0" * 64,
        envelope_sha256=binding7.envelope_sha256,
        key_id=binding7.key_id,
    )
    changed_snapshot = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: changed_binding},
        provenance_source_commit_by_sequence={7: "fb0d2e734ee611d75933ccd90cb82347c0b578bd"},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=7,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )
    with pytest.raises(ProductionHistoryEvidenceChanged):
        bootstrap_sequence_ledger(
            ledger_path=ledger_path,
            history_provider=FakeHistoryProvider(changed_snapshot),
            expected_floor=binding7,
            expected_floor_provenance_source_commit="fb0d2e734ee611d75933ccd90cb82347c0b578bd",
        )
    assert not ledger_path.exists()


def test_newly_discovered_seq8_before_genesis_hard_stops(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    _env_bytes7, binding7 = _make_signed_envelope_bytes(7)
    _env_bytes8, binding8 = _make_signed_envelope_bytes(8)

    snapshot_with_seq8 = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7, 8: binding8},
        provenance_source_commit_by_sequence={7: "fb0d2e734ee611d75933ccd90cb82347c0b578bd"},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=8,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )
    with pytest.raises(ProductionHistoryEvidenceChanged):
        bootstrap_sequence_ledger(
            ledger_path=ledger_path,
            history_provider=FakeHistoryProvider(snapshot_with_seq8),
            expected_floor=binding7,
            expected_floor_provenance_source_commit="fb0d2e734ee611d75933ccd90cb82347c0b578bd",
        )
    assert not ledger_path.exists()


def test_mutate_provider_history_between_preflight_and_locked_call_stops_or_advances(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    _env_bytes7, binding7 = _make_signed_envelope_bytes(7)
    _env_bytes8, binding8 = _make_signed_envelope_bytes(8)

    bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=FakeHistoryProvider(
            AuthenticatedHistorySnapshot(
                bindings_by_sequence={7: binding7},
                provenance_source_commit_by_sequence={7: "c" * 40},
                live_updates_sequences=frozenset(),
                highest_authenticated_sequence=7,
                authenticated_bindings_sha256="b" * 64,
                snapshot_sha256="s" * 64,
            )
        ),
        expected_floor=binding7,
        expected_floor_provenance_source_commit="c" * 40,
    )

    # Provider returns seq7 on first call, but newly discovered seq8 on locked reservation call
    call_count = 0

    class MutatingProvider:
        def load(self) -> AuthenticatedHistorySnapshot:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return AuthenticatedHistorySnapshot(
                    bindings_by_sequence={7: binding7},
                    provenance_source_commit_by_sequence={7: "c" * 40},
                    live_updates_sequences=frozenset(),
                    highest_authenticated_sequence=7,
                    authenticated_bindings_sha256="b" * 64,
                    snapshot_sha256="s" * 64,
                )
            return AuthenticatedHistorySnapshot(
                bindings_by_sequence={7: binding7, 8: binding8},
                provenance_source_commit_by_sequence={7: "c" * 40, 8: "d" * 40},
                live_updates_sequences=frozenset({8}),
                highest_authenticated_sequence=8,
                authenticated_bindings_sha256="b" * 64,
                snapshot_sha256="s" * 64,
            )

    provider = MutatingProvider()
    # Observation before lock: sees seq7
    obs = provider.load()
    assert obs.highest_authenticated_sequence == 7

    # Inside lock: reservation sees seq8 and stops with reconciliation required!
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        reserve_release_sequence(
            ledger_path=ledger_path,
            history_provider=provider,
            target=ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug"),
            source_commit="a" * 40,
            component_set_sha256="b" * 64,
        )


def test_same_sequence_cryptographic_disagreement_stops_before_append(tmp_path: Path):
    env_bytes1, _b1 = _make_signed_envelope_bytes(7, release_id="stable-0007")
    env_bytes2, _b2 = _make_signed_envelope_bytes(7, release_id="stable-conflict")

    rec1 = AuthenticatedEnvelopeRecord(
        source_id="custody-1",
        source_kind="custody",
        envelope_bytes=env_bytes1,
        provenance_source_commit="c" * 40,
    )
    rec2 = AuthenticatedEnvelopeRecord(
        source_id="custody-2",
        source_kind="custody",
        envelope_bytes=env_bytes2,
        provenance_source_commit="c" * 40,
    )

    provider = CompositeAuthenticatedHistoryProvider(
        enumerate_records=lambda: (rec1, rec2),
        trusted_public_keys=get_test_key_registry(),
    )
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        provider.load()


def test_conflicting_non_null_provenance_commit_yields_reconciliation_required():
    env_bytes, _b = _make_signed_envelope_bytes(7)
    rec1 = AuthenticatedEnvelopeRecord(
        source_id="custody-1",
        source_kind="custody",
        envelope_bytes=env_bytes,
        provenance_source_commit="c" * 40,
    )
    rec2 = AuthenticatedEnvelopeRecord(
        source_id="custody-2",
        source_kind="custody",
        envelope_bytes=env_bytes,
        provenance_source_commit="d" * 40,
    )

    provider = CompositeAuthenticatedHistoryProvider(
        enumerate_records=lambda: (rec1, rec2),
        trusted_public_keys=get_test_key_registry(),
    )
    with pytest.raises(ReleaseProvenanceReconciliationRequired):
        provider.load()


def test_live_authenticated_records_with_provenance_none_remain_valid():
    env_bytes, b = _make_signed_envelope_bytes(7)
    rec_live = AuthenticatedEnvelopeRecord(
        source_id="live-endpoint-1",
        source_kind="live_updates",
        envelope_bytes=env_bytes,
        provenance_source_commit=None,
    )
    provider = CompositeAuthenticatedHistoryProvider(
        enumerate_records=lambda: (rec_live,),
        trusted_public_keys=get_test_key_registry(),
    )
    snapshot = provider.load()
    assert snapshot.bindings_by_sequence[7] == b
    assert snapshot.provenance_source_commit_by_sequence.get(7) is None
    assert 7 in snapshot.live_updates_sequences


def test_live_updates_sequences_cannot_be_forged_by_custody_record():
    env_bytes, _b = _make_signed_envelope_bytes(7)
    rec_custody = AuthenticatedEnvelopeRecord(
        source_id="custody-1",
        source_kind="custody",
        envelope_bytes=env_bytes,
        provenance_source_commit="c" * 40,
    )
    provider = CompositeAuthenticatedHistoryProvider(
        enumerate_records=lambda: (rec_custody,),
        trusted_public_keys=get_test_key_registry(),
    )
    snapshot = provider.load()
    assert 7 not in snapshot.live_updates_sequences


def test_provider_conflict_or_newer_external_authority_hard_stops(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    _env_bytes7, binding7 = _make_signed_envelope_bytes(7)
    _env_bytes8, binding8 = _make_signed_envelope_bytes(8)

    bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=FakeHistoryProvider(
            AuthenticatedHistorySnapshot(
                bindings_by_sequence={7: binding7},
                provenance_source_commit_by_sequence={7: "c" * 40},
                live_updates_sequences=frozenset(),
                highest_authenticated_sequence=7,
                authenticated_bindings_sha256="b" * 64,
                snapshot_sha256="s" * 64,
            )
        ),
        expected_floor=binding7,
        expected_floor_provenance_source_commit="c" * 40,
    )

    # Provider sees seq8 signed in external history, but ledger only has genesis
    provider_with_seq8 = FakeHistoryProvider(
        AuthenticatedHistorySnapshot(
            bindings_by_sequence={7: binding7, 8: binding8},
            provenance_source_commit_by_sequence={7: "c" * 40, 8: "d" * 40},
            live_updates_sequences=frozenset({8}),
            highest_authenticated_sequence=8,
            authenticated_bindings_sha256="b" * 64,
            snapshot_sha256="s" * 64,
        )
    )
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        reserve_release_sequence(
            ledger_path=ledger_path,
            history_provider=provider_with_seq8,
            target=ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug"),
            source_commit="a" * 40,
            component_set_sha256="b" * 64,
        )


def test_concurrent_ledger_append_serializes(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    _env_bytes7, binding7 = _make_signed_envelope_bytes(7)

    bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=FakeHistoryProvider(
            AuthenticatedHistorySnapshot(
                bindings_by_sequence={7: binding7},
                provenance_source_commit_by_sequence={7: "c" * 40},
                live_updates_sequences=frozenset(),
                highest_authenticated_sequence=7,
                authenticated_bindings_sha256="b" * 64,
                snapshot_sha256="s" * 64,
            )
        ),
        expected_floor=binding7,
        expected_floor_provenance_source_commit="c" * 40,
    )

    history_provider = FakeHistoryProvider(
        AuthenticatedHistorySnapshot(
            bindings_by_sequence={7: binding7},
            provenance_source_commit_by_sequence={7: "c" * 40},
            live_updates_sequences=frozenset(),
            highest_authenticated_sequence=7,
            authenticated_bindings_sha256="b" * 64,
            snapshot_sha256="s" * 64,
        )
    )

    allocations: list[ReleaseAllocation] = []
    lock_errors: list[SequenceAuthorityLockError] = []

    barrier = threading.Barrier(3)

    def worker(i: int):
        barrier.wait()
        try:
            alloc = reserve_release_sequence(
                ledger_path=ledger_path,
                history_provider=history_provider,
                target=ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug"),
                source_commit=f"{i:040x}",
                component_set_sha256=f"{i:064x}",
            )
            allocations.append(alloc)
        except SequenceAuthorityLockError as e:
            lock_errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one acquires lock and succeeds, the others fail-closed with lock error (no silent retry!)
    assert len(allocations) + len(lock_errors) == 3
    assert len(allocations) >= 1
    assert len(lock_errors) >= 1

    # Sequential calls continue cleanly from highest sequence
    alloc2 = reserve_release_sequence(
        ledger_path=ledger_path,
        history_provider=history_provider,
        target=ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug"),
        source_commit="1" * 40,
        component_set_sha256="2" * 64,
    )
    assert alloc2.sequence == allocations[0].sequence + 1


def test_no_failure_path_silently_retries(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    _env_bytes7, binding7 = _make_signed_envelope_bytes(7)

    bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=FakeHistoryProvider(
            AuthenticatedHistorySnapshot(
                bindings_by_sequence={7: binding7},
                provenance_source_commit_by_sequence={7: "c" * 40},
                live_updates_sequences=frozenset(),
                highest_authenticated_sequence=7,
                authenticated_bindings_sha256="b" * 64,
                snapshot_sha256="s" * 64,
            )
        ),
        expected_floor=binding7,
        expected_floor_provenance_source_commit="c" * 40,
    )

    # Corrupt ledger file
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write("corrupted line\n")

    with pytest.raises(SequenceAuthorityError):
        reserve_release_sequence(
            ledger_path=ledger_path,
            history_provider=FakeHistoryProvider(
                AuthenticatedHistorySnapshot(
                    bindings_by_sequence={7: binding7},
                    provenance_source_commit_by_sequence={7: "c" * 40},
                    live_updates_sequences=frozenset(),
                    highest_authenticated_sequence=7,
                    authenticated_bindings_sha256="b" * 64,
                    snapshot_sha256="s" * 64,
                )
            ),
            target=ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug"),
            source_commit="a" * 40,
            component_set_sha256="b" * 64,
        )


# Custody Index Tests
def test_custody_index_canonical_closed_schema(tmp_path: Path):
    custody_root = tmp_path / "custody"
    custody_root.mkdir(parents=True)
    index_file = custody_root / "history-index-v1.json"

    # Extra top-level key
    bad_index = {"schema_version": 1, "entries": [], "extra": True}
    index_file.write_bytes(canonical_json_dumps(bad_index))
    with pytest.raises(ValueError, match="closed schema"):
        load_custody_records(custody_root)

    # Non-canonical whitespace
    good_index = {"entries": [], "schema_version": 1}
    index_file.write_text(json.dumps(good_index, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="non-canonical"):
        load_custody_records(custody_root)


def test_custody_index_fixed_root_confinement(tmp_path: Path):
    custody_root = tmp_path / "custody"
    custody_root.mkdir(parents=True)
    index_file = custody_root / "history-index-v1.json"

    bad_entry = {
        "envelope_relpath": "../outside.json",
        "envelope_sha256": "0" * 64,
        "provenance_source_commit": None,
        "source_id": "bad-1",
        "source_kind": "custody",
    }
    index_file.write_bytes(canonical_json_dumps({"entries": [bad_entry], "schema_version": 1}))
    with pytest.raises(ValueError, match="confinement"):
        load_custody_records(custody_root)


def test_custody_append_atomic_and_idempotent(tmp_path: Path):
    custody_root = tmp_path / "custody"
    env_bytes, _b = _make_signed_envelope_bytes(7)
    rec = AuthenticatedEnvelopeRecord(
        source_id="custody-7",
        source_kind="custody",
        envelope_bytes=env_bytes,
        provenance_source_commit="c" * 40,
    )

    sha1 = append_custody_record(custody_root, rec, expected_index_sha256=None)
    assert isinstance(sha1, str)
    records = load_custody_records(custody_root)
    assert len(records) == 1
    assert records[0] == rec

    # Idempotent append
    sha2 = append_custody_record(custody_root, rec, expected_index_sha256=sha1)
    assert sha2 == sha1


def test_custody_append_stale_index_guard(tmp_path: Path):
    custody_root = tmp_path / "custody"
    env_bytes, _b = _make_signed_envelope_bytes(7)
    rec = AuthenticatedEnvelopeRecord(
        source_id="custody-7",
        source_kind="custody",
        envelope_bytes=env_bytes,
        provenance_source_commit="c" * 40,
    )
    append_custody_record(custody_root, rec, expected_index_sha256=None)

    env_bytes8, _b8 = _make_signed_envelope_bytes(8)
    rec8 = AuthenticatedEnvelopeRecord(
        source_id="custody-8",
        source_kind="custody",
        envelope_bytes=env_bytes8,
        provenance_source_commit="d" * 40,
    )
    # Stale index (expected_index_sha256=None when index exists)
    with pytest.raises(ValueError, match="stale"):
        append_custody_record(custody_root, rec8, expected_index_sha256=None)

    # Wrong digest
    with pytest.raises(ValueError, match="stale"):
        append_custody_record(custody_root, rec8, expected_index_sha256="0" * 64)


def test_custody_envelope_hash_and_readback(tmp_path: Path):
    custody_root = tmp_path / "custody"
    env_bytes, _b = _make_signed_envelope_bytes(7)
    rec = AuthenticatedEnvelopeRecord(
        source_id="custody-7",
        source_kind="custody",
        envelope_bytes=env_bytes,
        provenance_source_commit="c" * 40,
    )
    append_custody_record(custody_root, rec, expected_index_sha256=None)

    # Corrupt envelope file on disk
    env_sha = hashlib.sha256(env_bytes).hexdigest()
    env_file = custody_root / "envelopes" / f"{env_sha}.json"
    env_file.write_bytes(b'{"corrupted": true}')

    with pytest.raises(ValueError, match="mismatch|canonical"):
        load_custody_records(custody_root)


def test_custody_rejects_malformed_or_duplicate_entries(tmp_path: Path):
    custody_root = tmp_path / "custody"
    env_bytes, _b = _make_signed_envelope_bytes(7)
    rec = AuthenticatedEnvelopeRecord(
        source_id="custody-7",
        source_kind="custody",
        envelope_bytes=env_bytes,
        provenance_source_commit="c" * 40,
    )
    sha1 = append_custody_record(custody_root, rec, expected_index_sha256=None)

    # Duplicate source_id with different content
    env_bytes8, _b8 = _make_signed_envelope_bytes(8)
    conflicting_rec = AuthenticatedEnvelopeRecord(
        source_id="custody-7",
        source_kind="custody",
        envelope_bytes=env_bytes8,
        provenance_source_commit="d" * 40,
    )
    with pytest.raises(ValueError, match="Conflicting"):
        append_custody_record(custody_root, conflicting_rec, expected_index_sha256=sha1)


def test_seq7_bootstrap_evidence_verification():
    seq7_path = Path(r"E:\Github\artifacts\main-auto-release\34601286641-fb0d2e734ee611d75933ccd90cb82347c0b578bd\5.1.3\publish\release-v2.json")
    assert seq7_path.is_file()
    data = seq7_path.read_bytes()
    assert len(data) == 1632
    assert hashlib.sha256(data).hexdigest() == "a806be8e9f1308df1d4ab63e08b319112723a49b768bbb1a2af6189d5ee625c9"


# Publisher / Verifier RED tests
def test_publish_atomic_release_rejects_deriving_sequence_from_tag():
    from scripts import publish_atomic_release
    # get_release_sequence must not be called or exist in publish_atomic_release
    assert "get_release_sequence" not in publish_atomic_release.__file__
    import inspect
    source = inspect.getsource(publish_atomic_release)
    assert "get_release_sequence" not in source


def test_verify_github_release_assets_requires_explicit_expected_binding():
    from scripts import verify_github_release_assets
    import inspect
    source = inspect.getsource(verify_github_release_assets)
    assert "get_release_sequence" not in source


# Legacy automation RED tests
def test_poll_github_never_dispatches_release_worker_for_semantic_intent(monkeypatch):
    from scripts import kanban_release_adapter

    monkeypatch.setattr(
        kanban_release_adapter,
        "get_successful_main_runs",
        lambda: [{"databaseId": 999, "headSha": "a" * 40}],
    )
    monkeypatch.setattr(kanban_release_adapter, "get_changed_files_for_sha", lambda sha: ["launcher/src/app.py"])
    monkeypatch.setattr(kanban_release_adapter, "should_trigger", lambda files: True)
    monkeypatch.setattr(
        kanban_release_adapter,
        "get_armed_target_from_sha",
        lambda sha: ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug"),
    )
    monkeypatch.setattr(kanban_release_adapter, "get_github_releases", lambda: [])

    # Spy on hermes / kanban / subprocess calls
    spawned = []
    def fake_subprocess_run(cmd, **kwargs):
        spawned.append(cmd)
    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    result = kanban_release_adapter.poll_github_and_create_tasks()
    # It must not dispatch any release worker or invoke release_controller
    for cmd in spawned:
        cmd_str = " ".join(str(c) for c in cmd)
        assert "release_controller.py" not in cmd_str
        assert "assignee release" not in cmd_str
    # Result must report CONTROLLER_RELEASE_REQUIRED or observation
    assert result == "CONTROLLER_RELEASE_REQUIRED" or spawned == []


def test_release_controller_cli_hard_stops_controller_action_required(monkeypatch):
    import scripts.release_controller as rc

    with pytest.raises(SystemExit) as exc:
        rc.main(["--commit", "a" * 40, "--run-id", "123"])
    # CLI must hard-stop before any authority-changing API
    assert "CONTROLLER_ACTION_REQUIRED" in str(exc.value)
