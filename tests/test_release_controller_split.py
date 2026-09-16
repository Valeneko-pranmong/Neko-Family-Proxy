from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import pytest

from scripts.publish_atomic_release import (
    CANONICAL_MACHINE_REPO,
    REQUIRED_STAGE_ASSETS,
    StageDraftReleaseError,
    StagedDraftEvidence,
)
from scripts.release_controller import (
    InstallerPublishError,
    PreparedSupersessionResult,
    REQUIRED_INSTALLER_ASSET,
    StagedInstallerDraftEvidence,
    SupersedeSignedReleaseRequest,
    prepare_signed_release_supersession,
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
    canonical = CANONICAL_MACHINE_REPO
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

    monkeypatch.setattr("scripts.release_controller.validate_staging_preconditions", lambda *a, **k: {})

    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()

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

    def mock_stage_draft_release(*args, **kwargs):
        events.append("stage_machine_draft")
        return StagedDraftEvidence(
            release_id=101,
            tag_name=tag,
            target_commit=sha,
            assets={name: idx for idx, name in enumerate(REQUIRED_STAGE_ASSETS, start=1)},
            dispatch_command="dispatch-cmd",
        )

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
            elif CANONICAL_MACHINE_REPO in args:
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
        if "api" in args and f"repos/{CANONICAL_MACHINE_REPO}/releases/101" in "".join(args):
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


def test_process_accepted_commits_requires_installer_repo(monkeypatch, tmp_path):
    # Isolate the controller from this checkout's real release_target.json.
    monkeypatch.setattr(
        "scripts.release_controller.__file__",
        str(tmp_path / "scripts" / "release_controller.py"),
    )
    monkeypatch.setattr(
        "scripts.release_controller.get_successful_main_runs",
        lambda: [{"databaseId": 1, "headSha": "a" * 40}],
    )
    # When installer_repo is omitted / None
    with pytest.raises((ValueError, SystemExit)):
        process_accepted_commits("a" * 40, 1, installer_repo=None)

    # When installer_repo is canonical machine repo
    with pytest.raises((ValueError, SystemExit)):
        process_accepted_commits("a" * 40, 1, installer_repo=CANONICAL_MACHINE_REPO)


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
        lambda *args, **kwargs: ("v5.1.1", "v5.1.2", 8, "stable-0008"),
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
            {
                "authority_version_tag": "v5.1.2",
                "authority_release_sequence": 6,
                "authority_release_id": "stable-0006",
                "authority_payload_sha256": "p" * 64,
                "authority_envelope_sha256": "e" * 64,
                "authority_key_id": "neko-update-prod-1",
                "core_source_commit": "6ab94bb",
                "provenance_sha256": "pr" * 32,
            },
        ),
    )

    fake_setup_bytes = b"inno-setup-installer-binary-12345"
    installer_builder_args: list[str] = []

    def fake_run(args, **kwargs):
        if args[0] == "git" and "merge-base" in args:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "git" and "archive" in args:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "tar":
            s_dir = staging_base / "source"
            (s_dir / "launcher" / "src" / "neko_launcher").mkdir(parents=True, exist_ok=True)
            (s_dir / "launcher" / "src" / "neko_launcher" / "__init__.py").write_text('__version__ = "5.1.1"\n')
            (s_dir / "launcher" / "pyproject.toml").write_text('version = "5.1.1"\n')
            (s_dir / "launcher" / "dist").mkdir(parents=True, exist_ok=True)
            (s_dir / "launcher" / "dist" / "NekoLauncher.exe").write_bytes(b"launcher-exe")
            (s_dir / "launcher" / "dist" / "NekoUpdater.exe").write_bytes(b"updater-exe")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "uv":
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if "build_beta_installer.py" in str(args[1]):
            installer_builder_args.extend(args)
            out_dir = staging_base / "5.1.2" / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "NekoFamilyProxy-Setup.exe").write_bytes(fake_setup_bytes)
            # simulate installer builder staging baseline envelope
            baseline_dir = staging_base / "5.1.2" / "payload" / "baseline"
            baseline_dir.mkdir(parents=True, exist_ok=True)
            if "--baseline-envelope" in args:
                env_in = Path(args[args.index("--baseline-envelope") + 1])
                (baseline_dir / "release-v2.json").write_bytes(env_in.read_bytes())
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if "build_software_release_v2.py" in str(args[1]):
            import base64
            out_idx = args.index("--output")
            fake_env = {
                "envelope_version": 1,
                "key_id": "neko-update-prod-1",
                "payload_b64": base64.b64encode(b'{"schema_version": 2}').decode("ascii"),
                "signature_b64": base64.b64encode(b"s" * 64).decode("ascii"),
            }
            Path(args[out_idx + 1]).write_bytes(canonical_json_dumps(fake_env) + b"\n")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def fake_check_output(args, **kwargs):
        if args[0] == "git" and "show" in args:
            return "src/launcher.py\n"
        return ""

    monkeypatch.setattr("scripts.release_controller.subprocess.run", fake_run)
    monkeypatch.setattr("scripts.release_controller.subprocess.check_output", fake_check_output)

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

    assert len(split_publish_calls) == 1
    call = split_publish_calls[0]
    assert call["tag"] == "v5.1.2"
    assert call["commit"] == sha
    assert call["installer_repo"] == installer_repo

    m_dir = Path(call["machine_staging_dir"])
    machine_files = sorted([f.name for f in m_dir.iterdir()])
    assert machine_files == sorted(list(REQUIRED_STAGE_ASSETS))
    assert "NekoFamilyProxy-Setup.exe" not in machine_files
    assert "NekoFamilyProxy-Installer.exe" not in machine_files

    i_dir = Path(call["installer_staging_dir"])
    installer_files = [f.name for f in i_dir.iterdir()]
    assert installer_files == [REQUIRED_INSTALLER_ASSET]
    installer_file = i_dir / REQUIRED_INSTALLER_ASSET
    assert installer_file.read_bytes() == fake_setup_bytes

    record_file = staging_base / "5.1.2" / "evidence" / "build-record.json"
    assert record_file.is_file()
    record = json.loads(record_file.read_text(encoding="utf-8"))

    assert record["source_commit"] == sha
    assert record["source_sha"] == sha
    assert record["stable_version"] == "5.1.1"
    assert record["target_version"] == "5.1.2"
    assert record["version"] == "v5.1.2"
    assert "launcher/src/neko_launcher/__init__.py" in record["injected_files"]
    assert "launcher/pyproject.toml" in record["injected_files"]

    core_auth = record["core_authority"]
    assert core_auth["authority_version_tag"] == "v5.1.2"
    assert core_auth["authority_release_sequence"] == 6
    assert core_auth["authority_release_id"] == "stable-0006"
    assert len(core_auth["authority_payload_sha256"]) == 64
    assert len(core_auth["authority_envelope_sha256"]) == 64
    assert core_auth["authority_key_id"] == "neko-update-prod-1"
    assert core_auth["core_source_commit"] == "6ab94bb"
    assert len(core_auth["provenance_sha256"]) == 64

    trust_prof = record["trust_profile"]
    assert trust_prof["profile_id"] == "production"
    assert trust_prof["channel"] == "stable"
    assert trust_prof["owner"] == "Valeneko-pranmong"
    assert trust_prof["repository"] == "Neko-Family-Proxy-Updates"
    assert "profile_authority_key_id" in trust_prof
    assert len(trust_prof["profile_authority_public_key_sha256"]) == 64
    assert len(trust_prof["profile_envelope_sha256"]) == 64
    assert len(trust_prof["keyset_sha256"]) == 64

    assert record["sequence"] == 8
    assert record["release_id"] == "stable-0008"
    assert record["key_id"] == "neko-update-prod-1"
    assert len(record["payload_sha256"]) == 64
    assert len(record["envelope_sha256"]) == 64
    assert record["embedded_envelope_sha256"] == record["envelope_sha256"]
    assert len(record["embedded_trust_profile_sha256"]) == 64

    assert set(record["machine_assets"].keys()) == {"launcher", "updater", "core", "manifest"}
    assert record["installer_asset"]["name"] == "NekoFamilyProxy-Installer.exe"
    assert record["installer_asset"]["sha256"] == hashlib.sha256(fake_setup_bytes).hexdigest()
    assert record["installer_asset"]["size"] == len(fake_setup_bytes)

    assert record["destination_repositories"]["machine"] == CANONICAL_MACHINE_REPO
    assert record["destination_repositories"]["installer"] == installer_repo

    assert "--release-version" in installer_builder_args
    rel_ver_idx = installer_builder_args.index("--release-version")
    assert installer_builder_args[rel_ver_idx + 1] == "5.1.2"
    assert "--baseline-envelope" in installer_builder_args
    assert "--trust-profile" in installer_builder_args


