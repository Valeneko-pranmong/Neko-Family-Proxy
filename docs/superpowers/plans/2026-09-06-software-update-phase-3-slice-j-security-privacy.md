# Software Update Phase 3 — Slice J Implementation Plan: Security, Privacy & Static Policy Regression

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the security and privacy regression test suite, validating path traversal defenses, reparse point rejection, Alternate Data Stream (ADS) defenses, 8.3 alias defenses, secret-leakage prevention in command-line arguments and logs, and diagnostic redaction rules.

**Architecture:** A dedicated test suite exercises malicious and edge-case inputs against the updater components: zip extraction, path resolution, IPC message serialization, log formatting, and process spawning. Automated scanners assert that no private keys, JWTs, Proxy credentials, or unsigned URLs are leaked into log files, process command lines, or git diffs.

**Tech Stack:** Python 3.11, pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§3, 7, 10, 14.1, 15).

---

## Global Constraints

- No secrets in logs: verify against regexes for private keys, bearer tokens, passwords, and signed URLs.
- Win32 filesystem attacks: explicitly test and reject NTFS reparse points (symlinks/junctions), Alternate Data Streams (`:stream`), 8.3 short name collisions, and device names (`NUL`, `CON`, etc.).
- Process environment and command-line scanning: inspect child process arguments and environment to confirm zero secrets passed.

---

### Task 1: Filesystem Security & Attack Matrix Test Suite

**Files:**
- Create: `launcher/tests/updater/test_security_filesystem.py`

**Interfaces:**
- Tests all path validation and handle security mechanisms against malicious input vectors:
  - Reparse points / junctions
  - Hardlinks
  - Alternate Data Streams (`test.txt:secret`)
  - 8.3 short name alias attacks (`PROGRA~1`)
  - Path traversal (`../`, `..\\`)
  - Reserved Win32 device names in all case/extension variations

- [ ] **Step 1: Write comprehensive filesystem security tests**

```python
# launcher/tests/updater/test_security_filesystem.py
import pytest
from pathlib import Path
...
```

- [ ] **Step 2: Run pytest to verify all security assertions hold**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_security_filesystem.py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add launcher/tests/updater/test_security_filesystem.py
git commit -m "test(updater): add comprehensive filesystem security and path-defense regression suite"
```

---

### Task 2: Secret Residue & Log Redaction Regression Test Suite

**Files:**
- Create: `launcher/tests/updater/test_security_privacy.py`

**Interfaces:**
- Scans generated logs, command lines, and IPC frames for forbidden markers:
  - `-----BEGIN PRIVATE KEY-----`
  - `Bearer eyJ...`
  - `NekoDistribution ...`
  - Raw permit tokens or passwords

- [ ] **Step 1: Write secret residue and log redaction tests**

```python
# launcher/tests/updater/test_security_privacy.py
import pytest
...
```

- [ ] **Step 2: Run pytest to verify privacy scanner passes**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_security_privacy.py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add launcher/tests/updater/test_security_privacy.py
git commit -m "test(updater): add secret-residue and log redaction regression suite"
```
