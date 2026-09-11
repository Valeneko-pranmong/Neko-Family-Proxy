"""Strict streaming ZIP extractor enforcing size, ratio, path, and security limits."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import zipfile

MAX_REGULAR_FILES = 8193
MAX_TOTAL_EXPANDED_BYTES = 1024 * 1024 * 1024 + 8 * 1024 * 1024  # 1 GiB + 8 MiB manifest
MAX_SINGLE_FILE_BYTES = 256 * 1024 * 1024                        # 256 MiB
MAX_EXPANSION_RATIO = 200                                        # 200:1
CHUNK_SIZE = 64 * 1024

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._ ()'-]+$")
_RESERVED_WIN32_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CLOCK$",
    "CONIN$",
    "CONOUT$",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class ZipSecurityError(ValueError):
    """Raised when a zip archive violates security or format policies."""


@dataclass(frozen=True)
class CoreExtractionSummary:
    file_count: int
    total_bytes: int


def _validate_path_segment(seg: str) -> None:
    if not seg or seg in (".", ".."):
        raise ZipSecurityError(f"Path traversal rejected: invalid segment {seg!r}")
    if len(seg) > 120:
        raise ZipSecurityError(f"Segment exceeds 120 characters: {seg!r}")
    if seg.strip(" .") != seg:
        raise ZipSecurityError(f"Segment has leading or trailing whitespace/dots: {seg!r}")
    if not _SEGMENT_RE.fullmatch(seg):
        raise ZipSecurityError(f"Disallowed character in segment: {seg!r}")

    # Check Win32 reserved device names
    base_name = seg.split(".")[0].upper()
    if base_name in _RESERVED_WIN32_NAMES:
        raise ZipSecurityError(f"Reserved Win32 device name: {seg!r}")


def _validate_entry_path(filename: str) -> list[str]:
    if "\\" in filename:
        raise ZipSecurityError(f"Backslash disallowed in ZIP entry path: {filename!r}")
    if filename.startswith("/"):
        raise ZipSecurityError(f"Path traversal rejected: absolute path {filename!r}")
    if ":" in filename:
        raise ZipSecurityError(f"Disallowed character ':' in path: {filename!r}")

    clean = filename.replace("\\", "/")
    segments = clean.split("/")
    if segments[-1] == "":
        segments.pop()  # trailing slash for directory

    if not segments or len(segments) > 16:
        raise ZipSecurityError(f"Too many path segments ({len(segments)}) in {filename!r}")
    if len(clean) > 240:
        raise ZipSecurityError(f"Path exceeds 240 characters: {filename!r}")

    for seg in segments:
        _validate_path_segment(seg)

    return segments


def extract_core_bundle(zip_path: Path, destination_dir: Path) -> CoreExtractionSummary:
    """Extract a Core bundle zip archive into destination_dir, enforcing all Section 6 constraints."""
    if not zip_path.is_file():
        raise FileNotFoundError(f"Zip archive not found: {zip_path}")

    destination_dir.mkdir(parents=True, exist_ok=True)
    seen_paths_lower: set[str] = set()
    total_extracted_bytes = 0
    regular_file_count = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        infolist = zf.infolist()
        if len(infolist) > MAX_REGULAR_FILES + 128:  # bounded entries
            raise ZipSecurityError("Archive exceeds maximum entry count")

        for info in infolist:
            # Check compression method: STORED (0) or DEFLATED (8)
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ZipSecurityError(f"Unsupported compression method: {info.compress_type}")

            # Check encryption
            if info.flag_bits & 0x1:
                raise ZipSecurityError("Encrypted zip entries are rejected")

            segments = _validate_entry_path(info.filename)
            norm_path_str = "/".join(segments)
            path_lower = norm_path_str.lower()
            if path_lower in seen_paths_lower:
                raise ZipSecurityError(f"Duplicate or case-colliding path: {norm_path_str}")
            seen_paths_lower.add(path_lower)

            is_dir = info.is_dir() or info.filename.endswith("/")
            target_path = destination_dir.joinpath(*segments)

            if is_dir:
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            # Regular file entry
            regular_file_count += 1
            if regular_file_count > MAX_REGULAR_FILES:
                raise ZipSecurityError(f"Archive exceeds maximum regular file count of {MAX_REGULAR_FILES}")

            target_path.parent.mkdir(parents=True, exist_ok=True)

            file_bytes = 0
            with zf.open(info, "r") as src, open(target_path, "wb") as dst:
                while True:
                    chunk = src.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    dst.write(chunk)
                    chunk_len = len(chunk)
                    file_bytes += chunk_len
                    total_extracted_bytes += chunk_len

                    if file_bytes > MAX_SINGLE_FILE_BYTES:
                        raise ZipSecurityError(f"File {info.filename} exceeds {MAX_SINGLE_FILE_BYTES} bytes")
                    if total_extracted_bytes > MAX_TOTAL_EXPANDED_BYTES:
                        raise ZipSecurityError("Archive exceeds maximum total expansion size")

                    if info.compress_size > 0:
                        ratio = file_bytes / info.compress_size
                        if ratio > MAX_EXPANSION_RATIO:
                            raise ZipSecurityError(
                                f"File {info.filename} exceeds expansion ratio limit ({ratio:.1f} > {MAX_EXPANSION_RATIO})"
                            )

    return CoreExtractionSummary(
        file_count=regular_file_count,
        total_bytes=total_extracted_bytes,
    )
