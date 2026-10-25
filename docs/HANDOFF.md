# Handoff — Neko Family Proxy Launcher

Updated: 2026-10-25 (Neko Family 5.2.0 unified-line release preparation — blocked)

## Current state
- Current release line: `v5.2.0` (source; preview/manual; publication blocked). `v5.1.6` remains the last published stable until 5.2.0 is released.
- Active branch: `feat/proxy-api-launcher-clean-v2` for release preparation; `main` remains the stable-line integration branch.
- Distribution Architecture: unified canonical releases on `Valeneko-pranmong/Neko-Family-Proxy`; the historical `Neko-Family-Proxy-Updates` identity is superseded.
- Trust Anchors: `neko-update-prod-2` and `neko-update-profile-v520-1`; the signed profile authorizes only the current release key. Historical public keys remain for verification. The old private key is unavailable.
- Upgrade Path: 5.1.6 and 5.2.0 are separate lines. 5.1.6 remains public stable on its legacy password/recovery backend. 5.2.0 is the unified-line release target using Neko-NETWORK-ID Discord login and Neko Proxy API only; it cannot auto-update 5.1.6, must not be installed over it, and requires a full 5.1.6 uninstall first (owner decision: clean uninstall-first). Local state is a clean start, there is no side-by-side support, and there is no day/coupon transfer. 5.2.0 uses the preview channel. `5.3.0` is not a release label; legacy retirement remains a future, separately approved gate.
- Deferred Update Lifecycle (released since 5.1.2, extended through 5.2.0):
  - Background staging (`SoftwareUpdateStageService`) downloads changed components while sessions remain active.
  - Durable pending store (`PendingUpdateStore`) verifies signed envelopes and reconstructs trust offline.
  - Session activity guard (`SessionActivityGuard`) guarantees updates never forcibly terminate game (`pso2.exe`) or proxy sessions.
  - Safe apply pathways: explicit Update action, normal exit, and next-launch offline bootstrap (`try_apply_pending_on_launch`).
  - Reuses the existing `NekoUpdater.exe` transactional engine, probation runner, rollback, and anti-downgrade machinery.
- v5.1.6 additions: startup update-check splash, in-app update progress dialog, windowless updater helper, committed-generation self-sync, Settings version check, and baseline enrollment from a working-directory install root.
- v5.2.0 additions: refreshed launcher/auth/dashboard/Settings presentation; atomic self-sync; buffered support/debug logging; one-shot startup update check; installer driver-path pinning; permit-issuance rate limiting; pinned CI actions; release/profile authority rotation; unified-line identity login, session lifecycle, launch permit, and Runtime Config v1 through Neko Proxy API. The legacy bridge path remains for 5.1.6 only. Core `54365f2` adds bounded 10-minute permit clock-skew tolerance with fresh-challenge authority; managed Core suite 344/344.
- Release workflow: `.github/workflows/release.yml` validates `release_tag` against `launcher/pyproject.toml` at `expected_target`, not a hardcoded version.
- Release controller: `scripts/release_controller.py` resolves the release version from the exact semver tag at the accepted commit, falling back to the declared `launcher/pyproject.toml` and `__init__.py` versions. For an untagged release, bump both declared versions before running the controller; an exact tag must match them. `release_target.json` is armed at `v5.1.6` → `v5.2.0`; the parser accepts a single patch increment or a `.0` minor release.
- Installer driver registration pins the Core manifest, `Redirector.bin`, and `nfdriver.sys`, verifies every declared driver DLL, and loads the redirector from an admin-only staging directory. The helper script itself still runs from the per-user app directory; a signed helper in an admin-only location is the remaining hardening step.
- Permit issuance is rate-limited per user at 10 attempts per 60 seconds. Apply `supabase/migrations/20261024120000_permit_rate_limit.sql` before deploying the matching Edge Function; a missing RPC fails closed with 503.
- Code signing is still pending a Windows Authenticode certificate. Launcher, Updater, and Installer remain unsigned.

