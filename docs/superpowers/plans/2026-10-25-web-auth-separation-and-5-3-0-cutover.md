# 5.2.0 Web-Auth Separation and 5.3.0 Legacy Cutover — Development Plan

**Status:** Direction approved; planning only. No release, tag, publication, or
production enablement is authorized by this document.

**Decision date:** 2026-10-25

**Owner:** Neko Family Proxy maintainers

> **Superseded for the new line (2026-10-25):** the bridge/session-minting and
> launcher web-session allowlist portions of this plan are replaced by the
> identity access/refresh token + Neko Proxy API design in
> [docs/current/5.3.0-proxy-api-launcher.md](../../current/5.3.0-proxy-api-launcher.md).
> `5.1.6` remains unchanged; the remainder of this document is historical
> context for the 5.2.0 line.

**Supersedes:** the in-place 5.1.6 -> 5.2.0 upgrade policy in the 5.2.0 release
notes and manual-upgrade guide.

## 1. Decision

1. **5.1.6 remains the public stable line and stays fully usable** on its
   existing password/recovery backend throughout 5.2.0 development.
2. **5.2.0 is a separate line with 100% web authentication.** It does not
   expose password login, registration, password change, or recovery-code
   login. It uses an isolated schema/RPC namespace and local session state.
   The Supabase `auth.users` pool remains shared with 5.1.6 until the 5.3.0
   cutover, so a web-session allowlist is mandatory.
3. **5.1.6 and 5.2.0 must not coexist on one installation.** A user who wants
   5.2.0 must uninstall 5.1.6 first. There is no in-place upgrade and no
   side-by-side installation. The installer keeps the existing AppId with a
   hard uninstall/process guard. Local state is a clean start; auth, trust, and
   session state are never carried across lines.
4. **5.2.0 must not be delivered as an automatic update to 5.1.6.** It is a
   manually installed preview line until the 5.3.0 cutover.
5. **5.3.0 is the cutover release.** It ships only after web auth, control web
   auth, identity-to-proxy mapping, the link/claim flow, and end-to-end
   verification are complete. It removes legacy 5.1.6 password/recovery access
   and retires the legacy backend. There is **no legacy day or coupon
   transfer**: legacy renewals/coupon issuance freeze, 5.1.6 stays usable
   until the last active legacy term expires (or an explicit cutoff is
   accepted), and unused legacy coupons become void after notice.
6. **No publication gate may be skipped.** A 5.2.0 or 5.3.0 artifact is not
   releasable while any acceptance gate in this plan is open.
7. **5.2.0 uses a dedicated preview channel in the same repository.** 5.1.6
   remains the latest stable feed; 5.2.0 may auto-update only within its
   dedicated preview channel.
8. **5.2.0 is for new accounts only.** Legacy 5.1.6 accounts stay on 5.1.6
   until the 5.3.0 cutover; 5.2.0 does not migrate them and no day/coupon
   transfer is planned.
9. **Control web auth means the Control Room/admin surface only.** The
   customer web portal is outside this scope.
10. **The 5.1.6 sunset is gate-based, not date-based.** 5.3.0 ships when all
    gates pass; legacy shutdown happens after the last active legacy term
    expires or an explicit cutoff is accepted, with 30/14/7/1-day notices.

### สรุปการตัดสินใจ (Thai)

- 5.1.6 ยังเป็น stable และใช้งานได้ตามปกติระหว่างพัฒนา 5.2.0
- 5.2.0 เป็นอีกสายงานหนึ่ง ใช้ web auth 100% ไม่มี password/recovery ในโปรแกรม
- 5.2.0 ใช้ schema/RPC namespace แยกใน Supabase project เดิม; `auth.users` ยังใช้ร่วมกับ 5.1.6 จนถึง 5.3.0 จึงต้องมี web-session allowlist
- ผู้ใช้ 5.1.6 ที่ต้องการใช้ 5.2.0 ต้อง uninstall 5.1.6 ก่อน; installer ใช้ AppId เดิมพร้อม guard; ข้อมูลในเครื่องเริ่มใหม่ และไม่มีการโอน auth/trust/session ข้าม line
- 5.2.0 preview เปิดเฉพาะบัญชีใหม่; ไม่มีการโอนวันคงเหลือหรือ coupon จาก 5.1.6
- 5.1.6 ยังใช้ได้จนกว่าสิทธิ์เดิมจะหมดอายุ; legacy renewals/coupon issuance ต้องหยุด และ coupon ที่ไม่ถูกใช้จะหมดอายุหลังประกาศ
- 5.2.0 ใช้ dedicated preview channel ใน repo เดิม; 5.1.6 ยังเป็น stable/latest
- ห้ามติดตั้ง 5.2.0 ทับ 5.1.6 และห้ามให้ทั้งสองเวอร์ชันอยู่ด้วยกัน
- 5.2.0 ต้องไม่ถูกส่งเป็น auto-update ให้ 5.1.6
- control web auth หมายถึง Control Room/admin เท่านั้น; customer portal อยู่นอก scope
- 5.3.0 คือรุ่นตัดระบบเก่า หลัง web auth + control web auth + mapping/link + E2E เสร็จครบ; sunset เป็นแบบ gate-based ไม่กำหนดวันตายตัว

