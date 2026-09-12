from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "verify_installer_release_assets.py"


def load_installer_verifier():
    if not SCRIPT_PATH.exists():
        pytest.fail(f"{SCRIPT_PATH} does not exist yet")
    spec = importlib.util.spec_from_file_location("verify_installer_release_assets", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        pytest.fail("Failed to create spec for verify_installer_release_assets")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def create_test_installer_bundle(
    tmp_path: Path,
    *,
    tag_name: str = "v5.1.1",
    target_commit: str = "0123456789abcdef0123456789abcdef01234567",
    draft: bool = True,
    prerelease: bool = False,
    asset_name: str = "NekoFamilyProxy-Installer.exe",
    asset_size: int | None = None,
    asset_id: int = 401,
    include_extra_asset: bool = False,
    extra_asset_name: str = "NekoFamilyProxy-Setup.exe",
    file_bytes: bytes = b"MZ-test-installer-binary-data",
    repo: str = "Valeneko-pranmong/Neko-Family-Proxy-Installer",
) -> dict[str, Any]:
    download_dir = tmp_path / "installer_download"
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
                "id": 402,
                "name": extra_asset_name,
                "size": 9999,
                "browser_download_url": f"https://github.com/{repo}/releases/download/{tag_name}/{extra_asset_name}",
            }
        )

    release_doc = {
        "id": 888,
        "tag_name": tag_name,
        "target_commitish": target_commit,
        "draft": draft,
        "prerelease": prerelease,
        "assets": assets,
        "url": f"https://api.github.com/repos/{repo}/releases/888",
    }

    release_json_file = tmp_path / "installer_release.json"
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
    }


def test_verify_installer_release_success(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path)

    digest, size = verifier.verify_installer_release_assets(
        release_json_path=bundle["release_json_file"],
        installer_path=bundle["installer_path"],
        expected_tag=bundle["expected_tag"],
        expected_target=bundle["expected_target"],
        require_draft=True,
        expected_repo=bundle["expected_repo"],
    )

    assert digest == bundle["actual_sha256"]
    assert size == bundle["actual_size"]


def test_verify_installer_release_rejects_missing_asset(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path)
    bundle["release_doc"]["assets"] = []
    bundle["release_json_file"].write_text(json.dumps(bundle["release_doc"]), encoding="utf-8")

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="exactly one custom asset"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_verify_installer_release_rejects_extra_assets(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path, include_extra_asset=True)

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="exactly one custom asset"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_verify_installer_release_rejects_wrong_asset_name(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path, asset_name="NekoFamilyProxy-Setup.exe")

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="NekoFamilyProxy-Installer.exe"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_verify_installer_release_rejects_canonical_machine_repo(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(
        tmp_path, repo="Valeneko-pranmong/Neko-Family-Proxy"
    )

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="canonical machine"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_repo="Valeneko-pranmong/Neko-Family-Proxy",
        )


def test_verify_installer_release_rejects_tag_mismatch(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path)

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="tag mismatch"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag="v5.1.2",
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_verify_installer_release_rejects_target_commit_mismatch(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path)

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="target commit mismatch"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target="1111111111111111111111111111111111111111",
            require_draft=True,
        )


def test_verify_installer_release_rejects_draft_mismatch(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path, draft=False)

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="draft"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_verify_installer_release_rejects_size_mismatch(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path, asset_size=123456)

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="size mismatch"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_verify_installer_release_rejects_non_positive_size(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path, asset_size=0)

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="positive integer"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_verify_installer_release_rejects_missing_installer_file(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path)
    bundle["installer_path"].unlink()

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="Installer file missing"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_verify_installer_release_rejects_missing_json(tmp_path: Path) -> None:
    verifier = load_installer_verifier()
    bundle = create_test_installer_bundle(tmp_path)
    bundle["release_json_file"].unlink()

    with pytest.raises(verifier.InstallerReleaseVerificationError, match="Release JSON file not found"):
        verifier.verify_installer_release_assets(
            release_json_path=bundle["release_json_file"],
            installer_path=bundle["installer_path"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
        )


def test_installer_verifier_has_no_signing_secret_dependency() -> None:
    verifier = load_installer_verifier()
    # Check that the verifier does not export or require signing keys or manifest verifier
    assert not hasattr(verifier, "PRODUCTION_RELEASE_PUBLIC_KEYS")
    assert not hasattr(verifier, "verify_release_envelope_v2")
