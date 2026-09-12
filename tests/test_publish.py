def test_atomic_publish_payload():
    from scripts.publish_atomic_release import build_release_payload
    payload = build_release_payload("v5.1.5", "sha_123")
    assert payload["tag_name"] == "v5.1.5"
    assert payload["target_commitish"] == "sha_123"
    assert not payload["draft"]

def test_execute_publish_duplicate(monkeypatch):
    from scripts.publish_atomic_release import execute_publish

    def mock_run(runner, args):
        return '{"targetCommitish": "sha_123"}'

    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)

    called = False
    def mock_stage(*args, **kwargs):
        nonlocal called
        called = True
    monkeypatch.setattr("scripts.publish_atomic_release.stage_draft_release", mock_stage)

    execute_publish("v5.1.5", "sha_123")
    assert not called

def test_execute_publish_promotion(monkeypatch):
    from scripts.publish_atomic_release import execute_publish, StagedDraftEvidence

    run_calls = []
    def mock_run(runner, args):
        run_calls.append(args)
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            return '{"id": 123, "tag_name": "v5.1.5", "target_commitish": "sha_123", "draft": true, "assets": []}'
        return "sha_123"

    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)
    monkeypatch.setattr("scripts.verify_github_release_assets.verify_github_release_assets", lambda **kwargs: None)

    stage_called = False
    def mock_stage(*args, **kwargs):
        nonlocal stage_called
        stage_called = True
        return StagedDraftEvidence(
            release_id=123, tag_name="v5.1.5", target_commit="sha_123", assets={}, dispatch_command=""
        )
    monkeypatch.setattr("scripts.publish_atomic_release.stage_draft_release", mock_stage)

    execute_publish("v5.1.5", "sha_123")

    assert stage_called
    assert any(call == ["gh", "release", "edit", "v5.1.5", "--draft=false", "--repo", "Valeneko-pranmong/Neko-Family-Proxy"] for call in run_calls)

def test_execute_publish_failure_before_promotion(monkeypatch):
    from scripts.publish_atomic_release import execute_publish, StageDraftReleaseError
    import pytest

    run_calls = []
    def mock_run(runner, args):
        run_calls.append(args)
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            return '{"id": 123, "tag_name": "v5.1.5", "target_commitish": "sha_123", "draft": true, "assets": []}'
        return "sha_123"

    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)

    def mock_stage(*args, **kwargs):
        raise StageDraftReleaseError("Validation failed")

    monkeypatch.setattr("scripts.publish_atomic_release.stage_draft_release", mock_stage)

    with pytest.raises(StageDraftReleaseError):
        execute_publish("v5.1.5", "sha_123")

    for args in run_calls:
        if args[0:3] == ["gh", "release", "edit"]:
            pytest.fail("Should not promote if staging fails")


def test_execute_publish_gate3_timeout(monkeypatch):
    from scripts.publish_atomic_release import execute_publish, StagedDraftEvidence, StageDraftReleaseError

    def mock_run(runner, args):
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            if "latest" in args[2]:
                return '{"id": 999, "tag_name": "wrong", "assets": []}'
            return '{"id": 123, "tag_name": "v5.1.5", "target_commitish": "sha_123", "draft": true, "assets": []}'
        return "sha_123"

    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)
    monkeypatch.setattr("scripts.verify_github_release_assets.verify_github_release_assets", lambda **kwargs: None)
    monkeypatch.setattr("time.time", lambda: 0)

    def mock_stage(*args, **kwargs):
        return StagedDraftEvidence(123, "v5.1.5", "sha_123", {}, "")
    monkeypatch.setattr("scripts.publish_atomic_release.stage_draft_release", mock_stage)

    t = 0
    def fake_time():
        nonlocal t
        t += 301
        return t
    monkeypatch.setattr("time.time", fake_time)
    monkeypatch.setattr("time.sleep", lambda s: None)

    import pytest
    with pytest.raises(StageDraftReleaseError, match="Gate3 failed"):
        execute_publish("v5.1.5", "sha_123")

