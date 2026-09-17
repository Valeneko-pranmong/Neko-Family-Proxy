from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest

from neko_launcher.updater.canonical_json import canonical_json_dumps
try:
    from tests.software_update_helpers import (
        TEST_PUBLIC_KEY,
        signed_envelope,
        valid_v2_release_document,
    )
except ImportError:
    from launcher.tests.software_update_helpers import (
        TEST_PUBLIC_KEY,
        signed_envelope,
        valid_v2_release_document,
    )

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "verify_human_release_assets.py"

APPROVED_BODY = """# Neko Family Proxy v5.1.2

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


@pytest.fixture(autouse=True)
def _patch_production_release_public_key(monkeypatch: pytest.MonkeyPatch):
    from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS

    monkeypatch.setitem(
        PRODUCTION_RELEASE_PUBLIC_KEYS, "neko-update-prod-1", TEST_PUBLIC_KEY
    )


def load_human_verifier():
    if not SCRIPT_PATH.exists():
        pytest.fail(f"{SCRIPT_PATH} does not exist yet")
    spec = importlib.util.spec_from_file_location("verify_human_release_assets", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        pytest.fail("Failed to create spec for verify_human_release_assets")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def create_test_human_bundle(
    tmp_path: Path,
    *,
    tag_name: str = "v5.1.2",
    target_commit: str = "0123456789abcdef0123456789abcdef01234567",
    draft: bool = True,
    prerelease: bool = False,
    asset_name: str = "NekoFamilyProxy-Installer.exe",
    asset_size: int | None = None,
    asset_id: int = 501,
    include_extra_asset: bool = False,
    extra_asset_name: str = "NekoLauncher.exe",
    file_bytes: bytes = b"MZ-test-human-installer-binary",
    repo: str = "Valeneko-pranmong/Neko-Family-Proxy",
    body: str = APPROVED_BODY,
) -> dict[str, Any]:
    download_dir = tmp_path / "human_download"
    download_dir.mkdir(parents=True, exist_ok=True)

    installer_file = download_dir / asset_name
    installer_file.write_bytes(file_bytes)

    actual_size = len(file_bytes) if asset_size is None else asset_size
    actual_sha256 = hashlib.sha256(file_bytes).hexdigest().lower()

    assets = [
        {
            "id": asset_id,
            "name": asset_name,
            "size": actual_size,
            "browser_download_url": f"https://github.com/{repo}/releases/download/{tag_name}/{asset_name}",
        }
    ]

    if include_extra_asset:
        assets.append(
            {
                "id": 502,
                "name": extra_asset_name,
                "size": 1234,
                "browser_download_url": f"https://github.com/{repo}/releases/download/{tag_name}/{extra_asset_name}",
            }
        )

    release_doc = {
        "id": 999,
        "tag_name": tag_name,
        "target_commitish": target_commit,
        "draft": draft,
        "prerelease": prerelease,
        "body": body,
        "assets": assets,
        "url": f"https://api.github.com/repos/{repo}/releases/999",
        "html_url": f"https://github.com/{repo}/releases/tag/{tag_name}",
    }

    release_json_file = tmp_path / "human_release.json"
    release_json_file.write_text(json.dumps(release_doc, indent=2), encoding="utf-8")

    return {
        "installer_path": installer_file,
        "release_json_file": release_json_file,
        "expected_tag": tag_name,
        "expected_target": target_commit,
        "expected_repo": repo,
        "actual_sha256": actual_sha256,
        "actual_size": len(file_bytes),
        "release_doc": release_doc,
        "body": body,
    }


def create_test_unified_human_bundle(
    tmp_path: Path,
    *,
    tag_name: str = "v5.1.2",
    target_commit: str = "0123456789abcdef0123456789abcdef01234567",
    draft: bool = True,
    prerelease: bool = False,
    include_extra_asset: bool = False,
    extra_asset_name: str = "extra.exe",
    installer_bytes: bytes = b"MZ-test-human-installer-binary",
    key_id: str = "neko-update-prod-1",
    repo: str = "Valeneko-pranmong/Neko-Family-Proxy",
    body: str = APPROVED_BODY,
) -> dict[str, Any]:
    download_dir = tmp_path / "unified_human_download"
    download_dir.mkdir(parents=True, exist_ok=True)

    installer_file = download_dir / "NekoFamilyProxy-Installer.exe"
    installer_file.write_bytes(installer_bytes)

    launcher_bytes = b"MZ-test-launcher-binary-content"
    updater_bytes = b"MZ-test-updater-binary-content"
    core_bytes = b"PK-test-core-zip-content"

    launcher_sha = hashlib.sha256(launcher_bytes).hexdigest()
    updater_sha = hashlib.sha256(updater_bytes).hexdigest()
    core_sha = hashlib.sha256(core_bytes).hexdigest()

    (download_dir / "NekoLauncher.exe").write_bytes(launcher_bytes)
    (download_dir / "NekoUpdater.exe").write_bytes(updater_bytes)
    (download_dir / "NekoProxyCore.zip").write_bytes(core_bytes)

    v2_doc = valid_v2_release_document(
        channel="stable",
        sequence=8,
        release_id="stable-0008",
        minimum_supported_sequence=1,
        proto_min=1,
        proto_max=1,
        launcher_version="5.1.2",
        launcher_sha=launcher_sha,
        launcher_size=len(launcher_bytes),
        updater_version="5.1.2",
        updater_sha=updater_sha,
        updater_size=len(updater_bytes),
        core_version="5.1.2",
        core_sha=core_sha,
        core_size=len(core_bytes),
        core_installed_sha=core_sha,
    )

    envelope = signed_envelope(v2_doc, key_id=key_id)
    manifest_bytes = canonical_json_dumps(envelope)
    (download_dir / "release-v2.json").write_bytes(manifest_bytes)

    pub_key_file = tmp_path / "approved.pub"
    pub_key_file.write_bytes(TEST_PUBLIC_KEY)

    actual_sha256 = hashlib.sha256(installer_bytes).hexdigest().lower()

    assets = [
        {
            "id": 501,
            "name": "NekoFamilyProxy-Installer.exe",
            "size": len(installer_bytes),
            "browser_download_url": f"https://github.com/{repo}/releases/download/{tag_name}/NekoFamilyProxy-Installer.exe",
        },
        {
            "id": 502,
            "name": "release-v2.json",
            "size": len(manifest_bytes),
            "browser_download_url": f"https://github.com/{repo}/releases/download/{tag_name}/release-v2.json",
        },
        {
            "id": 503,
            "name": "NekoLauncher.exe",
            "size": len(launcher_bytes),
            "browser_download_url": f"https://github.com/{repo}/releases/download/{tag_name}/NekoLauncher.exe",
        },
        {
            "id": 504,
            "name": "NekoUpdater.exe",
            "size": len(updater_bytes),
            "browser_download_url": f"https://github.com/{repo}/releases/download/{tag_name}/NekoUpdater.exe",
        },
        {
            "id": 505,
            "name": "NekoProxyCore.zip",
            "size": len(core_bytes),
            "browser_download_url": f"https://github.com/{repo}/releases/download/{tag_name}/NekoProxyCore.zip",
        },
    ]

    if include_extra_asset:
        assets.append(
            {
                "id": 506,
                "name": extra_asset_name,
                "size": 1234,
                "browser_download_url": f"https://github.com/{repo}/releases/download/{tag_name}/{extra_asset_name}",
            }
        )

    release_doc = {
        "id": 999,
        "tag_name": tag_name,
        "target_commitish": target_commit,
        "draft": draft,
        "prerelease": prerelease,
        "body": body,
        "assets": assets,
        "url": f"https://api.github.com/repos/{repo}/releases/999",
        "html_url": f"https://github.com/{repo}/releases/tag/{tag_name}",
    }

    release_json_file = tmp_path / "unified_human_release.json"
    release_json_file.write_text(json.dumps(release_doc, indent=2), encoding="utf-8")

    return {
        "installer_path": installer_file,
        "release_json_file": release_json_file,
        "expected_tag": tag_name,
        "expected_target": target_commit,
        "expected_repo": repo,
        "actual_sha256": actual_sha256,
        "actual_size": len(installer_bytes),
        "release_doc": release_doc,
        "body": body,
        "public_key_file": pub_key_file,
    }


def test_constants_present():
    verifier = load_human_verifier()
    assert verifier.CANONICAL_HUMAN_REPO == "Valeneko-pranmong/Neko-Family-Proxy"
    assert verifier.CANONICAL_REPO == "Valeneko-pranmong/Neko-Family-Proxy"
    assert verifier.REQUIRED_UNIFIED_ASSETS == (
        "NekoFamilyProxy-Installer.exe",
        "release-v2.json",
        "NekoLauncher.exe",
        "NekoUpdater.exe",
        "NekoProxyCore.zip",
    )
    assert verifier.REQUIRED_HUMAN_ASSETS == ("NekoFamilyProxy-Installer.exe",)
    assert verifier.REQUIRED_HUMAN_ASSET == "NekoFamilyProxy-Installer.exe"


def test_verify_human_release_success(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_unified_human_bundle(tmp_path)

    sha256, size = verifier.verify_human_release_assets(
        release_json_path=bundle["release_json_file"],
        installer_path=bundle["installer_path"],
        expected_tag=bundle["expected_tag"],
        expected_target=bundle["expected_target"],
        require_draft=True,
        expected_repo=bundle["expected_repo"],
        expected_body=bundle["body"],
        public_key_file=bundle["public_key_file"],
    )
    assert sha256 == bundle["actual_sha256"]
    assert size == bundle["actual_size"]


def test_normal_human_verifier_rejects_installer_only_release(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_human_bundle(tmp_path)
    with pytest.raises(verifier.HumanReleaseVerificationError, match="[Mm]issing required release asset"):
        verifier.verify_human_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_repo=bundle["expected_repo"],
            expected_body=bundle["body"],
        )


def test_historical_human_verifier_accepts_installer_only_release(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_human_bundle(tmp_path)
    sha256, size = verifier.verify_human_release_assets(
        release_json_path=bundle["release_json_file"],
        installer_path=bundle["installer_path"],
        expected_tag=bundle["expected_tag"],
        expected_target=bundle["expected_target"],
        require_draft=True,
        expected_repo=bundle["expected_repo"],
        expected_body=bundle["body"],
        historical=True,
    )
    assert sha256 == bundle["actual_sha256"]
    assert size == bundle["actual_size"]


def test_reject_extra_assets(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_unified_human_bundle(tmp_path, include_extra_asset=True, extra_asset_name="extra.exe")
    with pytest.raises(verifier.HumanReleaseVerificationError, match="[Ee]xactly one custom asset|extra assets"):
        verifier.verify_human_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            public_key_file=bundle["public_key_file"],
        )


@pytest.mark.parametrize(
    "forbidden_name",
    [
        "NekoLauncher.exe",
        "NekoUpdater.exe",
        "NekoProxyCore.zip",
        "release-v2.json",
    ],
)
def test_reject_forbidden_machine_assets_in_historical_mode(tmp_path: Path, forbidden_name: str):
    verifier = load_human_verifier()
    bundle = create_test_human_bundle(tmp_path, include_extra_asset=True, extra_asset_name=forbidden_name)
    with pytest.raises(verifier.HumanReleaseVerificationError, match="[Ff]orbidden|[Ee]xactly one custom asset"):
        verifier.verify_human_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            historical=True,
        )


def test_normal_human_verifier_does_not_forbid_machine_assets(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_unified_human_bundle(tmp_path)
    sha256, size = verifier.verify_human_release_assets(
        release_json_path=bundle["release_json_file"],
        installer_path=bundle["installer_path"],
        expected_tag=bundle["expected_tag"],
        expected_target=bundle["expected_target"],
        require_draft=True,
        expected_repo=bundle["expected_repo"],
        expected_body=bundle["body"],
        public_key_file=bundle["public_key_file"],
    )
    assert sha256 == bundle["actual_sha256"]


def test_reject_wrong_asset_name(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_human_bundle(tmp_path, asset_name="WrongName.exe")
    with pytest.raises(verifier.HumanReleaseVerificationError, match="[Aa]sset name mismatch"):
        verifier.verify_human_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            historical=True,
        )


def test_reject_retired_installer_repo(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_human_bundle(tmp_path, repo="Valeneko-pranmong/Neko-Family-Proxy-Installer")
    with pytest.raises(verifier.HumanReleaseVerificationError, match="[Rr]etired|[Rr]epository mismatch"):
        verifier.verify_human_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_reject_mismatched_size_or_digest(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_human_bundle(tmp_path, asset_size=999999)
    with pytest.raises(verifier.HumanReleaseVerificationError, match="[Ss]ize mismatch"):
        verifier.verify_human_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            historical=True,
        )


def test_normal_human_verifier_rejects_installer_size_mismatch(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_unified_human_bundle(tmp_path)
    bundle["release_doc"]["assets"][0]["size"] = 999999
    bundle["release_json_file"].write_text(json.dumps(bundle["release_doc"]), encoding="utf-8")
    with pytest.raises(verifier.HumanReleaseVerificationError, match="[Ss]ize mismatch"):
        verifier.verify_human_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            public_key_file=bundle["public_key_file"],
        )


def test_reject_mismatched_tag_or_target(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_human_bundle(tmp_path)
    with pytest.raises(verifier.HumanReleaseVerificationError, match="[Tt]ag mismatch"):
        verifier.verify_human_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag="v5.9.9",
            expected_target=bundle["expected_target"],
            require_draft=True,
        )
    with pytest.raises(verifier.HumanReleaseVerificationError, match="[Tt]arget commit mismatch"):
        verifier.verify_human_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target="f" * 40,
            require_draft=True,
        )


def test_reject_prerelease_flag(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_human_bundle(tmp_path, prerelease=True)
    with pytest.raises(verifier.HumanReleaseVerificationError, match="[Pp]rerelease flag must be false"):
        verifier.verify_human_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_body_contract_validation():
    verifier = load_human_verifier()

    # Valid body passes
    verifier.validate_human_release_body(APPROVED_BODY, tag="v5.1.2")

    # Missing Highlights section
    missing_highlights = APPROVED_BODY.replace("## Highlights | จุดเด่น", "## Other | อื่นๆ")
    with pytest.raises(verifier.HumanReleaseVerificationError, match="Highlights"):
        verifier.validate_human_release_body(missing_highlights, tag="v5.1.2")

    # Missing Downloads section
    missing_downloads = APPROVED_BODY.replace("## Downloads | ดาวน์โหลด", "## Files")
    with pytest.raises(verifier.HumanReleaseVerificationError, match="Downloads"):
        verifier.validate_human_release_body(missing_downloads, tag="v5.1.2")

    # Missing Notes section
    missing_notes = APPROVED_BODY.replace("## Notes | หมายเหตุ", "## Misc")
    with pytest.raises(verifier.HumanReleaseVerificationError, match="Notes"):
        verifier.validate_human_release_body(missing_notes, tag="v5.1.2")

    # Missing Thai text
    english_only = """# Neko Family Proxy v5.1.2
