from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
import unittest.mock

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.project_release_audit_ledger import (  # noqa: E402
    EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
    EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
    QUALIFICATION_STATUS_KNOWN_BROKEN,
    VERIFIED_DELETED_RESULT,
    ReleaseAuditEvent,
)
from scripts.publish_human_release import (  # noqa: E402
    CANONICAL_HUMAN_REPO,
    FORBIDDEN_HUMAN_ASSETS,
    REQUIRED_HUMAN_ASSET,
    REQUIRED_HUMAN_ASSETS,
    HumanPublishError,
    HumanPublishResult,
    publish_human_release,
)

TARGET_COMMIT = "a" * 40
RELEASE_TAG = "v5.1.2"
INSTALLER_BYTES = b"MZ-qualified-installer-for-human-release-v5.1.2"

CANONICAL_BODY = """# Neko Family Proxy v5.1.2

Current stable release for general users.
ผู้ใช้ทั่วไปดาวน์โหลดตัวติดตั้ง (Installer) เท่านั้น / Normal users download Installer ONLY.

## Highlights | จุดเด่น
- Release v5.1.2 baseline update
- อัปเดตเวอร์ชันหลัก v5.1.2 สำหรับผู้ใช้งานทั่วไป

## Downloads | ดาวน์โหลด
- `NekoFamilyProxy-Installer.exe` (Official Installer / ตัวติดตั้งทางการ)

## Notes | หมายเหตุ
- Notice for v5.1.0 users: Please uninstall v5.1.0 completely and manually install v5.1.2. Automatic mandatory updating begins from the v5.1.2 baseline.
- สำหรับผู้ใช้งาน v5.1.0: กรุณาถอนการติดตั้ง v5.1.0 ออกทั้งหมด และติดตั้ง v5.1.2 ด้วยตนเอง ระบบอัปเดตอัตโนมัติจะเริ่มต้นจาก v5.1.2 เป็นต้นไป
"""


class FakeExecutor:
    def __init__(
        self,
        *,
        tamper_download: bool = False,
        extra_asset: str | None = None,
        wrong_asset_name: str | None = None,
        wrong_tag_readback: str | None = None,
        wrong_target_readback: str | None = None,
        wrong_body_readback: str | None = None,
        wrong_remote_size: int | None = None,
        installer_bytes: bytes = INSTALLER_BYTES,
    ) -> None:
        self.commands: list[list[str]] = []
        self.calls = self.commands
        self.tamper_download = tamper_download
        self.extra_asset = extra_asset
        self.wrong_asset_name = wrong_asset_name
        self.wrong_tag_readback = wrong_tag_readback
        self.wrong_target_readback = wrong_target_readback
        self.wrong_body_readback = wrong_body_readback
        self.wrong_remote_size = wrong_remote_size
        self.installer_bytes = installer_bytes
        self.draft_created = False
        self.uploaded = False
        self.promoted = False

    def run(
        self,
        args: list[str],
        *,
        capture_output: bool = True,
        stdout: Any = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(args))
        cmd = args[0]

        if cmd == "git":
            if "status" in args:
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if "rev-parse" in args:
                return subprocess.CompletedProcess(args, 0, stdout=f"{TARGET_COMMIT}\n", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        if cmd == "gh":
            if args[1:3] == ["release", "create"]:
                self.draft_created = True
                return subprocess.CompletedProcess(args, 0, stdout="https://github.com/release/999\n", stderr="")

            if args[1:3] == ["release", "upload"]:
                self.uploaded = True
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            if args[1:3] == ["release", "edit"]:
                if "--draft=false" in args:
                    self.promoted = True
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            if args[1] == "api":
                endpoint = args[2]

                # Download asset binary
                if "/releases/assets/" in endpoint:
                    data = b"TAMPERED_BYTES_CORRUPTED" if self.tamper_download else self.installer_bytes
                    if stdout is not None:
                        stdout.write(data)
                        stdout.flush()
                        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
                    return subprocess.CompletedProcess(args, 0, stdout=data.decode("latin1"), stderr="")

                # Discover releases / paginated
                if f"repos/{CANONICAL_HUMAN_REPO}/releases" in endpoint and "/assets/" not in endpoint:
                    tag = self.wrong_tag_readback or RELEASE_TAG
                    target = self.wrong_target_readback or TARGET_COMMIT
                    body = self.wrong_body_readback or CANONICAL_BODY
                    size = self.wrong_remote_size or len(self.installer_bytes)
                    name = self.wrong_asset_name or REQUIRED_HUMAN_ASSET

                    assets = [
                        {
                            "id": 901,
                            "name": name,
                            "size": size,
                            "browser_download_url": f"https://github.com/{CANONICAL_HUMAN_REPO}/releases/download/{tag}/{name}",
                        }
                    ]
                    if self.extra_asset:
                        assets.append(
                            {
                                "id": 902,
                                "name": self.extra_asset,
                                "size": 1000,
                                "browser_download_url": f"https://github.com/{CANONICAL_HUMAN_REPO}/releases/download/{tag}/{self.extra_asset}",
                            }
                        )

                    release_obj = {
                        "id": 999,
                        "tag_name": tag,
                        "target_commitish": target,
                        "draft": not self.promoted,
                        "prerelease": False,
                        "body": body,
                        "assets": assets,
                        "url": f"https://api.github.com/repos/{CANONICAL_HUMAN_REPO}/releases/999",
                        "html_url": f"https://github.com/{CANONICAL_HUMAN_REPO}/releases/tag/{tag}",
                    }

                    if endpoint.endswith("/latest") or endpoint.endswith(f"/tags/{RELEASE_TAG}"):
                        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(release_obj), stderr="")

                    if endpoint.endswith("/999"):
                        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(release_obj), stderr="")

                    # Paginated discovery
                    return subprocess.CompletedProcess(args, 0, stdout=json.dumps([[release_obj]]), stderr="")

        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