def test_process_accepted_commits_rejects_stale_target_version(monkeypatch, tmp_path):
    sha = "8" * 40
    run_id = 99998
    installer_repo = "Valeneko-pranmong/Neko-Family-Proxy-Installer"
    monkeypatch.setattr(
        "scripts.release_controller.get_successful_main_runs",
        lambda: [{"databaseId": run_id, "headSha": sha}],
    )
    monkeypatch.setattr(
        "scripts.derive_version.get_armed_target_from_dir",
        lambda *args, **kwargs: ("v5.1.1", "v5.1.1", 5, "stable-0005"),
    )
    monkeypatch.setattr("scripts.derive_version.get_github_releases", lambda: [])
    monkeypatch.setattr("scripts.release_controller.should_trigger", lambda f: True)

    def fake_run(args, **kwargs):
        if args[0] == "git" and "merge-base" in args:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "git" and "archive" in args:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "tar":
            s_dir = Path(f"E:/Github/artifacts/main-auto-release/{run_id}-{sha}") / "source"
            (s_dir / "launcher" / "src" / "neko_launcher").mkdir(parents=True, exist_ok=True)
            (s_dir / "launcher" / "src" / "neko_launcher" / "__init__.py").write_text('__version__ = "5.1.1"\n')
            (s_dir / "launcher" / "pyproject.toml").write_text('version = "5.1.1"\n')
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("scripts.release_controller.subprocess.run", fake_run)
    with pytest.raises((ValueError, SystemExit), match="(?i)(5\\.1\\.2|target|stale)"):
        process_accepted_commits(sha, run_id, installer_repo=installer_repo)


def test_release_controller_consumes_explicit_core_authority_custody_without_network(tmp_path):
    from scripts.core_authority_custody import (
        ArtifactIdentity,
        CoreAuthorityBinding,
        VerifiedCoreAuthority,
    )
    from scripts.release_controller import resolve_core_authority

    fake_core = tmp_path / "NekoProxyCore.zip"
    fake_core.write_bytes(b"core-bytes")
    fake_env = tmp_path / "release-v2.json"
    fake_env.write_bytes(b"{}")

    core_id = ArtifactIdentity(
        artifact_id="NekoProxyCore.zip",
        version="5.1.2",
        sha256=hashlib.sha256(b"core-bytes").hexdigest(),
        size=len(b"core-bytes"),
        installed_identity_sha256="i" * 64,
        artifact_format="zip-core-v1",
    )
    binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256="p" * 64,
        authority_envelope_sha256="e" * 64,
        authority_key_id="neko-update-prod-1",
        core_source_commit="6ab94bb",
        provenance_sha256="pr" * 32,
    )
    verified = VerifiedCoreAuthority(
        binding=binding,
        core_zip_path=fake_core,
        core=core_id,
    )

    # Calling resolve_core_authority with explicit verified core_authority requires 0 network calls
    staging_dir = tmp_path / "staging"
    network_calls = []

    class FakeNetworkExecutor:
        def run(self, *a, **k):
            network_calls.append((a, k))
            raise AssertionError("Network executor must not be called")

    res = resolve_core_authority(
        "v5.1.1",
        staging_dir,
        core_authority=verified,
        network_executor=FakeNetworkExecutor(),
    )
    assert len(network_calls) == 0
    assert res.core_zip_path.is_file()
    assert res.core_sha256 == core_id.sha256
    assert res.installed_identity_sha256 == core_id.installed_identity_sha256


