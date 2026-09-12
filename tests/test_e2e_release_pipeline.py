import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from scripts.release_controller import process_accepted_commits


def create_fake_core_zip(path: Path):
    mandatory = ["NekoProxyCore.exe", "NekoProxyCore.dll", "runtime-settings.nkps", "bin/Redirector.bin", "bin/nfapi.dll", "bin/v2ray-sn.exe"]
    files_list = []
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for f in mandatory:
            p = tdp / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"123")
            files_list.append({"path": f, "size": 3, "sha256": hashlib.sha256(b"123").hexdigest()})
        manifest = {
            "rid": "win-x64",
            "executable": "NekoProxyCore.exe",
            "source_commit": "abcdef",
            "files": files_list
        }
        (tdp / "core-manifest.json").write_text(json.dumps(manifest))

        with zipfile.ZipFile(path, "w") as zf:
            for f in mandatory + ["core-manifest.json"]:
                zf.write(tdp / f, arcname=f)

def test_release_controller_e2e(monkeypatch, tmp_path):
    sha = "1111111111111111111111111111111111111111"
    run_id = 12345
    import shutil
    shutil.rmtree(f"E:/Github/artifacts/main-auto-release/{run_id}-{sha}", ignore_errors=True)

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

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )

    ephemeral_priv_path = tmp_path / "ephemeral.pem"
    ephemeral_priv_path.write_bytes(priv_bytes)

    monkeypatch.setattr("neko_launcher.updater.trust.PRODUCTION_RELEASE_PUBLIC_KEYS", {"neko-update-prod-1": pub_bytes})
    monkeypatch.setattr("scripts.release_controller.PRODUCTION_RELEASE_PUBLIC_KEYS", {"neko-update-prod-1": pub_bytes})

    fake_core_path = tmp_path / "fake_core_source.zip"
    create_fake_core_zip(fake_core_path)
    with zipfile.ZipFile(fake_core_path, "r") as zf:
        manifest_bytes = zf.read("core-manifest.json")
        fakehash = hashlib.sha256(manifest_bytes).hexdigest()

    import base64

    from neko_launcher.updater.canonical_json import canonical_json_dumps
    metadata = {
        "schema_version": 2,
        "channel": "stable",
        "release_sequence": 1,
        "release_id": "r-1",
        "mandatory": True,
        "minimum_supported_sequence": 1,
        "updater_protocol": {"minimum": 1, "maximum": 1},
        "components": {
            "launcher": {
                "version": "1.0",
                "artifact_id": "NekoLauncher.exe",
                "artifact_format": "raw-pe-v1",
                "artifact_size": 3,
                "artifact_sha256": hashlib.sha256(b"exe").hexdigest(),
                "installed_identity_sha256": hashlib.sha256(b"exe").hexdigest()
            },
            "updater": {
                "version": "1.0",
                "artifact_id": "NekoUpdater.exe",
                "artifact_format": "raw-pe-v1",
                "artifact_size": 3,
                "artifact_sha256": hashlib.sha256(b"exe").hexdigest(),
                "installed_identity_sha256": hashlib.sha256(b"exe").hexdigest()
            },
            "core": {
                "version": "1.0",
                "artifact_id": "NekoProxyCore.zip",
                "artifact_format": "zip-core-v1",
                "artifact_size": fake_core_path.stat().st_size,
                "artifact_sha256": hashlib.sha256(fake_core_path.read_bytes()).hexdigest(),
                "installed_identity_sha256": fakehash
            }
        }
    }
    payload = canonical_json_dumps(metadata)
    signature = private_key.sign(payload)
    signed_envelope = {
        "envelope_version": 1,
        "key_id": "neko-update-prod-1",
        "payload_b64": base64.b64encode(payload).decode("ascii"),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
    }
    signed_json = json.dumps(signed_envelope)

    executed_commands = []

    def fake_run(args, **kwargs):
        executed_commands.append(args)
        if args[0] == "git" and "merge-base" in args:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "git" and "archive" in args:
            out_idx = args.index("-o") + 1
            create_fake_core_zip(Path(args[out_idx]))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "tar":
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "uv":
            for i, a in enumerate(args):
                if a == "--output":
                    Path(args[i+1]).parent.mkdir(parents=True, exist_ok=True)
                    Path(args[i+1]).write_bytes(b"exe")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0:3] == ["gh", "release", "view"]:
            return subprocess.CompletedProcess(args, 0, stdout='{"targetCommitish": "fake"}', stderr="")
        if args[0:2] == ["gh", "api"]:
            if kwargs.get("stdout"):
                if args[2].endswith("2"): # manifest id
                    kwargs["stdout"].write(signed_json.encode())
                elif args[2].endswith("1"): # core id
                    kwargs["stdout"].write(fake_core_path.read_bytes())
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "curl":
            Path(args[3]).write_text(signed_json)
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if "build_software_release_v2.py" in str(args[1]):
            args = list(args)
            idx = args.index("--private-key-file")
            args[idx+1] = str(ephemeral_priv_path)
            from scripts.build_software_release_v2 import main as b_main
            try:
                ret = b_main(args[2:])
                if ret != 0:
                    raise RuntimeError(f"build_software_release_v2 failed with {ret}")
            except Exception:
                import traceback
                traceback.print_exc()
                raise
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if "build_beta_installer.py" in str(args[1]):
            idx = args.index("--release-version")
            assert args[idx+1] == "5.1.1"
            setup_out = Path(args[3]) / "out"
            setup_out.mkdir(parents=True, exist_ok=True)
            (setup_out / "NekoFamilyProxy-Setup.exe").write_bytes(b"setup_exe")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def fake_check_output(args, **kwargs):
        executed_commands.append(args)
        if args[0:2] == ["gh", "api"] and "releases/tags" in args[2]:
            ret = json.dumps({
                "id": 123, "tag_name": "v5.1.0", "target_commitish": "1111111111111111111111111111111111111111", "draft": False,
                "assets": [{"name": "NekoProxyCore.zip", "id": 1, "size": 100}, {"name": "release-v2.json", "id": 2, "size": 100}, {"name": "NekoLauncher.exe", "id": 3, "size": 3}, {"name": "NekoUpdater.exe", "id": 4, "size": 3}, {"name": "NekoFamilyProxy-Setup.exe", "id": 5, "size": 9}]
            })
            return ret if kwargs.get("text") else ret.encode()
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
    monkeypatch.setattr("scripts.release_controller.subprocess.check_output", fake_check_output)

    publish_calls = []
    monkeypatch.setattr(
        "scripts.publish_atomic_release.execute_publish",
        lambda *args, **kwargs: publish_calls.append(args),
    )

    from pathlib import Path
    real_exists = Path.exists
    def fake_exists(self):
        if "__init__.py" in str(self) and "launcher" in str(self):
            self.parent.mkdir(parents=True, exist_ok=True)
            if not real_exists(self):
                self.write_text('__version__ = "5.1.0"', encoding="utf-8")
            return True
        if "pyproject.toml" in str(self) and "launcher" in str(self):
            self.parent.mkdir(parents=True, exist_ok=True)
            if not real_exists(self):
                self.write_text('version = "5.1.0"', encoding="utf-8")
            return True
        if "NekoProxyCore.zip" in str(self) or "windowsdesktop-runtime" in str(self):
            return True
        return real_exists(self)

    monkeypatch.setattr("scripts.release_controller.Path.exists", fake_exists)

    real_stat = Path.stat
    class FakeStat:
        def __init__(self, size):
            self.st_size = size
            self.st_mode = 33206
    def fake_stat(self):
        if "NekoProxyCore.zip" in str(self):
            return FakeStat(fake_core_path.stat().st_size)
        return real_stat(self)
    monkeypatch.setattr("scripts.release_controller.Path.stat", fake_stat)

    monkeypatch.setattr(
        "scripts.release_controller._get_sha256",
        lambda path: hashlib.sha256(fake_core_path.read_bytes()).hexdigest() if "NekoProxyCore.zip" in str(path)
        else "0d20debb26fc8b2bc84f25fbd9d4596a6364af8517ebf012e8b871127b798941" if "windowsdesktop" in str(path)
        else hashlib.sha256(b"exe").hexdigest()
    )

    real_zipfile = zipfile.ZipFile
    def fake_zipfile(path, *args, **kwargs):
        if "NekoProxyCore.zip" in str(path):
            return real_zipfile(fake_core_path, *args, **kwargs)
        return real_zipfile(path, *args, **kwargs)
    monkeypatch.setattr("scripts.release_controller.zipfile.ZipFile", fake_zipfile)
    monkeypatch.setattr("neko_launcher.updater.zip_extractor.zipfile.ZipFile", fake_zipfile)

    import shutil
    real_copy = shutil.copy
    def fake_copy(src, dst):
        if "NekoProxyCore.zip" in str(dst):
            real_copy(fake_core_path, dst)
        else:
            Path(dst).write_bytes(b"exe")
    monkeypatch.setattr("scripts.release_controller.shutil.copy", fake_copy)

    # Run 1
    process_accepted_commits(sha, run_id)

    assert publish_calls == [("v5.1.1", sha)]

    metadata_path = Path(f"E:/Github/artifacts/main-auto-release/{run_id}-{sha}/5.1.1/evidence/base-metadata.json")
    metadata_content = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata_content["release_sequence"] == 5
    assert metadata_content["release_id"] == "stable-0005"
    assert metadata_content["components"]["core"]["version"] == "5.1.1"

    init_path = list(
        Path(f"E:/Github/artifacts/main-auto-release/{run_id}-{sha}/5.1.1/source/launcher/src/neko_launcher").rglob("__init__.py")
    )
    if init_path:
        content = init_path[0].read_text(encoding="utf-8")
        assert "5.1.1" in content

    # Run 2 for idempotency test
    process_accepted_commits(sha, run_id)
    assert publish_calls == [("v5.1.1", sha), ("v5.1.1", sha)]


