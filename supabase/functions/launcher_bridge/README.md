# launcher_bridge

Reference proxy-backend bridge for the 5.2.0 web-auth line.

The Launcher posts a custom identity JWT here after the browser/loopback
exchange. The bridge validates the token, consumes its `jti`, creates or
resolves the next-line account, mints a real Supabase Auth session, records the
web-session allowlist row, and returns the Supabase access/refresh tokens.

This function is intentionally not the legacy password path. It only handles
`app_metadata.auth_line = "next"` users and the private `launcher_v2` schema.

## Contract

```text
POST /functions/v1/launcher_bridge
Authorization: Bearer <identity access_token>
Body: {} or empty
```

Success:

```json
{
  "token_type": "Bearer",
  "access_token": "<supabase access token>",
  "refresh_token": "<supabase refresh token>",
  "expires_in": 3600
}
```

Errors:

- `401 invalid_token`
- `409 token_replayed`
- `409 identity_not_linked` (identity/user link conflict)
- `400 invalid_request`
- `405 MethodNotAllowed`
- `503 upstream_unavailable`

All responses use `cache-control: no-store`. Identity and Supabase tokens are
never logged.

## Required configuration

Set these as Supabase Edge Function secrets/environment variables:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
NEKO_IDENTITY_BASE_URL=https://neko-network-id.vercel.app
NEKO_IDENTITY_JWKS_URL=https://neko-network-id.vercel.app/.well-known/jwks.json
NEKO_IDENTITY_ISSUER=https://neko-network-id.vercel.app
NEKO_IDENTITY_AUDIENCE=neko-launcher-bridge
```

`SUPABASE_SERVICE_ROLE_KEY` is server-only. Never put it in the Launcher, a
browser bundle, the repository, logs, or support reports.

## Deployment

The identity token is not a Supabase JWT, so the function must run with
gateway JWT verification disabled:

```text
supabase functions deploy launcher_bridge --no-verify-jwt
```

Then set the Launcher bridge URL, for example:

```text
NEKO_AUTH_BRIDGE_URL=https://<project-ref>.supabase.co/functions/v1/launcher_bridge
```

Do not enable `NEKO_WEB_AUTH_ENABLED=1` in production until the staging E2E
passes.

## Account creation

For a new identity, the bridge calls Supabase Admin `createUser` with:

- a deterministic synthetic email derived from the identity `sub`;
- `email_confirm: true`;
- no password;
- `app_metadata.auth_line = "next"`;
- `app_metadata.identity_sub = <identity sub>`;
- the identity username/display name.

The shared Auth trigger routes that user to `launcher_v2.profiles`. The bridge
then calls `launcher_v2.bridge_link_identity` and, after minting the session,
`launcher_v2.bridge_record_web_session`. A normal password session in the
shared Auth pool has no `launcher_v2.web_sessions` allowlist row and cannot
claim a 5.2.0 Launcher session or obtain a permit.

## Session minting

The implementation uses Supabase Admin `generateLink({ type: "magiclink" })`
followed by the anon client's `verifyOtp` with the returned hashed token. This
does not send an email in the intended flow, but the staging project must
confirm that the email provider configuration permits admin-generated
magiclink verification. If it does not, replace only `mintSession` with the
approved server-side session-minting method; do not weaken the allowlist.

The bridge records `auth.sessions.id` from the returned access token. P1 E2E
must verify that this ID remains stable across refresh; if Supabase rotates it,
the bridge must update the allowlist row during refresh.

## Replay and failure behavior

`launcher_v2.consume_bridge_jti` performs a one-use insert keyed by `jti`.
Expired replay rows are pruned after one hour. A transient failure after JTI
consumption forces the user to restart the browser login; this is intentional
fail-closed behavior.

## Tests

The pure handler and JWT/JWKS verifier are tested with Node 24:

```text
node --test supabase/functions/launcher_bridge/service_test.ts \
  supabase/functions/launcher_bridge/identity_test.ts
```

The database contract tests are in
`launcher/tests/test_launcher_v2_bridge_support_migration.py`.

## Status

Reference implementation only. The migrations have not been applied to
production, staging accounts are not provisioned, and the full
loopback -> identity -> bridge -> Supabase -> claim/permit -> Core E2E remains
a P1/P4 gate.