@pytest.fixture
def qualified_installer(tmp_path: Path) -> Path:
    installer = tmp_path / REQUIRED_HUMAN_ASSET
    installer.write_bytes(INSTALLER_BYTES)
    return installer


@pytest.fixture
def verified_deleted_event() -> ReleaseAuditEvent:
    return ReleaseAuditEvent(
        event_type=EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
        target_repository_id=777,
        target_repository_node_id="R_kgDOXXXXXX",
        target_owner="Valeneko-pranmong",
        target_name="Neko-Family-Proxy-Installer",
        evidence={
            "result": VERIFIED_DELETED_RESULT,
            "execution_timestamp": "2026-09-14T20:30:00Z",
            "post_delete_live_verification_digest": "1" * 64,
            "post_delete_dependency_verification_digest": "2" * 64,
        },
        timestamp="2026-09-14T20:31:00Z",
        previous_entry_sha256="0" * 64,
    )


@pytest.fixture
def approved_human_body() -> str:
    return CANONICAL_BODY


@pytest.fixture
def fake_exec_with_tampered_remote_asset() -> FakeExecutor:
    return FakeExecutor(tamper_download=True)


# Step 1: Publisher refuses to start unless caller supplies proof of G22 deletion
def test_step1_refuses_without_verified_deleted_evidence(
    qualified_installer: Path,
    approved_human_body: str,
):
    fake_exec = FakeExecutor()

    # None / missing evidence
    with pytest.raises(HumanPublishError, match="[Dd]eletion evidence|[Gg]22"):
        publish_human_release(
            tag=RELEASE_TAG,
            target_commit=TARGET_COMMIT,
            installer_path=qualified_installer,
            body=approved_human_body,
            deletion_evidence=None,  # type: ignore[arg-type]
            executor=fake_exec,
        )
    assert len(fake_exec.commands) == 0

    # Wrong event type (RETIREMENT_EVIDENCE_READY)
    wrong_type_event = ReleaseAuditEvent(
        event_type=EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
        target_repository_id=777,
        target_repository_node_id="R_kgDOXXXXXX",
        target_owner="Valeneko-pranmong",
        target_name="Neko-Family-Proxy-Installer",
        evidence={
            "forensic_inventory_digest": "a" * 64,
            "custody": {
                "archive_path": "installer-forensics.tar.gz",
                "archive_sha256": "b" * 64,
                "recorded_at": "2026-09-14T20:00:00Z",
                "file_count": 5,
                "total_bytes": 100,
                "qualification_status": QUALIFICATION_STATUS_KNOWN_BROKEN,
                "known_broken_evidence_ref": "evidence/ref/1",
                "known_broken_evidence_sha256": "b" * 64,
            },
            "dependency_input_digest": "c" * 64,
            "dependency_result_digest": "d" * 64,
            "replacement_readiness_digest": "e" * 64,
            "owner_disposition": "DELETE",
        },
        timestamp="2026-09-14T20:10:00Z",
        previous_entry_sha256=None,
    )
    with pytest.raises(HumanPublishError, match="INSTALLER_REPOSITORY_DELETED"):
        publish_human_release(
            tag=RELEASE_TAG,
            target_commit=TARGET_COMMIT,
            installer_path=qualified_installer,
            body=approved_human_body,
            deletion_evidence=wrong_type_event,
            executor=fake_exec,
        )
    assert len(fake_exec.commands) == 0

    # Wrong result (not VERIFIED_DELETED)
    wrong_result_event = unittest.mock.MagicMock(spec=ReleaseAuditEvent)
    wrong_result_event.event_type = EVENT_TYPE_INSTALLER_REPOSITORY_DELETED
    wrong_result_event.evidence = {
        "result": "FAILED",
        "execution_timestamp": "2026-09-14T20:30:00Z",
        "post_delete_live_verification_digest": "1" * 64,
        "post_delete_dependency_verification_digest": "2" * 64,
    }
    with pytest.raises(HumanPublishError, match="VERIFIED_DELETED"):
        publish_human_release(
            tag=RELEASE_TAG,
            target_commit=TARGET_COMMIT,
            installer_path=qualified_installer,
            body=approved_human_body,
            deletion_evidence=wrong_result_event,
            executor=fake_exec,
        )
    assert len(fake_exec.commands) == 0