def test_release_controller_unaccepted_commit(monkeypatch):
    monkeypatch.setattr("scripts.release_controller.get_successful_main_runs", list)
    with pytest.raises(SystemExit):
        process_accepted_commits("111", 12345)


def test_release_controller_ignored_paths(monkeypatch):
    sha = "1111111111111111111111111111111111111111"
    run_id = 12345
    import shutil
    shutil.rmtree(f"E:/Github/artifacts/main-auto-release/{run_id}-{sha}", ignore_errors=True)
    monkeypatch.setattr("scripts.release_controller.get_successful_main_runs", lambda: [{"databaseId": run_id, "headSha": sha}])

    def fake_check_output(args, **kwargs):
        if args[0] == "git" and "show" in args:
            ret = "docs/README.md\n"
            return ret if kwargs.get("text") else ret.encode()
        return "" if kwargs.get("text") else b""

    monkeypatch.setattr("scripts.release_controller.subprocess.check_output", fake_check_output)
    monkeypatch.setattr("scripts.release_controller.subprocess.run", lambda *a, **kw: None)

    with pytest.raises(SystemExit):
        process_accepted_commits(sha, run_id)


def test_security_boundary_no_private_key_read():
    import ast
    path = Path(__file__).parent.parent / "scripts" / "release_controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in ("open", "read_text", "read_bytes"):
                if isinstance(node.func.value, ast.Name) and "key" in node.func.value.id.lower():
                    pytest.fail("Private key read detected in code")

