from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.project_release_audit_ledger import (
    EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
    OWNER_DISPOSITION_DELETE,
    QUALIFICATION_STATUS_KNOWN_BROKEN,
    ReleaseAuditEvent,
    ReleaseAuditSchemaError,
    validate_release_audit_event,
)
from scripts.capture_installer_repo_forensics import (
    BLOCKER_FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE,
    HISTORICAL_FAILURE_EXIT_CODE,
    HISTORICAL_INSTALLER_NAME,
    HISTORICAL_INSTALLER_SHA256,
    HISTORICAL_INSTALLER_SIZE,
    HISTORICAL_VERIFIER_PATH,
    ArtifactCustodyEvidence,
    FakeDownloadExecutor,
    FakeGitHubExecutor,
    ForensicArtifactCustodyIncompleteError,
    ForensicCaptureError,
    ForensicSnapshot,
    KnownBrokenEvidenceV1,
    RepositoryIdentity,
    build_known_broken_evidence,
    capture_assets,
    capture_forensic_snapshot,
    capture_refs,
    capture_releases,
    capture_repository_identity,
    custody_broken_installer,
    write_known_broken_evidence,
)


OWNER = "Valeneko-pranmong"
REPO = "Neko-Family-Proxy-Installer"
REPO_ID = 12345678
REPO_NODE_ID = "MDEwOlJlcG9zaXRvcnkxMjM0NTY3OA=="
DEFAULT_BRANCH = "main"
DEFAULT_HEAD_SHA = "1111111111111111111111111111111111111111"

HISTORICAL_SOURCE_COMMIT = "abcdef0123456789abcdef0123456789abcdef01"
HISTORICAL_VERIFIER_SHA = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
HISTORICAL_FAILURE_OUTPUT_SHA = "fedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321"
HISTORICAL_CORE_PAYLOAD_SHA = "9876543210fedcba9876543210fedcba9876543210fedcba9876543210fedcba"
SOURCE_BUILD_PROVENANCE_SHA = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"


def _make_sample_known_broken_evidence(
    *,
    repository_id: int = REPO_ID,
    repository_node_id: str = REPO_NODE_ID,
    release_id: int = 101,
    asset_id: int = 201,
    installer_size: int = HISTORICAL_INSTALLER_SIZE,
    installer_sha256: str = HISTORICAL_INSTALLER_SHA256,
    historical_failure_exit_code: int = HISTORICAL_FAILURE_EXIT_CODE,
    historical_verifier_path: str = HISTORICAL_VERIFIER_PATH,
    qualification_status: str = QUALIFICATION_STATUS_KNOWN_BROKEN,
) -> KnownBrokenEvidenceV1:
    return build_known_broken_evidence(
        repository_id=repository_id,
        repository_node_id=repository_node_id,
        release_id=release_id,
        asset_id=asset_id,
        installer_size=installer_size,
        installer_sha256=installer_sha256,
        historical_source_commit=HISTORICAL_SOURCE_COMMIT,
        historical_verifier_path=historical_verifier_path,
        historical_verifier_sha256=HISTORICAL_VERIFIER_SHA,
        historical_failure_exit_code=historical_failure_exit_code,
        historical_failure_output_sha256=HISTORICAL_FAILURE_OUTPUT_SHA,
        historical_core_payload_sha256=HISTORICAL_CORE_PAYLOAD_SHA,
        source_build_provenance_sha256=SOURCE_BUILD_PROVENANCE_SHA,
        qualification_status=qualification_status,
    )


