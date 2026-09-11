# Software Update Phase 3 — Slice C Implementation Plan: Windows Helper, Locks & Handle Safety

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the stable Windows update helper (`NekoUpdater.exe`), per-user KnownFolder root validation, permanent exclusive `state/control.lock` (byte 0), permanent inherited `state/family.lease` share-mode liveness guard, and handle-relative atomic generation publication.

**Architecture:** `NekoUpdater.exe` is a stable, manually enrolled bootstrap binary that runs unelevated (`asInvoker`). It locks the root via `LockFileEx` on `control.lock`, verifies that prior process families have closed their read leases on `family.lease`, and supervises the running Launcher. It stages new releases into `staging/<transaction-id>/generation`, verifies all component hashes on retained handles, and publishes the generation to `releases/<generation-id>` using directory rename before durable slot selection.

**Tech Stack:** Python 3.11 / PyInstaller 6.21.0 (or lightweight native runner), ctypes Win32 API (`LockFileEx`, `CreateFileW`, `MoveFileExW`, `SHGetKnownFolderPath`), pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§1, 3, 4, 7, 8, 10, 13.1, 15).

---

## Global Constraints

- Root location: `FOLDERID_UserProgramFiles\NEKO FAMILY` (`%LOCALAPPDATA%\Programs\NEKO FAMILY`).
- Must reject elevation (`TokenElevation` check) and run as current unelevated user.
- Exclusive `control.lock` byte 0 lock held for helper lifetime; share-delete denied.
- `family.lease` opened with `GENERIC_READ | GENERIC_WRITE`, share mode 0 during recovery drain check; then reopened `GENERIC_READ`, `FILE_SHARE_READ` and inherited to Launcher & Core descendants.
- Atomic directory rename with `MOVEFILE_WRITE_THROUGH` (if supported on directory) or handle-relative same-volume publish. Never overwrite an existing release directory.

---

### Task 1: KnownFolder Root & DACL Security Validation

**Files:**
- Create: `launcher/src/neko_launcher/updater/root_validator.py`
- Create: `launcher/tests/updater/test_root_validator.py`

**Interfaces:**
- Produces: `get_expected_install_root() -> Path`
- Produces: `validate_install_root(path: Path) -> RootValidationResult`
- Verifies path is exactly child of `FOLDERID_UserProgramFiles`, volume is NTFS, owned by current user, no reparse points, and unelevated process token.

- [ ] **Step 1: Write RED tests for root resolution and security checks**

```python
# launcher/tests/updater/test_root_validator.py
import pytest
from pathlib import Path
from neko_launcher.updater.root_validator import validate_install_root, get_expected_install_root

def test_validates_canonical_user_program_files_root():
    root = get_expected_install_root()
    assert "Programs" in str(root)
    assert root.name == "NEKO FAMILY"

def test_rejects_arbitrary_or_symlinked_root(tmp_path: Path):
    res = validate_install_root(tmp_path)
    assert not res.valid
    assert "ROOT_UNSUPPORTED" in res.error_code
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_root_validator.py`
Expected: FAIL.

- [ ] **Step 3: Implement root validator**

Implement in `launcher/src/neko_launcher/updater/root_validator.py`:
- Use `ctypes.windll.shell32.SHGetKnownFolderPath` with `FOLDERID_UserProgramFiles` GUID.
- Check `GetVolumeInformationW` for `NTFS`.
- Check process elevation via `OpenProcessToken` + `GetTokenInformation(TokenElevation)`.
- Reject if token is elevated (`Elevation != 0`).

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_root_validator.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/root_validator.py tests/updater/test_root_validator.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/root_validator.py launcher/tests/updater/test_root_validator.py
git commit -m "feat(updater): implement known folder root and elevation validator"
```

---

### Task 2: Root Control Lock & Process Family Lease Manager

**Files:**
- Create: `launcher/src/neko_launcher/updater/lock_manager.py`
- Create: `launcher/tests/updater/test_lock_manager.py`

**Interfaces:**
- Produces: `RootLockManager(root_dir: Path)`
- Methods:
  - `acquire_control_lock(timeout_s: float = 10.0) -> int` (returns handle, locks byte 0 exclusively)
  - `probe_family_quiescence(timeout_s: float = 30.0) -> bool` (opens `family.lease` share-mode 0 exclusively to prove all prior descendant handles closed)
  - `create_inheritable_family_lease() -> int` (opens `family.lease` with `GENERIC_READ`, `FILE_SHARE_READ`, `bInheritHandle=True`)
  - `release_all()`

- [ ] **Step 1: Write RED tests for lock contention and family lease liveness**

```python
# launcher/tests/updater/test_lock_manager.py
import pytest
from pathlib import Path
from neko_launcher.updater.lock_manager import RootLockManager, LockBusyError

