# NEKO FAMILY PROXY — Current Component Status & 5.1.6 Release Line

```text
DOCUMENT:                       docs/current/README.md
STATUS:                         STABLE RELEASE 5.1.6 (maintained on main)
PRODUCT_BASELINE:               5.1.6
CURRENT_STABLE_TAG:             v5.1.6 (01d5331, released 2026-09-21)
ACTIVE_DEV_BRANCH:              main
MAIN_HEAD_AT_REVIEW:            616ff89 (2026-10-24)
DISTRIBUTION_ARCHITECTURE:      TWO-REPO ROLE INVERSION (ACTIVE)
UPDATE_LIFECYCLE:               BACKGROUND STAGE -> DURABLE PENDING -> DEFERRED OFFLINE APPLY
AUTH_FLOW:                      PASS (Fail-closed Lite auth + single-session arbitration)
PROXY_FLOW:                     PASS (Runtime Config v1 + Core pipe supervision)
SESSION_GUARD_INVARIANT:        PASS (Zero forced game/proxy termination on update)
NEXT_LAUNCH_APPLY:              PASS (Offline verified bootstrap before window creation)
BOOTSTRAP_AUTHORITY:            PASS (Bounded v5.1.0 signed archive override; historical bootstrap)
LAUNCHER_TITLE_BINDING:         PASS (Bound to canonical neko_launcher.__version__)
INSTALLER_CORE_AUTHORITY:       PASS (Dynamic build authority propagation via ISCC)
REPOSITORY_SAFETY:              PASS (scripts/check_repository_safety.py, 2026-10-24)
TEST_SUITE:                     2,533 passed / 3 skipped (local 2026-10-24)
LAST_VERIFIED:                  2026-10-24 +07:00 (Asia/Bangkok)
```

> **Current-state rule:** `main` is the maintained release line and `v5.1.6` is the current public stable release. The 5.1.2 architecture described below remains the foundation of the deferred update lifecycle; it has been shipped and extended through 5.1.3–5.1.6. This document describes repository state, not a hosted-backend deployment audit.

---

## 1. What is the current architecture doing?

The 5.1.2 architecture introduced the **Deferred Update Lifecycle** and the **Production Updates & Canonical Main Repository Topology** (Revision 3.4). Later patch releases extended it without changing the fail-closed authorization model:

### 1.1 Repository Roles & Distribution Topology
- **Machine-Update Channel**: The dedicated updates repository `Valeneko-pranmong/Neko-Family-Proxy-Updates` serves as the permanent machine-update channel.
- **Machine Assets**: Every machine release publishes four canonical signed assets:
  1. `release-v2.json` (canonical Ed25519-signed manifest)
  2. `NekoLauncher.exe`
  3. `NekoUpdater.exe`
  4. `NekoProxyCore.zip`
  *Note: Normal users must not be linked to the machine repository as a download surface.*
- **Human-Facing Installer Surface**: The canonical main repository `Valeneko-pranmong/Neko-Family-Proxy` serves as the official human release surface. Standalone installer executables (`NekoFamilyProxy-Installer.exe`) are distributed directly from main repository releases (`Valeneko-pranmong/Neko-Family-Proxy/releases`). Any historical separate installer repository is retired.

### 1.2 Bounded Bootstrap Authority Override (Historical)
- Public `v5.1.0` was released installer-only and lacked public machine assets (`release-v2.json`, `NekoProxyCore.zip`, etc.).
- To establish the first machine release, `scripts/release_controller.py` implemented a strictly bounded bootstrap authority override:
  - Scoped exclusively to bootstrap Stable `v5.1.0`.
  - Consumed the byte-for-byte archived Attempt-3 signed manifest and Core bundle.
  - Verified production Ed25519 signature, channel, Core hash, size, canonical manifest, and installed identity.
  - Automatically refused for newer versions or arbitrary local files.
  - Disabled once a newer accepted machine release existed on GitHub.
- The bootstrap path is retained for traceability; it is not the release path for the current line.

