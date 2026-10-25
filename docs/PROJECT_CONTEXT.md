# Project Context — Neko Family Proxy Launcher

Updated: 2026-10-25 (Neko Family 5.1.6 stable + 5.2.0 web-auth preview planning)

## Purpose
This repository is the Windows Launcher/client tier for Neko Family Proxy. It owns user-facing launch/session orchestration, authentication/permit flow integration, installer/updater code, release-controller automation, Supabase client/backend contracts, and the canonical machine-update channel for existing clients. The deferred update lifecycle introduced in 5.1.2 is shipped and maintained on the 5.1.6 stable line; 5.2.0 is a separate web-auth-only preview line.

## Architecture Evolution (5.1.2+ Released Architecture)

### 1. Repository Roles & Distribution Topology
- **Canonical Release Surface**: `Valeneko-pranmong/Neko-Family-Proxy` serves both automated machine updates and human installer downloads. Releases publish the unified signed assets:
  - `release-v2.json`
  - `NekoLauncher.exe`
  - `NekoUpdater.exe`
  - `NekoProxyCore.zip`
  - `NekoFamilyProxy-Installer.exe`
- **Superseded identity**: `Valeneko-pranmong/Neko-Family-Proxy-Updates` is rejected by the production updater trust profile. Historical separate updates/installer repositories are not active distribution surfaces.

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
- Current Public Stable: `v5.1.6` on the legacy password/recovery backend. `v5.2.0` is a new-accounts-only web-auth preview using an isolated schema in the same Supabase project. It is not published and must not become the latest stable while 5.1.6 is supported; it uses a dedicated preview channel.
- Active Branch: `main`.
- Distribution: unified canonical releases on `Valeneko-pranmong/Neko-Family-Proxy`; the former updates-repository identity is superseded.
- Trust Anchors: release key `neko-update-prod-2` and profile authority `neko-update-profile-v520-1`. The signed profile authorizes only the current release key. New private custody material was generated on 2026-10-24; the historical `neko-update-prod-1` private key is unavailable.
- Upgrade Path: 5.1.6 and 5.2.0 are separate lines. 5.1.6 cannot auto-update to 5.2.0 and must remain usable during 5.2.0 development. A user who wants 5.2.0 must uninstall 5.1.6 first; in-place and side-by-side installation are unsupported. Local state is a clean start. 5.2.0 is new-accounts-only; legacy 5.1.6 account/entitlement migration is a 5.3.0 gate. The installer guard is pending.
- Update Lifecycle: background staging, durable pending storage, session guard, and offline apply are released and active.
- Release Automation: `.github/workflows/release.yml` is the manual publication gate. `scripts/release_controller.py` resolves the version from the exact commit tag or the declared `launcher/pyproject.toml` / `__init__.py`; bump both declared versions before an untagged release. `release_target.json` is armed at `v5.1.6` → `v5.2.0`; the intent parser accepts a single patch increment or a `.0` minor release. Staging, custody key, trust-profile, and bootstrapper paths come from environment variables with LocalAppData defaults; no personal paths remain.
- Driver Registration Hardening: the installer pins the Core manifest, `Redirector.bin`, and `nfdriver.sys`; the elevated helper verifies them and loads declared DLLs from an admin-only `%ProgramData%` staging directory.
- Permit Rate Limit: `issue_launch_permit` consumes a per-user attempt before authorization (10 per 60 seconds) and returns HTTP 429 when exhausted. The migration must be applied before the function deployment.
- Core Pipe Isolation: NekoProxyCore commit `ab3b08c` keeps `PipeOptions.CurrentUserOnly` on both control and telemetry pipes and binds both to the exact Launcher PID; an image-path check remains optional defense in depth.
- Core Clock Skew: NekoProxyCore commit `54365f2` tolerates a bounded 10-minute wall-clock disagreement only while a fresh one-use challenge remains the freshness authority; healthy clocks keep exact 2s/30s checks. Managed suite 344/344. Not pushed.
- Web Auth: Launcher-side browser/Discord PKCE loopback + identity token + bridge adapter is implemented behind `NEKO_WEB_AUTH_ENABLED` and a required `NEKO_AUTH_BRIDGE_URL`. The 5.1.6 legacy line keeps password/recovery; 5.2.0 is the new-accounts-only web-auth target and must remove them. The proxy bridge, isolated-schema identity links, new-account link/claim flow, web-session allowlist, staging test accounts, installer separation, and E2E are still pending.
- Pending Security Gates: Authenticode code signing requires an operator certificate. External backup of the new release/profile-authority custody keys is still required. Do not publish the stale pre-web-auth 5.2.0 candidate.

## Related Projects
- NekoProxyCore — separate low-level Core/driver/runtime repository used by the Launcher; pipe isolation `ab3b08c`, bounded clock-skew fix `54365f2` (local, not pushed).
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
