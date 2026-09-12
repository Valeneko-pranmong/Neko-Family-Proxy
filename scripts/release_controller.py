import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Mapping
import zipfile

# Add project root to sys.path so we can import internal modules
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2  # noqa: E402
from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS  # noqa: E402

from scripts.ci_change_classifier import should_trigger  # noqa: E402
from scripts.kanban_release_adapter import get_successful_main_runs  # noqa: E402
from scripts.publish_atomic_release import (  # noqa: E402
    CANONICAL_REPO,
    CommandExecutor,
    StageDraftReleaseError,
    StagedDraftEvidence,
    _SubprocessExecutor,
    _run,
    build_machine_release_notes,
    stage_draft_release,
    validate_staging_preconditions,
)
from scripts.publish_installer_release import (  # noqa: E402
    CANONICAL_MACHINE_REPO,
    REQUIRED_INSTALLER_ASSET,
    InstallerPublishError,
    StagedInstallerDraftEvidence,
    _contains_machine_repo,
    stage_installer_draft_release,
    validate_installer_staging_preconditions,
)
from scripts.verify_github_release_assets import verify_github_release_assets  # noqa: E402
from scripts.verify_installer_release_assets import (  # noqa: E402
    InstallerReleaseVerificationError,
    verify_installer_release_assets,
)

BOOTSTRAP_STABLE_TAG = "v5.1.0"


def validate_installer_repo_configuration(repo: str | None) -> str:
    if not repo or not str(repo).strip():
        raise ValueError(
            "Explicit installer repository identity is mandatory with no silent fallback"
        )
    cleaned = str(repo).strip()
    normalized = re.sub(r"\.git$", "", cleaned, flags=re.IGNORECASE)
    if _contains_machine_repo(cleaned) or _contains_machine_repo(normalized):
        raise ValueError(
            f"Installer repository cannot be the canonical machine repository ({CANONICAL_MACHINE_REPO})"
        )
    return cleaned



