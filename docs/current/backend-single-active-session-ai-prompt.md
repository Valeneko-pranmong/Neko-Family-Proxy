# AI Implementation Prompt: Allow multiple installations but only one active session

> **Status: SUPERSEDED 9 AUGUST 2026** — This historical handoff still describes
> explicit installation revocation. The current product policy removes permanent
> machine locking; see `supabase/migrations/20260809133000_remove_permanent_installation_lock.sql`.
>
> **Target team:** Backend / Supabase / Admin Web
>
> **Consumer:** Neko Family Launcher desktop client
>
> **Repository context:** Verify all paths and deployed database definitions before editing.
>
> **Required policy:** One account may be remembered on multiple installations, but may actively use the Launcher on only one installation at a time.

## Instructions to the implementing AI

You are implementing a coordinated Backend and Admin Web change for **Neko Family Proxy**.

Do not make assumptions from this prompt alone. Before editing:

1. Inspect the current repository, production migration history, deployed Supabase function definitions, Admin Web implementation, and tests.
2. Locate the latest effective definitions of:
   - `launcher.claim_session(text, text, text)`
   - `launcher.heartbeat_session(uuid)`
   - `launcher.release_session(uuid)`
   - `public.installations`
   - `public.launcher_sessions`
   - `public.products.max_devices`
   - `public.licenses.max_devices`
3. Confirm whether the Admin Web is in this repository or another repository. If it is elsewhere, inspect that source before changing it.
4. Preserve unrelated working-tree changes.
5. Use a new forward-only migration. Do not edit migrations already applied to production.
6. Implement with tests first and verify the real database behavior before claiming completion.

---

## 1. Business requirement

Change the device/session policy to:

> A user account may have multiple historical or remembered installations. Signing in from a new installation must not fail merely because another installation exists. However, one user account may have no more than one active Launcher session at a time. A successful claim from the newest installation replaces the previous active session.

Expected examples:

- Machine A signs in: success.
- Machine A signs in again with the same installation hash: success.
- Machine B signs in while Machine A has an active session: Machine B succeeds and replaces Machine A's session.
- Machine A's next heartbeat after replacement: returns `false`.
- Machine B's heartbeat: returns `true`.
- Machine A may later sign in again: success, replacing Machine B.
- An installation explicitly revoked by an administrator: rejected with `installation_revoked`.
- A restricted/suspended account: rejected according to the existing account restriction contract.
- A missing, expired, suspended, or revoked license: rejected with the existing license error behavior.

Do not interpret “one active session” as “one installation for the lifetime of the account.”

---

## 2. Current repository evidence to verify

The Launcher currently calls the Supabase RPC from:

- `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py`

It sends:

```json
{
  "p_product_code": "neko-family-proxy",
  "p_installation_key_hash": "<64 lowercase hexadecimal SHA-256 characters>",
  "p_display_name": "<display name up to 120 characters>"
}
```

The Launcher installation identity is generated and persisted locally by:

- `launcher/src/neko_launcher/infrastructure/storage/installation.py`

It is a random installation secret stored in the secure store and then SHA-256 hashed. It is not a hardware fingerprint. Reinstalling Windows, clearing secure storage, or moving the app may therefore create a new installation hash even on the same physical computer.

The repository currently contains device-limit logic in the effective historical implementation of `launcher.claim_session`, including:

- rejection of a previously revoked installation with `installation_revoked`;
- counting non-revoked installation rows;
- rejection with `device_limit_reached` when the installation count reaches `max_devices`;
- revocation of the user's previous active Launcher session before insertion of a new session.

The database currently has a partial unique index equivalent to:

```sql
create unique index launcher_sessions_one_active_per_user_idx
on public.launcher_sessions (user_id)
where revoked_at is null;
```

Verify these facts against the deployed environment. Repository migrations may not by themselves prove the live definition.

---

## 3. Required Backend behavior

### 3.1 Preserve the RPC signature

