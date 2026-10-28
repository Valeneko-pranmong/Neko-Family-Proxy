# NEKO FAMILY PROXY — Current Component Status & 5.2.0 Release Line

```text
DOCUMENT:                       docs/current/README.md
STATUS:                         5.2.3 FIXED MANUAL NON-LATEST (RE-RELEASE); 5.2.4 CANCELED
PRODUCT_BASELINE:               5.2.2 remains public stable; 5.2.3 fixed is the manual migration target; 5.1.6 remains the legacy line
SOURCE_5_2_2_PREP:              historical; 5.2.2 stable was published on 2026-10-28
ALPHA_BUILD_5_2_2A:             historical; superseded by the published 5.2.2 stable
CURRENT_RELEASE_TAG:            v5.2.3 (fixed re-release, non-latest manual, stable-0028 seq 28); v5.2.4 canceled
LAST_PUBLIC_STABLE:             v5.2.2 (releases/latest); v5.2.3 fixed manual non-latest until migration completes
INSTALLER_CANDIDATE:            NekoFamilyProxy-Installer.exe 5.2.3, unsigned (SHA-256 7a2683ced330bc0e73e72a1611aef44e2c710ca32b05f037e4fe50a584bc3d2b)
ACTIVE_DEV_BRANCH:              main
RELEASE_CHANNEL:                STABLE (5.2.2 and later may publish stable)
DISTRIBUTION_ARCHITECTURE:      CANONICAL MAIN REPOSITORY (historical updates repo superseded)
UPDATE_LIFECYCLE:               5.2.2 UPDATER CANNOT VERIFY FROZEN CORE (CORE_INVENTORY_INVALID); 5.2.3 RE-RELEASE FIXES IT AND PINS UPDATER d7d59cf4…; MANUAL CLEAN INSTALL REQUIRED
UPDATE_TRUST_ANCHOR:            neko-update-prod-3 / neko-update-profile-v520-2
RELEASE_SEPARATION:             5.1.6 LEGACY / 5.2.x UNIFIED; CLEAN UNINSTALL-FIRST; NO SIDE-BY-SIDE
UPGRADE_PATH_5_1_6:             NO IN-PLACE UPGRADE; UNINSTALL 5.1.6 BEFORE 5.2.x; NO LEGACY ACCOUNT/DAY/COUPON TRANSFER
WEB_AUTH_LAUNCHER:              5.2.3 SIGNS IN PENDING ACCOUNTS AND REDEEMS COUPONS THROUGH THE PROXY API; LIVE DISCORD LOGIN VERIFICATION PENDING
PROXY_API_DEPLOYMENT:           PRODUCTION + STAGING LIVE (neko-control-room deployed 5084eaa; self-service migration applied by owner)
STAGING_E2E:                    pending owner live login/coupon check
AUTH_FLOW:                      PASS (fail-closed identity refresh + single-session arbitration in source)
PROXY_FLOW:                     PASS (Runtime Config v1 + Core pipe supervision in source)
SESSION_GUARD_INVARIANT:        PASS (no forced game/proxy termination on update)
NEXT_LAUNCH_APPLY:              PASS (offline verified bootstrap before window creation)
BOOTSTRAP_AUTHORITY:            PASS (bounded v5.1.0 signed archive override; historical bootstrap)
LAUNCHER_TITLE_BINDING:         PASS (bound to canonical neko_launcher.__version__)
INSTALLER_CORE_AUTHORITY:       PASS (dynamic build authority propagation via ISCC)
REPOSITORY_SAFETY:              PASS (scripts/check_repository_safety.py, 2026-10-28)
TEST_SUITE:                     2,852 passed / 6 skipped / 7 deselected (launcher, 2026-10-28)
RELEASE_RUNBOOK:                docs/current/5.2.2-build-runbook.md
PATCH_RUNBOOK:                  docs/current/5.2.x-patch-runbook.md
RELEASE_NOTES:                  docs/current/5.2.3-release-notes.md
PREPARATION_RECORD:             docs/current/5.2.0-release-preparation-record.md
PREPARATION_RECORD_5_2_2:       docs/current/5.2.2-preparation-record.md
ALPHA_BUILD_RECORD_5_2_2A:      docs/current/5.2.2a-alpha-build.md
LEGACY_RETIREMENT:              future; 5.3.0 is not a release label (see 5.3.0-cutover-runbook.md)
LAST_VERIFIED:                  2026-10-28 21:06 +07:00 (Asia/Bangkok)
```

