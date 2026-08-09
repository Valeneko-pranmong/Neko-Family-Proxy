# Phase 2 Production Deployment and Rollback Plan

Status: **NOT AUTHORIZED FOR EXECUTION**  
Target project: `miikoutrnxsunbndecqh` (production authority; private configuration)  
Required approval: separate explicit Phase 3 production approval

This plan is ready for controlled execution only after the Phase 2 report has no open signing-key, hosted-staging, real-Core-crypto, Windows E2E, or secret-review blockers. Phase 2 itself must not change production.

## Preconditions

1. Pin Launcher/Backend source and released Core artifacts by full commit and cryptographic hash.
2. Require clean canonical branches and passing canonical Backend, Launcher, Core, disposable-database, hosted-staging, and Windows E2E evidence.
3. Reconfirm the exact production project ref before every remote command. Do not rely on a saved link alone.
4. Verify an approved production signing secret is already in custody and derives the public key pinned by the released Core under KID `neko-prod-key-1`. Record only KID, safe fingerprints, and pass/fail.
5. Export a production database backup/PITR recovery point and record the pre-change migration list, deployed Edge Function version, configuration, and safe signing-key fingerprints. Do not export secret values.
6. Establish an operator, independent verifier, observation window, rollback owner, and a change freeze for Launcher session/permit changes.

## Exact deployment order

### 1. Database migration

1. Assert the CLI/link target is exactly `miikoutrnxsunbndecqh`.
2. Run the linked migration list and retain sanitized evidence.
3. Run `supabase db push --linked --dry-run` without `--include-all`.
4. Continue only if the pending repository migrations are exactly, and in this order:
   - `20260809150000_bind_permits_to_auth_sessions.sql`;
   - `20260809233000_bind_session_controls_and_bound_permit_ledgers.sql`.
   Stop on history divergence, an unexpected migration, or an order mismatch.
5. Apply those forward migrations once with `supabase db push --linked`.
6. Do not deploy the Edge Function yet.

The first migration adds nullable `public.launcher_sessions.auth_session_id`.
Existing historical rows remain nullable and cannot authorize permits; a fresh
Launcher claim binds a validated Auth session. The second migration binds
heartbeat/release controls to that exact live Auth session and bounds permit
ledger retention outside a conservative ten-minute window. These are intentional
fail-closed compatibility boundaries.

### 2. Migration verification

Before function deployment, verify live catalog and behavior:

- migration-list parity and a second dry-run reporting up to date;
- `launcher.authorize_launch_permit(text,text)`, `launcher.bind_launcher_auth_session()`, `launcher.heartbeat_session(uuid)`, and `launcher.release_session(uuid)` definitions match reviewed source;
- all four are `SECURITY DEFINER`, owned by the approved migration owner, and use fixed empty `search_path`;
- `PUBLIC` and `anon` cannot execute the permit RPC; only `authenticated` can;
- internal reservation/rate tables and sequences have no direct `anon`/`authenticated` access and have RLS enabled;
- retention indexes exist and cleanup removes only rows older than ten minutes;
- a second Auth session for the same user cannot heartbeat or release the current Launcher session;
- `launcher_sessions_one_active_per_user_idx` remains valid, unique on `user_id`, with predicate `revoked_at is null`;
- Security Advisor output is captured and every warning classified;
- a disposable production-smoke account can freshly claim a session, while its pre-migration session cannot authorize a permit.

Stop before Edge deployment on any mismatch, unexpected migration, grant expansion, invalid index, Security Advisor regression, or failed fresh-claim behavior.

### 3. Signing-secret verification

Inside approved custody, without printing or exporting the private key:

1. Load the existing `RS256_PRIVATE_KEY` secret and derive only its public key/fingerprints.
2. Compare them to the exact public key embedded in the released Core artifact for KID `neko-prod-key-1`.
3. Independently sign a synthetic non-production challenge and verify it with the exact released Core verifier when approved.
4. Record only KID, safe fingerprints, Core build hash, and PASS/FAIL.
5. Do not rotate, replace, or generate a production key during this deployment.