Keep this RPC signature unchanged:

```sql
launcher.claim_session(
  p_product_code text,
  p_installation_key_hash text,
  p_display_name text default null
) returns jsonb
```

Do not require a Launcher release solely because of a renamed function, changed argument, removed response field, or incompatible response type.

### 3.2 Remove installation-history limiting

In the latest effective `launcher.claim_session` definition:

- Remove the check that counts previous non-revoked installations and rejects a new installation when it reaches `max_devices`.
- Do not emit `device_limit_reached` merely because another installation exists in the account history.
- Do not delete old installation records as a workaround.
- Do not automatically revoke old installation records merely because a different installation becomes active.
- Keep `products.max_devices`, `licenses.max_devices`, and the `max_devices` response field for backward compatibility in this change unless a separately approved migration removes them.

The required change is to the interpretation of installation history, not a destructive schema cleanup.

### 3.3 Preserve explicit installation revocation

Retain the ability for an administrator to deny a specific installation.

If an existing row for the same `(user_id, installation_key_hash)` has `revoked_at is not null`, `claim_session` must reject it with:

```text
installation_revoked
```

Do not silently un-revoke it during login.

Important security limitation:

- Installation identity is locally generated, not hardware-attested.
- A user who clears secure storage may receive a new installation hash.
- Therefore installation revocation is not equivalent to an account ban.
- Use account restriction/suspension to block the entire account.

### 3.4 Upsert or refresh the current installation

Within `claim_session`:

- Find the installation by authenticated `user_id` and `p_installation_key_hash`.
- If absent, insert a new installation row.
- If present and not revoked, update `last_seen_at` and update the display name according to the existing normalization/length rules.
- Never trust a client-supplied user ID. Resolve the user from `auth.uid()`.
- Continue validating the installation hash as exactly 64 lowercase hexadecimal characters.
- Continue bounding the display name to 120 characters and handling empty values safely.

### 3.5 Replace the active session transactionally

A successful claim must:

1. Authenticate the user via `auth.uid()`.
2. Validate the request.
3. Verify product and account eligibility.
4. Select a currently valid license.
5. create/update the requested installation.
6. Revoke any current active session belonging to that user.
7. Insert the new active session bound to the selected installation and license.
8. Return the new session response.

Keep the per-user transaction lock or an equally strong serialization mechanism, such as:

```sql
perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));
```

Keep the unique partial index enforcing one active session per user. Do not remove or weaken it.

The revoke and insert operations must happen inside one database transaction. Concurrent claims from two installations must finish with exactly one active session.

### 3.6 Preserve heartbeat semantics

Keep the RPC signature:

```sql
launcher.heartbeat_session(p_session_id uuid) returns boolean
```

Required behavior:

- Return `true` only for the authenticated user's current, non-revoked session with a valid license and within the existing heartbeat freshness rules.
- Return `false` for a session replaced by a newer claim.
- Return `false` for a released/revoked session.
- Return `false` when its license is no longer valid.
- A heartbeat must never reactivate a revoked session.
- A heartbeat for an old session must not affect the new active session.

The current Desktop Launcher invokes heartbeat approximately every 30 seconds. Replacement is authoritative immediately in the database, while the old client may take up to its next heartbeat cycle to discover the replacement.

### 3.7 Preserve release semantics

Keep the RPC signature:

```sql
launcher.release_session(p_session_id uuid) returns boolean
```

Required behavior:

- Releasing the caller's current active session revokes that session and returns the existing success result.
- Releasing an already revoked or replaced session is a safe no-op according to the existing contract.
- Releasing an old session must never revoke a newer session.
- A user must not be able to release another user's session.

---

## 4. Wire contract with the Desktop Launcher

Keep the existing `claim_session` response fields and compatible types. It must include at least:

```json
{
  "session_id": "<UUID>",
  "installation_id": "<UUID>",
  "license_id": "<UUID>",
  "product_code": "neko-family-proxy",
  "valid_until": "<ISO-8601 timestamp with timezone>",
  "max_devices": 1
}
```

