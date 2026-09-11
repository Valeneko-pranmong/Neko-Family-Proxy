# Software Update Phase 3 — Slice I Implementation Plan: UI & Application Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the live update workflow into the Launcher application, binding signed release payload v2 schema, enforcing idle-safe application policy (never interrupt active game/Proxy sessions), and providing UI progress, notification banners, and restart prompts.

**Architecture:** `UpdateCheckService` is extended to support Phase 3 signed manifests (ReleaseV2 with component format, helper protocol, and installed identity). The application update policy verifies that update staging occurs in the background, but update *application* (quiescence and restart) is deferred until the proxy session is completely stopped and no game is connected. The UI displays download progress, notifies the user when an update is staged, and prompts for restart.

**Tech Stack:** Python 3.11, CustomTkinter, `neko_launcher.application.software_update_policy`, pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§5, 9, 10, 11, 15).

---

## Global Constraints

- Never disrupt an active gaming or proxy session: If proxy state is `ACTIVE` or `CONNECTING`, update application is blocked.
- Schema version 2 is required for Phase 3 updates; schema version 1 is treated as legacy check-only.
- UI must reflect states: `IDLE`, `CHECKING`, `DOWNLOADING`, `STAGED_READY_TO_RESTART`, `APPLYING`, `UPDATE_FAILED`.

---

### Task 1: Update Application Policy for Schema v2 & Session Safety

**Files:**
- Modify: `launcher/src/neko_launcher/application/software_update_policy.py`
- Modify: `launcher/src/neko_launcher/application/software_update_models.py`
- Test: `launcher/tests/test_software_update_policy.py`

**Interfaces:**
- Updates `SoftwareUpdatePolicy.evaluate(...)`
- Validates that `schema_version == 2` and `updater_protocol.minimum <= 1 <= updater_protocol.maximum`.
- Checks proxy state before approving `APPLY`.

- [ ] **Step 1: Write RED tests for schema v2 validation and idle session enforcement**

```python
# launcher/tests/test_software_update_policy.py
import pytest
from neko_launcher.application.software_update_policy import SoftwareUpdatePolicy

def test_policy_blocks_apply_when_proxy_session_active(policy, sample_release_v2):
    res = policy.evaluate(sample_release_v2, is_proxy_active=True)
    assert res.can_download is True
    assert res.can_apply is False
    assert res.reason == "SESSION_BUSY"
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/test_software_update_policy.py`
Expected: FAIL.

- [ ] **Step 3: Implement policy changes**

Implement in `launcher/src/neko_launcher/application/software_update_policy.py`:
- Check protocol compatibility.
- Check proxy activity flag.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/test_software_update_policy.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/application/software_update_policy.py tests/test_software_update_policy.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/application/software_update_policy.py launcher/src/neko_launcher/application/software_update_models.py launcher/tests/test_software_update_policy.py
git commit -m "feat(update): update policy to support schema v2 and idle proxy session enforcement"
```

---

### Task 2: UI Status & Restart Notification Banner

**Files:**
- Modify: `launcher/src/neko_launcher/ui/main_window.py` (or update banner component)
- Test: `launcher/tests/ui/test_update_ui.py`

**Interfaces:**
- Renders non-intrusive update banner when update is `STAGED_READY_TO_RESTART`.
- Provides "Restart to Update" button that safely triggers quiesce and exits Launcher to let helper execute transaction.

- [ ] **Step 1: Write RED tests for update banner display**

```python
# launcher/tests/ui/test_update_ui.py
import pytest
...
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/ui/test_update_ui.py`
Expected: FAIL.

- [ ] **Step 3: Implement UI banner and restart trigger**

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/ui/test_update_ui.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/ui/main_window.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/ui/ launcher/tests/ui/test_update_ui.py
git commit -m "feat(ui): add update status indicator and restart prompt banner"
```
