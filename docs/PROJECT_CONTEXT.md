# Project Context — Neko Family Proxy Launcher

Updated: 2026-09-12 (Neko Family 5.1.2 Architecture)

## Purpose
This repository is the Windows Launcher/client tier for Neko Family Proxy. It owns user-facing launch/session orchestration, authentication/permit flow integration, installer/updater code, release-controller automation, Supabase client/backend contracts, and the planned permanent machine-update channel for existing clients under the 5.1.2 architecture.

## Architecture Evolution (Neko Family 5.1.2 Feature Branch Implementation)

### 1. Two-Repository Role Inversion
- **Machine-Update Channel**: `Valeneko-pranmong/Neko-Family-Proxy` (this repository) is planned as the permanent machine-update channel because legacy and dormant clients discover updates at `Valeneko-pranmong/Neko-Family-Proxy/releases/latest`. Releases on this channel publish four signed machine assets:
  - `release-v2.json`
  - `NekoLauncher.exe`
  - `NekoUpdater.exe`
  - `NekoProxyCore.zip`
- **Dedicated Installer Surface**: Standalone customer setup executables are planned to relocate to a separate installer repository (e.g. `Valeneko-pranmong/Neko-Family-Proxy-Installer`).

### 2. Deferred Update Lifecycle
- **Every-Open Discovery**: Launcher checks for newer releases in the background on startup.
- **Background Staging (`SoftwareUpdateStageService`)**: Changed product components download in the background without session interruption.
- **Durable Pending Store (`PendingUpdateStore`)**: Fully staged updates are atomically stored under `%LOCALAPPDATA%\NEKO FAMILY\update-pending\` and re-verified offline on every load before entering `UPDATE_PENDING` state.
- **Session Activity Guard (`SessionActivityGuard`)**: Evaluates safety before applying; never terminates the game (`pso2.exe`) or active proxy transitions.
- **Safe Apply Paths**: Updates apply safely via explicit Update action, normal Launcher exit, or early next-launch offline bootstrap (`try_apply_pending_on_launch`).
- **Updater Engine Reuse**: Handoff uses existing `NekoUpdater.exe` transactional, generation, probation, and rollback machinery.

### 3. Bounded Bootstrap Authority Override
- Because public `v5.1.0` was released installer-only without machine assets, `scripts/release_controller.py` implements a bounded bootstrap authority override for `v5.1.0` using the archived Attempt-3 signed manifest and Core payload.
- Strictly validated against production Ed25519 signature, channel, size, hash, and installed identity.
- Restricted solely to bootstrap `v5.1.0` and auto-disabled once a newer machine release exists.

## Current Baseline
- Historical/Current Production Release: `v5.1.0` (Release ID `387113854`, commit `0b71f03ee4ed69176da2682fdd1cfb4e5cce971c`). Public v5.1.0 remains strictly installer-only.
- Active Feature Branch: `feature/neko-family-5.1.2`
- Base Commit: `ed82b885138015e194bbf45db61a7d6899640156` (`origin/main`)
- Readiness & Production Scope: Implemented and tested on `feature/neko-family-5.1.2` and pending R10, Main Source Acceptance, merge to `main`, and future release engineering gates. In-app automatic updates are NOT yet available for production users, the architecture is not yet declared production-ready, and no production backend or release mutation has occurred. The dedicated installer repository and public machine assets do not exist publicly yet.

## Related Projects
- `E:\Github\NekoProxyCore` — low-level Core/driver/runtime used by the Launcher.
- `E:\Github\Neko-Family-Proxy-admin-tool` — operator Control Room / web admin.
- `E:\Github\Neko-Core AWS` — production server/infrastructure workspace.
- `E:\Github\Project manager` — cross-project authority, handoff, and history.

## Security / Release Boundaries
- Client code must not contain service-role/admin secrets.
- Do not read, print, copy, or export production signing private-key bytes.
- Local branch acceptance must not claim release completion or perform production mutations.
- Exact SHA/run-id/idempotency and independent review gates remain release invariants.

## Validation Entry Points
- Repository safety: `launcher/.venv/Scripts/python.exe scripts/check_repository_safety.py`
- Launcher lint/tests: `launcher/.venv/Scripts/ruff.exe check src tests` and `launcher/.venv/Scripts/pytest.exe -p no:cacheprovider -q --tb=short`
- Release-controller tests: `launcher/tests/test_release_controller_bootstrap.py`
- Deferred E2E tests: `launcher/tests/e2e/test_deferred_pending_update_e2e.py`

## Read Next
1. `docs/README.md`
2. `docs/HANDOFF.md`
3. `docs/superpowers/specs/2026-09-12-neko-family-5-1-2-update-architecture.md`
4. `docs/superpowers/plans/2026-09-12-neko-family-5-1-2-implementation.md`
5. `E:\Github\Project manager\current\CONTROLLER_LEDGER_NEKO_FAMILY_5_1_2.md`
