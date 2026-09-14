from __future__ import annotations

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from production_sequence_ledger import (
    AuthenticatedHistorySnapshot,
    AuthenticatedProductionBinding,
    ReconciledSequenceAuthority,
    ReleaseAuthorityReconciliationRequired,
    ReleaseProvenanceReconciliationRequired,
    ReleaseAuthorityStale,
    SequenceAuthorityError,
    SequenceAuthorityLockError,
    SequenceAuthoritySession,
    SequenceLedgerEvent,
    SequenceLedgerGenesis,
    VerifiedSequenceLedger,
    append_event,
    initialize_genesis,
    latest_sequence_state,
    next_unused_sequence,
    open_authority_session,
    reconcile_ledger_with_authenticated_history,
    verify_ledger,
)


def _make_floor_binding(sequence: int = 7) -> AuthenticatedProductionBinding:
    return AuthenticatedProductionBinding(
        sequence=sequence,
        release_id=f"stable-{sequence:04d}",
        payload_sha256="d62602d3b90ee0d6b251b6eee7d1aa3e1b5db591f1cd280f723bc011c12fed98",
        envelope_sha256="a806be8e9f1308df1d4ab63e08b319112723a49b768bbb1a2af6189d5ee625c9",
        key_id="neko-update-prod-1",
    )


def _make_genesis(
    sequence: int = 7,
    commit: str | None = "fb0d2e734ee611d75933ccd90cb82347c0b578bd",
) -> SequenceLedgerGenesis:
    return SequenceLedgerGenesis(
        record_type="GENESIS",
        floor_binding=_make_floor_binding(sequence),
        floor_provenance_source_commit=commit,
        timestamp="2026-09-14T20:00:00Z",
        previous_entry_sha256=None,
    )


def _make_event(
    sequence: int = 8,
    status: str = "RESERVED",
    previous_sha: str = "0" * 64,
    source_commit: str = "1111111111111111111111111111111111111111",
    component_set_sha256: str = "2222222222222222222222222222222222222222222222222222222222222222",
    payload_sha256: str | None = None,
    envelope_sha256: str | None = None,
    key_id: str | None = None,
) -> SequenceLedgerEvent:
    return SequenceLedgerEvent(
        record_type="EVENT",
        sequence=sequence,
        release_id=f"stable-{sequence:04d}",
        status=status,
        version="5.1.2",
        channel="stable",
        source_commit=source_commit,
        component_set_sha256=component_set_sha256,
        payload_sha256=payload_sha256,
        envelope_sha256=envelope_sha256,
        key_id=key_id,
        timestamp="2026-09-14T20:01:00Z",
        previous_entry_sha256=previous_sha,
    )


def _make_snapshot(
    bindings: dict[int, AuthenticatedProductionBinding],
    provenance: dict[int, str] | None = None,
    live_updates: set[int] | None = None,
) -> AuthenticatedHistorySnapshot:
    highest = max(bindings.keys()) if bindings else 0
    return AuthenticatedHistorySnapshot(
        bindings_by_sequence=bindings,
        provenance_source_commit_by_sequence=provenance or {},
        live_updates_sequences=frozenset(live_updates or set()),
        highest_authenticated_sequence=highest,
        authenticated_bindings_sha256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        snapshot_sha256="fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
    )


def test_one_time_genesis_creation(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)

    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    assert isinstance(genesis_sha, str)
    assert len(genesis_sha) == 64
    assert ledger_path.is_file()

    verified = verify_ledger(ledger_path)
    assert isinstance(verified, VerifiedSequenceLedger)
    assert verified.genesis == genesis
    assert verified.events == ()
    assert verified.latest_entry_sha256 == genesis_sha


