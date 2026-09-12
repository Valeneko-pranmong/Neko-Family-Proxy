from unittest.mock import patch
import pytest
import os

from scripts.ci_change_classifier import should_trigger

from scripts.kanban_release_adapter import (
    get_successful_main_runs,
    poll_github_and_create_tasks,
    create_kanban_task,
    get_changed_files_for_sha,
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
        pytest.fail(f"ImportError in release_controller: {e}")

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

# --- New tests for task runtime binding contract ---

@patch("scripts.kanban_release_adapter.subprocess.check_output")
@patch("scripts.kanban_release_adapter.subprocess.run")
def test_create_kanban_task_dirty_runtime_blocks(mock_run, mock_check_output):
    # simulate dirty git status
    def check_output_side_effect(cmd, **kwargs):
        if "status" in cmd and "--porcelain" in cmd:
            return b" M some_file.py\n"
        elif "rev-parse" in cmd:
            return b"c0ffee\n"
        elif "merge-base" in cmd:
            return b"c0ffee\n"
        return b""
    mock_check_output.side_effect = check_output_side_effect

    with pytest.raises(RuntimeError, match="runtime worktree is not clean"):
        create_kanban_task(100, "target_sha")
    mock_run.assert_not_called()

@patch("scripts.kanban_release_adapter.subprocess.check_output")
@patch("scripts.kanban_release_adapter.subprocess.run")
def test_create_kanban_task_not_ancestor_blocks(mock_run, mock_check_output):
    # simulate controller commit not ancestor of origin/main
    def check_output_side_effect(cmd, **kwargs):
        if "status" in cmd and "--porcelain" in cmd:
            return b""
        elif "rev-parse" in cmd:
            return b"c0ffee\n"
        elif "merge-base" in cmd:
            return b"not_c0ffee\n"
        return b""
    mock_check_output.side_effect = check_output_side_effect

    with pytest.raises(RuntimeError, match="not an ancestor of origin/main"):
        create_kanban_task(100, "target_sha")
    mock_run.assert_not_called()

@patch("scripts.kanban_release_adapter.subprocess.check_output")
@patch("scripts.kanban_release_adapter.subprocess.run")
def test_create_kanban_task_success_binding(mock_run, mock_check_output):
    def check_output_side_effect(cmd, **kwargs):
        if "status" in cmd and "--porcelain" in cmd:
            return b""
        elif "rev-parse" in cmd:
            if "HEAD" in cmd:
                return b"c0ffee\n"
            return b"c0ffee\n"
        elif "merge-base" in cmd:
            return b"c0ffee\n"
        return b""
    mock_check_output.side_effect = check_output_side_effect

    create_kanban_task(100, "target_sha")

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]

    # Assert canonical string is absent from arguments
    for arg in args:
        assert "E:/Github/Neko-Family-Proxy" not in arg

    # Check workspace dynamic binding and path serialization
    ws_idx = args.index("--workspace") + 1
    workspace = args[ws_idx]
    assert workspace.startswith("worktree:")
    # Must use forward slashes for cross-platform Hermes syntax, even on Windows
    assert "\\" not in workspace
    runtime_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    normalized_root = runtime_root.replace('\\', '/')
    assert workspace == f"worktree:{normalized_root}"

    # Check idempotency key preserved
    assert "--idempotency-key" in args
    idem_idx = args.index("--idempotency-key") + 1
    assert args[idem_idx] == "release-100-target_sha"

    # Check body details
    body_idx = args.index("--body") + 1
    body = args[body_idx]
    assert "target_sha" in body
    assert "100" in body
    assert "c0ffee" in body # controller SHA
    assert f"Runtime Workspace: {normalized_root}" in body
    assert "`git fetch origin main` ONLY" in body
    assert "Reassert HEAD==c0ffee after fetch" in body
    assert "NEVER checkout/reset/rebase/cherry-pick" in body
    assert "uv run python scripts/release_controller.py --commit target_sha --run-id 100" in body

@patch("scripts.kanban_release_adapter.get_armed_target_from_sha")
@patch("scripts.kanban_release_adapter.subprocess.run")
@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_idempotent_task_creation_with_valid_runtime(mock_check_output, mock_hermes_kanban, mock_get_armed_target_from_sha):
    mock_get_armed_target_from_sha.return_value = ("v5.1.0", "v5.1.1", 5, "stable-0005")
    def mock_check_output_side_effect(cmd, **kwargs):
        if "gh" in cmd and "run" in cmd:
            return b'[{"databaseId": 100, "headSha": "sha_abc123", "createdAt": "2026-09-11T10:00:00Z"}]'
        elif "diff-tree" in cmd:
            return b"src/main.py\n"
        elif "gh" in cmd and "release" in cmd:
            return b'[]'
        elif "status" in cmd and "--porcelain" in cmd:
            return b""
        elif "rev-parse" in cmd:
            return b"c0ffee\n"
        elif "merge-base" in cmd:
            return b"c0ffee\n"
        return b""
    mock_check_output.side_effect = mock_check_output_side_effect

    poll_github_and_create_tasks()

    mock_hermes_kanban.assert_called_once()

@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_get_changed_files_merge_dedup_local(mock_check_output):
    def check_output_side_effect(cmd, **kwargs):
        assert "diff-tree" in cmd
        assert "--no-commit-id" in cmd
        assert "--name-only" in cmd
        assert "-r" in cmd
        assert "-m" in cmd
        assert "-C" in cmd
        # verify repo root is absolute
        c_idx = cmd.index("-C")
        assert os.path.isabs(cmd[c_idx+1])
        return b"fileA.py\nfileB.py\nfileA.py\n"

    mock_check_output.side_effect = check_output_side_effect
    files = get_changed_files_for_sha("merge_sha")
    assert files == ["fileA.py", "fileB.py"]
    assert mock_check_output.call_count == 1

@patch("scripts.kanban_release_adapter.subprocess.check_output")
def test_get_changed_files_merge_dedup_fallback(mock_check_output):
    import subprocess
    def check_output_side_effect(cmd, **kwargs):
        if "diff-tree" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
        elif "gh" in cmd:
            return b"fileA.py\nfileC.py\nfileA.py\n"
        return b""
    mock_check_output.side_effect = check_output_side_effect

    files = get_changed_files_for_sha("merge_sha")
    assert files == ["fileA.py", "fileC.py"]
    assert mock_check_output.call_count == 2

def test_classifier_remains_release_eligible_on_merge():
    # non-merge list unchanged behavior: single file that is product triggers
    assert should_trigger(["src/main.py"]) is True
    # duplicate paths across parents from merge
    assert should_trigger(["src/main.py", "docs/README.md", "src/main.py"]) is True
    # non product
    assert should_trigger(["docs/README.md", "docs/README.md"]) is False
