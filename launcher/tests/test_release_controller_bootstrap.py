from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from neko_launcher.updater.canonical_json import canonical_json_dumps  # noqa: E402
from neko_launcher.updater.core_manifest_verifier import (  # noqa: E402
    CORE_MANIFEST_FILENAME,
    verify_canonical_core_bundle,
)
from scripts.release_controller import (  # noqa: E402
    CoreAuthoritySource,
    resolve_core_authority,
    verify_and_fetch_core,
    verify_core_authority_bytes,
)


def _create_synthetic_core_bundle(bundle_dir: Path) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "NekoProxyCore.exe": b"fake-core-exe-content-12345",
        "NekoProxyCore.dll": b"fake-core-dll-content-67890",
        "runtime-settings.nkps": b"fake-nkps-settings",
        "bin/Redirector.bin": b"fake-redirector",
        "bin/nfapi.dll": b"fake-nfapi",
        "bin/v2ray-sn.exe": b"fake-v2ray",
    }
    manifest_files = []
    for rel, data in files.items():
        fp = bundle_dir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(data)
        manifest_files.append({
            "path": rel,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })

    manifest = {
        "rid": "win-x64",
        "executable": "NekoProxyCore.exe",
        "source_commit": "abcdef1234567890abcdef1234567890abcdef12",
        "files": manifest_files,
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    (bundle_dir / CORE_MANIFEST_FILENAME).write_bytes(manifest_bytes)
    return bundle_dir


def _create_bootstrap_fixture(
    fixture_dir: Path,
    *,
    version: str = "5.1.0",
    channel: str = "stable",
    key_id: str = "test-key-1",
    private_key: Ed25519PrivateKey | None = None,
    include_updater: bool = True,
    tamper_signature: bool = False,
    tamper_core_byte: bool = False,
    tamper_updater: bool = False,
) -> tuple[dict[str, bytes], Path]:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    if private_key is None:
        private_key = Ed25519PrivateKey.generate()

    pub_key_bytes = private_key.public_key().public_bytes_raw()
    trusted_keys = {key_id: pub_key_bytes}

    # 1. Create Core bundle and zip
    with tempfile.TemporaryDirectory() as tmp_b:
        bundle_path = _create_synthetic_core_bundle(Path(tmp_b))
        verification = verify_canonical_core_bundle(bundle_path)
        assert verification.valid
        installed_identity = verification.manifest_sha256

        core_zip = fixture_dir / "NekoProxyCore.zip"
        with zipfile.ZipFile(core_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in bundle_path.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(bundle_path))

    if tamper_core_byte:
        core_bytes = core_zip.read_bytes()
        core_zip.write_bytes(core_bytes + b"\x00corrupt")

    core_size = core_zip.stat().st_size
    core_sha = hashlib.sha256(core_zip.read_bytes()).hexdigest()

    updater_bytes = b"MZ\x90\x00updater-binary-content"
    updater_file = fixture_dir / "NekoUpdater.exe"
    if include_updater:
        if tamper_updater:
            updater_file.write_bytes(updater_bytes + b"tampered")
        else:
            updater_file.write_bytes(updater_bytes)
    updater_sha = hashlib.sha256(updater_bytes).hexdigest()

    launcher_bytes = b"MZ\x90\x00launcher-binary-content"
    launcher_sha = hashlib.sha256(launcher_bytes).hexdigest()

    metadata: dict[str, Any] = {
        "schema_version": 2,
        "channel": channel,
        "release_sequence": 4,
        "release_id": "stable-0004",
        "mandatory": False,
        "minimum_supported_sequence": 1,
        "updater_protocol": {"minimum": 1, "maximum": 1},
        "components": {
            "launcher": {
                "version": version,
                "artifact_id": "NekoLauncher.exe",
                "artifact_sha256": launcher_sha,
                "artifact_size": len(launcher_bytes),
                "installed_identity_sha256": launcher_sha,
                "artifact_format": "raw-pe-v1",
            },
            "updater": {
                "version": version,
                "artifact_id": "NekoUpdater.exe",
                "artifact_sha256": updater_sha,
                "artifact_size": len(updater_bytes),
                "installed_identity_sha256": updater_sha,
                "artifact_format": "raw-pe-v1",
            },
            "core": {
                "version": version,
                "artifact_id": "NekoProxyCore.zip",
                "artifact_sha256": core_sha if not tamper_core_byte else hashlib.sha256(b"orig").hexdigest(),
                "artifact_size": core_size if not tamper_core_byte else 1234,
                "installed_identity_sha256": installed_identity,
                "artifact_format": "zip-core-v1",
            },
        },
    }

    payload_bytes = canonical_json_dumps(metadata)
    payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
    sig_bytes = private_key.sign(payload_bytes)
    if tamper_signature:
        sig_bytes = b"\x00" * 64
    sig_b64 = base64.b64encode(sig_bytes).decode("ascii")

    envelope = {
        "envelope_version": 1,
        "key_id": key_id,
        "payload_b64": payload_b64,
        "signature_b64": sig_b64,
    }
    manifest_file = fixture_dir / "release-v2.json"
    manifest_file.write_text(json.dumps(envelope, indent=2), encoding="utf-8")

    return trusted_keys, fixture_dir


def test_valid_archived_bootstrap_authority_succeeds(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    staging_dir = tmp_path / "staging"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir)

    source = resolve_core_authority(
        "v5.1.0",
        staging_dir,
        bootstrap_authority_dir=auth_dir,
        trusted_keys=trusted_keys,
    )

    assert isinstance(source, CoreAuthoritySource)
    assert source.manifest_path.is_file()
    assert source.core_zip_path.is_file()
    assert source.manifest_path.parent == staging_dir
    assert source.core_zip_path.parent == staging_dir
    assert source.provenance["source"] == "local_bootstrap_override"
    assert source.provenance["stable_tag"] == "v5.1.0"
    assert source.provenance["bootstrap_authority_dir"] == str(auth_dir.resolve())


def test_forged_signature_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    staging_dir = tmp_path / "staging"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir, tamper_signature=True)

    with pytest.raises(Exception):
        resolve_core_authority(
            "v5.1.0",
            staging_dir,
            bootstrap_authority_dir=auth_dir,
            trusted_keys=trusted_keys,
        )