def _parse_semver(tag: str) -> tuple[int, int, int]:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", tag)
    if not m:
        raise ValueError(f"Invalid semver tag format: {tag}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_version_newer(candidate_tag: str, base_tag: str) -> bool:
    return _parse_semver(candidate_tag) > _parse_semver(base_tag)


@dataclass(frozen=True)
class CoreAuthoritySource:
    manifest_path: Path
    core_zip_path: Path
    provenance: dict[str, object]
    core_sha256: str = ""
    core_size: int = 0
    installed_identity_sha256: str = ""


def _get_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().lower()


def verify_core_authority_bytes(
    manifest_path: Path,
    core_zip_path: Path,
    expected_tag: str,
    *,
    trusted_keys: Mapping[str, bytes] | None = None,
    updater_exe_path: Path | None = None,
) -> tuple[str, int, str]:
    from neko_launcher.updater.core_manifest_verifier import (
        verify_canonical_core_bundle,
    )
    from neko_launcher.updater.zip_extractor import extract_core_bundle

    if not manifest_path.is_file():
        raise RuntimeError(f"Manifest file not found: {manifest_path}")
    if not core_zip_path.is_file():
        raise RuntimeError(f"Core zip file not found: {core_zip_path}")

    try:
        manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to read/parse manifest JSON: {e}") from e

    if trusted_keys is None:
        trusted_keys = {"neko-update-prod-1": PRODUCTION_RELEASE_PUBLIC_KEYS["neko-update-prod-1"]}

    try:
        release_set, _ = verify_release_envelope_v2(manifest_doc, trusted_keys)
    except Exception as e:
        err_msg = str(e)
        if "channel" in err_msg.lower():
            raise RuntimeError(f"Release manifest channel is not stable: {e}") from e
        raise RuntimeError(f"Failed to verify release envelope signature: {e}") from e

    # Require channel stable
    if release_set.channel != "stable":
        raise RuntimeError(f"Release manifest channel is not stable (got '{release_set.channel}').")

    # If updater artifact is present, verify against signed authority
    if updater_exe_path is not None and updater_exe_path.is_file():
        if "updater" in release_set.components:
            up_comp = release_set.components["updater"]
            actual_up_sha = _get_sha256(updater_exe_path)
            actual_up_size = updater_exe_path.stat().st_size
            if actual_up_sha != up_comp.artifact_sha256.lower() or actual_up_size != up_comp.artifact_size:
                raise RuntimeError(
                    f"Archived NekoUpdater.exe in bootstrap authority does not match signed authority: "
                    f"sha {actual_up_sha} vs {up_comp.artifact_sha256}, size {actual_up_size} vs {up_comp.artifact_size}"
                )

    # Require core component
    if "core" not in release_set.components:
        raise RuntimeError("Core component missing from release manifest.")

    core_comp = release_set.components["core"]
    if core_comp.artifact_id != "NekoProxyCore.zip":
        raise RuntimeError(f"Core artifact_id mismatch: {core_comp.artifact_id}")

    expected_version = expected_tag.lstrip("v")
    if core_comp.version != expected_version:
        raise RuntimeError(
            f"Core component version '{core_comp.version}' does not match expected tag version '{expected_version}'."
        )

    expected_hash = core_comp.artifact_sha256.lower()
    expected_size = core_comp.artifact_size
    installed_identity = core_comp.installed_identity_sha256.lower()

    # Compare Core SHA256 and size to signed component
    actual_size = core_zip_path.stat().st_size
    actual_hash = _get_sha256(core_zip_path)

    if actual_size != expected_size or actual_hash != expected_hash:
        raise RuntimeError(
            f"Core zip does not match {expected_tag} signature: "
            f"size {actual_size} vs {expected_size}, sha256 {actual_hash} vs {expected_hash}"
        )

    # Run canonical Core bundle verifier + installed identity check
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        extract_core_bundle(core_zip_path, tmp_dir)
        verification = verify_canonical_core_bundle(tmp_dir)
        if not verification.valid:
            raise RuntimeError(f"Core bundle verification failed: {verification.error}")
        if verification.manifest_sha256 != installed_identity:
            raise RuntimeError(
                f"Core manifest installed identity mismatch inside zip: "
                f"expected {installed_identity}, got {verification.manifest_sha256}"
            )

    return actual_hash, actual_size, installed_identity


def resolve_core_authority(
    stable_tag: str,
    staging_dir: Path,
    *,
    bootstrap_authority_dir: Path | None = None,
    trusted_keys: Mapping[str, bytes] | None = None,
) -> CoreAuthoritySource:
    staging_dir.mkdir(parents=True, exist_ok=True)
    release_json_path = staging_dir / "release-v2.json"
    core_zip_path = staging_dir / "NekoProxyCore.zip"
    updater_exe_path: Path | None = None

    if bootstrap_authority_dir is not None:
        # Bounded bootstrap authority override
        if stable_tag != BOOTSTRAP_STABLE_TAG:
            if is_version_newer(stable_tag, BOOTSTRAP_STABLE_TAG):
                raise RuntimeError(
                    f"Bootstrap authority override is disabled because stable tag '{stable_tag}' "
                    f"is newer than bootstrap stable '{BOOTSTRAP_STABLE_TAG}'."
                )
            raise RuntimeError(
                f"Bootstrap authority override is only permitted for recognized bootstrap stable "
                f"'{BOOTSTRAP_STABLE_TAG}', not '{stable_tag}'."
            )

        if not bootstrap_authority_dir.is_dir():
            raise RuntimeError(
                f"Bootstrap authority directory does not exist or is not a directory: {bootstrap_authority_dir}"
            )

        manifest_src = bootstrap_authority_dir / "release-v2.json"
        core_src = bootstrap_authority_dir / "NekoProxyCore.zip"

        if not manifest_src.is_file() or not core_src.is_file():
            raise RuntimeError(
                f"Bootstrap authority directory is missing required assets (release-v2.json and NekoProxyCore.zip): {bootstrap_authority_dir}"
            )

        # Stage assets into staging_dir
        if staging_dir.resolve() != bootstrap_authority_dir.resolve():
            shutil.copy2(manifest_src, release_json_path)
            shutil.copy2(core_src, core_zip_path)

        # Also inspect/stage updater if present in bootstrap directory
        updater_src = bootstrap_authority_dir / "NekoUpdater.exe"
        staged_updater = staging_dir / "NekoUpdater.exe"
        if updater_src.is_file():
            if staging_dir.resolve() != bootstrap_authority_dir.resolve():
                shutil.copy2(updater_src, staged_updater)
            updater_exe_path = staged_updater

        provenance: dict[str, object] = {
            "source": "local_bootstrap_override",
            "stable_tag": stable_tag,
            "bootstrap_authority_dir": str(bootstrap_authority_dir.resolve()),
            "manifest_asset": "release-v2.json",
            "core_asset": "NekoProxyCore.zip",
        }
    else:
        # 1. Query GitHub release by exact stable tag (Normal path)
        print(f"Fetching {stable_tag} Core authority from GitHub...")
        cmd = ["gh", "api", f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/tags/{stable_tag}"]
        try:
            out = subprocess.check_output(cmd)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to fetch release {stable_tag}: {e}") from e

        release_data = json.loads(out)

        # 2. Require exactly one matching non-draft non-prerelease accepted release
        if release_data.get("draft") or release_data.get("prerelease"):
            raise RuntimeError(f"Release {stable_tag} is draft or prerelease.")

        release_id = release_data["id"]

        # 3. Require unique release-v2.json + NekoProxyCore.zip assets with numeric asset IDs
        release_json_asset = None
        core_zip_asset = None

        for asset in release_data.get("assets", []):
            if asset["name"] == "release-v2.json":
                if release_json_asset is not None:
                    raise RuntimeError("Duplicate release-v2.json assets found.")
                release_json_asset = asset
            elif asset["name"] == "NekoProxyCore.zip":
                if core_zip_asset is not None:
                    raise RuntimeError("Duplicate NekoProxyCore.zip assets found.")
                core_zip_asset = asset

        if not release_json_asset or not core_zip_asset:
            raise RuntimeError("Missing required assets in release.")

        manifest_asset_id = release_json_asset["id"]
        core_asset_id = core_zip_asset["id"]

        # 4. Download BOTH by immutable asset ID into staging
        subprocess.run([
            "gh", "api",
            f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/assets/{manifest_asset_id}",
            "-H", "Accept: application/octet-stream"
        ], stdout=release_json_path.open("wb"), check=True)

        subprocess.run([
            "gh", "api",
            f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/assets/{core_asset_id}",
            "-H", "Accept: application/octet-stream"
        ], stdout=core_zip_path.open("wb"), check=True)

        provenance = {
            "source": "github_release",
            "stable_tag": stable_tag,
            "release_id": release_id,
            "manifest_asset_id": manifest_asset_id,
            "core_asset_id": core_asset_id,
        }

    # Verify common byte-level cryptographic and canonical bundle properties
    core_hash, core_size, installed_identity = verify_core_authority_bytes(
        release_json_path,
        core_zip_path,
        expected_tag=stable_tag,
        trusted_keys=trusted_keys,
        updater_exe_path=updater_exe_path,
    )
    print(f"{stable_tag} Core verified successfully.")

    return CoreAuthoritySource(
        manifest_path=release_json_path,
        core_zip_path=core_zip_path,
        provenance=provenance,
        core_sha256=core_hash,
        core_size=core_size,
        installed_identity_sha256=installed_identity,
    )


def verify_and_fetch_core(
    stable_tag: str,
    staging_dir: Path,
    *,
    bootstrap_authority_dir: Path | None = None,
    trusted_keys: Mapping[str, bytes] | None = None,
) -> tuple[Path, str, int, str, dict]:
    print(f"Fetching and verifying {stable_tag} Core authority...")
    source = resolve_core_authority(
        stable_tag,
        staging_dir,
        bootstrap_authority_dir=bootstrap_authority_dir,
        trusted_keys=trusted_keys,
    )
    return (
        source.core_zip_path,
        source.core_sha256,
        source.core_size,
        source.installed_identity_sha256,
        source.provenance,
    )


def _hosted_verify_machine_channel(
    evidence: StagedDraftEvidence,
    staging_dir: Path,
    expected_tag: str,
    expected_target: str,
    runner: CommandExecutor,
) -> None:
    with tempfile.TemporaryDirectory(prefix="neko-hosted-verify-machine-") as tmpdir:
        tmp_path = Path(tmpdir)
        for name, asset_id in evidence.assets.items():
            out_path = tmp_path / name
            url = f"https://api.github.com/repos/{CANONICAL_REPO}/releases/assets/{asset_id}"
            curl = [
                "curl",
                "-sSL",
                "-H",
                "Authorization: Bearer ***",
                "-H",
                "Accept: application/octet-stream",
                "-o",
                str(out_path),
                url,
            ]
            _run(runner, curl)

            local_path = staging_dir / name
            if out_path.stat().st_size != local_path.stat().st_size:
                raise StageDraftReleaseError(f"Downloaded asset {name} size mismatch")

            hosted_digest = hashlib.sha256(out_path.read_bytes()).hexdigest().lower()
            local_digest = hashlib.sha256(local_path.read_bytes()).hexdigest().lower()
            if hosted_digest != local_digest:
                raise StageDraftReleaseError(f"Downloaded asset {name} digest mismatch")

        release_json_raw = _run(
            runner, ["gh", "api", f"repos/{CANONICAL_REPO}/releases/{evidence.release_id}"]
        )
        release_json_path = tmp_path / "release.json"
        release_json_path.write_text(release_json_raw, encoding="utf-8")

        try:
            verify_github_release_assets(
                release_json_path=release_json_path,
                download_dir=tmp_path,
                expected_tag=expected_tag,
                expected_target=expected_target,
                require_draft=True,
            )
        except Exception as e:
            raise StageDraftReleaseError(f"Hosted machine release verification failed: {e}") from e

        pre_promote_raw = _run(
            runner, ["gh", "api", f"repos/{CANONICAL_REPO}/releases/{evidence.release_id}"]
        )
        pre_promote = json.loads(pre_promote_raw)

        if (
            pre_promote.get("tag_name") != expected_tag
            or pre_promote.get("target_commitish", "").lower() != expected_target.lower()
            or pre_promote.get("draft") is not True
        ):
            raise StageDraftReleaseError("Machine draft state mutated before promotion")

        current_assets = {
            a.get("name"): {"id": a.get("id"), "size": a.get("size")}
            for a in pre_promote.get("assets", [])
            if isinstance(a, dict)
        }
        if set(current_assets.keys()) != set(evidence.assets.keys()):
            raise StageDraftReleaseError(
                f"Machine draft assets mutated before promotion (unexpected: {set(current_assets.keys()) - set(evidence.assets.keys())})"
            )
        for name, asset_id in evidence.assets.items():
            if name not in current_assets:
                raise StageDraftReleaseError(f"Machine asset {name} missing before promotion")
            if current_assets[name]["id"] != asset_id:
                raise StageDraftReleaseError(f"Machine asset {name} ID mutated before promotion")
            if current_assets[name]["size"] != (staging_dir / name).stat().st_size:
                raise StageDraftReleaseError(f"Machine asset {name} size mutated before promotion")


def _hosted_verify_installer_channel(
    evidence: StagedInstallerDraftEvidence,
    staging_dir: Path,
    expected_tag: str,
    expected_target: str,
    repo: str,
    runner: CommandExecutor,
) -> None:
    with tempfile.TemporaryDirectory(prefix="neko-installer-hosted-verify-") as tmpdir:
        tmp_path = Path(tmpdir)
        out_path = tmp_path / REQUIRED_INSTALLER_ASSET
        url = f"https://api.github.com/repos/{repo}/releases/assets/{evidence.installer_asset_id}"
        curl = [
            "curl",
            "-sSL",
            "-H",
            "Authorization: Bearer ***",
            "-H",
            "Accept: application/octet-stream",
            "-o",
            str(out_path),
            url,
        ]
        _run(runner, curl)

        local_file = (
            staging_dir / REQUIRED_INSTALLER_ASSET
            if staging_dir.is_dir()
            else staging_dir
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
                expected_tag=expected_tag,
                expected_target=expected_target,
                require_draft=True,
                expected_repo=repo,
            )
        except InstallerReleaseVerificationError as e:
            raise InstallerPublishError(f"Hosted installer verification failed: {e}") from e

        pre_promote_raw = _run(
            runner, ["gh", "api", f"repos/{repo}/releases/{evidence.release_id}"]
        )
        pre_promote = json.loads(pre_promote_raw)

        if (
            pre_promote.get("tag_name") != expected_tag
            or pre_promote.get("target_commitish", "").lower() != expected_target.lower()
            or pre_promote.get("draft") is not True
        ):
            raise InstallerPublishError("Installer draft state mutated before promotion")

        current_assets = [
            a for a in pre_promote.get("assets", []) if isinstance(a, dict)
        ]
        if len(current_assets) != 1:
            raise InstallerPublishError(
                f"Installer draft must contain exactly one asset before promotion, found {len(current_assets)}"
            )
        asset_obj = current_assets[0]
        if asset_obj.get("name") != REQUIRED_INSTALLER_ASSET:
            raise InstallerPublishError(
                f"Installer asset name mutated before promotion: {asset_obj.get('name')}"
            )
        if asset_obj.get("id") != evidence.installer_asset_id:
            raise InstallerPublishError("Installer asset ID mutated before promotion")
        if asset_obj.get("size") != local_file.stat().st_size:
            raise InstallerPublishError("Installer asset size mutated before promotion")


def publish_split_release(
    *,
    tag: str,
    commit: str,
    machine_staging_dir: Path | str,
    installer_staging_dir: Path | str,
    installer_repo: str,
    executor: CommandExecutor | None = None,
) -> None:
    repo = validate_installer_repo_configuration(installer_repo)
    runner = executor or _SubprocessExecutor()

    m_dir = Path(machine_staging_dir)
    i_dir = Path(installer_staging_dir)
    repo_root = Path(__file__).resolve().parent.parent

    # 1. Validate machine staging directory preconditions
    validate_staging_preconditions(
        staging_dir=m_dir,
        tag=tag,
        target_commit=commit,
        repo_root=repo_root,
        executor=runner,
    )

    # 2. Validate installer staging directory preconditions
    validate_installer_staging_preconditions(
        staging_dir=i_dir,
        tag=tag,
        target_commit=commit,
        installer_repo=repo,
        repo_root=repo_root,
        executor=runner,
    )

    # 3. Stage machine draft
    machine_notes = build_machine_release_notes(tag, installer_repo=repo)
    machine_evidence = stage_draft_release(
        staging_dir=m_dir,
        tag=tag,
        target_commit=commit,
        notes=machine_notes,
        as_prerelease=False,
        executor=runner,
    )
    if not machine_evidence:
        raise StageDraftReleaseError("Machine draft staging failed to return evidence")

    # 4. Stage installer draft
    installer_evidence = stage_installer_draft_release(
        staging_dir=i_dir,
        tag=tag,
        target_commit=commit,
        installer_repo=repo,
        as_prerelease=False,
        executor=runner,
    )
    if not installer_evidence:
        raise InstallerPublishError("Installer draft staging failed to return evidence")

    # 5. Hosted-verify machine draft byte-for-byte
    _hosted_verify_machine_channel(
        machine_evidence,
        staging_dir=m_dir,
        expected_tag=tag,
        expected_target=commit,
        runner=runner,
    )

    # 6. Hosted-verify installer draft byte-for-byte
    _hosted_verify_installer_channel(
        installer_evidence,
        staging_dir=i_dir,
        expected_tag=tag,
        expected_target=commit,
        repo=repo,
        runner=runner,
    )

    # 7. Promote installer surface FIRST
    _run(runner, ["gh", "release", "edit", tag, "--draft=false", "--repo", repo])
    post_promote_installer = json.loads(
        _run(runner, ["gh", "api", f"repos/{repo}/releases/{installer_evidence.release_id}"])
    )
    if post_promote_installer.get("draft") is not False:
        raise InstallerPublishError("Installer release promotion failed: still draft")

    # 8. Promote machine channel SECOND
    _run(runner, ["gh", "release", "edit", tag, "--draft=false", "--repo", CANONICAL_REPO])
    post_promote_machine = json.loads(
        _run(runner, ["gh", "api", f"repos/{CANONICAL_REPO}/releases/{machine_evidence.release_id}"])
    )
    if post_promote_machine.get("draft") is not False:
        raise StageDraftReleaseError("Machine release promotion failed: still draft")

    # 9. Gate 3 verification of machine latest release
    timeout = time.time() + 300
    success = False
    latest_error = None
    while time.time() < timeout:
        try:
            latest_raw = _run(runner, ["gh", "api", f"repos/{CANONICAL_REPO}/releases/latest"])
            latest = json.loads(latest_raw)
            if latest.get("id") == machine_evidence.release_id and latest.get("tag_name") == tag:
                latest_assets = {
                    a.get("name"): {"id": a.get("id"), "size": a.get("size")}
                    for a in latest.get("assets", [])
                    if isinstance(a, dict)
                }
                if set(latest_assets.keys()) != set(machine_evidence.assets.keys()):
                    raise ValueError(
                        f"Gate3: Asset set mismatch in latest release (unexpected: {set(latest_assets.keys()) - set(machine_evidence.assets.keys())})"
                    )
                for name, asset_id in machine_evidence.assets.items():
                    if (
                        name not in latest_assets
                        or latest_assets[name]["id"] != asset_id
                        or latest_assets[name]["size"] != (m_dir / name).stat().st_size
                    ):
                        raise ValueError(f"Gate3: Asset {name} mismatch in latest release")
                success = True
                break
            else:
                latest_error = (
                    f"Latest release id={latest.get('id')} tag={latest.get('tag_name')} "
                    f"does not match target id={machine_evidence.release_id} tag={tag}"
                )
        except Exception as e:
            latest_error = str(e)
        time.sleep(2)

    if not success:
        raise StageDraftReleaseError(
            f"Gate 3 failed: /releases/latest did not resolve to {tag}: {latest_error}"
        )


def process_accepted_commits(
    commit: str,
    run_id: int,
    *,
    installer_repo: str | None = None,
    bootstrap_authority_dir: Path | None = None,
):
    repo_root = Path(__file__).resolve().parent.parent

    # If installer_repo not explicitly passed as parameter, check if configured in repo's release_target.json
    if installer_repo is None:
        target_file = repo_root / "release_target.json"
        if target_file.is_file():
            try:
                target_data = json.loads(target_file.read_text(encoding="utf-8"))
                installer_repo = target_data.get("installer_repo")
            except Exception:
                pass

    # Explicit installer repository identity is mandatory with no silent fallback to canonical machine repo
    installer_repo = validate_installer_repo_configuration(installer_repo)

    # 1. Verify run-id and commit
    runs = get_successful_main_runs()
    valid = False
    for r in runs:
        if r["databaseId"] == run_id and r["headSha"] == commit:
            valid = True
            break
    if not valid:
        print(f"Error: Run {run_id} for commit {commit} is not an accepted product-impacting main run.", file=sys.stderr)
        sys.exit(1)

    # Verify reachable from origin/main
    subprocess.run(["git", "-C", str(repo_root), "merge-base", "--is-ancestor", commit, "origin/main"], check=True)

    # Verify should_trigger using exact-SHA changed files
    out = subprocess.check_output(["git", "-C", str(repo_root), "show", "--name-only", "--format=", commit], text=True)
    changed_files = [f for f in out.splitlines() if f.strip()]
    if not should_trigger(changed_files):
        print(f"Error: Commit {commit} does not contain product-impacting changes.", file=sys.stderr)
        sys.exit(1)


    staging_base = Path(f"E:/Github/artifacts/main-auto-release/{run_id}-{commit}")
    staging_base.mkdir(parents=True, exist_ok=True)

    source_dir = staging_base / "source"

    # 1.5. Extract exact-SHA workspace FIRST so we can read intent from it
    if not source_dir.exists():
        source_dir.mkdir(parents=True)
        tar_path = staging_base / "source.tar"
        subprocess.run(["git", "-C", str(repo_root), "archive", "--format=tar", "-o", str(tar_path), commit], check=True)
        subprocess.run(["tar", "-xf", str(tar_path), "-C", str(source_dir)], check=True)
        tar_path.unlink(missing_ok=True)

    idempotency_file = staging_base / "idempotency_record.json"
    if idempotency_file.exists():
        record = json.loads(idempotency_file.read_text(encoding="utf-8"))
        version_tag = record["version_tag"]
        version = version_tag.lstrip("v")
        stable = record.get("stable", "v5.1.0")
        stable_version = stable.lstrip("v")
        sequence = record["sequence"]
        release_id = record["release_id"]
        print(f"Resuming idempotent run: {version_tag}")
    else:
        # 2. Version allocation
        try:
            from scripts.derive_version import get_armed_target_from_dir
            stable, target, sequence, release_id = get_armed_target_from_dir(source_dir)
        except ValueError as e:
            print(f"Error: Could not derive target version from extracted source: {e}", file=sys.stderr)
            sys.exit(1)
        version_tag = target
        version = version_tag.lstrip("v")
        stable_version = stable.lstrip("v")
        print(f"Allocated version: {version_tag} ({version}), base/stable: {stable_version}, sequence: {sequence}, release_id: {release_id}")

        idempotency_file.write_text(json.dumps({
            "version_tag": version_tag,
            "stable": stable,
            "sequence": sequence,
            "release_id": release_id
        }))

    from scripts.derive_version import get_github_releases
    for r in get_github_releases():
        if r["tag_name"] == version_tag and not r["prerelease"]:
            print(f"Error: Target version {version_tag} already exists as a non-prerelease Stable on GitHub.", file=sys.stderr)
            sys.exit(1)

    staging_base = staging_base / version
    staging_base.mkdir(parents=True, exist_ok=True)

    build_record_file = staging_base / "evidence" / "build-record.json"
    if build_record_file.exists():
        print(f"Build already completed for {version_tag}. Resuming split publish...")
        publish_dir = staging_base / "publish"
        installer_dir = staging_base / "installer"
        publish_split_release(
            tag=version_tag,
            commit=commit,
            machine_staging_dir=publish_dir,
            installer_staging_dir=installer_dir,
            installer_repo=installer_repo,
        )
        return

    # 4. Inject version
    init_py_path = source_dir / "launcher" / "src" / "neko_launcher" / "__init__.py"
    if init_py_path.exists():
        content = init_py_path.read_text(encoding="utf-8")
        import re
        matches = list(re.finditer(r'__version__\s*=\s*"([^"]+)"', content))
        if len(matches) != 1:
            print(f"Error: Expected exactly one __version__ in __init__.py, found {len(matches)}", file=sys.stderr)
            sys.exit(1)
        m = matches[0]
        found_version = m.group(1)
        if found_version != stable_version:
            if found_version != version:
                print(f"Error: Base version mismatch in __init__.py. Expected {stable_version}, found {found_version}", file=sys.stderr)
                sys.exit(1)
        else:
            content = content[:m.start(1)] + version + content[m.end(1):]
            init_py_path.write_text(content, encoding="utf-8")
    else:
        print("Error: __init__.py not found", file=sys.stderr)
        sys.exit(1)

    pyproject_path = source_dir / "launcher" / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        matches = list(re.finditer(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE))
        if len(matches) != 1:
            print(f"Error: Expected exactly one version in pyproject.toml, found {len(matches)}", file=sys.stderr)
            sys.exit(1)
        m = matches[0]
        found_version = m.group(1)
        if found_version != stable_version:
            if found_version != version:
                print(f"Error: Base version mismatch in pyproject.toml. Expected {stable_version}, found {found_version}", file=sys.stderr)
                sys.exit(1)
        else:
            content = content[:m.start(1)] + version + content[m.end(1):]
            pyproject_path.write_text(content, encoding="utf-8")
    else:
        print("Error: pyproject.toml not found", file=sys.stderr)
        sys.exit(1)

    # 5. Build Launcher/Updater
    env = os.environ.copy()
    subprocess.run(["uv", "run", "--extra", "release", "pyinstaller", "NekoLauncher.spec"], cwd=str(source_dir / "launcher"), check=True, env=env)
    subprocess.run(["uv", "run", "--extra", "release", "pyinstaller", "NekoUpdater.spec"], cwd=str(source_dir / "launcher"), check=True, env=env)

    # 6. Core from signed authority
    core_zip, core_hash, core_size, installed_identity, core_provenance = verify_and_fetch_core(
        stable,
        staging_base / "evidence" / "core_authority",
        bootstrap_authority_dir=bootstrap_authority_dir,
    )

    publish_dir = staging_base / "publish"
    publish_dir.mkdir(exist_ok=True)

    final_core_zip = publish_dir / "NekoProxyCore.zip"
    shutil.copy(core_zip, final_core_zip)

    launcher_dist = source_dir / "launcher" / "dist" / "NekoLauncher.exe"
    updater_dist = source_dir / "launcher" / "dist" / "NekoUpdater.exe"

    final_launcher_exe = publish_dir / "NekoLauncher.exe"
    final_updater_exe = publish_dir / "NekoUpdater.exe"
    shutil.copy(launcher_dist, final_launcher_exe)
    shutil.copy(updater_dist, final_updater_exe)

    launcher_hash = _get_sha256(final_launcher_exe)
    updater_hash = _get_sha256(final_updater_exe)

    payload_dir = staging_base / "payload"
    payload_dir.mkdir(exist_ok=True)

    prereqs_dir = payload_dir / "Prereqs"
    prereqs_dir.mkdir(exist_ok=True)

    dotnet_src = Path("E:/Github/artifacts/v5.1.0-one-click-installer/payload/Prereqs/windowsdesktop-runtime-6.0.36-win-x64.exe")
    expected_dotnet_sha = "0d20debb26fc8b2bc84f25fbd9d4596a6364af8517ebf012e8b871127b798941"
    if _get_sha256(dotnet_src) != expected_dotnet_sha:
        raise RuntimeError(".NET runtime source SHA mismatch.")
    shutil.copy(dotnet_src, prereqs_dir / dotnet_src.name)

    setup_out = staging_base / "out"
    setup_out.mkdir(exist_ok=True)

    with zipfile.ZipFile(core_zip) as z:
        core_json = json.loads(z.read("core-manifest.json").decode("utf-8"))
        core_source_commit = core_json.get("source_commit")

        core_bundle_dir = payload_dir / "CoreBundle"
        core_bundle_dir.mkdir(parents=True, exist_ok=True)
        z.extractall(core_bundle_dir)

    print("Building Setup...")
    subprocess.run([
        sys.executable,
        str(source_dir / "installer" / "scripts" / "build_beta_installer.py"),
        "--candidate-dir", str(staging_base),
        "--launcher-sha256", launcher_hash,
        "--updater-sha256", updater_hash,
        "--core-authority", core_source_commit,
        "--release-version", version
    ], check=True)

    setup_exe = setup_out / "NekoFamilyProxy-Setup.exe"
    if not setup_exe.is_file():
        raise RuntimeError("Setup binary was not produced by installer compiler")

    installer_dir = staging_base / "installer"
    installer_dir.mkdir(exist_ok=True)
    final_installer_exe = installer_dir / "NekoFamilyProxy-Installer.exe"
    shutil.copy2(setup_exe, final_installer_exe)

    installer_hash = _get_sha256(final_installer_exe)
    setup_hash = _get_sha256(setup_exe)
    if installer_hash != setup_hash or final_installer_exe.stat().st_size != setup_exe.stat().st_size:
        raise RuntimeError("Installer binary byte copy verification mismatch")

    # 8. Generate release-v2.json base metadata
    metadata = {
        "schema_version": 2,
        "channel": "stable",
        "release_sequence": sequence,
        "release_id": release_id,
        "mandatory": False,
        "minimum_supported_sequence": 1,
        "updater_protocol": {"minimum": 1, "maximum": 1},
        "components": {
            "launcher": {
                "version": version,
                "artifact_id": "NekoLauncher.exe",
                "artifact_sha256": launcher_hash,
                "artifact_size": final_launcher_exe.stat().st_size,
                "installed_identity_sha256": launcher_hash,
                "artifact_format": "raw-pe-v1"
            },
            "updater": {
                "version": version,
                "artifact_id": "NekoUpdater.exe",
                "artifact_sha256": updater_hash,
                "artifact_size": final_updater_exe.stat().st_size,
                "installed_identity_sha256": updater_hash,
                "artifact_format": "raw-pe-v1"
            },
            "core": {
                "version": version,
                "artifact_id": "NekoProxyCore.zip",
                "artifact_sha256": core_hash,
                "artifact_size": core_size,
                "installed_identity_sha256": installed_identity,
                "artifact_format": "zip-core-v1"
            }
        }
    }

    evidence_dir = staging_base / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    metadata_path = evidence_dir / "base-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # 9. Sign software release
    sign_script = source_dir / "scripts" / "build_software_release_v2.py"
    release_json_out = publish_dir / "release-v2.json"

    prod_key_path = "C:/Users/Pranmong/AppData/Local/NekoFamily/release-custody/neko-update-prod-1.pem"
    prod_key_id = "neko-update-prod-1"

    # Create trusted public key file for the builder
    from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS
    pub_key_path = staging_base / f"{prod_key_id}.pub"
    pub_key_path.write_bytes(PRODUCTION_RELEASE_PUBLIC_KEYS[prod_key_id])

    print("Signing release...")
    cmd = [
        sys.executable,
        str(sign_script),
        "--input", str(metadata_path),
        "--launcher-artifact", str(final_launcher_exe),
        "--updater-artifact", str(final_updater_exe),
        "--core-artifact", str(final_core_zip),
        "--private-key-file", prod_key_path,
        "--key-id", prod_key_id,
        "--public-key-file", str(pub_key_path),
        "--output", str(release_json_out)
    ]
    subprocess.run(cmd, check=True)

    # 10. Split publish
    manifest_hash = _get_sha256(release_json_out)
    build_record = {
        "run_id": run_id,
        "source_commit": commit,
        "source_sha": commit,
        "version": version_tag,
        "stable_version": stable_version,
        "target_version": version,
        "injected_files": ["launcher/src/neko_launcher/__init__.py", "launcher/pyproject.toml"],
        "sequence": sequence,
        "release_id": release_id,
        "core_authority": core_provenance,
        "machine_assets": {
            "launcher": {"name": "NekoLauncher.exe", "sha256": launcher_hash, "size": final_launcher_exe.stat().st_size},
            "updater": {"name": "NekoUpdater.exe", "sha256": updater_hash, "size": final_updater_exe.stat().st_size},
            "core": {"name": "NekoProxyCore.zip", "sha256": core_hash, "size": final_core_zip.stat().st_size},
            "manifest": {"name": "release-v2.json", "sha256": manifest_hash, "size": release_json_out.stat().st_size},
        },
        "installer_asset": {
            "name": "NekoFamilyProxy-Installer.exe",
            "sha256": installer_hash,
            "size": final_installer_exe.stat().st_size,
        },
        "destination_repositories": {
            "machine": CANONICAL_REPO,
            "installer": installer_repo,
        },
        "assets": {
            "launcher": {"sha256": launcher_hash, "size": final_launcher_exe.stat().st_size},
            "updater": {"sha256": updater_hash, "size": final_updater_exe.stat().st_size},
            "core": {"sha256": core_hash, "size": final_core_zip.stat().st_size},
            "installer": {"sha256": installer_hash, "size": final_installer_exe.stat().st_size},
            "manifest": {"sha256": manifest_hash, "size": release_json_out.stat().st_size},
        },
    }
    (evidence_dir / "build-record.json").write_text(json.dumps(build_record, indent=2))

    print("Publishing split release...")
    publish_split_release(
        tag=version_tag,
        commit=commit,
        machine_staging_dir=publish_dir,
        installer_staging_dir=installer_dir,
        installer_repo=installer_repo,
    )


def main():
    parser = argparse.ArgumentParser(description="Main Auto Release Controller")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument(
        "--installer-repo",
        default=None,
        help="Explicit target repository for human installer releases (mandatory, no silent fallback to canonical repo)",
    )
    parser.add_argument(
        "--bootstrap-authority-dir",
        type=Path,
        default=None,
        help="Explicit bounded local bootstrap authority directory for first machine release",
    )
    args = parser.parse_args()

    process_accepted_commits(
        args.commit,
        args.run_id,
        installer_repo=args.installer_repo,
        bootstrap_authority_dir=args.bootstrap_authority_dir,
    )

if __name__ == "__main__":
    main()