def _make_standard_fake_github_executor() -> FakeGitHubExecutor:
    """Build fake executor fixture with multiple releases, draft/prerelease flags,

    multiple assets, annotated/lightweight tags, and branch refs.
    """
    repo_data = {
        "id": REPO_ID,
        "node_id": REPO_NODE_ID,
        "owner": {"login": OWNER},
        "name": REPO,
        "default_branch": DEFAULT_BRANCH,
        "visibility": "public",
    }

    releases_page_1 = [
        {
            "id": 101,
            "tag_name": "v5.1.2",
            "name": "Release v5.1.2",
            "draft": False,
            "prerelease": False,
            "target_commitish": "main",
            "assets": [
                {
                    "id": 201,
                    "name": HISTORICAL_INSTALLER_NAME,
                    "size": HISTORICAL_INSTALLER_SIZE,
                    "browser_download_url": "https://api.github.com/fake/download/201",
                    "content_type": "application/octet-stream",
                    "state": "uploaded",
                }
            ],
        },
        {
            "id": 102,
            "tag_name": "v5.1.1",
            "name": "Release v5.1.1",
            "draft": False,
            "prerelease": False,
            "target_commitish": "2222222222222222222222222222222222222222",
            "assets": [
                {
                    "id": 202,
                    "name": "old-installer-511.exe",
                    "size": 5000000,
                    "browser_download_url": "https://api.github.com/fake/download/202",
                    "content_type": "application/octet-stream",
                    "state": "uploaded",
                }
            ],
        },
    ]

    releases_page_2 = [
        {
            "id": 103,
            "tag_name": "v5.1.0-beta",
            "name": "Release v5.1.0-beta",
            "draft": True,
            "prerelease": True,
            "target_commitish": "beta",
            "assets": [
                {
                    "id": 203,
                    "name": "beta-installer.exe",
                    "size": 4000000,
                    "browser_download_url": "https://api.github.com/fake/download/203",
                    "content_type": "application/octet-stream",
                    "state": "uploaded",
                },
                {
                    "id": 204,
                    "name": "beta-checksums.txt",
                    "size": 500,
                    "browser_download_url": "https://api.github.com/fake/download/204",
                    "content_type": "text/plain",
                    "state": "uploaded",
                },
            ],
        }
    ]

    refs_data = [
        {
            "ref": "refs/heads/main",
            "node_id": "ref_main_node",
            "object": {
                "sha": DEFAULT_HEAD_SHA,
                "type": "commit",
            },
        },
        {
            "ref": "refs/heads/beta",
            "node_id": "ref_beta_node",
            "object": {
                "sha": "3333333333333333333333333333333333333333",
                "type": "commit",
            },
        },
        {
            "ref": "refs/tags/v5.1.2",
            "node_id": "ref_tag_v512_node",
            "object": {
                "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "type": "tag",
            },
        },
        {
            "ref": "refs/tags/v5.1.1",
            "node_id": "ref_tag_v511_node",
            "object": {
                "sha": "2222222222222222222222222222222222222222",
                "type": "commit",
            },
        },
    ]

    tag_v512_annotated = {
        "tag": "v5.1.2",
        "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "object": {
            "sha": "4444444444444444444444444444444444444444",
            "type": "commit",
        },
    }

    commits = {
        "main": {"sha": DEFAULT_HEAD_SHA},
        "beta": {"sha": "3333333333333333333333333333333333333333"},
        "2222222222222222222222222222222222222222": {"sha": "2222222222222222222222222222222222222222"},
    }

    return FakeGitHubExecutor(
        repo_data=repo_data,
        releases_pages=[releases_page_1, releases_page_2],
        refs=refs_data,
        tags_objects={"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": tag_v512_annotated},
        commits=commits,
    )


# ---------------------------------------------------------------------------
# Step 1: Fake paginated GitHub executor fixture tests
# ---------------------------------------------------------------------------


def test_step1_fake_paginated_executor_fixture():
    executor = _make_standard_fake_github_executor()
    repo_resp = executor.get(f"repos/{OWNER}/{REPO}")
    assert repo_resp.status_code == 200
    assert repo_resp.json()["id"] == REPO_ID

    rel_p1 = executor.get(f"repos/{OWNER}/{REPO}/releases", params={"page": 1, "per_page": 2})
    assert len(rel_p1.json()) == 2
    assert "rel=\"next\"" in rel_p1.headers.get("Link", "")

    rel_p2 = executor.get(f"repos/{OWNER}/{REPO}/releases", params={"page": 2, "per_page": 2})
    assert len(rel_p2.json()) == 1
    assert "rel=\"next\"" not in rel_p2.headers.get("Link", "")


def test_step1_capture_repository_identity():
    executor = _make_standard_fake_github_executor()
    identity = capture_repository_identity(OWNER, REPO, executor)
    assert isinstance(identity, RepositoryIdentity)
    assert identity.numeric_id == REPO_ID
    assert identity.node_id == REPO_NODE_ID
    assert identity.owner == OWNER
    assert identity.name == REPO
    assert identity.default_branch == DEFAULT_BRANCH
    assert identity.default_head_sha == DEFAULT_HEAD_SHA
    assert identity.to_dict()["numeric_id"] == REPO_ID


