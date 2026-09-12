from unittest.mock import patch

from scripts.kanban_release_adapter import (
    get_successful_main_runs,
    poll_github_and_create_tasks,
)


@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_get_successful_main_runs(mock_gh_run_list):
    mock_gh_run_list.return_value = b'''
    [
      {"databaseId": 3, "headSha": "sha_3", "createdAt": "2026-09-11T10:05:00Z"},
      {"databaseId": 2, "headSha": "sha_2", "createdAt": "2026-09-11T10:00:00Z"},
      {"databaseId": 1, "headSha": "sha_2", "createdAt": "2026-09-11T09:55:00Z"},
      {"databaseId": 4, "headSha": "sha_1", "createdAt": "2026-09-11T09:50:00Z"}
    ]
    '''
    runs = get_successful_main_runs()
    assert len(runs) == 4
    assert [r["databaseId"] for r in runs] == [4, 1, 2, 3]

@patch("scripts.kanban_release_adapter.get_armed_target_from_sha")
@patch("scripts.kanban_release_adapter.subprocess.run")
@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_idempotent_task_creation(mock_check_output, mock_hermes_kanban, mock_get_armed_target_from_sha):
    mock_get_armed_target_from_sha.return_value = ("v5.1.0", "v5.1.1", 5, "stable-0005")
    def mock_check_output_side_effect(cmd, **kwargs):
        if "gh" in cmd and "run" in cmd:
            return b'[{"databaseId": 100, "headSha": "sha_abc123", "createdAt": "2026-09-11T10:00:00Z"}]'
        elif "diff-tree" in cmd:
            return b"src/main.py\n"
        elif "gh" in cmd and "release" in cmd:
            return b'[]'
        return b""
    mock_check_output.side_effect = mock_check_output_side_effect

    poll_github_and_create_tasks()

    mock_hermes_kanban.assert_called_once()
    args = mock_hermes_kanban.call_args[0][0]
    assert "hermes" in args
    assert "kanban" in args
    assert "--board" in args
    assert "neko-family-5-1-stable" in args
    assert "create" in args
    assert "--assignee" in args
    assert "release" in args
    assert "--workspace" in args
    assert "worktree:E:/Github/Neko-Family-Proxy" in args
    assert "--idempotency-key" in args
    assert "release-100-sha_abc123" in args

    body_idx = args.index("--body") + 1
    body = args[body_idx]
    assert "100" in body
    assert "sha_abc123" in body
    assert "ONLY the reviewed release-controller CLI" in body

@patch("scripts.kanban_release_adapter.get_armed_target_from_sha")
@patch("scripts.kanban_release_adapter.subprocess.run")
@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_no_task_for_docs_only(mock_check_output, mock_hermes_kanban, mock_get_armed_target_from_sha):
    mock_get_armed_target_from_sha.return_value = ("v5.1.0", "v5.1.1", 5, "stable-0005")
    def mock_check_output_side_effect(cmd, **kwargs):
        if "gh" in cmd and "run" in cmd:
            return b'[{"databaseId": 101, "headSha": "sha_doc", "createdAt": "2026-09-11T10:00:00Z"}]'
        elif "diff-tree" in cmd:
            return b"docs/README.md\n"
        return b""
    mock_check_output.side_effect = mock_check_output_side_effect

    poll_github_and_create_tasks()
    mock_hermes_kanban.assert_not_called()

@patch("scripts.kanban_release_adapter.get_armed_target_from_sha")
@patch("scripts.kanban_release_adapter.subprocess.run")
@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_no_mutation_for_empty(mock_check_output, mock_hermes_kanban, mock_get_armed_target_from_sha):
    mock_get_armed_target_from_sha.return_value = ("v5.1.0", "v5.1.1", 5, "stable-0005")
    def mock_check_output_side_effect(cmd, **kwargs):
        if "gh" in cmd and "run" in cmd:
            return b'[]'
        return b""
    mock_check_output.side_effect = mock_check_output_side_effect

    poll_github_and_create_tasks()
    mock_hermes_kanban.assert_not_called()

def test_release_controller_import_no_error():
    try:
        from scripts.release_controller import process_accepted_commits
        assert callable(process_accepted_commits)
    except ImportError as e:
        import pytest
        pytest.fail(f"ImportError in release_controller: {e}")

@patch("scripts.kanban_release_adapter.get_armed_target_from_sha")
@patch("scripts.kanban_release_adapter.subprocess.run")
@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_kanban_task_workspace_and_cwd_contract(mock_check_output, mock_hermes_kanban, mock_get_armed_target_from_sha):
    mock_get_armed_target_from_sha.return_value = ("v5.1.0", "v5.1.1", 5, "stable-0005")
    def mock_check_output_side_effect(cmd, **kwargs):
        if "gh" in cmd and "run" in cmd:
            return b'[{"databaseId": 100, "headSha": "sha_abc123", "createdAt": "2026-09-11T10:00:00Z"}]'
        elif "diff-tree" in cmd:
            return b"src/main.py\n"
        elif "gh" in cmd and "release" in cmd:
            return b'[]'
        return b""
    mock_check_output.side_effect = mock_check_output_side_effect

    poll_github_and_create_tasks()

    mock_hermes_kanban.assert_called_once()
    args = mock_hermes_kanban.call_args[0][0]

    ws_idx = args.index("--workspace") + 1
    workspace = args[ws_idx]
    assert workspace == "worktree:E:/Github/Neko-Family-Proxy"

    body_idx = args.index("--body") + 1
    body = args[body_idx]
    assert "`python scripts/release_controller.py`" in body

@patch("scripts.kanban_release_adapter.get_armed_target_from_sha")
@patch("scripts.kanban_release_adapter.subprocess.run")
@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_closed_post_cutover_target_no_task(mock_check_output, mock_hermes_kanban, mock_get_armed_target_from_sha):
    mock_get_armed_target_from_sha.side_effect = ValueError("intent is closed")
    def mock_check_output_side_effect(cmd, **kwargs):
        if "gh" in cmd and "run" in cmd:
            return b'[{"databaseId": 100, "headSha": "sha_abc123", "createdAt": "2026-09-11T10:00:00Z"}]'
        elif "diff-tree" in cmd:
            return b"src/main.py\n"
        elif "gh" in cmd and "release" in cmd:
            return b'[]'
        return b""
    mock_check_output.side_effect = mock_check_output_side_effect

    poll_github_and_create_tasks()

    mock_hermes_kanban.assert_not_called()
