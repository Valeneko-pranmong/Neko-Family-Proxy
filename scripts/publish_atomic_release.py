from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Protocol, Sequence
from urllib.parse import quote


CANONICAL_REPO = "Valeneko-pranmong/Neko-Family-Proxy"
_REMOTE_TAG_MAX_DEPTH = 4
_SHA = re.compile(r"[0-9a-fA-F]{40}")


REQUIRED_STAGE_ASSETS: tuple[str, ...] = (
    "NekoFamilyProxy-Setup.exe",
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
    "release-v2.json",
)
_COMPONENTS = {
    "launcher": ("NekoLauncher.exe", "raw-pe-v1"),
    "updater": ("NekoUpdater.exe", "raw-pe-v1"),
    "core": ("NekoProxyCore.zip", "zip-core-v1"),
}


class StageDraftReleaseError(Exception):
    """Raised when staging validation or execution fails."""


@dataclass(frozen=True)
class StagedDraftEvidence:
    release_id: int
    tag_name: str
    target_commit: str
    assets: dict[str, int]
    dispatch_command: str


class CommandExecutor(Protocol):
    def run(
        self, args: list[str], *, capture_output: bool = True
    ) -> subprocess.CompletedProcess[str]: ...


class _SubprocessExecutor:
    def run(
        self, args: list[str], *, capture_output: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=capture_output, text=True, check=False)


def _run(executor: CommandExecutor, args: list[str]) -> str:
    result = executor.run(args, capture_output=True)
    if result.returncode != 0:
        raise StageDraftReleaseError(f"Command failed: {args[0]} {args[1] if len(args) > 1 else ''}")
    return result.stdout


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StageDraftReleaseError(f"Duplicate manifest key: {key}")
        result[key] = value
    return result


def _ensure_launcher_import_path() -> None:
    launcher_src = str(Path(__file__).resolve().parents[1] / "launcher" / "src")
    if launcher_src in sys.path:
        sys.path.remove(launcher_src)
    sys.path.insert(0, launcher_src)


def _verify_manifest_signature(document: dict[str, Any]) -> Any:
    _ensure_launcher_import_path()
    from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
    from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS

    try:
        release_set, _payload_sha256 = verify_release_envelope_v2(
            document, PRODUCTION_RELEASE_PUBLIC_KEYS
        )
        return release_set
    except Exception as error:
        raise StageDraftReleaseError("Manifest signature verification failed") from error


def _validate_manifest(manifest_path: Path, assets: dict[str, Path], tag: str) -> None:
    data = manifest_path.read_bytes()
    if len(data) > 65_536:
        raise StageDraftReleaseError("release-v2.json exceeds 65,536 bytes")
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except StageDraftReleaseError:
        raise
    except Exception as error:
        raise StageDraftReleaseError("release-v2.json is invalid JSON") from error
    if not isinstance(document, dict) or _canonical_json(document) != data:
        raise StageDraftReleaseError("release-v2.json is not canonical JSON")
    if document.get("key_id") != "neko-update-prod-1":
        raise StageDraftReleaseError("Stable-release key authority mismatch")
    release_set = _verify_manifest_signature(document)
    _ensure_launcher_import_path()
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts.derive_version import get_release_sequence, get_release_id
    finally:
        sys.path.pop(0)
    expected_sequence = get_release_sequence(tag)
    expected_release_id = get_release_id(expected_sequence)

    if (
        release_set.channel != "stable"
        or release_set.release_sequence != expected_sequence
        or release_set.minimum_supported_sequence != 1
        or release_set.release_id != expected_release_id
    ):
        raise StageDraftReleaseError("Stable-release authority mismatch")
    if (
        release_set.updater_protocol.minimum != 1
        or release_set.updater_protocol.maximum != 1
    ):
        raise StageDraftReleaseError("Stable-release protocol or tag mismatch")
    if set(release_set.components) != set(_COMPONENTS):
        raise StageDraftReleaseError("Manifest component set mismatch")
    for component_name, (file_name, file_format) in _COMPONENTS.items():
        descriptor = release_set.components[component_name]
        file_data = assets[file_name].read_bytes()
        digest = hashlib.sha256(file_data).hexdigest()
        if (
            descriptor.version != tag.lstrip("v")
            or descriptor.artifact_id != file_name
            or descriptor.artifact_sha256 != digest
            or descriptor.artifact_size != len(file_data)
            or descriptor.artifact_format != file_format
            or (
                component_name in {"launcher", "updater"}
                and descriptor.installed_identity_sha256 != digest
            )
        ):
            raise StageDraftReleaseError(f"Manifest descriptor mismatch: {component_name}")

    _ensure_launcher_import_path()
    try:
        from neko_launcher.updater.core_manifest_verifier import (
            verify_canonical_core_bundle,
        )
        from neko_launcher.updater.zip_extractor import extract_core_bundle

        with tempfile.TemporaryDirectory(prefix="neko-core-proof-") as extraction_dir:
            extracted = Path(extraction_dir)
            extract_core_bundle(assets["NekoProxyCore.zip"], extracted)
            verification = verify_canonical_core_bundle(extracted)
    except Exception as error:
        raise StageDraftReleaseError("Core bundle extraction or verification failed") from error
    if not verification.valid:
        raise StageDraftReleaseError("Core bundle verification failed")
    if (
        verification.manifest_sha256
        != release_set.components["core"].installed_identity_sha256
    ):
        raise StageDraftReleaseError("Core installed identity mismatch")


