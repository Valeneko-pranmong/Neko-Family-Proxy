# NEKO FAMILY PROXY — Current Component Status & 5.1.2 Architecture

```text
DOCUMENT:                       docs/current/README.md
STATUS:                         FEATURE BRANCH ACCEPTANCE (5.1.2) / PENDING R10 & RELEASE GATES
PRODUCT_BASELINE:               5.1.2 DEFERRED UPDATE ARCHITECTURE (BRANCH SCOPE)
ACTIVE_DEV_BRANCH:              feature/neko-family-5.1.2
BASE_COMMIT:                    ed82b885138015e194bbf45db61a7d6899640156 (origin/main)
DISTRIBUTION_ARCHITECTURE:      TWO-REPO ROLE INVERSION (PLANNED / BRANCH IMPLEMENTATION)
UPDATE_LIFECYCLE:               BACKGROUND STAGE -> DURABLE PENDING -> DEFERRED OFFLINE APPLY
AUTH_FLOW:                      PASS (Fail-closed Lite auth + single-session arbitration)
PROXY_FLOW:                     PASS (Runtime Config v1 + Core pipe supervision)
SESSION_GUARD_INVARIANT:        PASS (Zero forced game/proxy termination on update)
NEXT_LAUNCH_APPLY:              PASS (Offline verified bootstrap before window creation)
BOOTSTRAP_AUTHORITY:            PASS (Bounded v5.1.0 signed archive override; first-release only)
LAUNCHER_TITLE_BINDING:         PASS (Bound to canonical neko_launcher.__version__)
INSTALLER_CORE_AUTHORITY:       PASS (Dynamic build authority propagation via ISCC)
REPOSITORY_SAFETY:              PASS (scripts/check_repository_safety.py)
RUFF_LINT:                      PASS (0 errors, clean)
TEST_COVERAGE:                  1928 passed, 3 skipped, 7 deselected, 1 pre-existing baseline
LAST_VERIFIED:                  2026-09-12 +07:00 (Asia/Bangkok)
```

> **Current-state rule:** The active feature branch `feature/neko-family-5.1.2` contains the complete implementation and test coverage of the 5.1.2 Deferred Update Architecture. Public production remains v5.1.0 installer-only; the architecture is implemented and verified on this branch and awaits R10 review, Main Source Acceptance, merge to main, and subsequent release engineering gates before production availability. No production backend or release mutation has occurred. Frozen historical release evidence remains historical authority for the exact accepted artifacts only.

---

## 1. What is the 5.1.2 Architecture doing?

The Neko Family 5.1.2 feature branch implements the **Deferred Update Lifecycle** and **Two-Repo Role Inversion**, designed to restore automated in-app updates upon post-merge release:

### 1.1 Two-Repository Role Inversion
- **Machine-Update Channel**: The original repository `Valeneko-pranmong/Neko-Family-Proxy` is planned as the permanent machine-update channel. This ensures dormant and installed legacy clients (which discover updates via `Valeneko-pranmong/Neko-Family-Proxy/releases/latest`) continue to find valid signed releases.
- **Machine Assets**: Every machine release publishes four canonical signed assets:
  1. `release-v2.json` (canonical Ed25519-signed manifest)
  2. `NekoLauncher.exe`
  3. `NekoUpdater.exe`
  4. `NekoProxyCore.zip`
- **Human-Facing Installer Surface**: Planned to be separated into a dedicated installer repository (e.g. `Valeneko-pranmong/Neko-Family-Proxy-Installer`). It is a distribution surface for user setup executables, not a machine trust root. (Neither the separate repository nor machine update endpoints exist publicly yet; public release remains v5.1.0 installer-only.)

### 1.2 Bounded Bootstrap Authority Override
- Public `v5.1.0` was released installer-only and lacks public machine assets (`release-v2.json`, `NekoProxyCore.zip`, etc.).
- To establish the first new machine release, `scripts/release_controller.py` implements a strictly bounded bootstrap authority override:
  - Scoped exclusively to bootstrap Stable `v5.1.0`.
  - Consumes the byte-for-byte archived Attempt-3 signed manifest and Core bundle.
  - Verifies production Ed25519 signature, channel, Core hash, size, canonical manifest, and installed identity.
  - Automatically refused for newer versions or arbitrary local files.
  - Disabled once a newer accepted machine release exists on GitHub.

---

## 2. Deferred Update Lifecycle

The 5.1.2 client architecture guarantees that update operations never disrupt active user gameplay or proxy sessions:

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

The 5.1.2 branch preserves all fundamental security and product invariants:

- **Fail-Closed Authorization**: External Core startup requires authenticating, single active session ownership, valid entitlement, and fresh launch permit verification.
- **External Core Topology**: NekoProxyCore remains external under `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe`.
- **Game Invariant**: Launcher close, update staging, and update deferral never kill `pso2.exe`.
- **Single-Instance Mutex**: `Local\NekoFamilyProxyLauncher` remains the cross-process single-instance boundary; no competing locks added.
- **Credential Isolation**: Client contains only publishable credentials (Supabase URL / anon key); no service keys or private signing keys.
- **Canonical Version Display**: Launcher window title bar is bound directly to `neko_launcher.__version__` (`NEKO FAMILY PROXY v<version>`).
- **Installer Core Authority**: Post-install verification parameters match build-approved authority dynamically.

---

## 4. Verification Evidence Summary

- **Complete Launcher Suite**: 1,928 passed, 3 skipped, 7 deselected in `launcher/`.
  - *Note*: One pre-existing failure (`tests/test_config.py::test_application_root_resolves_to_repository_root_in_source_mode`) is proven pre-existing on canonical `main` due to repository file reorganization (`image_11.png` relocated to `Asset/`). It is retained as baseline evidence and not masked.
- **Ruff Code Inspection**: 0 errors / 0 warnings across all source and test modules.
- **Repository Safety**: `python scripts/check_repository_safety.py` PASSED with zero findings.
- **Git Diff**: `git diff --check` PASSED with clean formatting and no whitespace defects.
