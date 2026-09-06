# Software Update Phase 3 — Slice D Implementation Plan: Atomic Core Bundle & Runtime-Write Separation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement atomic Core bundle verification, strict ZIP extraction (with streaming size/ratio bounds and Win32 path validation), C# Core runtime-write separation (redirecting `logging` and temporary files to `LocalAppData\NEKO FAMILY\update-runtime\<generation-id>`), and the credential-free `--update-preflight` Core entry.

**Architecture:** Core is an atomic bundle identified by `canonical-core-manifest.json` (SHA-256 and exact file map). The Python updater extracts `core.artifact.zip` into `staging/<tx_id>/generation/ProxyCore` using a custom streaming extractor enforcing limits: max 8,192 files, max 1 GiB uncompressed, max 200:1 ratio per file, Win32 reserved name rejection, no parent directory traversal, and no symlinks/reparse points. In C# `NekoProxyCore`, `NetchRuntimeBootstrap` is modified to decouple `immutableResourceRoot` (read-only bundle) from `mutableRuntimeRoot` (for logs, temp route files, and CWD), preserving zero file changes inside the signed Core inventory during execution.

**Tech Stack:** Python 3.11, `zipfile` streaming, `hashlib`, C# (.NET 6.0 SDK 6.0.428), `NekoProxyCore.Legacy`, `NekoProxyCore.Host`, xUnit/MSTest for C#, pytest for Python.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§2, 4, 6, 7, 12, 17.7).

---

## Global Constraints

- Canonical Core baseline fixture: `E:\Github\worktrees\NekoProxyCore-live-update\TestResults\task12\a43-core` remains read-only reference evidence. Never modify it.
- Core branch: `feature/live-update-core` in `E:\Github\worktrees\NekoProxyCore-live-update`.
- Core ZIP format: STORE or DEFLATE only, no encryption, no multipart, manifest <= 8 MiB, total expanded <= 1 GiB.
- Character set for relative paths: printable ASCII `[A-Za-z0-9._ ()'-]+`, max 240 UTF-16 characters total, max 120 per segment, max 16 segments. Win32 reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1..9`, `LPT1..9`, `CLOCK$`, `CONIN$`, `CONOUT$`) strictly rejected.
- C# Core must accept `--update-preflight` command-line argument, read protocol input on stdin, validate dependencies, output JSON result, and exit 0 without executing any proxy session or network operations.

---

### Task 1: Strict Streaming Core ZIP Extractor

**Files:**
- Create: `launcher/src/neko_launcher/updater/zip_extractor.py`
- Create: `launcher/tests/updater/test_zip_extractor.py`

**Interfaces:**
- Produces: `extract_core_bundle(zip_path: Path, destination_dir: Path) -> CoreExtractionSummary`
- Enforces:
  - File count <= 8,192 (+ manifest = 8,193)
  - Expansion ratio <= 200:1
  - Max single file <= 256 MiB
  - Max total expanded <= 1,073,741,824 bytes
  - Win32 reserved names rejection (case-insensitive, including extension forms like `nul.txt`)
  - POSIX relative paths only, no leading `/`, no `..`, no `:` or `\`

- [ ] **Step 1: Write RED tests for strict ZIP extraction and malicious payload rejection**

```python
# launcher/tests/updater/test_zip_extractor.py
import pytest
import io
import zipfile
from pathlib import Path
from neko_launcher.updater.zip_extractor import extract_core_bundle, ZipSecurityError