def test_second_or_mutated_genesis_rejection(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)

    with open_authority_session(ledger_path) as session:
        initialize_genesis(session, genesis)

    # Attempt second initialization on existing ledger
    with open_authority_session(ledger_path) as session:
        with pytest.raises(SequenceAuthorityError):
            initialize_genesis(session, genesis)

    # Mutated genesis in file fails verification
    tampered_content = ledger_path.read_text(encoding="utf-8").replace("stable-0007", "stable-9999")
    ledger_path.write_text(tampered_content, encoding="utf-8")
    with pytest.raises(SequenceAuthorityError):
        verify_ledger(ledger_path)


def test_ledger_without_genesis_rejection(tmp_path: Path) -> None:
    # Non-existent ledger
    non_existent = tmp_path / "absent.jsonl"
    with pytest.raises(SequenceAuthorityError):
        verify_ledger(non_existent)

    # Empty ledger
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(SequenceAuthorityError):
        verify_ledger(empty)

    # Ledger starting with EVENT instead of GENESIS
    event_first = tmp_path / "event_first.jsonl"
    event_line = '{"body":{"record_type":"EVENT","sequence":8},"entry_sha256":"abc"}\n'
    event_first.write_text(event_line, encoding="utf-8")
    with pytest.raises(SequenceAuthorityError):
        verify_ledger(event_first)


def test_genesis_floor_disappearance_rebinding_rejection(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        initialize_genesis(session, genesis)
    ledger = verify_ledger(ledger_path)

    # Floor missing completely from history
    snapshot_missing_floor = _make_snapshot(
        bindings={8: _make_floor_binding(8)},
    )
    with pytest.raises(ReleaseAuthorityReconciliationRequired) as exc_info:
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=snapshot_missing_floor
        )
    assert "RELEASE_AUTHORITY_RECONCILIATION_REQUIRED" in str(exc_info.value)

    # Floor present but rebound (different release_id)
    rebound_binding = AuthenticatedProductionBinding(
        sequence=7,
        release_id="stable-0007-rebound",
        payload_sha256=genesis.floor_binding.payload_sha256,
        envelope_sha256=genesis.floor_binding.envelope_sha256,
        key_id=genesis.floor_binding.key_id,
    )
    snapshot_rebound = _make_snapshot(bindings={7: rebound_binding})
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=snapshot_rebound
        )


def test_later_discovery_of_non_conflicting_lower_historical_authority(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        initialize_genesis(session, genesis)
    ledger = verify_ledger(ledger_path)

    # History includes earlier sequences 5 and 6
    b5 = AuthenticatedProductionBinding(5, "stable-0005", "p5", "e5", "k1")
    b6 = AuthenticatedProductionBinding(6, "stable-0006", "p6", "e6", "k1")
    snapshot_with_lower = _make_snapshot(
        bindings={5: b5, 6: b6, 7: genesis.floor_binding},
    )
    reconciled = reconcile_ledger_with_authenticated_history(
        ledger=ledger, authenticated_history=snapshot_with_lower
    )
    assert isinstance(reconciled, ReconciledSequenceAuthority)
    assert reconciled.genesis_floor_sequence == 7
    assert reconciled.highest_authenticated_sequence == 7
    assert next_unused_sequence(reconciled) == 8


def test_permanent_reserved_consumption_above_floor(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha)
    append_event(ledger_path, ev_res, genesis_sha)

    ledger = verify_ledger(ledger_path)
    snapshot = _make_snapshot(bindings={7: genesis.floor_binding})
    reconciled = reconcile_ledger_with_authenticated_history(
        ledger=ledger, authenticated_history=snapshot
    )
    assert reconciled.highest_consumed_sequence == 8
    assert next_unused_sequence(reconciled) == 9

    # Re-reserving sequence 8 fails
    ev_res2 = _make_event(8, "RESERVED", ledger.latest_entry_sha256)
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, ev_res2, ledger.latest_entry_sha256)


