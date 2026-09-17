from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.project_release_audit_ledger import (  # noqa: E402
    EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
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
def test_publish_human_release_is_superseded(qualified_installer: Path, verified_deleted_event: ReleaseAuditEvent, approved_human_body: str):
    fake_exec = FakeExecutor()
    with pytest.raises(HumanPublishError, match="superseded"):
        publish_human_release(
            tag=RELEASE_TAG,
            target_commit=TARGET_COMMIT,
            installer_path=qualified_installer,
            body=approved_human_body,
            deletion_evidence=verified_deleted_event,
            executor=fake_exec,
        )

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