def test_freeze_integrity_rejects_changed_core_authority_binding():
    from scripts.build_software_release_v2 import (
        ArtifactIdentity,
        CoreAuthorityBinding,
        FinalComponentSet,
        TrustProfileBinding,
        build_unsigned_baseline,
        compute_component_set_sha256,
    )
    from scripts.derive_version import ReleaseAllocation

    launcher_id = ArtifactIdentity("NekoLauncher.exe", "5.1.2", "1" * 64, 100, "1" * 64, "raw-pe-v1")
    updater_id = ArtifactIdentity("NekoUpdater.exe", "5.1.2", "2" * 64, 200, "2" * 64, "raw-pe-v1")
    core_id = ArtifactIdentity("NekoProxyCore.zip", "5.1.2", "3" * 64, 300, "3" * 64, "zip-core-v1")
    core_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256="p" * 64,
        authority_envelope_sha256="e" * 64,
        authority_key_id="neko-update-prod-1",
        core_source_commit="6ab94bb",
        provenance_sha256="pr" * 32,
    )
    trust_binding = TrustProfileBinding(
        profile_id="production",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates",
        profile_authority_key_id="neko-update-profile-v512-1",
        profile_authority_public_key_sha256="a" * 64,
        profile_envelope_sha256="env" * 21 + "e",
        keyset_sha256="k" * 64,
    )
    comp_sha = compute_component_set_sha256(
        source_commit="c" * 40,
        launcher=launcher_id,
        updater=updater_id,
        core=core_id,
        core_authority=core_binding,
        trust_profile=trust_binding,
    )

    # If any core_authority field is mutated after collection, build_unsigned_baseline rejects it
    mutated_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256="p" * 64,
        authority_envelope_sha256="mutated" + "e" * 57,
        authority_key_id="neko-update-prod-1",
        core_source_commit="6ab94bb",
        provenance_sha256="pr" * 32,
    )
    tampered_component_set = FinalComponentSet(
        source_commit="c" * 40,
        launcher=launcher_id,
        updater=updater_id,
        core=core_id,
        core_authority=mutated_binding,
        trust_profile=trust_binding,
        component_set_sha256=comp_sha,
    )

    alloc = ReleaseAllocation(8, "stable-0008", "l" * 64, comp_sha, "b" * 64, "h" * 64)
    with pytest.raises(ValueError, match="(?i)(digest|mismatch|tamper)"):
        build_unsigned_baseline(allocation=alloc, component_set=tampered_component_set)


# =============================================================================
# RA4: Controller-Only Production Signing Boundary Tests
# =============================================================================

import tests as _root_tests  # noqa: E402
_launcher_tests_dir = str(Path(__file__).resolve().parents[1] / "launcher" / "tests")
if _launcher_tests_dir not in _root_tests.__path__:
    _root_tests.__path__.append(_launcher_tests_dir)

import sys  # noqa: E402
_scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from neko_launcher.updater.canonical_json import canonical_json_dumps  # noqa: E402
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2  # noqa: E402
from tests.software_update_helpers import (  # noqa: E402
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_v2_release_document,
)
from authenticated_production_history import (  # noqa: E402
    AuthenticatedEnvelopeRecord,
    append_custody_record,
    bootstrap_sequence_ledger,
    reserve_release_sequence,
)
from build_software_release_v2 import UnsignedBaselineEvidence  # noqa: E402
from derive_version import ReleaseTargetIntent  # noqa: E402
from production_sequence_ledger import (  # noqa: E402
    AuthenticatedHistorySnapshot,
    AuthenticatedProductionBinding,
    ReleaseAuthorityReconciliationRequired,
    SequenceLedgerEvent,
    append_event,
    open_authority_session,
)


class _FakeHistoryProvider:
    def __init__(self, snapshot: AuthenticatedHistorySnapshot) -> None:
        self.snapshot = snapshot
        self.session_to_check = None
        self.load_calls: list[bool] = []

    def load(self) -> AuthenticatedHistorySnapshot:
        if self.session_to_check is not None:
            self.load_calls.append(bool(self.session_to_check.is_locked))
        else:
            self.load_calls.append(True)
        return self.snapshot


def _setup_seq7_floor_and_seq8_reserved(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    custody_root = tmp_path / "custody"
    custody_root.mkdir(parents=True, exist_ok=True)

    doc7 = valid_v2_release_document(sequence=7, release_id="stable-0007")
    env7 = signed_envelope(doc7, key_id=TEST_KEY_ID)
    env_bytes7 = canonical_json_dumps(env7)
    env_sha7 = hashlib.sha256(env_bytes7).hexdigest()
    import base64
    payload7 = base64.b64decode(env7["payload_b64"])
    payload_sha7 = hashlib.sha256(payload7).hexdigest()

    binding7 = AuthenticatedProductionBinding(
        sequence=7,
        release_id="stable-0007",
        payload_sha256=payload_sha7,
        envelope_sha256=env_sha7,
        key_id=TEST_KEY_ID,
    )
    floor_snapshot = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7},
        provenance_source_commit_by_sequence={7: "c" * 40},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=7,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )
    bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=_FakeHistoryProvider(floor_snapshot),
        expected_floor=binding7,
        expected_floor_provenance_source_commit="c" * 40,
    )

    target = ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug")
    allocation = reserve_release_sequence(
        ledger_path=ledger_path,
        history_provider=_FakeHistoryProvider(floor_snapshot),
        target=target,
        source_commit="a" * 40,
        component_set_sha256="comp" * 16,
    )

    doc8 = valid_v2_release_document(sequence=8, release_id="stable-0008")
    payload8_bytes = canonical_json_dumps(doc8)
    payload8_sha = hashlib.sha256(payload8_bytes).hexdigest()
    payload_path = tmp_path / "unsigned_payload.json"
    payload_path.write_bytes(payload8_bytes)

    unsigned = UnsignedBaselineEvidence(
        sequence=8,
        release_id="stable-0008",
        component_set_sha256="comp" * 16,
        payload_sha256=payload8_sha,
        payload_path=payload_path,
    )

    return ledger_path, custody_root, floor_snapshot, binding7, allocation, unsigned, doc8