def test_step5_write_known_broken_evidence_directly(tmp_path: Path):
    custody_root = tmp_path / "direct_write"
    ev = _make_sample_known_broken_evidence()
    out_path = write_known_broken_evidence(ev, custody_root)
    assert out_path.is_file()
    assert out_path.name == "known-broken-v512-installer-evidence.json"
    reloaded = KnownBrokenEvidenceV1.from_dict(json.loads(out_path.read_text(encoding="utf-8")))
    assert reloaded.installer_size == HISTORICAL_INSTALLER_SIZE
    assert reloaded.historical_failure_exit_code == 6


# ---------------------------------------------------------------------------
# Step 2: RED test capture pages through ALL releases and assets
# ---------------------------------------------------------------------------


def test_step2_capture_pages_through_all_releases_and_assets():
    executor = _make_standard_fake_github_executor()
    releases = capture_releases(OWNER, REPO, executor)
    # Must capture all 3 releases across both pages
    assert len(releases) == 3
    tags = [r["tag_name"] for r in releases]
    assert tags == ["v5.1.2", "v5.1.1", "v5.1.0-beta"]

    assets = capture_assets(OWNER, REPO, releases, executor)
    # 1 asset in v5.1.2, 1 in v5.1.1, 2 in v5.1.0-beta -> 4 custom assets total
    assert len(assets) == 4
    asset_names = [a["name"] for a in assets]
    assert HISTORICAL_INSTALLER_NAME in asset_names
    assert "beta-checksums.txt" in asset_names


def test_step2_missing_or_incomplete_pagination_fails():
    executor = _make_standard_fake_github_executor()
    # Simulate broken pagination on page 2
    executor.broken_on_page = 2
    with pytest.raises(ForensicCaptureError, match="[Pp]agination|incomplete|failed"):
        capture_releases(OWNER, REPO, executor)


# ---------------------------------------------------------------------------
# Step 3: RED test canonical inventories are order-independent
# ---------------------------------------------------------------------------


def test_step3_canonical_inventories_order_independent():
    exec1 = _make_standard_fake_github_executor()
    snap1 = capture_forensic_snapshot(OWNER, REPO, exec1)

    # Invert the order in pages and lists
    exec2 = _make_standard_fake_github_executor()
    # Reverse release pages and inner items
    exec2.releases_pages = [
        list(reversed(exec2.releases_pages[1])),
        list(reversed(exec2.releases_pages[0])),
    ]
    # Reverse refs
    exec2.refs = list(reversed(exec2.refs))

    snap2 = capture_forensic_snapshot(OWNER, REPO, exec2)
    assert isinstance(snap1, ForensicSnapshot)
    assert isinstance(snap2, ForensicSnapshot)

    assert snap1.repository_identity_sha256 == snap2.repository_identity_sha256
    assert snap1.release_inventory_sha256 == snap2.release_inventory_sha256
    assert snap1.asset_inventory_sha256 == snap2.asset_inventory_sha256
    assert snap1.ref_inventory_sha256 == snap2.ref_inventory_sha256
    assert snap1.complete_forensic_inventory_sha256 == snap2.complete_forensic_inventory_sha256

    assert snap1.canonical_releases_json == snap2.canonical_releases_json
    assert snap1.canonical_assets_json == snap2.canonical_assets_json
    assert snap1.canonical_refs_json == snap2.canonical_refs_json


# ---------------------------------------------------------------------------
# Step 4: RED test tag inventory peeled commit and release target_commitish
# ---------------------------------------------------------------------------


