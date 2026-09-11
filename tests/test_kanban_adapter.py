from unittest.mock import patch
from scripts.kanban_release_adapter import get_successful_main_commits, poll_github_and_create_tasks

@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_get_successful_main_commits(mock_gh_run_list):
    mock_gh_run_list.return_value = b'''
    [
      {"headSha": "sha_3", "createdAt": "2026-09-11T10:05:00Z"},
      {"headSha": "sha_2", "createdAt": "2026-09-11T10:00:00Z"},
      {"headSha": "sha_2", "createdAt": "2026-09-11T09:55:00Z"},
      {"headSha": "sha_1", "createdAt": "2026-09-11T09:50:00Z"}
    ]
    '''
    # Should deduplicate, ignore non-success (which gh CLI filters), 
    # and return ordered by createdAt (oldest first) so we release in order.
    commits = get_successful_main_commits()
    assert commits == ["sha_1", "sha_2", "sha_3"]

@patch("scripts.kanban_release_adapter.subprocess.run")
@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_idempotent_task_creation(mock_gh_run_list, mock_hermes_kanban):
    mock_gh_run_list.return_value = b'[{"headSha": "sha_abc123", "createdAt": "2026-09-11T10:00:00Z"}]'
    
    poll_github_and_create_tasks()
    
    mock_hermes_kanban.assert_called_once()
    args = mock_hermes_kanban.call_args[0][0]
    assert "hermes" in args
    assert "kanban" in args
    assert "create" in args
    # Ensure idempotency key is passed
    assert "--idempotency-key" in args
    assert "release-sha_abc123" in args
    
@patch("scripts.kanban_release_adapter.subprocess.run")
@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_no_mutation_for_empty(mock_gh_run_list, mock_hermes_kanban):
    mock_gh_run_list.return_value = b'[]'
    
    poll_github_and_create_tasks()
    
    mock_hermes_kanban.assert_not_called()
