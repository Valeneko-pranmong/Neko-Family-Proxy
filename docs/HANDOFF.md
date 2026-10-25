# Handoff — Neko Family Proxy Launcher

Updated: 2026-10-25 (Neko Family 5.2.0 Release Line)

## Current state
- Current release line: `v5.2.0` (source; hosted publication pending). `v5.1.6` remains the last published stable until 5.2.0 is released.
- Active branch: `main`.
- Distribution Architecture: unified canonical releases on `Valeneko-pranmong/Neko-Family-Proxy`; the historical `Neko-Family-Proxy-Updates` identity is superseded.
- Trust Anchors: `neko-update-prod-2` and `neko-update-profile-v520-1`; the signed profile authorizes only the current release key. Historical public keys remain for verification. The old private key is unavailable.
- Upgrade Path: 5.1.6 and 5.2.0 are separate lines. 5.1.6 remains public stable on its legacy password/recovery backend. 5.2.0 is a new-accounts-only web-auth preview using an isolated schema in the same Supabase project; it cannot auto-update 5.1.6, must not be installed over it, and requires a full 5.1.6 uninstall first. Local state is a clean start. There is no side-by-side support. 5.2.0 uses a dedicated preview channel. There is no day/coupon transfer; 5.3.0 is the planned legacy cutover and its shutdown is gate-based, waiting for the last active legacy term or an explicit cutoff.
- Deferred Update Lifecycle (released since 5.1.2, extended through 5.2.0):
  - Background staging (`SoftwareUpdateStageService`) downloads changed components while sessions remain active.
  - Durable pending store (`PendingUpdateStore`) verifies signed envelopes and reconstructs trust offline.
  - Session activity guard (`SessionActivityGuard`) guarantees updates never forcibly terminate game (`pso2.exe`) or proxy sessions.
  - Safe apply pathways: explicit Update action, normal exit, and next-launch offline bootstrap (`try_apply_pending_on_launch`).
  - Reuses the existing `NekoUpdater.exe` transactional engine, probation runner, rollback, and anti-downgrade machinery.
- v5.1.6 additions: startup update-check splash, in-app update progress dialog, windowless updater helper, committed-generation self-sync, Settings version check, and baseline enrollment from a working-directory install root.
- v5.2.0 additions: refreshed launcher/auth/dashboard/Settings presentation; atomic self-sync; buffered support/debug logging; one-shot startup update check; installer driver-path pinning; permit-issuance rate limiting; pinned CI actions; release/profile authority rotation; Launcher-side browser/Discord PKCE loopback flow (hidden behind `NEKO_WEB_AUTH_ENABLED` + `NEKO_AUTH_BRIDGE_URL`). The 2026-10-25 decision makes 5.2.0 a separate web-auth-only line: password/recovery must be removed from 5.2.0, while 5.1.6 keeps them until 5.3.0. Core `54365f2` adds bounded 10-minute permit clock-skew tolerance with fresh-challenge authority; managed Core suite 344/344.
- Release workflow: `.github/workflows/release.yml` validates `release_tag` against `launcher/pyproject.toml` at `expected_target`, not a hardcoded version.
- Release controller: `scripts/release_controller.py` resolves the release version from the exact semver tag at the accepted commit, falling back to the declared `launcher/pyproject.toml` and `__init__.py` versions. For an untagged release, bump both declared versions before running the controller; an exact tag must match them. `release_target.json` is armed at `v5.1.6` → `v5.2.0`; the parser accepts a single patch increment or a `.0` minor release.
- Installer driver registration pins the Core manifest, `Redirector.bin`, and `nfdriver.sys`, verifies every declared driver DLL, and loads the redirector from an admin-only staging directory. The helper script itself still runs from the per-user app directory; a signed helper in an admin-only location is the remaining hardening step.
- Permit issuance is rate-limited per user at 10 attempts per 60 seconds. Apply `supabase/migrations/20261024120000_permit_rate_limit.sql` before deploying the matching Edge Function; a missing RPC fails closed with 503.
- Code signing is still pending a Windows Authenticode certificate. Launcher, Updater, and Installer remain unsigned.

## User-facing readiness
- `v5.1.6` remains the last published stable and must keep working on its legacy backend throughout 5.2.0 development.
- The earlier 5.2.0 candidate was built before the web-auth and Core clock changes; it is superseded and must be rebuilt before any publication.
- 5.2.0 is a separate web-auth preview: no automatic update from 5.1.6, no in-place install, no side-by-side installation. Users who want 5.2.0 must uninstall 5.1.6 first. The installer guard for this is not implemented yet.
- Web auth is implemented Launcher-side but disabled by default. Do not enable the Discord button or publish 5.2.0 until the proxy bridge, identity→proxy mapping, one-time link/claim flow, staging test accounts, E2E, password/recovery removal, and installer separation pass.
- The manual release workflow is unlocked for any tag that matches the checked-out launcher version, subject to its existing immutable-ID, SHA, asset, and hosted-verification gates.

