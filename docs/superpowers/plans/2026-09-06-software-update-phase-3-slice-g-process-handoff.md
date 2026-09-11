# Software Update Phase 3 — Slice G Implementation Plan: Process Protocol & Onefile Handoff

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the duplex framed JSON IPC protocol over standard stream anonymous pipes, Win32 Job Object management with kill-on-close semantics, PyInstaller 6.21.0 stream handle inheritance, and early bootstrap dispatch in `main.py` before `app_factory` imports.

**Architecture:** Communication between `NekoUpdater` (broker) and `NekoLauncher` (managed or probation child) uses two anonymous pipes passed in `STARTUPINFO.hStdInput` and `hStdOutput`, with the inheritable `family.lease` handle passed in `hStdError`. `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` explicitly limits handle inheritance to these three handles. Frames consist of a 4-byte little-endian length prefix followed by strict UTF-8 JSON up to 131,072 bytes. The child receives and responds using `GetStdHandle`. In `main.py`, an early dispatch function checks whether `--update-managed` or `--update-probation` was passed; if present, it connects to the broker IPC before any UI or dependency imports.

**Tech Stack:** Python 3.11, ctypes Win32 API (`CreatePipe`, `CreateJobObjectW`, `AssignProcessToJobObject`, `CreateProcessW`, `UpdateProcThreadAttribute`), pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§7, 10, 10.1, 10.2).

---

## Global Constraints

- Communication channel: anonymous pipes assigned to standard input and output.
- Standard error handle holds the read-only `family.lease` file handle.
- Maximum frame size: 131,072 bytes. Deadline: 5.0 seconds per read.
- Common frame keys: `{protocol_version: 1, type: str, message_id: str, body: dict}`.
- Job Object: created with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
- Early hook in `main.py`: must execute before importing `app_factory` or initializing CustomTkinter/Tkinter.

---

### Task 1: Framed JSON IPC Channel over Anonymous Pipes

**Files:**
- Create: `launcher/src/neko_launcher/updater/ipc_channel.py`
- Create: `launcher/tests/updater/test_ipc_channel.py`

**Interfaces:**
- Produces: `FramedIpcChannel(read_handle: int, write_handle: int)`
- Methods:
  - `send_message(msg_type: str, body: dict, message_id: str | None = None) -> str` (returns message_id)
  - `receive_message(timeout_s: float = 5.0) -> IpcMessage`
- Raises `IpcTimeoutError`, `IpcProtocolError`, `IpcFrameTooLargeError`.

- [ ] **Step 1: Write RED tests for framed IPC message exchange**

```python
# launcher/tests/updater/test_ipc_channel.py
import pytest
import os
from neko_launcher.updater.ipc_channel import FramedIpcChannel

def test_send_and_receive_frame():
    r1, w1 = os.pipe()
    r2, w2 = os.pipe()
    ch1 = FramedIpcChannel(read_handle=r1, write_handle=w2)
    ch2 = FramedIpcChannel(read_handle=r2, write_handle=w1)

    msg_id = ch1.send_message("HELLO", {"mode": "managed", "pid": 1234})
    received = ch2.receive_message(timeout_s=1.0)
    assert received.type == "HELLO"
    assert received.message_id == msg_id
    assert received.body["pid"] == 1234
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_ipc_channel.py`
Expected: FAIL.

- [ ] **Step 3: Implement FramedIpcChannel**

Implement in `launcher/src/neko_launcher/updater/ipc_channel.py`:
- 4-byte `uint32_le` length prefix.
- Enforce length <= 131,072 bytes.
- Encode/decode canonical UTF-8 JSON.
- Handle non-blocking or timed read via `ReadFile` / `PeekNamedPipe`.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_ipc_channel.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/ipc_channel.py tests/updater/test_ipc_channel.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/ipc_channel.py launcher/tests/updater/test_ipc_channel.py
git commit -m "feat(updater): implement duplex framed json ipc over anonymous pipes"
```

---

### Task 2: Win32 Job Object & Suspended Process Spawner

**Files:**
- Create: `launcher/src/neko_launcher/updater/process_spawner.py`
- Create: `launcher/tests/updater/test_process_spawner.py`

**Interfaces:**
- Produces: `spawn_managed_child(executable_path: Path, args: list[str], lease_handle: int) -> ManagedChildProcess`
- Uses `CreateProcessW` with `CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT`.
- Binds child to Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
- Restricts handle inheritance to stdin, stdout, and stderr (lease) via `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`.

- [ ] **Step 1: Write RED tests for job assignment and process termination on job close**

```python
# launcher/tests/updater/test_process_spawner.py
import pytest
from pathlib import Path
from neko_launcher.updater.process_spawner import spawn_managed_child

def test_spawn_managed_child_kills_child_on_job_close(tmp_path: Path):
    ...
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_process_spawner.py`
Expected: FAIL.

- [ ] **Step 3: Implement process spawner**

Implement in `launcher/src/neko_launcher/updater/process_spawner.py`:
- Use `InitializeProcThreadAttributeList` and `UpdateProcThreadAttribute`.
- Assign process to Job Object before calling `ResumeThread`.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_process_spawner.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/process_spawner.py tests/updater/test_process_spawner.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/process_spawner.py launcher/tests/updater/test_process_spawner.py
git commit -m "feat(updater): implement win32 job-object bound process spawner"
```

---

### Task 3: Early Bootstrap Hook in Launcher `main.py`

**Files:**
- Modify: `launcher/src/neko_launcher/main.py`
- Create: `launcher/src/neko_launcher/updater/early_dispatch.py`
- Test: `launcher/tests/updater/test_early_dispatch.py`

**Interfaces:**
- `maybe_dispatch_updater_entry(argv: list[str]) -> bool`
- Intercepts `--update-managed` and `--update-probation` before `app_factory` or UI imports.
- Connects to stdin/stdout pipes, validates broker handshake, performs local check or enters managed loop.

- [ ] **Step 1: Write RED tests for early dispatch hook**

```python
# launcher/tests/updater/test_early_dispatch.py
import pytest
from neko_launcher.updater.early_dispatch import maybe_dispatch_updater_entry

def test_early_dispatch_returns_false_for_normal_launch():
    assert not maybe_dispatch_updater_entry(["NekoLauncher.exe"])

def test_early_dispatch_intercepts_update_probation(monkeypatch):
    ...
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_early_dispatch.py`
Expected: FAIL.

- [ ] **Step 3: Implement early dispatch hook**

Implement `early_dispatch.py` and modify `main.py` at the very top of execution:
```python
# In neko_launcher/main.py
if __name__ == "__main__":
    from neko_launcher.updater.early_dispatch import maybe_dispatch_updater_entry
    if maybe_dispatch_updater_entry(sys.argv):
        sys.exit(0)
    # Continue with regular main...
```

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_early_dispatch.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/main.py src/neko_launcher/updater/early_dispatch.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/main.py launcher/src/neko_launcher/updater/early_dispatch.py launcher/tests/updater/test_early_dispatch.py
git commit -m "feat(launcher): add early updater bootstrap dispatch hook before app_factory"
```
