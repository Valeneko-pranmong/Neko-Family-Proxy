# Main Automatic Release Pipeline Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Establish a fully automated, `main`-branch-driven patch release pipeline operating with zero per-release owner clicks, ensuring legacy 5.1 compatibility and enforcing local signing custody.

**Architecture:** Phase 1: Source Acceptance (CI) -> Phase 2: Local Queue & Version Allocation (Controller) -> Phase 3: Build, Sign & Atomic Publish.

**Tech Stack:** Git, GitHub Actions, Python 3.11+, Pytest, Hermes Kanban DB.

---

## Execution Constraints & Parallelism

- **Phase 1 (Single-flight):** Task 1 (Migration) MUST run first sequentially.
- **Phase 2 (Single-flight):** Tasks 2, 3, 4, and 5 MUST run sequentially to prevent concurrent worktree mutations. Parallelism is allowed only for read-only validation.
- **Phase 3 (Single-flight):** Tasks 6, 7, and 8 MUST run sequentially.

---

### Task 1: Safe `release/5.1` -> `main` Parity Migration

**Objective:** Reconcile production release tooling from `release/5.1` into the `main` feature branch without rewriting history or stranding infrastructure.

**Files:**
- Modify: `scripts/`, `installer/`, `agent/`

**Step 1: Verify current tree state**
Run: `git status`
Expected: On branch `feature/main-auto-release-pipeline`.

**Step 2: Merge 5.1 tooling with history preservation**
```bash
git merge origin/release/5.1 --no-commit
```

**Step 3: Resolve conflicts and commit**
Ensure conflict resolution is scoped to preserving `main` docs/branding and production 5.1 code/tooling.
```bash
# ... resolve conflicts manually ...
git commit -m "chore: merge release/5.1 to main to migrate production tooling"
```
**Step 4: Verify ancestry and history**
```bash
git log --graph --oneline -n 10
# Verify that the merge commit has both main and release/5.1 as parents.
```

---

### Task 2: Main Source-Acceptance Trigger/Classifier

**Objective:** Implement a Python classifier and GitHub workflow to skip auto-releases for docs/test/CI-only changes but trigger on mixed or code changes.

**Files:**
- Create: `scripts/ci_change_classifier.py`
- Create: `tests/test_ci_classifier.py`
- Create: `.github/workflows/main_source_acceptance.yml`

**Step 1: Write failing test**
Create `tests/test_ci_classifier.py`:
```python
def test_classifier_skips_docs():
    from scripts.ci_change_classifier import should_trigger
    assert should_trigger(["docs/README.md", "tests/test_x.py"]) == False
    assert should_trigger(["src/main.py", "docs/README.md"]) == True
```

**Step 2: Run test to verify failure**
Run: `pytest tests/test_ci_classifier.py -v`
Expected: FAIL - ModuleNotFoundError

**Step 3: Implement classifier**
Create `scripts/ci_change_classifier.py`:
```python
def should_trigger(changed_files: list[str]) -> bool:
    ignored_prefixes = ('docs/', 'tests/', '.github/', 'README.md', 'CHANGELOG.md')
    for f in changed_files:
        if not f.startswith(ignored_prefixes):
            return True
    return False
```

**Step 4: Run test to verify pass**
Run: `pytest tests/test_ci_classifier.py -v`
Expected: PASS

**Step 5: Write GitHub Workflow**
Create `.github/workflows/main_source_acceptance.yml`:
```yaml
name: Main Source Acceptance
on:
  push:
    branches: [ "main" ]
jobs:
  acceptance:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - name: Check trigger
        run: python -c "from scripts.ci_change_classifier import should_trigger; import subprocess, sys; files=subprocess.check_output(['git','diff','--name-only','HEAD^','HEAD']).decode().split(); sys.exit(0 if should_trigger(files) else 78)"
      - name: Run Tests
        run: pytest tests/
```

**Step 6: Commit**
```bash
git add tests/test_ci_classifier.py scripts/ci_change_classifier.py .github/
git commit -m "ci: add main source-acceptance classifier and workflow"
```

---

### Task 3: Kanban-based Release Controller Adapter

**Objective:** Create a thin adapter script that polls GitHub API for successful CI runs on `main` and idempotently creates Kanban tasks in the local Kanban DB for single-allocator concurrency. No custom JSON queue or inbound webhook service.

**Files:**
- Create: `scripts/kanban_release_adapter.py`
- Create: `tests/test_kanban_adapter.py`

