# Software Update Phase 3 — Slice B Implementation Plan: Artifact Staging & Controlled Grants

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the broker-controlled artifact download handoff (`BEGIN` -> `REQUEST_READY` -> download -> `APPLY`), Win32 `DirectoryIdentity` capture, and the controlled Core grant authorization model using a dedicated distribution capability in Windows Credential Manager and server-side capability validation in the Admin tool.

**Architecture:** The Launcher requests update preparation via `BEGIN` carrying the signed envelope. The broker authenticates the envelope, verifies that candidate sequence > observed, exclusively creates `incoming/<request-id>`, captures the directory's Win32 volume serial and 128-bit file ID (`DirectoryIdentity`), and flushes `PREPARING(ADMITTED)` before replying with `REQUEST_READY`. The Launcher downloads changed artifacts to fixed filenames (`launcher.artifact`, `core.artifact.zip`) without passing child-chosen paths. Core download requires `Authorization: NekoDistribution <capability>`, resolved in memory from Windows Credential Manager; the Admin tool validates the capability against its protected registry before issuing short-lived private signed URLs.

**Tech Stack:** Python 3.11, ctypes Win32 API (`GetFileInformationByHandleEx`), Node.js v24 (Admin tool), Windows Credential Manager (`win32cred` / `ctypes.windll.advapi32`), pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§4, 7, 10, 10.1, 14, 14.1, 15).

---

## Global Constraints

- Launcher code: `launcher/src/neko_launcher/updater/`
- Admin tool code: `E:\Github\worktrees\Neko-Family-Proxy-admin-tool-software-update`
- Windows Credential Manager target name: `NEKO-FAMILY/SoftwareUpdateDistribution/v1`.
- Memory-only capability handling: no storing the distribution capability in configuration files, plaintext logs, project artifacts, command-line arguments, or environment variables.
- Admin endpoint `POST /api/software-update/artifact-grant` must enforce capability for controlled Core artifacts while optionally permitting anonymous access for Launcher artifacts.
- Fixed incoming file paths: `incoming/<request-id>/launcher.artifact` and `incoming/<request-id>/core.artifact.zip`. No arbitrary filenames.

---

### Task 1: Win32 DirectoryIdentity & Handle Security

**Files:**
- Create: `launcher/src/neko_launcher/updater/win32_directory.py`
- Create: `launcher/tests/updater/test_win32_directory.py`

**Interfaces:**
- Produces: `get_directory_identity(dir_handle: int) -> DirectoryIdentity`
- Produces: `create_incoming_container(root_dir: Path, request_id: str) -> tuple[int, DirectoryIdentity, Path]`
- Produces: `open_directory_guarded(path: Path) -> int` (opens with `FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT`, share-delete denied)

- [ ] **Step 1: Write RED tests for directory identity extraction and non-reparse verification**

```python
# launcher/tests/updater/test_win32_directory.py
import pytest
from pathlib import Path
from neko_launcher.updater.win32_directory import (
    create_incoming_container, open_directory_guarded, get_directory_identity
)

def test_create_incoming_container_returns_valid_identity(tmp_path: Path):
    handle, identity, path = create_incoming_container(tmp_path, "req-001")
    try:
        assert path.exists()
        assert len(identity.volume_serial) == 16
        assert len(identity.file_id) == 32
        assert len(identity.parent_file_id) == 32
    finally:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(handle)
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_win32_directory.py`
Expected: FAIL (ModuleNotFoundError: `neko_launcher.updater.win32_directory`).

- [ ] **Step 3: Implement Win32 DirectoryIdentity and handle-safe directory creation**

Implement in `launcher/src/neko_launcher/updater/win32_directory.py`:
- Call `CreateFileW` with `FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT`, `GENERIC_READ | FILE_LIST_DIRECTORY`, and share mode denying delete/rename.
- Call `GetFileInformationByHandleEx` with `FileIdInfo` (class 18) to retrieve 128-bit `FileId` and 64-bit `VolumeSerialNumber`.
- Format as fixed-width lowercase hex strings.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_win32_directory.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/win32_directory.py tests/updater/test_win32_directory.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/win32_directory.py launcher/tests/updater/test_win32_directory.py
git commit -m "feat(updater): implement win32 directory identity and handle security"
```

---

### Task 2: Broker Download Handoff Protocol (`BEGIN` -> `REQUEST_READY` -> `APPLY`)

**Files:**
- Create: `launcher/src/neko_launcher/updater/staging_handoff.py`
- Create: `launcher/tests/updater/test_staging_handoff.py`

**Interfaces:**
- Produces: `handle_begin_message(broker_ctx, envelope_b64: str) -> RequestReadyResult`
- Produces: `handle_apply_message(broker_ctx, transaction_id: str, request_id: str) -> ApplyResult`
- Validates that candidate sequence > observed floor, creates `incoming/<request-id>`, records `DirectoryIdentity`, flushes durable `PREPARING` snapshot before returning `REQUEST_READY`.

- [ ] **Step 1: Write RED tests for BEGIN / REQUEST_READY / APPLY sequence**

```python
# launcher/tests/updater/test_staging_handoff.py
import pytest
from neko_launcher.updater.staging_handoff import handle_begin_message, handle_apply_message

def test_begin_creates_incoming_and_returns_ready(broker_context, valid_envelope_b64):
    res = handle_begin_message(broker_context, valid_envelope_b64)
    assert res.error is None
    assert res.transaction_id is not None
    assert res.request_id is not None
    assert res.changed == {"launcher": True, "core": True}
    # Verify incoming dir exists on disk with identity recorded
    incoming_dir = broker_context.root / "incoming" / res.request_id
    assert incoming_dir.exists()

