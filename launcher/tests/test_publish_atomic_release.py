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

try:
    from tests.software_update_helpers import TEST_PUBLIC_KEY, signed_envelope
except ImportError:
    from launcher.tests.software_update_helpers import TEST_PUBLIC_KEY, signed_envelope


SCRIPT = Path(__file__).parents[2] / "scripts" / "publish_atomic_release.py"
SCRIPTS_DIR = str(SCRIPT.parent)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
TARGET = "b4dab9e9571cbe6d05c6fdb17617137b302856d2"
TAG = "v5.1.4"


def load_module():
    assert SCRIPT.is_file(), "scripts/publish_atomic_release.py must be implemented"
    spec = importlib.util.spec_from_file_location("publish_atomic_release", SCRIPT)
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
        extra_readback_assets: list[dict[str, Any]] | None = None,
        readback_assets: list[dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.dirty = dirty
        self.wrong_tag = wrong_tag
        self.prerelease = prerelease
        self.extra_readback_assets = extra_readback_assets
        self.readback_assets = readback_assets
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
                assets_list = (
                    self.readback_assets
                    if self.readback_assets is not None
                    else [
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
                            ("NekoFamilyProxy-Installer.exe", "release-v2.json", "NekoLauncher.exe", "NekoUpdater.exe", "NekoProxyCore.zip")
                        )
                    ] + (self.extra_readback_assets or [])
                )
                out = json.dumps(
                    {
                        "id": 901,
                        "tag_name": TAG,
                        "target_commitish": TARGET,
                        "draft": True,
                        "prerelease": self.prerelease,
                        "assets": assets_list,
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
    sequence: int = 8,
    minimum_supported_sequence: int = 1,
    release_id: str = "stable-0008",
    version: str = "5.1.4",
    mandatory: bool = False,
) -> Path:
    core_bytes, actual_core_identity = _make_core_zip(path / "NekoProxyCore.zip")
    payloads = {
        "NekoFamilyProxy-Installer.exe": b"installer",
        "NekoLauncher.exe": b"launcher",
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
            "version": version,
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
        "mandatory": mandatory,
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
    payloads = {"NekoLauncher.exe": b"launcher", "NekoUpdater.exe": b"updater", "NekoProxyCore.zip": b"core"}
    payload = {
        "schema_version": 2, "channel": "stable", "release_sequence": 8,
        "minimum_supported_sequence": 1, "release_id": "stable-0008", "mandatory": False,
        "updater_protocol": {"minimum": 1, "maximum": 1}, "components": {},
    }
    for component, name, fmt in (
        ("launcher", "NekoLauncher.exe", "raw-pe-v1"),
        ("updater", "NekoUpdater.exe", "raw-pe-v1"),
        ("core", "NekoProxyCore.zip", "zip-core-v1"),
    ):
        digest = hashlib.sha256(payloads[name]).hexdigest()
        payload["components"][component] = {
            "version": "5.1.4", "artifact_id": name, "artifact_sha256": digest,
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
        {"sequence": 7, "release_id": "stable-0007"},
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
            expected_sequence=8,
            expected_release_id="stable-0008",
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


def test_authority_bound_baseline_accepts_minimum_sequence_equal_allocation(
    tmp_path: Path,
) -> None:
    module = load_module()
    executor = FakeExecutor()
    allocation = type(
        "Allocation",
        (),
        {"sequence": 9, "release_id": "stable-0009"},
    )()
    stage = make_stage(
        tmp_path,
        sequence=9,
        minimum_supported_sequence=9,
        release_id="stable-0009",
    )

    assets = module.validate_staging_preconditions(
        staging_dir=stage,
        tag=TAG,
        target_commit=TARGET,
        repo_root=SCRIPT.parents[1],
        executor=executor,
        expected_allocation=allocation,
    )

    assert set(assets) == set(module.REQUIRED_STAGE_ASSETS)


def test_successor_authority_accepts_previous_published_floor_and_mandatory(
    tmp_path: Path,
) -> None:
    module = load_module()
    executor = FakeExecutor()
    allocation = type(
        "Allocation",
        (),
        {"sequence": 10, "release_id": "stable-0010"},
    )()
    stage = make_stage(
        tmp_path,
        sequence=10,
        minimum_supported_sequence=9,
        release_id="stable-0010",
        mandatory=True,
    )

    assets = module.validate_staging_preconditions(
        staging_dir=stage,
        tag=TAG,
        target_commit=TARGET,
        repo_root=SCRIPT.parents[1],
        executor=executor,
        expected_allocation=allocation,
        expected_minimum_sequence=9,
        expected_mandatory=True,
    )

    assert set(assets) == set(module.REQUIRED_STAGE_ASSETS)


@pytest.mark.parametrize(
    ("minimum_supported_sequence", "mandatory"),
    [(10, True), (9, False)],
)
def test_successor_authority_rejects_wrong_floor_or_nonmandatory(
    tmp_path: Path,
    minimum_supported_sequence: int,
    mandatory: bool,
) -> None:
    module = load_module()
    executor = FakeExecutor()
    allocation = type(
        "Allocation",
        (),
        {"sequence": 10, "release_id": "stable-0010"},
    )()
    stage = make_stage(
        tmp_path,
        sequence=10,
        minimum_supported_sequence=minimum_supported_sequence,
        release_id="stable-0010",
        mandatory=mandatory,
    )

    with pytest.raises(module.StageDraftReleaseError, match="Stable-release authority mismatch"):
        module.validate_staging_preconditions(
            staging_dir=stage,
            tag=TAG,
            target_commit=TARGET,
            repo_root=SCRIPT.parents[1],
            executor=executor,
            expected_allocation=allocation,
            expected_minimum_sequence=9,
            expected_mandatory=True,
        )


def test_authority_bound_baseline_rejects_legacy_minimum_sequence_one(
    tmp_path: Path,
) -> None:
    module = load_module()
    executor = FakeExecutor()
    allocation = type(
        "Allocation",
        (),
        {"sequence": 9, "release_id": "stable-0009"},
    )()
    stage = make_stage(
        tmp_path,
        sequence=9,
        minimum_supported_sequence=1,
        release_id="stable-0009",
    )

    with pytest.raises(module.StageDraftReleaseError, match="Stable-release authority mismatch"):
        module.validate_staging_preconditions(
            staging_dir=stage,
            tag=TAG,
            target_commit=TARGET,
            repo_root=SCRIPT.parents[1],
            executor=executor,
            expected_allocation=allocation,
        )


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
    assert evidence.assets == {
        "NekoFamilyProxy-Installer.exe": 10,
        "release-v2.json": 11,
        "NekoLauncher.exe": 12,
        "NekoUpdater.exe": 13,
        "NekoProxyCore.zip": 14,
    }
    assert evidence.dispatch_command == (
        f"gh workflow run release.yml --ref {TAG} -f publish_release=true -f release_id=901 "
        f"-f release_tag={TAG} -f expected_target={TARGET}"
    )
    assert not any(call[:3] == ["gh", "workflow", "run"] for call in executor.calls)
    create = next(call for call in executor.calls if call[:3] == ["gh", "release", "create"])
    upload = next(call for call in executor.calls if call[:3] == ["gh", "release", "upload"])
    canonical_machine_repo = "Valeneko-pranmong/Neko-Family-Proxy"
    assert module.CANONICAL_REPO == canonical_machine_repo
    assert module.CANONICAL_REPO == "Valeneko-pranmong/Neko-Family-Proxy"
    assert create[create.index("--repo") + 1] == "Valeneko-pranmong/Neko-Family-Proxy"
    assert upload[upload.index("--repo") + 1] == "Valeneko-pranmong/Neko-Family-Proxy"
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


def test_machine_publishing_required_assets_is_exact_five() -> None:
    module = load_module()
    assert set(module.REQUIRED_STAGE_ASSETS) == {
        "NekoFamilyProxy-Installer.exe",
        "release-v2.json",
        "NekoLauncher.exe",
        "NekoUpdater.exe",
        "NekoProxyCore.zip",
    }
    assert len(module.REQUIRED_STAGE_ASSETS) == 5
    assert "NekoFamilyProxy-Setup.exe" not in module.REQUIRED_STAGE_ASSETS
    assert "NekoFamilyProxy-Installer.exe" in module.REQUIRED_STAGE_ASSETS


def test_staging_rejects_missing_required_asset(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    (stage / "NekoLauncher.exe").unlink()
    executor = FakeExecutor()
    with pytest.raises(module.StageDraftReleaseError, match="missing"):
        module.validate_staging_preconditions(
            staging_dir=stage, tag=TAG, target_commit=TARGET, repo_root=SCRIPT.parents[1], executor=executor
        )


def test_staging_requires_installer_asset(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    (stage / "NekoFamilyProxy-Installer.exe").unlink()
    executor = FakeExecutor()
    with pytest.raises(module.StageDraftReleaseError, match="missing"):
        module.validate_staging_preconditions(
            staging_dir=stage, tag=TAG, target_commit=TARGET, repo_root=SCRIPT.parents[1], executor=executor
        )


def test_staging_rejects_setup_asset(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    (stage / "NekoFamilyProxy-Setup.exe").write_bytes(b"setup")
    executor = FakeExecutor()
    with pytest.raises(module.StageDraftReleaseError):
        module.validate_staging_preconditions(
            staging_dir=stage, tag=TAG, target_commit=TARGET, repo_root=SCRIPT.parents[1], executor=executor
        )


def test_staging_rejects_extra_custom_assets(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    (stage / "untrusted_extra.exe").write_bytes(b"bad")
    executor = FakeExecutor()
    with pytest.raises(module.StageDraftReleaseError, match="extra|forbidden"):
        module.validate_staging_preconditions(
            staging_dir=stage, tag=TAG, target_commit=TARGET, repo_root=SCRIPT.parents[1], executor=executor
        )


def test_staging_rejects_zero_size_asset(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    (stage / "NekoUpdater.exe").write_bytes(b"")
    executor = FakeExecutor()
    with pytest.raises(module.StageDraftReleaseError, match="non-empty regular file"):
        module.validate_staging_preconditions(
            staging_dir=stage, tag=TAG, target_commit=TARGET, repo_root=SCRIPT.parents[1], executor=executor
        )


def test_draft_readback_rejects_extra_custom_asset(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    extra = [{"id": 99, "name": "SHA256SUMS.txt", "size": 123}]
    executor = FakeExecutor(extra_readback_assets=extra)
    with pytest.raises(module.StageDraftReleaseError, match="unexpected extra asset"):
        module.stage_draft_release(
            staging_dir=stage, tag=TAG, target_commit=TARGET, executor=executor
        )


def test_draft_readback_rejects_setup_asset(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    extra = [{"id": 99, "name": "NekoFamilyProxy-Setup.exe", "size": 500}]
    executor = FakeExecutor(extra_readback_assets=extra)
    with pytest.raises(module.StageDraftReleaseError, match="unexpected extra asset"):
        module.stage_draft_release(
            staging_dir=stage, tag=TAG, target_commit=TARGET, executor=executor
        )


def test_draft_readback_requires_installer_asset(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    executor = FakeExecutor(readback_assets=[{"id": 10, "name": "release-v2.json", "size": 100}])
    with pytest.raises(module.StageDraftReleaseError, match="(does not contain each required asset exactly once|Invalid or mismatched required asset size)"):
        module.stage_draft_release(
            staging_dir=stage, tag=TAG, target_commit=TARGET, executor=executor
        )


def test_draft_readback_rejects_missing_required_asset(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    # Only 3 assets returned in readback
    three_assets = [
        {"id": 10, "name": "release-v2.json", "size": (stage / "release-v2.json").stat().st_size},
        {"id": 11, "name": "NekoLauncher.exe", "size": (stage / "NekoLauncher.exe").stat().st_size},
        {"id": 12, "name": "NekoUpdater.exe", "size": (stage / "NekoUpdater.exe").stat().st_size},
    ]
    executor = FakeExecutor(readback_assets=three_assets)
    with pytest.raises(module.StageDraftReleaseError, match="(does not contain each required asset exactly once|Invalid or mismatched required asset size)"):
        module.stage_draft_release(
            staging_dir=stage, tag=TAG, target_commit=TARGET, executor=executor
        )


def test_draft_readback_rejects_duplicate_asset(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    dup_assets = [
        {"id": 10, "name": "release-v2.json", "size": (stage / "release-v2.json").stat().st_size},
        {"id": 11, "name": "NekoLauncher.exe", "size": (stage / "NekoLauncher.exe").stat().st_size},
        {"id": 12, "name": "NekoUpdater.exe", "size": (stage / "NekoUpdater.exe").stat().st_size},
        {"id": 13, "name": "NekoProxyCore.zip", "size": (stage / "NekoProxyCore.zip").stat().st_size},
        {"id": 14, "name": "NekoLauncher.exe", "size": (stage / "NekoLauncher.exe").stat().st_size},
    ]
    executor = FakeExecutor(readback_assets=dup_assets)
    with pytest.raises(module.StageDraftReleaseError, match="Duplicate or invalid required asset binding"):
        module.stage_draft_release(
            staging_dir=stage, tag=TAG, target_commit=TARGET, executor=executor
        )


def test_draft_readback_rejects_zero_size_asset(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    zero_assets = [
        {"id": 10, "name": "release-v2.json", "size": (stage / "release-v2.json").stat().st_size},
        {"id": 11, "name": "NekoLauncher.exe", "size": 0},
        {"id": 12, "name": "NekoUpdater.exe", "size": (stage / "NekoUpdater.exe").stat().st_size},
        {"id": 13, "name": "NekoProxyCore.zip", "size": (stage / "NekoProxyCore.zip").stat().st_size},
    ]
    executor = FakeExecutor(readback_assets=zero_assets)
    with pytest.raises(module.StageDraftReleaseError, match="Invalid or mismatched required asset size"):
        module.stage_draft_release(
            staging_dir=stage, tag=TAG, target_commit=TARGET, executor=executor
        )


def test_draft_readback_rejects_invalid_asset_id(tmp_path: Path) -> None:
    module = load_module()
    stage = make_stage(tmp_path)
    bad_id_assets = [
        {"id": 10, "name": "release-v2.json", "size": (stage / "release-v2.json").stat().st_size},
        {"id": "not_an_int", "name": "NekoLauncher.exe", "size": (stage / "NekoLauncher.exe").stat().st_size},
        {"id": 12, "name": "NekoUpdater.exe", "size": (stage / "NekoUpdater.exe").stat().st_size},
        {"id": 13, "name": "NekoProxyCore.zip", "size": (stage / "NekoProxyCore.zip").stat().st_size},
    ]
    executor = FakeExecutor(readback_assets=bad_id_assets)
    with pytest.raises(module.StageDraftReleaseError, match="Duplicate or invalid required asset binding"):
        module.stage_draft_release(
            staging_dir=stage, tag=TAG, target_commit=TARGET, executor=executor
        )


def test_machine_release_notes_point_to_canonical_human_repository() -> None:
    module = load_module()
    notes = module.build_machine_release_notes("v5.1.2")
    assert "Valeneko-pranmong/Neko-Family-Proxy" in notes
    assert "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases" in notes
    
    assert "v5.1.2" in notes
    assert "unified release channel" in notes
    assert "download the installer from the official releases:" in notes


def test_build_release_payload_has_machine_notes() -> None:
    module = load_module()
    payload = module.build_release_payload("v5.1.2", "sha_123")
    assert payload["tag_name"] == "v5.1.2"
    assert payload["target_commitish"] == "sha_123"
    assert not payload["draft"]
    assert "body" in payload
    assert "Valeneko-pranmong/Neko-Family-Proxy" in payload["body"]
    assert "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases" in payload["body"]
    
    assert "unified release channel" in payload["body"]
    assert "download the installer from the official releases:" in payload["body"]


def test_machine_publisher_targets_only_updates_repository() -> None:
    module = load_module()
    assert module.CANONICAL_REPO == "Valeneko-pranmong/Neko-Family-Proxy"



def _setup_machine_publish_test_env(
    tmp_path: Path,
    *,
    tag: str = "v5.1.2",
    version: str = "5.1.2",
    seq: int = 8,
    rel_id: str = "stable-0008",
    target: str = TARGET,
):
    import base64
    from authenticated_production_history import (
        AuthenticatedHistorySnapshot,
        bootstrap_sequence_ledger,
    )
    from production_sequence_ledger import (
        AuthenticatedProductionBinding,
        SequenceLedgerEvent,
        open_authority_session,
    )
    from scripts.publish_atomic_release import SignedReleaseBinding

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    make_stage(
        staging_dir,
        sequence=seq,
        minimum_supported_sequence=seq,
        release_id=rel_id,
        version=version,
    )

    manifest_bytes = (staging_dir / "release-v2.json").read_bytes()
    manifest_doc = json.loads(manifest_bytes.decode("utf-8"))
    payload_bytes = base64.b64decode(manifest_doc["payload_b64"])
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()
    env_sha = hashlib.sha256(manifest_bytes).hexdigest()

    ledger_path = tmp_path / "ledger.jsonl"

    binding7 = AuthenticatedProductionBinding(
        sequence=7,
        release_id="stable-0007",
        payload_sha256="7" * 64,
        envelope_sha256="7" * 64,
        key_id="neko-update-prod-1",
    )
    binding8 = AuthenticatedProductionBinding(
        sequence=seq,
        release_id=rel_id,
        payload_sha256=payload_sha,
        envelope_sha256=env_sha,
        key_id="neko-update-prod-1",
    )

    floor_snapshot = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7},
        provenance_source_commit_by_sequence={7: "c" * 40},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=7,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )

    class _InitProvider:
        def load(self) -> AuthenticatedHistorySnapshot:
            return floor_snapshot

    bootstrap_sequence_ledger(
        ledger_path=ledger_path,
        history_provider=_InitProvider(),
        expected_floor=binding7,
        expected_floor_provenance_source_commit="c" * 40,
    )

    with open_authority_session(ledger_path) as session:
        verified = session.read_verified()
        reserved_event = SequenceLedgerEvent(
            record_type="EVENT",
            sequence=seq,
            release_id=rel_id,
            status="RESERVED",
            version=version,
            channel="stable",
            source_commit=target,
            component_set_sha256="comp" * 16,
            payload_sha256=None,
            envelope_sha256=None,
            key_id=None,
            timestamp="2026-09-14T00:00:00Z",
            previous_entry_sha256=verified.latest_entry_sha256,
        )
        prev_sha = session.append(reserved_event, expected_previous_sha256=verified.latest_entry_sha256)
        signed_event = SequenceLedgerEvent(
            record_type="EVENT",
            sequence=seq,
            release_id=rel_id,
            status="SIGNED",
            version=version,
            channel="stable",
            source_commit=target,
            component_set_sha256="comp" * 16,
            payload_sha256=payload_sha,
            envelope_sha256=env_sha,
            key_id="neko-update-prod-1",
            timestamp="2026-09-14T00:01:00Z",
            previous_entry_sha256=prev_sha,
        )
        session.append(signed_event, expected_previous_sha256=prev_sha)

        from scripts.publish_atomic_release import SignedReleaseBinding
        signed = SignedReleaseBinding(source_commit=target, 
        sequence=seq,
        release_id=rel_id,
        component_set_sha256="comp" * 16,
        payload_sha256=payload_sha,
        envelope_sha256=env_sha,
        key_id="neko-update-prod-1",
        
    )

    return staging_dir, ledger_path, signed, binding7, binding8


class _FakeMachinePublishExecutor:
    def __init__(
        self,
        staging_dir: Path,
        release_id: int = 901,
        tag: str = "v5.1.2",
        target: str = TARGET,
        live_draft: bool = False,
    ) -> None:
        self.staging_dir = staging_dir
        self.release_id = release_id
        self.tag = tag
        self.target = target
        self.live_draft = live_draft
        self.calls: list[list[str]] = []
        self.commands: list[list[str]] = self.calls
        self.assets = {
            "release-v2.json": 10,
            "NekoFamilyProxy-Installer.exe": 9, "NekoLauncher.exe": 11,
            "NekoUpdater.exe": 12,
            "NekoProxyCore.zip": 13,
        }

    def run(
        self, args: list[str], *, capture_output: bool = True, stdout: Any = None
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        cmd = args[0]
        if cmd == "git" and "status" in args:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if cmd == "git" and "rev-parse" in args:
            return subprocess.CompletedProcess(args, 0, stdout=f"{self.target}\n", stderr="")
        if cmd == "gh" and len(args) > 2 and args[1] == "release":
            sub = args[2]
            if sub in ("create", "upload", "edit"):
                if sub == "edit" and "--draft=false" in args:
                    self.live_draft = False
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if cmd == "gh" and len(args) > 2 and args[1] == "api":
            endpoint = args[2]
            if "/git/ref/tags/" in endpoint:
                return subprocess.CompletedProcess(
                    args, 0, stdout=json.dumps({"object": {"type": "commit", "sha": self.target}}), stderr=""
                )
            if "releases/assets/" in endpoint:
                aid = int(endpoint.split("releases/assets/")[1])
                for name, a_id in self.assets.items():
                    if a_id == aid:
                        data = (self.staging_dir / name).read_bytes()
                        if stdout is not None:
                            stdout.write(data)
                            stdout.flush()
                        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if endpoint.endswith("/releases?per_page=100"):
                rel = {
                    "id": self.release_id,
                    "tag_name": self.tag,
                    "target_commitish": self.target,
                    "draft": True,
                    "prerelease": False,
                }
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps([[rel]]), stderr="")
            if endpoint.endswith(f"/releases/{self.release_id}"):
                rel = {
                    "id": self.release_id,
                    "tag_name": self.tag,
                    "target_commitish": self.target,
                    "draft": self.live_draft,
                    "prerelease": False,
                    "assets": [
                        {"id": aid, "name": name, "size": (self.staging_dir / name).stat().st_size}
                        for name, aid in self.assets.items()
                        if (self.staging_dir / name).is_file()
                    ],
                }
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(rel), stderr="")
            if endpoint.endswith(f"/releases/tags/{self.tag}"):
                rel = {
                    "id": self.release_id,
                    "tag_name": self.tag,
                    "target_commitish": self.target,
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {"id": aid, "name": name, "size": (self.staging_dir / name).stat().st_size}
                        for name, aid in self.assets.items()
                        if (self.staging_dir / name).is_file()
                    ],
                }
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(rel), stderr="")
            if endpoint.endswith("/releases/latest"):
                rel = {
                    "id": self.release_id,
                    "tag_name": self.tag,
                    "target_commitish": self.target,
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {"id": aid, "name": name, "size": (self.staging_dir / name).stat().st_size}
                        for name, aid in self.assets.items()
                        if (self.staging_dir / name).is_file()
                    ],
                }
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(rel), stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def test_publish_unified_release_rejects_missing_required_asset(tmp_path: Path) -> None:
    module = load_module()
    staging_dir, ledger_path, signed, binding7, binding8 = _setup_machine_publish_test_env(tmp_path)
    (staging_dir / "NekoUpdater.exe").unlink()

    from authenticated_production_history import AuthenticatedHistorySnapshot

    snap = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7, 8: binding8},
        provenance_source_commit_by_sequence={7: "c" * 40, 8: TARGET},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=8,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )

    class _Prov:
        def load(self):
            return snap

    executor = _FakeMachinePublishExecutor(staging_dir)
    with pytest.raises((module.StageDraftReleaseError, ValueError)):
        module.publish_unified_release(
            ledger_path=ledger_path,
            history_provider=_Prov(),
            tag="v5.1.2",
            body="notes",
            authority_binding=signed,
            target_commit=TARGET,
            staging_dir=staging_dir,
            executor=executor,
        )
    assert not any(call[:3] == ["gh", "release", "create"] for call in executor.calls)


def test_publish_unified_release_rejects_extra_asset(tmp_path: Path) -> None:
    module = load_module()
    staging_dir, ledger_path, signed, binding7, binding8 = _setup_machine_publish_test_env(tmp_path)
    (staging_dir / "forbidden.exe").write_bytes(b"bad")

    from authenticated_production_history import AuthenticatedHistorySnapshot

    snap = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7, 8: binding8},
        provenance_source_commit_by_sequence={7: "c" * 40, 8: TARGET},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=8,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )

    class _Prov:
        def load(self):
            return snap

    executor = _FakeMachinePublishExecutor(staging_dir)
    with pytest.raises((module.StageDraftReleaseError, ValueError)):
        module.publish_unified_release(
            ledger_path=ledger_path,
            history_provider=_Prov(),
            tag="v5.1.2",
            body="notes",
            authority_binding=signed,
            target_commit=TARGET,
            staging_dir=staging_dir,
            executor=executor,
        )
    assert not any(call[:3] == ["gh", "release", "create"] for call in executor.calls)


def test_publish_unified_release_conflicting_authority_hard_stops_with_zero_mutation(tmp_path: Path) -> None:
    module = load_module()
    staging_dir, ledger_path, signed, binding7, binding8 = _setup_machine_publish_test_env(tmp_path)

    from authenticated_production_history import AuthenticatedHistorySnapshot
    from production_sequence_ledger import (
        AuthenticatedProductionBinding,
        ReleaseAuthorityReconciliationRequired,
    )

    binding9 = AuthenticatedProductionBinding(
        sequence=9,
        release_id="stable-0009",
        payload_sha256="9" * 64,
        envelope_sha256="9" * 64,
        key_id="neko-update-prod-1",
    )
    conflicting_snap = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7, 8: binding8, 9: binding9},
        provenance_source_commit_by_sequence={7: "c" * 40, 8: TARGET, 9: "9" * 40},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=9,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )

    class _Prov:
        def load(self):
            return conflicting_snap

    executor = _FakeMachinePublishExecutor(staging_dir)
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        module.publish_unified_release(
            ledger_path=ledger_path,
            history_provider=_Prov(),
            tag="v5.1.2",
            body="notes",
            authority_binding=signed,
            target_commit=TARGET,
            staging_dir=staging_dir,
            executor=executor,
        )
    # Zero mutation commands
    assert not any(call[:3] in (["gh", "release", "create"], ["gh", "release", "upload"], ["gh", "release", "edit"]) for call in executor.calls)


def test_publish_unified_release_crash_recovery_performs_readonly_verification_and_zero_mutations(tmp_path: Path) -> None:
    module = load_module()
    staging_dir, ledger_path, signed, binding7, binding8 = _setup_machine_publish_test_env(tmp_path)

    from authenticated_production_history import AuthenticatedHistorySnapshot
    from production_sequence_ledger import open_authority_session

    recovery_snap = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7, 8: binding8},
        provenance_source_commit_by_sequence={7: "c" * 40, 8: TARGET},
        live_updates_sequences=frozenset({8}),
        highest_authenticated_sequence=8,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )

    class _Prov:
        def load(self):
            return recovery_snap

    executor = _FakeMachinePublishExecutor(staging_dir, live_draft=False)
    result = module.publish_unified_release(
        ledger_path=ledger_path,
        history_provider=_Prov(),
        tag="v5.1.2",
            body="notes",
            authority_binding=signed,
        target_commit=TARGET,
        staging_dir=staging_dir,
        executor=executor,
    )
    assert result.status == "PUBLISHED_APPEND_REQUIRED"
    assert result.sequence == 8
    assert result.release_id == "stable-0008"
    assert result.tag == "v5.1.2"
    assert result.target_commit == TARGET
    # ZERO create / upload / edit commands
    assert not any(call[:3] in (["gh", "release", "create"], ["gh", "release", "upload"], ["gh", "release", "edit"]) for call in executor.calls)

    with open_authority_session(ledger_path) as session:
        verified = session.read_verified()
        last_event = verified.events[-1]
        assert last_event.sequence == 8
        assert last_event.status == "PUBLISHED"
        assert verified.latest_entry_sha256 == result.entry_sha256