Stop if custody, provenance, KID, or fingerprints do not match exactly.

### 4. Edge Function deployment

1. Reassert the exact production project ref.
2. Confirm `supabase/config.toml` keeps `[functions.issue_launch_permit] verify_jwt = true`.
3. Deploy only `issue_launch_permit` from the pinned source revision.
4. Do not change signing secrets as part of function deployment.
5. Record the deployed function identifier/version and source commit.

### 5. Function health verification

Using a disposable production-smoke account and no printed tokens/permits, verify:

- missing and invalid JWT are denied by the Gateway;
- malformed request is denied with a typed sanitized response;
- a replaced/old session is denied;
- a fresh current session with active profile/license/product is accepted;
- the returned permit verifies with the exact released Core;
- no Authorization header, access/refresh token, raw permit, service-role key, password, private key, or SQL detail appears in retained logs.

Immediately disable/roll back the function on any unexpected success, cross-user authority, secret exposure, 5xx surge, or Core rejection.

### 6. Launcher E2E

Roll out first to an internal canary Launcher bound to the pinned Core artifact. Require the observed sequence:

`GAME_PROCESS_DETECTED → PROXY_START_REQUESTED → COMMAND_VALIDATE → ACCESS_CONTEXT_VALIDATE → TARGET_WAIT → HOST_START → CONTROL_CHANNEL_WAIT → TARGET_RECHECK → CHALLENGE_REQUEST → TARGET_BIND → PERMIT_REQUEST → AUTHORIZED_START → RUNNING_VERIFY`

Require final `CoreStatus.RUNNING`, a live `NekoProxyCore.exe`, no `PERMIT_REQUEST FAILED`, and no immediate `CLEANUP`. Then run A→B→C→A replacement and verify old Launchers receive no new permits. Hold general rollout until the observation window completes.

## Rollback criteria

Rollback immediately for any of:

- migration/catalog/grant/index mismatch;
- permit issued for an old, wrong-user, wrong-installation, revoked, stale, inactive, expired, or wrong-product state;
- signature/KID/fingerprint mismatch or Core valid-permit rejection;
- Gateway JWT bypass or `verify_jwt` disabled;
- replay/rate/concurrency invariant violation;
- secret/token/raw-permit leakage;
- material Edge 5xx increase, Launcher launch regression, Core crash/cleanup loop, or inability to reach `RUNNING` in the canary;
- loss of exactly-one-active-session behavior.

## Exact rollback strategy

The database migration is forward-only once real sessions begin using `auth_session_id`; do **not** immediately drop the column, trigger, RPC, or ledger tables.

1. Stop Launcher rollout and preserve evidence.
2. Disable or redeploy `issue_launch_permit` to the previously recorded fail-closed function version. If a safe prior function cannot run against the forward schema, disable permit issuance entirely rather than bypass authorization.
3. Keep the forward database schema in place. It is additive and existing rows with null `auth_session_id` fail closed.
4. Revert Launcher distribution to the prior signed artifact if the defect is client-side. Do not weaken Core or permit requirements.
5. If necessary, revoke current Launcher sessions to force fresh claims after the corrected function/client is deployed. This interrupts users but preserves authority.
6. Correct the issue through a new reviewed forward migration or function revision, repeat staging and canary gates, then resume.
7. Only consider destructive database reversal during a separately approved outage after proving no rows, foreign keys, reservations, rate events, or deployed code depend on `auth_session_id`. Restore from the recorded backup/PITR point if data-level reversal is unavoidable.
8. Do not rotate the Core key or production signing secret as a rollback shortcut. Key compromise follows a separate emergency rotation procedure requiring coordinated Backend and Core release.

## Completion record

The Phase 3 operator must record: exact source commits, Core artifact hashes, project-ref guards, migration before/after lists, safe signing fingerprints/KID, function deployment identifier, health/E2E outcomes, Security Advisor result, observation window, and whether rollback was invoked. Secret values and raw permits are prohibited from the record.
