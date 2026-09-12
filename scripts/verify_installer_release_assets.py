from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence

REQUIRED_INSTALLER_ASSET = "NekoFamilyProxy-Installer.exe"
REQUIRED_INSTALLER_ASSETS = (REQUIRED_INSTALLER_ASSET,)
CANONICAL_MACHINE_REPO = "Valeneko-pranmong/Neko-Family-Proxy"
DEFAULT_INSTALLER_REPO = "Valeneko-pranmong/Neko-Family-Proxy-Installer"

_MAX_RELEASE_JSON_BYTES = 262_144


class InstallerReleaseVerificationError(ValueError):
    """Raised when installer release assets or metadata verification fails."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InstallerReleaseVerificationError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _file_digest_and_size(path: Path) -> tuple[str, int]:
    if not path.is_file():
        raise InstallerReleaseVerificationError(f"Installer file missing: {path.name}")
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest().lower(), size


def _contains_machine_repo(text: str) -> bool:
    pattern = re.compile(
        r"(?:repos/|github\.com/|^)" + re.escape(CANONICAL_MACHINE_REPO) + r"(?:/|\?|#|$)",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def verify_installer_release_assets(
    *,
    release_json_path: Path | str,
    installer_path: Path | str,
    expected_tag: str,
    expected_target: str,
    require_draft: bool = False,
    require_prerelease: bool = False,
    expected_repo: str | None = None,
) -> tuple[str, int]:
    """
    Verify downloaded installer release asset against GitHub release metadata.
    Enforces that human installer release has exactly one custom asset:
    'NekoFamilyProxy-Installer.exe' and is repository-bound to an explicit installer repo.
    """
    if expected_repo is not None:
        if _contains_machine_repo(expected_repo):
            raise InstallerReleaseVerificationError(
                f"Installer repository cannot be the canonical machine repository ({CANONICAL_MACHINE_REPO})"
            )

    release_path = Path(release_json_path)
    if not release_path.is_file():
        raise InstallerReleaseVerificationError("Release JSON file not found")
    if release_path.stat().st_size > _MAX_RELEASE_JSON_BYTES:
        raise InstallerReleaseVerificationError("Release JSON file exceeds maximum permitted size")

    try:
        content = release_path.read_text(encoding="utf-8")
        release_doc = json.loads(content, object_pairs_hook=_reject_duplicate_keys)
    except Exception as err:
        raise InstallerReleaseVerificationError("Failed to parse release JSON") from err

    if not isinstance(release_doc, dict):
        raise InstallerReleaseVerificationError("Release JSON root must be an object")

    # Guard against accidental machine repository in release metadata
    for url_field in ("url", "html_url"):
        url_val = release_doc.get(url_field)
        if isinstance(url_val, str) and _contains_machine_repo(url_val):
            raise InstallerReleaseVerificationError(
                f"Release metadata points to canonical machine repository ({CANONICAL_MACHINE_REPO})"
            )

    tag_name = release_doc.get("tag_name")
    if tag_name != expected_tag:
        raise InstallerReleaseVerificationError(
            f"Release tag mismatch: expected {expected_tag!r}, got {tag_name!r}"
        )

    target = release_doc.get("target_commitish")
    if not isinstance(target, str) or target.strip().lower() != expected_target.strip().lower():
        raise InstallerReleaseVerificationError("Release target commit mismatch")

    draft = release_doc.get("draft")
    if type(draft) is not bool:
        raise InstallerReleaseVerificationError("Release draft flag must be a boolean")
    if require_draft and not draft:
        raise InstallerReleaseVerificationError("Release draft flag must be true when require-draft is set")
    if require_prerelease and draft:
        raise InstallerReleaseVerificationError("Release draft flag must be false when require-prerelease is set")

    prerelease = release_doc.get("prerelease")
    if type(prerelease) is not bool:
        raise InstallerReleaseVerificationError("Release prerelease flag must be a boolean")
    if require_prerelease and not prerelease:
        raise InstallerReleaseVerificationError("Release prerelease flag must be true when require-prerelease is set")
    if not require_prerelease and prerelease:
        raise InstallerReleaseVerificationError("Release prerelease flag must be false")

    raw_assets = release_doc.get("assets")
    if not isinstance(raw_assets, list):
        raise InstallerReleaseVerificationError("Release assets must be a list")

    if len(raw_assets) != 1:
        raise InstallerReleaseVerificationError(
            f"Installer release must contain exactly one custom asset: {REQUIRED_INSTALLER_ASSET!r} "
            f"(found {len(raw_assets)} assets)"
        )

    asset = raw_assets[0]
    if not isinstance(asset, dict):
        raise InstallerReleaseVerificationError("Asset entry must be an object")

    asset_name = asset.get("name")
    if asset_name != REQUIRED_INSTALLER_ASSET:
        raise InstallerReleaseVerificationError(
            f"Asset name mismatch: expected {REQUIRED_INSTALLER_ASSET!r}, got {asset_name!r}"
        )

    asset_id = asset.get("id")
    if type(asset_id) is not int or asset_id <= 0:
        raise InstallerReleaseVerificationError("Asset id must be a positive integer")

    asset_size = asset.get("size")
    if type(asset_size) is not int or isinstance(asset_size, bool) or asset_size <= 0:
        raise InstallerReleaseVerificationError("Asset size must be a positive integer")

    download_url = asset.get("browser_download_url")
    if isinstance(download_url, str) and _contains_machine_repo(download_url):
        raise InstallerReleaseVerificationError(
            f"Asset download URL points to canonical machine repository ({CANONICAL_MACHINE_REPO})"
        )

    local_path = Path(installer_path)
    if not local_path.is_file():
        raise InstallerReleaseVerificationError(f"Installer file missing: {local_path.name}")

    actual_sha256, actual_size = _file_digest_and_size(local_path)
    if actual_size <= 0:
        raise InstallerReleaseVerificationError("Installer file is empty")
    if actual_size != asset_size:
        raise InstallerReleaseVerificationError(
            f"Installer file size mismatch: local {actual_size} != release asset {asset_size}"
        )

    return actual_sha256, actual_size


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify downloaded GitHub Release installer asset.",
        allow_abbrev=False,
    )
    parser.add_argument("--release-json", required=True, type=Path)
    parser.add_argument("--installer-path", required=True, type=Path)
    parser.add_argument("--expected-tag", required=True)
    parser.add_argument("--expected-target", required=True)
    parser.add_argument("--require-draft", action="store_true", default=False)
    parser.add_argument("--require-prerelease", action="store_true", default=False)
    parser.add_argument("--expected-repo", default=DEFAULT_INSTALLER_REPO)

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        sha256, size = verify_installer_release_assets(
            release_json_path=args.release_json,
            installer_path=args.installer_path,
            expected_tag=args.expected_tag,
            expected_target=args.expected_target,
            require_draft=args.require_draft,
            require_prerelease=args.require_prerelease,
            expected_repo=args.expected_repo,
        )
    except InstallerReleaseVerificationError as err:
        safe_message = re.sub(r"https?://\S+", "<sanitized-url>", str(err))
        print(f"installer release assets verification failed: {safe_message}", file=sys.stderr)
        return 1
    except Exception:
        print("installer release assets verification failed: unexpected error", file=sys.stderr)
        return 1

    print(f"installer release assets verification passed (sha256: {sha256}, size: {size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