## Next work
1. P0 is complete. P1 slices 1–2 landed: `launcher_v2` profiles, identity links, web-session allowlist, profile routing, entitlement/session tables, claim/heartbeat/release/permit RPCs, and contract tests. Next: the bridge and staging E2E.
2. Re-check the shared-auth consumer inventory before disabling legacy auth at cutover; add any new consumer.
3. Installer guard source is implemented in `installer/beta.iss`; rebuild with ISCC and run the install/uninstall matrix with 5.1.6 installed/running and 5.2.0 reinstall.
4. The reference bridge is implemented in `supabase/functions/launcher_bridge/`; deploy it using `docs/current/launcher-bridge-staging-runbook.md`, provision staging test accounts/entitlement, run the full E2E, and validate Auth `session_id` stability across refresh.
5. P2 is complete for the product path: next-line schema selection, server-metadata permit routing, web-only UI, frozen-build enforcement, no recovery view/gateway in web-only mode, and service-layer rejection of password/recovery. Source/dev legacy methods remain only for the non-frozen reference path and are scheduled for 5.3.0 deletion.
6. Run full web-auth E2E, build the 5.2.0 preview with the new Core bundle, refresh all hashes, and distribute it through the dedicated preview channel, not latest stable. Publisher guard, preview-profile release-list discovery, and the signed preview profile are in place; preview publication, auto-apply, and feed E2E remain.
7. Complete Control Room admin web auth and the 5.3.0 no-transfer expiry/coupon-notice plan; then prepare the 5.3.0 stable cutover and legacy schema/auth retirement.
8. Back up the new release and profile-authority custody keys to an external, access-controlled medium.
9. Apply the permit rate-limit migration and deploy the matching Edge Function.
10. Procure a Windows Authenticode certificate and wire signing into the release pipeline.
11. Review hosted Supabase/Edge deployment docs against production state.

Core pipe isolation is complete in `ab3b08c`; the bounded permit clock-skew fix is in Core `54365f2` (local commit, not pushed). A future image-path check remains optional defense in depth.

## Do not accidentally change
- Do not mutate or replace published `v5.1.6` release assets.
- Do not reuse the `neko-update-prod-1` key ID with new key bytes; existing clients verify it against the historical public key.
- Do not force 5.1.6 users onto 5.2.0; 5.1.6 must remain usable on its legacy backend during 5.2.0 development.
- Do not publish 5.2.0 as the latest stable or as an auto-update for 5.1.6. Use the approved separate preview/manual path.
- Do not allow 5.2.0 to be installed over or alongside 5.1.6. The uninstall/process guard is mandatory.
- Do not publish 5.2.0 until it is rebuilt with the web-auth/Core-clock source, web-only password removal, the installer guard, E2E, and `neko-update-prod-2` trust/profile verification.
- Do not keep password/recovery fallback in 5.2.0; those paths belong only to 5.1.6 until the 5.3.0 cutover.
- Do not bypass the workflow's canonical-repository, immutable release-ID, expected-target, signed-envelope, or asset-verification gates.
- Do not bypass fail-closed cryptographic verification of the signed manifest or component digests.
- Do not modify `launcher/tests/test_config.py` to hide pre-existing baseline asset defects.
- Do not expose signing private-key bytes or copy custody material into the repository.

## Authoritative reference documents
- Current status: `docs/current/README.md`
- Current architecture: `docs/current/launcher-architecture.md`
- Web auth status/contract: `docs/current/web-auth-launcher.md`
- 5.2.0 separation / 5.3.0 cutover plan: `docs/superpowers/plans/2026-10-25-web-auth-separation-and-5-3-0-cutover.md`
- 5.3.0 execution runbook: `docs/current/5.3.0-cutover-runbook.md`
- Update architecture (historical 5.1.2 design): `docs/superpowers/specs/2026-09-12-neko-family-5-1-2-update-architecture.md`
- Implementation plan (historical 5.1.2): `docs/superpowers/plans/2026-09-12-neko-family-5-1-2-implementation.md`
- Controller ledger (historical 5.1.2): `E:\Github\Project manager\current\CONTROLLER_LEDGER_NEKO_FAMILY_5_1_2.md`
- Accepted v5.1.0 archive (historical bootstrap): `E:\Github\artifacts\v5.1.0-clean-candidate\attempt-3\`

## First checks for a new maintainer
1. `git status --short --branch`
2. `git rev-parse HEAD` and `git rev-parse origin/main`
3. `launcher/.venv/Scripts/python.exe -B scripts/check_repository_safety.py`
4. `cd launcher && .venv/Scripts/ruff.exe check src tests`
5. `cd launcher && .venv/Scripts/pytest.exe -p no:cacheprovider -q --tb=short`
