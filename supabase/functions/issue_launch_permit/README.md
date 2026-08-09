# `issue_launch_permit` production candidate

> **Status: LOCAL CANDIDATE / NOT DEPLOYED — reviewed 9 August 2026.**
> Production remains blocked until the forward migration is reviewed/applied in
> staging, the configured signing private key is proven to match Core's approved
> bundled public key, and cross-repository integration/security review passes.

The function validates the caller's Supabase access token with Supabase Auth,
resolves the authoritative Launcher session/license state through a narrow
authenticated RPC, and returns a 30-second RS256 compact JWT. It never accepts
identity, session, installation, license, issuer, audience, expiry, or key ID
from the request body.

## Request

Exact JSON fields (unknown, missing, wrong-case, and wrong-type fields fail):

- `version`: integer `1`
- `contractRevision`: `s0-rc1`
- `correlationId`: 32 lowercase hexadecimal characters
- `challenge`: 43-character unpadded base64url (Core CSPRNG 32-byte challenge)
- `configurationDigest`: 64-character lowercase hexadecimal SHA-256
- `processName`: `pso2.exe`
- `targetPid`: integer `1..4294967295` (boolean/float invalid)
- `mode`: `ProcessMode`
- `product`: `neko-family-proxy`
- `scope`: `proxy:start`

The `Authorization` header must contain a valid non-anonymous Supabase access
token. Gateway JWT verification remains enabled and the function independently
calls Supabase Auth `getUser`.

## Authoritative state

Migration `20260809150000_bind_permits_to_auth_sessions.sql` adds the minimum
missing identity binding:

- a trigger stores the validated `auth.jwt().session_id` on every new
  `launcher_sessions` row;
- historical unbound rows fail closed and require a fresh normal session claim;
- `launcher.authorize_launch_permit(text, text)` reserves the challenge and returns identity only when the caller's
  Auth session owns the one active, heartbeat-fresh Launcher session and its
  profile, product, installation relationship, and selected license are valid;
- existing RLS and the one-active-session unique partial index remain unchanged;
- remembered installations are not a permanent authorization lock.

This prevents an old Machine A Auth token from being relabeled with Machine B's
new authoritative Launcher session after replacement.

Forward migration
`20260809233000_bind_session_controls_and_bound_permit_ledgers.sql` also:

- requires `heartbeat_session` and `release_session` to use the exact live Auth
  session that claimed the Launcher session;
- keeps both controls fail closed for missing, malformed, expired, or other-session
  JWT `session_id` values;
- prunes only the current user's replay/rate rows older than ten minutes while
  holding the issuance transaction lock; and
- adds global `issued_at` indexes for controlled retention maintenance without
  granting clients direct ledger access.

## Permit

Header is exactly `alg=RS256`, `typ=neko-launch+jwt`, and server-configured
`kid`. Claims are exactly `iss`, `aud`, `sub`, `sid`, `iid`, `lid`, `product`,
`scope`, `cfg`, `challenge`, `target_pid`, `mode`, `jti`, `iat`, `nbf`, and
`exp`. Identity claims come only from the RPC. `iat=nbf`, `exp=iat+30`, and
`jti` is a cryptographic UUID.

Required server-only configuration:

- `RS256_PRIVATE_KEY`: PKCS#8 PEM private key
- `RS256_KID`: exact key ID accepted by Core
- standard Supabase `SUPABASE_URL` and `SUPABASE_ANON_KEY`

Core source currently pins `kid=neko-prod-key-1` and an immutable bundled RSA
public key. Do not generate, rotate, or provision production signing material
until custody review proves the backend private key matches that public key.

## Replay, replacement, and rate policy

The permit RPC is the issuance linearization point. It takes the same per-user
transaction advisory lock as `claim_session`, checks that the JWT `session_id`
still exists in `auth.sessions`, evaluates the current Launcher/profile/license
state, and reserves the challenge before returning trusted signing claims.
Session replacement therefore cannot interleave with that decision.

Reservations reject reuse of the same `(auth_session_id, challenge)`. A separate
per-user rate-event ledger survives Auth-session deletion and limits each user
to 10 issuance reservations per rolling minute. A reservation is
committed before signing; an ambiguous/signing failure must start again with a
new Core challenge rather than retrying the old request. Core separately
atomically consumes its one-use challenge and permit `jti`. A successfully
issued JWT is an intentionally short 30-second authority snapshot; later
revocation cannot retroactively retract an already signed capability.
The ten-minute retention boundary is intentionally longer than both the
30-second challenge/permit lifetime and the one-minute rate window.

## Errors and secrecy

Responses use sanitized HTTP classes: `400` protocol, `401` authentication,
`403` session/authorization, `500` signing configuration, and `503` dependency
failure. No raw token, permit, key, SQL error, or stack trace is logged/returned.

## Local validation

```bash
npx --yes tsx --test service_test.ts migration_contract_test.ts runtime_contract_test.ts
npx --yes deno check index.ts service.ts local_verifier.ts
npx --yes deno fmt --check index.ts service.ts local_verifier.ts *_test.ts
```

Tests use a generated in-memory test keypair only. They do not use production
credentials, mutate hosted Supabase, deploy a function, or validate the real
production private/public key pairing.
