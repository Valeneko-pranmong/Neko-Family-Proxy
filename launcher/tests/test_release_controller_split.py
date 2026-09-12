from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.publish_atomic_release import (  # noqa: E402
    CANONICAL_REPO,
    REQUIRED_STAGE_ASSETS,
    StageDraftReleaseError,
    StagedDraftEvidence,
)
from scripts.publish_installer_release import (  # noqa: E402
    InstallerPublishError,
    REQUIRED_INSTALLER_ASSET,
    StagedInstallerDraftEvidence,
)
from scripts.release_controller import (  # noqa: E402
    process_accepted_commits,
    publish_split_release,
    validate_installer_repo_configuration,
)


def _make_clean_git_executor(tag: str, sha: str, *, custom_handler=None):
    class CleanGitExecutor:
        def run(self, args: list[str], capture_output: bool = True):
            if custom_handler:
                res = custom_handler(args)
                if res is not None:
                    return res
            if args[:2] == ["git", "-C"]:
                if "status" in args:
                    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
                if "rev-parse" in args:
                    return subprocess.CompletedProcess(args, 0, stdout=f"{sha}\n", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    return CleanGitExecutor()


def test_validate_installer_repo_rejects_none_and_empty():
    with pytest.raises(ValueError, match="[Ee]xplicit installer repository.*mandatory.*no silent fallback"):
        validate_installer_repo_configuration(None)

    with pytest.raises(ValueError, match="[Ee]xplicit installer repository.*mandatory.*no silent fallback"):
        validate_installer_repo_configuration("")

    with pytest.raises(ValueError, match="[Ee]xplicit installer repository.*mandatory.*no silent fallback"):
        validate_installer_repo_configuration("   ")


def test_validate_installer_repo_rejects_canonical_machine_repo():
    canonical = "Valeneko-pranmong/Neko-Family-Proxy"
    with pytest.raises(ValueError, match="[Cc]annot be the canonical machine repository"):
        validate_installer_repo_configuration(canonical)

    with pytest.raises(ValueError, match="[Cc]annot be the canonical machine repository"):
        validate_installer_repo_configuration(f"https://github.com/{canonical}.git")


def test_validate_installer_repo_accepts_valid_installer_repo():
    repo = "Valeneko-pranmong/Neko-Family-Proxy-Installer"
    cleaned = validate_installer_repo_configuration(repo)
    assert cleaned == repo

    cleaned_spaced = validate_installer_repo_configuration(f"  {repo}  ")
    assert cleaned_spaced == repo


def test_publish_split_release_rejects_setup_in_machine_dir(tmp_path):
    sha = "a" * 40
    tag = "v5.1.1"
    machine_dir = tmp_path / "machine"
    machine_dir.mkdir()
    for name in REQUIRED_STAGE_ASSETS:
        (machine_dir / name).write_bytes(b"content")
    # Add forbidden Setup file into machine dir
    (machine_dir / "NekoFamilyProxy-Setup.exe").write_bytes(b"forbidden_setup")

    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()
    (installer_dir / REQUIRED_INSTALLER_ASSET).write_bytes(b"installer_content")

    executor = _make_clean_git_executor(tag, sha)

    with pytest.raises(StageDraftReleaseError, match="(?i)(extra|forbidden|four required machine assets)"):
        publish_split_release(
            tag=tag,
            commit=sha,
            machine_staging_dir=machine_dir,
            installer_staging_dir=installer_dir,
            installer_repo="Valeneko-pranmong/Neko-Family-Proxy-Installer",
            executor=executor,
        )


def test_publish_split_release_rejects_missing_or_extra_installer(monkeypatch, tmp_path):
    sha = "a" * 40
    tag = "v5.1.1"
    machine_dir = tmp_path / "machine"
    machine_dir.mkdir()
    for name in REQUIRED_STAGE_ASSETS:
        (machine_dir / name).write_bytes(b"content")

    # Bypass manifest validation inside validate_staging_preconditions for unit test of installer check
    monkeypatch.setattr("scripts.release_controller.validate_staging_preconditions", lambda *a, **k: {})

    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()
    # Missing REQUIRED_INSTALLER_ASSET

    executor = _make_clean_git_executor(tag, sha)

    with pytest.raises(InstallerPublishError, match="(?i)(missing required installer asset|exactly one)"):
        publish_split_release(
            tag=tag,
            commit=sha,
            machine_staging_dir=machine_dir,
            installer_staging_dir=installer_dir,
            installer_repo="Valeneko-pranmong/Neko-Family-Proxy-Installer",
            executor=executor,
        )

    # Extra asset in installer dir
    (installer_dir / REQUIRED_INSTALLER_ASSET).write_bytes(b"installer")
    (installer_dir / "extra.zip").write_bytes(b"extra")

    with pytest.raises(InstallerPublishError, match="(?i)(exactly one custom installer asset|extra)"):
        publish_split_release(
            tag=tag,
            commit=sha,
            machine_staging_dir=machine_dir,
            installer_staging_dir=installer_dir,
            installer_repo="Valeneko-pranmong/Neko-Family-Proxy-Installer",
            executor=executor,
        )


def test_publish_split_release_order_and_cutover(monkeypatch, tmp_path):
    tag = "v5.1.1"
    sha = "3" * 40
    installer_repo = "Valeneko-pranmong/Neko-Family-Proxy-Installer"

    machine_dir = tmp_path / "machine"
    machine_dir.mkdir()
    for name in REQUIRED_STAGE_ASSETS:
        (machine_dir / name).write_bytes(f"{name}-content".encode())

    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()
    (installer_dir / REQUIRED_INSTALLER_ASSET).write_bytes(b"installer-binary")

    monkeypatch.setattr("scripts.release_controller.validate_staging_preconditions", lambda *a, **k: {})
    monkeypatch.setattr("scripts.release_controller.validate_installer_staging_preconditions", lambda *a, **k: (installer_dir / REQUIRED_INSTALLER_ASSET, "sha", 10))

    events: list[str] = []

    # Mock stage_draft_release (machine)
    def mock_stage_draft_release(*args, **kwargs):
        events.append("stage_machine_draft")
        return StagedDraftEvidence(
            release_id=101,
            tag_name=tag,
            target_commit=sha,
            assets={name: idx for idx, name in enumerate(REQUIRED_STAGE_ASSETS, start=1)},
            dispatch_command="dispatch-cmd",
        )

    # Mock stage_installer_draft_release (installer)
    def mock_stage_installer_draft(*args, **kwargs):
        events.append("stage_installer_draft")
        assert kwargs.get("installer_repo") == installer_repo
        return StagedInstallerDraftEvidence(
            release_id=202,
            tag_name=tag,
            target_commit=sha,
            repo=installer_repo,
            installer_asset_id=999,
            installer_size=len(b"installer-binary"),
            installer_sha256=hashlib.sha256(b"installer-binary").hexdigest(),
            dispatch_command="dispatch-installer-cmd",
        )

    monkeypatch.setattr("scripts.release_controller.stage_draft_release", mock_stage_draft_release)
    monkeypatch.setattr("scripts.release_controller.stage_installer_draft_release", mock_stage_installer_draft)

    # Mock hosted verifiers
    def mock_verify_machine_hosted(evidence, staging_dir, expected_tag, expected_target, runner):
        events.append("verify_machine_hosted")

    def mock_verify_installer_hosted(evidence, staging_dir, expected_tag, expected_target, repo, runner):
        events.append("verify_installer_hosted")

    monkeypatch.setattr("scripts.release_controller._hosted_verify_machine_channel", mock_verify_machine_hosted)
    monkeypatch.setattr("scripts.release_controller._hosted_verify_installer_channel", mock_verify_installer_hosted)

    executed_cmds: list[list[str]] = []

    def custom_handler(args: list[str]):
        executed_cmds.append(args)
        if "release" in args and "edit" in args and "--draft=false" in args:
            if installer_repo in args:
                events.append("promote_installer_first")
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            elif CANONICAL_REPO in args:
                events.append("promote_machine_second")
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if "releases/latest" in "".join(args):
            events.append("verify_latest_resolution")
            latest_data = {
                "id": 101,
                "tag_name": tag,
                "assets": [
                    {"name": name, "id": idx, "size": len(f"{name}-content".encode())}
                    for idx, name in enumerate(REQUIRED_STAGE_ASSETS, start=1)
                ]
            }
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(latest_data), stderr="")
        if "api" in args and f"repos/{installer_repo}/releases/202" in "".join(args):
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"draft": False}), stderr="")
        if "api" in args and f"repos/{CANONICAL_REPO}/releases/101" in "".join(args):
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"draft": False}), stderr="")
        return None

    executor = _make_clean_git_executor(tag, sha, custom_handler=custom_handler)
    publish_split_release(
        tag=tag,
        commit=sha,
        machine_staging_dir=machine_dir,
        installer_staging_dir=installer_dir,
        installer_repo=installer_repo,
        executor=executor,
    )

    # Check the required order:
    # 1. stage_machine_draft
    # 2. stage_installer_draft
    # 3. verify_machine_hosted
    # 4. verify_installer_hosted
    # 5. promote_installer_first
    # 6. promote_machine_second
    # 7. verify_latest_resolution
    assert events == [
        "stage_machine_draft",
        "stage_installer_draft",
        "verify_machine_hosted",
        "verify_installer_hosted",
        "promote_installer_first",
        "promote_machine_second",
        "verify_latest_resolution",
    ]