## 2. Current State and Gaps

- The Launcher-side Discord loopback/PKCE flow is implemented and committed,
  but gated off by `NEKO_WEB_AUTH_ENABLED` and `NEKO_AUTH_BRIDGE_URL`
  (`launcher/src/neko_launcher/infrastructure/config.py`).
- The password fallback is still present in `AuthGateway`, `LauncherService`,
  `SupabaseGateway`, the auth view, and the Settings account page.
- The proxy bridge, `launcher.identity_links` mapping, one-time link/claim
  flow, staging test accounts, and full E2E are not available.
- The installer uses one AppId and one install root
  (`%LOCALAPPDATA%\NEKO FAMILY`), installs over the existing tree, and has no
  guard that requires uninstalling 5.1.6 first
  (`installer/beta.iss`).
- The installer uninstaller removes launcher state, trust, baseline, tools,
  ProxyCore, logging, `*.json`, and `*.path` from the install root. The
  current data-preservation claim is therefore not valid for a clean line
  separation.
- The 5.2.0 candidate predates the web-auth and Core clock changes and is stale.
- The current normal updater path accepts only non-draft, non-prerelease
  `stable` releases. Publishing 5.2.0 as the latest stable in the same release
  repository would make 5.1.6 fetch a manifest it cannot verify with its old
  release key.

## 3. Separation Boundary

The following must be distinct between the legacy line and the next line:

| Boundary | Legacy 5.1.6 | Next 5.2.0 / 5.3.0 |
| --- | --- | --- |
| Login | Password + recovery code | Discord web auth only |
| Auth authority | Existing Supabase project, `launcher` schema | Isolated schema/RPC namespace in the same project; shared `auth.users` until 5.3.0 |
| Local session | Existing credential-store key | New session key; legacy auth/trust/state cleared; clean start |
| Backend entitlement | Existing legacy schema | Isolated next-line schema; no table mixing |
| Installer | Existing 5.1.6 install | Clean install after 5.1.6 uninstall |
| Update feed | Latest 5.1.6 stable | Dedicated preview channel; 5.1.6 remains latest stable |
| Trust profile | Existing 5.1.6 profile | 5.2.0+ profile and release key |

**D1 constraint:** the selected isolated-schema topology is **not full auth
isolation**. `auth.users`, the password provider, the JWT secret, and project
limits remain shared. Mitigations are mandatory: create 5.2.0 users without a
password, enforce the web-session allowlist in the new schema RPCs, audit all
other consumers of the shared auth pool, and disable/revoke legacy password
auth only at the 5.3.0 gate.

### Shared Auth Consumer Inventory

Read-only audit completed 2026-10-25 against this repository and the private
`Valeneko-pranmong/Neko-Family-Proxy-admin-tool` repository.

| Consumer | Current auth use | Required action |
| --- | --- | --- |
| Launcher 5.1.6 | Supabase password + recovery | Keep until its term expires or cutoff; no transfer |
| 5.2.0 Launcher/bridge | New web session; no password | Enforce next-line session allowlist |
| Control Room admin (`server/auth.mjs`, `server/supabase.mjs`) | Username/password through Supabase Auth, `profiles.role=admin`, server-only service role | Migrate to Control Room admin web auth before disabling password |
| Account recovery API (`server/account-recovery.mjs`) | Service-role lookup plus password update | Retire or replace when 5.1.6 password recovery is retired |
| `issue_launch_permit` Edge Function | Validated Supabase access-token session | Keep; verify next-line session IDs and allowlist |
| Tests/staging | Disposable password users | Remove/disable at cutover; never reuse production users |
| Public proxy status/runtime config | Public status plus admin session | Verify admin session auth after Control Room admin web-auth migration |