def test_release_controller_mismatch_fails_closed(monkeypatch, tmp_path):
    sha = "2222222222222222222222222222222222222222"
    run_id = 54321

    import shutil
    shutil.rmtree(f"E:/Github/artifacts/main-auto-release/{run_id}-{sha}", ignore_errors=True)

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

    def fake_run(args, **kwargs):
        import subprocess
        from pathlib import Path
        if args[0] == "git" and "merge-base" in args:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "git" and "archive" in args:
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(b"tar")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "tar":
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def fake_check_output(args, **kwargs):
        if args[0] == "git" and "show" in args:
            ret = "src/main.py\n"
            return ret if kwargs.get("text") else ret.encode()
        return "" if kwargs.get("text") else b""

    monkeypatch.setattr("scripts.release_controller.subprocess.run", fake_run)
    monkeypatch.setattr("scripts.release_controller.subprocess.check_output", fake_check_output)

    from pathlib import Path
    real_exists = Path.exists
    def fake_exists(self):
        if "__init__.py" in str(self) and "launcher" in str(self):
            self.parent.mkdir(parents=True, exist_ok=True)
            if not real_exists(self):
                self.write_text('__version__ = "5.1.2"', encoding="utf-8")
            return True
        if "pyproject.toml" in str(self) and "launcher" in str(self):
            self.parent.mkdir(parents=True, exist_ok=True)
            if not real_exists(self):
                self.write_text('version = "5.1.2"', encoding="utf-8")
            return True
        return real_exists(self)
    monkeypatch.setattr("scripts.release_controller.Path.exists", fake_exists)

    import pytest
    with pytest.raises(SystemExit):
        process_accepted_commits(sha, run_id)