def test_lifecycle_reserved_to_signed_to_published(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        curr_sha = initialize_genesis(session, genesis)

    # RESERVED
    ev_res = _make_event(8, "RESERVED", curr_sha)
    curr_sha = append_event(ledger_path, ev_res, curr_sha)

    # SIGNED
    ev_signed = _make_event(
        8,
        "SIGNED",
        curr_sha,
        payload_sha256="payload_sha_8",
        envelope_sha256="envelope_sha_8",
        key_id="neko-update-prod-1",
    )
    curr_sha = append_event(ledger_path, ev_signed, curr_sha)

    # PUBLISHED
    ev_pub = _make_event(
        8,
        "PUBLISHED",
        curr_sha,
        payload_sha256="payload_sha_8",
        envelope_sha256="envelope_sha_8",
        key_id="neko-update-prod-1",
    )
    curr_sha = append_event(ledger_path, ev_pub, curr_sha)

    # RETIRED
    ev_ret = _make_event(
        8,
        "RETIRED",
        curr_sha,
        payload_sha256="payload_sha_8",
        envelope_sha256="envelope_sha_8",
        key_id="neko-update-prod-1",
    )
    curr_sha = append_event(ledger_path, ev_ret, curr_sha)

    verified = verify_ledger(ledger_path)
    assert len(verified.events) == 4
    assert verified.events[0].status == "RESERVED"
    assert verified.events[1].status == "SIGNED"
    assert verified.events[2].status == "PUBLISHED"
    assert verified.events[3].status == "RETIRED"
    assert verified.latest_entry_sha256 == curr_sha


def test_reserved_plus_authenticated_signed_binding_classified_signed_append_required(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha)
    append_event(ledger_path, ev_res, genesis_sha)
    ledger = verify_ledger(ledger_path)

    # History contains signed binding for 8, matching release_id
    signed_b8 = AuthenticatedProductionBinding(
        sequence=8,
        release_id="stable-0008",
        payload_sha256="p8",
        envelope_sha256="e8",
        key_id="neko-update-prod-1",
    )
    snapshot = _make_snapshot(
        bindings={7: genesis.floor_binding, 8: signed_b8},
    )
    reconciled = reconcile_ledger_with_authenticated_history(
        ledger=ledger, authenticated_history=snapshot
    )
    assert reconciled.recovery_action == "SIGNED_APPEND_REQUIRED"
    assert reconciled.recovery_sequence == 8
    assert reconciled.recovery_state == "SIGNED_APPEND_REQUIRED"


def test_signed_plus_live_public_binding_classified_published_append_required(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha)
    res_sha = append_event(ledger_path, ev_res, genesis_sha)
    ev_signed = _make_event(8, "SIGNED", res_sha, payload_sha256="p8", envelope_sha256="e8", key_id="k1")
    append_event(ledger_path, ev_signed, res_sha)
    ledger = verify_ledger(ledger_path)

    signed_b8 = AuthenticatedProductionBinding(8, "stable-0008", "p8", "e8", "k1")
    snapshot = _make_snapshot(
        bindings={7: genesis.floor_binding, 8: signed_b8},
        live_updates={8},
    )
    reconciled = reconcile_ledger_with_authenticated_history(
        ledger=ledger, authenticated_history=snapshot
    )
    assert reconciled.recovery_action == "PUBLISHED_APPEND_REQUIRED"
    assert reconciled.recovery_sequence == 8
    assert reconciled.recovery_state == "PUBLISHED_APPEND_REQUIRED"


def test_authenticated_above_floor_with_no_reserved_hard_stop(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        initialize_genesis(session, genesis)
    ledger = verify_ledger(ledger_path)

    # Authenticated sequence 8 has no ledger allocation
    b8 = AuthenticatedProductionBinding(8, "stable-0008", "p8", "e8", "k1")
    snapshot = _make_snapshot(bindings={7: genesis.floor_binding, 8: b8})
    with pytest.raises(ReleaseAuthorityReconciliationRequired) as exc_info:
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=snapshot
        )
    assert "RELEASE_AUTHORITY_RECONCILIATION_REQUIRED" in str(exc_info.value)


def test_second_allocation_rejection(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha)
    res_sha = append_event(ledger_path, ev_res, genesis_sha)

    # Attempt second RESERVED for seq 8
    ev_res_dup = _make_event(8, "RESERVED", res_sha)
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, ev_res_dup, res_sha)