def test_step4_tag_inventory_peeled_commit_and_release_target_commitish():
    executor = _make_standard_fake_github_executor()
    refs = capture_refs(OWNER, REPO, executor)
    ref_by_name = {r["ref"]: r for r in refs}

    # Annotated tag: object_type is 'tag', peeled_commit is resolved commit
    tag_v512 = ref_by_name["refs/tags/v5.1.2"]
    assert tag_v512["object_type"] == "tag"
    assert tag_v512["object_sha"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert tag_v512["peeled_commit"] == "4444444444444444444444444444444444444444"

    # Lightweight tag: object_type is 'commit', peeled_commit is same commit
    tag_v511 = ref_by_name["refs/tags/v5.1.1"]
    assert tag_v511["object_type"] == "commit"
    assert tag_v511["object_sha"] == "2222222222222222222222222222222222222222"
    assert tag_v511["peeled_commit"] == "2222222222222222222222222222222222222222"

    # Branch ref:
    ref_main = ref_by_name["refs/heads/main"]
    assert ref_main["object_type"] == "commit"
    assert ref_main["object_sha"] == DEFAULT_HEAD_SHA
    assert ref_main["peeled_commit"] == DEFAULT_HEAD_SHA

    # Releases target_commitish + resolved commit
    releases = capture_releases(OWNER, REPO, executor)
    rel_by_tag = {r["tag_name"]: r for r in releases}
    assert rel_by_tag["v5.1.2"]["target_commitish"] == "main"
    assert rel_by_tag["v5.1.2"]["resolved_commit"] == DEFAULT_HEAD_SHA

    assert rel_by_tag["v5.1.1"]["target_commitish"] == "2222222222222222222222222222222222222222"
    assert rel_by_tag["v5.1.1"]["resolved_commit"] == "2222222222222222222222222222222222222222"

    assert rel_by_tag["v5.1.0-beta"]["target_commitish"] == "beta"
    assert rel_by_tag["v5.1.0-beta"]["resolved_commit"] == "3333333333333333333333333333333333333333"


# ---------------------------------------------------------------------------
# Step 5: RED custody test downloads exact historical broken v5.1.2 asset bytes
# ---------------------------------------------------------------------------


def test_step5_custody_broken_installer_creates_evidence(tmp_path: Path):
    custody_root = tmp_path / "custody_test"
    fake_installer_bytes = b"EXACT_BROKEN_V512_BYTES_" + (b"0" * (HISTORICAL_INSTALLER_SIZE - 24))
    assert len(fake_installer_bytes) == HISTORICAL_INSTALLER_SIZE
    computed_sha = hashlib.sha256(fake_installer_bytes).hexdigest()

    known_broken_evidence = _make_sample_known_broken_evidence(
        installer_size=HISTORICAL_INSTALLER_SIZE,
        installer_sha256=computed_sha,
    )

    download_executor = FakeDownloadExecutor(payload=fake_installer_bytes)

    custody_obj = custody_broken_installer(
        repository_id=REPO_ID,
        repository_node_id=REPO_NODE_ID,
        release_id=101,
        release_tag="v5.1.2",
        asset_id=201,
        asset_name=HISTORICAL_INSTALLER_NAME,
        custody_root=custody_root,
        download_executor=download_executor,
        download_url="https://api.github.com/fake/download/201",
        expected_size=HISTORICAL_INSTALLER_SIZE,
        expected_sha256=computed_sha,
        known_broken_evidence=known_broken_evidence,
    )

    assert isinstance(custody_obj, ArtifactCustodyEvidence)
    assert custody_obj.repository_id == REPO_ID
    assert custody_obj.repository_node_id == REPO_NODE_ID
    assert custody_obj.release_id == 101
    assert custody_obj.release_tag == "v5.1.2"
    assert custody_obj.asset_id == 201
    assert custody_obj.asset_name == HISTORICAL_INSTALLER_NAME
    assert custody_obj.size == HISTORICAL_INSTALLER_SIZE
    assert custody_obj.sha256 == computed_sha
    assert custody_obj.qualification_status == QUALIFICATION_STATUS_KNOWN_BROKEN
    assert custody_obj.known_broken_evidence_ref == "known-broken-v512-installer-evidence.json"

    # Verify physical file existence and re-hash under tmp_path
    custodied_file = Path(custody_obj.custody_path)
    assert custodied_file.is_file()
    assert hashlib.sha256(custodied_file.read_bytes()).hexdigest() == computed_sha

    evidence_file = custody_root / custody_obj.known_broken_evidence_ref
    assert evidence_file.is_file()
    actual_evidence_sha = hashlib.sha256(evidence_file.read_bytes()).hexdigest()
    assert custody_obj.known_broken_evidence_sha256 == actual_evidence_sha

    # Verify content of evidence file matches schema
    ev_data = json.loads(evidence_file.read_text(encoding="utf-8"))
    assert ev_data["schema_version"] == 1
    assert ev_data["historical_failure_exit_code"] == 6
    assert ev_data["historical_verifier_path"] == "installer/scripts/verify-core-install.ps1"
    assert ev_data["qualification_status"] == "KNOWN_BROKEN_UNQUALIFIED"


# ---------------------------------------------------------------------------
# Step 6: RED mismatch tests: FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE
# ---------------------------------------------------------------------------


def test_step6_custody_size_mismatch_blocks_incomplete(tmp_path: Path):
    custody_root = tmp_path / "custody_mismatch_size"
    wrong_bytes = b"wrong_size_bytes"
    known_broken_evidence = _make_sample_known_broken_evidence(
        installer_size=len(wrong_bytes),
        installer_sha256=hashlib.sha256(wrong_bytes).hexdigest(),
    )
    download_executor = FakeDownloadExecutor(payload=wrong_bytes)

    with pytest.raises(ForensicArtifactCustodyIncompleteError) as exc_info:
        custody_broken_installer(
            repository_id=REPO_ID,
            repository_node_id=REPO_NODE_ID,
            release_id=101,
            release_tag="v5.1.2",
            asset_id=201,
            asset_name=HISTORICAL_INSTALLER_NAME,
            custody_root=custody_root,
            download_executor=download_executor,
            download_url="https://fake",
            expected_size=HISTORICAL_INSTALLER_SIZE,  # expected differs
            expected_sha256=hashlib.sha256(wrong_bytes).hexdigest(),
            known_broken_evidence=known_broken_evidence,
        )
    assert BLOCKER_FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE in str(exc_info.value)


def test_step6_custody_hash_mismatch_blocks_incomplete(tmp_path: Path):
    custody_root = tmp_path / "custody_mismatch_hash"
    data = b"0" * HISTORICAL_INSTALLER_SIZE
    actual_hash = hashlib.sha256(data).hexdigest()
    expected_different_hash = "f" * 64
    known_broken_evidence = _make_sample_known_broken_evidence(
        installer_size=HISTORICAL_INSTALLER_SIZE,
        installer_sha256=actual_hash,
    )
    download_executor = FakeDownloadExecutor(payload=data)

    with pytest.raises(ForensicArtifactCustodyIncompleteError) as exc_info:
        custody_broken_installer(
            repository_id=REPO_ID,
            repository_node_id=REPO_NODE_ID,
            release_id=101,
            release_tag="v5.1.2",
            asset_id=201,
            asset_name=HISTORICAL_INSTALLER_NAME,
            custody_root=custody_root,
            download_executor=download_executor,
            download_url="https://fake",
            expected_size=HISTORICAL_INSTALLER_SIZE,
            expected_sha256=expected_different_hash,
            known_broken_evidence=known_broken_evidence,
        )
    assert BLOCKER_FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE in str(exc_info.value)


def test_step6_known_broken_evidence_mismatch_blocks(tmp_path: Path):
    custody_root = tmp_path / "custody_mismatch_ev"
    data = b"0" * HISTORICAL_INSTALLER_SIZE
    actual_hash = hashlib.sha256(data).hexdigest()
    download_executor = FakeDownloadExecutor(payload=data)

    # Mismatch: known_broken_evidence claims different installer hash
    ev_mismatched_hash = _make_sample_known_broken_evidence(
        installer_size=HISTORICAL_INSTALLER_SIZE,
        installer_sha256="0" * 64,
    )
    with pytest.raises(ForensicArtifactCustodyIncompleteError) as exc_info:
        custody_broken_installer(
            repository_id=REPO_ID,
            repository_node_id=REPO_NODE_ID,
            release_id=101,
            release_tag="v5.1.2",
            asset_id=201,
            asset_name=HISTORICAL_INSTALLER_NAME,
            custody_root=custody_root,
            download_executor=download_executor,
            download_url="https://fake",
            expected_size=HISTORICAL_INSTALLER_SIZE,
            expected_sha256=actual_hash,
            known_broken_evidence=ev_mismatched_hash,
        )
    assert BLOCKER_FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE in str(exc_info.value)

    # Mismatch: known_broken_evidence claims exit code 0 instead of 6
    ev_dict_code = _make_sample_known_broken_evidence(
        installer_size=HISTORICAL_INSTALLER_SIZE,
        installer_sha256=actual_hash,
    ).to_dict()
    ev_dict_code["historical_failure_exit_code"] = 0
    with pytest.raises(ForensicArtifactCustodyIncompleteError) as exc_info:
        custody_broken_installer(
            repository_id=REPO_ID,
            repository_node_id=REPO_NODE_ID,
            release_id=101,
            release_tag="v5.1.2",
            asset_id=201,
            asset_name=HISTORICAL_INSTALLER_NAME,
            custody_root=custody_root,
            download_executor=download_executor,
            download_url="https://fake",
            expected_size=HISTORICAL_INSTALLER_SIZE,
            expected_sha256=actual_hash,
            known_broken_evidence=ev_dict_code,
        )
    assert BLOCKER_FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE in str(exc_info.value)


def test_step6_cross_module_retirement_evidence_ready_assertion(tmp_path: Path):
    """Cross-module assertion: RETIREMENT_EVIDENCE_READY cannot be constructed

    unless the exact custody object carries the required known-broken evidence binding.
    """
    custody_root = tmp_path / "custody_cross_module"
    data = b"0" * 1000
    actual_hash = hashlib.sha256(data).hexdigest()
    download_executor = FakeDownloadExecutor(payload=data)

    ev = _make_sample_known_broken_evidence(
        installer_size=1000,
        installer_sha256=actual_hash,
    )

    custody_obj = custody_broken_installer(
        repository_id=REPO_ID,
        repository_node_id=REPO_NODE_ID,
        release_id=101,
        release_tag="v5.1.2",
        asset_id=201,
        asset_name="test.exe",
        custody_root=custody_root,
        download_executor=download_executor,
        download_url="https://fake",
        expected_size=1000,
        expected_sha256=actual_hash,
        known_broken_evidence=ev,
    )

    valid_event = ReleaseAuditEvent(
        event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
        target_repository_id=REPO_ID,
        target_repository_node_id=REPO_NODE_ID,
        target_owner=OWNER,
        target_name=REPO,
        evidence={
            "forensic_inventory_digest": "a" * 64,
            "custody": custody_obj,
            "dependency_input_digest": "c" * 64,
            "dependency_result_digest": "d" * 64,
            "replacement_readiness_digest": "e" * 64,
            "owner_disposition": OWNER_DISPOSITION_DELETE,
        },
        timestamp="2026-09-14T20:00:00Z",
        previous_entry_sha256=None,
    )
    # Valid custody object successfully constructs and validates event
    validate_release_audit_event(valid_event)

    # Now strip known_broken_evidence_ref
    bad_custody_dict = custody_obj.to_dict()
    bad_custody_dict["known_broken_evidence_ref"] = ""
    with pytest.raises(ReleaseAuditSchemaError, match="known_broken_evidence_ref"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=REPO_ID,
            target_repository_node_id=REPO_NODE_ID,
            target_owner=OWNER,
            target_name=REPO,
            evidence={
                "forensic_inventory_digest": "a" * 64,
                "custody": bad_custody_dict,
                "dependency_input_digest": "c" * 64,
                "dependency_result_digest": "d" * 64,
                "replacement_readiness_digest": "e" * 64,
                "owner_disposition": OWNER_DISPOSITION_DELETE,
            },
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )

    # Invalid qualification_status
    bad_custody_qual = custody_obj.to_dict()
    bad_custody_qual["qualification_status"] = "UNKNOWN"
    with pytest.raises(ReleaseAuditSchemaError, match="qualification_status"):
        ReleaseAuditEvent(
            event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
            target_repository_id=REPO_ID,
            target_repository_node_id=REPO_NODE_ID,
            target_owner=OWNER,
            target_name=REPO,
            evidence={
                "forensic_inventory_digest": "a" * 64,
                "custody": bad_custody_qual,
                "dependency_input_digest": "c" * 64,
                "dependency_result_digest": "d" * 64,
                "replacement_readiness_digest": "e" * 64,
                "owner_disposition": OWNER_DISPOSITION_DELETE,
            },
            timestamp="2026-09-14T20:00:00Z",
            previous_entry_sha256=None,
        )


# ---------------------------------------------------------------------------
# Safety test: no test references or writes real retirement custody path
# ---------------------------------------------------------------------------


def test_safety_no_live_custody_path_referenced(tmp_path: Path):
    test_file = Path(__file__)
    content = test_file.read_text(encoding="utf-8")
    forbidden = "artifacts" + "/v512-retirement-custody"
    assert forbidden not in content
    forbidden_win = "artifacts" + "\\v512-retirement-custody"
    assert forbidden_win not in content