def test_verify_and_fetch_core_draft_fails_closed(monkeypatch, tmp_path):
    from scripts.release_controller import verify_and_fetch_core
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: b'{"draft": true}')
    import pytest
    with pytest.raises(RuntimeError, match="draft or prerelease"):
        verify_and_fetch_core("v5.1.0", tmp_path)

def test_verify_and_fetch_core_missing_asset_fails_closed(monkeypatch, tmp_path):
    from scripts.release_controller import verify_and_fetch_core
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: b'{"draft": false, "id": 1, "assets": [{"name": "release-v2.json", "id": 1}]}')
    import pytest
    with pytest.raises(RuntimeError, match="Missing required assets"):
        verify_and_fetch_core("v5.1.0", tmp_path)

def test_verify_and_fetch_core_duplicate_asset_fails_closed(monkeypatch, tmp_path):
    from scripts.release_controller import verify_and_fetch_core
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: b'{"draft": false, "id": 1, "assets": [{"name": "release-v2.json", "id": 1}, {"name": "release-v2.json", "id": 2}]}')
    import pytest
    with pytest.raises(RuntimeError, match="Duplicate release-v2.json assets"):
        verify_and_fetch_core("v5.1.0", tmp_path)

def test_verify_and_fetch_core_signature_fails_closed(monkeypatch, tmp_path):
    from scripts.release_controller import verify_and_fetch_core
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: b'{"draft": false, "id": 1, "assets": [{"name": "release-v2.json", "id": 1}, {"name": "NekoProxyCore.zip", "id": 2}]}')
    
    import subprocess
    def fake_run(args, **kwargs):
        if "gh" in args and any("releases/assets/1" in a for a in args):
            kwargs["stdout"].write(b'{"envelope_version": 1, "key_id": "neko-update-prod-1", "payload_b64": "YmFk", "signature_b64": "YmFk"}')
            kwargs["stdout"].flush()
        if "gh" in args and any("releases/assets/2" in a for a in args):
            kwargs["stdout"].write(b"dummy")
            kwargs["stdout"].flush()
        return subprocess.CompletedProcess(args, 0)
    
    monkeypatch.setattr("subprocess.run", fake_run)
    import pytest
    with pytest.raises(Exception, match="Incorrect padding|signature|Invalid"):
        verify_and_fetch_core("v5.1.0", tmp_path)

def setup_mock_verify_and_fetch_core(monkeypatch, tmp_path, override_manifest=None, override_core_bytes=b"dummy"):
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: b'{"draft": false, "id": 1, "assets": [{"name": "release-v2.json", "id": 1}, {"name": "NekoProxyCore.zip", "id": 2}]}')
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    monkeypatch.setattr("neko_launcher.updater.trust.PRODUCTION_RELEASE_PUBLIC_KEYS", {"neko-update-prod-1": pub_bytes})
    monkeypatch.setattr("scripts.release_controller.PRODUCTION_RELEASE_PUBLIC_KEYS", {"neko-update-prod-1": pub_bytes})

    import hashlib
    core_hash = hashlib.sha256(override_core_bytes).hexdigest()
    
    metadata = {
        "schema_version": 2,
        "channel": "stable",
        "release_sequence": 1,
        "release_id": "r-1",
        "mandatory": True,
        "minimum_supported_sequence": 1,
        "updater_protocol": {"minimum": 1, "maximum": 1},
        "components": {
            "launcher": {
                "version": "1.0",
                "artifact_id": "l",
                "artifact_format": "raw-pe-v1",
                "artifact_size": 3,
                "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "installed_identity_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            },
            "updater": {
                "version": "1.0",
                "artifact_id": "u",
                "artifact_format": "raw-pe-v1",
                "artifact_size": 3,
                "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "installed_identity_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            },
            "core": {
                "version": "1.0",
                "artifact_id": "NekoProxyCore.zip",
                "artifact_format": "zip-core-v1",
                "artifact_size": len(override_core_bytes),
                "artifact_sha256": core_hash,
                "installed_identity_sha256": core_hash
            }
        }
    }
    if override_manifest:
        metadata.update(override_manifest)
        if "components" in override_manifest:
            metadata["components"] = override_manifest["components"]

    import base64
    from neko_launcher.updater.canonical_json import canonical_json_dumps
    import json
    payload = canonical_json_dumps(metadata)
    signature = private_key.sign(payload)
    signed_envelope = {
        "envelope_version": 1,
        "key_id": "neko-update-prod-1",
        "payload_b64": base64.b64encode(payload).decode("ascii"),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
    }
    signed_json = json.dumps(signed_envelope)

    import subprocess
    def fake_run(args, **kwargs):
        if "gh" in args and any("releases/assets/1" in a for a in args):
            kwargs["stdout"].write(signed_json.encode())
            kwargs["stdout"].flush()
        if "gh" in args and any("releases/assets/2" in a for a in args):
            kwargs["stdout"].write(override_core_bytes)
            kwargs["stdout"].flush()
        return subprocess.CompletedProcess(args, 0)
    
    monkeypatch.setattr("subprocess.run", fake_run)
    
    class MockVerifier:
        valid = True
        error = None
        manifest_sha256 = core_hash
    monkeypatch.setattr("neko_launcher.updater.zip_extractor.extract_core_bundle", lambda *a, **k: None)
    monkeypatch.setattr("neko_launcher.updater.core_manifest_verifier.verify_canonical_core_bundle", lambda *a, **k: MockVerifier())

    return MockVerifier