def test_immutable_ledger_allocation_fields(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha)
    res_sha = append_event(ledger_path, ev_res, genesis_sha)

    # Change release_id
    bad_rel = _make_event(8, "SIGNED", res_sha, payload_sha256="p", envelope_sha256="e", key_id="k")
    bad_rel = SequenceLedgerEvent(
        record_type=bad_rel.record_type,
        sequence=bad_rel.sequence,
        release_id="stable-changed",
        status=bad_rel.status,
        version=bad_rel.version,
        channel=bad_rel.channel,
        source_commit=bad_rel.source_commit,
        component_set_sha256=bad_rel.component_set_sha256,
        payload_sha256=bad_rel.payload_sha256,
        envelope_sha256=bad_rel.envelope_sha256,
        key_id=bad_rel.key_id,
        timestamp=bad_rel.timestamp,
        previous_entry_sha256=bad_rel.previous_entry_sha256,
    )
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, bad_rel, res_sha)

    # Change source_commit
    bad_commit = _make_event(8, "SIGNED", res_sha, source_commit="changed_commit", payload_sha256="p", envelope_sha256="e", key_id="k")
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, bad_commit, res_sha)

    # Change component_set_sha256
    bad_comp = _make_event(8, "SIGNED", res_sha, component_set_sha256="changed_comp", payload_sha256="p", envelope_sha256="e", key_id="k")
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, bad_comp, res_sha)


def test_immutable_payload_envelope_key_after_signed(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha)
    res_sha = append_event(ledger_path, ev_res, genesis_sha)
    ev_signed = _make_event(8, "SIGNED", res_sha, payload_sha256="p_orig", envelope_sha256="e_orig", key_id="k_orig")
    signed_sha = append_event(ledger_path, ev_signed, res_sha)

    # PUBLISHED with different payload_sha256
    bad_pub = _make_event(8, "PUBLISHED", signed_sha, payload_sha256="p_diff", envelope_sha256="e_orig", key_id="k_orig")
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, bad_pub, signed_sha)

    # PUBLISHED with different envelope_sha256
    bad_pub2 = _make_event(8, "PUBLISHED", signed_sha, payload_sha256="p_orig", envelope_sha256="e_diff", key_id="k_orig")
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, bad_pub2, signed_sha)

    # PUBLISHED with different key_id
    bad_pub3 = _make_event(8, "PUBLISHED", signed_sha, payload_sha256="p_orig", envelope_sha256="e_orig", key_id="k_diff")
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, bad_pub3, signed_sha)


def test_stale_previous_digest(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha)
    res_sha = append_event(ledger_path, ev_res, genesis_sha)

    # Append with wrong expected digest
    ev_signed = _make_event(8, "SIGNED", res_sha, payload_sha256="p", envelope_sha256="e", key_id="k")
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, ev_signed, "wrong" + "0" * 59)


def test_failed_terminal_consumption(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha)
    res_sha = append_event(ledger_path, ev_res, genesis_sha)

    ev_failed = _make_event(8, "FAILED", res_sha)
    failed_sha = append_event(ledger_path, ev_failed, res_sha)

    # Any transition from FAILED is illegal
    ev_signed = _make_event(8, "SIGNED", failed_sha, payload_sha256="p", envelope_sha256="e", key_id="k")
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, ev_signed, failed_sha)

    # Next unused remains 9, sequence 8 is not reusable
    ledger = verify_ledger(ledger_path)
    snapshot = _make_snapshot(bindings={7: genesis.floor_binding})
    reconciled = reconcile_ledger_with_authenticated_history(
        ledger=ledger, authenticated_history=snapshot
    )
    assert next_unused_sequence(reconciled) == 9


