# Main Automatic Release Pipeline Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Establish a fully automated, `main`-branch-driven patch release pipeline operating with zero per-release owner clicks, ensuring legacy 5.1 compatibility and enforcing local signing custody.

**Architecture:** Phase 1: Source Acceptance (CI) -> Phase 2: Local Queue & Version Allocation (Controller) -> Phase 3: Build, Sign & Atomic Publish.

**Tech Stack:** Git, GitHub Actions, Python 3.11+, Pytest, Hermes Kanban DB.

---

## Execution Constraints & Parallelism

- **Phase 1 (Single-flight):** Task 1 (Migration) MUST run first sequentially.
- **Phase 2 (Parallelizable):** Tasks 2, 3, 4, and 5 CAN run in parallel as they implement orthogonal modules.
- **Phase 3 (Single-flight):** Tasks 6, 7, and 8 MUST run sequentially.

---

### Task 1: Safe `release/5.1` -> `main` Parity Migration

**Objective:** Reconcile production release tooling from `release/5.1` into the `main` feature branch without rewriting history or stranding infrastructure.

**Files:**
- Modify: `scripts/`, `installer/`, `agent/`

**Step 1: Verify current tree state**
Run: `git status`
Expected: On branch `feature/main-auto-release-pipeline`.

**Step 2: Extract and merge 5.1 tooling**
```bash
git checkout origin/release/5.1 -- scripts/ installer/ agent/
```

**Step 3: Commit the migration**
```bash
git add scripts/ installer/ agent/
git commit -m "chore: migrate release/5.1 production tooling to main parity"
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

### Task 3: Local Release Queue & Controller Adapter

**Objective:** Create a persistent Hermes controller adapter tracking accepted commits in the Kanban primitives for offline recovery and single-allocator concurrency.

**Files:**
- Create: `agent/neko_release_queue.py`
- Create: `tests/test_release_queue.py`

**Step 1: Write failing test**
Create `tests/test_release_queue.py`:
```python
def test_queue_commit():
    from agent.neko_release_queue import queue_commit, get_pending_commits
    queue_commit("sha_abc123")
    assert "sha_abc123" in get_pending_commits()
```

**Step 2: Run test to verify failure**
Run: `pytest tests/test_release_queue.py -v`
Expected: FAIL

**Step 3: Implement Queue Logic**
Create `agent/neko_release_queue.py`:
```python
import os, json
QUEUE_FILE = ".hermes/release_queue.json"

def _load():
    if not os.path.exists(QUEUE_FILE): return []
    with open(QUEUE_FILE) as f: return json.load(f)

def _save(q):
    os.makedirs(".hermes", exist_ok=True)
    with open(QUEUE_FILE, "w") as f: json.dump(q, f)

def queue_commit(sha: str):
    q = _load()
    if sha not in q:
        q.append(sha)
        _save(q)

def get_pending_commits():
    return _load()
```

**Step 4: Verify pass and commit**
Run: `pytest tests/test_release_queue.py -v`
Expected: PASS
```bash
git add tests/test_release_queue.py agent/neko_release_queue.py
git commit -m "feat: implement local offline-recoverable release queue"
```

---

### Task 4: Exact Patch/Version Derivation

**Objective:** Allocate the exact next monotonic patch version at execution time based on repository state, ensuring legacy v5.1.x compatibility.

**Files:**
- Create: `scripts/derive_version.py`
- Create: `tests/test_derive_version.py`

**Step 1: Write failing test**
Create `tests/test_derive_version.py`:
```python
def test_derive_patch():
    from scripts.derive_version import get_next_patch
    # Mocking current highest release is v5.1.4
    assert get_next_patch(["v5.1.3", "v5.1.4"]) == "v5.1.5"
```

**Step 2: Verify test failure**
Run: `pytest tests/test_derive_version.py -v`

**Step 3: Implement derivation**
Create `scripts/derive_version.py`:
```python
def get_next_patch(existing_tags: list[str]) -> str:
    # Filter for 5.1.x
    patches = []
    for t in existing_tags:
        if t.startswith("v5.1."):
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
def test_e2e_pipeline_simulation():
    # Push fake commit to queue
    # Run process_accepted_commits()
    # Assert version derived, assets mocked built, publish mocked called
    assert True # Replace with actual integration test using pytest-mock
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
