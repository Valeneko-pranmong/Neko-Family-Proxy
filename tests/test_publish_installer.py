import hashlib
import json
from pathlib import Path
import pytest

from scripts.publish_installer_release import (
    DEFAULT_INSTALLER_REPO,
    CANONICAL_MACHINE_REPO,
    InstallerPublishError,
    StagedInstallerDraftEvidence,
    execute_installer_publish,
)
from scripts.verify_installer_release_assets import (
    InstallerReleaseVerificationError,
    verify_installer_release_assets,
)


def test_installer_publish_rejects_canonical_machine_repo():
    with pytest.raises(InstallerPublishError, match="canonical machine"):
        execute_installer_publish(
            "v5.1.1",
            "b4dab9e9571cbe6d05c6fdb17617137b302856d2",
            staging_dir=".",
            installer_repo=CANONICAL_MACHINE_REPO,
        )


def test_execute_installer_publish_duplicate(monkeypatch):
    def mock_run(runner, args):
        return '{"targetCommitish": "sha_123"}'

    monkeypatch.setattr("scripts.publish_installer_release._run", mock_run)

    called = False

    def mock_stage(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "scripts.publish_installer_release.stage_installer_draft_release", mock_stage
    )

    execute_installer_publish(
        "v5.1.1", "sha_123", installer_repo=DEFAULT_INSTALLER_REPO
    )
    assert not called


def test_execute_installer_publish_promotion(monkeypatch, tmp_path):
    run_calls = []

    def mock_run(runner, args):
        run_calls.append(args)
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            if "releases/latest" in args[2]:
                return json.dumps({
                    "id": 123,
                    "tag_name": "v5.1.1",
                    "assets": [{"name": "NekoFamilyProxy-Installer.exe", "id": 501, "size": 100}],
                })
            return json.dumps({
                "id": 123,
                "tag_name": "v5.1.1",
                "target_commitish": "sha_123",
                "draft": True,
                "prerelease": False,
                "assets": [{"name": "NekoFamilyProxy-Installer.exe", "id": 501, "size": 100}],
            })
        if args[0] == "gh" and args[1:3] == ["auth", "token"]:
            return "token"
        if args[0] == "curl":
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(b"A" * 100)
            return ""
        return "sha_123"

    monkeypatch.setattr("scripts.publish_installer_release._run", mock_run)
    monkeypatch.setattr(
        "scripts.verify_installer_release_assets.verify_installer_release_assets",
        lambda **kwargs: ("sha256", 100),
    )

    staging = tmp_path / "staging"
    staging.mkdir()
    installer_file = staging / "NekoFamilyProxy-Installer.exe"
    installer_file.write_bytes(b"A" * 100)

    stage_called = False

    def mock_stage(*args, **kwargs):
        nonlocal stage_called
        stage_called = True
        return StagedInstallerDraftEvidence(
            release_id=123,
            tag_name="v5.1.1",
            target_commit="sha_123",
            repo=DEFAULT_INSTALLER_REPO,
            installer_asset_id=501,
            installer_size=100,
            installer_sha256=hashlib.sha256(b"A" * 100).hexdigest(),
            dispatch_command="",
        )

    monkeypatch.setattr(
        "scripts.publish_installer_release.stage_installer_draft_release", mock_stage
    )

    execute_installer_publish(
        "v5.1.1",
        "sha_123",
        staging_dir=staging,
        installer_repo=DEFAULT_INSTALLER_REPO,
    )

    assert stage_called
    assert any(
        call
        == [
            "gh",
            "release",
            "edit",
            "v5.1.1",
            "--draft=false",
            "--repo",
            DEFAULT_INSTALLER_REPO,
        ]
        for call in run_calls
    )


