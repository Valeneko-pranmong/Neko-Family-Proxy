from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS

EXPECTED_PRODUCTION_KEY_ID = "neko-update-prod-1"
STABLE_RELEASE_EXPECTED_CHANNEL = "stable"
STABLE_RELEASE_EXPECTED_MIN_SEQUENCE = 1
STABLE_RELEASE_EXPECTED_PROTOCOL_MIN = 1
STABLE_RELEASE_EXPECTED_PROTOCOL_MAX = 1

REQUIRED_UPDATE_ASSETS = (
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
    "release-v2.json",
)

_MAX_RELEASE_JSON_BYTES = 262_144
_MAX_MANIFEST_BYTES = 65_536


class GitHubReleaseAssetsVerificationError(ValueError):
    """Raised when release assets or envelope verification fails."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GitHubReleaseAssetsVerificationError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _load_public_key(path: Path) -> bytes:
    if not path.is_file():
        raise GitHubReleaseAssetsVerificationError(f"Public key file not found: {path}")
    data = path.read_bytes()
    try:
        if len(data) == 32:
            Ed25519PublicKey.from_public_bytes(data)
            return data
        key = serialization.load_pem_public_key(data)
    except (TypeError, ValueError) as error:
        raise GitHubReleaseAssetsVerificationError("Public key format invalid") from error
    if not isinstance(key, Ed25519PublicKey):
        raise GitHubReleaseAssetsVerificationError("Public key is not an Ed25519 key")
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _file_digest_and_size(path: Path) -> tuple[str, int]:
    if not path.is_file():
        raise GitHubReleaseAssetsVerificationError(f"Required local file missing: {path.name}")
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest().lower(), size


def verify_github_release_assets(
    *,
    release_json_path: Path | str,
    download_dir: Path | str,
    public_key_file: Path | str | None = None,
    expected_tag: str,
    expected_target: str,
    require_draft: bool = False,
    require_prerelease: bool = False,
    expected_key_id: str = EXPECTED_PRODUCTION_KEY_ID,
    enforce_first_release: bool = True,
    trusted_public_keys: Mapping[str, bytes] | None = None,
) -> None:
    release_path = Path(release_json_path)
    if not release_path.is_file():
        raise GitHubReleaseAssetsVerificationError("Release JSON file not found")
    if release_path.stat().st_size > _MAX_RELEASE_JSON_BYTES:
        raise GitHubReleaseAssetsVerificationError("Release JSON file exceeds maximum permitted size")

    try:
        content = release_path.read_text(encoding="utf-8")
        release_doc = json.loads(content, object_pairs_hook=_reject_duplicate_keys)
    except Exception as err:
        raise GitHubReleaseAssetsVerificationError("Failed to parse release JSON") from err

    if not isinstance(release_doc, dict):
        raise GitHubReleaseAssetsVerificationError("Release JSON root must be an object")

    tag_name = release_doc.get("tag_name")
    if tag_name != expected_tag:
        raise GitHubReleaseAssetsVerificationError(
            f"Release tag mismatch: expected {expected_tag!r}, got {tag_name!r}"
        )

    target = release_doc.get("target_commitish")
    if not isinstance(target, str) or target.strip().lower() != expected_target.strip().lower():
        raise GitHubReleaseAssetsVerificationError("Release target commit mismatch")

    draft = release_doc.get("draft")
    if type(draft) is not bool:
        raise GitHubReleaseAssetsVerificationError("Release draft flag must be a boolean")
    if require_draft and not draft:
        raise GitHubReleaseAssetsVerificationError("Release draft flag must be true when require-draft is set")
    if require_prerelease and draft:
        raise GitHubReleaseAssetsVerificationError("Release draft flag must be false when require-prerelease is set")

    prerelease = release_doc.get("prerelease")
    if type(prerelease) is not bool:
        raise GitHubReleaseAssetsVerificationError("Release prerelease flag must be a boolean")
    if require_prerelease and not prerelease:
        raise GitHubReleaseAssetsVerificationError("Release prerelease flag must be true when require-prerelease is set")
    if not require_prerelease and prerelease:
        raise GitHubReleaseAssetsVerificationError("Release prerelease flag must be false")

    raw_assets = release_doc.get("assets")
    if not isinstance(raw_assets, list):
        raise GitHubReleaseAssetsVerificationError("Release assets must be a list")

    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    assets_by_name: dict[str, dict[str, Any]] = {}

    for asset in raw_assets:
        if not isinstance(asset, dict):
            raise GitHubReleaseAssetsVerificationError("Asset entry must be an object")
        asset_id = asset.get("id")
        asset_name = asset.get("name")
        asset_size = asset.get("size")

        if type(asset_id) is not int or asset_id <= 0:
            raise GitHubReleaseAssetsVerificationError("Asset id must be a positive integer")
        if asset_id in seen_ids:
            raise GitHubReleaseAssetsVerificationError(f"Duplicate asset id: {asset_id}")
        seen_ids.add(asset_id)

        if not isinstance(asset_name, str) or not asset_name:
            raise GitHubReleaseAssetsVerificationError("Asset name must be a non-empty string")
        if asset_name in seen_names:
            raise GitHubReleaseAssetsVerificationError(f"Duplicate asset name: {asset_name!r}")
        seen_names.add(asset_name)

        if type(asset_size) is not int or isinstance(asset_size, bool) or asset_size <= 0:
            raise GitHubReleaseAssetsVerificationError(f"Asset size must be a positive integer for {asset_name!r}")

        assets_by_name[asset_name] = asset

    for required_name in REQUIRED_UPDATE_ASSETS:
        if required_name not in assets_by_name:
            raise GitHubReleaseAssetsVerificationError(f"Missing required release asset: {required_name!r}")

    dir_path = Path(download_dir)
    if not dir_path.is_dir():
        raise GitHubReleaseAssetsVerificationError(f"Download directory does not exist: {dir_path}")

    manifest_path = dir_path / "release-v2.json"
    if not manifest_path.is_file():
        raise GitHubReleaseAssetsVerificationError("Local release-v2.json missing")
    manifest_stat_size = manifest_path.stat().st_size
    if manifest_stat_size > _MAX_MANIFEST_BYTES:
        raise GitHubReleaseAssetsVerificationError(f"release-v2.json exceeds maximum size ({_MAX_MANIFEST_BYTES} bytes)")
    if manifest_stat_size != assets_by_name["release-v2.json"]["size"]:
        raise GitHubReleaseAssetsVerificationError("release-v2.json file size does not match release asset metadata")

    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest_doc = json.loads(
            manifest_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except Exception as err:
        raise GitHubReleaseAssetsVerificationError("Failed to parse release-v2.json") from err

    if not isinstance(manifest_doc, dict):
        raise GitHubReleaseAssetsVerificationError("release-v2.json must be an object")

    try:
        canonical_manifest_bytes = canonical_json_dumps(manifest_doc)
        if canonical_manifest_bytes != manifest_bytes:
            raise GitHubReleaseAssetsVerificationError("release-v2.json is not formatted in canonical JSON")
    except GitHubReleaseAssetsVerificationError:
        raise
    except Exception as err:
        raise GitHubReleaseAssetsVerificationError("Error checking canonical JSON for release-v2.json") from err

    key_id = manifest_doc.get("key_id")
    if not isinstance(key_id, str):
        raise GitHubReleaseAssetsVerificationError("release-v2.json key_id must be a string")
    if key_id != expected_key_id:
        raise GitHubReleaseAssetsVerificationError("Manifest key_id mismatch")

    if trusted_public_keys is not None:
        try:
            public_key_bytes = trusted_public_keys[expected_key_id]
        except KeyError as err:
            raise GitHubReleaseAssetsVerificationError("Expected trusted public key not found") from err
    else:
        if expected_key_id != EXPECTED_PRODUCTION_KEY_ID:
            raise GitHubReleaseAssetsVerificationError("Production key_id mismatch")
        registry_key_bytes = PRODUCTION_RELEASE_PUBLIC_KEYS[EXPECTED_PRODUCTION_KEY_ID]
        public_key_bytes = (
            registry_key_bytes
            if public_key_file is None
            else _load_public_key(Path(public_key_file))
        )
        if public_key_file is not None and public_key_bytes != registry_key_bytes:
            raise GitHubReleaseAssetsVerificationError(
                "Public key file does not match in-repo production key registry"
            )

    try:
        release_set_v2, _payload_sha256 = verify_release_envelope_v2(
            manifest_doc,
            {expected_key_id: public_key_bytes},
        )
    except Exception as err:
        raise GitHubReleaseAssetsVerificationError("Envelope cryptographic verification failed") from err

    if enforce_first_release:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from scripts.derive_version import get_release_sequence, get_release_id
        finally:
            sys.path.pop(0)

        expected_sequence = get_release_sequence(expected_tag)
        expected_release_id = get_release_id(expected_sequence)
        expected_component_version = expected_tag.lstrip("v")

        invariant_checks = (
            (release_set_v2.channel == STABLE_RELEASE_EXPECTED_CHANNEL, "channel"),
            (release_set_v2.release_sequence == expected_sequence, "release_sequence"),
            (
                release_set_v2.minimum_supported_sequence == STABLE_RELEASE_EXPECTED_MIN_SEQUENCE,
                "minimum_supported_sequence",
            ),
            (release_set_v2.release_id == expected_release_id, "release_id"),
            (
                release_set_v2.updater_protocol.minimum == STABLE_RELEASE_EXPECTED_PROTOCOL_MIN
                and release_set_v2.updater_protocol.maximum == STABLE_RELEASE_EXPECTED_PROTOCOL_MAX,
                "updater_protocol",
            ),
        )
        for valid, name in invariant_checks:
            if not valid:
                raise GitHubReleaseAssetsVerificationError(
                    f"Stable-release {name} invariant mismatch"
                )
        for component_name in ("launcher", "updater", "core"):
            component = release_set_v2.components.get(component_name)
            if component is None or component.version != expected_component_version:
                raise GitHubReleaseAssetsVerificationError(
                    f"Stable-release {component_name} version invariant mismatch"
                )
    elif release_set_v2.channel != "stable":
        raise GitHubReleaseAssetsVerificationError(
            f"Release channel must be 'stable', got {release_set_v2.channel!r}"
        )

    expected_manifest_tag = f"v{release_set_v2.components['launcher'].version}"
    if expected_tag != expected_manifest_tag:
        raise GitHubReleaseAssetsVerificationError(
            f"Expected tag {expected_tag!r} does not match launcher version {expected_manifest_tag!r}"
        )

    components_map = {
        "launcher": ("NekoLauncher.exe", "raw-pe-v1"),
        "updater": ("NekoUpdater.exe", "raw-pe-v1"),
        "core": ("NekoProxyCore.zip", "zip-core-v1"),
    }

    for comp_name, (expected_file_name, expected_format) in components_map.items():
        comp = release_set_v2.components.get(comp_name)
        if comp is None:
            raise GitHubReleaseAssetsVerificationError(f"Manifest missing required component: {comp_name!r}")
        if comp.artifact_id != expected_file_name:
            raise GitHubReleaseAssetsVerificationError(
                f"Component {comp_name!r} artifact_id mismatch: {comp.artifact_id!r} != {expected_file_name!r}"
            )
        if comp.artifact_format != expected_format:
            raise GitHubReleaseAssetsVerificationError(
                f"Component {comp_name!r} artifact_format mismatch: {comp.artifact_format!r} != {expected_format!r}"
            )

        local_file_path = dir_path / expected_file_name
        actual_sha256, actual_size = _file_digest_and_size(local_file_path)

        if actual_size != comp.artifact_size:
            raise GitHubReleaseAssetsVerificationError(
                f"Component {comp_name!r} file size mismatch: local {actual_size} != manifest {comp.artifact_size}"
            )
        asset_meta = assets_by_name[expected_file_name]
        if actual_size != asset_meta["size"]:
            raise GitHubReleaseAssetsVerificationError(
                f"Component {comp_name!r} file size mismatch: local {actual_size} != release asset {asset_meta['size']}"
            )

        if actual_sha256.lower() != comp.artifact_sha256.lower():
            raise GitHubReleaseAssetsVerificationError(
                f"Component {comp_name!r} sha256 mismatch against signed manifest"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify downloaded GitHub Release assets against signed release-v2 envelope.",
        allow_abbrev=False,
    )
    parser.add_argument("--release-json", required=True, type=Path)
    parser.add_argument("--download-dir", required=True, type=Path)
    parser.add_argument("--public-key-file", type=Path)
    parser.add_argument("--expected-tag", required=True)
    parser.add_argument("--expected-target", required=True)
    parser.add_argument("--require-draft", action="store_true", default=False)
    parser.add_argument("--require-prerelease", action="store_true", default=False)
    parser.add_argument("--no-enforce-first-release", action="store_true", default=False)

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        verify_github_release_assets(
            release_json_path=args.release_json,
            download_dir=args.download_dir,
            public_key_file=args.public_key_file,
            expected_tag=args.expected_tag,
            expected_target=args.expected_target,
            require_draft=args.require_draft,
            require_prerelease=args.require_prerelease,
            enforce_first_release=not args.no_enforce_first_release,
        )
    except GitHubReleaseAssetsVerificationError as err:
        safe_message = re.sub(r"https?://\S+", "<sanitized-url>", str(err))
        print(f"github release assets verification failed: {safe_message}", file=sys.stderr)
        return 1
    except Exception:
        print("github release assets verification failed: unexpected error", file=sys.stderr)
        return 1

    print("github release assets verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
