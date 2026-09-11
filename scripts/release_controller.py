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

from scripts.kanban_release_adapter import get_successful_main_runs  # noqa: E402
from scripts.derive_version import get_github_releases, get_next_patch, get_release_sequence, get_release_id  # noqa: E402
from scripts.ci_change_classifier import should_trigger  # noqa: E402

from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2  # noqa: E402
from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS  # noqa: E402

def _get_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().lower()

def verify_and_fetch_core() -> tuple[Path, str, int, str]:
    print("Fetching and verifying v5.1.2 Core authority...")

    from neko_launcher.updater.core_manifest_verifier import verify_canonical_core_bundle
    from neko_launcher.updater.zip_extractor import extract_core_bundle

    cmd = ["gh", "release", "view", "v5.1.2", "--json", "assets"]
    out = subprocess.check_output(cmd)
    assets = json.loads(out)["assets"]

    release_json_url = next(a["url"] for a in assets if a["name"] == "release-v2.json")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        release_json_path = tmp_dir / "release-v2.json"
        subprocess.run(["curl", "-sSL", "-o", str(release_json_path), release_json_url], check=True)

        manifest_doc = json.loads(release_json_path.read_text(encoding="utf-8"))

        pub_keys = {"neko-update-prod-1": PRODUCTION_RELEASE_PUBLIC_KEYS["neko-update-prod-1"]}
        release_set, _ = verify_release_envelope_v2(manifest_doc, pub_keys)

        core_comp = release_set.components["core"]
        expected_hash = core_comp.artifact_sha256.lower()
        expected_size = core_comp.artifact_size
        installed_identity = core_comp.installed_identity_sha256.lower()

    local_zip = Path("E:/Github/artifacts/v5.1.3-one-click-installer/NekoProxyCore.zip")
    if not local_zip.exists():
        raise RuntimeError("Local Core zip missing.")

    actual_size = local_zip.stat().st_size
    actual_hash = _get_sha256(local_zip)

    if actual_size != expected_size or actual_hash != expected_hash:
        raise RuntimeError("Local Core zip does not match v5.1.2 signature.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        extract_core_bundle(local_zip, tmp_dir)
        verification = verify_canonical_core_bundle(tmp_dir)
        if not verification.valid:
            raise RuntimeError(f"Core bundle verification failed: {verification.error}")
        if verification.manifest_sha256 != installed_identity:
            raise RuntimeError("Core manifest installed identity mismatch inside zip.")

    print("v5.1.2 Core verified successfully.")
    return local_zip, actual_hash, actual_size, installed_identity

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

    idempotency_file = staging_base / "idempotency_record.json"
    if idempotency_file.exists():
        record = json.loads(idempotency_file.read_text(encoding="utf-8"))
        version_tag = record["version_tag"]
        version = version_tag.lstrip("v")
        sequence = record["sequence"]
        release_id = record["release_id"]
        print(f"Resuming idempotent run: {version_tag}")
    else:
        # 2. Version allocation
        releases = get_github_releases()
        version_tag = get_next_patch(releases)
        version = version_tag.lstrip("v")
        sequence = get_release_sequence(version_tag)
        release_id = get_release_id(sequence)
        print(f"Allocated version: {version_tag} ({version}), sequence: {sequence}, release_id: {release_id}")

        idempotency_file.write_text(json.dumps({
            "version_tag": version_tag,
            "sequence": sequence,
            "release_id": release_id
        }))

    staging_base = staging_base / version
    staging_base.mkdir(parents=True, exist_ok=True)

    source_dir = staging_base / "source"

    # 3. Build from isolated exact-SHA workspace
    if not source_dir.exists():
        source_dir.mkdir(parents=True)
        tar_path = staging_base / "source.tar"
        subprocess.run(["git", "-C", str(repo_root), "archive", "--format=tar", "-o", str(tar_path), commit], check=True)
        subprocess.run(["tar", "-xf", str(tar_path), "-C", str(source_dir)], check=True)
        tar_path.unlink()

    # 4. Inject version
    init_py_path = source_dir / "launcher" / "src" / "neko_launcher" / "__init__.py"
    if init_py_path.exists():
        content = init_py_path.read_text(encoding="utf-8")
        import re
        content = re.sub(r'__version__\s*=\s*".*?"', f'__version__ = "{version}"', content)
        init_py_path.write_text(content, encoding="utf-8")

    # 5. Build Launcher/Updater
    env = os.environ.copy()
    subprocess.run(["uv", "run", "--extra", "release", "pyinstaller", "NekoLauncher.spec"], cwd=str(source_dir / "launcher"), check=True, env=env)
    subprocess.run(["uv", "run", "--extra", "release", "pyinstaller", "NekoUpdater.spec"], cwd=str(source_dir / "launcher"), check=True, env=env)

    # 6. Core from v5.1.2 signed authority
    core_zip, core_hash, core_size, installed_identity = verify_and_fetch_core()

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

    dotnet_src = Path("E:/Github/artifacts/v5.1.3-one-click-installer/payload/Prereqs/windowsdesktop-runtime-6.0.36-win-x64.exe")
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

    metadata_path = staging_base / "base-metadata.json"
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
        "sequence": sequence,
        "release_id": release_id,
        "assets": {
            "launcher": launcher_hash,
            "updater": updater_hash,
            "core": core_hash,
            "setup": _get_sha256(final_setup_exe),
            "manifest": _get_sha256(release_json_out)
        }
    }
    (staging_base / "build-record.json").write_text(json.dumps(build_record, indent=2))

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