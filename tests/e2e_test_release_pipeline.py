
def test_e2e_pipeline_simulation(monkeypatch):
    from scripts.release_controller import process_accepted_commits
    
    # 1. Fake Kanban DB queue
    monkeypatch.setattr("scripts.release_controller.get_pending_commits", lambda: ["sha_1", "sha_2", "sha_1"])
    
    mark_done_calls = []
    monkeypatch.setattr("scripts.release_controller.mark_done", lambda sha: mark_done_calls.append(sha))
    
    # 2. Fake GitHub releases for derivation
    releases = [{"tag_name": "v5.1.4", "prerelease": False}]
    monkeypatch.setattr("scripts.derive_version.get_github_releases", lambda: list(releases))
    
    # 3. Fake build and sign verification
    build_calls = []
    def mock_build(version, sha): build_calls.append((version, sha))
    monkeypatch.setattr("scripts.build_software_release_v2.build_all", mock_build, raising=False)
    
    sign_calls = []
    def mock_sign(version, sha): sign_calls.append((version, sha))
    monkeypatch.setattr("scripts.sign_software_release.verify_and_sign", mock_sign, raising=False)
    
    # 4. Fake atomic publish
    publish_calls = []
    def mock_publish(version, sha): 
        publish_calls.append((version, sha))
        releases.append({"tag_name": version, "prerelease": False})
    monkeypatch.setattr("scripts.publish_atomic_release.execute_publish", mock_publish)
    
    process_accepted_commits()
    
    assert build_calls == [("v5.1.5", "sha_1"), ("v5.1.6", "sha_2")]
    assert len(build_calls) == 2
    assert len(sign_calls) == 2
    assert publish_calls == [("v5.1.5", "sha_1"), ("v5.1.6", "sha_2")]
    assert mark_done_calls == ["sha_1", "sha_2"]
