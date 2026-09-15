from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence

REQUIRED_HUMAN_ASSET = "NekoFamilyProxy-Installer.exe"
REQUIRED_HUMAN_ASSETS = (REQUIRED_HUMAN_ASSET,)
CANONICAL_HUMAN_REPO = "Valeneko-pranmong/Neko-Family-Proxy"
DEFAULT_HUMAN_REPO = CANONICAL_HUMAN_REPO
DEFAULT_INSTALLER_REPO = CANONICAL_HUMAN_REPO  # For backward-compat
REQUIRED_INSTALLER_ASSET = REQUIRED_HUMAN_ASSET
REQUIRED_INSTALLER_ASSETS = REQUIRED_HUMAN_ASSETS
_RETIRED_INSTALLER_REPO = "/".join(
    ["Valeneko-pranmong", "-".join(["Neko", "Family", "Proxy", "Installer"])]
)

FORBIDDEN_HUMAN_ASSETS = (
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
    "release-v2.json",
)

_MAX_RELEASE_JSON_BYTES = 262_144


class HumanReleaseVerificationError(ValueError):
    """Raised when human release assets, metadata, or presentation body verification fails."""


InstallerReleaseVerificationError = HumanReleaseVerificationError


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HumanReleaseVerificationError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _file_digest_and_size(path: Path) -> tuple[str, int]:
    if not path.is_file():
        raise HumanReleaseVerificationError(f"Installer file missing: {path.name}")
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest().lower(), size