def test_extracts_valid_minimal_zip(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("test.txt", "hello world")
        zf.writestr("mode/Game.txt", "game mode config")
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(buf.getvalue())

    dest = tmp_path / "dest"
    summary = extract_core_bundle(zip_path, dest)
    assert (dest / "test.txt").read_text() == "hello world"
    assert (dest / "mode" / "Game.txt").read_text() == "game mode config"
    assert summary.file_count == 2

def test_rejects_path_traversal(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", "evil")
    zip_path = tmp_path / "evil.zip"
    zip_path.write_bytes(buf.getvalue())
    with pytest.raises(ZipSecurityError, match="Path traversal rejected"):
        extract_core_bundle(zip_path, tmp_path / "dest")

def test_rejects_win32_reserved_names(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("con.txt", "evil device")
    zip_path = tmp_path / "con.zip"
    zip_path.write_bytes(buf.getvalue())
    with pytest.raises(ZipSecurityError, match="Reserved Win32 device name"):
        extract_core_bundle(zip_path, tmp_path / "dest")
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_zip_extractor.py`
Expected: FAIL (ModuleNotFoundError: `neko_launcher.updater.zip_extractor`).

- [ ] **Step 3: Implement streaming ZIP extractor**

Implement in `launcher/src/neko_launcher/updater/zip_extractor.py`:
- Use low-level `zipfile.ZipFile`.
- Stream uncompressed data chunk by chunk (64 KiB chunks) while tracking total bytes and per-file expansion ratios.
- Validate path grammar against regex `^[A-Za-z0-9._ ()'-]+$`.
- Strip and check 8.3 / reserved device names against `{"CON", "PRN", "AUX", "NUL", ...}`.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_zip_extractor.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/zip_extractor.py tests/updater/test_zip_extractor.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/zip_extractor.py launcher/tests/updater/test_zip_extractor.py
git commit -m "feat(updater): implement secure streaming zip extractor for core bundles"
```

---

### Task 2: Canonical Core Manifest Verifier

**Files:**
- Create: `launcher/src/neko_launcher/updater/core_manifest_verifier.py`
- Create: `launcher/tests/updater/test_core_manifest_verifier.py`

**Interfaces:**
- Produces: `verify_canonical_core_bundle(bundle_dir: Path) -> CoreVerificationResult`
- Validates `canonical-core-manifest.json` against all on-disk files.
- Checks `file_count`, `total_bytes`, key executables/DLLs hashes, and ensures zero extra unlisted files on disk.

- [ ] **Step 1: Write RED tests verifying a43 canonical core manifest**

```python
# launcher/tests/updater/test_core_manifest_verifier.py
import pytest
from pathlib import Path
from neko_launcher.updater.core_manifest_verifier import verify_canonical_core_bundle

CANONICAL_A43_ROOT = Path("E:/Github/worktrees/NekoProxyCore-live-update/TestResults/task12/a43-core")

def test_verifies_canonical_a43_fixture():
    res = verify_canonical_core_bundle(CANONICAL_A43_ROOT)
    assert res.valid
    assert res.file_count == 1022
    assert res.total_bytes == 371717577
    assert res.manifest_sha256 == "d39f43c75ac84fa3189f93f935dd30b6538ee76b3c817652d711451c3f15b59a"

def test_rejects_tampered_core_bundle(tmp_path: Path):
    # Copy minimal dummy bundle and tamper one byte
    ...
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_core_manifest_verifier.py`
Expected: FAIL.

- [ ] **Step 3: Implement core manifest verifier**

Implement in `launcher/src/neko_launcher/updater/core_manifest_verifier.py`:
- Parse `canonical-core-manifest.json` with canonical JSON loader.
- Verify security assertions (`runtime_settings_key_files == 0`, `plaintext_settings_files == 0`).
- Iterate and hash every mapped file; verify exact length and SHA-256 match.
- Enumerate on-disk directory recursively and assert disk set == manifest set + `{"canonical-core-manifest.json"}`.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_core_manifest_verifier.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/core_manifest_verifier.py tests/updater/test_core_manifest_verifier.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/core_manifest_verifier.py launcher/tests/updater/test_core_manifest_verifier.py
git commit -m "feat(updater): implement canonical core manifest bundle verifier"
```

---

### Task 3: Core C# Runtime-Write Separation & Preflight Entry

**Files:**
- Modify: `E:\Github\worktrees\NekoProxyCore-live-update\NekoProxyCore.Legacy\NetchRuntimeBootstrap.cs`
- Modify: `E:\Github\worktrees\NekoProxyCore-live-update\NekoProxyCore.Host\Program.cs`
- Test: `E:\Github\worktrees\NekoProxyCore-live-update\NekoProxyCore.Tests\RuntimeBootstrapTests.cs`

**Interfaces:**
- `NetchRuntimeBootstrap.InitializeProtectedAsync(immutableResourceRoot, mutableRuntimeRoot, protectedSettingsPath, key, ct)`
- Creates `logging` directory inside `mutableRuntimeRoot`, NOT in `immutableResourceRoot`.
- Sets working directory to `mutableRuntimeRoot`.
- `Program.cs` handles `--update-preflight` CLI flag: reads JSON from stdin `{"protocol_version":1,"generation_id":"..."}`, checks dependency loading and DLL exports, writes `{"protocol_version":1,"result":"PASS","code":null}` to stdout, and exits 0.

- [ ] **Step 1: Write RED tests in C# for mutable runtime root separation**

```csharp
// In NekoProxyCore.Tests/RuntimeBootstrapTests.cs
[Fact]
public async Task InitializeProtected_CreatesLoggingInMutableRoot_NotResourceRoot()
{
    var resourceRoot = Path.Combine(Path.GetTempPath(), "Resource_" + Guid.NewGuid());
    var mutableRoot = Path.Combine(Path.GetTempPath(), "Mutable_" + Guid.NewGuid());
    Directory.CreateDirectory(resourceRoot);
    Directory.CreateDirectory(mutableRoot);

    try
    {
        // Run bootstrap with separated roots
        await NetchRuntimeBootstrap.InitializeProtectedAsync(resourceRoot, mutableRoot, ...);
        Assert.True(Directory.Exists(Path.Combine(mutableRoot, "logging")));
        Assert.False(Directory.Exists(Path.Combine(resourceRoot, "logging")));
    }
    finally
    {
        Directory.Delete(resourceRoot, true);
        Directory.Delete(mutableRoot, true);
    }
}
```

- [ ] **Step 2: Run dotnet test to verify genuine RED**

Run: `dotnet test E:\Github\worktrees\NekoProxyCore-live-update\NekoProxyCore.Tests\NekoProxyCore.Tests.csproj`
Expected: FAIL (method signature does not match or directory created in wrong location).

- [ ] **Step 3: Implement runtime-write separation and preflight in C# Core**

Implement in `NetchRuntimeBootstrap.cs` and `Program.cs`:
- Support 2-root initialization: resource root for read-only modes, binaries, and `runtime-settings.nkps`; mutable root for `logging` and temporary route state.
- Handle `--update-preflight` in `Program.cs`:
  - Validate that `AppContext.BaseDirectory` is intact.
  - Load and check native DLLs (`nfapi.dll`, `Redirector.bin`).
  - Output strict JSON line to stdout and exit 0.

- [ ] **Step 4: Run dotnet build and test to verify GREEN**

Run: `dotnet build E:\Github\worktrees\NekoProxyCore-live-update\NekoProxyCore.sln -c Release`
Run: `dotnet test E:\Github\worktrees\NekoProxyCore-live-update\NekoProxyCore.Tests\NekoProxyCore.Tests.csproj -c Release`
Expected: Build successful (0 warnings/errors), tests pass.

- [ ] **Step 5: Commit Core Worktree**

```bash
git -C E:/Github/worktrees/NekoProxyCore-live-update add NekoProxyCore.Legacy/NetchRuntimeBootstrap.cs NekoProxyCore.Host/Program.cs NekoProxyCore.Tests/RuntimeBootstrapTests.cs
git -C E:/Github/worktrees/NekoProxyCore-live-update commit -m "feat(core): separate mutable runtime writes from immutable resource root and add update-preflight"
```