Rules:

- Do not rename or remove existing fields in this change.
- `session_id` must identify the newly active session.
- `valid_until` must remain parseable as an ISO-8601 timestamp by Python `datetime.fromisoformat` after replacing `Z` with `+00:00`.
- Keep `max_devices` for compatibility even though the new policy does not use it to limit historical installation rows.
- New response fields, if truly needed, must be optional and backward compatible.
- Do not send service-role credentials, internal SQL errors, tokens, or secrets in the response.

---

## 5. Error contract

Preserve safe, stable error codes for client mapping:

| Error code | Meaning under the new policy |
|---|---|
| `not_authenticated` | No valid authenticated Supabase user |
| `invalid_product` | Invalid product input or unavailable product according to existing policy |
| `invalid_installation` | Installation hash has invalid format |
| `license_invalid` | No currently valid license |
| `installation_revoked` | This exact installation was explicitly revoked |
| `account_restricted` | The entire account is restricted/suspended |
| `device_limit_reached` | Deprecated for the normal claim flow; must not be raised because historical installations exist |

Requirements:

- Do not leak raw database exception text to the public client.
- Do not change the meaning of `installation_revoked` into “another machine is active.”
- Another machine being active is not an error: a successful new claim replaces it.
- Keep authorization fail-closed for authentication, account, license, and explicit revocation failures.

The Desktop Launcher is prepared to map `installation_revoked` and legacy `device_limit_reached` to a typed device-authorization error. The Backend change should make `device_limit_reached` unreachable in the normal new policy while retaining safe compatibility with older deployments/clients.

---

## 6. Audit requirements

A successful replacement should create auditable records without secrets.

At minimum:

- Keep `session_claimed` for the new session.
- Record why an old session was revoked when it is replaced, preferably as `session_revoked` with a stable reason such as:

```json
{
  "session_id": "<old-session-uuid>",
  "reason": "replaced_by_new_session",
  "replacement_installation_id": "<new-installation-uuid>"
}
```

If the current audit implementation or constraints cannot accept the proposed metadata/event sequence, update it through a forward migration and add tests. Do not bypass constraints or omit auditing silently.

Never record:

- passwords;
- plaintext coupons;
- access tokens or refresh tokens;
- service-role keys;
- private keys;
- full authentication headers.

Installation hashes should be masked in Admin Web views unless an authorized operational workflow requires the complete value.

---

## 7. Required Admin Web changes

Inspect the actual Admin Web implementation and update every UI, API, validation rule, report, and help text that assumes one lifetime device per account.

### 7.1 Account and installation view

Show, where authorized:

- installation display name;
- masked installation hash;
- creation time;
- last-seen time;
- revoked status and revocation time;
- whether the installation owns the current active session;
- active session creation and last heartbeat time.

Do not label all historical installations as concurrently authorized sessions. Distinguish installation history from the one active session.

### 7.2 Admin actions

Support or preserve clearly separated actions:

- Revoke a specific installation.
- Restore/un-revoke an installation only if this is an approved administrative policy.
- Revoke the current active session.
- Restrict/suspend the entire account.
- Remove an account restriction through the approved workflow.

Each action must use a trusted server-side Admin API or Edge Function. Never expose a service-role key to browser JavaScript or the Desktop Launcher.

### 7.3 UI wording

Remove wording equivalent to:

> This account can only ever use one computer.

Use wording equivalent to:

> This account can be remembered on multiple computers but can be active on only one computer at a time. Signing in on another computer replaces the previous active session.

For installation revocation, use wording that makes the scope explicit:

> This installation is blocked. To block all computers, restrict the account instead.

### 7.4 Deprecated `max_devices` controls

If Admin Web currently edits `products.max_devices` or `licenses.max_devices`:

