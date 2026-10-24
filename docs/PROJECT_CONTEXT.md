# Project Context — Neko Family Proxy Launcher

Updated: 2026-10-24 (Neko Family 5.1.6 Release Line)

## Purpose
This repository is the Windows Launcher/client tier for Neko Family Proxy. It owns user-facing launch/session orchestration, authentication/permit flow integration, installer/updater code, release-controller automation, Supabase client/backend contracts, and the permanent machine-update channel for existing clients. The deferred update lifecycle introduced in 5.1.2 is shipped and maintained on the 5.1.6 line.

## Architecture Evolution (5.1.2+ Released Architecture)

### 1. Repository Roles & Distribution Topology (Revision 3.4)
- **Machine-Update Channel**: `Valeneko-pranmong/Neko-Family-Proxy-Updates` serves as the permanent production machine-update channel. Releases on this channel publish four signed machine assets:
  - `release-v2.json`
  - `NekoLauncher.exe`
  - `NekoUpdater.exe`
  - `NekoProxyCore.zip`
  *Note: Normal users must not be linked to the machine repository as a download surface.*
- **Human Installer Surface**: `Valeneko-pranmong/Neko-Family-Proxy` (this repository) serves as the official human release surface for standalone installer executables (`NekoFamilyProxy-Installer.exe`). Any historical separate installer repository is retired.

### 2. Deferred Update Lifecycle
- **Every-Open Discovery**: Launcher checks for newer releases in the background on startup.
- **Background Staging (`SoftwareUpdateStageService`)**: Changed product components download in the background without session interruption.
- **Durable Pending Store (`PendingUpdateStore`)**: Fully staged updates are atomically stored under `%LOCALAPPDATA%\NEKO FAMILY\update-pending\` and re-verified offline on every load before entering `UPDATE_PENDING` state.
- **Session Activity Guard (`SessionActivityGuard`)**: Evaluates safety before applying; never terminates the game (`pso2.exe`) or active proxy transitions.
- **Safe Apply Paths**: Updates apply safely via explicit Update action, normal Launcher exit, or early next-launch offline bootstrap (`try_apply_pending_on_launch`).
- **Updater Engine Reuse**: Handoff uses existing `NekoUpdater.exe` transactional, generation, probation, and rollback machinery.

### 3. Bounded Bootstrap Authority Override (Historical)
- Because public `v5.1.0` was released installer-only without machine assets, `scripts/release_controller.py` implements a bounded bootstrap authority override for `v5.1.0` using the archived Attempt-3 signed manifest and Core payload.
- Strictly validated against production Ed25519 signature, channel, size, hash, and installed identity.
- Restricted solely to bootstrap `v5.1.0` and auto-disabled once a newer machine release exists.

## Current Baseline
- Current Stable Release: `v5.1.6` (tag `01d5331`, released 2026-09-21). `main` is two commits ahead for merge/test cleanup (`616ff89`).
- Active Branch: `main`.
- Distribution: Two-Repo Role Inversion is active. `Valeneko-pranmong/Neko-Family-Proxy-Updates` carries machine assets; `Valeneko-pranmong/Neko-Family-Proxy` carries the human installer and source.
- Update Lifecycle: background staging, durable pending storage, session guard, and offline apply are released and active.
- Release Automation: `.github/workflows/release.yml` is the manual publication gate. `scripts/release_controller.py` still contains v5.1.2-specific bootstrap/version checks and must be generalized before it can drive a new release line.
- Repository Status (2026-10-24, at review start): `main` clean and synced with `origin/main`; repository safety check PASS.

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
1. `docs/current/README.md` — current release-line status
2. `docs/HANDOFF.md`
3. `docs/current/launcher-architecture.md`
4. `docs/superpowers/specs/2026-09-12-neko-family-5-1-2-update-architecture.md` (historical architecture)
5. `E:\Github\Project manager\current\CONTROLLER_LEDGER_NEKO_FAMILY_5_1_2.md` (historical ledger)