No other in-repo consumer of the shared password provider was found outside
these paths. Any external app added later must be recorded here before the
5.3.0 password shutdown.

## 4. Workstreams

### A. Identity, Bridge, and Web Auth

- Deploy the proxy bridge and validate the identity JWT through JWKS.
- Implement replay protection (`jti`), audience/issuer/expiry validation, and
  rate limits.
- Create the isolated next-line schema/RPC namespace (for example
  `launcher_v2`) with its own tables, grants, and RLS.
- Add `identity_links` with unique mappings in both directions, audit events,
  RLS, and administrative support operations.
- Implement account creation/link for new 5.2.0 accounts. Legacy 5.1.6
  link/claim is a 5.3.0 gate, not a 5.2.0 feature.
- Create new 5.2.0 users without a password; mint the Supabase session in the
  same project and adopt it through `SupabaseGateway.sign_in_with_web()`.
- Record the minted `auth_session_id` in a web-session allowlist and enforce it
  in the next-line `claim_session` and `authorize_launch_permit` RPCs.
- Complete Control Room admin web auth before 5.3.0.
- Decide and implement new-user, unlink, Discord-ban, lost-Discord, and legacy
  recovery policies.

### B. 5.2.0 Client

- Make the 5.2.0 UI web-only: no password fields, sign-up tab, password-change
  action, or recovery-code entry.
- Remove password/recovery methods from the 5.2.0 `AuthGateway`,
  `LauncherService`, `SupabaseGateway`, ports, controller states, and tests.
- Remove the password fallback from 5.2.0. The flag may remain only for
  development/test builds; a release build must not be able to re-enable the
  password path.
- Do not add a legacy-account migration entry point to 5.2.0. Show clear
  guidance that existing 5.1.6 users stay on 5.1.6 until their term expires or
  the 5.3.0 cutoff gate.
- Use a new local session key. Because the install is a clean start, do not
  attempt to import legacy auth/trust/session state.
- Update screenshots, release notes, support docs, and error messages to the
  web-only, new-account flow.

### C. Installer and Version Isolation

- Choose and document the installer identity strategy (same AppId with a hard
  guard, or a new AppId). Side-by-side installation is not supported.
- Add a pre-install guard that detects a 5.1.6 installation and blocks with a
  clear Thai/English message instructing the user to uninstall it first.
- Add a running-process guard for `NekoLauncher.exe` and `NekoProxyCore.exe`.
- Ensure the 5.2.0 installer cannot replace a 5.1.6 trust profile or state in
  place.
- Apply the locked clean-start policy: uninstall removes local app state,
  trust, logs, session data, and preferences. Do not claim settings
  preservation; only the shared netfilter2 driver remains.
- Preserve the shared netfilter2 driver as the current uninstaller does.
- Keep the new trust profile and release-key enrollment in the 5.2.0 payload.
- Test on clean Windows, 5.1.6-installed Windows, 5.1.6-running, 5.2.0
  reinstall, and failed/uninstall-interrupted cases.

### D. Release and Distribution Isolation

- Keep 5.1.6 as the latest stable release while 5.2.0 is under development.
- Use a dedicated preview channel in the same repository for 5.2.0. Do not
  make 5.2.0 the latest stable in the feed that 5.1.6 checks.
- Extend the updater/release tooling for the preview channel; the current
  normal resolver rejects prereleases and requires a `stable` manifest.
- Allow 5.2.0 to auto-update only within the preview channel. Ensure 5.1.6
  update checks continue to see a valid 5.1.6 stable release.
- Make 5.3.0 the first stable release of the web-only line after all gates
  pass.
- Keep the 5.1.6 published assets immutable.

### E. Legacy Data and Entitlement Migration

- 5.2.0 is locked to new accounts only; existing 5.1.6 accounts remain on the
  legacy line until the 5.3.0 cutover.
- 5.3.0 does **not** transfer remaining days or unused coupons. Freeze legacy
  renewals and coupon issuance, keep 5.1.6 usable until the last active legacy
  term expires, and announce the cutoff.
- If an earlier shutdown is required, record an explicit cutoff/forfeiture
  decision; never silently revoke paid days.
