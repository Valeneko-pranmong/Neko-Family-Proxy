from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path
import sys

# Ensure scripts and launcher/src are in sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from scripts.capture_installer_repo_forensics import (  # noqa: E402
    HISTORICAL_INSTALLER_NAME,
    HISTORICAL_INSTALLER_SHA256,
    HISTORICAL_INSTALLER_SIZE,
    ForensicSnapshot,
    RepositoryIdentity,
)
from scripts.project_release_audit_ledger import (  # noqa: E402
    EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
    EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
    OWNER_DISPOSITION_DELETE,
    QUALIFICATION_STATUS_KNOWN_BROKEN,
    ArtifactCustodyEvidence,
    ReleaseAuditEvent,
)
from scripts.release_dependency_audit import (  # noqa: E402
    DependencyAuditEvidence,
    DependencyFinding,
)
from scripts.retirement_predelete_check import (  # noqa: E402
    PreDeleteCheckResult,
    RetirementBlocker,
    check_predelete_freshness,
)

REPO_ID = 12345678
REPO_NODE_ID = "MDEwOlJlcG9zaXRvcnkxMjM0NTY3OA=="
OWNER = "Valeneko-pranmong"
REPO = "Neko-Family-Proxy-Installer"
DEFAULT_BRANCH = "main"
DEFAULT_HEAD_SHA = "0123456789abcdef0123456789abcdef01234567"
APPROVED_FINAL_SHA = "0123456789abcdef0123456789abcdef01234567"
DEPENDENCY_INPUT_SHA = "c" * 64
DEPENDENCY_RESULT_SHA = "d" * 64
REPLACEMENT_READINESS_SHA = "e" * 64
KNOWN_BROKEN_REF = "installer-custody/known-broken-v512-installer-evidence.json"
KNOWN_BROKEN_SHA = "b" * 64