def test_authenticated_history_higher_lower_cases(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        initialize_genesis(session, genesis)
    ledger = verify_ledger(ledger_path)

    # Lower historical sequence 5 does not raise floor or next unused
    b5 = AuthenticatedProductionBinding(5, "stable-0005", "p5", "e5", "k5")
    snapshot = _make_snapshot(bindings={5: b5, 7: genesis.floor_binding})
    reconciled = reconcile_ledger_with_authenticated_history(
        ledger=ledger, authenticated_history=snapshot
    )
    assert next_unused_sequence(reconciled) == 8

    # Higher historical sequence 9 without ledger event fails
    b9 = AuthenticatedProductionBinding(9, "stable-0009", "p9", "e9", "k9")
    snapshot_hi = _make_snapshot(bindings={7: genesis.floor_binding, 9: b9})
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=snapshot_hi
        )


def test_same_sequence_cryptographic_conflict(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha)
    res_sha = append_event(ledger_path, ev_res, genesis_sha)
    ev_signed = _make_event(8, "SIGNED", res_sha, payload_sha256="p8", envelope_sha256="e8", key_id="k8")
    append_event(ledger_path, ev_signed, res_sha)
    ledger = verify_ledger(ledger_path)

    # Conflict on release_id
    b_bad_id = AuthenticatedProductionBinding(8, "stable-diff", "p8", "e8", "k8")
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=_make_snapshot({7: genesis.floor_binding, 8: b_bad_id})
        )

    # Conflict on payload_sha256
    b_bad_payload = AuthenticatedProductionBinding(8, "stable-0008", "p_diff", "e8", "k8")
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=_make_snapshot({7: genesis.floor_binding, 8: b_bad_payload})
        )

    # Conflict on envelope_sha256
    b_bad_envelope = AuthenticatedProductionBinding(8, "stable-0008", "p8", "e_diff", "k8")
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=_make_snapshot({7: genesis.floor_binding, 8: b_bad_envelope})
        )

    # Conflict on key_id
    b_bad_key = AuthenticatedProductionBinding(8, "stable-0008", "p8", "e8", "k_diff")
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=_make_snapshot({7: genesis.floor_binding, 8: b_bad_key})
        )


def test_separate_controller_custody_provenance_source_mismatch(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha, source_commit="commit_alpha")
    append_event(ledger_path, ev_res, genesis_sha)
    ledger = verify_ledger(ledger_path)

    b8 = AuthenticatedProductionBinding(8, "stable-0008", "p8", "e8", "k8")
    snapshot = _make_snapshot(
        bindings={7: genesis.floor_binding, 8: b8},
        provenance={8: "commit_bravo"},
    )
    with pytest.raises(ReleaseProvenanceReconciliationRequired) as exc_info:
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=snapshot
        )
    assert "RELEASE_PROVENANCE_RECONCILIATION_REQUIRED" in str(exc_info.value)


def test_live_authenticated_history_with_no_source_commit_provenance(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha, source_commit="commit_alpha")
    append_event(ledger_path, ev_res, genesis_sha)
    ledger = verify_ledger(ledger_path)

    # Live public envelope without provenance commit is completely valid
    b8 = AuthenticatedProductionBinding(8, "stable-0008", "p8", "e8", "k8")
    snapshot = _make_snapshot(
        bindings={7: genesis.floor_binding, 8: b8},
        provenance={},
    )
    reconciled = reconcile_ledger_with_authenticated_history(
        ledger=ledger, authenticated_history=snapshot
    )
    assert reconciled.highest_consumed_sequence == 8


def test_concurrent_stale_append(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ev_res = _make_event(8, "RESERVED", genesis_sha)
    res_sha = append_event(ledger_path, ev_res, genesis_sha)

    # Two concurrent callers both saw res_sha
    ev1 = _make_event(8, "SIGNED", res_sha, payload_sha256="p", envelope_sha256="e", key_id="k")
    ev2 = _make_event(8, "FAILED", res_sha)

    # First succeeds
    append_event(ledger_path, ev1, res_sha)

    # Second fails because res_sha is now stale
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, ev2, res_sha)