- Prevent double entitlement at shutdown: revoke legacy licenses/sessions
  atomically when the legacy line is retired.
- Retain payment/audit/tax records; unused legacy coupons become void after
  notice.
- Keep a legacy reconciliation ledger (old user hash, license term, cutoff
  date, operator where applicable); do not copy legacy passwords.

### F. Verification, Security, and Operations

- End-to-end: loopback -> identity -> bridge -> new Supabase session ->
  next-line `claim_session` -> `issue_launch_permit` -> Core start.
- Regression: 5.1.6 login/proxy/heartbeat/permit behavior is unchanged while
  it remains supported.
- Shared-auth-pool audit: enumerate all other consumers of `auth.users` and
  the password provider; confirm 5.3.0 shutdown cannot break an unowned app.
- Security: no tokens/passwords in logs, JWKS and replay tests, session
  allowlist negative tests, RLS tests, secret scans, `pip-audit`, `bandit`.
- Installer: clean install, uninstall, reinstall, interrupted install, and
  driver-preservation evidence.
- Operations: backup/restore, rollback window, monitoring, support runbook,
  and customer communication.
- Authenticode signing remains a separate open dependency for the installer
  line.

## 5. Phases and Gates

### P0 — Decision Lock

Deliverables:

- Locked: isolated schema/RPC namespace in the existing Supabase project.
- Locked: dedicated preview channel in the same repository; 5.1.6 remains
  latest stable.
- Locked: same AppId with a hard uninstall/process guard.
- Locked: clean-start uninstall data policy; auth/trust/session/preferences do
  not cross lines.
- Locked: 5.2.0 is new-accounts-only; no legacy day/coupon transfer.
- Locked: 5.2.0 may auto-update only within the preview channel.
- Locked: 5.3.0 freezes legacy renewals/coupons, waits for the last active
  legacy term (or an explicit cutoff), and retires the legacy line.
- Locked: control web auth is the Control Room/admin surface only.
- Locked: gate-based sunset; no fixed shutdown date; 30/14/7/1-day notices.
- Audit complete: shared-auth consumer inventory recorded (Launcher 5.1.6,
  5.2.0 bridge, Control Room admin, recovery API, Edge permit, tests, public
  status/config).
- Update release notes, separation guide, handoff, and this plan.

Exit gate: all P0 decisions recorded; no conflicting "install over 5.1.6"
instructions remain in current docs; shared-auth-pool consumers are recorded.

### P1 — Identity and Bridge Foundation

Deliverables:

- Isolated next-line schema/RPC migrations in the existing Supabase project.
- Bridge, JWKS validation, `jti` replay protection, identity links, and
  new-account link/claim flow.
- No-password creation for 5.2.0 users; web-session allowlist enforcement in
  the next-line claim/permit RPCs.
- Staging Discord account, new 5.2.0 account with entitlement, and test mapping.
- E2E evidence.

Exit gate: full web-auth E2E passes in staging; no production flag enabled yet.

**P1 slice 1 status (2026-10-25):** `20261025130000_create_launcher_v2_auth_foundation.sql`
creates the private `launcher_v2` profiles, identity links, web-session
allowlist, and audit foundation; the shared Auth trigger routes only
server-controlled `app_metadata.auth_line = next` users to the next-line
profile.

**P1 slice 2 status (2026-10-25):** `20261025131000_create_launcher_v2_claim_permit.sql`
adds next-line products, licenses, installations, sessions, and permit
attempts plus the claim/heartbeat/release/permit RPCs. Every RPC requires the
web-session allowlist and an active identity link.

**P1 slice 3 status (2026-10-25):** `20261025132000_add_launcher_v2_bridge_support.sql`
adds service-role-only JTI replay, identity lookup/link, and web-session
recording. A reference `supabase/functions/launcher_bridge/` validates the
identity RS256/JWKS token, consumes `jti`, creates a no-password next-line
user, mints a Supabase session, and records the allowlist. Node bridge tests
(14) and SQL/config/runbook contract tests (6) pass; the full Launcher suite
is 2,585 passed / 4 skipped.

None of these migrations or the bridge has been applied/deployed. The
staging deployment/E2E sequence is recorded in
`docs/current/launcher-bridge-staging-runbook.md`. Staging accounts and E2E
remain open. P1 must also validate that the Supabase Auth `session_id` remains
stable across refresh, or update the allowlist row during refresh, and confirm
that the project's email-provider settings permit admin-generated magiclink
verification.

