"""Tests for canonical append-only Project Release-Audit Ledger and hash chain."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import project_release_audit_ledger as ledger_mod  # noqa: E402
from project_release_audit_ledger import (  # noqa: E402
    ArtifactCustodyEvidence,
    EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
    EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
    QUALIFICATION_STATUS_KNOWN_BROKEN,
    VERIFIED_DELETED_RESULT,
    ReleaseAuditEvent,
    ReleaseAuditHashChainError,
    ReleaseAuditLocationError,
    ReleaseAuditSchemaError,
    ReleaseAuditStaleAppendError,
    append_release_audit_event,
    compute_entry_sha256,
    verify_release_audit_ledger,
)

TARGET_REPO_ID = 12345678
TARGET_NODE_ID = "MDEwOlJlcG9zaXRvcnkxMjM0NTY3OA=="
TARGET_OWNER = "Valeneko-pranmong"
TARGET_NAME = "Neko-Family-Proxy-Installer"


def _make_valid_custody_evidence() -> ArtifactCustodyEvidence:
    return ArtifactCustodyEvidence(
        repository_id=TARGET_REPO_ID,
        repository_node_id=TARGET_NODE_ID,
        release_id=987654,
        release_tag="v5.1.2",
        asset_id=11223344,
        asset_name="NekoFamilyProxy-Installer.exe",
        size=212293271,
        sha256="e069aa2b268d134ca16d038bef58c176d237e01201e638c63e07f5832803e3f7",
        custody_path="/var/custody/v512-installer.exe",
        captured_at="2026-09-14T20:00:00Z",
        known_broken_evidence_ref="known-broken-v512-installer-evidence.json",
        known_broken_evidence_sha256="b" * 64,
        qualification_status=QUALIFICATION_STATUS_KNOWN_BROKEN,
    )


def _make_valid_retirement_evidence(use_dataclass: bool = True) -> dict:
    custody = _make_valid_custody_evidence() if use_dataclass else asdict(_make_valid_custody_evidence())
    return {
        "forensic_inventory_digest": "a" * 64,
        "custody": custody,
        "dependency_input_digest": "c" * 64,
        "dependency_result_digest": "d" * 64,
        "replacement_readiness_digest": "e" * 64,
        "owner_disposition": "DELETE",
    }


def _make_retirement_event(
    previous_entry_sha256: str | None = None,
    use_dataclass: bool = True,
) -> ReleaseAuditEvent:
    return ReleaseAuditEvent(
        event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
        target_repository_id=TARGET_REPO_ID,
        target_repository_node_id=TARGET_NODE_ID,
        target_owner=TARGET_OWNER,
        target_name=TARGET_NAME,
        evidence=_make_valid_retirement_evidence(use_dataclass=use_dataclass),
        timestamp="2026-09-14T20:10:00Z",
        previous_entry_sha256=previous_entry_sha256,
    )


def _make_valid_deleted_evidence() -> dict:
    return {
        "result": VERIFIED_DELETED_RESULT,
        "execution_timestamp": "2026-09-14T20:30:00Z",
        "post_delete_live_verification_digest": "1" * 64,
        "post_delete_dependency_verification_digest": "2" * 64,
    }


def _make_deleted_event(previous_entry_sha256: str) -> ReleaseAuditEvent:
    return ReleaseAuditEvent(
        event_type=EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
        target_repository_id=TARGET_REPO_ID,
        target_repository_node_id=TARGET_NODE_ID,
        target_owner=TARGET_OWNER,
        target_name=TARGET_NAME,
        evidence=_make_valid_deleted_evidence(),
        timestamp="2026-09-14T20:31:00Z",
        previous_entry_sha256=previous_entry_sha256,
    )


# Step 1: Append / readback / hash-chain test independent of sequence ledger
def test_step1_append_readback_hash_chain_independent_of_sequence_ledger(tmp_path: Path) -> None:
    ledger_path = tmp_path / "release-audit-ledger.jsonl"

    ev1 = _make_retirement_event(previous_entry_sha256=None)
    h1 = append_release_audit_event(ledger_path, ev1, expected_previous_sha256=None)
    assert isinstance(h1, str)
    assert len(h1) == 64
    assert h1 == compute_entry_sha256(ev1)

    readback1 = verify_release_audit_ledger(ledger_path)
    assert len(readback1) == 1
    assert readback1[0].event_type == EVENT_TYPE_RETIREMENT_EVIDENCE_READY
    assert readback1[0].previous_entry_sha256 is None

    ev2 = _make_deleted_event(previous_entry_sha256=h1)
    h2 = append_release_audit_event(ledger_path, ev2, expected_previous_sha256=h1)
    assert isinstance(h2, str)
    assert len(h2) == 64
    assert h2 == compute_entry_sha256(ev2)
    assert h2 != h1

    readback2 = verify_release_audit_ledger(ledger_path)
    assert len(readback2) == 2
    assert readback2[0].event_type == EVENT_TYPE_RETIREMENT_EVIDENCE_READY
    assert readback2[1].event_type == EVENT_TYPE_INSTALLER_REPOSITORY_DELETED
    assert readback2[1].previous_entry_sha256 == h1

    # Independence from Production Sequence Authority Ledger:
    assert not hasattr(ev1, "sequence")
    assert not hasattr(ev1, "floor_binding")
    assert not hasattr(ev1, "genesis")
    assert not hasattr(ledger_mod, "initialize_genesis")
    assert not hasattr(ledger_mod, "next_unused_sequence")


# Step 2: RED schema test for RETIREMENT_EVIDENCE_READY
def test_step2_schema_retirement_evidence_ready_valid(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    ev = _make_retirement_event(use_dataclass=True)
    h = append_release_audit_event(ledger_path, ev, expected_previous_sha256=None)
    events = verify_release_audit_ledger(ledger_path)
    assert len(events) == 1
    assert events[0].evidence["owner_disposition"] == "DELETE"
    assert compute_entry_sha256(events[0]) == h


def test_step2_schema_retirement_evidence_dict_custody(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    ev = _make_retirement_event(use_dataclass=False)
    h = append_release_audit_event(ledger_path, ev, expected_previous_sha256=None)
    events = verify_release_audit_ledger(ledger_path)
    assert len(events) == 1
    assert compute_entry_sha256(events[0]) == h


def test_step2_schema_missing_or_invalid_forensic_inventory() -> None:
    # Missing forensic inventory
    ev_data = _make_valid_retirement_evidence()
    del ev_data["forensic_inventory_digest"]
    with pytest.raises(ReleaseAuditSchemaError, match="forensic inventory"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Invalid non-hex digest
    ev_data = _make_valid_retirement_evidence()
    ev_data["forensic_inventory_digest"] = "not-a-valid-hex64"
    with pytest.raises(ReleaseAuditSchemaError, match="forensic inventory"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )


def test_step2_schema_missing_or_invalid_custody_binding() -> None:
    # Missing custody completely
    ev_data = _make_valid_retirement_evidence()
    del ev_data["custody"]
    with pytest.raises(ReleaseAuditSchemaError, match="custody"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Missing known_broken_evidence_ref
    custody = asdict(_make_valid_custody_evidence())
    del custody["known_broken_evidence_ref"]
    ev_data = _make_valid_retirement_evidence()
    ev_data["custody"] = custody
    with pytest.raises(ReleaseAuditSchemaError, match="known_broken_evidence_ref"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Missing known_broken_evidence_sha256
    custody = asdict(_make_valid_custody_evidence())
    del custody["known_broken_evidence_sha256"]
    ev_data = _make_valid_retirement_evidence()
    ev_data["custody"] = custody
    with pytest.raises(ReleaseAuditSchemaError, match="known_broken_evidence_sha256"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Invalid qualification status
    custody = asdict(_make_valid_custody_evidence())
    custody["qualification_status"] = "QUALIFIED_OK"
    ev_data = _make_valid_retirement_evidence()
    ev_data["custody"] = custody
    with pytest.raises(ReleaseAuditSchemaError, match="qualification_status"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )


def test_step2_schema_missing_dependency_or_replacement_digests() -> None:
    # Missing dependency_input_digest
    ev_data = _make_valid_retirement_evidence()
    del ev_data["dependency_input_digest"]
    with pytest.raises(ReleaseAuditSchemaError, match="dependency_input_digest"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Missing dependency_result_digest
    ev_data = _make_valid_retirement_evidence()
    del ev_data["dependency_result_digest"]
    with pytest.raises(ReleaseAuditSchemaError, match="dependency_result_digest"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Missing replacement_readiness_digest
    ev_data = _make_valid_retirement_evidence()
    del ev_data["replacement_readiness_digest"]
    with pytest.raises(ReleaseAuditSchemaError, match="replacement_readiness_digest"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )


def test_step2_schema_owner_disposition_delete_required() -> None:
    # Missing owner_disposition
    ev_data = _make_valid_retirement_evidence()
    del ev_data["owner_disposition"]
    with pytest.raises(ReleaseAuditSchemaError, match="owner_disposition"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Invalid owner disposition
    ev_data = _make_valid_retirement_evidence()
    ev_data["owner_disposition"] = "KEEP"
    with pytest.raises(ReleaseAuditSchemaError, match="owner_disposition"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )


def test_step2_schema_no_field_interpreted_as_delete_authorized() -> None:
    ev_data = _make_valid_retirement_evidence()
    ev_data["delete_authorized"] = True
    with pytest.raises(ReleaseAuditSchemaError, match="delete_authorized"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=ev_data,
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    valid_ev = _make_retirement_event()
    assert not getattr(valid_ev, "delete_authorized", False)
    assert not getattr(valid_ev, "can_delete", False)


# Step 3: RED schema test for INSTALLER_REPOSITORY_DELETED
def test_step3_schema_installer_repository_deleted_valid(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    ev1 = _make_retirement_event()
    h1 = append_release_audit_event(ledger_path, ev1, expected_previous_sha256=None)

    del_ev = _make_deleted_event(previous_entry_sha256=h1)
    h2 = append_release_audit_event(ledger_path, del_ev, expected_previous_sha256=h1)
    events = verify_release_audit_ledger(ledger_path)
    assert len(events) == 2
    assert events[1].evidence["result"] == VERIFIED_DELETED_RESULT
    assert compute_entry_sha256(events[1]) == h2


def test_step3_schema_installer_repository_deleted_requires_verified_deleted() -> None:
    evidence = _make_valid_deleted_evidence()
    evidence["result"] = "SUCCESS"
    with pytest.raises(ReleaseAuditSchemaError, match="VERIFIED_DELETED"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=evidence,
            timestamp="2026-09-14T20:30:00Z",
            previous_entry_sha256="a" * 64,
        )


def test_step3_schema_installer_repository_deleted_missing_digests() -> None:
    # Missing execution_timestamp
    evidence = _make_valid_deleted_evidence()
    del evidence["execution_timestamp"]
    with pytest.raises(ReleaseAuditSchemaError, match="execution_timestamp"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=evidence,
            timestamp="2026-09-14T20:30:00Z",
            previous_entry_sha256="a" * 64,
        )

    # Missing post_delete_live_verification_digest
    evidence = _make_valid_deleted_evidence()
    del evidence["post_delete_live_verification_digest"]
    with pytest.raises(ReleaseAuditSchemaError, match="post_delete_live_verification_digest"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=evidence,
            timestamp="2026-09-14T20:30:00Z",
            previous_entry_sha256="a" * 64,
        )

    # Missing post_delete_dependency_verification_digest
    evidence = _make_valid_deleted_evidence()
    del evidence["post_delete_dependency_verification_digest"]
    with pytest.raises(ReleaseAuditSchemaError, match="post_delete_dependency_verification_digest"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=evidence,
            timestamp="2026-09-14T20:30:00Z",
            previous_entry_sha256="a" * 64,
        )


# Step 4: RED tamper, broken previous hash, stale append, invalid event type/fields
def test_step4_tamper_detection(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    ev1 = _make_retirement_event()
    h1 = append_release_audit_event(ledger_path, ev1, expected_previous_sha256=None)
    ev2 = _make_deleted_event(previous_entry_sha256=h1)
    append_release_audit_event(ledger_path, ev2, expected_previous_sha256=h1)

    # Tamper with byte in line 1
    content = ledger_path.read_bytes()
    tampered = content.replace(b"2026-09-14T20:10:00Z", b"2026-09-14T20:10:01Z")
    ledger_path.write_bytes(tampered)

    with pytest.raises(ReleaseAuditHashChainError):
        verify_release_audit_ledger(ledger_path)


def test_step4_tamper_non_canonical_formatting(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    ev1 = _make_retirement_event()
    append_release_audit_event(ledger_path, ev1, expected_previous_sha256=None)

    # Inject extra whitespace into canonical json
    content = ledger_path.read_text("utf-8")
    tampered = content.replace('{"evidence":', '{ "evidence": ')
    ledger_path.write_text(tampered, "utf-8")

    with pytest.raises(ReleaseAuditHashChainError):
        verify_release_audit_ledger(ledger_path)


def test_step4_tamper_crlf_rejected(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    ev1 = _make_retirement_event()
    append_release_audit_event(ledger_path, ev1, expected_previous_sha256=None)

    content = ledger_path.read_bytes()
    crlf_content = content.replace(b"\n", b"\r\n")
    ledger_path.write_bytes(crlf_content)

    with pytest.raises(ReleaseAuditHashChainError, match="CRLF"):
        verify_release_audit_ledger(ledger_path)


def test_step4_broken_previous_hash_initial_entry(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    # First entry has non-None previous_entry_sha256
    with pytest.raises(ReleaseAuditHashChainError, match="(?i)initial.*previous_entry_sha256"):
        ev = _make_retirement_event(previous_entry_sha256="a" * 64)
        append_release_audit_event(ledger_path, ev, expected_previous_sha256="a" * 64)

    # Directly written ledger with invalid line 1 previous_entry_sha256
    raw_ev = _make_retirement_event(previous_entry_sha256="b" * 64)
    ledger_path.write_bytes(ledger_mod.serialize_event(raw_ev) + b"\n")
    with pytest.raises(ReleaseAuditHashChainError, match="(?i)initial.*previous_entry_sha256"):
        verify_release_audit_ledger(ledger_path)

    # Valid line 1, then line 2 with broken hash chain
    ledger_path.unlink()
    valid_ev1 = _make_retirement_event(previous_entry_sha256=None)
    append_release_audit_event(ledger_path, valid_ev1, expected_previous_sha256=None)
    broken_ev2 = _make_deleted_event(previous_entry_sha256="c" * 64)
    with open(ledger_path, "ab") as f:
        f.write(ledger_mod.serialize_event(broken_ev2) + b"\n")
    with pytest.raises(ReleaseAuditHashChainError, match="(?i)broken hash chain"):
        verify_release_audit_ledger(ledger_path)


def test_step4_stale_append(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    ev1 = _make_retirement_event()
    h1 = append_release_audit_event(ledger_path, ev1, expected_previous_sha256=None)

    # Non-empty ledger but passed None
    ev2 = _make_deleted_event(previous_entry_sha256=h1)
    with pytest.raises(ReleaseAuditStaleAppendError):
        append_release_audit_event(ledger_path, ev2, expected_previous_sha256=None)

    # Stale hash
    with pytest.raises(ReleaseAuditStaleAppendError):
        append_release_audit_event(ledger_path, ev2, expected_previous_sha256="f" * 64)

    # Mismatch between event.previous_entry_sha256 and expected_previous_sha256
    ev_mismatch = _make_deleted_event(previous_entry_sha256="0" * 64)
    with pytest.raises(ReleaseAuditHashChainError):
        append_release_audit_event(ledger_path, ev_mismatch, expected_previous_sha256=h1)


def test_step4_invalid_event_type() -> None:
    with pytest.raises(ReleaseAuditSchemaError, match="event_type"):
        ReleaseAuditEvent(
            event_type="UNAUTHORIZED_DELETE_EVENT",
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=_make_valid_retirement_evidence(),
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )


def test_step4_invalid_target_fields() -> None:
    # Negative repository id
    with pytest.raises(ReleaseAuditSchemaError, match="target_repository_id"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=-1,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=_make_valid_retirement_evidence(),
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Empty node id
    with pytest.raises(ReleaseAuditSchemaError, match="target_repository_node_id"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id="",
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=_make_valid_retirement_evidence(),
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Empty owner
    with pytest.raises(ReleaseAuditSchemaError, match="target_owner"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner="",
            target_name=TARGET_NAME,
            evidence=_make_valid_retirement_evidence(),
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Empty target name
    with pytest.raises(ReleaseAuditSchemaError, match="target_name"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name="",
            evidence=_make_valid_retirement_evidence(),
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Invalid timestamp format
    with pytest.raises(ReleaseAuditSchemaError, match="timestamp"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=TARGET_REPO_ID,
            target_repository_node_id=TARGET_NODE_ID,
            target_owner=TARGET_OWNER,
            target_name=TARGET_NAME,
            evidence=_make_valid_retirement_evidence(),
            timestamp="invalid-timestamp",
            previous_entry_sha256=None,
        )


# Step 6: Reject paths inside the retiring repository
def test_step6_reject_ledger_path_inside_retiring_repository(tmp_path: Path) -> None:
    inside_path = tmp_path / "Valeneko-pranmong" / "Neko-Family-Proxy-Installer" / "ledger.jsonl"
    ev = _make_retirement_event()
    with pytest.raises(ReleaseAuditLocationError, match="retiring repository"):
        append_release_audit_event(inside_path, ev, expected_previous_sha256=None)

    direct_repo_path = tmp_path / "Neko-Family-Proxy-Installer" / "ledger.jsonl"
    with pytest.raises(ReleaseAuditLocationError, match="retiring repository"):
        append_release_audit_event(direct_repo_path, ev, expected_previous_sha256=None)


# Step 7: RETIREMENT_EVIDENCE_READY alone cannot satisfy can_delete; no DELETE API in module
def test_step7_no_delete_execution_api_in_module() -> None:
    # Assert module does not expose any DELETE execution functions
    assert not hasattr(ledger_mod, "delete_repository")
    assert not hasattr(ledger_mod, "execute_delete")
    assert not hasattr(ledger_mod, "delete_repo")
    assert not hasattr(ledger_mod, "can_delete")
    assert not hasattr(ledger_mod, "delete_authorized")

    # Assert event cannot grant delete authorization
    ev = _make_retirement_event()
    assert not hasattr(ev, "can_delete")
    assert not hasattr(ev, "delete_authorized")
    assert ev.event_type == EVENT_TYPE_RETIREMENT_EVIDENCE_READY
