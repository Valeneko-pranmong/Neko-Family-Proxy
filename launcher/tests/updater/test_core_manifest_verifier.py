import hashlib
import json
from pathlib import Path

import os
import pytest

from neko_launcher.updater.core_manifest_verifier import (
    CORE_MANIFEST_FILENAME,
    verify_canonical_core_bundle,
)

CANONICAL_A43_ROOT = Path(os.environ.get("NEKO_TEST_FIXTURE_A43", "E:/Github/worktrees/NekoProxyCore-live-update/TestResults/task12/a43-core"))

@pytest.mark.integration
def test_verifies_canonical_a43_fixture() -> None:
    if not CANONICAL_A43_ROOT.exists():
        pytest.skip(f"Missing external fixture: {CANONICAL_A43_ROOT}")
    res = verify_canonical_core_bundle(CANONICAL_A43_ROOT)
    assert res.valid
    assert res.file_count == 1022
    assert res.total_bytes == 371717577
    assert res.manifest_sha256 == "0e0cd94c0a56eb2e20897035f6445d60be9cbcfcdd21f2d0fa48c94e883a3972"


def _create_test_bundle(
    bundle_dir: Path,
    *,
    files: dict[str, bytes] | None = None,
    rid: str = "win-x64",
    executable: str = "NekoProxyCore.exe",
    source_commit: str = "1234567890abcdef1234567890abcdef12345678",
    tamper_hash: str | None = None,
    tamper_size: int | None = None,
    extra_disk_file: tuple[str, bytes] | None = None,
) -> Path:
    if files is None:
        files = {
            "NekoProxyCore.exe": b"test-core-exe",
            "NekoProxyCore.dll": b"test-core-dll",
            "runtime-settings.nkps": b"test-nkps-payload",
            "bin/Redirector.bin": b"test-redirector-bin",
            "bin/nfapi.dll": b"test-nfapi-dll",
            "bin/v2ray-sn.exe": b"test-v2ray-exe",
        }

    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    for rel_path, data in files.items():
        file_path = bundle_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)

        file_hash = hashlib.sha256(data).hexdigest()
        file_size = len(data)
        if tamper_hash and rel_path == "NekoProxyCore.exe":
            file_hash = tamper_hash
        if tamper_size and rel_path == "NekoProxyCore.exe":
            file_size = tamper_size

        manifest_files.append({
            "path": rel_path,
            "size": file_size,
            "sha256": file_hash,
        })

    manifest = {
        "rid": rid,
        "executable": executable,
        "source_commit": source_commit,
        "files": manifest_files,
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    (bundle_dir / CORE_MANIFEST_FILENAME).write_bytes(manifest_bytes)

    if extra_disk_file:
        extra_path, extra_data = extra_disk_file
        target = bundle_dir / extra_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(extra_data)

    return bundle_dir


def test_verifies_valid_core_bundle(tmp_path: Path) -> None:
    bundle = _create_test_bundle(tmp_path / "valid_bundle")
    res = verify_canonical_core_bundle(bundle)
    assert res.valid
    assert res.file_count == 6
    assert res.total_bytes > 0
    assert res.manifest_sha256 != ""
    assert res.error is None


def test_rejects_tampered_core_bundle_hash_mismatch(tmp_path: Path) -> None:
    bundle = _create_test_bundle(
        tmp_path / "tampered_hash_bundle",
        tamper_hash="0" * 64,
    )
    res = verify_canonical_core_bundle(bundle)
    assert not res.valid
    assert "hash mismatch" in (res.error or "").lower()


def test_rejects_tampered_core_bundle_size_mismatch(tmp_path: Path) -> None:
    bundle = _create_test_bundle(
        tmp_path / "tampered_size_bundle",
        tamper_size=999999,
    )
    res = verify_canonical_core_bundle(bundle)
    assert not res.valid
    assert "size mismatch" in (res.error or "").lower()


def test_rejects_incomplete_core_bundle_missing_mandatory_file(tmp_path: Path) -> None:
    # Missing bin/v2ray-sn.exe
    files = {
        "NekoProxyCore.exe": b"test-core-exe",
        "NekoProxyCore.dll": b"test-core-dll",
        "runtime-settings.nkps": b"test-nkps-payload",
        "bin/Redirector.bin": b"test-redirector-bin",
        "bin/nfapi.dll": b"test-nfapi-dll",
    }
    bundle = _create_test_bundle(tmp_path / "incomplete_bundle", files=files)
    res = verify_canonical_core_bundle(bundle)
    assert not res.valid
    assert "missing mandatory core file" in (res.error or "").lower()


def test_rejects_missing_manifest(tmp_path: Path) -> None:
    bundle = tmp_path / "no_manifest_bundle"
    bundle.mkdir(parents=True)
    (bundle / "NekoProxyCore.exe").write_bytes(b"dummy")
    res = verify_canonical_core_bundle(bundle)
    assert not res.valid
    assert "core-manifest.json missing" in (res.error or "")


def test_rejects_invalid_schema_missing_rid(tmp_path: Path) -> None:
    bundle = tmp_path / "missing_rid_bundle"
    bundle.mkdir(parents=True)
    (bundle / "NekoProxyCore.exe").write_bytes(b"dummy")
    manifest = {
        "executable": "NekoProxyCore.exe",
        "source_commit": "1234567890abcdef",
        "files": [{"path": "NekoProxyCore.exe", "size": 5, "sha256": "0" * 64}],
    }
    (bundle / CORE_MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    res = verify_canonical_core_bundle(bundle)
    assert not res.valid
    assert "missing required manifest fields" in (res.error or "").lower()


def test_rejects_invalid_schema_missing_executable(tmp_path: Path) -> None:
    bundle = tmp_path / "missing_exe_bundle"
    bundle.mkdir(parents=True)
    (bundle / "NekoProxyCore.exe").write_bytes(b"dummy")
    manifest = {
        "rid": "win-x64",
        "source_commit": "1234567890abcdef",
        "files": [{"path": "NekoProxyCore.exe", "size": 5, "sha256": "0" * 64}],
    }
    (bundle / CORE_MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    res = verify_canonical_core_bundle(bundle)
    assert not res.valid
    assert "missing required manifest fields" in (res.error or "").lower()


def test_rejects_forbidden_file_in_manifest(tmp_path: Path) -> None:
    files = {
        "NekoProxyCore.exe": b"test-core-exe",
        "NekoProxyCore.dll": b"test-core-dll",
        "runtime-settings.nkps": b"test-nkps-payload",
        "bin/Redirector.bin": b"test-redirector-bin",
        "bin/nfapi.dll": b"test-nfapi-dll",
        "bin/v2ray-sn.exe": b"test-v2ray-exe",
        "runtime-settings.key": b"secret-key",
    }
    bundle = _create_test_bundle(tmp_path / "forbidden_bundle", files=files)
    res = verify_canonical_core_bundle(bundle)
    assert not res.valid
    assert "forbidden file in manifest" in (res.error or "").lower()


def test_rejects_unlisted_disk_file(tmp_path: Path) -> None:
    bundle = _create_test_bundle(
        tmp_path / "unlisted_bundle",
        extra_disk_file=("extra_sneaky_file.dll", b"surprise"),
    )
    res = verify_canonical_core_bundle(bundle)
    assert not res.valid
    assert "unlisted file found on disk" in (res.error or "").lower()