Current stable release for general users. Normal users download Installer ONLY.
## Highlights | จุดเด่น
- Release v5.1.2 baseline update
## Downloads | ดาวน์โหลด
- NekoFamilyProxy-Installer.exe
## Notes | หมายเหตุ
- Notice for v5.1.0 users: Please uninstall v5.1.0 completely and manually install v5.1.2.
"""
    # Wait, english_only has "จุดเด่น", "ดาวน์โหลด", "หมายเหตุ". If we strip all Thai:
    pure_english = english_only.replace("จุดเด่น", "Highlights").replace("ดาวน์โหลด", "Downloads").replace("หมายเหตุ", "Notes")
    with pytest.raises(verifier.HumanReleaseVerificationError):
        verifier.validate_human_release_body(pure_english, tag="v5.1.2")

    # Missing 5.1.0 uninstall notice
    missing_migration = APPROVED_BODY.replace("uninstall v5.1.0", "upgrade from older versions").replace("ถอนการติดตั้ง v5.1.0", "อัปเกรด")
    with pytest.raises(verifier.HumanReleaseVerificationError, match="uninstall|5.1.0"):
        verifier.validate_human_release_body(missing_migration, tag="v5.1.2")

    # Missing 5.1.2 install notice
    missing_install = APPROVED_BODY.replace("install v5.1.2", "run the new version").replace("ติดตั้ง v5.1.2", "เปิดใช้งาน")
    with pytest.raises(verifier.HumanReleaseVerificationError, match="install|5.1.2"):
        verifier.validate_human_release_body(missing_install, tag="v5.1.2")


def test_cli_verify_human_release_assets(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_unified_human_bundle(tmp_path)

    exit_code = verifier.main(
        [
            "--release-json",
            str(bundle["release_json_file"]),
            "--installer-path",
            str(bundle["installer_path"]),
            "--expected-tag",
            bundle["expected_tag"],
            "--expected-target",
            bundle["expected_target"],
            "--require-draft",
            "--expected-repo",
            bundle["expected_repo"],
            "--public-key-file",
            str(bundle["public_key_file"]),
        ]
    )
    assert exit_code == 0


def test_cli_verify_historical_human_release_assets(tmp_path: Path):
    verifier = load_human_verifier()
    bundle = create_test_human_bundle(tmp_path)

    exit_code = verifier.main(
        [
            "--release-json",
            str(bundle["release_json_file"]),
            "--installer-path",
            str(bundle["installer_path"]),
            "--expected-tag",
            bundle["expected_tag"],
            "--expected-target",
            bundle["expected_target"],
            "--require-draft",
            "--expected-repo",
            bundle["expected_repo"],
            "--historical",
        ]
    )
    assert exit_code == 0