def test_control_lock_denies_second_manager(tmp_path: Path):
    mgr1 = RootLockManager(tmp_path)
    mgr2 = RootLockManager(tmp_path)
    h1 = mgr1.acquire_control_lock(timeout_s=1.0)
    try:
        with pytest.raises(LockBusyError):
            mgr2.acquire_control_lock(timeout_s=0.2)
    finally:
        mgr1.release_all()

def test_family_lease_quiescence_detects_living_descendant(tmp_path: Path):
    mgr = RootLockManager(tmp_path)
    mgr.acquire_control_lock()
    lease_handle = mgr.create_inheritable_family_lease()
    try:
        # While lease_handle is open, probe must fail/timeout
        assert not mgr.probe_family_quiescence(timeout_s=0.2)
    finally:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(lease_handle)
        # Now probe must succeed immediately
        assert mgr.probe_family_quiescence(timeout_s=1.0)
        mgr.release_all()
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_lock_manager.py`
Expected: FAIL.

- [ ] **Step 3: Implement RootLockManager**

Implement in `launcher/src/neko_launcher/updater/lock_manager.py`:
- `CreateFileW` for `control.lock` with `GENERIC_READ | GENERIC_WRITE`, share-delete denied.
- `LockFileEx` with `LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY` for byte offset 0, length 1.
- `probe_family_quiescence`: retry loop attempting `CreateFileW` on `family.lease` with `dwShareMode = 0`. If `ERROR_SHARING_VIOLATION`, sleep and retry until timeout.
- `create_inheritable_family_lease`: open `family.lease` with `GENERIC_READ`, `FILE_SHARE_READ`, and `bInheritHandle = TRUE` in `SECURITY_ATTRIBUTES`.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_lock_manager.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/lock_manager.py tests/updater/test_lock_manager.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/lock_manager.py launcher/tests/updater/test_lock_manager.py
git commit -m "feat(updater): implement control lock and family lease manager"
```

---

### Task 3: Generation Staging & Atomic Publish

**Files:**
- Create: `launcher/src/neko_launcher/updater/generation_publisher.py`
- Create: `launcher/tests/updater/test_generation_publisher.py`

**Interfaces:**
- Produces: `GenerationPublisher(root_dir: Path)`
- Methods:
  - `create_staging_area(transaction_id: str) -> tuple[int, DirectoryIdentity, Path]`
  - `publish_generation(staging_generation_dir: Path, generation_id: str) -> Path`
  - Verifies that published generation directory matches expected ID and destination did not exist prior to atomic rename.

- [ ] **Step 1: Write RED tests for staging creation and generation publication**

```python
# launcher/tests/updater/test_generation_publisher.py
import pytest
from pathlib import Path
from neko_launcher.updater.generation_publisher import GenerationPublisher

def test_atomic_generation_publication(tmp_path: Path):
    pub = GenerationPublisher(tmp_path)
    handle, identity, stage_dir = pub.create_staging_area("tx-123")
    gen_stage = stage_dir / "generation"
    gen_stage.mkdir()
    (gen_stage / "test.txt").write_text("hello")

    target_gen_id = "g-00000000000000000002-abcd"
    final_path = pub.publish_generation(gen_stage, target_gen_id)
    assert final_path.exists()
    assert (final_path / "test.txt").read_text() == "hello"
    assert not gen_stage.exists()
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_generation_publisher.py`
Expected: FAIL.

- [ ] **Step 3: Implement GenerationPublisher**

Implement in `launcher/src/neko_launcher/updater/generation_publisher.py`:
- Create `staging/<tx_id>` and capture `DirectoryIdentity`.
- Perform atomic rename via `MoveFileExW` with `MOVEFILE_WRITE_THROUGH` (or standard MoveFileEx without REPLACE_EXISTING).
- Fail if destination already exists and differs.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_generation_publisher.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/generation_publisher.py tests/updater/test_generation_publisher.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/generation_publisher.py launcher/tests/updater/test_generation_publisher.py
git commit -m "feat(updater): implement generation staging and atomic publisher"
```
