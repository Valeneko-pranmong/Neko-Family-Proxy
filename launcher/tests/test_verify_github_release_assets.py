from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from neko_launcher.updater.canonical_json import canonical_json_dumps
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    get_test_key_registry,
    signed_envelope,
    valid_v2_release_document,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "verify_github_release_assets.py"


def load_verifier_module():
    if not SCRIPT_PATH.exists():
        pytest.fail(f"{SCRIPT_PATH} does not exist yet")
    spec = importlib.util.spec_from_file_location("verify_github_release_assets", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        pytest.fail("Failed to create spec for verify_github_release_assets")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_test_release_bundle(
    tmp_path: Path,
    *,
    tag_name: str = "v5.1.4",
    target_commit: str = "0123456789abcdef0123456789abcdef01234567",
    draft: bool = True,
    prerelease: bool = False,
    include_extra_asset: bool = False,
    key_id: str = TEST_KEY_ID,
    sequence: int = 8,
    minimum_supported_sequence: int = 1,
    release_id: str = "stable-0008",
    proto_min: int = 1,
    proto_max: int = 1,
    launcher_version: str = "5.1.4",
    updater_version: str = "5.1.4",
    core_version: str = "5.1.4",
    channel: str = "stable",
) -> dict[str, Any]:
    download_dir = tmp_path / "download"
    download_dir.mkdir(parents=True, exist_ok=True)

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
        channel=channel,
        sequence=sequence,
        release_id=release_id,
        minimum_supported_sequence=minimum_supported_sequence,
        proto_min=proto_min,
        proto_max=proto_max,
        launcher_version=launcher_version,
        launcher_sha=launcher_sha,
        launcher_size=len(launcher_bytes),
        updater_version=updater_version,
        updater_sha=updater_sha,
        updater_size=len(updater_bytes),
        core_version=core_version,
        core_sha=core_sha,
        core_size=len(core_bytes),
        core_installed_sha=core_sha,
    )

    envelope = signed_envelope(v2_doc, key_id=key_id)
    manifest_bytes = canonical_json_dumps(envelope)
    (download_dir / "release-v2.json").write_bytes(manifest_bytes)

    pub_key_file = tmp_path / "approved.pub"
    pub_key_file.write_bytes(TEST_PUBLIC_KEY)

    assets = [
        {
            "id": 101,
            "name": "NekoLauncher.exe",
            "size": len(launcher_bytes),
            "browser_download_url": (
                f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag_name}/NekoLauncher.exe"
            ),
        },
        {
            "id": 102,
            "name": "NekoUpdater.exe",
            "size": len(updater_bytes),
            "browser_download_url": (
                f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag_name}/NekoUpdater.exe"
            ),
        },
        {
            "id": 103,
            "name": "NekoProxyCore.zip",
            "size": len(core_bytes),
            "browser_download_url": (
                f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag_name}/NekoProxyCore.zip"
            ),
        },
        {
            "id": 104,
            "name": "release-v2.json",
            "size": len(manifest_bytes),
            "browser_download_url": (
                f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag_name}/release-v2.json"
            ),
        },
    ]

    if include_extra_asset:
        assets.append(
            {
                "id": 105,
                "name": "NekoFamilyProxy-Setup.exe",
                "size": 999999,
                "browser_download_url": (
                    f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag_name}/NekoFamilyProxy-Setup.exe"
                ),
            }
        )

    release_doc = {
        "id": 999,
        "tag_name": tag_name,
        "target_commitish": target_commit,
        "draft": draft,
        "prerelease": prerelease,
        "assets": assets,
    }

    release_json_file = tmp_path / "release.json"
    release_json_file.write_text(json.dumps(release_doc, indent=2), encoding="utf-8")

    return {
        "download_dir": download_dir,
        "public_key_file": pub_key_file,
        "release_json_file": release_json_file,
        "expected_tag": tag_name,
        "expected_target": target_commit,
        "v2_doc": v2_doc,
        "envelope": envelope,
        "assets": assets,
        "release_doc": release_doc,
    }