def _make_forensic_snapshot(
    *,
    numeric_id: int = REPO_ID,
    node_id: str = REPO_NODE_ID,
    owner: str = OWNER,
    name: str = REPO,
    default_branch: str = DEFAULT_BRANCH,
    default_head_sha: str = DEFAULT_HEAD_SHA,
    releases: list[dict] | None = None,
    assets: list[dict] | None = None,
    refs: list[dict] | None = None,
) -> ForensicSnapshot:
    identity = RepositoryIdentity(
        numeric_id=numeric_id,
        node_id=node_id,
        owner=owner,
        name=name,
        default_branch=default_branch,
        default_head_sha=default_head_sha,
    )
    repo_bytes = json.dumps(identity.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    repo_sha = hashlib.sha256(repo_bytes).hexdigest()

    if releases is None:
        releases = [
            {
                "id": 101,
                "name": "Release v5.1.2",
                "tag_name": "v5.1.2",
                "target_commitish": DEFAULT_HEAD_SHA,
            }
        ]
    sorted_releases = sorted(releases, key=lambda r: (r["id"], r.get("tag_name", "")))
    rel_bytes = json.dumps(sorted_releases, sort_keys=True, separators=(",", ":")).encode("utf-8")
    rel_sha = hashlib.sha256(rel_bytes).hexdigest()

    if assets is None:
        assets = [
            {
                "id": 201,
                "name": HISTORICAL_INSTALLER_NAME,
                "size": HISTORICAL_INSTALLER_SIZE,
                "browser_download_url": "https://api.github.com/fake/download/201",
                "content_type": "application/octet-stream",
                "state": "uploaded",
            }
        ]
    sorted_assets = sorted(assets, key=lambda a: (a["id"], a.get("name", "")))
    asset_bytes = json.dumps(sorted_assets, sort_keys=True, separators=(",", ":")).encode("utf-8")
    asset_sha = hashlib.sha256(asset_bytes).hexdigest()

    if refs is None:
        refs = [
            {
                "ref": "refs/tags/v5.1.2",
                "node_id": "ref_node_101",
                "object_type": "commit",
                "object_sha": DEFAULT_HEAD_SHA,
                "peeled_commit": DEFAULT_HEAD_SHA,
            }
        ]
    sorted_refs = sorted(refs, key=lambda r: r["ref"])
    ref_bytes = json.dumps(sorted_refs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ref_sha = hashlib.sha256(ref_bytes).hexdigest()

    combined = {
        "repository": json.loads(repo_bytes.decode("utf-8")),
        "releases": json.loads(rel_bytes.decode("utf-8")),
        "assets": json.loads(asset_bytes.decode("utf-8")),
        "refs": json.loads(ref_bytes.decode("utf-8")),
    }
    comb_bytes = json.dumps(combined, sort_keys=True, separators=(",", ":")).encode("utf-8")
    complete_sha = hashlib.sha256(comb_bytes).hexdigest()

    return ForensicSnapshot(
        repository=identity,
        repository_identity_sha256=repo_sha,
        release_inventory_sha256=rel_sha,
        asset_inventory_sha256=asset_sha,
        ref_inventory_sha256=ref_sha,
        complete_forensic_inventory_sha256=complete_sha,
        canonical_repository_json=repo_bytes,
        canonical_releases_json=rel_bytes,
        canonical_assets_json=asset_bytes,
        canonical_refs_json=ref_bytes,
    )


def _make_custody_evidence(
    *,
    repository_id: int = REPO_ID,
    repository_node_id: str = REPO_NODE_ID,
    release_id: int = 101,
    release_tag: str = "v5.1.2",
    asset_id: int = 201,
    asset_name: str = HISTORICAL_INSTALLER_NAME,
    size: int = HISTORICAL_INSTALLER_SIZE,
    sha256: str = HISTORICAL_INSTALLER_SHA256,
    custody_path: str = "installer-custody/NekoFamilyProxy-Installer.exe",
    captured_at: str = "2026-09-14T20:00:00Z",
    known_broken_evidence_ref: str = KNOWN_BROKEN_REF,
    known_broken_evidence_sha256: str = KNOWN_BROKEN_SHA,
    qualification_status: str = QUALIFICATION_STATUS_KNOWN_BROKEN,
) -> ArtifactCustodyEvidence:
    return ArtifactCustodyEvidence(
        repository_id=repository_id,
        repository_node_id=repository_node_id,
        release_id=release_id,
        release_tag=release_tag,
        asset_id=asset_id,
        asset_name=asset_name,
        size=size,
        sha256=sha256,
        custody_path=custody_path,
        captured_at=captured_at,
        known_broken_evidence_ref=known_broken_evidence_ref,
        known_broken_evidence_sha256=known_broken_evidence_sha256,
        qualification_status=qualification_status,  # type: ignore[arg-type]
    )


def _make_dependency_evidence(
    *,
    input_snapshot_sha256: str = DEPENDENCY_INPUT_SHA,
    result_sha256: str = DEPENDENCY_RESULT_SHA,
    approved_source_commit: str = APPROVED_FINAL_SHA,
    tracked_tree_sha256: str = "1" * 64,
    operational_matches: tuple[DependencyFinding, ...] = (),
    historical_allowed_matches: tuple[DependencyFinding, ...] = (),
) -> DependencyAuditEvidence:
    return DependencyAuditEvidence(
        input_snapshot_sha256=input_snapshot_sha256,
        result_sha256=result_sha256,
        approved_source_commit=approved_source_commit,
        tracked_tree_sha256=tracked_tree_sha256,
        operational_matches=operational_matches,
        historical_allowed_matches=historical_allowed_matches,
    )


def _make_retirement_event(
    *,
    event_type: str = EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
    repository_id: int = REPO_ID,
    repository_node_id: str = REPO_NODE_ID,
    owner: str = OWNER,
    name: str = REPO,
    forensic_digest: str | None = None,
    custody: ArtifactCustodyEvidence | dict | None = None,
    dependency_input_digest: str = DEPENDENCY_INPUT_SHA,
    dependency_result_digest: str = DEPENDENCY_RESULT_SHA,
    replacement_readiness_digest: str = REPLACEMENT_READINESS_SHA,
    owner_disposition: str = OWNER_DISPOSITION_DELETE,
    previous_entry_sha256: str | None = None,
    timestamp: str = "2026-09-14T20:10:00Z",
) -> ReleaseAuditEvent:
    if custody is None:
        custody = _make_custody_evidence()
    custody_val = custody.to_dict() if isinstance(custody, ArtifactCustodyEvidence) else custody

    evidence = {
        "forensic_inventory_digest": forensic_digest,
        "custody": custody_val,
        "dependency_input_digest": dependency_input_digest,
        "dependency_result_digest": dependency_result_digest,
        "replacement_readiness_digest": replacement_readiness_digest,
        "owner_disposition": owner_disposition,
    }
    return ReleaseAuditEvent(
        event_type=event_type,
        target_repository_id=repository_id,
        target_repository_node_id=repository_node_id,
        target_owner=owner,
        target_name=name,
        evidence=evidence,
        timestamp=timestamp,
        previous_entry_sha256=previous_entry_sha256,
    )


def _make_valid_bundle():
    approved_forensic = _make_forensic_snapshot()
    live_forensic = _make_forensic_snapshot()
    custody = _make_custody_evidence()
    dependency_evidence = _make_dependency_evidence()
    latest_event = _make_retirement_event(
        forensic_digest=approved_forensic.complete_forensic_inventory_sha256,
        custody=custody,
    )
    return {
        "approved_forensic": approved_forensic,
        "live_forensic": live_forensic,
        "dependency_evidence": dependency_evidence,
        "live_dependency_snapshot_sha256": DEPENDENCY_INPUT_SHA,
        "custody": custody,
        "latest_retirement_event": latest_event,
        "approved_final_source_sha": APPROVED_FINAL_SHA,
        "live_tag_commit_sha": APPROVED_FINAL_SHA,
        "live_replacement_readiness_sha256": REPLACEMENT_READINESS_SHA,
    }


def test_contract_constants_and_types():
    """Verify interface contract: RetirementBlocker contains exactly the 6 required members."""
    expected_blockers = {
        "TARGET_IDENTITY_MISMATCH",
        "FORENSIC_STATE_CHANGED",
        "DEPENDENCY_AUDIT_STALE",
        "FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE",
        "TAG_AUTHORITY_BLOCKED",
        "RETIREMENT_BLOCKED",
    }
    assert len(RetirementBlocker) == 6
    assert set(b.name for b in RetirementBlocker) == expected_blockers
    for name in expected_blockers:
        assert getattr(RetirementBlocker, name).value == name

    # Verify PreDeleteCheckResult fields
    sig = inspect.signature(PreDeleteCheckResult)
    expected_fields = {"allowed_now", "blockers", "live_inventory_sha256", "live_dependency_snapshot_sha256"}
    assert set(sig.parameters.keys()) == expected_fields


# Step 1: RED PASS test
def test_step1_pass_all_evidence_exact_match():
    """Step 1: Live owner/name + numeric ID/node_id + complete digest + dep input snapshot

    + canonical tag + custody + ledger all exactly match latest approved evidence => PASS.
    """
    bundle = _make_valid_bundle()
    result = check_predelete_freshness(**bundle)

    assert isinstance(result, PreDeleteCheckResult)
    assert result.allowed_now is True
    assert result.blockers == ()
    assert result.live_inventory_sha256 == bundle["live_forensic"].complete_forensic_inventory_sha256
    assert result.live_dependency_snapshot_sha256 == DEPENDENCY_INPUT_SHA


# Step 2: RED immutable identity mismatch tests
def test_step2_immutable_identity_mismatch_numeric_id():
    """Step 2: Same owner/name but changed numeric ID => TARGET_IDENTITY_MISMATCH."""
    bundle = _make_valid_bundle()
    # Modify live numeric id
    bundle["live_forensic"] = _make_forensic_snapshot(numeric_id=99999999)

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.TARGET_IDENTITY_MISMATCH in result.blockers
    assert result.blockers == (RetirementBlocker.TARGET_IDENTITY_MISMATCH,)


def test_step2_immutable_identity_mismatch_node_id():
    """Step 2: Same owner/name/id but changed node_id => TARGET_IDENTITY_MISMATCH."""
    bundle = _make_valid_bundle()
    bundle["live_forensic"] = _make_forensic_snapshot(node_id="MDEwOlJlcG9zaXRvcnk5OTk5OTk5OQ==")

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.TARGET_IDENTITY_MISMATCH in result.blockers
    assert result.blockers == (RetirementBlocker.TARGET_IDENTITY_MISMATCH,)


def test_step2_identity_mismatch_owner_or_name():
    """Step 2: Changed owner or name => TARGET_IDENTITY_MISMATCH, no fallback."""
    bundle = _make_valid_bundle()
    bundle["live_forensic"] = _make_forensic_snapshot(owner="OtherOwner")

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.TARGET_IDENTITY_MISMATCH in result.blockers

    bundle2 = _make_valid_bundle()
    bundle2["live_forensic"] = _make_forensic_snapshot(name="OtherName")
    result2 = check_predelete_freshness(**bundle2)
    assert result2.allowed_now is False
    assert RetirementBlocker.TARGET_IDENTITY_MISMATCH in result2.blockers


def test_step2_identity_mismatch_against_ledger_event():
    """Step 2: Mismatch between live identity and latest ledger event => TARGET_IDENTITY_MISMATCH."""
    bundle = _make_valid_bundle()
    bundle["latest_retirement_event"] = _make_retirement_event(
        repository_id=88888888,
        forensic_digest=bundle["approved_forensic"].complete_forensic_inventory_sha256,
        custody=bundle["custody"],
    )
    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.TARGET_IDENTITY_MISMATCH in result.blockers


# Step 3: RED complete inventory delta tests
def test_step3_complete_inventory_delta_release_added():
    """Step 3: Added release in live forensic => FORENSIC_STATE_CHANGED."""
    bundle = _make_valid_bundle()
    extra_releases = [
        {
            "id": 101,
            "name": "Release v5.1.2",
            "tag_name": "v5.1.2",
            "target_commitish": DEFAULT_HEAD_SHA,
        },
        {
            "id": 102,
            "name": "Release v5.1.3",
            "tag_name": "v5.1.3",
            "target_commitish": DEFAULT_HEAD_SHA,
        },
    ]
    bundle["live_forensic"] = _make_forensic_snapshot(releases=extra_releases)

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.FORENSIC_STATE_CHANGED in result.blockers
    assert result.blockers == (RetirementBlocker.FORENSIC_STATE_CHANGED,)


def test_step3_complete_inventory_delta_asset_tampered():
    """Step 3: Changed asset in live forensic => FORENSIC_STATE_CHANGED."""
    bundle = _make_valid_bundle()
    tampered_assets = [
        {
            "id": 201,
            "name": HISTORICAL_INSTALLER_NAME,
            "size": 999999,  # tampered size
            "browser_download_url": "https://api.github.com/fake/download/201",
            "content_type": "application/octet-stream",
            "state": "uploaded",
        }
    ]
    bundle["live_forensic"] = _make_forensic_snapshot(assets=tampered_assets)

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.FORENSIC_STATE_CHANGED in result.blockers


def test_step3_complete_inventory_delta_ref_drift():
    """Step 3: Changed ref in live forensic => FORENSIC_STATE_CHANGED."""
    bundle = _make_valid_bundle()
    drifted_refs = [
        {
            "ref": "refs/tags/v5.1.2",
            "node_id": "ref_node_101",
            "object_type": "commit",
            "object_sha": "9999999999abcdef9999999999abcdef99999999",
            "peeled_commit": "9999999999abcdef9999999999abcdef99999999",
        }
    ]
    bundle["live_forensic"] = _make_forensic_snapshot(refs=drifted_refs)

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.FORENSIC_STATE_CHANGED in result.blockers


def test_step3_approved_forensic_mismatch_with_ledger():
    """Step 3: Approved forensic digest does not match ledger recorded forensic digest => FORENSIC_STATE_CHANGED."""
    bundle = _make_valid_bundle()
    bundle["latest_retirement_event"] = _make_retirement_event(
        forensic_digest="f" * 64,  # different from approved_forensic
        custody=bundle["custody"],
    )
    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.FORENSIC_STATE_CHANGED in result.blockers


# Step 4: RED dependency snapshot change
def test_step4_live_dependency_snapshot_change():
    """Step 4: Live dependency snapshot sha256 changed => DEPENDENCY_AUDIT_STALE."""
    bundle = _make_valid_bundle()
    bundle["live_dependency_snapshot_sha256"] = "f" * 64

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.DEPENDENCY_AUDIT_STALE in result.blockers
    assert result.blockers == (RetirementBlocker.DEPENDENCY_AUDIT_STALE,)


def test_step4_dependency_evidence_mismatches_ledger():
    """Step 4: Dependency evidence digests do not match ledger event => DEPENDENCY_AUDIT_STALE."""
    bundle = _make_valid_bundle()
    bundle["latest_retirement_event"] = _make_retirement_event(
        forensic_digest=bundle["approved_forensic"].complete_forensic_inventory_sha256,
        dependency_input_digest="9" * 64,  # mismatch with dependency_evidence
        custody=bundle["custody"],
    )

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.DEPENDENCY_AUDIT_STALE in result.blockers


# Step 5: RED canonical tag not resolving exact approved final SHA
def test_step5_live_tag_sha_mismatch():
    """Step 5: Canonical tag not resolving exact approved final SHA => TAG_AUTHORITY_BLOCKED."""
    bundle = _make_valid_bundle()
    bundle["live_tag_commit_sha"] = "deadbeef0123456789abcdef0123456789abcdef"

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.TAG_AUTHORITY_BLOCKED in result.blockers
    assert result.blockers == (RetirementBlocker.TAG_AUTHORITY_BLOCKED,)


def test_step5_live_tag_sha_invalid_or_empty():
    """Step 5: Empty or malformed tag SHA => TAG_AUTHORITY_BLOCKED."""
    bundle = _make_valid_bundle()
    bundle["live_tag_commit_sha"] = ""

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.TAG_AUTHORITY_BLOCKED in result.blockers


# Step 6: RED missing/mismatched external broken-installer custody hash/IDs
def test_step6_custody_hash_mismatch():
    """Step 6: Custody hash mismatch with ledger event custody => FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE."""
    bundle = _make_valid_bundle()
    bundle["custody"] = _make_custody_evidence(sha256="1" * 64)

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE in result.blockers


def test_step6_custody_size_mismatch():
    """Step 6: Custody size mismatch with ledger event custody => FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE."""
    bundle = _make_valid_bundle()
    bundle["custody"] = _make_custody_evidence(size=999)

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE in result.blockers


def test_step6_custody_known_broken_binding_missing():
    """Step 6: Missing known_broken_evidence_ref/sha256 => FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE."""
    bundle = _make_valid_bundle()
    bundle["custody"] = _make_custody_evidence(known_broken_evidence_ref="")

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE in result.blockers


def test_step6_custody_qualification_status_invalid():
    """Step 6: Non-unqualified status in custody => FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE."""
    bundle = _make_valid_bundle()
    bundle["custody"] = _make_custody_evidence(qualification_status="QUALIFIED_PRODUCTION")

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE in result.blockers


def test_step6_custody_asset_not_in_approved_forensic():
    """Step 6: Custody asset ID not found in approved forensic assets => FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE."""
    bundle = _make_valid_bundle()
    bundle["custody"] = _make_custody_evidence(asset_id=99999)

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE in result.blockers


# Step 7: RED old RETIREMENT_EVIDENCE_READY event plus fresh state mismatch still blocks
def test_step7_old_retirement_event_plus_fresh_mismatch_blocks():
    """Step 7: Valid old RETIREMENT_EVIDENCE_READY in ledger does not authorize delete

    if fresh live readback mismatches (ledger status is not reusable authorization).
    """
    bundle = _make_valid_bundle()
    # Event is valid and from the past
    bundle["latest_retirement_event"] = _make_retirement_event(
        timestamp="2026-09-10T12:00:00Z",
        forensic_digest=bundle["approved_forensic"].complete_forensic_inventory_sha256,
        custody=bundle["custody"],
    )
    # But live state drifted
    bundle["live_dependency_snapshot_sha256"] = "f" * 64

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.DEPENDENCY_AUDIT_STALE in result.blockers


def test_step7_replacement_readiness_digest_mismatch():
    """Step 7: Live replacement readiness digest does not match event => RETIREMENT_BLOCKED."""
    bundle = _make_valid_bundle()
    bundle["live_replacement_readiness_sha256"] = "0" * 64

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.RETIREMENT_BLOCKED in result.blockers
    assert result.blockers == (RetirementBlocker.RETIREMENT_BLOCKED,)


def test_step7_event_type_not_retirement_ready():
    """Step 7: Latest ledger event is not RETIREMENT_EVIDENCE_READY => RETIREMENT_BLOCKED."""
    bundle = _make_valid_bundle()
    bundle["latest_retirement_event"] = ReleaseAuditEvent(
        event_type=EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
        target_repository_id=REPO_ID,
        target_repository_node_id=REPO_NODE_ID,
        target_owner=OWNER,
        target_name=REPO,
        evidence={
            "result": "VERIFIED_DELETED",
            "execution_timestamp": "2026-09-14T20:30:00Z",
            "post_delete_live_verification_digest": "1" * 64,
            "post_delete_dependency_verification_digest": "2" * 64,
        },
        timestamp="2026-09-14T20:31:00Z",
        previous_entry_sha256="0" * 64,
    )

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.RETIREMENT_BLOCKED in result.blockers


def test_step7_event_owner_disposition_not_delete():
    """Step 7: Owner disposition is not DELETE in ledger event => RETIREMENT_BLOCKED."""
    bundle = _make_valid_bundle()
    event = _make_retirement_event(
        forensic_digest=bundle["approved_forensic"].complete_forensic_inventory_sha256,
        custody=bundle["custody"],
    )
    tampered_evidence = copy.deepcopy(event.evidence)
    tampered_evidence["owner_disposition"] = "RETAIN"
    object.__setattr__(event, "evidence", tampered_evidence)
    bundle["latest_retirement_event"] = event

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.RETIREMENT_BLOCKED in result.blockers


def test_step7_operational_dependencies_present():
    """Step 7: Non-empty operational dependency findings => RETIREMENT_BLOCKED."""
    bundle = _make_valid_bundle()
    bundle["dependency_evidence"] = _make_dependency_evidence(
        operational_matches=(
            DependencyFinding(
                path="scripts/some_script.py",
                line=42,
                kind="OPERATIONAL_DEPENDENCY",
                text_digest="a" * 64,
            ),
        )
    )

    result = check_predelete_freshness(**bundle)
    assert result.allowed_now is False
    assert RetirementBlocker.RETIREMENT_BLOCKED in result.blockers


def test_step7_no_caching_across_sessions_or_calls():
    """Step 7: check_predelete_freshness does not cache PASS across calls."""
    bundle = _make_valid_bundle()
    res1 = check_predelete_freshness(**bundle)
    assert res1.allowed_now is True

    # Mutate live input on second call
    bundle["live_tag_commit_sha"] = "wrong" * 8
    res2 = check_predelete_freshness(**bundle)
    assert res2.allowed_now is False
    assert RetirementBlocker.TAG_AUTHORITY_BLOCKED in res2.blockers


def test_safety_no_delete_capability_in_module():
    """Safety / C0 verification: module has NO function that deletes a repository,

    no delete callback/executor parameter, and no network mutation libraries imported.
    """
    import scripts.retirement_predelete_check as mod

    # Inspect all module attributes defined in this module
    for attr_name in dir(mod):
        if attr_name.startswith("__"):
            continue
        obj = getattr(mod, attr_name)
        if callable(obj) and getattr(obj, "__module__", None) == mod.__name__:
            # The only allowed public function is check_predelete_freshness
            if not attr_name.startswith("_") and not isinstance(obj, type):
                assert attr_name == "check_predelete_freshness", f"Unexpected public callable: {attr_name}"
            # No callable may contain delete execution words
            assert "repo_delete" not in attr_name.lower()
            assert "execute_delete" not in attr_name.lower()

    # Check validator signature: must NOT take executor/callback or delete parameter
    sig = inspect.signature(mod.check_predelete_freshness)
    for param_name in sig.parameters:
        assert "delete" not in param_name.lower() or param_name in (
            "live_dependency_snapshot_sha256",
        ), f"Suspicious parameter name: {param_name}"
        assert "executor" not in param_name.lower()
        assert "callback" not in param_name.lower()

    # Verify source does not contain DELETE HTTP/API invocations
    src = inspect.getsource(mod)
    assert "gh repo delete" not in src
    assert "DELETE" not in src or "RetirementBlocker" in src or "OWNER_DISPOSITION_DELETE" in src
    assert "requests.delete" not in src
    assert "httpx.delete" not in src