def test_verify_and_fetch_core_channel_mismatch(monkeypatch, tmp_path):
    setup_mock_verify_and_fetch_core(monkeypatch, tmp_path, override_manifest={"channel": "beta"})
    from scripts.release_controller import verify_and_fetch_core
    import pytest
    with pytest.raises(Exception, match="channel"):
        verify_and_fetch_core("v5.1.0", tmp_path)

def test_verify_and_fetch_core_artifact_id_mismatch(monkeypatch, tmp_path):
    comps = {
        "launcher": {
            "version": "1.0", "artifact_id": "l", "artifact_format": "raw-pe-v1", "artifact_size": 3,
            "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "installed_identity_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        },
        "updater": {
            "version": "1.0", "artifact_id": "u", "artifact_format": "raw-pe-v1", "artifact_size": 3,
            "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "installed_identity_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        },
        "core": {
            "version": "1.0", "artifact_id": "wrong", "artifact_format": "zip-core-v1", "artifact_size": 5,
            "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "installed_identity_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        }
    }
    setup_mock_verify_and_fetch_core(monkeypatch, tmp_path, override_manifest={"components": comps})
    from scripts.release_controller import verify_and_fetch_core
    import pytest
    with pytest.raises(RuntimeError, match="artifact_id mismatch"):
        verify_and_fetch_core("v5.1.0", tmp_path)

def test_verify_and_fetch_core_hash_mismatch(monkeypatch, tmp_path):
    comps = {
        "launcher": {
            "version": "1.0", "artifact_id": "l", "artifact_format": "raw-pe-v1", "artifact_size": 3,
            "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "installed_identity_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        },
        "updater": {
            "version": "1.0", "artifact_id": "u", "artifact_format": "raw-pe-v1", "artifact_size": 3,
            "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "installed_identity_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        },
        "core": {
            "version": "1.0", "artifact_id": "NekoProxyCore.zip", "artifact_format": "zip-core-v1", "artifact_size": 5,
            "artifact_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "installed_identity_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        }
    }
    setup_mock_verify_and_fetch_core(monkeypatch, tmp_path, override_manifest={"components": comps}, override_core_bytes=b"dummy")
    from scripts.release_controller import verify_and_fetch_core
    import pytest
    with pytest.raises(RuntimeError, match="does not match .* signature"):
        verify_and_fetch_core("v5.1.0", tmp_path)

def test_verify_and_fetch_core_canonical_failure(monkeypatch, tmp_path):
    MockVerifier = setup_mock_verify_and_fetch_core(monkeypatch, tmp_path)
    MockVerifier.valid = False
    MockVerifier.error = "bad bundle"
    from scripts.release_controller import verify_and_fetch_core
    import pytest
    with pytest.raises(RuntimeError, match="Core bundle verification failed"):
        verify_and_fetch_core("v5.1.0", tmp_path)

def test_verify_and_fetch_core_installed_identity_mismatch(monkeypatch, tmp_path):
    MockVerifier = setup_mock_verify_and_fetch_core(monkeypatch, tmp_path)
    MockVerifier.manifest_sha256 = "completely_different"
    from scripts.release_controller import verify_and_fetch_core
    import pytest
    with pytest.raises(RuntimeError, match="installed identity mismatch"):
        verify_and_fetch_core("v5.1.0", tmp_path)
