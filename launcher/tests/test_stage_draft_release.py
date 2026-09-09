from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from tests.software_update_helpers import TEST_PUBLIC_KEY, signed_envelope


SCRIPT = Path(__file__).parents[2] / "scripts" / "stage_draft_release.py"
TARGET = "b4dab9e9571cbe6d05c6fdb17617137b302856d2"
TAG = "v5.1.0a3"


def load_module():
    assert SCRIPT.is_file(), "scripts/stage_draft_release.py must be implemented"
    spec = importlib.util.spec_from_file_location("stage_draft_release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def use_test_release_public_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS

    monkeypatch.setitem(
        PRODUCTION_RELEASE_PUBLIC_KEYS, "neko-update-prod-1", TEST_PUBLIC_KEY
    )


class FakeExecutor:
    def __init__(self, *, dirty: bool = False, wrong_tag: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.dirty = dirty
        self.wrong_tag = wrong_tag

    def run(self, args: list[str], *, capture_output: bool = True):
        self.calls.append(args)
        if args[0] == "git" and "status" in args:
            out = " M bad.txt\n" if self.dirty else ""
        elif args[0] == "git" and "rev-parse" in args:
            out = ("a" * 40 if self.wrong_tag else TARGET) + "\n"
        elif args[:3] == ["gh", "release", "create"]:
            out = ""
        elif args[:3] == ["gh", "release", "upload"]:
            out = ""
        elif args[:3] == ["gh", "api", "repos/"]:
            out = ""
        elif args[:2] == ["gh", "api"]:
            if args[2].endswith(f"/releases/tags/{TAG}"):
                out = json.dumps({"id": 901, "draft": False, "assets": []})
            elif args[2].endswith("/releases/901"):
                out = json.dumps(
                    {
                        "id": 901,
                        "tag_name": TAG,
                        "target_commitish": TARGET,
                        "draft": True,
                        "prerelease": False,
                        "assets": [
                            {"id": i + 10, "name": name}
                            for i, name in enumerate(
                                ("NekoLauncher.exe", "NekoUpdater.exe", "NekoProxyCore.zip", "release-v2.json")
                            )
                        ] + [{"id": 99, "name": "SHA256SUMS.txt"}],
                    }
                )
            else:
                raise AssertionError(f"unexpected API endpoint: {args}")
        else:
            raise AssertionError(f"unexpected command: {args}")
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def make_stage(path: Path) -> Path:
    payloads = {
        "NekoLauncher.exe": b"launcher",
        "NekoUpdater.exe": b"updater",
        "NekoProxyCore.zip": b"core",
    }
    for name, data in payloads.items():
        (path / name).write_bytes(data)
    components = {}
    for component, name, fmt in (
        ("launcher", "NekoLauncher.exe", "raw-pe-v1"),
        ("updater", "NekoUpdater.exe", "raw-pe-v1"),
        ("core", "NekoProxyCore.zip", "zip-core-v1"),
    ):
        data = payloads[name]
        components[component] = {
            "version": "5.1.0a3",
            "artifact_id": name,
            "artifact_sha256": hashlib.sha256(data).hexdigest(),
            "artifact_size": len(data),
            "artifact_format": fmt,
            "installed_identity_sha256": (
                hashlib.sha256(data).hexdigest() if component != "core" else "1" * 64
            ),
        }
    payload = {
        "schema_version": 2,
        "channel": "stable",
        "release_sequence": 1,
        "minimum_supported_sequence": 1,
        "release_id": "stable-0001",
        "updater_protocol": {"minimum": 1, "maximum": 1},
        "mandatory": False,
        "components": components,
    }
    envelope = signed_envelope(payload, key_id="neko-update-prod-1")
    assert set(envelope) == {
        "envelope_version", "key_id", "payload_b64", "signature_b64"
    }
    (path / "release-v2.json").write_bytes(canonical(envelope))
    return path


def validate(module, stage: Path, executor: FakeExecutor):
    return module.validate_staging_preconditions(
        staging_dir=stage, tag=TAG, target_commit=TARGET, repo_root=SCRIPT.parents[1], executor=executor
    )


def test_argument_parsing() -> None:
    module = load_module()
    args = module.parse_args(["--staging-dir", "candidate", "--tag", TAG, "--target-commit", TARGET, "--dry-run"])
    assert args.staging_dir == Path("candidate")
    assert args.tag == TAG and args.target_commit == TARGET and args.dry_run is True


@pytest.mark.parametrize("case", ["dirty", "wrong_sha", "wrong_tag", "missing", "extra", "empty", "large_manifest", "noncanonical"])
def test_validation_fails_closed(tmp_path: Path, case: str) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    executor = FakeExecutor(dirty=case == "dirty", wrong_tag=case == "wrong_tag")
    target = "bad" if case == "wrong_sha" else TARGET
    if case == "missing":
        (stage / "NekoUpdater.exe").unlink()
    elif case == "extra":
        (stage / "untrusted.txt").write_text("x")
    elif case == "empty":
        (stage / "NekoProxyCore.zip").write_bytes(b"")
    elif case == "large_manifest":
        (stage / "release-v2.json").write_bytes(b"x" * 65537)
    elif case == "noncanonical":
        doc = json.loads((stage / "release-v2.json").read_bytes())
        (stage / "release-v2.json").write_text(json.dumps(doc, indent=2))
    with pytest.raises(module.StageDraftReleaseError):
        module.validate_staging_preconditions(
            staging_dir=stage, tag=TAG, target_commit=target, repo_root=SCRIPT.parents[1], executor=executor
        )
    assert not any(call[:2] == ["gh", "release"] for call in executor.calls)


@pytest.mark.parametrize("field", ["artifact_size", "artifact_sha256"])
def test_manifest_descriptor_mismatch(tmp_path: Path, field: str) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    payloads = {"NekoLauncher.exe": b"launcher", "NekoUpdater.exe": b"updater", "NekoProxyCore.zip": b"core"}
    payload = {
        "schema_version": 2, "channel": "stable", "release_sequence": 1,
        "minimum_supported_sequence": 1, "release_id": "stable-0001", "mandatory": False,
        "updater_protocol": {"minimum": 1, "maximum": 1}, "components": {},
    }
    for component, name, fmt in (
        ("launcher", "NekoLauncher.exe", "raw-pe-v1"),
        ("updater", "NekoUpdater.exe", "raw-pe-v1"),
        ("core", "NekoProxyCore.zip", "zip-core-v1"),
    ):
        digest = hashlib.sha256(payloads[name]).hexdigest()
        payload["components"][component] = {
            "version": "5.1.0a3", "artifact_id": name, "artifact_sha256": digest,
            "artifact_size": len(payloads[name]), "artifact_format": fmt,
            "installed_identity_sha256": digest if component != "core" else "1" * 64,
        }
    payload["components"]["launcher"][field] = 99 if field == "artifact_size" else "0" * 64
    doc = signed_envelope(payload, key_id="neko-update-prod-1")
    (stage / "release-v2.json").write_bytes(canonical(doc))
    with pytest.raises(module.StageDraftReleaseError):
        validate(module, stage, FakeExecutor())


def test_dry_run_has_no_github_mutation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = load_module()
    executor = FakeExecutor()
    assert module.stage_draft_release(
        staging_dir=make_stage(tmp_path), tag=TAG, target_commit=TARGET, dry_run=True, executor=executor
    ) is None
    output = capsys.readouterr().out
    assert "gh release create" in output and "--draft" in output and "--clobber=false" in output
    assert not any(call[0] == "gh" for call in executor.calls)


def test_execution_stages_and_returns_immutable_evidence(tmp_path: Path) -> None:
    module = load_module()
    executor = FakeExecutor()
    evidence = module.stage_draft_release(
        staging_dir=make_stage(tmp_path), tag=TAG, target_commit=TARGET, executor=executor
    )
    assert evidence.release_id == 901
    assert evidence.assets == {"NekoLauncher.exe": 10, "NekoUpdater.exe": 11, "NekoProxyCore.zip": 12, "release-v2.json": 13}
    assert evidence.dispatch_command == (
        f"gh workflow run release.yml --ref {TAG} -f publish_release=true -f release_id=901 "
        f"-f release_tag={TAG} -f expected_target={TARGET}"
    )
    assert not any(call[:3] == ["gh", "workflow", "run"] for call in executor.calls)
    create = next(call for call in executor.calls if call[:3] == ["gh", "release", "create"])
    upload = next(call for call in executor.calls if call[:3] == ["gh", "release", "upload"])
    assert [TAG, "--target", TARGET, "--draft", "--prerelease=false"] == create[3:8]
    assert "--clobber=false" in upload
    api_calls = [call for call in executor.calls if call[:2] == ["gh", "api"]]
    assert [call[2] for call in api_calls] == [
        f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/tags/{TAG}",
        "repos/Valeneko-pranmong/Neko-Family-Proxy/releases/901",
    ]
    assert not any("workflow" in part for call in executor.calls for part in call)
