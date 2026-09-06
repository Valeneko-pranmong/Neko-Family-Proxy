# Software Update Phase 3 — Slice L Implementation Plan: Candidate Preparation (5.1.0a3) & Gate #2 Package

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bump the Launcher version to `5.1.0a3`, build packaged standalone candidates for `NekoLauncher.exe` and `NekoUpdater.exe`, execute packaged smoke verification, and assemble the comprehensive Owner Gate #2 Production Authorization Package without performing any production mutation.

**Architecture:** Version identity is bumped in the two canonical locations: `launcher/pyproject.toml` and `launcher/src/neko_launcher/__init__.py`. PyInstaller builds the standalone `NekoLauncher.exe` and `NekoUpdater.exe` into a new, isolated directory `E:\Github\artifacts\phase3\5.1.0a3-candidate`. Packaged smoke tests verify that the binaries launch, report version `5.1.0a3`, execute clean process lifecycle, and clean up temporary `_MEI` directories. A formal Owner Gate #2 package is prepared documenting hashes, signing procedures, and deployment order.

**Tech Stack:** Python 3.11, PyInstaller 6.21.0, pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§12, 13, 14, 17).

---

## Global Constraints

- Do not overwrite `5.1.0a2` candidate artifacts in `E:\Github\artifacts\phase2\5.1.0a2-candidate`.
- Version bump applies strictly to:
  1. `launcher/pyproject.toml`: `version = "5.1.0a3"`
  2. `launcher/src/neko_launcher/__init__.py`: `__version__ = "5.1.0a3"`
- Packaged smoke must verify: visible window, version 5.1.0a3, no lingering `_MEI` folders, exact parent/child normal exit.
- STOP before ANY production mutation: no production Vercel deploy, no production key use, no active release publication.

---

### Task 1: Canonical Version Bump to 5.1.0a3 & Full Regression

**Files:**
- Modify: `launcher/pyproject.toml`
- Modify: `launcher/src/neko_launcher/__init__.py`
- Test: Full regression suite across all repositories

- [ ] **Step 1: Write RED test asserting version bump**

```python
# In test asserting version
from neko_launcher import __version__
def test_launcher_version_is_5_1_0a3():
    assert __version__ == "5.1.0a3"
```

- [ ] **Step 2: Update version declarations**

Update `pyproject.toml` and `__init__.py`.

- [ ] **Step 3: Run full pytest and Ruff suite**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add launcher/pyproject.toml launcher/src/neko_launcher/__init__.py
git commit -m "release: bump version to 5.1.0a3 for phase 3 live update candidate"
```

---

### Task 2: Standalone Candidate Packaging & Smoke Verification

**Files:**
- Create: `launcher/NekoUpdater.spec`
- Create: `artifacts/phase3/5.1.0a3-candidate/`
- Create: `launcher/tests/smoke/test_packaged_smoke_a3.py`

**Interfaces:**
- Produces packaged binaries:
  - `E:\Github\artifacts\phase3\5.1.0a3-candidate\NekoLauncher.exe`
  - `E:\Github\artifacts\phase3\5.1.0a3-candidate\NekoUpdater.exe`
- Runs smoke harness: verifies window creation, version display, clean shutdown, and zero remaining `_MEI` temp folders.

- [ ] **Step 1: Build standalone binaries with PyInstaller**

Run: `build/venv-5.1/Scripts/python.exe -m PyInstaller --clean NekoLauncher.spec`
Run: `build/venv-5.1/Scripts/python.exe -m PyInstaller --clean NekoUpdater.spec`

- [ ] **Step 2: Run packaged smoke test**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/smoke/test_packaged_smoke_a3.py`
Expected: PASS with `PASS_NO_LOGIN_NO_START`.

- [ ] **Step 3: Record artifact metadata and SHA-256**

---

### Task 3: Assemble Owner Gate #2 Production Authorization Package

**Files:**
- Create: `E:\Github\Project manager\OWNER_GATE_2_PRODUCTION_PACKAGE.md`

**Interfaces:**
- Documents:
  - Exact binary hashes and sizes for `5.1.0a3`
  - Canonical Core manifest identity
  - Production Ed25519 public key provisioning plan
  - Production private key custody procedure
  - Admin deployment sequence
  - Rollback and revocation plan
  - Owner authorization checklist

- [ ] **Step 1: Write Owner Gate #2 production authorization package**

- [ ] **Step 2: Commit documentation**

```bash
git add docs/
git commit -m "docs: assemble owner gate 2 production authorization package"
```
