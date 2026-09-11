# Software Update Phase 3 — Slice F Implementation Plan: Interruption Recovery & Fault Matrix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the deterministic recovery engine and fault-injection matrix covering interruption or power loss after every filesystem mutation and durable slot transition as specified in Section 13 of the approved Phase-3 specification.

**Architecture:** Recovery is initiated whenever `NekoUpdater.exe` starts. The engine acquires the root lock, verifies process family quiescence, reads and selects the authoritative slot state, and determines the recovery action from the state and on-disk invariants. If interrupted during `PREPARING`, it executes pre-quiesce abort; if interrupted during `QUIESCING` or `PROBATION`, it rolls back to `committed` (or `previous`); if a newly committed generation is missing on disk, it journals rollback to `previous` while preserving `highwater`; if in `CLEANING`, it validates directory identities and resumes postorder deletion. Running recovery twice must be completely idempotent.

**Tech Stack:** Python 3.11, ctypes Win32 API, pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§8, 8.1, 10, 11, 13, 14, 17.5).

---

## Global Constraints

- Recovery must be strictly idempotent: First run converges state; second run does not mutate authority, replay floors, or selected generation.
- Never guess state from filesystem timestamps (`mtime`) or directory presence.
- Never recursively delete an unowned or identity-mismatched directory (use `INTENT -> SKIPPED` and leave inert).
- Torn slot writes: use the valid alternate slot; if both slots torn or evidence corrupt -> `REPAIR_REQUIRED`.

---

### Task 1: Comprehensive Recovery Dispatcher

**Files:**
- Create: `launcher/src/neko_launcher/updater/recovery_engine.py`
- Create: `launcher/tests/updater/test_recovery_engine.py`

**Interfaces:**
- Produces: `RecoveryEngine(root_dir: Path, lock_mgr: RootLockManager, public_keys: Mapping[str, bytes])`
- Method: `run_recovery() -> RecoveryResult`
- Handles all 15 scenarios from the Section 13 recovery table.

- [ ] **Step 1: Write RED tests for all recovery table rows**

```python
# launcher/tests/updater/test_recovery_engine.py
import pytest
from neko_launcher.updater.recovery_engine import RecoveryEngine

def test_recovery_from_interrupted_building_rolls_back_to_committed(simulated_env):
    # Setup state in PREPARING / BUILDING with partial stage dir
    ...
    engine = RecoveryEngine(simulated_env.root, simulated_env.lock_mgr, simulated_env.keys)
    res1 = engine.run_recovery()
    assert res1.converged
    assert res1.selected_generation == simulated_env.orig_committed

    # Idempotence: run recovery second time
    res2 = engine.run_recovery()
    assert res2.converged
    assert res2.mutations_performed == 0

def test_recovery_from_missing_committed_generation_rolls_back_to_previous(simulated_env):
    # State has committed=N+1, but folder releases/g-N+1 was deleted/lost!
    ...
    engine = RecoveryEngine(simulated_env.root, simulated_env.lock_mgr, simulated_env.keys)
    res = engine.run_recovery()
    assert res.selected_generation == simulated_env.previous_gen
    assert res.highwater_preserved
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_recovery_engine.py`
Expected: FAIL.

- [ ] **Step 3: Implement RecoveryEngine**

Implement in `launcher/src/neko_launcher/updater/recovery_engine.py`:
- Inspect selected snapshot phase.
- Route to appropriate recovery handler:
  - `ENROLLING`: report incomplete enrollment.
  - `PREPARING`: abort candidate, record `failed=observed`, queue scratch roots.
  - `QUIESCING` / `PROBATION`: post-quiesce rollback to `committed`.
  - `ROLLING_BACK`: complete pending rollback sequence.
  - `CLEANING`: execute handle-relative deletion of queued scratch roots.
  - `IDLE`: verify committed generation completeness; if corrupt/missing and `previous` exists, trigger postcommit rollback.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_recovery_engine.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/recovery_engine.py tests/updater/test_recovery_engine.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/recovery_engine.py launcher/tests/updater/test_recovery_engine.py
git commit -m "feat(updater): implement crash-recovery engine and recovery dispatcher"
```

---

### Task 2: Fault-Injection Interruption Matrix Test Suite

**Files:**
- Create: `launcher/tests/updater/test_interruption_matrix.py`

**Interfaces:**
- Exercises simulated power loss / process kill after every single durable slot write and filesystem mutation:
  1. Partial slot write (torn write)
  2. Crash after `incoming` creation before identity recorded
  3. Crash after `incoming` identity recorded before download
  4. Crash during download
  5. Crash after `staging` created before files written
  6. Crash during candidate file write
  7. Crash after candidate files written before directory rename
  8. Crash after directory rename before `VERIFIED` slot write
  9. Crash during `QUIESCING` (stop old family)
  10. Crash during `PROBATION` before self-test
  11. Crash during `PROBATION` after self-test before commit slot flush
  12. Crash after commit slot flush before `NORMAL_AUTH`
  13. Crash after `NORMAL_AUTH` before `NORMAL_ACK`
  14. Crash during scratch root cleanup (incoming / staging)
  15. Crash during postcommit rollback drain and restore

- [ ] **Step 1: Write tests exercising every fault injection point**

```python
# launcher/tests/updater/test_interruption_matrix.py
import pytest
from neko_launcher.updater.recovery_engine import RecoveryEngine

@pytest.mark.parametrize("interruption_point", [
    "after_create_incoming",
    "after_stage_files",
    "after_publish_rename",
    "after_quiesce_intent",
    "after_probation_pass",
    "after_commit_flush",
    "during_cleanup_first_file",
])
def test_interruption_converges_to_valid_terminal_state(interruption_point, test_harness):
    test_harness.run_until(interruption_point)
    # Simulate abrupt process kill & restart
    engine = RecoveryEngine(test_harness.root, test_harness.lock_mgr, test_harness.keys)
    result = engine.run_recovery()
    assert result.converged
    # State must be strictly OLD_RESTORED or NEW_COMMITTED
    assert result.status in ("OLD_FULLY_RESTORED", "NEW_FULLY_COMMITTED")
```

- [ ] **Step 2: Run pytest to verify all fault cases pass**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_interruption_matrix.py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add launcher/tests/updater/test_interruption_matrix.py
git commit -m "test(updater): add comprehensive every-mutation interruption and recovery test suite"
```