def test_sign_reserved_baseline_none_signer_returns_signing_required_without_side_effects(tmp_path: Path):
    from scripts.release_controller import SigningRequired, sign_reserved_baseline

    ledger_path, custody_root, floor_snapshot, _binding7, allocation, unsigned, _doc8 = (
        _setup_seq7_floor_and_seq8_reserved(tmp_path)
    )

    res = sign_reserved_baseline(
        ledger_path=ledger_path,
        custody_root=custody_root,
        history_provider=_FakeHistoryProvider(floor_snapshot),
        production_public_keys={TEST_KEY_ID: TEST_PUBLIC_KEY},
        allocation=allocation,
        unsigned=unsigned,
        signer=None,
    )

    assert isinstance(res, SigningRequired)
    assert res.status == "SIGNING_REQUIRED"
    assert res.payload_path == unsigned.payload_path
    assert res.payload_sha256 == unsigned.payload_sha256

    # Verify no envelopes created in custody
    env_dir = custody_root / "envelopes"
    assert not env_dir.exists() or not list(env_dir.iterdir())

    # Verify ledger still only has the 1 RESERVED event
    with open_authority_session(ledger_path) as session:
        verified = session.read_verified()
        assert len(verified.events) == 1
        assert verified.events[0].status == "RESERVED"


def test_sign_reserved_baseline_none_signer_recovers_existing_custody_signed_binding(tmp_path: Path):
    from scripts.release_controller import (
        SignedBaselineEvidence,
        sign_reserved_baseline,
    )

    ledger_path, custody_root, _floor_snapshot, binding7, allocation, unsigned, doc8 = (
        _setup_seq7_floor_and_seq8_reserved(tmp_path)
    )

    # Put signed envelope for seq 8 into custody
    env8 = signed_envelope(doc8, key_id=TEST_KEY_ID)
    env_bytes8 = canonical_json_dumps(env8)
    env_sha8 = hashlib.sha256(env_bytes8).hexdigest()
    rec8 = AuthenticatedEnvelopeRecord(
        source_id="custody-0008",
        source_kind="custody",
        envelope_bytes=env_bytes8,
        provenance_source_commit="a" * 40,
    )
    append_custody_record(custody_root, rec8, expected_index_sha256=None)

    binding8 = AuthenticatedProductionBinding(
        sequence=8,
        release_id="stable-0008",
        payload_sha256=unsigned.payload_sha256,
        envelope_sha256=env_sha8,
        key_id=TEST_KEY_ID,
    )
    snapshot8 = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7, 8: binding8},
        provenance_source_commit_by_sequence={7: "c" * 40, 8: "a" * 40},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=8,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )

    class FailingSigner:
        def sign(self, payload: bytes):
            raise AssertionError("Signer must not be invoked when custody contains exact binding")

    res = sign_reserved_baseline(
        ledger_path=ledger_path,
        custody_root=custody_root,
        history_provider=_FakeHistoryProvider(snapshot8),
        production_public_keys={TEST_KEY_ID: TEST_PUBLIC_KEY},
        allocation=allocation,
        unsigned=unsigned,
        signer=FailingSigner(),
    )

    assert isinstance(res, SignedBaselineEvidence)
    assert res.sequence == 8
    assert res.release_id == "stable-0008"
    assert res.key_id == TEST_KEY_ID
    assert res.envelope_sha256 == env_sha8
    assert res.envelope_path == custody_root / "envelopes" / f"{env_sha8}.json"

    with open_authority_session(ledger_path) as session:
        verified = session.read_verified()
        assert len(verified.events) == 2
        assert verified.events[1].status == "SIGNED"
        assert verified.events[1].key_id == TEST_KEY_ID


