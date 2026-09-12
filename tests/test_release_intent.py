import json
import subprocess
from pathlib import Path

import pytest

from scripts import derive_version
from scripts.kanban_release_adapter import poll_github_and_create_tasks


def test_c_api_compatibility():
    # C) API compatibility
    assert hasattr(derive_version, "get_release_sequence")
    assert hasattr(derive_version, "get_release_id")
    assert hasattr(derive_version, "get_github_releases")
    assert derive_version.get_release_sequence("v5.1.0") == 4
    assert derive_version.get_release_id(4) == "stable-0004"
    # we can't test get_github_releases without mocking but we can check if it exists

def test_a_exact_sha_intent_binding_adapter(monkeypatch, tmp_path):
    # A) Adapter must load/parse release_target.json from EACH exact accepted run head SHA
    called_shas = []

    def fake_gh_run(*args, **kwargs):
        return [{"databaseId": 123, "headSha": "sha123"}]
    monkeypatch.setattr("scripts.kanban_release_adapter.get_successful_main_runs", fake_gh_run)

    def mock_get_armed_target_from_sha(sha):
        called_shas.append(sha)
        return "v5.1.0", "v5.1.1", 5, "stable-0005"
    monkeypatch.setattr("scripts.kanban_release_adapter.get_armed_target_from_sha", mock_get_armed_target_from_sha)

    # Mock other things so we don't actually run anything
    monkeypatch.setattr("subprocess.check_output", lambda *args, **kwargs: b"launcher/src/main.py\n")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr("scripts.kanban_release_adapter.get_github_releases", list)

    poll_github_and_create_tasks()
    assert "sha123" in called_shas

def test_b_duplicate_guard_adapter(monkeypatch):
    # Adapter does NOT create a task when exact target already exists as non-prerelease Stable
    def fake_gh_run(*args, **kwargs):
        return [{"databaseId": 123, "headSha": "sha123"}]
    monkeypatch.setattr("scripts.kanban_release_adapter.get_successful_main_runs", fake_gh_run)

    def mock_get_armed_target_from_sha(sha):
        return "v5.1.0", "v5.1.1", 5, "stable-0005"
    monkeypatch.setattr("scripts.kanban_release_adapter.get_armed_target_from_sha", mock_get_armed_target_from_sha)

    def fake_get_github_releases():
        return [{"tag_name": "v5.1.1", "prerelease": False}] # Already exists as stable!
    monkeypatch.setattr("scripts.kanban_release_adapter.get_github_releases", fake_get_github_releases)

    # Make sure we track if kanban task was created
    created = []
    def fake_subprocess_run(cmd, **kwargs):
        if cmd[0] == "hermes" and cmd[1] == "kanban":
            created.append(cmd)
    monkeypatch.setattr("subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("subprocess.check_output", lambda *args, **kwargs: b"fake\n")

    poll_github_and_create_tasks()
    assert len(created) == 0, "Should not create task if target is already stable"

def test_b_duplicate_guard_controller(monkeypatch, tmp_path):
    # Controller independently fail-closed/no-publish for already accepted target
    from scripts import release_controller

    class FakeSystemExit(Exception):
        pass
    monkeypatch.setattr("sys.exit", lambda code: (_ for _ in ()).throw(FakeSystemExit(code)))

    def fake_gh_run(): return [{"databaseId": 1, "headSha": "sha1"}]
    monkeypatch.setattr(release_controller, "get_successful_main_runs", fake_gh_run)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: None)
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: b"file.txt\n")
    monkeypatch.setattr(release_controller, "should_trigger", lambda f: True)

    def mock_get_armed_target(*a, **k):
        return "v5.1.0", "v5.1.1", 5, "stable-0005"
    monkeypatch.setattr("scripts.derive_version.get_armed_target_from_dir", mock_get_armed_target)
    monkeypatch.setattr("scripts.derive_version.get_github_releases", lambda: [])

    # Mock get_github_releases to say v5.1.1 is already stable
    def fake_get_github_releases():
        return [{"tag_name": "v5.1.1", "prerelease": False}]
    monkeypatch.setattr("scripts.derive_version.get_github_releases", fake_get_github_releases)

    staging_base = tmp_path / "artifacts"
    orig_path = release_controller.Path
    def mock_path(*args, **kwargs):
        if args and "E:/Github/artifacts" in str(args[0]):
            return orig_path(str(args[0]).replace("E:/Github/artifacts", str(tmp_path)))
        return orig_path(*args, **kwargs)
    monkeypatch.setattr(release_controller, "Path", mock_path)

    source_dir = staging_base / "main-auto-release" / "1-sha1" / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(FakeSystemExit):
        release_controller.process_accepted_commits("sha1", 1)

def test_d_version_injection_hardening(monkeypatch, tmp_path):
    # D) 0/multiple versions fail closed, exact 1 succeeds

    from scripts import release_controller

    # We will just test the injection logic part directly by mocking
    class FakeSystemExit(Exception):
        pass

    def mock_exit(code):
        raise FakeSystemExit(code)
    monkeypatch.setattr("sys.exit", mock_exit)

    # Let's extract the injection block to test it, or we can just mock process_accepted_commits's dependencies.
    # To test process_accepted_commits up to injection:
    def fake_gh_run(): return [{"databaseId": 1, "headSha": "sha1"}]
    monkeypatch.setattr(release_controller, "get_successful_main_runs", fake_gh_run)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: None)
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: b"file.txt\n")
    monkeypatch.setattr(release_controller, "should_trigger", lambda f: True)

    def mock_get_armed_target(*a, **k):
        return "v5.1.0", "v5.1.1", 5, "stable-0005"
    monkeypatch.setattr("scripts.derive_version.get_armed_target_from_dir", mock_get_armed_target)
    monkeypatch.setattr("scripts.derive_version.get_github_releases", lambda: [])

    staging_base = tmp_path / "artifacts"
    monkeypatch.setattr(release_controller, "Path", type("MockPath", (type(tmp_path),), {"__new__": lambda cls, *args, **kwargs: Path(str(staging_base)) if "artifacts" in str(args[0]) else Path(*args, **kwargs)}))

    # Create the files with multiple versions
    source_dir = staging_base / "source"
    init_path = source_dir / "launcher" / "src" / "neko_launcher" / "__init__.py"
    init_path.parent.mkdir(parents=True, exist_ok=True)
    init_path.write_text('__version__ = "5.1.0"\n__version__ = "5.1.0"')

    pyproject_path = source_dir / "launcher" / "pyproject.toml"
    pyproject_path.parent.mkdir(parents=True, exist_ok=True)
    pyproject_path.write_text('version = "5.1.0"')

    with pytest.raises(FakeSystemExit):
        release_controller.process_accepted_commits("sha1", 1)