def test_execute_publish_hosted_verification_drift(monkeypatch):
    from scripts.publish_atomic_release import execute_publish, StagedDraftEvidence, StageDraftReleaseError

    def mock_run(runner, args):
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            return '{"id": 123, "tag_name": "v5.1.5", "target_commitish": "sha_123", "draft": true, "assets": [{"name": "fake", "id": 99, "size": 999}]}'
        return "sha_123"

    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)
    monkeypatch.setattr("scripts.verify_github_release_assets.verify_github_release_assets", lambda **kwargs: None)

    def mock_stage(*args, **kwargs):
        return StagedDraftEvidence(123, "v5.1.5", "sha_123", {"fake": 99}, "")
    monkeypatch.setattr("scripts.publish_atomic_release.stage_draft_release", mock_stage)

    import pytest
    monkeypatch.setattr("pathlib.Path.stat", lambda self: type("FakeStat", (), {"st_size": 100})())
    monkeypatch.setattr("pathlib.Path.read_bytes", lambda self: b"fake")

    with pytest.raises(StageDraftReleaseError, match="mutated before promotion"):
        execute_publish("v5.1.5", "sha_123")

def test_execute_publish_token_redaction_regression(monkeypatch):
    from scripts.publish_atomic_release import execute_publish, StagedDraftEvidence

    run_calls = []

    def mock_run(runner, args):
        run_calls.append(args)
        if args == ["gh", "auth", "token"]:
            return "gho_SENTINEL_TOKEN_12345\n"
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            return '{"id": 123, "tag_name": "v5.1.5", "target_commitish": "sha_123", "draft": true, "assets": [{"name": "asset.zip", "id": 99, "size": 100}]}'
        if args[0] == "curl":
            return ""
        return "sha_123"

    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)
    monkeypatch.setattr("scripts.verify_github_release_assets.verify_github_release_assets", lambda **kwargs: None)

    def mock_stage(*args, **kwargs):
        return StagedDraftEvidence(123, "v5.1.5", "sha_123", {"asset.zip": 99}, "")
    monkeypatch.setattr("scripts.publish_atomic_release.stage_draft_release", mock_stage)

    monkeypatch.setattr("pathlib.Path.stat", lambda self: type("FakeStat", (), {"st_size": 100})())
    monkeypatch.setattr("pathlib.Path.read_bytes", lambda self: b"fake_content")

    # Needs a mock for writing release.json to avoid FileNotFoundError
    monkeypatch.setattr("pathlib.Path.write_text", lambda self, text, encoding=None: None)

    execute_publish("v5.1.5", "sha_123")

    curl_args = [args for args in run_calls if args[0] == "curl"]
    assert len(curl_args) == 1

    assert "Authorization: Bearer gho_SENTINEL_TOKEN_12345" in curl_args[0], "Generated curl argv must contain exactly Authorization: Bearer <sentinel>"

    for arg in curl_args[0]:
        assert "***" not in arg, "argv must never contain literal ***"

def test_execute_publish_token_failure_before_promotion(monkeypatch):
    from scripts.publish_atomic_release import execute_publish, StagedDraftEvidence

    run_calls = []

    def mock_run(runner, args):
        run_calls.append(args)
        if args == ["gh", "auth", "token"]:
            raise Exception("gh auth token failed")
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        return "sha_123"

    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)

    def mock_stage(*args, **kwargs):
        return StagedDraftEvidence(123, "v5.1.5", "sha_123", {"asset.zip": 99}, "")
    monkeypatch.setattr("scripts.publish_atomic_release.stage_draft_release", mock_stage)

    import pytest
    with pytest.raises(Exception, match="gh auth token failed"):
        execute_publish("v5.1.5", "sha_123")

    # Ensure no curl or promote commands were issued
    for args in run_calls:
        if args[0] == "curl":
            pytest.fail("Should not execute curl if token fetch fails")
        if args[0:3] == ["gh", "release", "edit"]:
            pytest.fail("Should not promote if token fetch fails")


