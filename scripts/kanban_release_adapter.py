import subprocess
import json

def get_successful_main_commits() -> list[str]:
    # Poll GitHub API for successful main commits using gh CLI
    # Only consider "Main Source Acceptance" workflow successes
    cmd = [
        "gh", "run", "list", 
        "--workflow", "Main Source Acceptance", 
        "--branch", "main", 
        "--status", "success", 
        "--json", "headSha,createdAt"
    ]
    
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        print(f"Failed to fetch GH runs: {e.output.decode()}")
        raise

    runs = json.loads(out)
    
    # Sort by createdAt to ensure oldest first (ordered creation)
    runs.sort(key=lambda x: x["createdAt"])
    
    # Deduplicate while preserving order
    seen = set()
    ordered_shas = []
    for run in runs:
        sha = run["headSha"]
        if sha not in seen:
            seen.add(sha)
            ordered_shas.append(sha)
            
    return ordered_shas

def create_kanban_task(sha: str):
    # Idempotently create Kanban task
    # We use Hermes CLI: hermes kanban create ...
    
    title = f"Release pipeline for {sha[:7]}"
    body = f"Automated release process for commit {sha}. Run build, sign, and publish."
    
    cmd = [
        "hermes", "kanban", "create",
        "--title", title,
        "--body", body,
        "--assignee", "default", # Need an assignee, use default or a release profile
        "--idempotency-key", f"release-{sha}"
    ]
    
    # Run hermes CLI
    subprocess.run(cmd, check=True)

def poll_github_and_create_tasks():
    for sha in get_successful_main_commits():
        create_kanban_task(sha)

if __name__ == "__main__":
    poll_github_and_create_tasks()
