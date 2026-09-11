# Software Update Phase 3 — Slice H Implementation Plan: Restart, Self-Test & Auth Handshake

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the candidate probation runner, mandatory credential-free Core loader preflight, Tkinter event-loop responsiveness probe, `NORMAL_AUTH` / `NORMAL_ACK` handshake, and the ordinary cold-start authorization sequence.

**Architecture:** During probation, `NekoLauncher` starts with `--update-probation`. It verifies own executable integrity, validates embedded assets and importability, verifies the complete canonical Core bundle on disk, executes the Core binary with `--update-preflight` to test native DLL dependencies, and pumps the Tkinter event loop for at least two frames without network, Proxy credentials, or launch permits. On success, it sends `SELF_TEST` with `result: "PASS"`. The broker flushes the selecting durable slot snapshot, replies with `NORMAL_AUTH`, and only after receiving `NORMAL_ACK` allows the candidate to transition into regular normal execution.

**Tech Stack:** Python 3.11, Tkinter (`tkinter.Tk`), subprocess/ctypes, pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§10, 10.2, 11, 12).

---

## Global Constraints

- Probation must be strictly credential-free: NO Supabase JWT, NO Proxy password, NO launch permit request, NO active proxy session.
- Mandatory Core preflight: must execute for every update, including Launcher-only and metadata-only releases. Core preflight timeout: 30.0s.
- Tkinter probe: instantiate headless/hidden Tkinter window, schedule and process at least two `after()` callbacks, then destroy.
- Timeouts: `HELLO` 10s, whole probation 60s, `NORMAL_ACK` 10s.

---

### Task 1: Candidate Probation & Self-Test Runner

**Files:**
- Create: `launcher/src/neko_launcher/updater/probation_runner.py`
- Create: `launcher/tests/updater/test_probation_runner.py`

**Interfaces:**
- Produces: `run_probation_self_test(generation_dir: Path, core_preflight_timeout: float = 30.0) -> SelfTestResult`
- Verifies:
  1. Own executable hash and version match expected generation descriptor.
  2. Canonical Core manifest exists and all mapped files exist and match hashes.
  3. Spawns `ProxyCore/NekoProxyCore.exe --update-preflight`, writes JSON handshake, reads JSON response, asserts `PASS` and exit code 0.
  4. Tkinter event loop pumps 2 iterations cleanly.

- [ ] **Step 1: Write RED tests for self-test sequence & failure detection**

```python
# launcher/tests/updater/test_probation_runner.py
import pytest
from pathlib import Path
from neko_launcher.updater.probation_runner import run_probation_self_test

def test_probation_passes_on_valid_bundle(valid_generation_dir):
    res = run_probation_self_test(valid_generation_dir)
    assert res.passed
    assert res.error_code is None

def test_probation_fails_if_core_preflight_fails(corrupted_core_generation_dir):
    res = run_probation_self_test(corrupted_core_generation_dir)
    assert not res.passed
    assert res.error_code == "SELFTEST_FAILED"
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_probation_runner.py`
Expected: FAIL.

- [ ] **Step 3: Implement probation self-test runner**

Implement in `launcher/src/neko_launcher/updater/probation_runner.py`:
- Use `core_manifest_verifier.py`.
- Call Core preflight executable with `subprocess.Popen`, write stdin JSON, read stdout JSON.
- Run mini Tkinter loop with `root.withdraw()`, schedule callbacks with `root.after(10, ...)`, call `root.update()`.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_probation_runner.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/probation_runner.py tests/updater/test_probation_runner.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/probation_runner.py launcher/tests/updater/test_probation_runner.py
git commit -m "feat(updater): implement candidate credential-free probation and self-test runner"
```

---

### Task 2: Broker-Child Authorization Handshake & Cold-Start Protocol

**Files:**
- Create: `launcher/src/neko_launcher/updater/auth_handshake.py`
- Create: `launcher/tests/updater/test_auth_handshake.py`

**Interfaces:**
- Produces: `execute_broker_auth_handshake(ipc: FramedIpcChannel, state: State, mode: str) -> None`
- Implements the cold-start protocol:
  `HELLO` -> `CONTEXT` -> `LOCAL_CHECK` -> `NORMAL_AUTH` -> `NORMAL_ACK`.
- Implements update probation:
  `HELLO` -> `CONTEXT` -> `SELF_TEST` -> commit slot flush -> `NORMAL_AUTH` -> `NORMAL_ACK`.

- [ ] **Step 1: Write RED tests for full auth handshake sequences**

```python
# launcher/tests/updater/test_auth_handshake.py
import pytest
from neko_launcher.updater.auth_handshake import execute_broker_auth_handshake

def test_cold_start_handshake_succeeds(mock_ipc_pair, idle_state):
    broker_ipc, child_ipc = mock_ipc_pair
    # Run handshake on both sides
    ...
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_auth_handshake.py`
Expected: FAIL.

- [ ] **Step 3: Implement auth handshake logic**

Implement in `launcher/src/neko_launcher/updater/auth_handshake.py`:
- Strict state verification and message ordering.
- Re-validate durable state before issuing `NORMAL_AUTH`.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_auth_handshake.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/auth_handshake.py tests/updater/test_auth_handshake.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/auth_handshake.py launcher/tests/updater/test_auth_handshake.py
git commit -m "feat(updater): implement broker-child authorization handshake and cold-start protocol"
```