def test_sign_reserved_baseline_ephemeral_signer_and_shared_assembler_happy_path(tmp_path: Path):
    from scripts.release_controller import (
        DetachedReleaseSignature,
        ReleaseSigner,
        SignedBaselineEvidence,
        sign_reserved_baseline,
    )

    ledger_path, custody_root, floor_snapshot, _binding7, allocation, unsigned, _doc8 = (
        _setup_seq7_floor_and_seq8_reserved(tmp_path)
    )

    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    key_id = "test-eph-release-1"

    class EphemeralSigner:
        def sign(self, canonical_payload: bytes) -> DetachedReleaseSignature:
            sig = priv.sign(canonical_payload)
            return DetachedReleaseSignature(key_id=key_id, signature=sig)

    signer = EphemeralSigner()
    assert isinstance(signer, ReleaseSigner)

    # Provider that updates snapshot after custody append
    class AutoUpdatingProvider:
        def __init__(self, initial_snapshot: AuthenticatedHistorySnapshot):
            self.snapshot = initial_snapshot
            self.load_count = 0

        def load(self) -> AuthenticatedHistorySnapshot:
            self.load_count += 1
            # If custody has envelopes, load them
            from scripts.authenticated_production_history import load_custody_records
            recs = load_custody_records(custody_root)
            if len(recs) > 0:
                env_doc = json.loads(recs[0].envelope_bytes.decode("utf-8"))
                import base64
                payload = base64.b64decode(env_doc["payload_b64"])
                b8 = AuthenticatedProductionBinding(
                    sequence=8,
                    release_id="stable-0008",
                    payload_sha256=hashlib.sha256(payload).hexdigest(),
                    envelope_sha256=hashlib.sha256(recs[0].envelope_bytes).hexdigest(),
                    key_id=key_id,
                )
                bindings = dict(self.snapshot.bindings_by_sequence)
                bindings[8] = b8
                prov = dict(self.snapshot.provenance_source_commit_by_sequence)
                prov[8] = "a" * 40
                return AuthenticatedHistorySnapshot(
                    bindings_by_sequence=bindings,
                    provenance_source_commit_by_sequence=prov,
                    live_updates_sequences=frozenset(),
                    highest_authenticated_sequence=8,
                    authenticated_bindings_sha256="b" * 64,
                    snapshot_sha256="s" * 64,
                )
            return self.snapshot

    provider = AutoUpdatingProvider(floor_snapshot)

    res = sign_reserved_baseline(
        ledger_path=ledger_path,
        custody_root=custody_root,
        history_provider=provider,
        production_public_keys={key_id: pub_bytes},
        allocation=allocation,
        unsigned=unsigned,
        signer=signer,
    )

    assert isinstance(res, SignedBaselineEvidence)
    assert res.sequence == 8
    assert res.release_id == "stable-0008"
    assert res.key_id == key_id
    assert res.envelope_path.is_file()

    # Re-verify envelope using public key
    envelope_doc = json.loads(res.envelope_path.read_text(encoding="utf-8"))
    rel_set, ret_sha = verify_release_envelope_v2(envelope_doc, {key_id: pub_bytes})
    assert rel_set.release_sequence == 8
    assert rel_set.release_id == "stable-0008"
    assert ret_sha == unsigned.payload_sha256

    # Verify ledger append
    with open_authority_session(ledger_path) as session:
        verified = session.read_verified()
        assert len(verified.events) == 2
        assert verified.events[1].status == "SIGNED"
        assert verified.events[1].key_id == key_id


def test_sign_reserved_baseline_rejects_unknown_signer_key_id(tmp_path: Path):
    from scripts.release_controller import (
        DetachedReleaseSignature,
        sign_reserved_baseline,
    )

    ledger_path, custody_root, floor_snapshot, _binding7, allocation, unsigned, _doc8 = (
        _setup_seq7_floor_and_seq8_reserved(tmp_path)
    )

    class UnknownKeySigner:
        def sign(self, canonical_payload: bytes) -> DetachedReleaseSignature:
            return DetachedReleaseSignature(key_id="unknown-key-id", signature=b"\x00" * 64)

    with pytest.raises(ValueError, match="(?i)(unknown|absent|key_id)"):
        sign_reserved_baseline(
            ledger_path=ledger_path,
            custody_root=custody_root,
            history_provider=_FakeHistoryProvider(floor_snapshot),
            production_public_keys={TEST_KEY_ID: TEST_PUBLIC_KEY},
            allocation=allocation,
            unsigned=unsigned,
            signer=UnknownKeySigner(),
        )

    # Confirm no mutation
    env_dir = custody_root / "envelopes"
    assert not env_dir.exists() or not list(env_dir.iterdir())
    with open_authority_session(ledger_path) as session:
        assert len(session.read_verified().events) == 1


def test_sign_reserved_baseline_rejects_bad_signature_length(tmp_path: Path):
    from scripts.release_controller import (
        DetachedReleaseSignature,
        sign_reserved_baseline,
    )

    ledger_path, custody_root, floor_snapshot, _binding7, allocation, unsigned, _doc8 = (
        _setup_seq7_floor_and_seq8_reserved(tmp_path)
    )

    class BadLengthSigner:
        def sign(self, canonical_payload: bytes) -> DetachedReleaseSignature:
            return DetachedReleaseSignature(key_id=TEST_KEY_ID, signature=b"\x00" * 32)

    with pytest.raises(ValueError, match="(?i)(signature|length)"):
        sign_reserved_baseline(
            ledger_path=ledger_path,
            custody_root=custody_root,
            history_provider=_FakeHistoryProvider(floor_snapshot),
            production_public_keys={TEST_KEY_ID: TEST_PUBLIC_KEY},
            allocation=allocation,
            unsigned=unsigned,
            signer=BadLengthSigner(),
        )


def test_sign_reserved_baseline_rejects_corrupted_signature_for_payload(tmp_path: Path):
    from scripts.release_controller import (
        DetachedReleaseSignature,
        sign_reserved_baseline,
    )

    ledger_path, custody_root, floor_snapshot, _binding7, allocation, unsigned, _doc8 = (
        _setup_seq7_floor_and_seq8_reserved(tmp_path)
    )

    class CorruptSigner:
        def sign(self, canonical_payload: bytes) -> DetachedReleaseSignature:
            return DetachedReleaseSignature(key_id=TEST_KEY_ID, signature=b"\x00" * 64)

    with pytest.raises(ValueError, match="(?i)(invalid|signature)"):
        sign_reserved_baseline(
            ledger_path=ledger_path,
            custody_root=custody_root,
            history_provider=_FakeHistoryProvider(floor_snapshot),
            production_public_keys={TEST_KEY_ID: TEST_PUBLIC_KEY},
            allocation=allocation,
            unsigned=unsigned,
            signer=CorruptSigner(),
        )


