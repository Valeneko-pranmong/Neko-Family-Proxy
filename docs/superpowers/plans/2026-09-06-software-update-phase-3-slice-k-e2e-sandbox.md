# Software Update Phase 3 — Slice K Implementation Plan: Sandbox End-to-End Update & Rollback Proofs

> **NOTICE: IMPLEMENTATION PAUSED / SUPERSEDED**
>
> Remaining unimplemented Slice-K work is paused and superseded pending a new Balanced Security implementation plan (refer to `docs/superpowers/specs/2026-09-06-software-update-phase-3-balanced-security-amendment.md`).
> Completed units (Unit1, Unit2) remain accepted and retained.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute and verify the complete end-to-end sandbox update and rollback matrix, proving both positive live updates (Launcher-only, Core-only, and both) and automatic rollback on activation failure (broken N+2 candidate), resulting in deterministic `NEW FULLY COMMITTED` or `OLD FULLY RESTORED` states.

**Architecture:** A local sandbox environment creates an authentic per-user installation root under `E:\Github\artifacts\phase3\sandbox-e2e`. Ephemeral in-memory Ed25519 signing keys sign realistic sequence N, N+1, and N+2 releases. The test runs real process executions of `NekoUpdater.exe` and `NekoLauncher.exe`, verifying the entire lifecycle: discovery -> download -> verification -> handoff -> replacement -> restart -> probation -> self-test -> commit -> new identity. In a second suite, an intentionally broken candidate (fails probation self-test) is applied, proving automatic rollback to the intact prior generation.

**Tech Stack:** Python 3.11, pytest 8.3.5, real subprocess execution, Win32 process APIs.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§11, 13, 17.1, 17.2).

---

## Global Constraints

- No mock shortcuts for the final E2E proof: real executables must be spawned and supervised by the real helper.
- Sandbox runs strictly within `E:\Github\artifacts\phase3\sandbox-e2e`.
- Verification requires two concrete proofs:
  1. Success proof: Sequence N -> Sequence N+1 commits cleanly and runs new version.
  2. Rollback proof: Sequence N+1 -> broken Sequence N+2 fails probation and automatically restores running Sequence N+1.
- Both proofs must be backed by real captured JSON output and process exit codes.

---

### Task 1: End-to-End Success Matrix (Launcher-only, Core-only, Both)

**Files:**
- Create: `launcher/tests/e2e/test_live_update_success_e2e.py`

**Interfaces:**
- Exercises full update flow:
  1. Initial manual bootstrap (sequence 1)
  2. Sign sequence 2 (Launcher-only change) -> update -> verify new Launcher version running
  3. Sign sequence 3 (Core-only change) -> update -> verify new Core manifest running
  4. Sign sequence 4 (both changed) -> update -> verify both updated

- [ ] **Step 1: Write E2E success test suite**

```python
# launcher/tests/e2e/test_live_update_success_e2e.py
import pytest
...
```

- [ ] **Step 2: Run pytest to verify all success scenarios pass**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -s tests/e2e/test_live_update_success_e2e.py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add launcher/tests/e2e/test_live_update_success_e2e.py
git commit -m "test(e2e): add end-to-end live update success test suite"
```

---

### Task 2: End-to-End Automatic Rollback Proof (Broken N+2 Candidate)

**Files:**
- Create: `launcher/tests/e2e/test_live_update_rollback_e2e.py`

**Interfaces:**
- Exercises broken candidate update:
  1. Start with verified, healthy sequence N+1.
  2. Prepare validly signed sequence N+2 where Core or Launcher has an intentional probation failure.
  3. Trigger update handoff.
  4. Verify helper detects probation failure, drains candidate, triggers rollback, and restores sequence N+1.
  5. Verify sequence N+1 is running and healthy.
  6. Verify sequence N+2 is recorded as `failed` and not retried.

- [ ] **Step 1: Write E2E rollback test suite**

```python
# launcher/tests/e2e/test_live_update_rollback_e2e.py
import pytest
...
```

- [ ] **Step 2: Run pytest to verify automatic rollback passes**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -s tests/e2e/test_live_update_rollback_e2e.py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add launcher/tests/e2e/test_live_update_rollback_e2e.py
git commit -m "test(e2e): add end-to-end live update automatic rollback test suite"
```