def test_authority_session_lock_serialization(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"

    with open_authority_session(ledger_path):
        # Nested/concurrent attempt to acquire the lock must raise
        with pytest.raises((SequenceAuthorityLockError, ReleaseAuthorityStale)):
            with open_authority_session(ledger_path):
                pass

    # After first session exits, opening again succeeds
    with open_authority_session(ledger_path) as session2:
        assert isinstance(session2, SequenceAuthoritySession)


def test_session_append_readback_without_nested_lock(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)

    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)
        # Read verified within the same session
        v1 = session.read_verified()
        assert v1.latest_entry_sha256 == genesis_sha

        # Append within the same session
        ev_res = _make_event(8, "RESERVED", genesis_sha)
        res_sha = session.append(ev_res, genesis_sha)

        # Read verified again without reacquiring lock
        v2 = session.read_verified()
        assert v2.latest_entry_sha256 == res_sha
        assert len(v2.events) == 1
        assert v2.events[0].sequence == 8


def test_illegal_lifecycle_transitions(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    # Cannot start with SIGNED directly (must be RESERVED first)
    bad_start = _make_event(8, "SIGNED", genesis_sha, payload_sha256="p", envelope_sha256="e", key_id="k")
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, bad_start, genesis_sha)

    # Advance to PUBLISHED
    ev_res = _make_event(8, "RESERVED", genesis_sha)
    res_sha = append_event(ledger_path, ev_res, genesis_sha)
    ev_signed = _make_event(8, "SIGNED", res_sha, payload_sha256="p", envelope_sha256="e", key_id="k")
    signed_sha = append_event(ledger_path, ev_signed, res_sha)
    ev_pub = _make_event(8, "PUBLISHED", signed_sha, payload_sha256="p", envelope_sha256="e", key_id="k")
    pub_sha = append_event(ledger_path, ev_pub, signed_sha)

    # Cannot transition PUBLISHED -> FAILED
    bad_fail = _make_event(8, "FAILED", pub_sha, payload_sha256="p", envelope_sha256="e", key_id="k")
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, bad_fail, pub_sha)

    # Cannot transition PUBLISHED -> RESERVED
    bad_re_reserve = _make_event(8, "RESERVED", pub_sha)
    with pytest.raises(SequenceAuthorityError):
        append_event(ledger_path, bad_re_reserve, pub_sha)


def test_latest_sequence_state(tmp_path: Path) -> None:
    events = (
        _make_event(8, "RESERVED", "sha0"),
        _make_event(8, "SIGNED", "sha1", payload_sha256="p", envelope_sha256="e", key_id="k"),
        _make_event(9, "RESERVED", "sha2"),
    )
    st8 = latest_sequence_state(events, 8)
    assert st8 is not None
    assert st8.status == "SIGNED"

    st9 = latest_sequence_state(events, 9)
    assert st9 is not None
    assert st9.status == "RESERVED"

    assert latest_sequence_state(events, 10) is None