def validate_staging_preconditions(
    *,
    staging_dir: Path,
    tag: str,
    target_commit: str,
    repo_root: Path,
    executor: CommandExecutor,
) -> dict[str, Path]:
    if re.fullmatch(r"[0-9a-fA-F]{40}", target_commit) is None:
        raise StageDraftReleaseError("Target commit must be a 40-character hexadecimal SHA")
    git = ["git", "-C", str(repo_root)]
    status = _run(executor, [*git, "status", "--porcelain", "--untracked-files=all"])
    if status:
        raise StageDraftReleaseError("Worktree is not clean")
    bound = _run(executor, [*git, "rev-parse", f"{tag}^{{commit}}"]).strip()
    if bound.lower() != target_commit.lower():
        raise StageDraftReleaseError("Local tag does not bind to target commit")
    if not staging_dir.is_dir():
        raise StageDraftReleaseError("Staging directory does not exist")
    names = {item.name for item in staging_dir.iterdir()}
    required = set(REQUIRED_STAGE_ASSETS)
    if names != required:
        raise StageDraftReleaseError("Staging directory must contain exactly the five required files")
    assets = {name: staging_dir / name for name in REQUIRED_STAGE_ASSETS}
    if any(not path.is_file() or path.stat().st_size <= 0 for path in assets.values()):
        raise StageDraftReleaseError("Every staging asset must be a non-empty regular file")
    _validate_manifest(assets["release-v2.json"], assets, tag)
    return assets


def _quoted(args: list[str]) -> str:
    return subprocess.list2cmdline(args)


def _github_object(raw: str, *, context: str) -> tuple[str, str]:
    try:
        document = json.loads(raw)
        value = document["object"]
        object_type = value["type"]
        sha = value["sha"]
    except Exception as error:
        raise StageDraftReleaseError(f"{context} returned malformed JSON") from error
    if object_type not in {"commit", "tag"} or not isinstance(sha, str) or _SHA.fullmatch(sha) is None:
        raise StageDraftReleaseError(f"{context} returned an invalid Git object")
    return object_type, sha.lower()


def _validate_remote_tag_binding(
    *, tag: str, target_commit: str, executor: CommandExecutor
) -> None:
    endpoint = f"repos/{CANONICAL_REPO}/git/ref/tags/{quote(tag, safe='')}"
    object_type, sha = _github_object(
        _run(executor, ["gh", "api", endpoint]), context="Remote tag reference"
    )
    seen: set[str] = set()
    while object_type == "tag":
        if sha in seen:
            raise StageDraftReleaseError("Canonical remote tag contains a peel cycle")
        if len(seen) >= _REMOTE_TAG_MAX_DEPTH:
            raise StageDraftReleaseError("Canonical remote tag exceeds maximum peel depth")
        seen.add(sha)
        object_type, sha = _github_object(
            _run(
                executor,
                ["gh", "api", f"repos/{CANONICAL_REPO}/git/tags/{sha}"],
            ),
            context="Remote annotated tag",
        )
    if sha != target_commit.lower():
        raise StageDraftReleaseError("Canonical remote tag does not bind to target commit")