def test_publish_unified_release_happy_path_promotes_once_and_appends_published(tmp_path: Path) -> None:
    module = load_module()
    staging_dir, ledger_path, signed, binding7, binding8 = _setup_machine_publish_test_env(tmp_path)

    from authenticated_production_history import AuthenticatedHistorySnapshot
    from production_sequence_ledger import open_authority_session

    pre_snap = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7, 8: binding8},
        provenance_source_commit_by_sequence={7: "c" * 40, 8: TARGET},
        live_updates_sequences=frozenset(),
        highest_authenticated_sequence=8,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )
    post_snap = AuthenticatedHistorySnapshot(
        bindings_by_sequence={7: binding7, 8: binding8},
        provenance_source_commit_by_sequence={7: "c" * 40, 8: TARGET},
        live_updates_sequences=frozenset({8}),
        highest_authenticated_sequence=8,
        authenticated_bindings_sha256="b" * 64,
        snapshot_sha256="s" * 64,
    )

    class _Prov:
        def __init__(self):
            self.calls = 0

        def load(self):
            self.calls += 1
            if self.calls == 1:
                return pre_snap
            return post_snap

    prov = _Prov()
    executor = _FakeMachinePublishExecutor(staging_dir, live_draft=True)
    result = module.publish_unified_release(
        ledger_path=ledger_path,
        history_provider=prov,
        tag="v5.1.2",
            body="notes",
            authority_binding=signed,
        target_commit=TARGET,
        staging_dir=staging_dir,
        executor=executor,
    )
    assert result.status == "PUBLISHED"
    assert result.sequence == 8
    assert result.release_id == "stable-0008"
    assert result.tag == "v5.1.2"
    assert result.target_commit == TARGET
    assert any(call[:3] == ["gh", "release", "create"] for call in executor.calls)
    assert any(call[:3] == ["gh", "release", "upload"] for call in executor.calls)
    assert any(call[:3] == ["gh", "release", "edit"] and "--draft=false" in call for call in executor.calls)

    with open_authority_session(ledger_path) as session:
        verified = session.read_verified()
        last_event = verified.events[-1]
        assert last_event.sequence == 8
        assert last_event.status == "PUBLISHED"
        assert verified.latest_entry_sha256 == result.entry_sha256
