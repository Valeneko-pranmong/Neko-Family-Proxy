# 5.2.0 Web-Auth Separation and 5.3.0 Legacy Cutover — Development Plan

**Status:** Direction approved; planning only. No release, tag, publication, or
production enablement is authorized by this document.

**Decision date:** 2026-10-25

**Owner:** Neko Family Proxy maintainers

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
   side-by-side installation. Local state is a clean start; auth, trust, and
   session state are never carried across lines.
4. **5.2.0 must not be delivered as an automatic update to 5.1.6.** It is a
   manually installed preview line until the 5.3.0 cutover.
5. **5.3.0 is the cutover release.** It ships only after web auth, control web
   auth, identity-to-proxy mapping, the link/claim flow, and end-to-end
   verification are complete. It removes legacy 5.1.6 password/recovery access
   and retires the legacy backend.
6. **No publication gate may be skipped.** A 5.2.0 or 5.3.0 artifact is not
   releasable while any acceptance gate in this plan is open.
7. **5.2.0 uses a dedicated preview channel in the same repository.** 5.1.6
   remains the latest stable feed; 5.2.0 may auto-update only within its
   dedicated preview channel.
8. **5.2.0 is for new accounts only.** Legacy 5.1.6 accounts stay on 5.1.6
   until the 5.3.0 migration/cutover gate; 5.2.0 does not migrate them.

### สรุปการตัดสินใจ (Thai)

- 5.1.6 ยังเป็น stable และใช้งานได้ตามปกติระหว่างพัฒนา 5.2.0
- 5.2.0 เป็นอีกสายงานหนึ่ง ใช้ web auth 100% ไม่มี password/recovery ในโปรแกรม
- 5.2.0 ใช้ schema/RPC namespace แยกใน Supabase project เดิม; `auth.users` ยังใช้ร่วมกับ 5.1.6 จนถึง 5.3.0 จึงต้องมี web-session allowlist
- ผู้ใช้ 5.1.6 ที่ต้องการใช้ 5.2.0 ต้อง uninstall 5.1.6 ก่อน; ข้อมูลในเครื่องเริ่มใหม่ และไม่มีการโอน auth/trust/session ข้าม line
- 5.2.0 preview เปิดเฉพาะบัญชีใหม่; บัญชี 5.1.6 เดิมจะ migrate ตอน 5.3.0
- 5.2.0 ใช้ dedicated preview channel ใน repo เดิม; 5.1.6 ยังเป็น stable/latest
- ห้ามติดตั้ง 5.2.0 ทับ 5.1.6 และห้ามให้ทั้งสองเวอร์ชันอยู่ด้วยกัน
- 5.2.0 ต้องไม่ถูกส่งเป็น auto-update ให้ 5.1.6
- 5.3.0 คือรุ่นตัดระบบเก่า หลัง web auth + control web auth + mapping/link + E2E เสร็จครบ

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
- Complete control web auth before 5.3.0.
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
  guidance that existing 5.1.6 users stay on 5.1.6 until the 5.3.0 migration
  gate.
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
  legacy line until the 5.3.0 migration gate.
- For 5.3.0, define a one-time migration proving ownership of the legacy
  account, transferring remaining days, and revoking the old license/session
  atomically.
- Prevent double entitlement: a user must not run a legacy license and a new
  license concurrently for the same entitlement.
- Migrate or honor unused coupons; define payment/audit/tax retention.
- Build a migration ledger: old user hash, new user ID, migrated-at time,
  remaining days, method, and operator where applicable.
- Do not copy legacy passwords into the new auth path.

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
- Locked: clean-start uninstall data policy; auth/trust/session/preferences do
  not cross lines.
- Locked: 5.2.0 is new-accounts-only; legacy migration is a 5.3.0 gate.
- Locked: 5.2.0 may auto-update only within the preview channel.
- Pending: installer AppId/install-path strategy.
- Pending: 5.3.0 legacy migration, coupon, and entitlement policy.
- Pending: control web auth scope and acceptance evidence.
- Pending: 5.1.6 support window and 5.3.0 sunset date.
- Audit all consumers of the shared `auth.users`/password provider.
- Update release notes, separation guide, handoff, and this plan.

Exit gate: all P0 decisions recorded; no conflicting "install over 5.1.6"
instructions remain in current docs; shared-auth-pool consumers are known.

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

### P2 — 5.2.0 Web-Only Client

Deliverables:

