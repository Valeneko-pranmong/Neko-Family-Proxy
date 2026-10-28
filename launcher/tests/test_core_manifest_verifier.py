from __future__ import annotations

import hashlib
import json
from pathlib import Path

from neko_launcher.updater.core_manifest_verifier import verify_canonical_core_bundle

_MANDATORY = (
    "NekoProxyCore.exe",
    "NekoProxyCore.dll",
    "runtime-settings.nkps",
    "bin/Redirector.bin",
    "bin/nfapi.dll",
    "bin/v2ray-sn.exe",
)

_FIELD_TO_PATH = {
    "neko_proxy_core_exe_hash": "NekoProxyCore.exe",
    "neko_proxy_core_dll_hash": "NekoProxyCore.dll",
    "protected_settings_payload_hash": "runtime-settings.nkps",
    "redirector_bin_hash": "bin/Redirector.bin",
    "nfapi_dll_hash": "bin/nfapi.dll",
    "v2ray_sn_exe_hash": "bin/v2ray-sn.exe",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_files(bundle: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        path = bundle / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _write_frozen_manifest(bundle: Path, files: dict[str, bytes], *, file_count: int | None = None) -> str:
    hashes = {rel: _sha(data) for rel, data in files.items()}
    manifest = {
        "source_commit": "b7d9708bc2c9a97255a9ea2f8307ef66e2d81bf8",
        "file_count": len(files) if file_count is None else file_count,
        "files": hashes,
    }
    for field, rel in _FIELD_TO_PATH.items():
        if rel in hashes:
            manifest[field] = hashes[rel]
    raw = json.dumps(manifest, sort_keys=True).encode("utf-8")
    (bundle / "core-manifest.json").write_bytes(raw)
    return _sha(raw)


def _valid_files() -> dict[str, bytes]:
    files = {rel: f"content:{rel}".encode("utf-8") for rel in _MANDATORY}
    files["extra/data.bin"] = b"extra"
    return files


def test_frozen_authority_manifest_is_valid(tmp_path: Path) -> None:
    bundle = tmp_path / "core"
    bundle.mkdir()
    files = _valid_files()
    _write_files(bundle, files)
    expected_manifest_sha = _write_frozen_manifest(bundle, files)

    result = verify_canonical_core_bundle(bundle)

    assert result.valid is True
    assert result.error is None
    assert result.file_count == len(files)
    assert result.total_bytes == sum(len(data) for data in files.values())
    assert result.manifest_sha256 == expected_manifest_sha


def test_frozen_authority_manifest_rejects_tampered_file(tmp_path: Path) -> None:
    bundle = tmp_path / "core"
    bundle.mkdir()
    files = _valid_files()
    _write_files(bundle, files)
    _write_frozen_manifest(bundle, files)
    (bundle / "bin" / "nfapi.dll").write_bytes(b"tampered")

    result = verify_canonical_core_bundle(bundle)

    assert result.valid is False
    assert "Hash mismatch" in (result.error or "")


def test_frozen_authority_manifest_rejects_unlisted_file(tmp_path: Path) -> None:
    bundle = tmp_path / "core"
    bundle.mkdir()
    files = _valid_files()
    _write_files(bundle, files)
    _write_frozen_manifest(bundle, files)
    (bundle / "unlisted.bin").write_bytes(b"unexpected")

    result = verify_canonical_core_bundle(bundle)

    assert result.valid is False
    assert "Unlisted file" in (result.error or "")


def test_frozen_authority_manifest_requires_mandatory_files(tmp_path: Path) -> None:
    bundle = tmp_path / "core"
    bundle.mkdir()
    files = _valid_files()
    del files["bin/v2ray-sn.exe"]
    _write_files(bundle, files)
    _write_frozen_manifest(bundle, files)

    result = verify_canonical_core_bundle(bundle)

    assert result.valid is False
    assert "Missing mandatory Core file" in (result.error or "")


def test_frozen_authority_manifest_rejects_file_count_mismatch(tmp_path: Path) -> None:
    bundle = tmp_path / "core"
    bundle.mkdir()
    files = _valid_files()
    _write_files(bundle, files)
    _write_frozen_manifest(bundle, files, file_count=len(files) + 1)

    result = verify_canonical_core_bundle(bundle)

    assert result.valid is False
    assert "file_count" in (result.error or "")


def test_canonical_manifest_still_valid(tmp_path: Path) -> None:
    bundle = tmp_path / "core"
    bundle.mkdir()
    files = _valid_files()
    _write_files(bundle, files)
    manifest = {
        "rid": "win-x64",
        "executable": "NekoProxyCore.exe",
        "source_commit": "b7d9708bc2c9a97255a9ea2f8307ef66e2d81bf8",
        "files": [
            {"path": rel, "size": len(data), "sha256": _sha(data)}
            for rel, data in files.items()
        ],
    }
    raw = json.dumps(manifest, sort_keys=True).encode("utf-8")
    (bundle / "core-manifest.json").write_bytes(raw)

    result = verify_canonical_core_bundle(bundle)

    assert result.valid is True
    assert result.file_count == len(files)
    assert result.manifest_sha256 == _sha(raw)