def test_changed_core_byte_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    staging_dir = tmp_path / "staging"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir, tamper_core_byte=True)

    with pytest.raises(RuntimeError, match="(?i)(signature|hash|size|mismatch)"):
        resolve_core_authority(
            "v5.1.0",
            staging_dir,
            bootstrap_authority_dir=auth_dir,
            trusted_keys=trusted_keys,
        )


def test_tampered_core_manifest_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    staging_dir = tmp_path / "staging"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir)

    # Corrupt a file inside the zip without modifying zip size/sha metadata before signing
    # Re-pack zip with wrong content for NekoProxyCore.exe
    with tempfile.TemporaryDirectory() as tmp_b:
        bundle_path = _create_synthetic_core_bundle(Path(tmp_b))
        (bundle_path / "NekoProxyCore.exe").write_bytes(b"tampered-binary")
        core_zip = auth_dir / "NekoProxyCore.zip"
        with zipfile.ZipFile(core_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in bundle_path.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(bundle_path))

    with pytest.raises(RuntimeError, match="(?i)(signature|hash|size|bundle|verification)"):
        resolve_core_authority(
            "v5.1.0",
            staging_dir,
            bootstrap_authority_dir=auth_dir,
            trusted_keys=trusted_keys,
        )


def test_wrong_tag_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    staging_dir = tmp_path / "staging"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir, version="5.1.0")

    # Override with v5.0.0 must be rejected
    with pytest.raises(RuntimeError, match="(?i)only permitted for recognized bootstrap stable 'v5.1.0'"):
        resolve_core_authority(
            "v5.0.0",
            staging_dir,
            bootstrap_authority_dir=auth_dir,
            trusted_keys=trusted_keys,
        )


def test_wrong_channel_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    staging_dir = tmp_path / "staging"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir, channel="beta")

    with pytest.raises(RuntimeError, match="(?i)channel is not stable"):
        resolve_core_authority(
            "v5.1.0",
            staging_dir,
            bootstrap_authority_dir=auth_dir,
            trusted_keys=trusted_keys,
        )


