# Software Update Phase 3 — Slice E Implementation Plan: Backup & Rollback

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement safe, non-destructive backup retention and deterministic rollback mechanisms that preserve replay floors (`highwater` and `observed`), retain prior committed rollback descriptors on precommit candidate failures, and safely execute postcommit rollback via restricted probation.

**Architecture:** Each release generation is kept intact on disk under `releases/<generation-id>`. On precommit candidate abort/failure, the running healthy old family is preserved, `failed=observed` is recorded, and `previous` remains intact so that a subsequent failure of the current version can still revert to the older known-good backup. On postcommit failure (e.g. candidate fails local self-test or cannot start), the broker drains the failed family, validates the previous generation, runs restricted probation on it, and only after probation passes flushes `committed=previous`, `previous=null`, and transfers scratch roots to `CLEANING` before issuing `NORMAL_AUTH`.

**Tech Stack:** Python 3.11, dataclasses, pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§1, 8, 8.1, 9, 11, 13, 14).

---

## Global Constraints

- Never delete or truncate prior committed generations (`releases/<generation-id>`) during updates or rollback.
- Monotonic floors `highwater.sequence` and `observed.sequence` must NEVER decrease, even after a rollback.
- Precommit failure MUST keep `previous` untouched. (Scenario: N was previous, N+1 is committed. N+2 candidate fails precommit -> `previous` MUST remain N).
- Postcommit rollback clears `previous` (`previous=null`) to avoid circular rollbacks.
- Scratch directories (`incoming/<request-id>` and `staging/<transaction-id>`) are transferred atomically to the `cleanup` queue in the selecting slot snapshot.

---

### Task 1: Precommit Abort & Active Family Preservation

**Files:**
- Create: `launcher/src/neko_launcher/updater/precommit_abort.py`
- Create: `launcher/tests/updater/test_precommit_abort.py`

**Interfaces:**
- Produces: `execute_precommit_abort(broker_ctx, reason_code: str) -> State`
- Enforces:
  - If current state is `PREPARING` (before `STOP_OLD`), do NOT stop or drain the running process family.
  - Set `failed = observed`.
  - Atomically move `incoming` and `staging` directory identities to `cleanup` queue.
  - Clear `transaction`.
  - Leave `committed`, `previous`, `highwater`, and `observed` intact.

- [ ] **Step 1: Write RED tests verifying precommit abort invariants**

```python
# launcher/tests/updater/test_precommit_abort.py
import pytest
from neko_launcher.updater.precommit_abort import execute_precommit_abort
from neko_launcher.updater.state_models import State, Generation, Binding, DirectoryIdentity

def test_precommit_abort_preserves_previous_and_active_session(broker_context):
    # Setup state: committed=N+1, previous=N, preparing N+2
    state = broker_context.current_state
    orig_committed = state.committed
    orig_previous = state.previous
    orig_highwater = state.highwater
    orig_observed = state.observed

    new_state = execute_precommit_abort(broker_context, "DOWNLOAD_FAILED")
    assert new_state.committed == orig_committed
    assert new_state.previous == orig_previous  # Must NOT be cleared!
    assert new_state.highwater == orig_highwater
    assert new_state.observed == orig_observed
    assert new_state.failed == orig_observed
    assert new_state.transaction is None
    assert new_state.cleanup is not None
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_precommit_abort.py`
Expected: FAIL.

- [ ] **Step 3: Implement precommit abort controller**

Implement in `launcher/src/neko_launcher/updater/precommit_abort.py`:
- Check phase is `PREPARING`.
- Formulate next State following `PREPARING -> CLEANING/IDLE (pre-quiesce abort)` row.
- Flush and reread slot before acknowledging abort to child.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_precommit_abort.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/precommit_abort.py tests/updater/test_precommit_abort.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/precommit_abort.py launcher/tests/updater/test_precommit_abort.py
git commit -m "feat(updater): implement precommit abort preserving previous rollback descriptor"
```

---

### Task 2: Postcommit Rollback Controller with Restricted Probation

**Files:**
- Create: `launcher/src/neko_launcher/updater/rollback_controller.py`
- Create: `launcher/tests/updater/test_rollback_controller.py`

**Interfaces:**
- Produces: `execute_postcommit_rollback(broker_ctx, error_code: str) -> State`
- Orchestrates:
  1. `DRAIN_INTENT`: terminate failed candidate job.
  2. `RESTORE_INTENT`: spawn target `previous` generation in restricted probation (`--update-probation`).
  3. `RESTORE_DONE`: verify local check / Core preflight passed.
  4. Commit rollback selection: `committed = previous`, `previous = None`, `phase = "CLEANING"`, queues scratch roots, preserves `highwater` and `observed`.
  5. Issue `NORMAL_AUTH` for restored target.

- [ ] **Step 1: Write RED tests for postcommit rollback execution**

```python
# launcher/tests/updater/test_rollback_controller.py
import pytest
from neko_launcher.updater.rollback_controller import execute_postcommit_rollback

def test_postcommit_rollback_restores_previous_and_preserves_floors(broker_context):
    # Setup candidate committed at sequence 2, previous sequence 1
    ...
    rolled_back_state = execute_postcommit_rollback(broker_context, "SELFTEST_FAILED")
    assert rolled_back_state.committed.binding.release_sequence == 1
    assert rolled_back_state.previous is None
    assert rolled_back_state.highwater.release_sequence == 2  # Highwater preserved!
    assert rolled_back_state.observed.release_sequence == 2   # Observed preserved!
    assert rolled_back_state.failed.release_sequence == 2
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_rollback_controller.py`
Expected: FAIL.

- [ ] **Step 3: Implement RollbackController**

Implement in `launcher/src/neko_launcher/updater/rollback_controller.py`:
- Enforce that rollback target is valid on disk.
- Step through the `ROLLING_BACK` state machine.
- Verify `NORMAL_AUTH` is dispatched only after the selecting snapshot is durable.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_rollback_controller.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/rollback_controller.py tests/updater/test_rollback_controller.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/rollback_controller.py launcher/tests/updater/test_rollback_controller.py
git commit -m "feat(updater): implement postcommit rollback with restricted probation"
```