def _contains_retired_repo(text: str) -> bool:
    pattern = re.compile(
        r"(?:repos/|github\.com/|^)" + re.escape(_RETIRED_INSTALLER_REPO) + r"(?:/|\?|#|$)",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def _contains_repo(text: str, repo: str) -> bool:
    pattern = re.compile(
        r"(?:repos/|github\.com/|^)" + re.escape(repo) + r"(?:/|\?|#|$)",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def validate_human_release_body(body: str, tag: str = "v5.1.2") -> None:
    """Validate that human release body satisfies the presentation and bilingual notice contract."""
    if not isinstance(body, str) or not body.strip():
        raise HumanReleaseVerificationError("Release body must be a non-empty string")

    # Title matching tag
    if tag not in body or "# Neko Family Proxy" not in body:
        raise HumanReleaseVerificationError(f"Release body missing title for tag {tag}")

    # Required section headers
    if "Highlights | จุดเด่น" not in body:
        raise HumanReleaseVerificationError("Release body missing 'Highlights | จุดเด่น' section")
    if "Downloads | ดาวน์โหลด" not in body:
        raise HumanReleaseVerificationError("Release body missing 'Downloads | ดาวน์โหลด' section")
    if "Notes | หมายเหตุ" not in body:
        raise HumanReleaseVerificationError("Release body missing 'Notes | หมายเหตุ' section")

    # Bilingual content (Thai and English)
    has_thai = bool(re.search(r"[\u0e00-\u0e7f]", body))
    has_english = bool(re.search(r"[a-zA-Z]", body))
    if not has_thai or not has_english:
        raise HumanReleaseVerificationError("Release body must be bilingual English/Thai")

    # Normal users download Installer ONLY
    if REQUIRED_HUMAN_ASSET not in body and "Installer" not in body:
        raise HumanReleaseVerificationError("Release body must specify Installer download")

    # Explicit 5.1.0 uninstall notice
    has_510_uninstall = bool(
        re.search(r"(?:uninstall|ถอนการติดตั้ง)\s+v?5\.1\.0", body, re.IGNORECASE)
    )
    if not has_510_uninstall:
        raise HumanReleaseVerificationError(
            "Release body must explicitly instruct v5.1.0 users to uninstall v5.1.0"
        )

    # Explicit 5.1.2 install notice
    has_512_install = bool(
        re.search(r"(?:install|ติดตั้ง)\s+v?5\.1\.2", body, re.IGNORECASE)
    )
    if not has_512_install:
        raise HumanReleaseVerificationError(
            "Release body must explicitly instruct users to install v5.1.2"
        )


def verify_human_release_assets(
    *,
    release_json_path: Path | str,
    installer_path: Path | str,
    expected_tag: str,
    expected_target: str,
    require_draft: bool = False,
    require_prerelease: bool = False,
    expected_repo: str = CANONICAL_HUMAN_REPO,
    expected_body: str | None = None,
    validate_body: bool = True,
) -> tuple[str, int]:
    """Verify downloaded human release asset against GitHub release metadata."""
    if _contains_retired_repo(expected_repo):
        raise HumanReleaseVerificationError(
            f"Release repository cannot be the retired installer repository ({_RETIRED_INSTALLER_REPO})"
        )

    release_path = Path(release_json_path)
    if not release_path.is_file():
        raise HumanReleaseVerificationError("Release JSON file not found")
    if release_path.stat().st_size > _MAX_RELEASE_JSON_BYTES:
        raise HumanReleaseVerificationError("Release JSON file exceeds maximum permitted size")

    try:
        content = release_path.read_text(encoding="utf-8")
        release_doc = json.loads(content, object_pairs_hook=_reject_duplicate_keys)
    except Exception as err:
        raise HumanReleaseVerificationError("Failed to parse release JSON") from err

    if not isinstance(release_doc, dict):
        raise HumanReleaseVerificationError("Release JSON root must be an object")

    # Guard against retired installer repository in metadata
    for url_field in ("url", "html_url"):
        url_val = release_doc.get(url_field)
        if isinstance(url_val, str):
            if _contains_retired_repo(url_val):
                raise HumanReleaseVerificationError(
                    f"Release metadata points to retired installer repository ({_RETIRED_INSTALLER_REPO})"
                )
            if not _contains_repo(url_val, expected_repo):
                raise HumanReleaseVerificationError(
                    f"Release metadata repository mismatch: expected {expected_repo}"
                )

    tag_name = release_doc.get("tag_name")
    if tag_name != expected_tag:
        raise HumanReleaseVerificationError(
            f"Release tag mismatch: expected {expected_tag!r}, got {tag_name!r}"
        )

    target = release_doc.get("target_commitish")
    if not isinstance(target, str) or target.strip().lower() != expected_target.strip().lower():
        raise HumanReleaseVerificationError("Release target commit mismatch")

    draft = release_doc.get("draft")
    if type(draft) is not bool:
        raise HumanReleaseVerificationError("Release draft flag must be a boolean")
    if require_draft and not draft:
        raise HumanReleaseVerificationError("Release draft flag must be true when require-draft is set")

    prerelease = release_doc.get("prerelease")
    if type(prerelease) is not bool:
        raise HumanReleaseVerificationError("Release prerelease flag must be a boolean")
    if require_prerelease and not prerelease:
        raise HumanReleaseVerificationError("Release prerelease flag must be true when require-prerelease is set")
    if not require_prerelease and prerelease:
        raise HumanReleaseVerificationError("Release prerelease flag must be false")

    raw_assets = release_doc.get("assets")
    if not isinstance(raw_assets, list):
        raise HumanReleaseVerificationError("Release assets must be a list")

    if len(raw_assets) != 1:
        raise HumanReleaseVerificationError(
            f"Human release must contain exactly one custom asset: {REQUIRED_HUMAN_ASSET!r} "
            f"(found {len(raw_assets)} assets)"
        )

    asset = raw_assets[0]
    if not isinstance(asset, dict):
        raise HumanReleaseVerificationError("Asset entry must be an object")

    asset_name = asset.get("name")
    if asset_name in FORBIDDEN_HUMAN_ASSETS:
        raise HumanReleaseVerificationError(
            f"Forbidden machine asset found in release: {asset_name!r}"
        )
    if asset_name != REQUIRED_HUMAN_ASSET:
        raise HumanReleaseVerificationError(
            f"Asset name mismatch: expected {REQUIRED_HUMAN_ASSET!r}, got {asset_name!r}"
        )

    asset_id = asset.get("id")
    if type(asset_id) is not int or asset_id <= 0:
        raise HumanReleaseVerificationError("Asset id must be a positive integer")

    asset_size = asset.get("size")
    if type(asset_size) is not int or isinstance(asset_size, bool) or asset_size <= 0:
        raise HumanReleaseVerificationError("Asset size must be a positive integer")

    download_url = asset.get("browser_download_url")
    if isinstance(download_url, str):
        if _contains_retired_repo(download_url):
            raise HumanReleaseVerificationError(
                f"Asset download URL points to retired installer repository ({_RETIRED_INSTALLER_REPO})"
            )
        if not _contains_repo(download_url, expected_repo):
            raise HumanReleaseVerificationError(
                f"Asset download URL repository mismatch: expected {expected_repo}"
            )

    local_path = Path(installer_path)
    if not local_path.is_file():
        raise HumanReleaseVerificationError(f"Installer file missing: {local_path.name}")

    actual_sha256, actual_size = _file_digest_and_size(local_path)
    if actual_size <= 0:
        raise HumanReleaseVerificationError("Installer file is empty")
    if actual_size != asset_size:
        raise HumanReleaseVerificationError(
            f"Installer file size mismatch: local {actual_size} != release asset {asset_size}"
        )

    # Validate body
    body_text = release_doc.get("body", "")
    if expected_body is not None:
        if body_text.strip() != expected_body.strip():
            raise HumanReleaseVerificationError("Release body does not match expected body")
    if validate_body:
        validate_human_release_body(body_text, expected_tag)

    return actual_sha256, actual_size


# Alias for backward-compat
verify_installer_release_assets = verify_human_release_assets


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify downloaded GitHub Release human installer asset.",
        allow_abbrev=False,
    )
    parser.add_argument("--release-json", required=True, type=Path)
    parser.add_argument("--installer-path", required=True, type=Path)
    parser.add_argument("--expected-tag", required=True)
    parser.add_argument("--expected-target", required=True)
    parser.add_argument("--require-draft", action="store_true", default=False)
    parser.add_argument("--require-prerelease", action="store_true", default=False)
    parser.add_argument("--expected-repo", default=CANONICAL_HUMAN_REPO)
    parser.add_argument("--expected-body-file", type=Path)
    parser.add_argument("--skip-body-validation", action="store_true", default=False)

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    expected_body = None
    if args.expected_body_file and args.expected_body_file.is_file():
        expected_body = args.expected_body_file.read_text(encoding="utf-8")

    try:
        verify_human_release_assets(
            release_json_path=args.release_json,
            installer_path=args.installer_path,
            expected_tag=args.expected_tag,
            expected_target=args.expected_target,
            require_draft=args.require_draft,
            require_prerelease=args.require_prerelease,
            expected_repo=args.expected_repo,
            expected_body=expected_body,
            validate_body=not args.skip_body_validation,
        )
    except HumanReleaseVerificationError as err:
        safe_message = re.sub(r"https?://\S+", "<sanitized-url>", str(err))
        print(f"human release assets verification failed: {safe_message}", file=sys.stderr)
        return 1
    except Exception as err:
        print(f"human release assets verification unexpected error: {err}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