> **2026-10-26 5.2.1 patch overlay:** 5.2.1 is a launcher/UI patch on the
> 5.2.0 line. Core, the external Core bundle, the preview trust profile, the
> staging origins, and the Proxy API contract are unchanged. The envelope is
> `preview-0016` (sequence 16, `minimum_supported_sequence = 16`), signed by
> `neko-update-prod-3`. Later 5.2.x releases must set
> `minimum_supported_sequence` to their own sequence so 5.2.1 installations are
> forced to update on the next Launcher start; the running game/proxy session is
> never force-closed. See [5.2.1-release-notes.md](5.2.1-release-notes.md).
>
> **2026-10-26 5.2.2 source preparation:** the release branch now contains
> structured support diagnostics, a centered login layout with a pinned top
> status row and a non-shifting pending panel, one-frame Settings rendering, and
> a startup splash that waits for session restore. The last change removes the
> 2–4 second login-screen flash that made users think their session had been
> lost. These are source-only commits `81f8c8b` and `72270c7`; the installed
> 5.2.1 artifacts do not include them, and no 5.2.2 build, tag, or publication
> exists. See [5.2.2-preparation-record.md](5.2.2-preparation-record.md).

> **2026-10-25 unified-platform overlay:** the first usable release of the
> unified line is **5.2.0** on the preview/manual channel. The new line uses
> Neko-NETWORK-ID access/refresh tokens and Neko Proxy API only. P1 slices 1–2
> (source/dev `NEKO_PROXY_API_URL`) implement the account-status preflight,
> refresh-token storage, claim/heartbeat/release, and the permit + Runtime
> Config v1 Core path without a bridge or Supabase session. See
> [5.2.0-release-notes.md](5.2.0-release-notes.md),
> [5.2.0-release-runbook.md](5.2.0-release-runbook.md), and
> [proxy-api-launcher-contract.md](proxy-api-launcher-contract.md). The
> bridge/session-minting and web-session allowlist parts of the older plan are
> superseded for the new line; `5.1.6` remains unchanged.
>
> **Current-state rule:** `feat/proxy-api-launcher-clean-v2` is the release
> preparation branch. `v5.1.6` remains the last published stable and must stay
> usable on its legacy password/recovery backend throughout 5.2.0 development.
> 5.2.0 is a preview/manual release with a clean uninstall-first install: there
> is no legacy day/coupon transfer, 5.1.6 remains usable until its existing
> term expires or an approved cutoff, 5.2.0 must not be published as the latest
> stable, must not auto-update 5.1.6, and must not be installed over or
> alongside 5.1.6. The installer guard is implemented in source (same AppId,
> running-process and installed-version checks); the rebuilt installer/install
> matrix, frozen release configuration, staging deployment, and E2E are still
> pending. The 5.1.2 architecture described below remains the foundation of the
> deferred update lifecycle; it has been shipped and extended through
> 5.1.3–5.1.6. This document describes repository state, not a hosted-backend
> deployment audit.
>
> **Release-label rule:** `5.3.0` is not a release label. The 5.3.0 documents
> are retained as historical/legacy-retirement material only.

---

## 1. What is the current architecture doing?

The 5.1.2 architecture introduced the **Deferred Update Lifecycle** and the **Production Updates & Canonical Main Repository Topology** (Revision 3.4). Later patch releases extended it without changing the fail-closed authorization model:

### 1.1 Repository Roles & Distribution Topology
- **Canonical Repository**: `Valeneko-pranmong/Neko-Family-Proxy` is the active machine-update channel and the human-facing release surface. The historical `Valeneko-pranmong/Neko-Family-Proxy-Updates` identity is superseded and is rejected by the updater trust profile.
- **Machine Assets**: Every machine release publishes four canonical signed assets:
  1. `release-v2.json` (canonical Ed25519-signed manifest)
  2. `NekoLauncher.exe`
  3. `NekoUpdater.exe`
  4. `NekoProxyCore.zip`
- **Human-Facing Installer Surface**: Standalone installer executables (`NekoFamilyProxy-Installer.exe`) are distributed from canonical repository releases (`Valeneko-pranmong/Neko-Family-Proxy/releases`).

### 1.2 Bounded Bootstrap Authority Override (Historical)
- Public `v5.1.0` was released installer-only and lacked public machine assets (`release-v2.json`, `NekoProxyCore.zip`, etc.).
- To establish the first machine release, `scripts/release_controller.py` implemented a strictly bounded bootstrap authority override:
  - Scoped exclusively to bootstrap Stable `v5.1.0`.
  - Consumed the byte-for-byte archived Attempt-3 signed manifest and Core bundle.
  - Verified production Ed25519 signature, channel, Core hash, size, canonical manifest, and installed identity.
  - Automatically refused for newer versions or arbitrary local files.
  - Disabled once a newer accepted machine release existed on GitHub.