### P2 — 5.2.0 Web-Only Client

Deliverables:

- Password/recovery code and UI removed from the 5.2.0 product path.
- Web-only auth view for new accounts, clean-start local state, new session
  storage key.
- Clear guidance for existing 5.1.6 users to stay on 5.1.6 until their term
  expires or the 5.3.0 cutoff gate.
- Updated tests and UI evidence.
- 5.1.6 regression suite remains green.

Exit gate: 5.2.0 cannot authenticate with a password; 5.1.6 behavior is
unchanged.

**P2 slice 1 status (2026-10-25):** the Launcher can select
`NEKO_LAUNCHER_SCHEMA=launcher_v2` while defaulting to legacy `launcher`; the
claims/RPC adapter uses that schema. The `issue_launch_permit` Edge Function
auto-selects `launcher_v2` only from server-controlled
`app_metadata.auth_line = next` and keeps legacy callers on `launcher`. Default
behavior is unchanged.

**P2 slice 2 status (2026-10-25):** when web auth is enabled, the auth view
becomes web-only (no password, registration, or recovery controls) and the
Settings password-change action is hidden. Source/dev without a bridge still
uses the legacy UI.

**P2 slice 3 status (2026-10-25):** frozen/release builds now require a
configured web-auth bridge and are always web-only; `NEKO_WEB_AUTH_ONLY=0` is
rejected in a frozen build. Source/dev may still use the legacy surface when
no bridge is configured.

**P2 slice 4 status (2026-10-25):** web-only mode does not construct
`RecoveryView` or the `HttpAccountRecoveryGateway`; recovery entry is guarded
even if a stale controller state arrives. Source/dev without a bridge keeps
the legacy recovery path.

**P2 slice 5 status (2026-10-25):** `LauncherService` rejects password
registration, password login, password change, and all recovery methods when
`web_auth_only` is active. Frozen builds are web-only and cannot re-enable
password mode. The source/dev legacy methods remain available only for the
non-frozen reference path and will be deleted at the 5.3.0 cleanup. Full
Launcher suite: 2,601 passed / 4 skipped. P2 product-path exit gate is met.

### P3 — Installer Separation

Deliverables:

- Uninstall guard and running-process guard.
- AppId/path decision implemented.
- Uninstall/install matrix, including data-loss disclosure.
- 5.2.0 installer enrollment with the new trust profile.

Exit gate: installing 5.2.0 over or beside 5.1.6 is impossible; clean
uninstall/install passes; 5.1.6 remains usable when 5.2.0 is not installed.

**P3 slice 1 status (2026-10-25):** `installer/beta.iss` now fails closed when
NekoLauncher/NekoProxyCore/NekoUpdater are running, when an existing install
has no verifiable DisplayVersion, or when the installed version does not match
the installer's declared version. A 5.1.6 install is therefore blocked until it
is uninstalled. Static guard tests and the full Launcher suite pass. ISCC and
the pinned .NET bootstrapper are present; the canonical Core bundle
(`CoreBundle` + `core-manifest.json`) is absent and the `dotnet` SDK is not
installed, so the rebuilt installer and full install/uninstall matrix remain
open.

### P4 — 5.2.0 Preview

Deliverables:

- Dedicated preview-channel distribution in the same repository, with
  5.1.6 remaining latest stable.
- Preview-channel auto-update for 5.2.0 only.
- Bridge and Control Room admin web-auth monitoring.
- New-account onboarding rehearsal; separately rehearse the 5.3.0 legacy
  expiry/cutoff and coupon-notice path.
- Support runbook and rollback plan.

Exit gate: no 5.1.6 breakage in the release feed; preview users can complete
web-only login and launch; 5.3.0 expiry/cutoff and coupon-notice path is proven
or explicitly deferred with customer communication.

**P4 slice 1 status (2026-10-25):** `validate_stable_release_channel` blocks
5.2.x from being staged/published as a non-prerelease stable release, while
allowing an explicit prerelease stage. 5.1.x and 5.3.x stable behavior is
unchanged.

**P4 slice 2 status (2026-10-25):** preview trust profiles can now read the
newest prerelease from the repository release list, while the stable profile
continues using `/releases/latest`. The resolver permits a prerelease only for
a profile whose channel is `preview`; 5.1.6 stable discovery is unchanged.
Feed-isolation tests now prove the stable profile never reads the preview list
and rejects a prerelease, while the preview profile never reads the stable
latest endpoint.