- Password/recovery code and UI removed from the 5.2.0 product path.
- Web-only auth view for new accounts, clean-start local state, new session
  storage key.
- Clear guidance for existing 5.1.6 users to stay on 5.1.6 until the 5.3.0
  migration gate.
- Updated tests and UI evidence.
- 5.1.6 regression suite remains green.

Exit gate: 5.2.0 cannot authenticate with a password; 5.1.6 behavior is
unchanged.

### P3 — Installer Separation

Deliverables:

- Uninstall guard and running-process guard.
- AppId/path decision implemented.
- Uninstall/install matrix, including data-loss disclosure.
- 5.2.0 installer enrollment with the new trust profile.

Exit gate: installing 5.2.0 over or beside 5.1.6 is impossible; clean
uninstall/install passes; 5.1.6 remains usable when 5.2.0 is not installed.

### P4 — 5.2.0 Preview

Deliverables:

- Dedicated preview-channel distribution in the same repository, with
  5.1.6 remaining latest stable.
- Preview-channel auto-update for 5.2.0 only.
- Bridge and control web auth monitoring.
- New-account onboarding rehearsal; separately rehearse the 5.3.0 legacy
  migration/coupon path.
- Support runbook and rollback plan.

Exit gate: no 5.1.6 breakage in the release feed; preview users can complete
web-only login and launch; 5.3.0 migration/coupon path is proven or explicitly
deferred with customer communication.

### P5 — 5.3.0 Cutover

Deliverables:

- Web auth and control web auth complete.
- Existing-user migration/entitlement decision executed for 5.1.6 accounts.
- 5.3.0 stable release.
- Legacy 5.1.6 login/recovery disabled and legacy schema/RPCs frozen/archived.
- Legacy auth surface decommissioned per the approved retention policy, with
  the shared-auth-pool consumer audit complete.
- 5.1.6 sunset communication and support plan.

Exit gate: all acceptance criteria below pass; owner approves publication and
legacy shutdown.

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

- [ ] Bridge, mapping, link/claim, control web auth, and E2E are complete.
- [ ] Existing-user migration and remaining-day handling are complete, or a
      documented support path exists.
- [ ] Legacy licenses/sessions are revoked without double entitlement.
- [ ] Legacy data is archived/retained per policy and restore-tested.
- [ ] 5.1.6 password/recovery access is removed only after the sunset gate.
- [ ] 5.3.0 is published as stable with approved trust and signing evidence.

## 7. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| 5.1.6 sees 5.2.0 as an update and shows an error | Keep 5.1.6 as latest stable; use the dedicated preview channel; test old-client feed behavior |
| Installer silently replaces 5.1.6 | Hard pre-install guard and running-process guard; test with 5.1.6 installed |
| Uninstall deletes local settings/account state | Clean-start policy is approved; document data loss and do not claim settings preservation |
| Existing users lose remaining days | 5.2.0 is new accounts only; 5.1.6 stays usable until the 5.3.0 migration gate |
| Double entitlement across two lines | Revoke old license/session at 5.3.0 migration; audit both schemas |
| Shared `auth.users`/password pool across lines | No-password 5.2.0 users; web-session allowlist in next-line RPCs; audit all auth consumers; disable legacy password auth only at cutover |
| Legacy password remains an attack path | Keep it only on the legacy schema/RPC path; remove it from 5.2.0/5.3.0; revoke at cutover |
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
| D3a | Installer AppId/install-path strategy | Same AppId with a hard uninstall/process guard | PENDING |
| D3b | Uninstall data policy | Clean start; auth/trust/session/preferences do not cross lines; only the shared driver remains | LOCKED |
| D4 | Existing 5.1.6 accounts in 5.2.0 | New accounts only; no legacy migration in 5.2.0 | LOCKED |
| D5 | 5.3.0 migration, coupon, and entitlement policy | Transfer remaining days atomically, revoke the old license/session, honor unused coupons, and record a migration ledger | PENDING |
| D6 | Control web auth scope | Define owner, surfaces, and acceptance evidence before 5.3.0 | PENDING |
| D7 | 5.1.6 support window and 5.3.0 sunset | No fixed date until gates pass; announce 30/14/7/1 days before shutdown | PENDING |
| D8 | 5.2.0 automatic updates | Preview channel may update 5.2.0 only; 5.1.6 remains on the stable channel | LOCKED |

D1 guardrail: the shared-auth-pool consumer audit is a P0 exit item; the
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