def test_representative_assertions(tmp_path: Path) -> None:
    # 1. Genesis floor at exact authenticated seq7 yielding next_unused_sequence(...) == 8
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        genesis_sha = initialize_genesis(session, genesis)

    ledger = verify_ledger(ledger_path)
    snapshot = _make_snapshot(bindings={7: genesis.floor_binding})
    reconciled = reconcile_ledger_with_authenticated_history(
        ledger=ledger, authenticated_history=snapshot
    )
    assert next_unused_sequence(reconciled) == 8

    # 2. A reserved seq8 making next-unused 9
    ev_res = _make_event(8, "RESERVED", genesis_sha)
    append_event(ledger_path, ev_res, genesis_sha)
    ledger2 = verify_ledger(ledger_path)
    reconciled2 = reconcile_ledger_with_authenticated_history(
        ledger=ledger2, authenticated_history=snapshot
    )
    assert next_unused_sequence(reconciled2) == 9

    # 3. Fresh provider that loses/rebinds seq7 failing closed
    lost_snapshot = _make_snapshot(bindings={})
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        reconcile_ledger_with_authenticated_history(
            ledger=ledger2, authenticated_history=lost_snapshot
        )

    # 4. Crash-recovery classification for signed-before-ledger-append / published-before-ledger-append
    signed_b8 = AuthenticatedProductionBinding(8, "stable-0008", "p8", "e8", "k8")
    crash_signed_snapshot = _make_snapshot(
        bindings={7: genesis.floor_binding, 8: signed_b8}
    )
    reconciled_signed = reconcile_ledger_with_authenticated_history(
        ledger=ledger2, authenticated_history=crash_signed_snapshot
    )
    assert reconciled_signed.recovery_action == "SIGNED_APPEND_REQUIRED"

    ev_signed = _make_event(8, "SIGNED", ledger2.latest_entry_sha256, payload_sha256="p8", envelope_sha256="e8", key_id="k8")
    append_event(ledger_path, ev_signed, ledger2.latest_entry_sha256)
    ledger3 = verify_ledger(ledger_path)
    crash_pub_snapshot = _make_snapshot(
        bindings={7: genesis.floor_binding, 8: signed_b8},
        live_updates={8},
    )
    reconciled_pub = reconcile_ledger_with_authenticated_history(
        ledger=ledger3, authenticated_history=crash_pub_snapshot
    )
    assert reconciled_pub.recovery_action == "PUBLISHED_APPEND_REQUIRED"


def test_ledger_signed_published_retired_missing_from_authenticated_history_raises(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        curr_sha = initialize_genesis(session, genesis)

    # 1. SIGNED in ledger but missing from authenticated history
    ev_res = _make_event(8, "RESERVED", curr_sha)
    curr_sha = append_event(ledger_path, ev_res, curr_sha)
    ev_signed = _make_event(
        8,
        "SIGNED",
        curr_sha,
        payload_sha256="payload_sha_8",
        envelope_sha256="envelope_sha_8",
        key_id="neko-update-prod-1",
    )
    curr_sha = append_event(ledger_path, ev_signed, curr_sha)

    ledger = verify_ledger(ledger_path)
    snapshot_missing_8 = _make_snapshot(bindings={7: genesis.floor_binding})

    with pytest.raises(ReleaseAuthorityReconciliationRequired) as exc_info:
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=snapshot_missing_8
        )
    assert "RELEASE_AUTHORITY_RECONCILIATION_REQUIRED" in str(exc_info.value)

    # 2. PUBLISHED in ledger but missing from authenticated history
    ev_pub = _make_event(
        8,
        "PUBLISHED",
        curr_sha,
        payload_sha256="payload_sha_8",
        envelope_sha256="envelope_sha_8",
        key_id="neko-update-prod-1",
    )
    curr_sha = append_event(ledger_path, ev_pub, curr_sha)
    ledger_pub = verify_ledger(ledger_path)

    with pytest.raises(ReleaseAuthorityReconciliationRequired) as exc_info:
        reconcile_ledger_with_authenticated_history(
            ledger=ledger_pub, authenticated_history=snapshot_missing_8
        )
    assert "RELEASE_AUTHORITY_RECONCILIATION_REQUIRED" in str(exc_info.value)

    # 3. RETIRED in ledger but missing from authenticated history
    ev_ret = _make_event(
        8,
        "RETIRED",
        curr_sha,
        payload_sha256="payload_sha_8",
        envelope_sha256="envelope_sha_8",
        key_id="neko-update-prod-1",
    )
    curr_sha = append_event(ledger_path, ev_ret, curr_sha)
    ledger_ret = verify_ledger(ledger_path)

    with pytest.raises(ReleaseAuthorityReconciliationRequired) as exc_info:
        reconcile_ledger_with_authenticated_history(
            ledger=ledger_ret, authenticated_history=snapshot_missing_8
        )
    assert "RELEASE_AUTHORITY_RECONCILIATION_REQUIRED" in str(exc_info.value)