def test_sign_reserved_baseline_rejects_proof_authority_keys_and_mixed_registries(tmp_path: Path):
    from scripts.release_controller import (
        DetachedReleaseSignature,
        sign_reserved_baseline,
    )

    ledger_path, custody_root, floor_snapshot, _binding7, allocation, unsigned, _doc8 = (
        _setup_seq7_floor_and_seq8_reserved(tmp_path)
    )

    class SpySigner:
        called = False

        def sign(self, canonical_payload: bytes) -> DetachedReleaseSignature:
            self.called = True
            return DetachedReleaseSignature(key_id="test", signature=b"\x00" * 64)

    signer = SpySigner()

    # Proof key rejected
    with pytest.raises(ValueError, match="(?i)(proof|forbidden)"):
        sign_reserved_baseline(
            ledger_path=ledger_path,
            custody_root=custody_root,
            history_provider=_FakeHistoryProvider(floor_snapshot),
            production_public_keys={"proof-release-key-v512-1": TEST_PUBLIC_KEY},
            allocation=allocation,
            unsigned=unsigned,
            signer=signer,
        )
    assert not signer.called

    # Mixed registry rejected
    with pytest.raises(ValueError, match="(?i)(mixed|multi-key|forbidden)"):
        sign_reserved_baseline(
            ledger_path=ledger_path,
            custody_root=custody_root,
            history_provider=_FakeHistoryProvider(floor_snapshot),
            production_public_keys={"neko-update-prod-1": TEST_PUBLIC_KEY, "extra-key": TEST_PUBLIC_KEY},
            allocation=allocation,
            unsigned=unsigned,
            signer=signer,
        )
    assert not signer.called


def test_sign_reserved_baseline_checks_history_freshness_under_lock_and_stops_on_conflict(tmp_path: Path):
    from scripts.release_controller import (
        DetachedReleaseSignature,
        sign_reserved_baseline,
    )

    ledger_path, custody_root, _floor_snapshot, binding7, allocation, unsigned, _doc8 = (
        _setup_seq7_floor_and_seq8_reserved(tmp_path)
    )

    # Newer unallocated sequence 9 present in history
    binding9 = AuthenticatedProductionBinding(
        sequence=9,
        release_id="stable-0009",
        payload_sha256="p" * 64,
        envelope_sha256="e" * 64,
        key_id=TEST_KEY_ID,
    )
    conflicting_snapshot = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7, 9: binding9},
        provenance_source_commit_by_sequence={7: "c" * 40, 9: "x" * 40},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=9,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )

    class SpySigner:
        called = False

        def sign(self, canonical_payload: bytes) -> DetachedReleaseSignature:
            self.called = True
            return DetachedReleaseSignature(key_id=TEST_KEY_ID, signature=b"\x00" * 64)

    signer = SpySigner()

    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        sign_reserved_baseline(
            ledger_path=ledger_path,
            custody_root=custody_root,
            history_provider=_FakeHistoryProvider(conflicting_snapshot),
            production_public_keys={TEST_KEY_ID: TEST_PUBLIC_KEY},
            allocation=allocation,
            unsigned=unsigned,
            signer=signer,
        )
    assert not signer.called


def test_sign_reserved_baseline_crash_recovery_after_custody_write_does_not_resign(tmp_path: Path):
    from scripts.release_controller import (
        DetachedReleaseSignature,
        SignedBaselineEvidence,
        sign_reserved_baseline,
    )

    ledger_path, custody_root, floor_snapshot, _binding7, allocation, unsigned, _doc8 = (
        _setup_seq7_floor_and_seq8_reserved(tmp_path)
    )

    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    key_id = "test-eph-crash-1"

    call_count = 0

    class CountingSigner:
        def sign(self, canonical_payload: bytes) -> DetachedReleaseSignature:
            nonlocal call_count
            call_count += 1
            sig = priv.sign(canonical_payload)
            return DetachedReleaseSignature(key_id=key_id, signature=sig)

    class AutoUpdatingProvider:
        def __init__(self, initial_snapshot: AuthenticatedHistorySnapshot):
            self.snapshot = initial_snapshot

        def load(self) -> AuthenticatedHistorySnapshot:
            from scripts.authenticated_production_history import load_custody_records
            recs = load_custody_records(custody_root)
            if len(recs) > 0:
                env_doc = json.loads(recs[0].envelope_bytes.decode("utf-8"))
                import base64
                payload = base64.b64decode(env_doc["payload_b64"])
                b8 = AuthenticatedProductionBinding(
                    sequence=8,
                    release_id="stable-0008",
                    payload_sha256=hashlib.sha256(payload).hexdigest(),
                    envelope_sha256=hashlib.sha256(recs[0].envelope_bytes).hexdigest(),
                    key_id=key_id,
                )
                bindings = dict(self.snapshot.bindings_by_sequence)
                bindings[8] = b8
                prov = dict(self.snapshot.provenance_source_commit_by_sequence)
                prov[8] = "a" * 40
                return AuthenticatedHistorySnapshot(
                    bindings_by_sequence=bindings,
                    provenance_source_commit_by_sequence=prov,
                    live_updates_sequences=frozenset(),
                    highest_authenticated_sequence=8,
                    authenticated_bindings_sha256="b" * 64,
                    snapshot_sha256="s" * 64,
                )
            return self.snapshot

    provider = AutoUpdatingProvider(floor_snapshot)
    signer = CountingSigner()

    # Simulate crash right after custody persistence by hooking append_custody_record to write custody then raise
    import scripts.release_controller as rc
    orig_append = rc.append_custody_record

    def failing_custody_append(*args, **kwargs):
        orig_append(*args, **kwargs)
        raise RuntimeError("Simulated power outage / process kill after custody write")

    rc.append_custody_record = failing_custody_append
    try:
        with pytest.raises(RuntimeError, match="Simulated power outage"):
            sign_reserved_baseline(
                ledger_path=ledger_path,
                custody_root=custody_root,
                history_provider=provider,
                production_public_keys={key_id: pub_bytes},
                allocation=allocation,
                unsigned=unsigned,
                signer=signer,
            )
    finally:
        rc.append_custody_record = orig_append

    assert call_count == 1
    # Ledger should still only have RESERVED
    with open_authority_session(ledger_path) as session:
        assert len(session.read_verified().events) == 1

    # Rerun sign_reserved_baseline
    res = sign_reserved_baseline(
        ledger_path=ledger_path,
        custody_root=custody_root,
        history_provider=provider,
        production_public_keys={key_id: pub_bytes},
        allocation=allocation,
        unsigned=unsigned,
        signer=signer,
    )

    assert isinstance(res, SignedBaselineEvidence)
    assert res.sequence == 8
    assert res.key_id == key_id
    assert call_count == 1  # Crucial: NO second signature performed!

    with open_authority_session(ledger_path) as session:
        verified = session.read_verified()
        assert len(verified.events) == 2
        assert verified.events[1].status == "SIGNED"