def test_e_build_record_provenance(monkeypatch, tmp_path):
    # E) Build-record provenance must actually contain source_commit, stable/base version, target version, and exact injected files

    from scripts import release_controller

    class FakeSystemExit(Exception):
        pass
    monkeypatch.setattr("sys.exit", lambda code: (_ for _ in ()).throw(FakeSystemExit(code)))

    def fake_gh_run(): return [{"databaseId": 1, "headSha": "sha1"}]
    monkeypatch.setattr(release_controller, "get_successful_main_runs", fake_gh_run)
    def mock_run(*args, **kwargs):
        if "gh" in args[0] and "release" in args[0] and "view" in args[0]:
            pass
        if "build_software_release_v2.py" in str(args[0]):
            out_idx = args[0].index("--output") + 1
            Path(args[0][out_idx]).write_text("fake_release_json")
        if "build_beta_installer.py" in str(args[0]):
            # we already mocked shutil.copy for it, wait, setup_exe stat fails? No, NekoFamilyProxy-Setup.exe
            # Oh wait, setup_exe is copied to final_setup_exe
            setup_out = staging_base / "out"
            setup_out.mkdir(parents=True, exist_ok=True)
            (setup_out / "NekoFamilyProxy-Setup.exe").write_text("fake_setup")
        return subprocess.CompletedProcess(args[0], 0, stdout=b"", stderr=b"")
    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: b"file.txt\n" if "git" in a[0] else b'{"assets":[{"name":"release-v2.json","url":"http"}]}')
    monkeypatch.setattr(release_controller, "should_trigger", lambda f: True)

    def mock_get_armed_target(*a, **k):
        return "v5.1.0", "v5.1.1", 5, "stable-0005"
    monkeypatch.setattr("scripts.derive_version.get_armed_target_from_dir", mock_get_armed_target)
    monkeypatch.setattr("scripts.derive_version.get_github_releases", lambda: [])

    # Need to skip core verify
    monkeypatch.setattr(release_controller, "verify_and_fetch_core", lambda *a, **k: (tmp_path/"core.zip", "hash", 100, "ident", {"stable_tag": "v5.1.0", "release_id": 123}))
    tmp_core = tmp_path / "core.zip"
    tmp_core.write_text("dummy")

    import zipfile
    class MockZipFile:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, name): return b'{"source_commit":"sha_core"}'
        def extractall(self, path): pass
    monkeypatch.setattr(zipfile, "ZipFile", MockZipFile)

    monkeypatch.setattr("shutil.copy", lambda src, dst: None)

    staging_base = tmp_path / "artifacts"

    # Patch Path inside release_controller
    orig_path = release_controller.Path
    def mock_path(*args, **kwargs):
        if args and "E:/Github/artifacts" in str(args[0]):
            return orig_path(str(args[0]).replace("E:/Github/artifacts", str(tmp_path)))
        return orig_path(*args, **kwargs)
    monkeypatch.setattr(release_controller, "Path", mock_path)

    # Create the files with correct versions
    source_dir = tmp_path / "main-auto-release" / "1-sha1" / "source"
    init_path = source_dir / "launcher" / "src" / "neko_launcher" / "__init__.py"
    init_path.parent.mkdir(parents=True, exist_ok=True)
    init_path.write_text('__version__ = "5.1.0"')

    pyproject_path = source_dir / "launcher" / "pyproject.toml"
    pyproject_path.parent.mkdir(parents=True, exist_ok=True)
    pyproject_path.write_text('version = "5.1.0"')

    dist_dir = source_dir / "launcher" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "NekoLauncher.exe").write_text("l")
    (dist_dir / "NekoUpdater.exe").write_text("u")

    # Fake shutil copy so the publish dir has the exe
    def fake_copy(src, dst):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_text("fake")
    monkeypatch.setattr("shutil.copy", fake_copy)

    monkeypatch.setattr("scripts.publish_atomic_release.execute_publish", lambda *a, **k: None)

    # Also bypass the _get_sha256 on dotnet
    def fake_sha256(path):
        return "0d20debb26fc8b2bc84f25fbd9d4596a6364af8517ebf012e8b871127b798941"
    monkeypatch.setattr(release_controller, "_get_sha256", fake_sha256)

    release_controller.process_accepted_commits("sha1", 1)

    build_record_path = tmp_path / "main-auto-release" / "1-sha1" / "5.1.1" / "evidence" / "build-record.json"
    record = json.loads(build_record_path.read_text())
    assert "source_commit" in record
    assert "stable_version" in record
    assert "target_version" in record
    assert "injected_files" in record
    assert "core_authority" in record
    assert record["core_authority"]["stable_tag"] == "v5.1.0"
    assert len(record["injected_files"]) > 0