def test_multiple_simultaneous_pending_recovery_actions_raises(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    genesis = _make_genesis(7)
    with open_authority_session(ledger_path) as session:
        curr_sha = initialize_genesis(session, genesis)

    # Two sequences in RESERVED state: 8 and 9
    ev_res8 = _make_event(8, "RESERVED", curr_sha)
    curr_sha = append_event(ledger_path, ev_res8, curr_sha)
    ev_res9 = _make_event(9, "RESERVED", curr_sha)
    curr_sha = append_event(ledger_path, ev_res9, curr_sha)

    ledger = verify_ledger(ledger_path)

    b8 = AuthenticatedProductionBinding(8, "stable-0008", "p8", "e8", "neko-update-prod-1")
    b9 = AuthenticatedProductionBinding(9, "stable-0009", "p9", "e9", "neko-update-prod-1")

    # Case A: Two simultaneous SIGNED_APPEND_REQUIRED
    snapshot_dual_signed = _make_snapshot(
        bindings={7: genesis.floor_binding, 8: b8, 9: b9},
    )
    with pytest.raises(ReleaseAuthorityReconciliationRequired) as exc_info:
        reconcile_ledger_with_authenticated_history(
            ledger=ledger, authenticated_history=snapshot_dual_signed
        )
    assert "RELEASE_AUTHORITY_RECONCILIATION_REQUIRED" in str(exc_info.value)

    # Case B: One SIGNED_APPEND_REQUIRED and one PUBLISHED_APPEND_REQUIRED
    # Advance sequence 9 to SIGNED in ledger
    ev_signed9 = _make_event(
        9,
        "SIGNED",
        curr_sha,
        payload_sha256="p9",
        envelope_sha256="e9",
        key_id="neko-update-prod-1",
    )
    curr_sha = append_event(ledger_path, ev_signed9, curr_sha)
    ledger_signed9 = verify_ledger(ledger_path)

    # seq 8 is RESERVED in ledger + has signed binding in history -> SIGNED_APPEND_REQUIRED
    # seq 9 is SIGNED in ledger + has live_updates -> PUBLISHED_APPEND_REQUIRED
    snapshot_mixed = _make_snapshot(
        bindings={7: genesis.floor_binding, 8: b8, 9: b9},
        live_updates={9},
    )
    with pytest.raises(ReleaseAuthorityReconciliationRequired) as exc_info:
        reconcile_ledger_with_authenticated_history(
            ledger=ledger_signed9, authenticated_history=snapshot_mixed
        )
    assert "RELEASE_AUTHORITY_RECONCILIATION_REQUIRED" in str(exc_info.value)

    # Case C: Two simultaneous PUBLISHED_APPEND_REQUIRED
    # Advance sequence 8 to SIGNED in ledger
    ev_signed8 = _make_event(
        8,
        "SIGNED",
        curr_sha,
        payload_sha256="p8",
        envelope_sha256="e8",
        key_id="neko-update-prod-1",
    )
    curr_sha = append_event(ledger_path, ev_signed8, curr_sha)
    ledger_signed_both = verify_ledger(ledger_path)

    snapshot_dual_published = _make_snapshot(
        bindings={7: genesis.floor_binding, 8: b8, 9: b9},
        live_updates={8, 9},
    )
    with pytest.raises(ReleaseAuthorityReconciliationRequired) as exc_info:
        reconcile_ledger_with_authenticated_history(
            ledger=ledger_signed_both, authenticated_history=snapshot_dual_published
        )
    assert "RELEASE_AUTHORITY_RECONCILIATION_REQUIRED" in str(exc_info.value)
