# Handoff — Neko Family Proxy Launcher

Updated: 2026-10-24 (Neko Family 5.1.6 Release Line)

## Current state
- Current stable release: `v5.1.6` (tag `01d5331`, released 2026-09-21). `main` is two commits ahead for merge/test cleanup (`616ff89`).
- Active branch: `main`.
- Distribution Architecture: Production Updates & Canonical Main Separation under Revision 3.4, now active.
  - `Valeneko-pranmong/Neko-Family-Proxy-Updates` carries machine assets.
  - `Valeneko-pranmong/Neko-Family-Proxy` carries the official human installer (`NekoFamilyProxy-Installer.exe`) and source.
- Deferred Update Lifecycle (released since 5.1.2, extended through 5.1.6):
  - Background staging (`SoftwareUpdateStageService`) downloads changed components while sessions remain active.
  - Durable pending store (`PendingUpdateStore`) verifies signed envelopes and reconstructs trust offline.
  - Session activity guard (`SessionActivityGuard`) guarantees updates never forcibly terminate game (`pso2.exe`) or proxy sessions.
  - Safe apply pathways: explicit Update action, normal exit, and next-launch offline bootstrap (`try_apply_pending_on_launch`).
  - Reuses the existing `NekoUpdater.exe` transactional engine, probation runner, rollback, and anti-downgrade machinery.
- v5.1.6 additions: startup update-check splash, in-app update progress dialog, windowless updater helper, committed-generation self-sync, Settings version check, and baseline enrollment from a working-directory install root.
- Release workflow: `.github/workflows/release.yml` validates `release_tag` against `launcher/pyproject.toml` at `expected_target`, not a hardcoded version.
- Release controller: `scripts/release_controller.py` resolves the release version from the exact semver tag at the accepted commit, falling back to the declared `launcher/pyproject.toml` and `__init__.py` versions. For an untagged release, bump both declared versions before running the controller; an exact tag must match them. `release_target.json` still supplies sequence/allocation and remains armed at v5.1.2.
- Installer driver registration pins the Core manifest, `Redirector.bin`, and `nfdriver.sys`, verifies every declared driver DLL, and loads the redirector from an admin-only staging directory. The helper script itself still runs from the per-user app directory; a signed helper in an admin-only location is the remaining hardening step.
- Permit issuance is rate-limited per user at 10 attempts per 60 seconds. Apply `supabase/migrations/20261024120000_permit_rate_limit.sql` before deploying the matching Edge Function; a missing RPC fails closed with 503.
- Code signing is still pending a Windows Authenticode certificate. Launcher, Updater, and Installer remain unsigned.

## User-facing readiness
- `v5.1.6` is the current public stable release; in-app automatic updates are active for the released line.
- The manual release workflow is unlocked for any tag that matches the checked-out launcher version, subject to its existing immutable-ID, SHA, asset, and hosted-verification gates.

## Next work
1. Apply the permit rate-limit migration and deploy the matching Edge Function.
2. Procure a Windows Authenticode certificate and wire signing into the release pipeline.
3. Audit the Core-side named-pipe DACL and client verification in the separate NekoProxyCore repository.
4. Re-run the full launcher suite and Ruff at current `main` HEAD.
5. Review hosted Supabase/Edge deployment docs against production state; several `docs/current` and `supabase` deployment statements predate 5.1.6.

## Do not accidentally change
- Do not mutate or replace published `v5.1.6` release assets.
- Do not bypass the workflow's canonical-repository, immutable release-ID, expected-target, signed-envelope, or asset-verification gates.
- Do not bypass fail-closed cryptographic verification of the signed manifest or component digests.
- Do not modify `launcher/tests/test_config.py` to hide pre-existing baseline asset defects.
- Do not expose signing private-key bytes.

## Authoritative reference documents
- Current status: `docs/current/README.md`
- Current architecture: `docs/current/launcher-architecture.md`
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