# Step 2: Command-order test: first GitHub Release mutation is draft creation in main repo with draft=true, prerelease=false
def test_step2_first_mutation_is_draft_creation(
    qualified_installer: Path,
    verified_deleted_event: ReleaseAuditEvent,
    approved_human_body: str,
):
    fake_exec = FakeExecutor()
    result = publish_human_release(
        tag=RELEASE_TAG,
        target_commit=TARGET_COMMIT,
        installer_path=qualified_installer,
        body=approved_human_body,
        deletion_evidence=verified_deleted_event,
        executor=fake_exec,
    )
    assert result.status == "SUCCESS"

    # Find mutations (gh release create, gh release upload, gh release edit)
    mutations = [
        cmd for cmd in fake_exec.commands
        if len(cmd) >= 3 and cmd[0] == "gh" and cmd[1] == "release" and cmd[2] in {"create", "upload", "edit", "delete"}
    ]
    assert len(mutations) >= 3
    first_mutation = mutations[0]
    assert first_mutation[1:3] == ["release", "create"]
    assert RELEASE_TAG in first_mutation
    assert "--draft" in first_mutation
    assert "--prerelease=false" in first_mutation
    assert CANONICAL_HUMAN_REPO in first_mutation


# Step 3: Exact Installer uploaded and draft readback requires exactly one custom asset named NekoFamilyProxy-Installer.exe
def test_step3_exact_installer_uploaded_and_single_asset_readback(
    qualified_installer: Path,
    verified_deleted_event: ReleaseAuditEvent,
    approved_human_body: str,
):
    fake_exec = FakeExecutor()
    result = publish_human_release(
        tag=RELEASE_TAG,
        target_commit=TARGET_COMMIT,
        installer_path=qualified_installer,
        body=approved_human_body,
        deletion_evidence=verified_deleted_event,
        executor=fake_exec,
    )
    assert result.status == "SUCCESS"

    upload_cmds = [cmd for cmd in fake_exec.commands if len(cmd) >= 3 and cmd[1:3] == ["release", "upload"]]
    assert len(upload_cmds) == 1
    upload_cmd = upload_cmds[0]
    assert str(qualified_installer) in upload_cmd or REQUIRED_HUMAN_ASSET in " ".join(upload_cmd)
    assert "--clobber=false" in upload_cmd


