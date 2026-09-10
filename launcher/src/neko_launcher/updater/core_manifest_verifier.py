"""Canonical Core manifest and on-disk bundle verifier."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

CORE_MANIFEST_FILENAME = "core-manifest.json"

_REQUIRED_TOP_KEYS = {
    "rid",
    "executable",
    "source_commit",
    "files",
}

_MANDATORY_CORE_FILES = {
    "NekoProxyCore.exe",
    "NekoProxyCore.dll",
    "runtime-settings.nkps",
    "bin/Redirector.bin",
    "bin/nfapi.dll",
    "bin/v2ray-sn.exe",
}

_FORBIDDEN_LEAF_NAMES = {
    "runtime-settings.key",
    "settings.json",
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
    """Verify that bundle_dir contains a valid core-manifest.json matching all on-disk files."""
    if not bundle_dir.is_dir():
        return CoreVerificationResult(valid=False, error=f"Bundle directory does not exist: {bundle_dir}")

    manifest_path = bundle_dir / CORE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return CoreVerificationResult(valid=False, error=f"{CORE_MANIFEST_FILENAME} missing from bundle")

    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except Exception as err:
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error=f"Invalid manifest JSON: {err}")

    if not isinstance(manifest, dict):
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Manifest must be a JSON object")

    if not _REQUIRED_TOP_KEYS.issubset(manifest.keys()):
        missing_keys = sorted(_REQUIRED_TOP_KEYS - set(manifest.keys()))
        return CoreVerificationResult(
            valid=False,
            manifest_sha256=manifest_sha256,
            error=f"Missing required manifest fields: {', '.join(missing_keys)}",
        )

    # Validate rid
    rid = manifest["rid"]
    if not isinstance(rid, str) or not rid.strip():
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Invalid manifest rid")
    if rid != "win-x64":
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error=f"Unsupported RID: {rid}")

    # Validate executable
    executable = manifest["executable"]
    if not isinstance(executable, str) or not executable.strip():
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Invalid manifest executable")
    if executable != "NekoProxyCore.exe":
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error=f"Unsupported executable: {executable}")

    # Validate source_commit
    source_commit = manifest["source_commit"]
    if not isinstance(source_commit, str) or not source_commit.strip():
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Invalid manifest source_commit")

    # Validate files array
    files_list = manifest["files"]
    if not isinstance(files_list, list):
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Manifest files field must be a list")

    if len(files_list) == 0:
        return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Manifest declares zero files")

    files_map: dict[str, dict[str, Any]] = {}
    for item in files_list:
        if not isinstance(item, dict):
            return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Manifest files entry must be an object")
        if not {"path", "size", "sha256"}.issubset(item.keys()):
            return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Manifest files entry missing required fields")

        rel_path = item["path"]
        if not isinstance(rel_path, str) or not rel_path.strip():
            return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error="Invalid file path in manifest")
        norm_path = rel_path.replace("\\", "/")
        if norm_path.startswith("/") or ".." in norm_path.split("/"):
            return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error=f"Path traversal or absolute path in manifest: {rel_path}")
        if norm_path in files_map:
            return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error=f"Duplicate file path in manifest: {rel_path}")

        leaf = Path(norm_path).name.lower()
        if leaf in _FORBIDDEN_LEAF_NAMES:
            return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error=f"Forbidden file in manifest: {rel_path}")

        size_val = item["size"]
        if not isinstance(size_val, int) or size_val < 0:
            return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error=f"Invalid file size in manifest for {rel_path}: {size_val}")

        sha_val = item["sha256"]
        if not isinstance(sha_val, str) or len(sha_val) != 64 or not all(c in "0123456789abcdefABCDEF" for c in sha_val):
            return CoreVerificationResult(valid=False, manifest_sha256=manifest_sha256, error=f"Invalid SHA256 in manifest for {rel_path}: {sha_val}")

        files_map[norm_path] = {"size": size_val, "sha256": sha_val.lower()}

    # Check mandatory files
    for mandatory_file in _MANDATORY_CORE_FILES:
        if mandatory_file not in files_map:
            return CoreVerificationResult(
                valid=False,
                manifest_sha256=manifest_sha256,
                error=f"Missing mandatory Core file in manifest: {mandatory_file}",
            )

    if executable not in files_map:
        return CoreVerificationResult(
            valid=False,
            manifest_sha256=manifest_sha256,
            error=f"Manifest executable '{executable}' missing from files map",
        )

    # Enumerate all files on disk
    disk_files: set[str] = set()
    actual_total_bytes = 0

    for file_path in bundle_dir.rglob("*"):
        if file_path.is_file():
            rel_name = file_path.relative_to(bundle_dir).as_posix()
            if rel_name in (CORE_MANIFEST_FILENAME, "canonical-core-manifest.json"):
                continue

            if rel_name not in files_map:
                return CoreVerificationResult(
                    valid=False,
                    manifest_sha256=manifest_sha256,
                    error=f"Unlisted file found on disk: {rel_name}",
                )

            data = file_path.read_bytes()
            expected_size = files_map[rel_name]["size"]
            if len(data) != expected_size:
                return CoreVerificationResult(
                    valid=False,
                    manifest_sha256=manifest_sha256,
                    error=f"Size mismatch on {rel_name}: expected {expected_size}, got {len(data)}",
                )

            sha = hashlib.sha256(data).hexdigest()
            expected_sha = files_map[rel_name]["sha256"]
            if sha != expected_sha:
                return CoreVerificationResult(
                    valid=False,
                    manifest_sha256=manifest_sha256,
                    error=f"Hash mismatch on {rel_name}: expected {expected_sha}, got {sha}",
                )

            disk_files.add(rel_name)
            actual_total_bytes += len(data)

    if disk_files != set(files_map.keys()):
        missing = set(files_map.keys()) - disk_files
        return CoreVerificationResult(
            valid=False,
            manifest_sha256=manifest_sha256,
            error=f"Missing files from disk: {next(iter(missing))}",
        )

    return CoreVerificationResult(
        valid=True,
        file_count=len(files_map),
        total_bytes=actual_total_bytes,
        manifest_sha256=manifest_sha256,
        error=None,
    )