def _setup_seq8_signed_fixture(tmp_path: Path):
    ledger_path, custody_root, _floor_snapshot, binding7, allocation, unsigned, doc8 = (
        _setup_seq7_floor_and_seq8_reserved(tmp_path)
    )
    env8 = signed_envelope(doc8, key_id=TEST_KEY_ID)
    env_bytes8 = canonical_json_dumps(env8)
    env_sha8 = hashlib.sha256(env_bytes8).hexdigest()
    rec8 = AuthenticatedEnvelopeRecord(
        source_id="custody-0008",
        source_kind="custody",
        envelope_bytes=env_bytes8,
        provenance_source_commit="a" * 40,
    )
    append_custody_record(custody_root, rec8, expected_index_sha256=None)

    from scripts.release_controller import (
        SignedBaselineEvidence,
        sign_reserved_baseline,
    )

    sign_res = sign_reserved_baseline(
        ledger_path=ledger_path,
        custody_root=custody_root,
        history_provider=_FakeHistoryProvider(
            AuthenticatedHistorySnapshot(
                bindings_by_sequence={
                    7: binding7,
                    8: AuthenticatedProductionBinding(
                        sequence=8,
                        release_id="stable-0008",
                        payload_sha256=unsigned.payload_sha256,
                        envelope_sha256=env_sha8,
                        key_id=TEST_KEY_ID,
                    ),
                },
                provenance_source_commit_by_sequence={7: "c" * 40, 8: "a" * 40},
                live_updates_sequences=frozenset(),
                highest_authenticated_sequence=8,
                authenticated_bindings_sha256="b" * 64,
                snapshot_sha256="s" * 64,
            )
        ),
        production_public_keys={TEST_KEY_ID: TEST_PUBLIC_KEY},
        allocation=allocation,
        unsigned=unsigned,
        signer=None,
    )
    assert isinstance(sign_res, SignedBaselineEvidence)

    with open_authority_session(ledger_path) as session:
        verified = session.read_verified()

    request = SupersedeSignedReleaseRequest(
        sequence=8,
        release_id="stable-0008",
        source_commit="a" * 40,
        component_set_sha256="comp" * 16,
        payload_sha256=unsigned.payload_sha256,
        envelope_sha256=env_sha8,
        latest_ledger_entry_sha256=verified.latest_entry_sha256,
        approved_spec_commit="d" * 40,
        reason_code="ARCHITECTURE_SUPERSEDED_BEFORE_PUBLICATION",
    )

    return ledger_path, custody_root, verified, request


def test_supersede_signed_unpublished_release_prepares_terminal_failed_event(tmp_path: Path):
    ledger_path, custody_root, verified, request = _setup_seq8_signed_fixture(tmp_path)

    result = prepare_signed_release_supersession(
        verified_ledger=verified,
        custody=custody_root,
        request=request,
    )
    assert result.event.sequence == 8
    assert result.event.status == "FAILED"
    assert result.next_unused_sequence == 9


def test_supersession_rejects_published_release_before_append(tmp_path: Path):
    ledger_path, custody_root, verified, request = _setup_seq8_signed_fixture(tmp_path)

    # Append a PUBLISHED event for seq 8
    ev_pub = SequenceLedgerEvent(
        record_type="EVENT",
        sequence=8,
        release_id="stable-0008",
        status="PUBLISHED",
        version="5.1.2",
        channel="stable",
        source_commit="a" * 40,
        component_set_sha256="comp" * 16,
        payload_sha256=request.payload_sha256,
        envelope_sha256=request.envelope_sha256,
        key_id=TEST_KEY_ID,
        timestamp="2026-09-16T12:00:00Z",
        previous_entry_sha256=verified.latest_entry_sha256,
    )
    pub_sha = append_event(ledger_path, ev_pub, verified.latest_entry_sha256)

    with open_authority_session(ledger_path) as session:
        verified_pub = session.read_verified()

    req_pub = SupersedeSignedReleaseRequest(
        sequence=8,
        release_id="stable-0008",
        source_commit="a" * 40,
        component_set_sha256="comp" * 16,
        payload_sha256=request.payload_sha256,
        envelope_sha256=request.envelope_sha256,
        latest_ledger_entry_sha256=pub_sha,
        approved_spec_commit="d" * 40,
        reason_code="ARCHITECTURE_SUPERSEDED_BEFORE_PUBLICATION",
    )

    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        prepare_signed_release_supersession(
            verified_ledger=verified_pub,
            custody=custody_root,
            request=req_pub,
        )


def test_supersession_dry_run_mutate_false_preserves_zero_writes(tmp_path: Path):
    ledger_path, custody_root, verified, request = _setup_seq8_signed_fixture(tmp_path)
    ledger_bytes_before = ledger_path.read_bytes()

    result = prepare_signed_release_supersession(
        ledger_path=ledger_path,
        custody_root=custody_root,
        request=request,
        mutate=False,
    )

    assert isinstance(result, PreparedSupersessionResult)
    assert result.mutated is False
    assert result.event.sequence == 8
    assert result.event.status == "FAILED"
    assert result.event.previous_entry_sha256 == verified.latest_entry_sha256
    assert result.current_ledger_head_sha256 == verified.latest_entry_sha256
    assert result.next_unused_sequence == 9
    assert len(result.proposed_entry_sha256) == 64

    # File on disk is completely unchanged (zero writes)
    assert ledger_path.read_bytes() == ledger_bytes_before

    with open_authority_session(ledger_path) as session:
        after_ledger = session.read_verified()
        assert len(after_ledger.events) == 2
        assert after_ledger.latest_entry_sha256 == verified.latest_entry_sha256


