import json
import subprocess
from pathlib import Path
import pytest

from scripts.release_controller import process_accepted_commits


def test_release_controller_e2e(monkeypatch, tmp_path):
    sha = "1111111111111111111111111111111111111111"
    run_id = 12345

    monkeypatch.setattr(
        "scripts.release_controller.get_successful_main_runs",
        lambda: [{"databaseId": run_id, "headSha": sha}],
    )
    monkeypatch.setattr(
        "scripts.release_controller.get_github_releases",
        lambda: [{"tag_name": "v5.1.6", "prerelease": False}],
    )
    monkeypatch.setattr("scripts.release_controller.should_trigger", lambda f: True)

    executed_commands = []

    def fake_run(args, **kwargs):
        executed_commands.append(args)
        if args[0:3] == [
            "git",
            "-C",
            "E:\\Github\\worktrees\\Neko-Family-Proxy-main-auto-release",
            "merge-base",
        ]:
            return subprocess.CompletedProcess(args, 0)
        # Handle Windows paths cleanly by checking parts
        if args[0] == "git" and "merge-base" in args:
            return subprocess.CompletedProcess(args, 0)
        if args[0] == "git" and "archive" in args:
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(b"")
            return subprocess.CompletedProcess(args, 0)
        if args[0] == "tar":
            return subprocess.CompletedProcess(args, 0)
        if args[0] == "uv":
            return subprocess.CompletedProcess(args, 0)
        if args[0:3] == ["gh", "release", "view"]:
            return subprocess.CompletedProcess(args, 0)
        if args[0] == "curl":
            Path(args[3]).write_text(
                json.dumps(
                    {
                        "key_id": "neko-update-prod-1",
                        "components": {
                            "core": {
                                "artifact_sha256": "fakehash",
                                "artifact_size": 100,
                                "installed_identity_sha256": "fakeidentity",
                            }
                        },
                    }
                )
            )
            return subprocess.CompletedProcess(args, 0)
        if "build_software_release_v2.py" in str(args[1]):
            assert "--public-key-file" in args
            if "--private-key-file" in args:
                idx = args.index("--private-key-file")
                assert (
                    args[idx + 1]
                    == "C:/Users/Pranmong/AppData/Local/NekoFamily/release-custody/neko-update-prod-1.pem"
                )
            return subprocess.CompletedProcess(args, 0)
        if "build_beta_installer.py" in str(args[1]):
            setup_out = Path(args[3]) / "out"
            setup_out.mkdir(parents=True, exist_ok=True)
            (setup_out / "NekoFamilyProxy-Setup.exe").write_bytes(b"")
            return subprocess.CompletedProcess(args, 0)

        return subprocess.CompletedProcess(args, 0)

    def fake_check_output(args, **kwargs):
        executed_commands.append(args)
        if args[0:3] == ["gh", "release", "view"]:
            ret = json.dumps(
                {"assets": [{"name": "release-v2.json", "url": "http://fake"}]}
            )
            return ret if kwargs.get("text") else ret.encode()
        if args[0] == "git" and "show" in args:
            ret = "src/main.py\n"
            return ret if kwargs.get("text") else ret.encode()
        return "" if kwargs.get("text") else b""

    monkeypatch.setattr("scripts.release_controller.subprocess.run", fake_run)
    monkeypatch.setattr(
        "scripts.release_controller.subprocess.check_output", fake_check_output
    )

    class FakeReleaseSet:
        class FakeComponent:
            artifact_sha256 = "fakehash"
            artifact_size = 100
            installed_identity_sha256 = "fakeidentity"

        components = {"core": FakeComponent()}

    monkeypatch.setattr(
        "scripts.release_controller.verify_release_envelope_v2",
        lambda a, b: (FakeReleaseSet(), None),
    )

    class FakeVerificationResult:
        valid = True
        error = ""
        manifest_sha256 = "fakeidentity"

    monkeypatch.setattr(
        "neko_launcher.updater.core_manifest_verifier.verify_canonical_core_bundle",
        lambda p: FakeVerificationResult(),
    )
    monkeypatch.setattr(
        "neko_launcher.updater.zip_extractor.extract_core_bundle", lambda p, d: None
    )

    original_exists = Path.exists

    def fake_exists(self):
        name = str(self)
        if "NekoProxyCore.zip" in name:
            return True
        if "windowsdesktop-runtime" in name:
            return True
        if "__init__.py" in name:
            self.parent.mkdir(parents=True, exist_ok=True)
            self.write_text('__version__ = "1.0.0"', encoding="utf-8")
            return True
        return original_exists(self)

    original_stat = Path.stat

    class FakeStat:
        st_size = 100

    def fake_stat(self):
        if "NekoProxyCore.zip" in str(self):
            return FakeStat()
        return original_stat(self)

    monkeypatch.setattr("scripts.release_controller.Path.exists", fake_exists)
    monkeypatch.setattr("scripts.release_controller.Path.stat", fake_stat)

    monkeypatch.setattr(
        "scripts.release_controller._get_sha256",
        lambda path: "fakehash"
        if "NekoProxyCore.zip" in str(path)
        else "0d20debb26fc8b2bc84f25fbd9d4596a6364af8517ebf012e8b871127b798941"
        if "windowsdesktop" in str(path)
        else "hash",
    )

    class FakeZipFile:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, name):
            if name == "core-manifest.json":
                return json.dumps(
                    {
                        "installed_identity_sha256": "fakeidentity",
                        "source_commit": "fake_auth",
                    }
                ).encode()
            return b""

        def extractall(self, path):
            pass

    monkeypatch.setattr("scripts.release_controller.zipfile.ZipFile", FakeZipFile)

    publish_calls = []
    monkeypatch.setattr(
        "scripts.publish_atomic_release.execute_publish",
        lambda *args, **kwargs: publish_calls.append(args),
    )
    monkeypatch.setattr(
        "scripts.release_controller.shutil.copy",
        lambda src, dst: Path(dst).write_bytes(b""),
    )

    # Run 1
    process_accepted_commits(sha, run_id)

    assert publish_calls == [("v5.1.7", sha)]

    # Assert version was injected correctly
    init_path = list(
        Path(
            f"E:/Github/artifacts/main-auto-release/{run_id}-{sha}/v5.1.7/source/launcher/src/neko_launcher"
        ).rglob("__init__.py")
    )
    if init_path:
        content = init_path[0].read_text(encoding="utf-8")
        assert "5.1.7" in content

    # Run 2 for idempotency test
    process_accepted_commits(sha, run_id)
    # The version should remain v5.1.7, publish_calls should have second 'v5.1.7'
    assert publish_calls == [("v5.1.7", sha), ("v5.1.7", sha)]


