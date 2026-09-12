from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "publish_installer_release.py"
TARGET = "b4dab9e9571cbe6d05c6fdb17617137b302856d2"
TAG = "v5.1.1"
DEFAULT_INSTALLER_REPO = "Valeneko-pranmong/Neko-Family-Proxy-Installer"
CANONICAL_MACHINE_REPO = "Valeneko-pranmong/Neko-Family-Proxy"


def load_module():
    assert SCRIPT.is_file(), "scripts/publish_installer_release.py must be implemented"
    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    spec = importlib.util.spec_from_file_location("publish_installer_release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeExecutor:
    def __init__(
        self,
        *,
        dirty: bool = False,
        wrong_tag: bool = False,
        remote_tags: dict[str, Any] | None = None,
        releases: list[dict[str, Any]] | None = None,
        readback_release: dict[str, Any] | None = None,
        latest_release: dict[str, Any] | None = None,
        token: str = "fake-token",
    ) -> None:
        self.calls: list[list[str]] = []
        self.dirty = dirty
        self.wrong_tag = wrong_tag
        self.remote_tags = remote_tags or {}
        self.releases = releases if releases is not None else []
        self.readback_release = readback_release
        self.latest_release = latest_release
        self.token = token

    def run(
        self, args: list[str], *, capture_output: bool = True
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        cmd = args[0]

        if cmd == "git":
            sub = args[3] if len(args) > 3 else ""
            if sub == "status":
                return subprocess.CompletedProcess(
                    args, 0, stdout=" M dirty.txt" if self.dirty else "", stderr=""
                )
            if sub == "rev-parse":
                sha = "0000000000000000000000000000000000000000" if self.wrong_tag else TARGET
                return subprocess.CompletedProcess(args, 0, stdout=f"{sha}\n", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        if cmd == "gh":
            if args[1:3] == ["auth", "token"]:
                return subprocess.CompletedProcess(args, 0, stdout=f"{self.token}\n", stderr="")

            if args[1:3] == ["release", "create"]:
                return subprocess.CompletedProcess(args, 0, stdout="https://github.com/release", stderr="")

            if args[1:3] == ["release", "upload"]:
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            if args[1:3] == ["release", "edit"]:
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            if args[1:3] == ["release", "view"]:
                # If checking existing release
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="release not found")

            if args[1] == "api":
                endpoint = args[2]
                if "/git/ref/tags/" in endpoint:
                    return subprocess.CompletedProcess(
                        args,
                        0,
                        stdout=json.dumps({"object": {"type": "commit", "sha": TARGET}}),
                        stderr="",
                    )
                if endpoint.endswith("/releases/latest"):
                    if self.latest_release is not None:
                        return subprocess.CompletedProcess(
                            args, 0, stdout=json.dumps(self.latest_release), stderr=""
                        )
                    return subprocess.CompletedProcess(
                        args,
                        0,
                        stdout=json.dumps({
                            "id": 123,
                            "tag_name": TAG,
                            "target_commitish": TARGET,
                            "assets": [{"name": "NekoFamilyProxy-Installer.exe", "id": 501, "size": 100}],
                        }),
                        stderr="",
                    )
                if "/releases?per_page=100" in endpoint:
                    pages = [self.releases] if self.releases else [[{
                        "id": 123,
                        "draft": True,
                        "tag_name": TAG,
                        "target_commitish": TARGET,
                    }]]
                    return subprocess.CompletedProcess(args, 0, stdout=json.dumps(pages), stderr="")
                if "/releases/123" in endpoint:
                    if self.readback_release is not None:
                        return subprocess.CompletedProcess(
                            args, 0, stdout=json.dumps(self.readback_release), stderr=""
                        )
                    return subprocess.CompletedProcess(
                        args,
                        0,
                        stdout=json.dumps({
                            "id": 123,
                            "tag_name": TAG,
                            "target_commitish": TARGET,
                            "draft": True,
                            "prerelease": False,
                            "assets": [
                                {
                                    "id": 501,
                                    "name": "NekoFamilyProxy-Installer.exe",
                                    "size": 100,
                                }
                            ],
                        }),
                        stderr="",
                    )
                return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

        if cmd == "curl":
            out_idx = args.index("-o") + 1
            out_file = Path(args[out_idx])
            out_file.write_bytes(b"A" * 100)
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def make_installer_staging_dir(tmp_path: Path, *, content: bytes = b"A" * 100) -> Path:
    staging = tmp_path / "installer_staging"
    staging.mkdir(parents=True, exist_ok=True)
    installer = staging / "NekoFamilyProxy-Installer.exe"
    installer.write_bytes(content)
    return staging


def test_installer_publisher_rejects_canonical_machine_repo(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    runner = FakeExecutor()

    with pytest.raises(module.InstallerPublishError, match="canonical machine"):
        module.stage_installer_draft_release(
            staging_dir=staging,
            tag=TAG,
            target_commit=TARGET,
            installer_repo=CANONICAL_MACHINE_REPO,
            executor=runner,
        )


def test_installer_publisher_requires_explicit_non_empty_repo(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    runner = FakeExecutor()

    with pytest.raises(module.InstallerPublishError, match="explicitly specified"):
        module.stage_installer_draft_release(
            staging_dir=staging,
            tag=TAG,
            target_commit=TARGET,
            installer_repo="",
            executor=runner,
        )


def test_installer_publisher_rejects_extra_assets_in_staging_dir(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    (staging / "extra.zip").write_bytes(b"extra")
    runner = FakeExecutor()

    with pytest.raises(module.InstallerPublishError, match="exactly one.*installer"):
        module.stage_installer_draft_release(
            staging_dir=staging,
            tag=TAG,
            target_commit=TARGET,
            installer_repo=DEFAULT_INSTALLER_REPO,
            executor=runner,
        )


def test_installer_publisher_rejects_missing_installer_in_staging_dir(tmp_path: Path) -> None:
    module = load_module()
    staging = tmp_path / "empty_staging"
    staging.mkdir(parents=True, exist_ok=True)
    runner = FakeExecutor()

    with pytest.raises(module.InstallerPublishError, match="missing|not found"):
        module.stage_installer_draft_release(
            staging_dir=staging,
            tag=TAG,
            target_commit=TARGET,
            installer_repo=DEFAULT_INSTALLER_REPO,
            executor=runner,
        )


def test_installer_publisher_rejects_dirty_worktree(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    runner = FakeExecutor(dirty=True)

    with pytest.raises(module.InstallerPublishError, match="Worktree is not clean"):
        module.stage_installer_draft_release(
            staging_dir=staging,
            tag=TAG,
            target_commit=TARGET,
            installer_repo=DEFAULT_INSTALLER_REPO,
            executor=runner,
        )


def test_installer_publisher_rejects_tag_target_mismatch(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    runner = FakeExecutor(wrong_tag=True)

    with pytest.raises(module.InstallerPublishError, match="does not bind to target commit"):
        module.stage_installer_draft_release(
            staging_dir=staging,
            tag=TAG,
            target_commit=TARGET,
            installer_repo=DEFAULT_INSTALLER_REPO,
            executor=runner,
        )


def test_installer_publisher_rejects_invalid_sha_format(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    runner = FakeExecutor()

    with pytest.raises(module.InstallerPublishError, match="40-character"):
        module.stage_installer_draft_release(
            staging_dir=staging,
            tag=TAG,
            target_commit="invalid-sha",
            installer_repo=DEFAULT_INSTALLER_REPO,
            executor=runner,
        )


def test_stage_installer_draft_success(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    runner = FakeExecutor()

    evidence = module.stage_installer_draft_release(
        staging_dir=staging,
        tag=TAG,
        target_commit=TARGET,
        installer_repo=DEFAULT_INSTALLER_REPO,
        executor=runner,
    )

    assert evidence.release_id == 123
    assert evidence.tag_name == TAG
    assert evidence.target_commit == TARGET
    assert evidence.repo == DEFAULT_INSTALLER_REPO
    assert evidence.installer_asset_id == 501
    assert evidence.installer_size == 100
    assert any("gh release create" in " ".join(call) for call in runner.calls)
    assert any("gh release upload" in " ".join(call) for call in runner.calls)


def test_draft_readback_rejects_extra_asset(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    readback = {
        "id": 123,
        "tag_name": TAG,
        "target_commitish": TARGET,
        "draft": True,
        "prerelease": False,
        "assets": [
            {"id": 501, "name": "NekoFamilyProxy-Installer.exe", "size": 100},
            {"id": 502, "name": "NekoFamilyProxy-Setup.exe", "size": 200},
        ],
    }
    runner = FakeExecutor(readback_release=readback)

    with pytest.raises(module.InstallerPublishError, match="unexpected extra asset|exactly one"):
        module.stage_installer_draft_release(
            staging_dir=staging,
            tag=TAG,
            target_commit=TARGET,
            installer_repo=DEFAULT_INSTALLER_REPO,
            executor=runner,
        )


def test_draft_readback_rejects_size_mismatch(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    readback = {
        "id": 123,
        "tag_name": TAG,
        "target_commitish": TARGET,
        "draft": True,
        "prerelease": False,
        "assets": [
            {"id": 501, "name": "NekoFamilyProxy-Installer.exe", "size": 99999},
        ],
    }
    runner = FakeExecutor(readback_release=readback)

    with pytest.raises(module.InstallerPublishError, match="size"):
        module.stage_installer_draft_release(
            staging_dir=staging,
            tag=TAG,
            target_commit=TARGET,
            installer_repo=DEFAULT_INSTALLER_REPO,
            executor=runner,
        )


def test_execute_installer_publish_success(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    runner = FakeExecutor()

    module.execute_installer_publish(
        version=TAG,
        sha=TARGET,
        staging_dir=staging,
        installer_repo=DEFAULT_INSTALLER_REPO,
        executor=runner,
    )

    # Verifies promote command was issued
    assert any(
        call == ["gh", "release", "edit", TAG, "--draft=false", "--repo", DEFAULT_INSTALLER_REPO]
        for call in runner.calls
    )


def test_execute_installer_publish_rejects_canonical_machine_repo(tmp_path: Path) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    runner = FakeExecutor()

    with pytest.raises(module.InstallerPublishError, match="canonical machine"):
        module.execute_installer_publish(
            version=TAG,
            sha=TARGET,
            staging_dir=staging,
            installer_repo=CANONICAL_MACHINE_REPO,
            executor=runner,
        )


def test_execute_installer_publish_gate3_rejects_extra_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    staging = make_installer_staging_dir(tmp_path)
    latest_bad = {
        "id": 123,
        "tag_name": TAG,
        "target_commitish": TARGET,
        "assets": [
            {"name": "NekoFamilyProxy-Installer.exe", "id": 501, "size": 100},
            {"name": "extra.exe", "id": 502, "size": 50},
        ],
    }
    runner = FakeExecutor(latest_release=latest_bad)

    t = 0
    def fake_time():
        nonlocal t
        t += 301
        return t
    monkeypatch.setattr("time.time", fake_time)
    monkeypatch.setattr("time.sleep", lambda s: None)

    with pytest.raises(module.InstallerPublishError, match="Gate3|extra"):
        module.execute_installer_publish(
            version=TAG,
            sha=TARGET,
            staging_dir=staging,
            installer_repo=DEFAULT_INSTALLER_REPO,
            executor=runner,
        )


def test_installer_publisher_has_no_signing_secret_dependency() -> None:
    module = load_module()
    assert not hasattr(module, "PRODUCTION_RELEASE_PUBLIC_KEYS")
    assert not hasattr(module, "verify_release_envelope_v2")
