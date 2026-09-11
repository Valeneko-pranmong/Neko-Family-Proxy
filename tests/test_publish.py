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