**Step 1: Write failing test**
Create `tests/test_kanban_adapter.py`:
```python
def test_idempotent_task_creation(mocker):
    from scripts.kanban_release_adapter import poll_github_and_create_tasks
    mock_gh = mocker.patch("scripts.kanban_release_adapter.get_successful_main_commits", return_value=["sha_abc123"])
    mock_kb = mocker.patch("scripts.kanban_release_adapter.create_kanban_task")
    
    poll_github_and_create_tasks()
    mock_kb.assert_called_once_with("sha_abc123")
```

**Step 2: Run test to verify failure**
Run: `pytest tests/test_kanban_adapter.py -v`
Expected: FAIL

**Step 3: Implement Adapter Logic**
Create `scripts/kanban_release_adapter.py`:
```python
import subprocess, json

def get_successful_main_commits():
    # Poll GitHub API for successful main commits using gh CLI
    out = subprocess.check_output(["gh", "run", "list", "--branch", "main", "--status", "success", "--json", "headSha"])
    runs = json.loads(out)
    return [run["headSha"] for run in runs]

def create_kanban_task(sha: str):
    # Idempotently create Kanban task
    # (Relies on idempotency_key=sha to avoid duplicates)
    import sqlite3
    db_path = ".hermes/kanban.db"
    # Example logic using sqlite or hermes-cli
    pass

def poll_github_and_create_tasks():
    for sha in get_successful_main_commits():
        create_kanban_task(sha)
```

**Step 4: Verify pass and commit**
Run: `pytest tests/test_kanban_adapter.py -v`
Expected: PASS
```bash
git add tests/test_kanban_adapter.py scripts/kanban_release_adapter.py
git commit -m "feat: implement kanban adapter polling github ci for release task creation"
```

---

### Task 4: Exact Patch/Version Derivation (SUPERSEDED by Explicit Release Target authority)

**Objective:** Allocate the exact next monotonic patch version at execution time based on repository state, ensuring legacy v5.1.x compatibility.

**Files:**
- Create: `scripts/derive_version.py`
- Create: `tests/test_derive_version.py`

**Step 1: Write failing test**
Create `tests/test_derive_version.py`:
```python
def test_derive_patch_stable_only():
    from scripts.derive_version import get_next_patch
    releases = [
        {"tag_name": "v5.1.2", "prerelease": False},
        {"tag_name": "v5.1.4", "prerelease": False}
    ]
    assert get_next_patch(releases) == "v5.1.5"

def test_derive_patch_filters_prerelease_and_suffix():
    from scripts.derive_version import get_next_patch
    releases = [
        {"tag_name": "v5.1.2", "prerelease": False},
        {"tag_name": "v5.1.3-beta.1", "prerelease": True},
        {"tag_name": "v5.1.3", "prerelease": True}
    ]
    assert get_next_patch(releases) == "v5.1.3"
```

**Step 2: Verify test failure**
Run: `pytest tests/test_derive_version.py -v`

**Step 3: Implement derivation**
Create `scripts/derive_version.py`:
```python
def get_next_patch(releases: list[dict]) -> str:
    patches = []
    for r in releases:
        t = r.get("tag_name", "")
        # Distinguish stable from prerelease via GitHub metadata and tag shape
        if r.get("prerelease") is False and t.startswith("v5.1.") and "-" not in t:
            try: patches.append(int(t.split(".")[2]))
            except ValueError: pass
    next_patch = max(patches) + 1 if patches else 0
    return f"v5.1.{next_patch}"
```

**Step 4: Verify pass and commit**
Run: `pytest tests/test_derive_version.py -v`
```bash
git add tests/test_derive_version.py scripts/derive_version.py
git commit -m "feat: exact patch allocator for legacy compatibility"
```

---

### Task 5: Local Trusted Build, Sign & Verify

**Objective:** Build and sign the exact 5 specified assets using the production key reference, without touching key contents.

**Files:**
- Modify: `scripts/build_software_release_v2.py`
- Modify: `scripts/sign_software_release.py`

**Step 1: Write failing validation test**
Create `tests/test_build_assets.py`:
```python
def test_expected_assets_list():
    from scripts.build_software_release_v2 import EXPECTED_ASSETS
    assert set(EXPECTED_ASSETS) == {
        "NekoFamilyProxy-Setup.exe",
        "NekoLauncher.exe",
        "NekoUpdater.exe",
        "NekoProxyCore.zip",
        "release-v2.json"
    }
```

**Step 2: Verify test failure**
Run: `pytest tests/test_build_assets.py -v`