def test_supersession_dry_run_real_authority_inputs_read_only():
    prod_ledger = Path("E:/Github/authority/v512-production-sequence-authority/production-sequence-ledger-v1.jsonl")
    prod_custody = Path("E:/Github/artifacts/v512-production-authority-custody")

    if not prod_ledger.is_file() or not prod_custody.is_dir():
        pytest.skip("Real authority inputs not present on this machine")

    real_bytes_before = prod_ledger.read_bytes()
    real_stat_before = prod_ledger.stat()

    req = SupersedeSignedReleaseRequest(
        sequence=8,
        release_id="stable-0008",
        source_commit="efb79a0b62d27437fd7ac0c7b2c4bfad8c4264ce",
        component_set_sha256="4520cba9be1785155630992d75ebd11f7616a1256fdcd394abb9950ad6681f57",
        payload_sha256="ed9d510fc3aca08b70ef1a78864fd1c632a4f87b0a285fc3360e2627359161f0",
        envelope_sha256="0ee3134aaddffab345eddec669918fe3defc794f446b922d22d61f3b91be50b7",
        latest_ledger_entry_sha256="ac89aea38c06ab62ab8c6fab1e99db6491a05d0a41a15eb8a041a4b83e4dca58",
        approved_spec_commit="224eb9cb43df0ca0fa583fa41a0c219622392a56",
        reason_code="ARCHITECTURE_SUPERSEDED_BEFORE_PUBLICATION",
    )

    result = prepare_signed_release_supersession(
        ledger_path=prod_ledger,
        custody_root=prod_custody,
        request=req,
        mutate=False,
    )

    assert result.event.sequence == 8
    assert result.event.status == "FAILED"
    assert result.event.release_id == "stable-0008"
    assert result.event.source_commit == "efb79a0b62d27437fd7ac0c7b2c4bfad8c4264ce"
    assert result.event.previous_entry_sha256 == "ac89aea38c06ab62ab8c6fab1e99db6491a05d0a41a15eb8a041a4b83e4dca58"
    assert result.next_unused_sequence == 9
    assert result.mutated is False
    assert result.current_ledger_head_sha256 == "ac89aea38c06ab62ab8c6fab1e99db6491a05d0a41a15eb8a041a4b83e4dca58"

    # Absolute proof that production ledger was NOT mutated
    assert prod_ledger.read_bytes() == real_bytes_before
    assert prod_ledger.stat().st_size == real_stat_before.st_size
    assert prod_ledger.stat().st_mtime_ns == real_stat_before.st_mtime_ns


def test_supersession_rejects_identity_mismatches_at_controller_level(tmp_path: Path):
    ledger_path, custody_root, verified, request = _setup_seq8_signed_fixture(tmp_path)

    # Wrong release id
    req_bad_id = SupersedeSignedReleaseRequest(
        sequence=request.sequence,
        release_id="stable-9999",
        source_commit=request.source_commit,
        component_set_sha256=request.component_set_sha256,
        payload_sha256=request.payload_sha256,
        envelope_sha256=request.envelope_sha256,
        latest_ledger_entry_sha256=request.latest_ledger_entry_sha256,
        approved_spec_commit=request.approved_spec_commit,
        reason_code="ARCHITECTURE_SUPERSEDED_BEFORE_PUBLICATION",
    )
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        prepare_signed_release_supersession(
            ledger_path=ledger_path,
            custody_root=custody_root,
            request=req_bad_id,
        )

    # Wrong source commit
    req_bad_src = SupersedeSignedReleaseRequest(
        sequence=request.sequence,
        release_id=request.release_id,
        source_commit="b" * 40,
        component_set_sha256=request.component_set_sha256,
        payload_sha256=request.payload_sha256,
        envelope_sha256=request.envelope_sha256,
        latest_ledger_entry_sha256=request.latest_ledger_entry_sha256,
        approved_spec_commit=request.approved_spec_commit,
        reason_code="ARCHITECTURE_SUPERSEDED_BEFORE_PUBLICATION",
    )
    with pytest.raises((ReleaseAuthorityReconciliationRequired, Exception)):
        prepare_signed_release_supersession(
            ledger_path=ledger_path,
            custody_root=custody_root,
            request=req_bad_src,
        )

    # Wrong payload sha256
    req_bad_payload = SupersedeSignedReleaseRequest(
        sequence=request.sequence,
        release_id=request.release_id,
        source_commit=request.source_commit,
        component_set_sha256=request.component_set_sha256,
        payload_sha256="0" * 64,
        envelope_sha256=request.envelope_sha256,
        latest_ledger_entry_sha256=request.latest_ledger_entry_sha256,
        approved_spec_commit=request.approved_spec_commit,
        reason_code="ARCHITECTURE_SUPERSEDED_BEFORE_PUBLICATION",
    )
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        prepare_signed_release_supersession(
            ledger_path=ledger_path,
            custody_root=custody_root,
            request=req_bad_payload,
        )

    # Stale latest ledger entry sha256
    req_bad_head = SupersedeSignedReleaseRequest(
        sequence=request.sequence,
        release_id=request.release_id,
        source_commit=request.source_commit,
        component_set_sha256=request.component_set_sha256,
        payload_sha256=request.payload_sha256,
        envelope_sha256=request.envelope_sha256,
        latest_ledger_entry_sha256="0" * 64,
        approved_spec_commit=request.approved_spec_commit,
        reason_code="ARCHITECTURE_SUPERSEDED_BEFORE_PUBLICATION",
    )
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        prepare_signed_release_supersession(
            ledger_path=ledger_path,
            custody_root=custody_root,
            request=req_bad_head,
        )
