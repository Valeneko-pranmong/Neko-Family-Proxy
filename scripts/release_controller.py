import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# Add project root to sys.path so we can import internal modules
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2  # noqa: E402
from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS  # noqa: E402

from scripts.ci_change_classifier import should_trigger  # noqa: E402
from scripts.kanban_release_adapter import get_successful_main_runs  # noqa: E402


def _get_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().lower()

def verify_and_fetch_core(stable_tag: str, staging_dir: Path) -> tuple[Path, str, int, str, dict]:
    print(f"Fetching and verifying {stable_tag} Core authority...")

    from neko_launcher.updater.core_manifest_verifier import (
        verify_canonical_core_bundle,
    )
    from neko_launcher.updater.zip_extractor import extract_core_bundle

    # 1. Query GitHub release by exact stable tag
    cmd = ["gh", "api", f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/tags/{stable_tag}"]
    try:
        out = subprocess.check_output(cmd)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to fetch release {stable_tag}: {e}")

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
    staging_dir.mkdir(parents=True, exist_ok=True)
    release_json_path = staging_dir / "release-v2.json"
    core_zip_path = staging_dir / "NekoProxyCore.zip"

    subprocess.run([
        "gh", "api",
        f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/assets/{manifest_asset_id}",
        "-H", "Accept: application/octet-stream"
    ], stdout=release_json_path.open('wb'), check=True)

    subprocess.run([
        "gh", "api",
        f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/assets/{core_asset_id}",
        "-H", "Accept: application/octet-stream"
    ], stdout=core_zip_path.open('wb'), check=True)

    manifest_doc = json.loads(release_json_path.read_text(encoding="utf-8"))
    pub_keys = {"neko-update-prod-1": PRODUCTION_RELEASE_PUBLIC_KEYS["neko-update-prod-1"]}
    release_set, _ = verify_release_envelope_v2(manifest_doc, pub_keys)

    # 6. Require channel stable and that Core component artifact_id is NekoProxyCore.zip
    if release_set.channel != "stable":
        raise RuntimeError("Release manifest channel is not stable.")

    if "core" not in release_set.components:
        raise RuntimeError("Core component missing from release manifest.")

    core_comp = release_set.components["core"]
    if core_comp.artifact_id != "NekoProxyCore.zip":
        raise RuntimeError(f"Core artifact_id mismatch: {core_comp.artifact_id}")

    expected_hash = core_comp.artifact_sha256.lower()
    expected_size = core_comp.artifact_size
    installed_identity = core_comp.installed_identity_sha256.lower()

    # 7. Compare downloaded Core SHA256+size to signed component
    actual_size = core_zip_path.stat().st_size
    actual_hash = _get_sha256(core_zip_path)

    if actual_size != expected_size or actual_hash != expected_hash:
        raise RuntimeError(f"Downloaded Core zip does not match {stable_tag} signature.")

    # 8. Run canonical Core bundle verifier + installed identity check
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        extract_core_bundle(core_zip_path, tmp_dir)
        verification = verify_canonical_core_bundle(tmp_dir)
        if not verification.valid:
            raise RuntimeError(f"Core bundle verification failed: {verification.error}")
        if verification.manifest_sha256 != installed_identity:
            raise RuntimeError("Core manifest installed identity mismatch inside zip.")

    print(f"{stable_tag} Core verified successfully.")

    provenance = {
        "stable_tag": stable_tag,
        "release_id": release_id,
        "manifest_asset_id": manifest_asset_id,
        "core_asset_id": core_asset_id
    }

    return core_zip_path, actual_hash, actual_size, installed_identity, provenance

def process_accepted_commits(commit: str, run_id: int):
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

    repo_root = Path(__file__).resolve().parent.parent

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
        print(f"Build already completed for {version_tag}. Resuming publish...")
        publish_dir = staging_base / "publish"
        from scripts.publish_atomic_release import execute_publish
        execute_publish(version_tag, commit, staging_dir=str(publish_dir))
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
    core_zip, core_hash, core_size, installed_identity, core_provenance = verify_and_fetch_core(stable, staging_base / "evidence" / "core_authority")

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
    final_setup_exe = publish_dir / "NekoFamilyProxy-Setup.exe"
    shutil.copy(setup_exe, final_setup_exe)

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

    # 10. Atomic publish
    from scripts.publish_atomic_release import execute_publish

    build_record = {
        "run_id": run_id,
        "source_commit": commit,
        "version": version_tag,
        "stable_version": stable_version,
        "target_version": version,
        "injected_files": ["launcher/src/neko_launcher/__init__.py", "launcher/pyproject.toml"],
        "sequence": sequence,
        "release_id": release_id,
        "core_authority": core_provenance,
        "assets": {
            "launcher": {"sha256": launcher_hash, "size": final_launcher_exe.stat().st_size},
            "updater": {"sha256": updater_hash, "size": final_updater_exe.stat().st_size},
            "core": {"sha256": core_hash, "size": final_core_zip.stat().st_size},
            "setup": {"sha256": _get_sha256(final_setup_exe), "size": final_setup_exe.stat().st_size},
            "manifest": {"sha256": _get_sha256(release_json_out), "size": release_json_out.stat().st_size}
        }
    }
    (evidence_dir / "build-record.json").write_text(json.dumps(build_record, indent=2))

    print("Publishing release...")
    execute_publish(version_tag, commit, staging_dir=str(publish_dir))


def main():
    parser = argparse.ArgumentParser(description="Main Auto Release Controller")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    args = parser.parse_args()

    process_accepted_commits(args.commit, args.run_id)

if __name__ == "__main__":
    main()