# P0–P5 Status Audit

**Audit date:** 2026-10-25

**Result:** P0 and the P2 product path are complete. P1, P3, P4, and P5 are
partially complete; the remaining items require staging Supabase/identity
access, ISCC, and a preview publication/E2E run. The overall cutover is **not
complete** and no 5.2.0/5.3.0 publication is authorized.

## Evidence summary

| Phase | Status | Evidence | Missing gate |
| --- | --- | --- | --- |
| P0 — decisions | COMPLETE | Locked decision register and shared-auth consumer inventory in `docs/superpowers/plans/2026-10-25-web-auth-separation-and-5-3-0-cutover.md`; docs aligned; consumer audit recorded | None |
| P1 — identity/bridge | PARTIAL | `launcher_v2` schema/RPC migrations; reference `supabase/functions/launcher_bridge`; JWT/JWKS, JTI, identity-link, web-session and bridge tests | Deploy migrations/bridge to staging; provision accounts/entitlement; full loopback → identity → bridge → Supabase → claim/permit → Core E2E; Auth `session_id` refresh verification |
| P2 — client web-only | COMPLETE for product path | `NEKO_LAUNCHER_SCHEMA`, server-metadata permit routing, web-only UI, frozen-build enforcement, recovery removal, service-layer password/recovery rejection; UI/config/service tests | Full 5.2.0 staging E2E/Windows package smoke |
| P3 — installer separation | PARTIAL | `installer/beta.iss` same-AppId guard blocks running processes and any version other than 5.2.0; clean-start policy; contract tests | ISCC rebuild; install/uninstall matrix with 5.1.6 installed/running and 5.2.0 reinstall |
| P4 — preview safely | PARTIAL | 5.2.x stable publication block; preview release-list discovery; signed `update-profile-preview-v1.json`; feed-isolation tests | Preview publication path; 5.2.0 auto-apply; real feed-level E2E |
| P5 — 5.3.0 cutover | PARTIAL | `docs/current/5.3.0-cutover-runbook.md` with gates, no-transfer, archive, shutdown and rollback | Execute after P1/P3/P4 and owner-approved cutoff |

## P0 evidence

- Isolated `launcher_v2` schema decision; shared `auth.users` constraint and
  web-session allowlist recorded.
- Dedicated preview channel, same AppId + guard, clean-start uninstall,
  new-accounts-only 5.2.0, no day/coupon transfer, Control Room admin-only web
  auth, and gate-based sunset.
- Shared-auth consumer inventory covers Launcher 5.1.6, 5.2.0 bridge, Control
  Room admin, account-recovery API, permit Edge Function, tests/staging, and
  public status/runtime config.

## P1 evidence and gaps

Present:

- `supabase/migrations/20261025130000_create_launcher_v2_auth_foundation.sql`
- `supabase/migrations/20261025131000_create_launcher_v2_claim_permit.sql`
- `supabase/migrations/20261025132000_add_launcher_v2_bridge_support.sql`
- `supabase/functions/launcher_bridge/` with JWT/JWKS, JTI replay, identity
  linking, session minting, and web-session allowlist tests.
- `docs/current/launcher-bridge-staging-runbook.md`.

Not verified:

- No migration or function has been applied to staging/production.
- No staging bridge, test Discord account, or next-line test entitlement.
- No real end-to-end flow.
- No confirmation that the project's email-provider settings permit
  admin-generated magiclink verification.
- No confirmation that `auth.sessions.id` survives refresh; the allowlist
  rotation fallback remains unimplemented.

## P2 evidence and gaps

Present:

- `NEKO_LAUNCHER_SCHEMA=launcher_v2`; legacy default `launcher`.
- `issue_launch_permit` selects `launcher_v2` only from server-controlled
  `app_metadata.auth_line=next`.
- Bridge-enabled UI is web-only; Settings password action and recovery
  view/gateway are omitted.
- Frozen/release builds require the bridge and reject `NEKO_WEB_AUTH_ONLY=0`.
- `LauncherService` rejects password/recovery calls in web-only mode.
- Full Launcher suite: 2,607 passed / 4 skipped (latest recorded run).

Not verified:

- Full 5.2.0 E2E and Windows packaged smoke.
- Source deletion of legacy methods is deferred to the 5.3.0 cleanup.

## P3 evidence and gaps

Present:

- Same AppId/path and clean-start policy.
- `InitializeSetup` fails closed on running NekoLauncher/NekoProxyCore/
  NekoUpdater, unknown installed version, or installed version other than
  5.2.0.
- Installer contract tests pass.

Not verified:

- ISCC is not available on this host; the rebuilt installer does not exist.
- No install/uninstall matrix on Windows with 5.1.6 and 5.2.0 states.
- No Authenticode signature.

## P4 evidence and gaps

Present:

- 5.2.x non-prerelease stable publication is blocked.
- Preview profiles use the release list and accept prereleases; stable profiles
  use `/releases/latest` and reject prereleases.
- Signed `trust/update-profile-preview-v1.json` authorizes only
  `neko-update-prod-2` and verifies against the profile authority.
- Feed-isolation tests pass.

Not verified:

- No preview publication function/run.
- No 5.2.0 auto-apply run from the preview feed.
- No real feed-level E2E.

## P5 evidence and gaps

Present:

- Runbook covers preconditions, legacy freeze, Control Room/recovery
  retirement, no-transfer, 5.3.0 publication, archive/restore, shutdown,
  rollback, and evidence.

Not verified:

- All execution gates remain pending. The runbook explicitly forbids execution
  until P1/P3/P4 pass and the owner approves the cutoff.

## External blockers

1. Staging Supabase + identity bridge/test accounts/entitlement and E2E.
2. ISCC and Windows install/uninstall matrix.
3. Preview publication/auto-apply and feed E2E.
4. Owner-approved legacy cutoff and 5.3.0 execution window.

## Publication rule

Do not tag, publish, push release assets, enable web auth in production, or
claim the 5.3.0 cutover until every missing gate above is evidenced.