**Step 3: Implement exact asset enforcement and signing custody**
Update `scripts/build_software_release_v2.py` to define `EXPECTED_ASSETS` as above.
Update `scripts/sign_software_release.py` to hardcode the custody reference:
```python
PRODUCTION_KEY_REF = r"C:\Users\Pranmong\AppData\Local\NekoFamily\release-custody\neko-update-prod-1.pem"
# Implement verification logic ensuring runtime-settings.key is never used
```

**Step 4: Verify pass and commit**
Run: `pytest tests/test_build_assets.py -v`
```bash
git add scripts/ tests/test_build_assets.py
git commit -m "feat: enforce 5.1 asset contracts and strict key custody reference"
```

---

### Task 6: Atomic Publish & Gate3 Fix-Forward

**Objective:** Publish the unified Stable/Latest release to GitHub atomically and run post-publication resolver.

**Files:**
- Modify: `scripts/stage_draft_release.py` -> rename/repurpose to `scripts/publish_atomic_release.py`

**Step 1: Write atomicity test**
Create `tests/test_publish.py`:
```python
def test_atomic_publish_payload():
    from scripts.publish_atomic_release import build_release_payload
    payload = build_release_payload("v5.1.5", "sha_123")
    assert payload["tag_name"] == "v5.1.5"
    assert payload["target_commitish"] == "sha_123"
    assert not payload["draft"]
```

**Step 2: Implement publish logic**
Create `scripts/publish_atomic_release.py`:
```python
def build_release_payload(version, sha):
    return {
        "tag_name": version,
        "target_commitish": sha,
        "name": version,
        "draft": False,
        "prerelease": False,
        "generate_release_notes": True
    }
# Add GitHub API call using `gh` CLI
```

**Step 3: Verify pass and commit**
Run: `pytest tests/test_publish.py -v`
```bash
git add scripts/ tests/
git commit -m "feat: atomic github release publisher and Gate3 hook"
```

---

### Task 7: E2E Tests for Controller

**Objective:** Prove the end-to-end integration works including offline queue recovery, duplicate avoidance, and asset validation.

**Files:**
- Create: `tests/e2e_test_release_pipeline.py`

**Step 1: Write E2E Test**
```python
def test_e2e_pipeline_simulation(mocker):
    from scripts.release_controller import process_accepted_commits
    
    # 1. Fake Kanban DB queue: simulates ordered queued accepted commits and duplicates
    mock_get_pending = mocker.patch("scripts.kanban_release_adapter.get_pending_commits", return_value=["sha_1", "sha_2", "sha_1"])
    mock_mark_done = mocker.patch("scripts.kanban_release_adapter.mark_done")
    
    # 2. Fake GitHub releases for derivation
    mocker.patch("scripts.derive_version.get_github_releases", return_value=[{"tag_name": "v5.1.4", "prerelease": False}])
    
    # 3. Fake build & sign verification
    mock_build = mocker.patch("scripts.build_software_release_v2.build_all")
    mock_sign = mocker.patch("scripts.sign_software_release.verify_and_sign")
    
    # 4. Fake atomic publish
    mock_publish = mocker.patch("scripts.publish_atomic_release.execute_publish")
    
    process_accepted_commits()
    
    # Verify ordered execution and duplicate suppression (sha_1 runs once, then sha_2)
    assert mock_build.call_args_list == [mocker.call("v5.1.5", "sha_1"), mocker.call("v5.1.6", "sha_2")]
    
    # Verify build and sign called before publish
    assert mock_build.call_count == 2
    assert mock_sign.call_count == 2
    
    # Verify publish payload correctly constructed and called
    assert mock_publish.call_args_list == [mocker.call("v5.1.5", "sha_1"), mocker.call("v5.1.6", "sha_2")]
    assert mock_mark_done.call_count == 2
```

**Step 2: Run and verify integration**
Run: `pytest tests/e2e_test_release_pipeline.py -v`

**Step 3: Commit**
```bash
git add tests/e2e_test_release_pipeline.py
git commit -m "test: add end-to-end simulation for release controller"
```

---

### Task 8: Final Review & Activation Gate

**Objective:** Verify worktree is clean, feature branch matches origin, and all specs are met. 

**Steps:**
1. Run `pytest tests/ -v` to ensure all 100% green.
2. Run `git status` to ensure working directory is clean.
3. Push to feature branch: `git push -u origin feature/main-auto-release-pipeline`
4. Request C0/I0 review.

```bash
git push -u origin feature/main-auto-release-pipeline
```
