# Software Update Phase 3 — Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full Phase-3 transactional live update system for Neko Family 5.1, enabling atomic, crash-resilient update of Launcher and Core without running-executable overwrite, with mandatory credential-free probation, dual-slot durable authority, separate Core runtime writes, and automatic rollback on activation failure.

**Architecture:** A stable, un-updated helper (`NekoUpdater.exe`) supervises execution and manages updates across complete immutable release generations. Two 1 MiB durable fixed slot files hold authoritative state, signed evidence, and directory identities using an exhaustive transition automaton. Downloads occur via a broker-created incoming handoff; Core distribution uses a dedicated revocable capability in Windows Credential Manager. Local probation with mandatory Core loader preflight validates candidate health before durable slot selection and `NORMAL_AUTH`.

**Tech Stack:** Python 3.11, ctypes Win32 API, `cryptography` Ed25519, PyInstaller 6.21.0, C# (.NET 6.0 SDK 6.0.428), Node.js v24 (Admin tool), pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (Approved commit `fe4bab0f5665b88a8788b6a9d6d162a3e5764381`, SHA-256 `df3e425ca8c333721c29d3c421a6054e9bedda89832cf6e422efed6755d2b1c0`).

---

## Global Constraints

- **Single-Flight & Ownership:** Work strictly inside `E:\Github`. Routine engineering (code, tests, refactors, development commits, pushes to approved development branches, local/sandbox builds) is authorized autonomously under Owner Gate #1 approval.
- **Hard Authority Gates:** Stop only for: (1) material architecture divergence, (2) production signing key use/provisioning, (3) production Vercel deployment / main merge, (4) setting `SOFTWARE_UPDATE_ACTIVE_RELEASE_JSON` in production, (5) public tag or release.
- **TDD Law:** Tests-only commit → genuine RED execution assertion (collected, fails on assertion/missing symbol) → minimal GREEN code → tests pass → Ruff lint → diff check → commit. Collection/import errors are NOT valid RED.
- **Candidate & Evidence Preservation:** Never overwrite `v5.0.0`, `5.0.0a43`, `5.0.0a44`, or `5.1.0a2` candidate artifacts. Once Phase 3 code changes begin, bump canonical prerelease identity to `5.1.0a3` in `launcher/pyproject.toml` and `launcher/src/neko_launcher/__init__.py`.
- **Secret Separation:** No Proxy credentials, launch permits, JWTs, signing private keys, or Windows Credential Manager distribution secrets in command-line arguments, logs, IPC payloads, or git commits. Ephemeral Ed25519 keys for tests exist in memory only.
- **Core Bundle & Runtime Separation:** Core is an atomic immutable bundle identified by its canonical manifest. Core runtime writes (`logging`, data, temp, CWD mutation) must be redirected to a generation-scoped mutable directory under `LocalAppData\NEKO FAMILY\update-runtime\<generation-id>` before Core atomic replacement is accepted.
- **Process & Handle Discipline:** Retained Win32 handles with share-delete denied; no arbitrary root arguments or child-supplied path destinations; anonymous pipes via `GetStdHandle` slots for duplex framed JSON IPC; `state/family.lease` share-mode liveness guard for process family tracking.
- **Deterministic Outcomes:** Every failure or power-loss interruption must converge to either `OLD FULLY RESTORED` or `NEW FULLY COMMITTED`. Never leave a mixed or ambiguous installation.

---

## Slices Breakdown & Execution Order

The implementation is structured into 12 vertical slices (A through L):

```text
┌────────────────────────────────────────────────────────┐
│ SLICE A: Updater Transaction Model & Durable Journal   │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE B: Artifact Staging & Controlled Grant Auth      │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE C: Windows Helper Binary, Locks & Handle Safety  │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE D: Atomic Core Bundle & Runtime-Write Separation │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE E: Backup, Rollback & Replay Floor Preservation  │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE F: Every-Mutation Interruption Recovery Matrix   │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE G: Process Protocol & Packaged Onefile Handoff   │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE H: Restart, Mandatory Self-Test & Auth Handshake │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE I: UI & Application Update-State Integration     │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE J: Security, Privacy & Static Policy Regression  │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE K: Sandbox End-to-End Update & Rollback Proofs   │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SLICE L: Release Candidate (5.1.0a3) & Gate #2 Package │
└────────────────────────────────────────────────────────┘
```

---

## Detailed Slice Documents