### 1.3 Release Line 5.1.3–5.1.6
- **v5.1.3**: installed-file integrity check and repair in Settings; update-notification and Settings-focus refinements; clean uninstall/state cleanup; machine credential provisioned during baseline enrollment.
- **v5.1.4**: 64-bit WOW64 redirection guard in the elevated driver installer and non-BOM ASCII installer logging.
- **v5.1.5**: native `ensure-netfilter2.cmd` Sysnative dispatcher and Inno Setup result-file polling guard.
- **v5.1.6**: startup update-check splash before the main window; in-app update progress dialog; windowless updater helper; committed-generation self-sync; Settings version check; baseline enrollment from a working-directory install root.

---

## 2. Deferred Update Lifecycle

The released client architecture guarantees that update operations never disrupt active user gameplay or proxy sessions:

1. **Every-Open Discovery**: Launcher automatically schedules a background check on startup; manual checks remain independent.
2. **Background Staging (`SoftwareUpdateStageService`)**:
   - Downloads changed components (`Launcher`, `Core`) into private staging directories while the session continues.
   - Preserves exact signed `release-v2.json` envelope and verifies byte counts and SHA-256 hashes against the signature.
3. **Durable Pending Store (`PendingUpdateStore`)**:
   - Atomically promotes fully staged candidates to `%LOCALAPPDATA%\NEKO FAMILY\update-pending\`.
   - On load, reconstructs trust offline: re-verifies signature, envelope, and staged files before marking state `UPDATE_PENDING`.
   - Rejects anti-downgrade and same-sequence conflicts; cleans incomplete crash leftovers.
4. **Session Activity Guard (`SessionActivityGuard`)**:
   - Evaluates whether immediate update apply is safe.
   - If game process (`pso2.exe`) or proxy transition is active, immediate apply is blocked.
   - **Critical Invariant**: Updates NEVER forcibly terminate the game or active session.
5. **Safe Apply Execution Paths**:
   - **Explicit Update Action**: User-initiated update. If game is running, notifies user without killing game; if safe, initiates graceful shutdown and handoff.
   - **Normal Exit**: During Launcher shutdown, if a verified pending update exists and session is stopped, transitions to `NekoUpdater.exe`.
   - **Next-Launch Apply (`try_apply_pending_on_launch`)**: Early in startup (after acquiring singleton mutex, before creating UI window), evaluates verified pending updates and runs offline helper handoff.
6. **Updater Handoff Preservation**:
   - Reuses existing `NekoUpdater.exe` transactional engine, generation builder, probation runner, and rollback controller.
   - Handoff sends exact stored envelope to `BEGIN`, copies verified staged files to incoming paths, verifies hashes, and issues `APPLY`.

---

## 3. Non-Regression Contracts

The released line preserves all fundamental security and product invariants:

- **Fail-Closed Authorization**: External Core startup requires authenticating, single active session ownership, valid entitlement, and fresh launch permit verification.
- **External Core Topology**: NekoProxyCore remains external under `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe`.
- **Game Invariant**: Launcher close, update staging, and update deferral never kill `pso2.exe`.
- **Single-Instance Mutex**: `Local\NekoFamilyProxyLauncher` remains the cross-process single-instance boundary; no competing locks added.
- **Credential Isolation**: Client contains only publishable credentials (Supabase URL / anon key); no service keys or private signing keys.
- **Canonical Version Display**: Launcher window title bar is bound directly to `neko_launcher.__version__` (`NEKO FAMILY PROXY v<version>`).
- **Installer Core Authority**: Post-install verification parameters match build-approved authority dynamically.

---

## 4. Verification Evidence Summary

- **Launcher suite**: 2,533 passed, 3 skipped, 7 deselected on 2026-10-24 (local Python 3.14 venv). One environment-only failure remains: `test_release_workflow_github_assets.py::test_noncanonical_repository_is_rejected_before_first_release_api` requires PowerShell 7 (`pwsh`), which is not installed on this host.
- **Repository safety**: PASS on 2026-10-24 (`scripts/check_repository_safety.py`).
- **Ruff and CI**: `ruff check src tests` PASS; CI enforces the same gate in `.github/workflows/ci.yml`.
- **Git diff**: `git diff --check` PASSED with clean formatting and no whitespace defects.