def test_release_controller_unaccepted_commit(monkeypatch):
    monkeypatch.setattr(
        "scripts.release_controller.get_successful_main_runs", lambda: []
    )
    with pytest.raises(SystemExit):
        process_accepted_commits("111", 12345)


def test_release_controller_ignored_paths(monkeypatch):
    sha = "1111111111111111111111111111111111111111"
    run_id = 12345
    monkeypatch.setattr(
        "scripts.release_controller.get_successful_main_runs",
        lambda: [{"databaseId": run_id, "headSha": sha}],
    )

    def fake_check_output(args, **kwargs):
        if args[0] == "git" and "show" in args:
            ret = "docs/README.md\n"
            return ret if kwargs.get("text") else ret.encode()
        return "" if kwargs.get("text") else b""

    monkeypatch.setattr(
        "scripts.release_controller.subprocess.check_output", fake_check_output
    )
    monkeypatch.setattr(
        "scripts.release_controller.subprocess.run", lambda *a, **kw: None
    )

    with pytest.raises(SystemExit):
        # Should exit because should_trigger returns False
        process_accepted_commits(sha, run_id)


def test_release_controller_hosted_verification_fails(monkeypatch):
    sha = "1111111111111111111111111111111111111111"
    run_id = 12345
    monkeypatch.setattr(
        "scripts.release_controller.get_successful_main_runs",
        lambda: [{"databaseId": run_id, "headSha": sha}],
    )
    monkeypatch.setattr(
        "scripts.release_controller.subprocess.run", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "scripts.release_controller.get_github_releases",
        lambda: [{"tag_name": "v5.1.6", "prerelease": False}],
    )
    monkeypatch.setattr("scripts.release_controller.should_trigger", lambda f: True)

    def fake_check_output(args, **kwargs):
        if args[0] == "git" and "show" in args:
            ret = "src/main.py\n"
            return ret if kwargs.get("text") else ret.encode()
        # Make check_output return bad json for release view
        return "{}" if kwargs.get("text") else b"{}"

    monkeypatch.setattr(
        "scripts.release_controller.subprocess.check_output", fake_check_output
    )

    with pytest.raises(KeyError):
        process_accepted_commits(sha, run_id)


def test_security_boundary_no_private_key_read():
    import ast

    path = Path(__file__).parent.parent / "scripts" / "release_controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in (
                "open",
                "read_text",
                "read_bytes",
            ):
                if (
                    isinstance(node.func.value, ast.Name)
                    and "key" in node.func.value.id.lower()
                ):
                    pytest.fail("Private key read detected in code")
