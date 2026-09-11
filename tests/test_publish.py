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
        return "sha_123"
    
    monkeypatch.setattr("scripts.publish_atomic_release._run", mock_run)
    
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
    assert run_calls[-1] == ["gh", "release", "edit", "v5.1.5", "--draft=false", "--repo", "Valeneko-pranmong/Neko-Family-Proxy"]

def test_execute_publish_failure_before_promotion(monkeypatch):
    from scripts.publish_atomic_release import execute_publish, StageDraftReleaseError
    import pytest
    
    run_calls = []
    def mock_run(runner, args):
        run_calls.append(args)
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
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