def test_execute_publish_passes_machine_release_notes(monkeypatch):
    from scripts.publish_atomic_release import execute_publish, StagedDraftEvidence

    stage_kwargs = {}

    def mock_run(runner, args):
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            return '{"id": 123, "tag_name": "v5.1.5", "target_commitish": "sha_123", "draft": true, "assets": []}'
        return "sha_123"

    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)
    monkeypatch.setattr("scripts.verify_github_release_assets.verify_github_release_assets", lambda **kwargs: None)

    def mock_stage(*args, **kwargs):
        nonlocal stage_kwargs
        stage_kwargs = kwargs
        return StagedDraftEvidence(
            release_id=123, tag_name="v5.1.5", target_commit="sha_123", assets={}, dispatch_command=""
        )
    monkeypatch.setattr("scripts.publish_atomic_release.stage_draft_release", mock_stage)

    execute_publish("v5.1.5", "sha_123")
    assert "notes" in stage_kwargs
    assert "Valeneko-pranmong/Neko-Family-Proxy-Installer" in stage_kwargs["notes"]
    assert "v5.1.5" in stage_kwargs["notes"]


def test_execute_publish_rejects_extra_asset_before_promotion(monkeypatch):
    from scripts.publish_atomic_release import execute_publish, StagedDraftEvidence, StageDraftReleaseError
    import pytest

    def mock_run(runner, args):
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            # pre_promote returns an extra asset not in evidence.assets
            return '{"id": 123, "tag_name": "v5.1.5", "target_commitish": "sha_123", "draft": true, "assets": [{"name": "allowed.zip", "id": 99, "size": 100}, {"name": "extra.exe", "id": 100, "size": 200}]}'
        return "sha_123"

    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)
    monkeypatch.setattr("scripts.verify_github_release_assets.verify_github_release_assets", lambda **kwargs: None)

    def mock_stage(*args, **kwargs):
        return StagedDraftEvidence(123, "v5.1.5", "sha_123", {"allowed.zip": 99}, "")
    monkeypatch.setattr("scripts.publish_atomic_release.stage_draft_release", mock_stage)

    monkeypatch.setattr("pathlib.Path.stat", lambda self: type("FakeStat", (), {"st_size": 100})())
    monkeypatch.setattr("pathlib.Path.read_bytes", lambda self: b"fake")

    with pytest.raises(StageDraftReleaseError, match="mismatch|extra|unexpected"):
        execute_publish("v5.1.5", "sha_123")


def test_execute_publish_gate3_rejects_extra_asset(monkeypatch):
    from scripts.publish_atomic_release import execute_publish, StagedDraftEvidence, StageDraftReleaseError
    import pytest

    def mock_run(runner, args):
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0] == "gh" and args[1] == "api":
            if "latest" in args[2]:
                # Latest release contains extra asset
                return '{"id": 123, "tag_name": "v5.1.5", "assets": [{"name": "allowed.zip", "id": 99, "size": 100}, {"name": "Setup.exe", "id": 101, "size": 500}]}'
            return '{"id": 123, "tag_name": "v5.1.5", "target_commitish": "sha_123", "draft": true, "assets": [{"name": "allowed.zip", "id": 99, "size": 100}]}'
        return "sha_123"

    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)
    monkeypatch.setattr("scripts.verify_github_release_assets.verify_github_release_assets", lambda **kwargs: None)

    t = 0
    def fake_time():
        nonlocal t
        t += 301
        return t
    monkeypatch.setattr("time.time", fake_time)
    monkeypatch.setattr("time.sleep", lambda s: None)

    def mock_stage(*args, **kwargs):
        return StagedDraftEvidence(123, "v5.1.5", "sha_123", {"allowed.zip": 99}, "")
    monkeypatch.setattr("scripts.publish_atomic_release.stage_draft_release", mock_stage)

    monkeypatch.setattr("pathlib.Path.stat", lambda self: type("FakeStat", (), {"st_size": 100})())
    monkeypatch.setattr("pathlib.Path.read_bytes", lambda self: b"fake")

    with pytest.raises(StageDraftReleaseError, match="Gate3 failed"):
        execute_publish("v5.1.5", "sha_123")
