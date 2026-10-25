# Handoff — Neko Family Proxy Launcher

Updated: 2026-10-25 (Neko Family 5.2.0 Release Line)

## Current state
- Current release line: `v5.2.0` (source; hosted publication pending). `v5.1.6` remains the last published stable until 5.2.0 is released.
- Active branch: `main`.
- Distribution Architecture: unified canonical releases on `Valeneko-pranmong/Neko-Family-Proxy`; the historical `Neko-Family-Proxy-Updates` identity is superseded.
- Trust Anchors: `neko-update-prod-2` and `neko-update-profile-v520-1`; the signed profile authorizes only the current release key. Historical public keys remain for verification. The old private key is unavailable.
- Upgrade Path: existing 5.1.6 installations cannot auto-update and must run the 5.2.0 installer manually; user data under `%LOCALAPPDATA%\NEKO FAMILY` is preserved.
- Deferred Update Lifecycle (released since 5.1.2, extended through 5.2.0):
  - Background staging (`SoftwareUpdateStageService`) downloads changed components while sessions remain active.
  - Durable pending store (`PendingUpdateStore`) verifies signed envelopes and reconstructs trust offline.
  - Session activity guard (`SessionActivityGuard`) guarantees updates never forcibly terminate game (`pso2.exe`) or proxy sessions.
  - Safe apply pathways: explicit Update action, normal exit, and next-launch offline bootstrap (`try_apply_pending_on_launch`).
  - Reuses the existing `NekoUpdater.exe` transactional engine, probation runner, rollback, and anti-downgrade machinery.
- v5.1.6 additions: startup update-check splash, in-app update progress dialog, windowless updater helper, committed-generation self-sync, Settings version check, and baseline enrollment from a working-directory install root.
- v5.2.0 additions: refreshed launcher/auth/dashboard/Settings presentation; atomic self-sync; buffered support/debug logging; one-shot startup update check; installer driver-path pinning; permit-issuance rate limiting; pinned CI actions; release/profile authority rotation and manual-upgrade documentation; Launcher-side browser/Discord PKCE loopback flow (hidden behind `NEKO_WEB_AUTH_ENABLED` + `NEKO_AUTH_BRIDGE_URL`). Core `54365f2` adds bounded 10-minute permit clock-skew tolerance with fresh-challenge authority; managed Core suite 344/344.
- Release workflow: `.github/workflows/release.yml` validates `release_tag` against `launcher/pyproject.toml` at `expected_target`, not a hardcoded version.
- Release controller: `scripts/release_controller.py` resolves the release version from the exact semver tag at the accepted commit, falling back to the declared `launcher/pyproject.toml` and `__init__.py` versions. For an untagged release, bump both declared versions before running the controller; an exact tag must match them. `release_target.json` is armed at `v5.1.6` → `v5.2.0`; the parser accepts a single patch increment or a `.0` minor release.
- Installer driver registration pins the Core manifest, `Redirector.bin`, and `nfdriver.sys`, verifies every declared driver DLL, and loads the redirector from an admin-only staging directory. The helper script itself still runs from the per-user app directory; a signed helper in an admin-only location is the remaining hardening step.
- Permit issuance is rate-limited per user at 10 attempts per 60 seconds. Apply `supabase/migrations/20261024120000_permit_rate_limit.sql` before deploying the matching Edge Function; a missing RPC fails closed with 503.
- Code signing is still pending a Windows Authenticode certificate. Launcher, Updater, and Installer remain unsigned.

## User-facing readiness
- `v5.1.6` remains the last published stable. The earlier 5.2.0 candidate was built before the web-auth and Core clock changes; it is now superseded and must be rebuilt before publication.
- 5.1.6 users must be told explicitly to install 5.2.0 manually; in-app automatic updates cannot bridge the trust-anchor rotation.
- Web auth is implemented Launcher-side but disabled by default. Do not enable the Discord button until the proxy bridge, identity→proxy mapping, one-time link/claim flow, staging test accounts, and E2E pass.
- The manual release workflow is unlocked for any tag that matches the checked-out launcher version, subject to its existing immutable-ID, SHA, asset, and hosted-verification gates.

## Next work
1. Back up the new release and profile-authority custody keys to an external, access-controlled medium.
2. Build the proxy bridge + `launcher.identity_links` mapping and the one-time link/claim flow; provide staging bridge/test accounts.
3. Run web-auth E2E and enable the Launcher flag for testing, then rebuild the 5.2.0 candidate with the new Core bundle and refresh all hashes.
4. Publish the verified candidate through the hosted release gate, then announce the manual upgrade path for 5.1.6 users.
5. Apply the permit rate-limit migration and deploy the matching Edge Function.
6. Procure a Windows Authenticode certificate and wire signing into the release pipeline.
7. Review hosted Supabase/Edge deployment docs against production state.

Core pipe isolation is complete in `ab3b08c`; the bounded permit clock-skew fix is in Core `54365f2` (local commit, not pushed). A future image-path check remains optional defense in depth.

## Do not accidentally change
- Do not mutate or replace published `v5.1.6` release assets.
- Do not reuse the `neko-update-prod-1` key ID with new key bytes; existing clients verify it against the historical public key.
- Do not publish 5.2.0 until the installer is rebuilt with the web-auth/Core-clock source, signed with `neko-update-prod-2`, and verified against the new trust profile.
- Do not enable web auth in production before the bridge/mapping E2E; keep password login as the fallback.
- Do not bypass the workflow's canonical-repository, immutable release-ID, expected-target, signed-envelope, or asset-verification gates.
- Do not bypass fail-closed cryptographic verification of the signed manifest or component digests.
- Do not modify `launcher/tests/test_config.py` to hide pre-existing baseline asset defects.
- Do not expose signing private-key bytes or copy custody material into the repository.

## Authoritative reference documents
- Current status: `docs/current/README.md`
- Current architecture: `docs/current/launcher-architecture.md`
- Web auth status/contract: `docs/current/web-auth-launcher.md`
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