**P4 slice 3 status (2026-10-25):** `trust/update-profile-preview-spec.json`
and the signed `trust/update-profile-preview-v1.json` are committed. The
preview profile is channel `preview`, profile id `preview`, canonical
repository, and authorizes only `neko-update-prod-2`; it verifies against
`neko-update-profile-v520-1`. `scripts/sign_update_trust_profile.py` provides
the reproducible signing path without exposing private bytes. Preview
publication, 5.2.0 auto-apply, and feed-level E2E remain open. Full Launcher
suite: 2,605 passed / 4 skipped.

**P4 slice 4 status (2026-10-25):** the preview path is now consistent from
manifest to pending update. Release-v2 manifests accept `channel=preview`;
the release builder requires a preview profile for 5.2.x and emits a preview
manifest, the installer builder requires the same binding, and pending-update
stores are channel-scoped so preview and stable updates cannot cross-load.
The resolver binds the manifest channel to the installed profile, the
publisher and hosted verifier require preview manifests to be prereleases, and
`rollout-stable` now refuses to promote any 5.2.x tag. Cleanup and version
guards cover 5.2.x suffixes. Full Launcher suite: 2,629 passed / 4 skipped.
Actual preview publication, 5.2.0 auto-apply, and feed-level E2E remain open.

**P4 alpha slice status (2026-10-27):** the intermediate `5.2.0a1`
re-version was superseded by the `5.2.2a` local alpha build (revision 6). The
release, publisher, verifier, workflow, and installer toolchain accept
alpha/PEP 440 suffixes while keeping the 5.2 line preview-only. Evidence:
`docs/current/5.2.2a-alpha-build.md`. No tag or publication exists; staging E2E
and staged installer payloads remain blocked (ISCC itself is available).

### P5 — 5.3.0 Cutover

Deliverables:

- Web auth and Control Room admin web auth complete.
- No-transfer policy executed: legacy renewals/coupon issuance frozen; last
  active legacy term expired or an explicit cutoff approved.
- 5.3.0 stable release.
- Legacy 5.1.6 login/recovery disabled and legacy schema/RPCs frozen/archived.
- Account recovery API retired/replaced; no password-reset consumer remains.
- All shared-auth consumers from the inventory are migrated or retired.
- Legacy auth surface decommissioned per the approved retention policy.
- 5.1.6 sunset communication and support plan, including unused-coupon notice.

Exit gate: all acceptance criteria below pass; owner approves publication and
legacy shutdown.

**P5 runbook status (2026-10-25):** `docs/current/5.3.0-cutover-runbook.md`
records the hard preconditions, legacy freeze, Control Room/recovery
retirement, 5.3.0 publication, no-transfer policy, archive/restore, shutdown,
rollback, and evidence checklist. Execution remains blocked on the P1/P3/P4
gates and owner-approved cutoff.

## 6. Acceptance Criteria

### 5.1.6 Protection

- [ ] A 5.1.6 user who does nothing can still log in, claim a session, and
      start the proxy.
- [ ] 5.1.6 update checks do not receive an unverifiable 5.2.0 manifest.
- [ ] Published 5.1.6 assets and trust material are not modified.

### 5.2.0 Separation

- [ ] 5.2.0 installer blocks when 5.1.6 is installed or running.
- [ ] 5.2.0 cannot be installed over 5.1.6 and cannot coexist with it.
- [ ] 5.2.0 has no password, sign-up, password-change, or recovery-code login.
- [ ] 5.2.0 web login completes end to end and issues a Core permit.
- [ ] A password session or non-allowlisted session cannot claim or obtain a
      permit.
- [ ] 5.2.0 is not the latest stable release while 5.1.6 remains supported.

### 5.3.0 Cutover

- [ ] Bridge, mapping, link/claim, Control Room admin web auth, and E2E are complete.
- [ ] Legacy account-recovery API is retired/replaced; no password-reset consumer remains.
- [ ] Shared-auth consumer inventory is fully migrated or retired.
- [ ] No-transfer policy applied: legacy renewals/coupon issuance frozen; last
      active legacy term expired or an explicit cutoff approved.
- [ ] Unused legacy coupons have a documented notice/void date.
- [ ] Legacy licenses/sessions are revoked without double entitlement only at
      the approved shutdown point.
