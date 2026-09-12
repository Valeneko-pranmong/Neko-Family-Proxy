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
import time
from typing import Protocol, Sequence
from urllib.parse import quote

try:
    from scripts.verify_installer_release_assets import (
        CANONICAL_MACHINE_REPO,
        DEFAULT_INSTALLER_REPO,
        REQUIRED_INSTALLER_ASSET,
        REQUIRED_INSTALLER_ASSETS,
        InstallerReleaseVerificationError,
        _contains_machine_repo,
        verify_installer_release_assets,
    )
except ModuleNotFoundError:
    from verify_installer_release_assets import (  # type: ignore[no-redef]
        CANONICAL_MACHINE_REPO,
        DEFAULT_INSTALLER_REPO,
        REQUIRED_INSTALLER_ASSET,
        REQUIRED_INSTALLER_ASSETS,
        InstallerReleaseVerificationError,
        _contains_machine_repo,
        verify_installer_release_assets,
    )

__all__ = [
    "CANONICAL_MACHINE_REPO",
    "DEFAULT_INSTALLER_REPO",
    "REQUIRED_INSTALLER_ASSET",
    "REQUIRED_INSTALLER_ASSETS",
    "CommandExecutor",
    "InstallerPublishError",
    "InstallerReleaseVerificationError",
    "StagedInstallerDraftEvidence",
    "execute_installer_publish",
    "main",
    "stage_installer_draft_release",
    "validate_installer_staging_preconditions",
    "verify_installer_release_assets",
]

_REMOTE_TAG_MAX_DEPTH = 4
_SHA = re.compile(r"[0-9a-fA-F]{40}")


class InstallerPublishError(Exception):
    """Raised when installer release staging or publication fails."""


@dataclass(frozen=True)
class StagedInstallerDraftEvidence:
    release_id: int
    tag_name: str
    target_commit: str
    repo: str
    installer_asset_id: int
    installer_size: int
    installer_sha256: str
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
        raise InstallerPublishError(f"Command failed: {args[0]} {args[1] if len(args) > 1 else ''}")
    return result.stdout


def _quoted(args: list[str]) -> str:
    return subprocess.list2cmdline(args)


def _validate_installer_repo(repo: str | None) -> str:
    if not repo or not repo.strip():
        raise InstallerPublishError("Installer repository must be explicitly specified")
    cleaned = repo.strip()
    if _contains_machine_repo(cleaned):
        raise InstallerPublishError(
            f"Installer repository cannot be the canonical machine repository ({CANONICAL_MACHINE_REPO})"
        )
    return cleaned


def _github_object(raw: str, *, context: str) -> tuple[str, str]:
    try:
        document = json.loads(raw)
        value = document["object"]
        object_type = value["type"]
        sha = value["sha"]
    except Exception as error:
        raise InstallerPublishError(f"{context} returned malformed JSON") from error
    if object_type not in {"commit", "tag"} or not isinstance(sha, str) or _SHA.fullmatch(sha) is None:
        raise InstallerPublishError(f"{context} returned an invalid Git object")
    return object_type, sha.lower()


def _validate_remote_tag_binding(
    *, tag: str, target_commit: str, repo: str, executor: CommandExecutor
) -> None:
    endpoint = f"repos/{repo}/git/ref/tags/{quote(tag, safe='')}"
    object_type, sha = _github_object(
        _run(executor, ["gh", "api", endpoint]), context="Remote tag reference"
    )
    seen: set[str] = set()
    while object_type == "tag":
        if sha in seen:
            raise InstallerPublishError("Remote tag contains a peel cycle")
        if len(seen) >= _REMOTE_TAG_MAX_DEPTH:
            raise InstallerPublishError("Remote tag exceeds maximum peel depth")
        seen.add(sha)
        object_type, sha = _github_object(
            _run(
                executor,
                ["gh", "api", f"repos/{repo}/git/tags/{sha}"],
            ),
            context="Remote annotated tag",
        )
    if sha != target_commit.lower():
        raise InstallerPublishError("Remote tag does not bind to target commit")