def verify_bundle(verifier: Any, bundle: dict[str, Any], **overrides: Any) -> None:
    arguments = {
        "release_json_path": bundle["release_json_file"],
        "download_dir": bundle["download_dir"],
        "public_key_file": None,
        "expected_tag": bundle["expected_tag"],
        "expected_target": bundle["expected_target"],
        "require_draft": True,
        "expected_key_id": TEST_KEY_ID,
        "trusted_public_keys": get_test_key_registry(),
    }
    arguments.update(overrides)
    verifier.verify_github_release_assets(**arguments)


def test_verify_assets_succeeds_with_in_repo_production_key_omitting_public_key_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, key_id=verifier.EXPECTED_PRODUCTION_KEY_ID)
    monkeypatch.setitem(
        verifier.PRODUCTION_RELEASE_PUBLIC_KEYS,
        verifier.EXPECTED_PRODUCTION_KEY_ID,
        TEST_PUBLIC_KEY,
    )
    verify_bundle(
        verifier,
        bundle,
        expected_key_id=verifier.EXPECTED_PRODUCTION_KEY_ID,
        trusted_public_keys=None,
    )


@pytest.mark.parametrize(
    ("bundle_kwargs", "message"),
    [
        ({"sequence": 1, "release_id": "stable-0001"}, "release_sequence"),
        ({"sequence": 2, "release_id": "stable-0002"}, "release_sequence"),
        ({"sequence": 7, "release_id": "stable-0007"}, "release_sequence"),
        ({"release_id": "stable-0001"}, "release_id"),
        ({"release_id": "stable-9999"}, "release_id"),
        ({"minimum_supported_sequence": 2}, "minimum_supported_sequence"),
        ({"proto_max": 2}, "updater_protocol"),
        ({"launcher_version": "5.1.0a2"}, "launcher version"),
        ({"updater_version": "5.1.0a2"}, "updater version"),
        ({"core_version": "5.1.0a2"}, "core version"),
    ],
)
def test_verify_assets_fails_first_release_invariant(
    tmp_path: Path, bundle_kwargs: dict[str, Any], message: str
) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, **bundle_kwargs)
    with pytest.raises(verifier.GitHubReleaseAssetsVerificationError, match=message):
        verify_bundle(verifier, bundle)


def test_verify_assets_fails_when_envelope_key_id_mismatches_expected(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)
    with pytest.raises(
        verifier.GitHubReleaseAssetsVerificationError, match="Manifest key_id mismatch"
    ):
        verify_bundle(verifier, bundle, expected_key_id="other-key")


def test_verify_assets_fails_when_channel_is_not_stable(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, channel="beta")
    with pytest.raises(
        verifier.GitHubReleaseAssetsVerificationError,
        match="cryptographic verification",
    ):
        verify_bundle(verifier, bundle)


def test_verify_assets_fails_when_updater_protocol_minimum_is_not_one(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, proto_min=2, proto_max=2)
    with pytest.raises(verifier.GitHubReleaseAssetsVerificationError, match="updater_protocol"):
        verify_bundle(verifier, bundle)


def test_verify_assets_fails_when_minimum_supported_sequence_is_not_one(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, minimum_supported_sequence=2)
    with pytest.raises(
        verifier.GitHubReleaseAssetsVerificationError,
        match="minimum_supported_sequence",
    ):
        verify_bundle(verifier, bundle)


def test_cli_rejects_caller_selected_key_authority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)
    with pytest.raises(SystemExit) as error:
        verifier.main(
            [
                "--release-json",
                str(bundle["release_json_file"]),
                "--download-dir",
                str(bundle["download_dir"]),
                "--public-key-file",
                str(bundle["public_key_file"]),
                "--trusted-key-id",
                TEST_KEY_ID,
                "--expected-tag",
                bundle["expected_tag"],
                "--expected-target",
                bundle["expected_target"],
            ]
        )
    assert error.value.code == 2
    assert "unrecognized arguments: --trusted-key-id" in capsys.readouterr().err