- [ ] Legacy data is archived/retained per policy and restore-tested.
- [ ] 5.1.6 password/recovery access is removed only after the sunset gate.
- [ ] 5.3.0 is published as stable with approved trust and signing evidence.

## 7. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| 5.1.6 sees 5.2.0 as an update and shows an error | Keep 5.1.6 as latest stable; use the dedicated preview channel; test old-client feed behavior |
| Installer silently replaces 5.1.6 | Hard pre-install guard and running-process guard; test with 5.1.6 installed |
| Uninstall deletes local settings/account state | Clean-start policy is approved; document data loss and do not claim settings preservation |
| Existing users lose remaining days | No-transfer policy: freeze legacy renewals/coupons, keep 5.1.6 until the last active term expires, or record an explicit cutoff; do not silently revoke paid days |
| Double entitlement across two lines | Revoke old license/session at the approved 5.3.0 shutdown point; audit both schemas |
| Shared `auth.users`/password pool across lines | No-password 5.2.0 users; web-session allowlist in next-line RPCs; audit all auth consumers; disable legacy password auth only at cutover |
| Legacy password remains an attack path | Keep it only on the legacy schema/RPC path; remove it from 5.2.0/5.3.0; revoke at cutover |
| Auth `session_id` changes on token refresh | Validate in P1 E2E; if it changes, the bridge must rotate the allowlist row before the client refreshes |
| Bridge/identity outage blocks all login | Monitoring, retry/error UX, support runbook, rollback plan |
| Missing staging bridge/test accounts | P1 release gate; no 5.2.0 preview without E2E |
| Authenticode still unavailable | Keep hash verification and signing dependency visible; do not claim signed status |
| Legal/accounting retention | Export/archive before deletion; define retention period with owner |

## 8. P0 Decision Register

Status values: `PENDING` (owner decision needed), `LOCKED` (approved and
recorded), `DEFERRED` (explicitly moved to a later gate).

| ID | Decision | Locked value / recommended default | Status |
| --- | --- | --- | --- |
| D1 | Auth/data authority topology | Isolated schema/RPC namespace in the existing Supabase project; shared `auth.users` accepted with a mandatory web-session allowlist | LOCKED |
| D2 | 5.2.0 distribution | Dedicated preview channel in the same repository; 5.1.6 remains latest stable | LOCKED |
| D3a | Installer AppId/install-path strategy | Same AppId with a hard uninstall/process guard | LOCKED |
| D3b | Uninstall data policy | Clean start; auth/trust/session/preferences do not cross lines; only the shared driver remains | LOCKED |
| D4 | Existing 5.1.6 accounts in 5.2.0 | New accounts only; no legacy migration in 5.2.0 | LOCKED |
| D5 | 5.3.0 legacy shutdown, coupon, and entitlement policy | No transfer of remaining days or unused coupons; freeze legacy renewals/coupons and wait for the last active term or an explicit cutoff | LOCKED |
| D6 | Control web auth scope | Control Room/admin surface only; customer web portal out of scope | LOCKED |
| D7 | 5.1.6 support window and 5.3.0 sunset | Gate-based, no fixed date; last active legacy term or explicit cutoff; announce 30/14/7/1 days before shutdown | LOCKED |
| D8 | 5.2.0 automatic updates | Preview channel may update 5.2.0 only; 5.1.6 remains on the stable channel | LOCKED |

D1 guardrail: the shared-auth consumer inventory is recorded in section 3.
Any new consumer must be added there before the 5.3.0 password shutdown; the
isolated schema is not full auth isolation.

## 9. Out of Scope

- Implementing the bridge, isolated next-line schema, or installer guard in
  this planning change.
- Publishing, tagging, or pushing a release.
- Enabling web auth in production.
- Modifying published 5.1.6 assets.
- Supporting side-by-side 5.1.6 and 5.2.0 installations.
- Automatic upgrade from 5.1.6 to 5.2.0.

## 10. References

- `docs/current/web-auth-launcher.md`
- `docs/current/5.2.0-release-notes.md`
- `docs/current/5.2.0-manual-upgrade.md`
- `docs/HANDOFF.md`
- `installer/beta.iss`
- `launcher/src/neko_launcher/infrastructure/config.py`
- `launcher/src/neko_launcher/application/services.py`
- `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py`