def validate_installer_staging_preconditions(
    *,
    staging_dir: Path,
    tag: str,
    target_commit: str,
    installer_repo: str,
    repo_root: Path,
    executor: CommandExecutor,
) -> tuple[Path, str, int]:
    _validate_installer_repo(installer_repo)
    if _SHA.fullmatch(target_commit) is None:
        raise InstallerPublishError("Target commit must be a 40-character hexadecimal SHA")

    git = ["git", "-C", str(repo_root)]
    status = _run(executor, [*git, "status", "--porcelain", "--untracked-files=all"])
    if status:
        raise InstallerPublishError("Worktree is not clean")

    bound = _run(executor, [*git, "rev-parse", f"{tag}^{{commit}}"]).strip()
    if bound.lower() != target_commit.lower():
        raise InstallerPublishError("Local tag does not bind to target commit")

    staging_path = Path(staging_dir)
    if staging_path.is_dir():
        names = {item.name for item in staging_path.iterdir()}
        if REQUIRED_INSTALLER_ASSET not in names:
            raise InstallerPublishError(
                f"Staging directory missing required installer asset: {REQUIRED_INSTALLER_ASSET}"
            )
        extra = names - {REQUIRED_INSTALLER_ASSET}
        if extra:
            raise InstallerPublishError(
                f"Staging directory must contain exactly one custom installer asset (found extra: {sorted(extra)})"
            )
        installer_file = staging_path / REQUIRED_INSTALLER_ASSET
    elif staging_path.is_file():
        if staging_path.name != REQUIRED_INSTALLER_ASSET:
            raise InstallerPublishError(
                f"Installer file name mismatch: expected {REQUIRED_INSTALLER_ASSET!r}, got {staging_path.name!r}"
            )
        installer_file = staging_path
    else:
        raise InstallerPublishError(f"Staging path does not exist: {staging_path}")

    if not installer_file.is_file() or installer_file.stat().st_size <= 0:
        raise InstallerPublishError("Installer asset must be a non-empty regular file")

    file_bytes = installer_file.read_bytes()
    sha256 = hashlib.sha256(file_bytes).hexdigest().lower()
    size = len(file_bytes)
    return installer_file, sha256, size


