from scripts.release_controller import process_accepted_commits
import json

def test_e2e_pipeline_simulation(monkeypatch, tmp_path):
    sha_docs = "1111111111111111111111111111111111111111"
    sha_1    = "2222222222222222222222222222222222222222"
    sha_2    = "3333333333333333333333333333333333333333"

    queued_commits = [sha_docs, sha_1, sha_2, sha_1, sha_docs]
    monkeypatch.setattr("scripts.release_controller.get_pending_commits", lambda: queued_commits)
    
    mark_done_calls = []
    monkeypatch.setattr("scripts.release_controller.mark_done", lambda sha: mark_done_calls.append(sha))
    
    def fake_get_changed_files(sha):
        if sha == sha_docs:
            return ["docs/README.md"]
        elif sha == sha_1:
            return ["launcher/src/main.py"]
        elif sha == sha_2:
            return ["docs/README.md", "launcher/src/updater.py"]
        return []
    monkeypatch.setattr("scripts.release_controller.get_changed_files", fake_get_changed_files)
    
    releases = [{"tag_name": "v5.1.4", "prerelease": False}]
    monkeypatch.setattr("scripts.derive_version.get_github_releases", lambda: list(releases))
    
    build_calls = []
    def mock_build(version, sha):
        build_calls.append((version, sha))
    monkeypatch.setattr("scripts.build_software_release_v2.build_all", mock_build, raising=False)
    
    sign_calls = []
    def mock_sign(version, sha):
        sign_calls.append((version, sha))
    monkeypatch.setattr("scripts.sign_software_release.verify_and_sign", mock_sign, raising=False)
    
    cli_commands = []
    def fake_run(executor, args, **kwargs):
        cli_commands.append(args)
        if args[0:3] == ["gh", "release", "view"]:
            raise Exception("Not found")
        if args[0:3] == ["git", "rev-parse"]:
            return "not-bound-so-create-tag"
        if args[0:3] == ["gh", "api", "repos/Valeneko-pranmong/Neko-Family-Proxy/git/ref/tags/v5.1.5"]:
            return json.dumps({"object": {"type": "commit", "sha": sha_1}})
        if args[0:3] == ["gh", "api", "repos/Valeneko-pranmong/Neko-Family-Proxy/git/ref/tags/v5.1.6"]:
            return json.dumps({"object": {"type": "commit", "sha": sha_2}})
        if args[0:2] == ["gh", "api"] and "releases?per_page=100" in args[2]:
            return json.dumps([[{
                "id": 123, 
                "draft": True, 
                "tag_name": "v5.1.5" if "v5.1.5" in str(cli_commands) else "v5.1.6", 
                "target_commitish": sha_1 if "v5.1.5" in str(cli_commands) else sha_2
            }]])
        if args[0:2] == ["gh", "api"] and "releases/123" in args[2]:
            return json.dumps({
                "id": 123,
                "draft": True,
                "tag_name": "v5.1.5" if "v5.1.5" in str(cli_commands) else "v5.1.6",
                "target_commitish": sha_1 if "v5.1.5" in str(cli_commands) else sha_2,
                "prerelease": False,
                "assets": [
                    {"name": "NekoFamilyProxy-Setup.exe", "id": 1, "size": 10},
                    {"name": "NekoLauncher.exe", "id": 2, "size": 10},
                    {"name": "NekoUpdater.exe", "id": 3, "size": 10},
                    {"name": "NekoProxyCore.zip", "id": 4, "size": 10},
                    {"name": "release-v2.json", "id": 5, "size": 10}
                ]
            })
        return "fake-output"
        
    monkeypatch.setattr("scripts.publish_atomic_release._run", fake_run)
    
    dummy_file = tmp_path / "dummy"
    dummy_file.write_bytes(b"0123456789") # 10 bytes to match
    
    def fake_validate(*args, **kwargs):
        return {
            "NekoFamilyProxy-Setup.exe": dummy_file,
            "NekoLauncher.exe": dummy_file,
            "NekoUpdater.exe": dummy_file,
            "NekoProxyCore.zip": dummy_file,
            "release-v2.json": dummy_file
        }
    monkeypatch.setattr("scripts.publish_atomic_release.validate_staging_preconditions", fake_validate)
    
    # Wrap original execute_publish to record releases
    from scripts.publish_atomic_release import execute_publish
    original_execute = execute_publish
    all_cli_commands = []
    def mock_publish_and_increment(version, sha):
        original_execute(version, sha)
        releases.append({"tag_name": version, "prerelease": False})
        all_cli_commands.extend(cli_commands)
        cli_commands.clear() # Clear state for the next publish!

    monkeypatch.setattr("scripts.publish_atomic_release.execute_publish", mock_publish_and_increment)
    
    process_accepted_commits()
    
    assert build_calls == [("v5.1.5", sha_1), ("v5.1.6", sha_2)]
    
    gh_calls = [cmd for cmd in all_cli_commands if cmd[0] == "gh"]
    
    draft_creates = [cmd for cmd in gh_calls if cmd[0:3] == ["gh", "release", "create"] and "--draft" in cmd]
    draft_publishes = [cmd for cmd in gh_calls if cmd[0:3] == ["gh", "release", "edit"] and "--draft=false" in cmd]
    
    assert len(draft_creates) == 2, "Draft release should be created"
    assert len(draft_publishes) == 2, "Draft should be promoted"
    
    assert mark_done_calls == [sha_docs, sha_1, sha_2]

