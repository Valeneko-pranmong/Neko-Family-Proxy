import subprocess
import json
import os
import sys

# Ensure scripts module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.ci_change_classifier import should_trigger

def get_successful_main_commits() -> list[str]:
    # Stub to prevent import errors in placeholder release_controller.py
    # Will be removed in R2 when release_controller.py becomes a CLI.
    return []

def get_successful_main_runs() -> list[dict]:
    cmd = [
        "gh", "run", "list", 
        "--workflow", "Main Source Acceptance", 
        "--branch", "main", 
        "--status", "success", 
        "--json", "databaseId,headSha,createdAt"
    ]
    
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        print(f"Failed to fetch GH runs: {e.output.decode()}")
        raise

    runs = json.loads(out)
    
    # Sort by createdAt to ensure oldest first
    runs.sort(key=lambda x: x["createdAt"])
    
    # Deduplicate while preserving order based on run identity
    seen = set()
    ordered_runs = []
    for run in runs:
        identity = (run["databaseId"], run["headSha"])
        if identity not in seen:
            seen.add(identity)
            ordered_runs.append(run)
            
    return ordered_runs

def get_changed_files_for_sha(sha: str) -> list[str]:
    # Use git locally or gh api if git is insufficient. Git diff-tree is highly authoritative locally.
    try:
        out = subprocess.check_output(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha])
        return [line for line in out.decode().splitlines() if line]
    except subprocess.CalledProcessError:
        # Fallback to GH API if local git doesn't have the sha
        out = subprocess.check_output(["gh", "api", f"repos/Valeneko-pranmong/Neko-Family-Proxy/commits/{sha}", "--jq", ".files[].filename"])
        return [line for line in out.decode().splitlines() if line]

def create_kanban_task(run_id: int, sha: str):
    title = f"Release pipeline for {sha[:7]}"
    body = (
        f"Automated release process for commit {sha} from run {run_id}.\n"
        f"Invoke ONLY the reviewed release-controller CLI (`python scripts/release_controller.py`) for this identity.\n"
        f"Never patch/improvise build/sign/publish."
    )
    
    cmd = [
        "hermes", "kanban", "--board", "neko-family-5-1-stable", "create",
        title,
        "--body", body,
        "--assignee", "release",
        "--workspace", "dir:E:/Github/Project manager",
        "--idempotency-key", f"release-{run_id}-{sha}"
    ]
    
    env = os.environ.copy()
    env.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
    env.pop("HERMES_SUPERVISED_CHILD", None)
    subprocess.run(cmd, check=True, env=env)

def poll_github_and_create_tasks():
    for run in get_successful_main_runs():
        run_id = run["databaseId"]
        sha = run["headSha"]
        files = get_changed_files_for_sha(sha)
        if should_trigger(files):
            create_kanban_task(run_id, sha)

if __name__ == "__main__":
    poll_github_and_create_tasks()