def test_begin_rejects_downgrade_sequence(broker_context, downgrade_envelope_b64):
    res = handle_begin_message(broker_context, downgrade_envelope_b64)
    assert res.error == "DOWNGRADE_REJECTED"
    assert res.transaction_id is None
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_staging_handoff.py`
Expected: FAIL.

- [ ] **Step 3: Implement staging handoff coordinator**

Implement in `launcher/src/neko_launcher/updater/staging_handoff.py`:
- Unpack and verify Ed25519 envelope against public key registry.
- Extract candidate `ReleaseSet` (v2).
- Compare candidate component hashes against current committed generation to determine `changed.launcher` and `changed.core`.
- Create incoming container; persist `PREPARING(ADMITTED)` state via `state_machine.py`.
- Formulate `REQUEST_READY` payload.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_staging_handoff.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/staging_handoff.py tests/updater/test_staging_handoff.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/staging_handoff.py launcher/tests/updater/test_staging_handoff.py
git commit -m "feat(updater): implement broker begin and apply handoff protocol"
```

---

### Task 3: Controlled Core Grant Authorization in Admin Tool

**Files:**
- Modify: `server/software-update.mjs` (in admin worktree `E:\Github\worktrees\Neko-Family-Proxy-admin-tool-software-update`)
- Modify: `tests/software-update.test.mjs`
- Modify: `tests/vercel-api.test.mjs`

**Interfaces:**
- Updates `getArtifactGrant(artifactId, env, now, authorizationHeader)`
- Enforces `Authorization: NekoDistribution <capability>` for controlled Core artifacts (`distribution: "controlled-core"`).
- Compares SHA-256 of capability with constant-time equality against `DISTRIBUTION_CAPABILITIES_JSON`.

- [ ] **Step 1: Write RED tests in Node.js for capability authentication and anonymous rejection**

```javascript
// In admin-tool tests/software-update.test.mjs
test("artifact grant requires NekoDistribution capability for controlled core artifact", async () => {
  const env = {
    ...validEnv,
    DISTRIBUTION_CAPABILITIES_JSON: JSON.stringify([
      {
        credential_sha256: crypto.createHash("sha256").update("valid-secret-cap").digest("hex"),
        enabled: true,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        artifact_ids: ["core-v1-artifact"]
      }
    ])
  };
  // Anonymous request must fail with 401
  assert.throws(
    () => getArtifactGrant("core-v1-artifact", env, new Date(), null),
    { code: "DISTRIBUTION_CAPABILITY_REQUIRED", status: 401 }
  );
  // Valid capability succeeds
  const grant = getArtifactGrant("core-v1-artifact", env, new Date(), "NekoDistribution dmFsaWQtc2VjcmV0LWNhcA");
  assert.ok(grant.url);
});
```

- [ ] **Step 2: Run node tests to verify genuine RED**

Run: `E:/Github/tools/node-v24-portable/node-v24.20.0-win-x64/node.exe --test tests/software-update.test.mjs`
Expected: FAIL with `DISTRIBUTION_CAPABILITY_REQUIRED`.

- [ ] **Step 3: Implement capability verification in Admin provider**

Implement in `server/software-update.mjs`:
- Parse authorization header `NekoDistribution <token>`.
- Hash token with SHA-256; perform constant-time match with active registry.
- Check artifact ID scope and expiration.

- [ ] **Step 4: Run full admin tests to verify GREEN**

Run: `E:/Github/tools/node-v24-portable/node-v24.20.0-win-x64/node.exe --test tests/*.test.mjs`
Expected: 115+ passed, 0 failed.

- [ ] **Step 5: Commit Admin Worktree**

```bash
git -C E:/Github/worktrees/Neko-Family-Proxy-admin-tool-software-update add server/software-update.mjs tests/software-update.test.mjs tests/vercel-api.test.mjs
git -C E:/Github/worktrees/Neko-Family-Proxy-admin-tool-software-update commit -m "feat(update): enforce distribution capability on controlled core artifact grants"
```

---

### Task 4: Windows Credential Manager Distribution Capability Client in Launcher

**Files:**
- Create: `launcher/src/neko_launcher/infrastructure/distribution_credential.py`
- Create: `launcher/tests/test_distribution_credential.py`

**Interfaces:**
- Produces: `get_distribution_capability() -> str | None`
- Produces: `set_distribution_capability(capability: str) -> None`
- Produces: `clear_distribution_capability() -> None`
- Interacts strictly with `Advapi32.dll` (`CredReadW`, `CredWriteW`, `CredDeleteW`) under target `NEKO-FAMILY/SoftwareUpdateDistribution/v1`.

- [ ] **Step 1: Write RED tests with mocked Win32 Credential calls & memory safety**

```python
# launcher/tests/test_distribution_credential.py
import pytest
from neko_launcher.infrastructure.distribution_credential import (
    get_distribution_capability, set_distribution_capability, clear_distribution_capability
)

def test_credential_storage_roundtrip(monkeypatch):
    # Test memory store mock or real user credential test
    ...
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/test_distribution_credential.py`
Expected: FAIL.

- [ ] **Step 3: Implement Credential Manager client**

Implement in `launcher/src/neko_launcher/infrastructure/distribution_credential.py`:
- Use `ctypes.windll.advapi32` with explicit 64-bit types.
- Ensure retrieved secret string is cleared from memory as soon as header construction finishes.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/test_distribution_credential.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/infrastructure/distribution_credential.py tests/test_distribution_credential.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/infrastructure/distribution_credential.py launcher/tests/test_distribution_credential.py
git commit -m "feat(updater): implement windows credential manager distribution capability storage"
```