def test_publish_split_release_installer_failure_stops_machine_cutover(monkeypatch, tmp_path):
    tag = "v5.1.1"
    sha = "4" * 40
    installer_repo = "Valeneko-pranmong/Neko-Family-Proxy-Installer"

    machine_dir = tmp_path / "machine"
    machine_dir.mkdir()
    for name in REQUIRED_STAGE_ASSETS:
        (machine_dir / name).write_bytes(b"content")

    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()
    (installer_dir / REQUIRED_INSTALLER_ASSET).write_bytes(b"installer-binary")

    monkeypatch.setattr("scripts.release_controller.validate_staging_preconditions", lambda *a, **k: {})
    monkeypatch.setattr("scripts.release_controller.validate_installer_staging_preconditions", lambda *a, **k: (installer_dir / REQUIRED_INSTALLER_ASSET, "sha", 10))

    events: list[str] = []

    monkeypatch.setattr(
        "scripts.release_controller.stage_draft_release",
        lambda *a, **kw: StagedDraftEvidence(101, tag, sha, {}, "cmd"),
    )
    def failing_stage_installer(*a, **kw):
        events.append("stage_installer_failed")
        raise InstallerPublishError("Installer draft upload failed")

    monkeypatch.setattr("scripts.release_controller.stage_installer_draft_release", failing_stage_installer)

    def custom_handler(args: list[str]):
        if "edit" in args and "--draft=false" in args:
            events.append("unexpected_promotion")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    executor = _make_clean_git_executor(tag, sha, custom_handler=custom_handler)

    with pytest.raises(InstallerPublishError, match="Installer draft upload failed"):
        publish_split_release(
            tag=tag,
            commit=sha,
            machine_staging_dir=machine_dir,
            installer_staging_dir=installer_dir,
            installer_repo=installer_repo,
            executor=executor,
        )

    assert "unexpected_promotion" not in events