def test_missing_asset_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    staging_dir = tmp_path / "staging"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir)

    (auth_dir / "NekoProxyCore.zip").unlink()

    with pytest.raises(RuntimeError, match="(?i)missing required assets"):
        resolve_core_authority(
            "v5.1.0",
            staging_dir,
            bootstrap_authority_dir=auth_dir,
            trusted_keys=trusted_keys,
        )


def test_arbitrary_directory_rejected(tmp_path: Path) -> None:
    empty_dir = tmp_path / "arbitrary"
    empty_dir.mkdir()
    staging_dir = tmp_path / "staging"

    with pytest.raises(RuntimeError):
        resolve_core_authority(
            "v5.1.0",
            staging_dir,
            bootstrap_authority_dir=empty_dir,
        )


def test_no_override_normal_failure_does_not_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    staging_dir = tmp_path / "staging"

    def fake_subprocess_check_output(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["gh", "api"], output=b"not found")

    monkeypatch.setattr(subprocess, "check_output", fake_subprocess_check_output)

    with pytest.raises(RuntimeError, match="Failed to fetch release"):
        resolve_core_authority("v5.1.0", staging_dir, bootstrap_authority_dir=None)


def test_newer_stable_refuses_local_override(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    staging_dir = tmp_path / "staging"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir, version="5.1.1")

    # Newer stable tag must strictly refuse bootstrap override
    with pytest.raises(RuntimeError, match="(?i)(newer than bootstrap stable|disabled)"):
        resolve_core_authority(
            "v5.1.1",
            staging_dir,
            bootstrap_authority_dir=auth_dir,
            trusted_keys=trusted_keys,
        )


def test_updater_mismatch_in_bootstrap_dir_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    staging_dir = tmp_path / "staging"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir, tamper_updater=True)

    with pytest.raises(RuntimeError, match="(?i)NekoUpdater.exe in bootstrap authority does not match"):
        resolve_core_authority(
            "v5.1.0",
            staging_dir,
            bootstrap_authority_dir=auth_dir,
            trusted_keys=trusted_keys,
        )


def test_verify_and_fetch_core_with_bootstrap_authority(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    staging_dir = tmp_path / "staging"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir)

    core_zip, core_hash, core_size, installed_id, prov = verify_and_fetch_core(
        "v5.1.0",
        staging_dir,
        bootstrap_authority_dir=auth_dir,
        trusted_keys=trusted_keys,
    )

    assert core_zip.is_file()
    assert core_hash == hashlib.sha256((staging_dir / "NekoProxyCore.zip").read_bytes()).hexdigest()
    assert core_size == (staging_dir / "NekoProxyCore.zip").stat().st_size
    assert len(installed_id) == 64
    assert prov["source"] == "local_bootstrap_override"


def test_real_archived_attempt3_if_available(tmp_path: Path) -> None:
    attempt3_dir = Path("E:/Github/artifacts/v5.1.0-clean-candidate/attempt-3/publish")
    if not attempt3_dir.is_dir():
        pytest.skip("Attempt-3 directory not found on host.")

    staging_dir = tmp_path / "staging_attempt3"
    source = resolve_core_authority(
        "v5.1.0",
        staging_dir,
        bootstrap_authority_dir=attempt3_dir,
    )
    assert source.manifest_path.is_file()
    assert source.core_zip_path.is_file()
    assert (staging_dir / "NekoUpdater.exe").is_file()
    assert source.provenance["source"] == "local_bootstrap_override"


def test_verify_core_authority_bytes_direct(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "bootstrap_auth"
    trusted_keys, auth_dir = _create_bootstrap_fixture(fixture_dir)

    manifest_file = auth_dir / "release-v2.json"
    core_zip = auth_dir / "NekoProxyCore.zip"
    updater_file = auth_dir / "NekoUpdater.exe"

    actual_hash, actual_size, installed_id = verify_core_authority_bytes(
        manifest_file,
        core_zip,
        expected_tag="v5.1.0",
        trusted_keys=trusted_keys,
        updater_exe_path=updater_file,
    )

    assert len(actual_hash) == 64
    assert actual_size > 0
    assert len(installed_id) == 64

