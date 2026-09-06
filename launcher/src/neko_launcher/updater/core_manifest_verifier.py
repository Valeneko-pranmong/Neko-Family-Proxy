"""Canonical Core manifest and on-disk bundle verifier."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

_REQUIRED_TOP_KEYS = {
    "source_commit",
    "candidate",
    "authority",
    "file_count",
    "total_bytes",
    "neko_proxy_core_exe_hash",
    "neko_proxy_core_dll_hash",
    "protected_settings_payload_hash",
    "redirector_bin_hash",
    "nfapi_dll_hash",
    "v2ray_sn_exe_hash",
    "security",
    "files",
}

_REQUIRED_SECURITY_KEYS = {
    "runtime_settings_key_files",
    "plaintext_settings_files",
    "plaintext_secret_marker_hits",
    "external_dotnet_dependency",
}

_DESIGNATED_HASH_KEYS = {
    "NekoProxyCore.exe": "neko_proxy_core_exe_hash",
    "NekoProxyCore.dll": "neko_proxy_core_dll_hash",
    "runtime-settings.nkps": "protected_settings_payload_hash",
    "bin/Redirector.bin": "redirector_bin_hash",
    "bin/nfapi.dll": "nfapi_dll_hash",
    "bin/v2ray-sn.exe": "v2ray_sn_exe_hash",
}


class CoreVerificationError(ValueError):
    """Raised when a Core bundle does not match its canonical manifest."""


@dataclass(frozen=True)
class CoreVerificationResult:
    valid: bool
    file_count: int = 0
    total_bytes: int = 0
    manifest_sha256: str = ""
    error: str | None = None


def verify_canonical_core_bundle(bundle_dir: Path) -> CoreVerificationResult:
    """Verify that bundle_dir contains a valid canonical-core-manifest.json matching all on-disk files."""
    if not bundle_dir.is_dir():
        return CoreVerificationResult(valid=False, error=f"Bundle directory does not exist: {bundle_dir}")

    manifest_path = bundle_dir / "canonical-core-manifest.json"
    if not manifest_path.is_file():
        return CoreVerificationResult(valid=False, error="canonical-core-manifest.json missing from bundle")

    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except Exception as err:
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error=f"Invalid manifest JSON: {err}")

    if not isinstance(manifest, dict) or set(manifest.keys()) != _REQUIRED_TOP_KEYS:
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Invalid manifest top-level fields")

    sec = manifest["security"]
    if not isinstance(sec, dict) or set(sec.keys()) != _REQUIRED_SECURITY_KEYS:
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Invalid manifest security fields")

    if (
        sec["runtime_settings_key_files"] != 0
        or sec["plaintext_settings_files"] != 0
        or sec["plaintext_secret_marker_hits"] != 0
        or sec["external_dotnet_dependency"] is not False
    ):
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Security assertions violation in manifest")

    files_map = manifest["files"]
    if not isinstance(files_map, dict):
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Manifest files field must be a dictionary")

    if len(files_map) != manifest["file_count"]:
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="file_count does not match files map count")

    # Reject forbidden filenames
    for rel_path in files_map:
        leaf = Path(rel_path).name.lower()
        if leaf in ("runtime-settings.key", "settings.json"):
            return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error=f"Forbidden file in manifest: {rel_path}")

    # Enumerate all files on disk
    disk_files: dict[str, str] = {}
    actual_total_bytes = 0

    for file_path in bundle_dir.rglob("*"):
        if file_path.is_file():
            rel_name = file_path.relative_to(bundle_dir).as_posix()
            if rel_name == "canonical-core-manifest.json":
                continue

            if rel_name not in files_map:
                return CoreVerificationResult(
                    valid=False,
                    manifest_sha256=manifest_sha256,
                    error=f"Unlisted file found on disk: {rel_name}",
                )

            data = file_path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            expected_sha = files_map[rel_name]

            if sha != expected_sha:
                return CoreVerificationResult(
                    valid=False,
                    manifest_sha256=manifest_sha256,
                    error=f"Hash mismatch on {rel_name}: expected {expected_sha}, got {sha}",
                )

            disk_files[rel_name] = sha
            actual_total_bytes += len(data)

    if set(disk_files.keys()) != set(files_map.keys()):
        missing = set(files_map.keys()) - set(disk_files.keys())
        return CoreVerificationResult(
            valid=False,
            manifest_sha256=manifest_sha256,
            error=f"Missing files from disk: {next(iter(missing))}",
        )

    if actual_total_bytes != manifest["total_bytes"]:
        return CoreVerificationResult(
            valid=False,
            manifest_sha256=manifest_sha256,
            error=f"total_bytes mismatch: expected {manifest['total_bytes']}, got {actual_total_bytes}",
        )

    # Validate designated executable hashes
    for rel_key, manifest_key in _DESIGNATED_HASH_KEYS.items():
        if rel_key in files_map:
            if files_map[rel_key] != manifest[manifest_key]:
                return CoreVerificationResult(
                    valid=False,
                    manifest_sha256=manifest_sha256,
                    error=f"Designated hash mismatch for {rel_key}",
                )

    return CoreVerificationResult(
        valid=True,
        file_count=len(files_map),
        total_bytes=actual_total_bytes,
        manifest_sha256=manifest_sha256,
        error=None,
    )