def test_execute_installer_publish_hosted_verification_failure(monkeypatch, tmp_path):
    def mock_run(runner, args):
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            return json.dumps({
                "id": 123,
                "tag_name": "v5.1.1",
                "target_commitish": "sha_123",
                "draft": True,
                "prerelease": False,
                "assets": [{"name": "NekoFamilyProxy-Installer.exe", "id": 501, "size": 100}],
            })
        if args[0] == "gh" and args[1:3] == ["auth", "token"]:
            return "token"
        if args[0] == "curl":
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(b"WRONG_BYTES_FOR_DIGEST")
            return ""
        return "sha_123"

    monkeypatch.setattr("scripts.publish_installer_release._run", mock_run)

    staging = tmp_path / "staging"
    staging.mkdir()
    installer_file = staging / "NekoFamilyProxy-Installer.exe"
    installer_file.write_bytes(b"A" * 100)

    def mock_stage(*args, **kwargs):
        return StagedInstallerDraftEvidence(
            release_id=123,
            tag_name="v5.1.1",
            target_commit="sha_123",
            repo=DEFAULT_INSTALLER_REPO,
            installer_asset_id=501,
            installer_size=100,
            installer_sha256=hashlib.sha256(b"A" * 100).hexdigest(),
            dispatch_command="",
        )

    monkeypatch.setattr(
        "scripts.publish_installer_release.stage_installer_draft_release", mock_stage
    )

    with pytest.raises(InstallerPublishError, match="digest mismatch|size mismatch"):
        execute_installer_publish(
            "v5.1.1",
            "sha_123",
            staging_dir=staging,
            installer_repo=DEFAULT_INSTALLER_REPO,
        )


def test_execute_installer_publish_pre_promote_extra_asset(monkeypatch, tmp_path):
    calls_123 = 0

    def mock_run(runner, args):
        nonlocal calls_123
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            if "releases/123" in args[2]:
                calls_123 += 1
                if calls_123 == 1:
                    # hosted verification readback
                    return json.dumps({
                        "id": 123,
                        "tag_name": "v5.1.1",
                        "target_commitish": "sha_123",
                        "draft": True,
                        "prerelease": False,
                        "assets": [
                            {"name": "NekoFamilyProxy-Installer.exe", "id": 501, "size": 100},
                        ],
                    })
                else:
                    # pre-promote readback with extra asset
                    return json.dumps({
                        "id": 123,
                        "tag_name": "v5.1.1",
                        "target_commitish": "sha_123",
                        "draft": True,
                        "prerelease": False,
                        "assets": [
                            {"name": "NekoFamilyProxy-Installer.exe", "id": 501, "size": 100},
                            {"name": "extra.exe", "id": 502, "size": 200},
                        ],
                    })
        if args[0] == "gh" and args[1:3] == ["auth", "token"]:
            return "token"
        if args[0] == "curl":
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(b"A" * 100)
            return ""
        return "sha_123"

    monkeypatch.setattr("scripts.publish_installer_release._run", mock_run)
    monkeypatch.setattr(
        "scripts.verify_installer_release_assets.verify_installer_release_assets",
        lambda **kwargs: ("sha256", 100),
    )

    staging = tmp_path / "staging"
    staging.mkdir()
    installer_file = staging / "NekoFamilyProxy-Installer.exe"
    installer_file.write_bytes(b"A" * 100)

    def mock_stage(*args, **kwargs):
        return StagedInstallerDraftEvidence(
            release_id=123,
            tag_name="v5.1.1",
            target_commit="sha_123",
            repo=DEFAULT_INSTALLER_REPO,
            installer_asset_id=501,
            installer_size=100,
            installer_sha256=hashlib.sha256(b"A" * 100).hexdigest(),
            dispatch_command="",
        )

    monkeypatch.setattr(
        "scripts.publish_installer_release.stage_installer_draft_release", mock_stage
    )

    with pytest.raises(InstallerPublishError, match="mutated before promotion"):
        execute_installer_publish(
            "v5.1.1",
            "sha_123",
            staging_dir=staging,
            installer_repo=DEFAULT_INSTALLER_REPO,
        )