## User-facing readiness
- `v5.1.6` remains the last published stable and must keep working on its legacy backend throughout 5.2.0 development.
- The earlier 5.2.0 candidate was built before the web-auth and Core clock changes; it is superseded and must be rebuilt before any publication.
- 5.2.0 is a separate unified-line release: no automatic update from 5.1.6, no in-place install, no side-by-side installation. Users who want 5.2.0 must uninstall 5.1.6 first. The installer guard is implemented in `installer/beta.iss`; the installer has not been rebuilt and the install matrix has not been run.
- The unified-line release is blocked: Proxy API `/v1/*` and `/public/status` return HTTP 404, 01c/02d/03c E2E is not passed, no approved `NEKO_PROXY_API_URL` origin exists, the frozen-build guard rejects the new line, and no Authenticode certificate is available. Do not publish or distribute 5.2.0 until these gates pass.
- The manual release workflow is unlocked for any tag that matches the checked-out launcher version, subject to its existing immutable-ID, SHA, asset, and hosted-verification gates.

## Next work
1. Complete identity 01c and Proxy API 02d staging deployment; then run 03c live E2E (login, `/v1/me`, claim, heartbeat, permit, Core start, release) and the negative cases.
2. Approve the HTTPS `NEKO_PROXY_API_URL` origin and implement/test the frozen release configuration without weakening the Supabase-free and bridge-free guards.
3. Stage the approved Launcher, Updater, Core bundle, authority envelope, and .NET 6.0.36 bootstrapper; rebuild the preview installer with ISCC and record hashes.
4. Run the clean-VM install matrix: clean install, 5.1.6 uninstall -> 5.2.0 install, uninstall/reinstall, and rollback to 5.1.6. Document that clean uninstall-first loses local state.
5. Verify no Supabase URL/key/session, no bridge call, and no proxy database access in the new-line process, logs, and network.
6. Keep the Control Room status endpoint available for 5.2.0; the `/public/status` migration remains deferred.
7. Back up the release and profile-authority custody keys to an external, access-controlled medium.
8. Procure a Windows Authenticode certificate or explicitly accept an unsigned build; do not claim signing without evidence.
9. Review hosted Supabase/Edge deployment docs against production state.
10. Prepare the owner sign-off package; do not publish 5.2.0 until every gate is evidenced.

Core pipe isolation is complete in `ab3b08c`; the bounded permit clock-skew fix is in Core `54365f2` (local commit, not pushed). A future image-path check remains optional defense in depth.

## Do not accidentally change
- Do not mutate or replace published `v5.1.6` release assets.
- Do not reuse the `neko-update-prod-1` key ID with new key bytes; existing clients verify it against the historical public key.
- Do not force 5.1.6 users onto 5.2.0; 5.1.6 must remain usable on its legacy backend during 5.2.0 development.
- Do not publish 5.2.0 as the latest stable or as an auto-update for 5.1.6. Use the approved separate preview/manual path.
- Do not allow 5.2.0 to be installed over or alongside 5.1.6. The uninstall/process guard is mandatory.
- Do not publish 5.2.0 until it is rebuilt with the unified-line source, approved Proxy API configuration, the installer guard, E2E, and `neko-update-prod-2` preview trust/profile verification.
- Do not keep password/recovery fallback in 5.2.0; those paths belong only to 5.1.6 until the legacy-retirement gate.
- Do not bypass the workflow's canonical-repository, immutable release-ID, expected-target, signed-envelope, or asset-verification gates.
- Do not bypass fail-closed cryptographic verification of the signed manifest or component digests.
- Do not modify `launcher/tests/test_config.py` to hide pre-existing baseline asset defects.
- Do not expose signing private-key bytes or copy custody material into the repository.

## Authoritative reference documents
- Current status: `docs/current/README.md`
- 5.2.0 release notes: `docs/current/5.2.0-release-notes.md`
- 5.2.0 release runbook: `docs/current/5.2.0-release-runbook.md`
- 5.2.0 preparation record: `docs/current/5.2.0-release-preparation-record.md`
- Current architecture: `docs/current/launcher-architecture.md`
- Proxy API launcher contract: `docs/current/proxy-api-launcher-contract.md`
- Unified-line design reference (formerly 5.3.0): `docs/current/5.3.0-proxy-api-launcher.md`
- Legacy retirement runbook (formerly 5.3.0 cutover): `docs/current/5.3.0-cutover-runbook.md`
- P0–P5 status audit: `docs/current/p0-p5-status-audit.md`
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