# Step 4: Extra machine asset, wrong/missing asset, wrong tag/source, wrong release body, wrong remote size, wrong remote SHA-256 all return DRAFT_VALIDATION_FAILED
@pytest.mark.parametrize(
    ("executor_kwargs", "reason"),
    [
        ({"extra_asset": "NekoLauncher.exe"}, "extra machine asset"),
        ({"extra_asset": "release-v2.json"}, "forbidden release-v2.json"),
        ({"extra_asset": "extra_tool.exe"}, "extra custom asset"),
        ({"wrong_asset_name": "wrong_installer.exe"}, "wrong asset name"),
        ({"wrong_tag_readback": "v5.9.9"}, "wrong tag in draft readback"),
        ({"wrong_target_readback": "f" * 40}, "wrong target commit in draft readback"),
        ({"wrong_body_readback": "tampered body missing notices"}, "wrong release body"),
        ({"wrong_remote_size": 9999999}, "wrong remote size"),
        ({"tamper_download": True}, "wrong remote SHA-256"),
    ],
)
def test_step4_failure_paths_return_draft_validation_failed(
    qualified_installer: Path,
    verified_deleted_event: ReleaseAuditEvent,
    approved_human_body: str,
    executor_kwargs: dict[str, Any],
    reason: str,
):
    fake_exec = FakeExecutor(**executor_kwargs)
    result = publish_human_release(
        tag=RELEASE_TAG,
        target_commit=TARGET_COMMIT,
        installer_path=qualified_installer,
        body=approved_human_body,
        deletion_evidence=verified_deleted_event,
        executor=fake_exec,
    )
    assert result.status == "DRAFT_VALIDATION_FAILED", f"Failed for reason: {reason}"
    assert not any("draft=false" in " ".join(cmd) for cmd in fake_exec.commands), (
        f"Promotion was issued despite failure: {reason}"
    )


# Step 5: RED safety test proves none of those failure paths issue a command setting draft=false
def test_invalid_draft_is_never_published(
    fake_exec_with_tampered_remote_asset: FakeExecutor,
    qualified_installer: Path,
    verified_deleted_event: ReleaseAuditEvent,
    approved_human_body: str,
):
    result = publish_human_release(
        tag="v5.1.2",
        target_commit="a" * 40,
        installer_path=qualified_installer,
        body=approved_human_body,
        deletion_evidence=verified_deleted_event,
        executor=fake_exec_with_tampered_remote_asset,
    )
    assert result.status == "DRAFT_VALIDATION_FAILED"
    assert not any(
        "draft=false" in " ".join(cmd)
        for cmd in fake_exec_with_tampered_remote_asset.commands
    )


# Step 6: Valid-draft test: only after draft validation PASS does publisher issue public promotion, then perform fresh public readback
def test_step6_valid_draft_promoted_and_public_readback(
    qualified_installer: Path,
    verified_deleted_event: ReleaseAuditEvent,
    approved_human_body: str,
):
    fake_exec = FakeExecutor()
    result = publish_human_release(
        tag=RELEASE_TAG,
        target_commit=TARGET_COMMIT,
        installer_path=qualified_installer,
        body=approved_human_body,
        deletion_evidence=verified_deleted_event,
        executor=fake_exec,
    )
    assert result.status == "SUCCESS"
    assert result.release_id == 999
    assert result.tag_name == RELEASE_TAG
    assert result.target_commit == TARGET_COMMIT
    assert result.repo == CANONICAL_HUMAN_REPO
    assert result.installer_asset_id == 901
    assert result.installer_size == len(INSTALLER_BYTES)
    assert result.installer_sha256 == hashlib.sha256(INSTALLER_BYTES).hexdigest().lower()

    # Verify promotion command occurred after upload and download check
    edit_cmds = [cmd for cmd in fake_exec.commands if len(cmd) >= 3 and cmd[1:3] == ["release", "edit"]]
    assert len(edit_cmds) == 1
    assert "--draft=false" in edit_cmds[0]
    assert CANONICAL_HUMAN_REPO in edit_cmds[0]

    # Verify public readback occurred after edit command
    edit_idx = fake_exec.commands.index(edit_cmds[0])
    subsequent_cmds = fake_exec.commands[edit_idx + 1 :]
    assert any("api" in cmd and f"repos/{CANONICAL_HUMAN_REPO}/releases" in " ".join(cmd) for cmd in subsequent_cmds)


