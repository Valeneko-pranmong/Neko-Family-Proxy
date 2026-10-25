# Launcher Bridge — Staging Deployment and E2E Runbook

**Scope:** staging verification of the 5.2.0 web-auth bridge and
`launcher_v2` schema only. This runbook must not be used to mutate production,
change 5.1.6, or publish a release.

## 1. Prerequisites

- Supabase CLI or approved hosted migration access for the staging project.
- A staging identity deployment and test Discord account.
- An approved test entitlement path for a new 5.2.0 account.
- `NEKO_AUTH_BRIDGE_URL` pointing at the staging bridge function.
- No production service-role key, identity token, proxy password, or private
  key in the repository, screenshots, shell history, or support reports.

## 2. Apply migrations in order

Apply only after the P0 decisions and staging review are approved:

```text
20261025130000_create_launcher_v2_auth_foundation.sql
20261025131000_create_launcher_v2_claim_permit.sql
20261025132000_add_launcher_v2_bridge_support.sql
```

If the permit rate-limit migration is not already present in staging, apply
`20261024120000_permit_rate_limit.sql` through the normal approved path.

Verify after migration:

- `launcher_v2` exists and is in the Data API schema list.
- `launcher_v2` tables have RLS enabled and forced.
- `authenticated` has no direct table grants.
- `service_role` can execute the four bridge helper functions.
- The shared Auth trigger routes only `app_metadata.auth_line = next` users to
  `launcher_v2.profiles`.
- Existing 5.1.6 login/session/permit behavior is unchanged.

## 3. Deploy the bridge

Deploy the reference function with gateway JWT verification disabled because
the identity token is not a Supabase JWT:

```text
supabase functions deploy launcher_bridge --no-verify-jwt
```

Set secrets through the approved Supabase secret mechanism; never commit an
env file:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
NEKO_IDENTITY_BASE_URL
NEKO_IDENTITY_JWKS_URL
NEKO_IDENTITY_ISSUER
NEKO_IDENTITY_AUDIENCE=neko-launcher-bridge
```

Confirm the deployed function URL and that `cache-control: no-store` is
present on responses.

## 4. Prepare the staging test account

1. Run the Launcher with the staging bridge and complete one Discord browser
   login. The bridge creates a no-password next-line Auth user and an
   `identity_links` row.
2. The first claim is expected to fail with `license_invalid` until an
   entitlement is provisioned.
3. In the staging project only, provision a short-lived license for that user:

```sql
-- STAGING ONLY. Replace the placeholder; never run this against production.
insert into launcher_v2.licenses (user_id, product_id, valid_from, valid_until)
select '<test-user-id>'::uuid, id, now(), now() + interval '1 day'
from launcher_v2.products
where code = 'neko-family-proxy';
```

4. Restart the Launcher login and verify the next-line session claim.

Do not put this SQL, test user IDs, test coupons, or staging tokens in the
production install root or release bundle.

## 5. E2E verification

Run with a 5.2.0 build and staging-only environment:

```text
NEKO_WEB_AUTH_ENABLED=1
NEKO_AUTH_BRIDGE_URL=https://<staging-project>.supabase.co/functions/v1/launcher_bridge
NEKO_IDENTITY_BASE_URL=https://<staging-identity>
```

Verify in this order:

- [ ] Browser opens the identity Discord flow and returns to the exact loopback
      callback.
- [ ] Identity code exchange succeeds and the bridge returns a Supabase session.
- [ ] `launcher_v2.web_sessions` has one active allowlist row for the minted
      `auth_session_id`.
- [ ] `launcher_v2.sessions` has one active session and the previous session is
      revoked.
- [ ] `launcher_v2.heartbeat_session` succeeds while the license is active.
- [ ] `launcher_v2.authorize_launch_permit` returns the expected state; the
      legacy `issue_launch_permit` Edge Function still needs its P2 v2 route.
- [ ] A normal password session from the shared Auth pool cannot claim a
      next-line session or obtain a next-line permit.
- [ ] A replayed identity token returns `409 token_replayed`.
- [ ] A session without an allowlist row is rejected.
- [ ] An expired/suspended license or profile is rejected.
- [ ] No identity token, Supabase access/refresh token, service-role key, or
      proxy credential appears in logs, screenshots, or test evidence.
- [ ] Refresh the Supabase session and re-run claim/heartbeat/permit. Record
      whether `auth.sessions.id` remains stable; if it changes, implement the
      allowlist rotation before continuing.

## 6. P2 handoff

After P1 staging evidence:

- Add the v2 permit route to the Edge Function/Launcher.
- Remove password/recovery from the 5.2.0 client.
- Run the full 5.2.0 E2E through Core start.
- Keep 5.1.6 on its legacy path and do not publish 5.2.0.

## 7. Rollback

- Disable `NEKO_WEB_AUTH_ENABLED` and clear `NEKO_AUTH_BRIDGE_URL` in staging.
- Disable or undeploy `launcher_bridge`.
- Delete only the staging test rows created for this run.
- Do not drop production schema, revoke production Auth users, or alter 5.1.6.
- Preserve logs without tokens for the evidence record.

## 8. Do not

- Do not apply these migrations to production from this runbook.
- Do not use a real customer account or coupon for staging.
- Do not log or paste identity/session tokens.
- Do not put test data in the production install root.
- Do not publish, tag, or claim Authenticode signing from this runbook.