def test_execute_installer_publish_gate3_rejects_extra_asset(monkeypatch, tmp_path):
    t = 0

    def fake_time():
        nonlocal t
        t += 301
        return t

    monkeypatch.setattr("time.time", fake_time)
    monkeypatch.setattr("time.sleep", lambda s: None)

    def mock_run(runner, args):
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            if "releases/latest" in args[2]:
                return json.dumps({
                    "id": 123,
                    "tag_name": "v5.1.1",
                    "assets": [
                        {"name": "NekoFamilyProxy-Installer.exe", "id": 501, "size": 100},
                        {"name": "Setup.exe", "id": 502, "size": 200},
                    ],
                })
            return json.dumps({
                "id": 123,
                "tag_name": "v5.1.1",
                "target_commitish": "sha_123",
                "draft": True,
                "prerelease": False,
                "assets": [{"name": "NekoFamilyProxy-Installer.exe", "id": 501, "size": 100}],
            })
        if args[0] == "gh" and args[1:3] == ["auth", "token"]:
            return "token"
        if args[0] == "curl":
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(b"A" * 100)
            return ""
        return "sha_123"

    monkeypatch.setattr("scripts.publish_installer_release._run", mock_run)
    monkeypatch.setattr(
        "scripts.publish_installer_release.verify_installer_release_assets",
        lambda **kwargs: ("sha256", 100),
    )

    staging = tmp_path / "staging"
    staging.mkdir()
    installer_file = staging / "NekoFamilyProxy-Installer.exe"
    installer_file.write_bytes(b"A" * 100)

    def mock_stage(*args, **kwargs):
        return StagedInstallerDraftEvidence(
            release_id=123,
            tag_name="v5.1.1",
            target_commit="sha_123",
            repo=DEFAULT_INSTALLER_REPO,
            installer_asset_id=501,
            installer_size=100,
            installer_sha256=hashlib.sha256(b"A" * 100).hexdigest(),
            dispatch_command="",
        )

    monkeypatch.setattr(
        "scripts.publish_installer_release.stage_installer_draft_release", mock_stage
    )

    with pytest.raises(InstallerPublishError, match="Gate3 failed"):
        execute_installer_publish(
            "v5.1.1",
            "sha_123",
            staging_dir=staging,
            installer_repo=DEFAULT_INSTALLER_REPO,
        )


def test_verify_installer_release_assets_rejects_extra_asset(tmp_path):
    rel_doc = {
        "tag_name": "v5.1.1",
        "target_commitish": "1111111111111111111111111111111111111111",
        "draft": True,
        "prerelease": False,
        "assets": [
            {"name": "NekoFamilyProxy-Installer.exe", "id": 1, "size": 5},
            {"name": "extra.exe", "id": 2, "size": 10},
        ],
    }
    rel_path = tmp_path / "release.json"
    rel_path.write_text(json.dumps(rel_doc))
    inst_path = tmp_path / "NekoFamilyProxy-Installer.exe"
    inst_path.write_bytes(b"12345")

    with pytest.raises(InstallerReleaseVerificationError, match="exactly one custom asset"):
        verify_installer_release_assets(
            release_json_path=rel_path,
            installer_path=inst_path,
            expected_tag="v5.1.1",
            expected_target="1111111111111111111111111111111111111111",
            require_draft=True,
        )


def test_verify_installer_release_assets_rejects_machine_channel_assets(tmp_path):
    # If someone tries to pass machine assets to installer verifier
    rel_doc = {
        "tag_name": "v5.1.1",
        "target_commitish": "1111111111111111111111111111111111111111",
        "draft": True,
        "prerelease": False,
        "assets": [
            {"name": "release-v2.json", "id": 1, "size": 5},
        ],
    }
    rel_path = tmp_path / "release.json"
    rel_path.write_text(json.dumps(rel_doc))
    inst_path = tmp_path / "NekoFamilyProxy-Installer.exe"
    inst_path.write_bytes(b"12345")

    with pytest.raises(InstallerReleaseVerificationError, match="Asset name mismatch"):
        verify_installer_release_assets(
            release_json_path=rel_path,
            installer_path=inst_path,
            expected_tag="v5.1.1",
            expected_target="1111111111111111111111111111111111111111",
            require_draft=True,
        )