def test_publish_split_release_installer_verify_failure_stops_cutover(monkeypatch, tmp_path):
    tag = "v5.1.1"
    sha = "5" * 40
    installer_repo = "Valeneko-pranmong/Neko-Family-Proxy-Installer"

    machine_dir = tmp_path / "machine"
    machine_dir.mkdir()
    for name in REQUIRED_STAGE_ASSETS:
        (machine_dir / name).write_bytes(b"content")

    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()
    (installer_dir / REQUIRED_INSTALLER_ASSET).write_bytes(b"installer-binary")

    monkeypatch.setattr("scripts.release_controller.validate_staging_preconditions", lambda *a, **k: {})
    monkeypatch.setattr("scripts.release_controller.validate_installer_staging_preconditions", lambda *a, **k: (installer_dir / REQUIRED_INSTALLER_ASSET, "sha", 10))

    events: list[str] = []

    monkeypatch.setattr(
        "scripts.release_controller.stage_draft_release",
        lambda *a, **kw: StagedDraftEvidence(101, tag, sha, {}, "cmd"),
    )
    monkeypatch.setattr(
        "scripts.release_controller.stage_installer_draft_release",
        lambda *a, **kw: StagedInstallerDraftEvidence(202, tag, sha, installer_repo, 999, 10, "sha", "cmd"),
    )
    monkeypatch.setattr("scripts.release_controller._hosted_verify_machine_channel", lambda *a, **kw: None)

    def failing_installer_verify(*a, **kw):
        events.append("installer_verify_failed")
        raise RuntimeError("Hosted installer verification failed: digest mismatch")

    monkeypatch.setattr("scripts.release_controller._hosted_verify_installer_channel", failing_installer_verify)

    def custom_handler(args: list[str]):
        if "edit" in args and "--draft=false" in args:
            events.append("unexpected_promotion")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    executor = _make_clean_git_executor(tag, sha, custom_handler=custom_handler)

    with pytest.raises(RuntimeError, match="Hosted installer verification failed"):
        publish_split_release(
            tag=tag,
            commit=sha,
            machine_staging_dir=machine_dir,
            installer_staging_dir=installer_dir,
            installer_repo=installer_repo,
            executor=executor,
        )

    assert "unexpected_promotion" not in events
    assert "installer_verify_failed" in events