- Do not silently present those fields as the active concurrent-session policy.
- Hide them from ordinary operations or mark them deprecated pending a separately approved schema cleanup.
- Do not delete columns in this task unless all consumers have been inspected and a separate compatibility migration is approved.

---

## 8. Permissions and security constraints

Required:

- Client RPC access uses an authenticated Supabase session and a publishable key only.
- `claim_session`, `heartbeat_session`, and `release_session` remain authenticated-only.
- Security-definer functions must set a safe, explicit `search_path`.
- Resolve account identity from `auth.uid()`; never accept user identity from request parameters.
- Preserve RLS and least-privilege grants.
- Admin operations run only in a trusted server environment with actor authorization and audit logging.
- Preserve account/license/revocation fail-closed behavior.

Forbidden:

- Embedding a service-role or secret key in Admin browser code or Launcher code.
- Removing the one-active-session unique index.
- Allowing the client to choose another user ID.
- Treating display name as a trusted device identifier.
- Automatically clearing explicit installation revocation on login.
- Returning raw SQL errors, stack traces, tokens, or secrets.
- Editing old production migrations in place.

---

## 9. Required tests

Write tests before implementation and show that they fail for the old behavior.

### 9.1 Claim tests

1. A valid license and first installation can claim a session.
2. The same installation can claim again; the newest session is active and the previous session is revoked.
3. A different installation can claim even when historical installations already exist.
4. A different installation can claim even when `max_devices = 1`.
5. A new claim replaces the previous active session.
6. An explicitly revoked installation receives `installation_revoked`.
7. A new, non-revoked installation is not rejected because another installation is revoked or historical.
8. Invalid installation hashes are rejected.
9. Missing/expired/suspended/revoked licenses are rejected.
10. Restricted accounts are rejected according to the current account contract.
11. Unauthenticated calls are rejected.

### 9.2 Concurrency tests

1. Run concurrent claims from two different installation hashes for the same user.
2. Confirm both requests do not leave two active sessions.
3. Confirm exactly one active session remains after both transactions finish.
4. Confirm the surviving session is internally consistent with its installation and license.
5. Confirm the unique partial index remains present and valid.

Do not weaken or remove the unique index merely to make a concurrency test pass.

### 9.3 Heartbeat tests

1. Newest session heartbeat returns `true`.
2. Replaced session heartbeat returns `false`.
3. Released session heartbeat returns `false`.
4. Expired-license session heartbeat returns `false`.
5. Heartbeat of an old session cannot modify/revoke/reactivate the newest session.

### 9.4 Release tests

1. Releasing the current session succeeds according to the existing return contract.
2. Releasing the same session again is a safe no-op.
3. Releasing an old/replaced session does not revoke the current session.
4. A user cannot release another user's session.

### 9.5 Admin Web tests

1. Installation history and active session are displayed as separate concepts.
2. Revoke-installation affects only that installation.
3. Account restriction blocks all installations.
4. Browser requests never contain a service-role key.
5. Unauthorized admins cannot invoke device/session/account actions.
6. UI copy describes one active session, not one lifetime device.

### 9.6 Integration/E2E scenario

Using disposable authenticated test users and approved test data:

1. Sign in as the same user from Gateway/Client A and claim installation A.
2. Heartbeat A and confirm `true`.
3. Sign in as the same user from Gateway/Client B and claim installation B.
4. Confirm B claim succeeds even when `max_devices = 1`.
5. Heartbeat A and confirm `false`.
6. Heartbeat B and confirm `true`.
7. Claim A again and confirm it succeeds and replaces B.
8. Revoke installation A through the trusted Admin path.
9. Confirm A receives `installation_revoked` on its next claim.
10. Confirm B can still claim unless the account itself is restricted.
11. Restrict the account and confirm neither installation can claim.
12. Clean up all disposable users, sessions, licenses, installations, and audit fixtures through an approved workflow.

---

## 10. Migration requirements

Create a new timestamped forward migration. The migration must:

- `create or replace` the latest `launcher.claim_session` definition using the unchanged signature;
- preserve validation, product lookup, account eligibility, license selection, advisory locking, installation revocation, active-session replacement, response compatibility, safe `search_path`, and permissions;
- remove only the historical-installation count rejection;
- add/adjust audit behavior if required;
- reassert function grants only where necessary;
- avoid destructive installation/schema cleanup;
- be safe to apply once to staging and then production;
- include a rollback or forward-fix strategy in the handoff notes, without relying on editing migration history.

Before applying to production, compare the migration's `create or replace function` body against the live `pg_get_functiondef(...)` result so that newer production checks are not accidentally overwritten by an older repository function body.

---

## 11. Coordination contract with the Launcher team

The Backend team must provide the following to the Launcher team:

1. Migration filename and commit/revision.
2. Staging deployment confirmation.
3. Exact deployed `claim_session`, `heartbeat_session`, and `release_session` signatures.
4. Response fixture from a successful claim with secrets removed.
5. Error matrix showing that:
   - new installation with historical devices: succeeds;
   - replacement of active session: succeeds;
   - old heartbeat after replacement: `false`;
   - explicitly revoked installation: `installation_revoked`;
   - expired/missing license: `license_invalid`;
   - restricted account: approved restriction error;
   - `device_limit_reached`: not emitted by normal policy.
6. Concurrency-test evidence proving one active session per user.
7. Admin Web behavior and authorization-test evidence.
8. Audit event examples with sensitive values removed.
9. Confirmation that no service-role/secret key is exposed to clients.
10. Production rollout and rollback/forward-fix plan.

The Launcher team will match this contract by:

- continuing to send the same RPC parameters;
- accepting the same response fields;
- treating a successful newest claim as the active session;
- using heartbeat to detect replacement;
- returning to Login when the active session is revoked/replaced;
- treating `installation_revoked` as a hard device authorization denial;
- retaining legacy safe handling for `device_limit_reached` while expecting it not to occur under the new Backend policy.

Do not require additional incompatible Launcher wire changes. The Launcher may ship preparatory session-cleanup and typed-error handling before Backend staging, while production activation of the new multi-installation policy still requires the Backend evidence above.

---

## 12. Acceptance criteria

The task is complete only when all of the following are true:

- [ ] A new installation can claim even when the account has previous installations and `max_devices = 1`.
- [ ] Returning to a previously used, non-revoked installation succeeds.
- [ ] An explicitly revoked installation remains rejected.
- [ ] A successful claim revokes/replaces the previous active session.
- [ ] Exactly one active session exists per account after sequential and concurrent claims.
- [ ] Old-session heartbeat returns `false`; newest-session heartbeat returns `true`.
- [ ] Releasing an old session cannot revoke the newest session.
- [ ] RPC signatures and response fields remain backward compatible.
- [ ] Admin Web distinguishes installation history, active session, installation revocation, and account restriction.
- [ ] No service-role key or secret is exposed to a browser or Launcher.
- [ ] Focused unit/contract tests pass.
- [ ] Database integration and concurrency tests pass in staging.
- [ ] Security/RLS/grant checks pass.
- [ ] Supabase security advisors have no new ERROR/WARN findings caused by this change.
- [ ] Disposable staging data is cleaned up.
- [ ] Backend provides the Launcher coordination evidence listed above.

---

## 13. Required final report from the implementing AI

Return a concise implementation report containing:

1. Root cause and old policy.
2. Files and repositories changed.
3. New migration path and summary.
4. Admin Web changes.
5. Exact preserved RPC contract.
6. Error behavior before and after.
7. Test commands and exact pass/fail counts.
8. Concurrency evidence.
9. Staging deployment status.
10. Security/RLS/advisor results.
11. Remaining blockers or decisions.
12. Rollout and rollback/forward-fix instructions.
13. Explicit statement of whether production was modified.

Do not claim production completion from unit tests alone. Production activation requires reviewed migration evidence, staging E2E results, security checks, and explicit release approval.