def test_verify_assets_fails_when_public_key_file_differs_from_in_repo_registry(
    tmp_path: Path,
) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, key_id=verifier.EXPECTED_PRODUCTION_KEY_ID)
    with pytest.raises(
        verifier.GitHubReleaseAssetsVerificationError,
        match="Public key file does not match in-repo production key registry",
    ):
        verify_bundle(
            verifier,
            bundle,
            public_key_file=bundle["public_key_file"],
            expected_key_id=verifier.EXPECTED_PRODUCTION_KEY_ID,
            trusted_public_keys=None,
        )


def test_verifier_module_loads() -> None:
    module = load_verifier_module()
    assert hasattr(module, "verify_github_release_assets")
    assert hasattr(module, "main")


def test_verify_assets_success_with_required_four_assets(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    verifier.verify_github_release_assets(
        release_json_path=bundle["release_json_file"],
        download_dir=bundle["download_dir"],
        public_key_file=bundle["public_key_file"],
        expected_tag=bundle["expected_tag"],
        expected_target=bundle["expected_target"],
        require_draft=True,
        expected_key_id=TEST_KEY_ID,
        trusted_public_keys=get_test_key_registry(),
    )


def test_verify_assets_permits_and_ignores_human_facing_extras(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, include_extra_asset=True)

    verifier.verify_github_release_assets(
        release_json_path=bundle["release_json_file"],
        download_dir=bundle["download_dir"],
        public_key_file=bundle["public_key_file"],
        expected_tag=bundle["expected_tag"],
        expected_target=bundle["expected_target"],
        require_draft=True,
        expected_key_id=TEST_KEY_ID,
        trusted_public_keys=get_test_key_registry(),
    )


def test_verify_assets_fails_when_missing_required_asset(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    (bundle["download_dir"] / "NekoProxyCore.zip").unlink()

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_when_duplicate_required_asset_name(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    release_doc = bundle["release_doc"]
    release_doc["assets"].append(
        {
            "id": 999,
            "name": "NekoLauncher.exe",
            "size": 1234,
            "browser_download_url": "https://github.com/.../NekoLauncher.exe",
        }
    )
    bundle["release_json_file"].write_text(json.dumps(release_doc), encoding="utf-8")

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_when_duplicate_asset_id(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    release_doc = bundle["release_doc"]
    release_doc["assets"][1]["id"] = release_doc["assets"][0]["id"]
    bundle["release_json_file"].write_text(json.dumps(release_doc), encoding="utf-8")

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_when_tag_mismatch(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag="v9.9.9",
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_when_target_commit_mismatch(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target="ffffffffffffffffffffffffffffffffffffffff",
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_when_require_draft_and_draft_is_false(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, draft=False)

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_when_require_prerelease_and_prerelease_is_false(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, prerelease=False, draft=False)

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_prerelease=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_when_require_prerelease_and_draft_is_true(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, prerelease=True, draft=True)

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_prerelease=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_succeeds_when_require_prerelease_and_prerelease_is_true(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, prerelease=True, draft=False)

    verifier.verify_github_release_assets(
        release_json_path=bundle["release_json_file"],
        download_dir=bundle["download_dir"],
        public_key_file=bundle["public_key_file"],
        expected_tag=bundle["expected_tag"],
        expected_target=bundle["expected_target"],
        require_prerelease=True,
        expected_key_id=TEST_KEY_ID,
        trusted_public_keys=get_test_key_registry(),
    )


def test_verify_assets_fails_when_prerelease_is_true(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path, prerelease=True)

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_on_launcher_size_or_hash_mismatch(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    (bundle["download_dir"] / "NekoLauncher.exe").write_bytes(b"tampered-launcher-bytes")

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_on_updater_size_or_hash_mismatch(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    (bundle["download_dir"] / "NekoUpdater.exe").write_bytes(b"tampered-updater-bytes")

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_on_core_size_or_hash_mismatch(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    (bundle["download_dir"] / "NekoProxyCore.zip").write_bytes(b"tampered-core-bytes")

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_on_manifest_size_mismatch(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    release_doc = bundle["release_doc"]
    for asset in release_doc["assets"]:
        if asset["name"] == "release-v2.json":
            asset["size"] += 10
    bundle["release_json_file"].write_text(json.dumps(release_doc), encoding="utf-8")

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_on_forged_envelope_signature(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    envelope = bundle["envelope"]
    sig = bytearray(json.loads(canonical_json_dumps(envelope))["signature_b64"].encode("ascii"))
    sig[10] = ord("A") if sig[10] != ord("A") else ord("B")
    envelope["signature_b64"] = sig.decode("ascii")

    (bundle["download_dir"] / "release-v2.json").write_bytes(
        canonical_json_dumps(envelope)
    )

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_on_wrong_public_key(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    bundle["public_key_file"].write_bytes(b"\x99" * 32)

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
        )


def test_verify_assets_fails_on_wrong_three_product_binding(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    v2_doc = bundle["v2_doc"]
    del v2_doc["components"]["updater"]
    envelope = signed_envelope(v2_doc, key_id=TEST_KEY_ID)
    (bundle["download_dir"] / "release-v2.json").write_bytes(
        canonical_json_dumps(envelope)
    )

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_on_oversized_manifest(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    (bundle["download_dir"] / "release-v2.json").write_bytes(b"x" * 65537)

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_fails_on_noncanonical_manifest_json(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    envelope = bundle["envelope"]
    non_canonical_bytes = json.dumps(envelope, indent=4).encode("utf-8")
    (bundle["download_dir"] / "release-v2.json").write_bytes(non_canonical_bytes)

    release_doc = bundle["release_doc"]
    for asset in release_doc["assets"]:
        if asset["name"] == "release-v2.json":
            asset["size"] = len(non_canonical_bytes)
    bundle["release_json_file"].write_text(json.dumps(release_doc), encoding="utf-8")

    with pytest.raises(Exception):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_verify_assets_cli_invocation_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)

    exit_code = verifier.main(
        [
            "--release-json",
            str(bundle["release_json_file"]),
            "--download-dir",
            str(bundle["download_dir"]),
            "--public-key-file",
            str(bundle["public_key_file"]),
            "--expected-tag",
            "v0.0.0-wrong",
            "--expected-target",
            bundle["expected_target"],
            "--require-draft",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "github release assets verification failed" in captured.err.lower()


def test_same_size_corruption_in_remote_download_fails_with_valid_local_staging(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    bundle = create_test_release_bundle(tmp_path)
    staged_dir = tmp_path / "local-staging"
    staged_dir.mkdir()
    for path in bundle["download_dir"].iterdir():
        (staged_dir / path.name).write_bytes(path.read_bytes())

    remote_launcher = bundle["download_dir"] / "NekoLauncher.exe"
    original = remote_launcher.read_bytes()
    remote_launcher.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    assert remote_launcher.stat().st_size == (staged_dir / remote_launcher.name).stat().st_size

    verifier.verify_github_release_assets(
        release_json_path=bundle["release_json_file"],
        download_dir=staged_dir,
        public_key_file=bundle["public_key_file"],
        expected_tag=bundle["expected_tag"],
        expected_target=bundle["expected_target"],
        require_draft=True,
        expected_key_id=TEST_KEY_ID,
        trusted_public_keys=get_test_key_registry(),
    )
    with pytest.raises(Exception, match="sha256 mismatch"):
        verifier.verify_github_release_assets(
            release_json_path=bundle["release_json_file"],
            download_dir=bundle["download_dir"],
            public_key_file=bundle["public_key_file"],
            expected_tag=bundle["expected_tag"],
            expected_target=bundle["expected_target"],
            require_draft=True,
            expected_key_id=TEST_KEY_ID,
            trusted_public_keys=get_test_key_registry(),
        )


def test_cli_runs_from_unrelated_cwd_with_only_installed_launcher_runtime(tmp_path: Path) -> None:
    bundle = create_test_release_bundle(tmp_path)
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    env = os.environ.copy()
    launcher_src = str(REPOSITORY_ROOT / "launcher" / "src")
    env["PYTHONPATH"] = launcher_src

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--release-json",
            str(bundle["release_json_file"]),
            "--download-dir",
            str(bundle["download_dir"]),
            "--public-key-file",
            str(bundle["public_key_file"]),
            "--expected-tag",
            bundle["expected_tag"],
            "--expected-target",
            bundle["expected_target"],
            "--require-draft",
        ],
        cwd=unrelated_cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "verification failed" in result.stderr.lower()