def stage_installer_draft_release(
    *,
    staging_dir: Path | str,
    tag: str,
    target_commit: str,
    installer_repo: str = DEFAULT_INSTALLER_REPO,
    title: str | None = None,
    notes: str | None = None,
    as_prerelease: bool = False,
    dry_run: bool = False,
    executor: CommandExecutor | None = None,
) -> StagedInstallerDraftEvidence | None:
    runner = executor or _SubprocessExecutor()
    repo = _validate_installer_repo(installer_repo)
    repo_root = Path(__file__).resolve().parents[1]

    installer_file, sha256, size = validate_installer_staging_preconditions(
        staging_dir=Path(staging_dir),
        tag=tag,
        target_commit=target_commit,
        installer_repo=repo,
        repo_root=repo_root,
        executor=runner,
    )

    _validate_remote_tag_binding(
        tag=tag, target_commit=target_commit, repo=repo, executor=runner
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
        repo,
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
        str(installer_file),
        "--clobber=false",
        "--repo",
        repo,
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
            f"repos/{repo}/releases?per_page=100",
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
        raise InstallerPublishError("Draft ID discovery returned invalid JSON") from error

    if len(matches) != 1:
        raise InstallerPublishError(
            "Draft ID discovery requires exactly one draft matching tag and target"
        )
    release_id = matches[0].get("id")
    if type(release_id) is not int or release_id <= 0:
        raise InstallerPublishError("Draft ID discovery has invalid numeric release ID")

    release_raw = _run(
        runner, ["gh", "api", f"repos/{repo}/releases/{release_id}"]
    )
    try:
        release = json.loads(release_raw)
    except Exception as error:
        raise InstallerPublishError("Draft readback returned invalid JSON") from error

    if (
        release.get("id") != release_id
        or release.get("tag_name") != tag
        or release.get("target_commitish", "").lower() != target_commit.lower()
        or release.get("draft") is not True
        or release.get("prerelease") is not as_prerelease
    ):
        raise InstallerPublishError("Draft readback identity or state mismatch")

    raw_assets = release.get("assets")
    if not isinstance(raw_assets, list):
        raise InstallerPublishError("Draft readback assets missing")

    if len(raw_assets) != 1:
        raise InstallerPublishError(
            f"Draft readback contains unexpected extra assets (expected exactly one, got {len(raw_assets)})"
        )

    asset = raw_assets[0]
    if not isinstance(asset, dict):
        raise InstallerPublishError("Draft readback asset entry must be an object")

    name = asset.get("name")
    if name != REQUIRED_INSTALLER_ASSET:
        raise InstallerPublishError(
            f"Draft readback contains unexpected asset name: {name!r} (expected {REQUIRED_INSTALLER_ASSET!r})"
        )

    asset_id, asset_size = asset.get("id"), asset.get("size")
    if type(asset_id) is not int or asset_id <= 0:
        raise InstallerPublishError("Invalid required installer asset ID")
    if type(asset_size) is not int or asset_size <= 0 or asset_size != size:
        raise InstallerPublishError("Invalid or mismatched required installer asset size")

    dispatch = (
        f"gh workflow run release.yml --ref {tag} -f publish_installer=true "
        f"-f release_id={release_id} -f release_tag={tag} -f expected_target={target_commit} "
        f"-f installer_repo={repo}"
    )
    evidence = StagedInstallerDraftEvidence(
        release_id=release_id,
        tag_name=tag,
        target_commit=target_commit,
        repo=repo,
        installer_asset_id=asset_id,
        installer_size=size,
        installer_sha256=sha256,
        dispatch_command=dispatch,
    )
    return evidence


def execute_installer_publish(
    version: str,
    sha: str,
    staging_dir: Path | str = ".",
    *,
    installer_repo: str = DEFAULT_INSTALLER_REPO,
    notes: str | None = None,
    title: str | None = None,
    executor: CommandExecutor | None = None,
) -> None:
    runner = executor or _SubprocessExecutor()
    repo = _validate_installer_repo(installer_repo)
    repo_root = Path(__file__).resolve().parents[1]

    try:
        out = _run(
            runner,
            ["gh", "release", "view", version, "--repo", repo, "--json", "targetCommitish"],
        )
        view = json.loads(out)
        if view.get("targetCommitish", "").lower() == sha.lower():
            print(f"Installer release {version} for {sha} already exists on {repo}. Skipping duplicate publish.")
            return
    except Exception:
        pass

    git = ["git", "-C", str(repo_root)]
    try:
        bound = _run(runner, [*git, "rev-parse", f"{version}^{{commit}}"]).strip()
        if bound.lower() != sha.lower():
            raise InstallerPublishError(
                f"Local tag {version} already exists but points to {bound}, expected {sha}"
            )
    except Exception:
        _run(runner, [*git, "tag", version, sha])
        _run(runner, [*git, "push", "origin", version])

    evidence = stage_installer_draft_release(
        staging_dir=Path(staging_dir),
        tag=version,
        target_commit=sha,
        installer_repo=repo,
        title=title,
        notes=notes,
        as_prerelease=False,
        executor=runner,
    )

    if not evidence:
        raise InstallerPublishError("Installer draft staging failed to return evidence")

    with tempfile.TemporaryDirectory(prefix="neko-installer-hosted-verify-") as tmpdir:
        tmp_path = Path(tmpdir)
        token = _run(runner, ["gh", "auth", "token"]).strip()

        out_path = tmp_path / REQUIRED_INSTALLER_ASSET
        url = f"https://api.github.com/repos/{repo}/releases/assets/{evidence.installer_asset_id}"
        curl = [
            "curl",
            "-sSL",
            "-H",
            f"Authorization: Bearer {token}",
            "-H",
            "Accept: application/octet-stream",
            "-o",
            str(out_path),
            url,
        ]
        _run(runner, curl)

        local_file = (
            Path(staging_dir) / REQUIRED_INSTALLER_ASSET
            if Path(staging_dir).is_dir()
            else Path(staging_dir)
        )
        if out_path.stat().st_size != local_file.stat().st_size:
            raise InstallerPublishError("Downloaded installer asset size mismatch")

        hosted_digest = hashlib.sha256(out_path.read_bytes()).hexdigest().lower()
        local_digest = hashlib.sha256(local_file.read_bytes()).hexdigest().lower()
        if hosted_digest != local_digest:
            raise InstallerPublishError("Downloaded installer asset digest mismatch")

        release_json_raw = _run(
            runner, ["gh", "api", f"repos/{repo}/releases/{evidence.release_id}"]
        )
        release_json_path = tmp_path / "installer_release.json"
        release_json_path.write_text(release_json_raw, encoding="utf-8")

        try:
            verify_installer_release_assets(
                release_json_path=release_json_path,
                installer_path=out_path,
                expected_tag=version,
                expected_target=sha,
                require_draft=True,
                expected_repo=repo,
            )
        except InstallerReleaseVerificationError as e:
            raise InstallerPublishError(f"Hosted verification failed: {e}") from e

        pre_promote_raw = _run(
            runner, ["gh", "api", f"repos/{repo}/releases/{evidence.release_id}"]
        )
        pre_promote = json.loads(pre_promote_raw)

        if (
            pre_promote.get("tag_name") != version
            or pre_promote.get("target_commitish", "").lower() != sha.lower()
            or pre_promote.get("draft") is not True
        ):
            raise InstallerPublishError("Draft state mutated before promotion")

        current_assets = [
            a for a in pre_promote.get("assets", []) if isinstance(a, dict)
        ]
        if len(current_assets) != 1:
            raise InstallerPublishError(
                f"Draft assets mutated before promotion: expected 1 asset, got {len(current_assets)}"
            )
        prom_asset = current_assets[0]
        if prom_asset.get("id") != evidence.installer_asset_id:
            raise InstallerPublishError("Installer asset ID mutated before promotion")
        if prom_asset.get("size") != local_file.stat().st_size:
            raise InstallerPublishError("Installer asset size mutated before promotion")
        if prom_asset.get("name") != REQUIRED_INSTALLER_ASSET:
            raise InstallerPublishError("Installer asset name mutated before promotion")

    _run(runner, ["gh", "release", "edit", version, "--draft=false", "--repo", repo])

    timeout = time.time() + 300
    success = False
    latest_error = None
    while time.time() < timeout:
        try:
            latest_raw = _run(runner, ["gh", "api", f"repos/{repo}/releases/latest"])
            latest = json.loads(latest_raw)
            if latest.get("id") == evidence.release_id and latest.get("tag_name") == version:
                latest_assets = [
                    a for a in latest.get("assets", []) if isinstance(a, dict)
                ]
                if len(latest_assets) != 1:
                    raise ValueError(
                        f"Gate3: Asset count mismatch in latest installer release (expected 1, got {len(latest_assets)})"
                    )
                l_asset = latest_assets[0]
                if l_asset.get("id") != evidence.installer_asset_id or l_asset.get("size") != local_file.stat().st_size:
                    raise ValueError("Gate3: Asset mismatch in latest installer release")
                if l_asset.get("name") != REQUIRED_INSTALLER_ASSET:
                    raise ValueError("Gate3: Asset name mismatch in latest installer release")
                success = True
                break
        except Exception as e:
            latest_error = e
        time.sleep(5)

    if not success:
        raise InstallerPublishError(
            f"Gate3 failed: Latest installer release did not resolve to {version} correctly: {latest_error}"
        )

    print(f"Successfully published installer {version} to {repo}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage a verified installer artifact as a GitHub draft in the installer repository"
    )
    parser.add_argument("--staging-dir", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--installer-repo", default=DEFAULT_INSTALLER_REPO)
    parser.add_argument("--title")
    parser.add_argument("--notes")
    parser.add_argument("--as-prerelease", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        stage_installer_draft_release(**vars(args))
    except InstallerPublishError as error:
        message = re.sub(r"https?://\S+", "<sanitized-url>", str(error))
        print(f"installer draft staging failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