1. **Slice A:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-a-transaction-journal.md`](2026-09-06-software-update-phase-3-slice-a-transaction-journal.md)
   - Canonical UTF-8 JSON serializer & deserializer
   - Dual-slot fixed frame layout (1 MiB, magic `NEKOUPD1`, checksum, body)
   - Enrollment marker frame (16 KiB, magic `NEKOENR1`)
   - State schema, closed records, predicates & pairwise resolution
   - Exhaustive 25-state transition automaton

2. **Slice B:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-b-artifact-staging.md`](2026-09-06-software-update-phase-3-slice-b-artifact-staging.md)
   - Broker-created incoming directory & `DirectoryIdentity` capture
   - `BEGIN` / `REQUEST_READY` / `APPLY` download handoff protocol
   - Admin server controlled Core grant registry & capability verification
   - Windows Credential Manager distribution capability storage in Launcher

3. **Slice C:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-c-windows-helper.md`](2026-09-06-software-update-phase-3-slice-c-windows-helper.md)
   - `NekoUpdater` executable entry, fixed KnownFolder root validation
   - `control.lock` exclusive `LockFileEx` (byte 0)
   - `family.lease` share-mode liveness guard (read-only lease inherited to descendants)
   - Atomic generation publication & immutable directory protection

4. **Slice D:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-d-core-bundle.md`](2026-09-06-software-update-phase-3-slice-d-core-bundle.md)
   - Canonical Core manifest verifier (1,022 files, 371 MB baseline matching a43)
   - Strict ZIP extractor (streaming size/ratio limits, Win32 reserved name & path validation)
   - Core C# adaptation: runtime write relocation to `LocalAppData\NEKO FAMILY\update-runtime\<gen-id>`
   - Core `--update-preflight` entry for credential-free dependency check

5. **Slice E:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-e-backup-rollback.md`](2026-09-06-software-update-phase-3-slice-e-backup-rollback.md)
   - Pre-quiesce abort preserving healthy active session & `previous` descriptor
   - Post-quiesce rollback with restricted probation
   - Atomic scratch queue transfer to `CLEANING` phase
   - Preservation of monotonic `highwater` and `observed` replay floors

6. **Slice F:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-f-interruption-recovery.md`](2026-09-06-software-update-phase-3-slice-f-interruption-recovery.md)
   - Idempotent recovery dispatcher for all 25 mutation/durable boundaries
   - Torn slot write recovery & namespace rename loss recovery
   - Crash during cleanup recovery with handle-relative identity checks
   - Fault-injection harness simulating interruption at every step

7. **Slice G:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-g-process-handoff.md`](2026-09-06-software-update-phase-3-slice-g-process-handoff.md)
   - Duplex framed JSON IPC over standard input/output anonymous pipes
   - Job Object assignment with kill-on-close semantics
   - PyInstaller 6.21.0 bootloader stream handle inheritance verification
   - Early bootstrap hook in `main.py` before `app_factory` imports

8. **Slice H:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-h-restart-selftest.md`](2026-09-06-software-update-phase-3-slice-h-restart-selftest.md)
   - Restricted candidate probation runner
   - Mandatory Core preflight execution via stdin/stdout pipe
   - Tkinter event-loop responsiveness probe
   - `NORMAL_AUTH` / `NORMAL_ACK` handshake before normal composition

9. **Slice I:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-i-ui-application.md`](2026-09-06-software-update-phase-3-slice-i-ui-application.md)
   - UpdateCheckService integration with Phase 3 signed payload schema v2
   - Idle-safe update application policy (block during active game/proxy session)
   - UI status indicators, notification banners, and user restart prompts

10. **Slice J:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-j-security-privacy.md`](2026-09-06-software-update-phase-3-slice-j-security-privacy.md)
    - Anti-traversal, reparse point, hardlink, ADS, and 8.3 alias defense tests
    - Process command-line and environment secret-leakage scan
    - Synthetic secret marker scanning across artifacts and logs
    - Diagnostic logging policy enforcement

11. **Slice K:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-k-e2e-sandbox.md`](2026-09-06-software-update-phase-3-slice-k-e2e-sandbox.md)
    - End-to-end sandbox update: N → N+1 for Launcher-only, Core-only, and combined
    - Broken candidate N+2: self-test failure → automatic rollback → N+1 restored and runnable
    - Repeated recovery idempotence test (run 1 converges, run 2 mutates nothing)

12. **Slice L:** [`docs/superpowers/plans/2026-09-06-software-update-phase-3-slice-l-candidate-release-prep.md`](2026-09-06-software-update-phase-3-slice-l-candidate-release-prep.md)
    - Prerelease version bump to `5.1.0a3`
    - Standalone packaged build of `NekoLauncher.exe` and `NekoUpdater.exe`
    - Verification summary, artifact hashing, and Owner Gate #2 authorization package preparation