# Step 7: Body contract test requires v5.1.0-style bilingual structure and explicit 5.1.0 uninstall->5.1.2 install notice
def test_step7_body_contract_required(
    qualified_installer: Path,
    verified_deleted_event: ReleaseAuditEvent,
):
    fake_exec = FakeExecutor()
    invalid_body = "Release notes without required bilingual structure or notices"
    result = publish_human_release(
        tag=RELEASE_TAG,
        target_commit=TARGET_COMMIT,
        installer_path=qualified_installer,
        body=invalid_body,
        deletion_evidence=verified_deleted_event,
        executor=fake_exec,
    )
    assert result.status == "DRAFT_VALIDATION_FAILED"
    assert not any("draft=false" in " ".join(cmd) for cmd in fake_exec.commands)


# Step 8: No-secret-argv test: no gh auth token and no bearer token argv.
# Hosted asset bytes re-read/re-hashed through exact RA5 mechanism:
# gh api repos/{owner}/{repo}/releases/assets/{asset_id} -H "Accept: application/octet-stream"
# with stdout connected directly to parent-opened temporary file; no curl and no shell redirection.
def test_step8_no_secret_argv_and_ra5_download_mechanism(
    qualified_installer: Path,
    verified_deleted_event: ReleaseAuditEvent,
    approved_human_body: str,
):
    fake_exec = FakeExecutor()
    result = publish_human_release(
        tag=RELEASE_TAG,
        target_commit=TARGET_COMMIT,
        installer_path=qualified_installer,
        body=approved_human_body,
        deletion_evidence=verified_deleted_event,
        executor=fake_exec,
    )
    assert result.status == "SUCCESS"

    for cmd in fake_exec.commands:
        cmd_str = " ".join(cmd)
        assert "auth token" not in cmd_str, f"Found secret command: {cmd_str}"
        assert "Bearer" not in cmd_str, f"Found Bearer token in argv: {cmd_str}"
        assert "Authorization:" not in cmd_str, f"Found Authorization header in argv: {cmd_str}"
        assert "curl" not in cmd[0], f"Found curl command: {cmd_str}"
        assert ">" not in cmd and ">>" not in cmd, f"Found shell redirection in argv: {cmd_str}"

    download_cmds = [
        cmd for cmd in fake_exec.commands
        if len(cmd) >= 3 and cmd[0] == "gh" and cmd[1] == "api" and "/releases/assets/" in cmd[2]
    ]
    assert len(download_cmds) == 1
    dl_cmd = download_cmds[0]
    expected_endpoint = f"repos/{CANONICAL_HUMAN_REPO}/releases/assets/901"
    assert dl_cmd[2] == expected_endpoint
    assert "-H" in dl_cmd
    h_idx = dl_cmd.index("-H")
    assert dl_cmd[h_idx + 1] == "Accept: application/octet-stream"


def test_constants_and_exports():
    assert HumanPublishResult is not None
    assert CANONICAL_HUMAN_REPO == "Valeneko-pranmong/Neko-Family-Proxy"
    assert REQUIRED_HUMAN_ASSETS == ("NekoFamilyProxy-Installer.exe",)
    assert REQUIRED_HUMAN_ASSET == "NekoFamilyProxy-Installer.exe"
    assert FORBIDDEN_HUMAN_ASSETS == (
        "NekoLauncher.exe",
        "NekoUpdater.exe",
        "NekoProxyCore.zip",
        "release-v2.json",
    )
