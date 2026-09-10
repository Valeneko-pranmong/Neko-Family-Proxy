from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import zipfile

import pytest

from tests.software_update_helpers import TEST_PUBLIC_KEY, signed_envelope


SCRIPT = Path(__file__).parents[2] / "scripts" / "stage_draft_release.py"
TARGET = "b4dab9e9571cbe6d05c6fdb17617137b302856d2"
TAG = "v5.1.3"


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
    def __init__(
        self,
        *,
        dirty: bool = False,
        wrong_tag: bool = False,
        remote_ref: Any = "default",
        remote_tags: dict[str, Any] | None = None,
        releases: list[dict[str, Any]] | None = None,
        mismatched_asset_size: str | None = None,
        prerelease: bool = False,
    ) -> None:
        self.calls: list[list[str]] = []
        self.dirty = dirty
        self.wrong_tag = wrong_tag
        self.prerelease = prerelease
        self.remote_ref = (
            {"object": {"type": "commit", "sha": TARGET}}
            if remote_ref == "default"
            else remote_ref
        )
        self.remote_tags = remote_tags or {}
        self.mismatched_asset_size = mismatched_asset_size
        self.releases = (
            [
                {
                    "id": 901,
                    "tag_name": TAG,
                    "target_commitish": TARGET,
                    "draft": True,
                }
            ]
            if releases is None
            else releases
        )

    def run(self, args: list[str], *, capture_output: bool = True):
        self.calls.append(args)
        if args[0] == "git" and "status" in args:
            out = " M bad.txt\n" if self.dirty else ""
        elif args[0] == "git" and "rev-parse" in args:
            out = ("a" * 40 if self.wrong_tag else TARGET) + "\n"
        elif args[:3] == ["gh", "release", "create"]:
            out = ""
        elif args[:3] == ["gh", "release", "upload"]:
            self.uploaded_sizes = {
                Path(value).name: Path(value).stat().st_size
                for value in args[4 : args.index("--clobber=false")]
            }
            out = ""
        elif args[:3] == ["gh", "api", "repos/"]:
            out = ""
        elif args[:2] == ["gh", "api"]:
            if "/git/ref/tags/" in args[2]:
                out = json.dumps(self.remote_ref)
            elif "/git/tags/" in args[2]:
                tag_sha = args[2].rsplit("/", 1)[-1]
                out = json.dumps(self.remote_tags[tag_sha])
            elif args[2].endswith("/releases?per_page=100"):
                out = json.dumps([self.releases])
            elif args[2].endswith(f"/releases/tags/{TAG}"):
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="HTTP 404")
            elif args[2].endswith("/releases/901"):
                out = json.dumps(
                    {
                        "id": 901,
                        "tag_name": TAG,
                        "target_commitish": TARGET,
                        "draft": True,
                        "prerelease": self.prerelease,
                        "assets": [
                            {
                                "id": i + 10,
                                "name": name,
                                "size": (
                                    self.uploaded_sizes[name] + 1
                                    if name == self.mismatched_asset_size
                                    else self.uploaded_sizes[name]
                                ),
                            }
                            for i, name in enumerate(
                                ("NekoFamilyProxy-Setup.exe", "NekoLauncher.exe", "NekoUpdater.exe", "NekoProxyCore.zip", "release-v2.json")
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


def _make_core_zip(path: Path) -> tuple[bytes, str]:
    core_file = b"minimal core executable"
    files = {
        "NekoProxyCore.exe": core_file,
        "NekoProxyCore.dll": b"dummy",
        "runtime-settings.nkps": b"dummy",
        "bin/Redirector.bin": b"dummy",
        "bin/nfapi.dll": b"dummy",
        "bin/v2ray-sn.exe": b"dummy",
    }
    files_array = [
        {
            "path": k,
            "size": len(v),
            "sha256": hashlib.sha256(v).hexdigest(),
        }
        for k, v in sorted(files.items())
    ]
    manifest = {
        "rid": "win-x64",
        "executable": "NekoProxyCore.exe",
        "source_commit": TARGET,
        "files": files_array,
    }
    manifest_bytes = canonical(manifest)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("core-manifest.json", manifest_bytes)
        for k, v in files.items():
            archive.writestr(k, v)
    return path.read_bytes(), hashlib.sha256(manifest_bytes).hexdigest()


def make_stage(
    path: Path,
    *,
    core_identity: str | None = None,
    sequence: int = 7,
    minimum_supported_sequence: int = 1,
    release_id: str = "stable-0007",
) -> Path:
    core_bytes, actual_core_identity = _make_core_zip(path / "NekoProxyCore.zip")
    payloads = {
        "NekoFamilyProxy-Setup.exe": b"setup", "NekoLauncher.exe": b"launcher",
        "NekoUpdater.exe": b"updater",
        "NekoProxyCore.zip": core_bytes,
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
            "version": "5.1.3",
            "artifact_id": name,
            "artifact_sha256": hashlib.sha256(data).hexdigest(),
            "artifact_size": len(data),
            "artifact_format": fmt,
            "installed_identity_sha256": (
                hashlib.sha256(data).hexdigest()
                if component != "core"
                else core_identity or actual_core_identity
            ),
        }
    payload = {
        "schema_version": 2,
        "channel": "stable",
        "release_sequence": sequence,
        "minimum_supported_sequence": minimum_supported_sequence,
        "release_id": release_id,
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


def test_script_imports_launcher_from_unrelated_cwd_without_pythonpath(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import importlib.util, pathlib, sys; "
                f"p=pathlib.Path({str(SCRIPT)!r}); "
                "s=importlib.util.spec_from_file_location('isolated_stage', p); "
                "m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; "
                "s.loader.exec_module(m); m._ensure_launcher_import_path(); "
                "import neko_launcher; print(pathlib.Path(neko_launcher.__file__).resolve())"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert str((SCRIPT.parents[1] / "launcher" / "src").resolve()) in result.stdout


def test_manifest_signature_setup_error_is_not_reported_as_crypto_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    real_import = builtins.__import__

    def reject_launcher_import(name, *args, **kwargs):
        if name.startswith("neko_launcher"):
            raise ModuleNotFoundError("No module named 'neko_launcher'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_launcher_import)
    with pytest.raises(ModuleNotFoundError):
        module._verify_manifest_signature({})


def test_argument_parsing() -> None:
    module = load_module()
    args = module.parse_args(["--staging-dir", "candidate", "--tag", TAG, "--target-commit", TARGET, "--dry-run"])
    assert args.staging_dir == Path("candidate")
    assert args.tag == TAG and args.target_commit == TARGET and args.dry_run is True


def test_argument_parsing_rejects_caller_selected_repository() -> None:
    module = load_module()
    with pytest.raises(SystemExit):
        module.parse_args(
            [
                "--staging-dir",
                "candidate",
                "--tag",
                TAG,
                "--target-commit",
                TARGET,
                "--repo",
                "evil/example",
            ]
        )


def test_public_staging_path_has_no_repository_authority_parameter() -> None:
    import inspect

    module = load_module()
    assert "repo" not in inspect.signature(module.stage_draft_release).parameters


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
    payloads = {"NekoFamilyProxy-Setup.exe": b"setup", "NekoLauncher.exe": b"launcher", "NekoUpdater.exe": b"updater", "NekoProxyCore.zip": b"core"}
    payload = {
        "schema_version": 2, "channel": "stable", "release_sequence": 7,
        "minimum_supported_sequence": 1, "release_id": "stable-0007", "mandatory": False,
        "updater_protocol": {"minimum": 1, "maximum": 1}, "components": {},
    }
    for component, name, fmt in (
        ("launcher", "NekoLauncher.exe", "raw-pe-v1"),
        ("updater", "NekoUpdater.exe", "raw-pe-v1"),
        ("core", "NekoProxyCore.zip", "zip-core-v1"),
    ):
        digest = hashlib.sha256(payloads[name]).hexdigest()
        payload["components"][component] = {
            "version": "5.1.3", "artifact_id": name, "artifact_sha256": digest,
            "artifact_size": len(payloads[name]), "artifact_format": fmt,
            "installed_identity_sha256": digest if component != "core" else "1" * 64,
        }
    payload["components"]["launcher"][field] = 99 if field == "artifact_size" else "0" * 64
    if field == "artifact_sha256":
        payload["components"]["launcher"]["installed_identity_sha256"] = "0" * 64
    doc = signed_envelope(payload, key_id="neko-update-prod-1")
    (stage / "release-v2.json").write_bytes(canonical(doc))
    with pytest.raises(
        module.StageDraftReleaseError, match="Manifest descriptor mismatch: launcher"
    ):
        validate(module, stage, FakeExecutor())


@pytest.mark.parametrize(
    "authority",
    [
        {"sequence": 1, "release_id": "stable-0001"},  # spent, unpublished
        {"sequence": 2, "release_id": "stable-0002"},  # published alpha history
        {"sequence": 2, "release_id": "stable-0001"},
        {"sequence": 1, "release_id": "stable-0007"},
        {"sequence": 2, "release_id": "stable-9999"},
    ],
)
def test_recovery_authority_mismatch_fails_before_github_mutation(
    tmp_path: Path, authority: dict[str, Any]
) -> None:
    module = load_module()
    executor = FakeExecutor()
    with pytest.raises(module.StageDraftReleaseError, match="Stable-release authority mismatch"):
        module.stage_draft_release(
            staging_dir=make_stage(tmp_path, **authority),
            tag=TAG,
            target_commit=TARGET,
            executor=executor,
        )
    assert not any(call[0] == "gh" for call in executor.calls)


def test_recovery_minimum_sequence_two_fails_closed(tmp_path: Path) -> None:
    module = load_module()
    executor = FakeExecutor()
    with pytest.raises(module.StageDraftReleaseError):
        module.stage_draft_release(
            staging_dir=make_stage(tmp_path, minimum_supported_sequence=2),
            tag=TAG,
            target_commit=TARGET,
            executor=executor,
        )
    assert not any(call[0] == "gh" for call in executor.calls)


def test_core_installed_identity_mismatch_fails_before_github_mutation(
    tmp_path: Path,
) -> None:
    module = load_module()
    executor = FakeExecutor()
    with pytest.raises(module.StageDraftReleaseError):
        module.stage_draft_release(
            staging_dir=make_stage(tmp_path, core_identity="f" * 64),
            tag=TAG,
            target_commit=TARGET,
            executor=executor,
        )
    assert not any(call[0] == "gh" for call in executor.calls)


def test_malformed_core_bundle_fails_before_github_mutation(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    (stage / "NekoProxyCore.zip").write_bytes(b"not a zip")
    executor = FakeExecutor()
    with pytest.raises(module.StageDraftReleaseError):
        module.stage_draft_release(
            staging_dir=stage, tag=TAG, target_commit=TARGET, executor=executor
        )
    assert not any(call[0] == "gh" for call in executor.calls)


@pytest.mark.parametrize(
    "remote_ref",
    [
        None,
        {},
        {"object": {"type": "commit", "sha": "a" * 40}},
        {"object": {"type": "blob", "sha": TARGET}},
    ],
)
def test_remote_tag_failure_precedes_release_mutation(
    tmp_path: Path, remote_ref: Any
) -> None:
    module = load_module()
    executor = FakeExecutor(remote_ref=remote_ref)
    with pytest.raises(module.StageDraftReleaseError):
        module.stage_draft_release(
            staging_dir=make_stage(tmp_path),
            tag=TAG,
            target_commit=TARGET,
            executor=executor,
        )
    assert not any(call[:2] == ["gh", "release"] for call in executor.calls)


def test_remote_annotated_tag_is_peeled_to_target_before_mutation(tmp_path: Path) -> None:
    module = load_module()
    tag_object_sha = "c" * 40
    executor = FakeExecutor(
        remote_ref={"object": {"type": "tag", "sha": tag_object_sha}},
        remote_tags={tag_object_sha: {"object": {"type": "commit", "sha": TARGET}}},
    )
    evidence = module.stage_draft_release(
        staging_dir=make_stage(tmp_path), tag=TAG, target_commit=TARGET, executor=executor
    )
    assert evidence.release_id == 901
    create_index = next(
        index
        for index, call in enumerate(executor.calls)
        if call[:3] == ["gh", "release", "create"]
    )
    assert executor.calls[create_index - 1][2].endswith(f"/git/tags/{tag_object_sha}")


def test_dry_run_has_no_github_mutation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = load_module()
    executor = FakeExecutor()
    assert module.stage_draft_release(
        staging_dir=make_stage(tmp_path), tag=TAG, target_commit=TARGET, dry_run=True, executor=executor
    ) is None
    output = capsys.readouterr().out
    assert "gh release create" in output and "--draft" in output and "--clobber=false" in output
    assert "--verify-tag" in output
    assert [call[2] for call in executor.calls if call[:2] == ["gh", "api"]] == [
        f"repos/Valeneko-pranmong/Neko-Family-Proxy/git/ref/tags/{TAG}"
    ]
    assert not any(call[:2] == ["gh", "release"] for call in executor.calls)


def test_readback_asset_size_mismatch_emits_no_evidence_or_dispatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_module()
    executor = FakeExecutor(mismatched_asset_size="NekoUpdater.exe")
    with pytest.raises(module.StageDraftReleaseError, match="asset size"):
        module.stage_draft_release(
            staging_dir=make_stage(tmp_path),
            tag=TAG,
            target_commit=TARGET,
            executor=executor,
        )
    assert capsys.readouterr().out == ""
    assert not any(call[:3] == ["gh", "workflow", "run"] for call in executor.calls)


def test_execution_stages_and_returns_immutable_evidence(tmp_path: Path) -> None:
    module = load_module()
    executor = FakeExecutor()
    evidence = module.stage_draft_release(
        staging_dir=make_stage(tmp_path), tag=TAG, target_commit=TARGET, executor=executor
    )
    assert evidence.release_id == 901
    assert evidence.assets == {"NekoFamilyProxy-Setup.exe": 10, "NekoLauncher.exe": 11, "NekoUpdater.exe": 12, "NekoProxyCore.zip": 13, "release-v2.json": 14}
    assert evidence.dispatch_command == (
        f"gh workflow run release.yml --ref {TAG} -f publish_release=true -f release_id=901 "
        f"-f release_tag={TAG} -f expected_target={TARGET}"
    )
    assert not any(call[:3] == ["gh", "workflow", "run"] for call in executor.calls)
    create = next(call for call in executor.calls if call[:3] == ["gh", "release", "create"])
    upload = next(call for call in executor.calls if call[:3] == ["gh", "release", "upload"])
    canonical_repo = "Valeneko-pranmong/Neko-Family-Proxy"
    assert module.CANONICAL_REPO == canonical_repo
    assert create[create.index("--repo") + 1] == canonical_repo
    assert upload[upload.index("--repo") + 1] == canonical_repo
    assert [
        TAG,
        "--target",
        TARGET,
        "--verify-tag",
        "--draft",
        "--prerelease=false",
    ] == create[3:9]
    assert "--clobber=false" in upload
    api_calls = [call for call in executor.calls if call[:2] == ["gh", "api"]]
    assert [call[2] for call in api_calls] == [
        f"repos/Valeneko-pranmong/Neko-Family-Proxy/git/ref/tags/{TAG}",
        "repos/Valeneko-pranmong/Neko-Family-Proxy/releases?per_page=100",
        "repos/Valeneko-pranmong/Neko-Family-Proxy/releases/901",
    ]
    collection_call = api_calls[1]
    assert collection_call[3:] == ["--paginate", "--slurp"]
    assert not any("/releases/tags/" in call[2] for call in api_calls)
    assert not any("workflow" in part for call in executor.calls for part in call)


def test_execution_stages_with_prerelease_semantics(tmp_path: Path) -> None:
    module = load_module()
    executor = FakeExecutor(prerelease=True)
    evidence = module.stage_draft_release(
        staging_dir=make_stage(tmp_path), tag=TAG, target_commit=TARGET, as_prerelease=True, executor=executor
    )
    assert evidence.release_id == 901
    create = next(call for call in executor.calls if call[:3] == ["gh", "release", "create"])
    assert "--prerelease=true" in create

def test_execution_rejects_prerelease_mismatch_during_readback(tmp_path: Path) -> None:
    module = load_module()
    # Mock returns prerelease=False, but we asked for True
    executor = FakeExecutor(prerelease=False)
    with pytest.raises(module.StageDraftReleaseError, match="Draft readback identity or state mismatch"):
        module.stage_draft_release(
            staging_dir=make_stage(tmp_path), tag=TAG, target_commit=TARGET, as_prerelease=True, executor=executor
        )

def test_argument_parsing_as_prerelease() -> None:
    module = load_module()
    args = module.parse_args(["--staging-dir", "candidate", "--tag", TAG, "--target-commit", TARGET, "--as-prerelease"])
    assert args.as_prerelease is True


@pytest.mark.parametrize("matches", [0, 2])
def test_draft_discovery_requires_exactly_one_matching_draft(
    tmp_path: Path, matches: int
) -> None:
    module = load_module()
    matching = {
        "id": 901,
        "tag_name": TAG,
        "target_commitish": TARGET,
        "draft": True,
    }
    releases = [matching.copy() for _ in range(matches)]
    executor = FakeExecutor(releases=releases)
    with pytest.raises(
        module.StageDraftReleaseError,
        match="exactly one draft matching tag and target",
    ):
        module.stage_draft_release(
            staging_dir=make_stage(tmp_path),
            tag=TAG,
            target_commit=TARGET,
            executor=executor,
        )
    assert not any(call[2].endswith("/releases/901") for call in executor.calls if call[:2] == ["gh", "api"])