def stage_draft_release(
    *,
    staging_dir: Path,
    tag: str,
    target_commit: str,
    title: str | None = None,
    notes: str | None = None,
    as_prerelease: bool = False,
    dry_run: bool = False,
    executor: CommandExecutor | None = None,
) -> StagedDraftEvidence | None:
    runner = executor or _SubprocessExecutor()
    repo_root = Path(__file__).resolve().parents[1]
    assets = validate_staging_preconditions(
        staging_dir=Path(staging_dir), tag=tag, target_commit=target_commit,
        repo_root=repo_root, executor=runner,
    )
    _validate_remote_tag_binding(
        tag=tag, target_commit=target_commit, executor=runner
    )
    create = [
        "gh",
        "release",
        "create",
        tag,
        "--target",
        target_commit,
        "--verify-tag",
        "--draft",
        f"--prerelease={str(as_prerelease).lower()}",
        "--repo",
        CANONICAL_REPO,
    ]
    if title is not None:
        create.extend(["--title", title])
    if notes is not None:
        create.extend(["--notes", notes])
    upload = [
        "gh",
        "release",
        "upload",
        tag,
        *(str(assets[name]) for name in REQUIRED_STAGE_ASSETS),
        "--clobber=false",
        "--repo",
        CANONICAL_REPO,
    ]
    if dry_run:
        print(_quoted(create))
        print(_quoted(upload))
        return None
    _run(runner, create)
    _run(runner, upload)
    discovery_raw = _run(
        runner,
        [
            "gh",
            "api",
            f"repos/{CANONICAL_REPO}/releases?per_page=100",
            "--paginate",
            "--slurp",
        ],
    )
    try:
        pages = json.loads(discovery_raw)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise ValueError("expected paginated release arrays")
        matches = [
            release
            for page in pages
            for release in page
            if isinstance(release, dict)
            and release.get("draft") is True
            and release.get("tag_name") == tag
            and isinstance(release.get("target_commitish"), str)
            and release["target_commitish"].lower() == target_commit.lower()
        ]
    except Exception as error:
        raise StageDraftReleaseError("Draft ID discovery returned invalid JSON") from error
    if len(matches) != 1:
        raise StageDraftReleaseError(
            "Draft ID discovery requires exactly one draft matching tag and target"
        )
    release_id = matches[0].get("id")
    if type(release_id) is not int or release_id <= 0:
        raise StageDraftReleaseError("Draft ID discovery has invalid numeric release ID")
    release_raw = _run(
        runner, ["gh", "api", f"repos/{CANONICAL_REPO}/releases/{release_id}"]
    )
    try:
        release = json.loads(release_raw)
    except Exception as error:
        raise StageDraftReleaseError("Draft readback returned invalid JSON") from error
    if (
        release.get("id") != release_id
        or release.get("tag_name") != tag
        or release.get("target_commitish", "").lower() != target_commit.lower()
        or release.get("draft") is not True
        or release.get("prerelease") is not as_prerelease
    ):
        raise StageDraftReleaseError("Draft readback identity or state mismatch")
    bindings: dict[str, int] = {}
    raw_assets = release.get("assets")
    if not isinstance(raw_assets, list):
        raise StageDraftReleaseError("Draft readback assets missing")
    for asset in raw_assets:
        if isinstance(asset, dict) and asset.get("name") in REQUIRED_STAGE_ASSETS:
            name, asset_id, asset_size = asset["name"], asset.get("id"), asset.get("size")
            if name in bindings or type(asset_id) is not int or asset_id <= 0:
                raise StageDraftReleaseError("Duplicate or invalid required asset binding")
            if (
                type(asset_size) is not int
                or asset_size <= 0
                or asset_size != assets[name].stat().st_size
            ):
                raise StageDraftReleaseError("Invalid or mismatched required asset size")
            bindings[name] = asset_id
    if set(bindings) != set(REQUIRED_STAGE_ASSETS):
        raise StageDraftReleaseError("Draft readback does not contain each required asset exactly once")
    dispatch = (
        f"gh workflow run release.yml --ref {tag} -f publish_release=true "
        f"-f release_id={release_id} -f release_tag={tag} -f expected_target={target_commit}"
    )
    evidence = StagedDraftEvidence(release_id, tag, target_commit, bindings, dispatch)
    print(json.dumps({"release_id": release_id, "tag_name": tag, "target_commit": target_commit, "assets": bindings}, sort_keys=True))
    print(dispatch)
    return evidence


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage a validated offline-signed candidate as a GitHub draft")
    parser.add_argument("--staging-dir", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--title")
    parser.add_argument("--notes")
    parser.add_argument("--as-prerelease", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        stage_draft_release(**vars(args))
    except StageDraftReleaseError as error:
        message = re.sub(r"https?://\S+", "<sanitized-url>", str(error))
        print(f"draft staging failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
def build_release_payload(version: str, sha: str) -> dict:
    return {
        "tag_name": version,
        "target_commitish": sha,
        "name": version,
        "draft": False,
        "prerelease": False,
        "generate_release_notes": True
    }


def execute_publish(version: str, sha: str, staging_dir: str = ".") -> None:
    from pathlib import Path
    import tempfile
    import json
    import time
    import hashlib
    from scripts.verify_github_release_assets import verify_github_release_assets

    runner = _SubprocessExecutor()
    repo_root = Path(__file__).resolve().parents[1]

    try:
        out = _run(runner, ["gh", "release", "view", version, "--repo", CANONICAL_REPO, "--json", "targetCommitish"])
        view = json.loads(out)
        if view.get("targetCommitish", "").lower() == sha.lower():
            print(f"Release {version} for {sha} already exists. Skipping duplicate publish.")
            return
    except Exception:
        pass

    git = ["git", "-C", str(repo_root)]
    try:
        bound = _run(runner, [*git, "rev-parse", f"{version}^{{commit}}"]).strip()
        if bound.lower() != sha.lower():
            raise StageDraftReleaseError(f"Local tag {version} already exists but points to {bound}, expected {sha}")
    except Exception:
        _run(runner, [*git, "tag", version, sha])
        _run(runner, [*git, "push", "origin", version])

    evidence = stage_draft_release(
        staging_dir=Path(staging_dir),
        tag=version,
        target_commit=sha,
        as_prerelease=False,
        executor=runner
    )

    if not evidence:
        raise StageDraftReleaseError("Draft staging failed to return evidence")

    with tempfile.TemporaryDirectory(prefix="neko-hosted-verify-") as tmpdir:
        tmp_path = Path(tmpdir)
        token = _run(runner, ["gh", "auth", "token"]).strip()

        for name, asset_id in evidence.assets.items():
            out_path = tmp_path / name
            url = f"https://api.github.com/repos/{CANONICAL_REPO}/releases/assets/{asset_id}"
            curl = ["curl", "-sSL", "-H", f"Authorization: Bearer {token}", "-H", "Accept: application/octet-stream", "-o", str(out_path), url]
            _run(runner, curl)

            local_path = Path(staging_dir, name)
            if out_path.stat().st_size != local_path.stat().st_size:
                raise StageDraftReleaseError(f"Downloaded asset {name} size mismatch")

            hosted_digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
            local_digest = hashlib.sha256(local_path.read_bytes()).hexdigest()
            if hosted_digest != local_digest:
                raise StageDraftReleaseError(f"Downloaded asset {name} digest mismatch")

        release_json_raw = _run(runner, ["gh", "api", f"repos/{CANONICAL_REPO}/releases/{evidence.release_id}"])
        release_json_path = tmp_path / "release.json"
        release_json_path.write_text(release_json_raw, encoding="utf-8")

        try:
            verify_github_release_assets(
                release_json_path=release_json_path,
                download_dir=tmp_path,
                expected_tag=version,
                expected_target=sha,
                require_draft=True
            )
        except Exception as e:
            raise StageDraftReleaseError(f"Hosted verification failed: {e}") from e

        pre_promote_raw = _run(runner, ["gh", "api", f"repos/{CANONICAL_REPO}/releases/{evidence.release_id}"])
        pre_promote = json.loads(pre_promote_raw)

        if (
            pre_promote.get("tag_name") != version
            or pre_promote.get("target_commitish", "").lower() != sha.lower()
            or pre_promote.get("draft") is not True
        ):
            raise StageDraftReleaseError("Draft state mutated before promotion")

        current_assets = {a.get("name"): {"id": a.get("id"), "size": a.get("size")} for a in pre_promote.get("assets", []) if isinstance(a, dict)}
        for name, asset_id in evidence.assets.items():
            if name not in current_assets:
                raise StageDraftReleaseError(f"Asset {name} missing before promotion")
            if current_assets[name]["id"] != asset_id:
                raise StageDraftReleaseError(f"Asset {name} ID mutated before promotion")
            if current_assets[name]["size"] != Path(staging_dir, name).stat().st_size:
                raise StageDraftReleaseError(f"Asset {name} size mutated before promotion")

    _run(runner, ["gh", "release", "edit", version, "--draft=false", "--repo", CANONICAL_REPO])

    timeout = time.time() + 300
    success = False
    latest_error = None
    while time.time() < timeout:
        try:
            latest_raw = _run(runner, ["gh", "api", f"repos/{CANONICAL_REPO}/releases/latest"])
            latest = json.loads(latest_raw)
            if latest.get("id") == evidence.release_id and latest.get("tag_name") == version:
                latest_assets = {a.get("name"): {"id": a.get("id"), "size": a.get("size")} for a in latest.get("assets", []) if isinstance(a, dict)}
                for name, asset_id in evidence.assets.items():
                    if name not in latest_assets or latest_assets[name]["id"] != asset_id or latest_assets[name]["size"] != Path(staging_dir, name).stat().st_size:
                        raise ValueError(f"Gate3: Asset {name} mismatch in latest release")
                success = True
                break
        except Exception as e:
            latest_error = e
        time.sleep(5)

    if not success:
        raise StageDraftReleaseError(f"Gate3 failed: Latest release did not resolve to {version} correctly: {latest_error}")

    print(f"Successfully published {version}")
