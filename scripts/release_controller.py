from typing import List
import subprocess

def get_pending_commits() -> List[str]:
    # Placeholder for reading Kanban queue
    from scripts.kanban_release_adapter import get_successful_main_commits
    return get_successful_main_commits()

def mark_done(sha: str):
    # Placeholder for completing Kanban task
    pass

def get_changed_files(sha: str) -> List[str]:
    cmd = ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return out.decode().splitlines()
    except subprocess.CalledProcessError:
        return []

def process_accepted_commits():
    from scripts.derive_version import get_github_releases, get_next_patch
    from scripts.publish_atomic_release import execute_publish
    from scripts.ci_change_classifier import should_trigger
    import scripts.build_software_release_v2 as b
    import scripts.sign_software_release as s
    
    seen = set()
    pending = get_pending_commits()
    for sha in pending:
        if sha in seen:
            continue
        seen.add(sha)
        
        changed_files = get_changed_files(sha)
        if not should_trigger(changed_files):
            # Skip CI/docs only changes
            mark_done(sha)
            continue
        
        releases = get_github_releases()
        next_patch = get_next_patch(releases)
        
        if hasattr(b, "build_all"):
            b.build_all(next_patch, sha)
        
        if hasattr(s, "verify_and_sign"):
            s.verify_and_sign(next_patch, sha)
            
        execute_publish(next_patch, sha)
        mark_done(sha)