- The bootstrap path is retained for traceability; it is not the release path for the current line.

### 1.3 Release Line 5.1.3–5.2.2 (source)
- **v5.1.3**: installed-file integrity check and repair in Settings; update-notification and Settings-focus refinements; clean uninstall/state cleanup; machine credential provisioned during baseline enrollment.
- **v5.1.4**: 64-bit WOW64 redirection guard in the elevated driver installer and non-BOM ASCII installer logging.
- **v5.1.5**: native `ensure-netfilter2.cmd` Sysnative dispatcher and Inno Setup result-file polling guard.
- **v5.1.6**: startup update-check splash before the main window; in-app update progress dialog; windowless updater helper; committed-generation self-sync; Settings version check; baseline enrollment from a working-directory install root.
- **v5.2.0 (unified-line release target, preview)**: refreshed launcher/auth/dashboard/Settings presentation; atomic self-sync and buffered logging; installer driver-path pinning; permit-issuance rate limiting; CI action pinning; release/profile authority rotation. The new line uses Neko-NETWORK-ID and Neko Proxy API only; 5.1.6 remains on the legacy line and must be uninstalled before a clean 5.2.0 installation. See [5.2.0-release-notes.md](5.2.0-release-notes.md) and [5.2.0-release-runbook.md](5.2.0-release-runbook.md).
- **v5.2.1 (preview/manual; built and installed, not published)**: login copy and Discord icon, login-endpoint pre-warm, fixed 500×640 window, one-frame Settings render, and an uninstall-time process guard. Envelope `preview-0016`, sequence 16, `minimum_supported_sequence = 16`. See [5.2.1-release-notes.md](5.2.1-release-notes.md).
- **v5.2.2 (source preparation)**: schema-2 support diagnostics with privacy-safe auth/restore timing, pinned-status centered login layout with a floating pending panel, and a startup splash that waits for session restore so auto-login does not flash the login screen. See [5.2.2-preparation-record.md](5.2.2-preparation-record.md).
- **v5.2.2a (local alpha build; not published)**: the 5.2.2 preparation changes re-versioned to `5.2.2a`, built with Python 3.12/Tk 8.6, and signed into `preview-0023` (sequence 23, `minimum_supported_sequence = 23`). Installer `17458568…` (201,007,176 bytes, unsigned); launcher `1837c270…` (21,629,808 bytes); updater `c3411b95…` (11,281,237 bytes). Revision 6 is the final rebuild of the code-review/hardening pass: update evidence pruning, streaming Core hashes, 900 s apply deadline, in-memory verified elevated driver script, scratch cleanup on uninstall, trimmed frozen builds, and UI robustness fixes. Sequences 17–22 were consumed by the b17 test build and revisions 1–5. See [5.2.2a-alpha-build.md](5.2.2a-alpha-build.md).

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
- **Credential Isolation**: 5.1.6 contains only publishable Supabase credentials (URL / anon key); the 5.2.0 new line contains no Supabase URL, key, session, or proxy database credential. Neither line contains service keys or private signing keys.
- **Canonical Version Display**: Launcher window title bar is bound directly to `neko_launcher.__version__` (`NEKO FAMILY PROXY v<version>`).
- **Installer Core Authority**: Post-install verification parameters match build-approved authority dynamically.

---

## 4. Verification Evidence Summary

- **Launcher suite**: 2,809 passed, 5 skipped, 7 deselected on 2026-10-26 (source). This includes the `launcher_v2` auth-foundation, claim/permit, bridge-support, staging-runbook, installer-separation, next-line schema-selection, web-only/frozen-build, preview-channel, and feed-isolation tests, plus the 5.2.2 support-diagnostics and startup splash/session-restore tests; the PowerShell-dependent test remains environment-skipped when `pwsh` is unavailable.
- **Repository safety**: PASS on 2026-10-26 (`scripts/check_repository_safety.py`).
- **Ruff and CI**: `ruff check src tests` PASS; CI enforces the same gate in `.github/workflows/ci.yml`.
- **Git diff**: `git diff --check` PASSED with clean formatting and no whitespace defects.
- **Edge permit service**: 31 Node tests PASS, including rate-limit 429 and fail-closed 503 paths.
- **Installer driver registration**: 30 builder/PowerShell tests PASS, including pinned hash mismatch and secure-stage checks.
- **Core pipe isolation**: NekoProxyCore `ab3b08c` uses `PipeOptions.CurrentUserOnly` plus exact Launcher-PID binding for both control and telemetry pipes. Core `54365f2` adds the bounded 10-minute permit clock-skew tolerance with fresh-challenge authority; managed Core suite 344/344.
- **Pending gate**: Authenticode signing requires an operator certificate.