def test_process_accepted_commits_requires_installer_repo(monkeypatch):
    monkeypatch.setattr(
        "scripts.release_controller.get_successful_main_runs",
        lambda: [{"databaseId": 1, "headSha": "a" * 40}],
    )
    # When installer_repo is omitted / None
    with pytest.raises((ValueError, SystemExit)):
        process_accepted_commits("a" * 40, 1, installer_repo=None)

    # When installer_repo is canonical machine repo
    with pytest.raises((ValueError, SystemExit)):
        process_accepted_commits("a" * 40, 1, installer_repo=CANONICAL_REPO)


def test_process_accepted_commits_split_build_and_provenance(monkeypatch, tmp_path):
    sha = "7" * 40
    run_id = 99999
    installer_repo = "Valeneko-pranmong/Neko-Family-Proxy-Installer"

    staging_base = Path(f"E:/Github/artifacts/main-auto-release/{run_id}-{sha}")
    import shutil
    shutil.rmtree(staging_base, ignore_errors=True)

    monkeypatch.setattr(
        "scripts.release_controller.get_successful_main_runs",
        lambda: [{"databaseId": run_id, "headSha": sha}],
    )
    monkeypatch.setattr(
        "scripts.derive_version.get_armed_target_from_dir",
        lambda *args, **kwargs: ("v5.1.0", "v5.1.1", 5, "stable-0005"),
    )
    monkeypatch.setattr("scripts.derive_version.get_github_releases", lambda: [])
    monkeypatch.setattr("scripts.release_controller.should_trigger", lambda f: True)

    fake_core = tmp_path / "fake_core.zip"
    fake_core.write_bytes(b"core-zip-bytes")
    fake_dotnet = tmp_path / "windowsdesktop-runtime-6.0.36-win-x64.exe"
    fake_dotnet.write_bytes(b"dotnet")

    monkeypatch.setattr(
        "scripts.release_controller.verify_and_fetch_core",
        lambda *a, **k: (
            fake_core,
            hashlib.sha256(b"core-zip-bytes").hexdigest(),
            len(b"core-zip-bytes"),
            "core-installed-id",
            {"source": "provenance-test"},
        ),
    )

    fake_setup_bytes = b"inno-setup-installer-binary-12345"

    def fake_run(args, **kwargs):
        if args[0] == "git" and "merge-base" in args:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "git" and "archive" in args:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "tar":
            # Populate fake extracted source
            s_dir = staging_base / "source"
            (s_dir / "launcher" / "src" / "neko_launcher").mkdir(parents=True, exist_ok=True)
            (s_dir / "launcher" / "src" / "neko_launcher" / "__init__.py").write_text('__version__ = "5.1.0"\n')
            (s_dir / "launcher" / "pyproject.toml").write_text('version = "5.1.0"\n')
            (s_dir / "launcher" / "dist").mkdir(parents=True, exist_ok=True)
            (s_dir / "launcher" / "dist" / "NekoLauncher.exe").write_bytes(b"launcher-exe")
            (s_dir / "launcher" / "dist" / "NekoUpdater.exe").write_bytes(b"updater-exe")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "uv":
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if "build_beta_installer.py" in str(args[1]):
            out_dir = staging_base / "5.1.1" / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "NekoFamilyProxy-Setup.exe").write_bytes(fake_setup_bytes)
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if "build_software_release_v2.py" in str(args[1]):
            out_idx = args.index("--output")
            Path(args[out_idx + 1]).write_bytes(b'{"envelope_version": 1}')
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def fake_check_output(args, **kwargs):
        if args[0] == "git" and "show" in args:
            return "src/launcher.py\n"
        return ""

    monkeypatch.setattr("scripts.release_controller.subprocess.run", fake_run)
    monkeypatch.setattr("scripts.release_controller.subprocess.check_output", fake_check_output)

    # Patch dotnet path & sha
    monkeypatch.setattr(
        "scripts.release_controller._get_sha256",
        lambda p: "0d20debb26fc8b2bc84f25fbd9d4596a6364af8517ebf012e8b871127b798941"
        if "windowsdesktop" in str(p)
        else hashlib.sha256(Path(p).read_bytes()).hexdigest(),
    )

    class FakeZip:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, name): return b'{"source_commit": "core-commit"}'
        def extractall(self, path): pass
    monkeypatch.setattr("scripts.release_controller.zipfile.ZipFile", FakeZip)

    split_publish_calls = []
    monkeypatch.setattr(
        "scripts.release_controller.publish_split_release",
        lambda **kwargs: split_publish_calls.append(kwargs),
    )

    process_accepted_commits(sha, run_id, installer_repo=installer_repo)

    # 1. Verify split_publish was called once with exact arguments
    assert len(split_publish_calls) == 1
    call = split_publish_calls[0]
    assert call["tag"] == "v5.1.1"
    assert call["commit"] == sha
    assert call["installer_repo"] == installer_repo

    # 2. Verify machine publish directory contains EXACTLY the 4 machine assets and NO installer/setup
    m_dir = Path(call["machine_staging_dir"])
    machine_files = sorted([f.name for f in m_dir.iterdir()])
    assert machine_files == sorted(list(REQUIRED_STAGE_ASSETS))
    assert "NekoFamilyProxy-Setup.exe" not in machine_files
    assert "NekoFamilyProxy-Installer.exe" not in machine_files

    # 3. Verify installer directory contains EXACTLY NekoFamilyProxy-Installer.exe with unmodified bytes
    i_dir = Path(call["installer_staging_dir"])
    installer_files = [f.name for f in i_dir.iterdir()]
    assert installer_files == [REQUIRED_INSTALLER_ASSET]
    installer_file = i_dir / REQUIRED_INSTALLER_ASSET
    assert installer_file.read_bytes() == fake_setup_bytes

    # 4. Verify build-record.json provenance
    record_file = staging_base / "5.1.1" / "evidence" / "build-record.json"
    assert record_file.is_file()
    record = json.loads(record_file.read_text(encoding="utf-8"))

    assert record["source_commit"] == sha
    assert record["source_sha"] == sha
    assert record["stable_version"] == "5.1.0"
    assert record["target_version"] == "5.1.1"
    assert record["version"] == "v5.1.1"
    assert "launcher/src/neko_launcher/__init__.py" in record["injected_files"]
    assert "launcher/pyproject.toml" in record["injected_files"]
    assert record["core_authority"] == {"source": "provenance-test"}

    assert set(record["machine_assets"].keys()) == {"launcher", "updater", "core", "manifest"}
    assert record["installer_asset"]["name"] == "NekoFamilyProxy-Installer.exe"
    assert record["installer_asset"]["sha256"] == hashlib.sha256(fake_setup_bytes).hexdigest()
    assert record["installer_asset"]["size"] == len(fake_setup_bytes)

    assert record["destination_repositories"]["machine"] == CANONICAL_REPO
    assert record["destination_repositories"]["installer"] == installer_repo
