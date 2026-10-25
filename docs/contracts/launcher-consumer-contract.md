# Launcher Consumer Contract — Neko Proxy API v1

**Status:** P0 draft for sign-off
**Applies to:** the new Launcher line (target `5.3.0` cutover line and later)
**Does not apply to:** `5.1.6` or any legacy build, which remains on its frozen
Supabase/password backend
**Baseline:** NEKO Unified Platform, contract baseline v0 (2026-10-25)
**Companion documents:** [gap-and-conflict-register.md](gap-and-conflict-register.md),
[p0-signoff-checklist.md](p0-signoff-checklist.md)

The words MUST, MUST NOT, SHOULD, and MAY are used normatively. Items marked
**PENDING** are not defined in contract baseline v0 and require an owner
decision before P1 implementation.

## 1. Trust boundary

```text
Discord / browser
      |
      | authorization code + PKCE (loopback)
      v
Neko-NETWORK-ID (identity provider)
      |
      | RS256 access token (aud=neko-proxy-api) + opaque refresh token
      v
NekoLauncher  ----------------------->  Neko Proxy API v1
      |                                  (accounts, licenses, sessions,
      |                                   permits, runtime config, metrics)
      |
      | signed permit + Runtime Config v1 over the local Core pipe
      v
NekoProxyCore (unchanged)
```

The Launcher:

- is a **public OAuth client**. It has no client secret and no service token.
- calls the identity provider only for `GET /launcher/authorize`,
  `POST /api/launcher/token`, and token revocation once that endpoint is
  defined (section 4.6).
- calls Neko Proxy API only for proxy-domain data.
- never talks to Supabase, PostgREST, Supabase Auth, or the proxy database.
- treats the access token as an opaque bearer credential. It MUST NOT validate
  the JWT signature itself, call JWKS, or accept claims from the token as
  authorization. Authorization is decided by Neko Proxy API.
- never calls `/v1/admin/*`, never requests `proxy:admin`, and never holds a
  service JWT.

Neko Proxy API may use the transitional `launcher_v2.identity_links` mapping
during its own migration. The Launcher never reads that table and never relies
on an allowlist; mapping is a server-side identity-to-proxy-account concern.

The only local authorization input is the current in-memory session state. It
is never sufficient to start Core without a fresh server heartbeat and a newly
issued permit.

## 2. Consumed endpoints

| System | Method and path | Authentication | Contract status |
| --- | --- | --- | --- |
| Identity | `GET /launcher/authorize` | Browser, PKCE S256 | Existing; exact values below |
| Identity | `POST /api/launcher/token` (`authorization_code`) | PKCE verifier | Existing; **refresh grant PENDING** |
| Identity | `POST /api/launcher/token` (`refresh_token`) | Rotating refresh token | **PENDING — not implemented by live identity** |
| Identity | `GET /.well-known/jwks.json` | None | **Not consumed by the Launcher**; server-side verifiers only |
| Proxy API | `GET /v1/me` | Bearer access token | v0 |
| Proxy API | `POST /v1/session/claim` | Bearer access token | v0; request schema **PENDING** |
| Proxy API | `POST /v1/session/heartbeat` | Bearer access token | v0; request schema **PENDING** |
| Proxy API | `POST /v1/session/release` | Bearer access token | v0; request schema **PENDING** |
| Proxy API | `POST /v1/launch-permit` | Bearer access token | v0; request/response schema **PENDING**, Core shape frozen |
| Proxy API | `POST /v1/coupons/redeem` | Bearer access token | v0; request/response schema **PENDING** |
| Proxy API | `GET /public/status` | None | v0; response schema **PENDING** |
| Proxy API | `/v1/admin/*` | Service JWT only | **Forbidden to the Launcher** |

Scope matrix from v0:

| Endpoint | Required scope |
| --- | --- |
| `/v1/me` | `proxy:read` |
| `/v1/session/claim`, `/v1/session/heartbeat`, `/v1/session/release` | `proxy:launch` (assumed; confirm) |
| `/v1/launch-permit` | `proxy:launch` |
| `/v1/coupons/redeem` | **PENDING** — not covered explicitly by `proxy:launch proxy:read` |
| `/public/status` | None |
| `/v1/admin/*` | `proxy:admin` (Launcher never uses it) |

Access token shape from v0: `RS256`, `iss=<identity origin>`,
`aud=neko-proxy-api`, `sub=<identity user uuid>`,
`scope="proxy:launch proxy:read"`, `jti`, `iat`, `exp`, `nbf`; 10-minute
lifetime. The Launcher does not inspect these claims; they are recorded for
contract review only.

## 3. Configuration and build separation

### 3.1 New line

The new line needs only:

| Setting | Rule |
| --- | --- |
| Neko Proxy API base URL | HTTPS origin, no path, query, or fragment. Production value compiled in; environment override allowed only in non-frozen development builds. |
| Identity base URL | HTTPS origin; defaults to the locked identity origin. |
| OAuth client ID | `neko-launcher`. |
| Redirect URI | `http://127.0.0.1:53682/auth/callback` exactly. |
| Loopback port | `53682`, fixed. No dynamic-port fallback. |

Proposed environment names for P1 (not part of the server contract):
`NEKO_PROXY_API_BASE_URL`, `NEKO_IDENTITY_BASE_URL`.

### 3.2 Forbidden in the new line

The new-line build MUST NOT contain, read, or ship:

- a Supabase URL, publishable key, anon key, service-role key, or JWT secret;
- a Supabase session or Supabase client;
- `NEKO_AUTH_BRIDGE_URL`, `launcher_bridge`, `launcher_v2.web_sessions`,
  `launcher_v2.identity_links`, or `NEKO_LAUNCHER_SCHEMA`;
- any Control Room admin URL or admin service-token path;
- any legacy password, registration, recovery, or password-change surface.

Presence of any of these in the new-line configuration is a release blocker,
not a runtime fallback.

### 3.3 Frozen line

`5.1.6` keeps its existing Supabase configuration and legacy backend. This
contract does not authorize changing, retiring, or re-pointing that line. The
new-line build selection must be explicit and testable so the legacy path
cannot accidentally consume the new API or the new path cannot read legacy
credentials.

## 4. Login and token lifecycle

### 4.1 Authorization request

The Launcher opens the system browser (never an embedded web view) at:

```text
GET {identity_base_url}/launcher/authorize
  ?response_type=code
  &client_id=neko-launcher
  &redirect_uri=http%3A%2F%2F127.0.0.1%3A53682%2Fauth%2Fcallback
  &state=<43-128 character URL-safe random value>
  &code_challenge=<S256(verifier)>
  &code_challenge_method=S256
```

The verifier MUST be 43–128 characters of `[A-Za-z0-9-._~]`, generated with a
cryptographically secure random source. `plain` is not acceptable.

### 4.2 Loopback callback

The Launcher MUST:

- bind only to `127.0.0.1:53682`, not `0.0.0.0` or a hostname;
- accept only `GET /auth/callback` on the exact host;
- reject duplicate or malformed query keys;
- compare `state` in constant time against the value for this attempt;
- accept the first valid callback only; later callbacks are rejected;
- treat `error=access_denied|server_error` as a terminal login failure;
- close the listener after the callback or after the 120-second timeout;
- never log the full callback URL, code, state, or verifier;
- send `Cache-Control: no-store`, `Pragma: no-cache`, `Referrer-Policy:
  no-referrer`, and `X-Content-Type-Options: nosniff` on the callback response.

The authorization code is opaque, single-use, and short-lived (60 seconds in the
live identity implementation). It MUST NOT be retried after an ambiguous code
exchange outcome.

### 4.3 Authorization-code exchange

```text
POST {identity_base_url}/api/launcher/token
Content-Type: application/json

{
  "grant_type": "authorization_code",
  "client_id": "neko-launcher",
  "code": "<opaque code>",
  "code_verifier": "<PKCE verifier>",
  "redirect_uri": "http://127.0.0.1:53682/auth/callback"
}
```

`redirect_uri` is required by the live identity implementation but is absent
from the v0 request sketch. Its inclusion is a **PENDING** contract correction,
not a Launcher-side workaround: the live server rejects the exchange without
it. The Launcher already sends it.

Successful response (v0):

```json
{
  "token_type": "Bearer",
  "access_token": "<opaque or JWT access token>",
  "refresh_token": "<opaque 256-bit refresh token>",
  "expires_in": 600,
  "scope": "proxy:launch proxy:read"
}
```

The Launcher MUST validate, before using the session:

- `token_type` is `Bearer` (case-insensitive);
- `access_token` and `refresh_token` are non-empty strings within the size
  bound;
- `expires_in` is a positive integer and not unreasonably large;
- the response is a JSON object, not an array, and within the response limit.

The access token is kept in memory only. The refresh token MUST be written
atomically to the OS credential vault **before** the login is reported as
successful. If secure storage is unavailable, login fails closed; there is no
plaintext fallback.

### 4.4 Refresh-token rotation

```text
POST {identity_base_url}/api/launcher/token
Content-Type: application/json

{
  "grant_type": "refresh_token",
  "client_id": "neko-launcher",
  "refresh_token": "<current refresh token>"
}
```

v0 states that refresh tokens are opaque, hashed at rest, valid for 30 sliding
days, rotated on every use, and that reuse revokes the entire session family.

Client obligations:

1. **Single-flight.** Never run two refreshes concurrently. A process-wide lock
   and the Launcher's single-instance guard are both required.
2. **Refresh before expiry.** Refresh no later than 60 seconds before
   `expires_in` elapses. Never send a token known to be expired if a refresh is
   possible.
3. **Atomic replacement.** Persist the new refresh token with a
   write-then-rename or equivalent atomic vault write before using the new
   access token. If persistence fails, fail closed to re-login.
4. **Never reuse the old token after a possible success.** If the refresh
   request outcome is ambiguous (timeout after transmission, connection reset
   after request write), do **not** resend the old refresh token. Under v0,
   that can revoke the family. Treat the stored session as unusable and require
   an interactive login.
5. **No retry on 400/401.** `invalid_token`, `invalid_grant`, or
   `token_expired` on refresh means the stored credential is dead. Clear it and
   sign out.
6. **Preserve on transport failure.** A network error or retryable 5xx does not
   invalidate the stored refresh token. Keep it, show a retryable state, and do
   not authorize a launch.

The ambiguous-outcome rule is a direct consequence of rotate-on-use plus
reuse-revocation. See register items G5/D3 for the requested contract
resolution (idempotent refresh or a bounded replay grace).

### 4.5 Storage

- Refresh token at rest: Windows Credential Manager or an equivalent
  OS-protected store, under a **new** service/key namespace for the new line.
- Access token: memory only; never written to disk, registry, logs, or crash
  reports.
- No read, import, or migration of `5.1.6` Supabase sessions, trust state, or
  credentials. The new line starts clean.
- Clear both tokens on explicit sign-out, invalid refresh, account suspension,
  or uninstall.

### 4.6 Sign-out

Contract baseline v0 does not define a refresh-token revocation endpoint.
Until one exists, the Launcher can only:

1. release the proxy session (`POST /v1/session/release`, best effort);
2. delete the local refresh token and access token;
3. return to signed-out state.

This is **not** a complete server-side logout: a copied refresh token could
remain valid for up to 30 days. A revocation endpoint is a **PENDING** blocker
for the security claim "sign-out terminates the session". See G5/D4.

### 4.7 Expiry and clock handling

- Use a monotonic clock plus `expires_in` for refresh scheduling. Do not trust
  the local wall clock for token lifetime.
- Do not parse or verify JWT claims as an authorization decision.
- If the device clock is wrong, the server remains authoritative. A permit may
  be rejected by Core (bounded 10-minute skew with a fresh challenge); the
  Launcher surfaces a retry, not a local bypass.
- On resume from sleep or a long pause, check expiry first, refresh if needed,
  then revalidate `/v1/me` before enabling launch.

## 5. HTTP and error policy

### 5.1 Transport

- HTTPS only for production identity and Proxy API endpoints. HTTP is allowed
  only for the exact loopback callback and for non-frozen local tests.
- Do not follow redirects on API or identity token requests. Treat a 3xx as a
  failure.
- Bound request bodies and response bodies (current Launcher limit: 64 KiB).
- Connect/read timeout: 10 seconds for API calls; 4 seconds for the public
  status display. Permit issuance is bounded by the existing 10-second
  orchestration timeout.
- Send `Accept: application/json`, `Content-Type: application/json` where a
  body exists, and `Authorization: Bearer <access_token>` on protected calls.
- Send a stable `User-Agent` containing `NekoLauncher/<version>`. Exact client
  version/protocol negotiation is **PENDING** (G17/D15).
- Do not send cookies, browser storage, Supabase keys, or query-string tokens.
- Do not log request bodies containing codes, tokens, permits, runtime
  credentials, or machine proofs.

### 5.2 Error envelope

v0 envelope:

```json
{
  "error": {
    "code": "invalid_token",
    "message": "human-readable, non-sensitive",
    "request_id": "opaque correlation id",
    "retryable": false
  }
}
```

Requirements:

- Parse the envelope strictly. A missing/invalid envelope is a protocol error,
  not a success.
- Preserve `code` and `request_id` for support diagnostics; never display raw
  server messages that may contain internals.
- Honor `retryable`; do not infer retryability from the HTTP status alone
  (except 429 and 5xx transport handling).
- Unknown error codes map to a generic failure. They never grant access and
  never trigger a fallback backend.
- Identity OAuth errors currently use a different shape
  (`{error, error_description}`). Whether identity is exempt from the shared
  envelope is **PENDING** (G12/D12). The Launcher can map both shapes, but the
  contract must say which is authoritative for new code.

### 5.3 Retries and idempotency

v0 requires `Idempotency-Key` on claim, permit, and redeem.

Client rules:

- Generate a new UUIDv4 key per logical operation, not per HTTP attempt.
- Reuse the **same** key for retries of that operation.
- Never reuse a key for a different body, account, session, code, or challenge.
- Do not automatically retry `POST /v1/session/claim`,
  `POST /v1/launch-permit`, or `POST /v1/coupons/redeem` without a key.
- `GET /v1/me` and `GET /public/status` are safe to retry with bounded backoff.
- A launch permit is bound to a Core challenge and a short lifetime. If the
  challenge or permit window is no longer valid, request a fresh challenge
  instead of replaying the idempotency key.
- On 429, honor `Retry-After` when present; otherwise use a bounded backoff and
  tell the user to wait. Never spin.
- On a retryable 5xx, retry only after the backoff budget; never fall back to a
  cached entitlement, cached session, unsigned permit, or legacy backend.

Exact idempotency semantics (key scope, TTL, body binding, response replay,
conflict status) are **PENDING** (G12/D13).

## 6. Session lifecycle

```text
SignedOut
  -> Authorizing (browser + PKCE)
  -> TokenReady (access + refresh)
  -> ProfileLoaded (GET /v1/me)
  -> SessionActive (POST /v1/session/claim)
  -> [heartbeat ...]
  -> LaunchPermit (Core challenge -> POST /v1/launch-permit)
  -> SessionActive
  -> SignedOut (release/sign-out/revocation)
```

### 6.1 `GET /v1/me`

Response (v0): `identity_user_id`, `proxy_account_id`, `status`,
`display_name`, license summary, ban/app-access state.

Client behavior:

- Call after a successful token exchange, on session restore, and after a
  permit-level authorization error.
- Treat this response as the display/state source; the server remains
  authoritative for authorization.
- Map `identity_user_id` to the internal user ID and `display_name` to the
  display label. Do not require a Supabase user ID or email.
- `status` values: `pending`, `active`, `suspended`, `closed`. Pending,
  suspended, and closed accounts do not launch. The exact UI copy and whether
  `claim` is attempted first are **PENDING** (G13/D8, G6/D5).
- License summary and ban/app-access field names/shapes are **PENDING**. Until
  frozen, the Launcher must not invent a local schema or parse free-form text.
- Do not cache `/v1/me` as proof of entitlement across launches.

### 6.2 `POST /v1/session/claim`

v0 response: `session_id`, `runtime_config_version`,
`heartbeat_interval_seconds`.

The request body is **PENDING**. The current Core/entitlement path needs at
least:

```json
{
  "product_code": "neko-family-proxy",
  "installation_key_hash": "<64 lowercase hex>",
  "display_name": "<bounded label>"
}
```

plus `Idempotency-Key`. Whether the API derives the account from the bearer
token and whether it accepts an installation identity are contract decisions.
The current RPC requires a Supabase `auth.uid()` and JWT `session_id`; those
must not appear in the new request.

Client behavior:

- Require a successful `/v1/me` and an active license before claiming, but let
  the claim response be authoritative.
- Treat `session_id` as opaque. Do not assume it is a UUID unless the contract
  says so.
- Apply `heartbeat_interval_seconds` from the response; do not hardcode 30
  seconds.
- Store `runtime_config_version` for diagnostics only; the permit response
  remains the source of runtime configuration.
- A `session_conflict` response is not a reason to retry blindly. The client
  must re-read `/v1/me` and follow the agreed conflict policy (latest-claim-wins
  versus explicit conflict). This is **PENDING** (G6/D5).
- A license/account error clears the local entitlement display and blocks
  launch; it does not delete the refresh token unless the account is suspended
  or the token is invalid.

### 6.3 `POST /v1/session/heartbeat`

v0 does not define the request body. The current RPC takes `session_id`; the
new API likely needs the same binding. This is **PENDING**.

Client behavior:

- Schedule heartbeats at the server-provided interval, with no overlapping
  requests.
- Refresh the access token first if it is within the refresh window.
- If heartbeat returns `invalid_token`/`token_expired`: refresh once and retry
  once. If it still fails, revoke local session state and require login.
- If heartbeat returns a session/account/license denial: stop the proxy,
  invalidate local state, and show the mapped reason.
- On network/5xx errors: keep the refresh token, retry with backoff, mark the
  UI as degraded, and block new launches after the agreed failure budget. Do
  not extend the session locally or claim offline authorization.
- The exact stale timeout (current server: 90 seconds for a 30-second
  heartbeat) is **PENDING** and must be part of the contract (G7/D14).

### 6.4 `POST /v1/session/release`

- Best effort on explicit sign-out, normal shutdown, and session loss.
- Idempotent by contract; a repeated release is not an error.
- Do not block UI shutdown beyond the existing short grace period (0.75 s in
  the current Launcher).
- Never release a session that belongs to another account or process.

### 6.5 Restore and offline behavior

- On launch, read the refresh token from the new-line vault, refresh, call
  `/v1/me`, and claim a session.
- If the network is unavailable, the new line cannot authorize a launch. Show
  a retryable offline state; no cached entitlement or cached session may enable
  Core.
- Whether the UI shows a cached profile while offline is a product decision
  (G16/D16). It must never show "active" based only on local cache.
- If the refresh token is invalid, clear it and show signed-out. Do not fall
  back to `5.1.6` credentials or Supabase.

### 6.6 Session termination reason

The current Launcher reads `launcher_sessions`, `profiles`, `licenses`, and
`installations` directly to distinguish "replaced", "license expired",
"account restricted", and "revoked". The new line must not do direct reads.
`/v1/me` returns ban/app-access state, but v0 does not define a termination
reason or a heartbeat denial detail. This is **PENDING** (G9/D9). Until it is
defined, the client uses a generic "session ended" message without guessing the
cause.

## 7. Launch permit and Runtime Config v1

NekoProxyCore is unchanged. The permit and Runtime Config wire shapes that Core
consumes today remain the contract; only the issuance authority moves from the
Supabase Edge Function to Neko Proxy API.

### 7.1 Preconditions

- Authenticated and active `/v1/me` state.
- A claimed session with a fresh heartbeat (the current Launcher performs a new
  online heartbeat immediately before each start attempt).
- A Core-generated challenge from the fresh Core control channel.
- An installation proof only if the contract preserves the machine-bound
  credential check.

### 7.2 Request

The v0 endpoint exists, but the request body is **PENDING**. The current
Launcher sends the following `runtime-config-v1` body to
`issue_launch_permit`; Neko Proxy API must accept and validate the equivalent,
or the contract must version the shape and Core must be updated:

```json
{
  "version": 1,
  "contractRevision": "runtime-config-v1",
  "correlationId": "<32 lowercase hex>",
  "challenge": "<Core challenge, bounded ASCII>",
  "machineProof": {
    "credentialId": "<installation credential id>",
    "algorithm": "ed25519",
    "publicKeyB64": "<public key>",
    "keyHash": "<64 hex>",
    "signatureB64": "<signature over challenge>"
  }
}
```

Missing from v0 and required for review:

- which session/installation the permit is bound to (request field or derived
  from the bearer token);
- whether `machineProof` remains mandatory;
- the exact accepted `contractRevision` values and unknown-field policy;
- the rate-limit response and `Retry-After` behavior;
- the error codes for stale session, stale heartbeat, inactive entitlement,
  challenge replay, and installation mismatch.

### 7.3 Response

The current Launcher requires the exact success shape:

```json
{
  "version": 1,
  "contractRevision": "runtime-config-v1",
  "correlationId": "<same correlation id>",
  "succeeded": true,
  "permit": "<opaque ASCII permit, 1-4096 chars>",
  "expiresInSeconds": 30,
  "runtimeConfig": {
    "schemaVersion": 1,
    "configVersion": 1,
    "endpointId": "<bounded ASCII>",
    "host": "<bounded ASCII>",
    "port": 443,
    "protocol": "shadowsocks",
    "cipher": "<bounded ASCII>",
    "credential": "<opaque runtime credential>",
    "issuedAt": 1760000000,
    "expiresAt": 1760000120
  }
}
```

The Runtime Config object is consumed by Core with strict field validation:
exact key set, ASCII-safe values, a 120-second `expiresAt - issuedAt` window,
and `protocol=shadowsocks`. If Neko Proxy API changes this shape, the contract
must be versioned and Core must be changed in its own repository. The Launcher
must not translate, repair, infer, or fabricate missing fields.

### 7.4 Handling

- Keep the permit and runtime credential in memory; pass them only to the
  authorized Core start call over the existing local pipe.
- Never write them to disk, logs, analytics, crash reports, or the UI.
- Never reuse a permit after Core rejects it, after the challenge is consumed,
  or after 30 seconds. Request a fresh challenge and a fresh permit.
- If the response is malformed, fail the start. Do not attempt a legacy
  `issue_launch_permit` call or a Supabase RPC.
- If the API returns 401, refresh once, then abort on failure.
- If the API returns 403/`insufficient_scope`, treat the client as
  incompatible or the account as not permitted; do not loop.
- On 429, wait per `Retry-After` and let the user retry. The current permit
  rate limit is 10 attempts per 60 seconds.
- If the API is unavailable, the launch fails closed; an existing Core session
  is not extended by a failed permit request.

## 8. Coupons

Endpoint: `POST /v1/coupons/redeem`, `Idempotency-Key` required.

v0 defines only the path and idempotency. The current Launcher's RPC contract
returns `product_code`, `days_added`, and `valid_until`, and uses
`invalid_coupon`, `already_redeemed`, `rate_limited`, and `account_restricted`.
The new request/response and stable error mapping are **PENDING** (G11/D11).

Client behavior:

- Send only the entered coupon code plus the idempotency key; no account ID.
- Reuse the same key when the user retries the same code after an ambiguous
  outcome. Generate a new key for a different code.
- On success, update the displayed entitlement from the response and re-run
  `/v1/me` and claim; do not add days locally.
- On `already_redeemed`, do not retry with a new key.
- On 429, honor `Retry-After`; the current behavior is 10 minutes.
- Never log the coupon code.

## 9. Public status

Endpoint: `GET /public/status`, no authentication, no identity, no cookies.

v0 requires a sanitized response with no client identity, credentials, raw
proxy endpoint, or packet data. The current Launcher consumes
`/api/proxy/status` on the Control Room origin with this shape:

```json
{
  "ok": true,
  "proxy": {
    "status": "ONLINE|DEGRADED|STALE|UNKNOWN|OFFLINE",
    "load_level": "light|moderate|heavy|full|unknown",
    "average_30m": {
      "rx_bps": 0,
      "tx_bps": 0,
      "sample_count": 0,
      "covered_minutes": 0
    },
    "observed_at": null,
    "age_seconds": null
  }
}
```

The new line must call Neko Proxy API, not the Control Room. Whether the Proxy
API preserves this shape or defines a new one is **PENDING** (G10/D10). The
status client is best-effort: failures are isolated and never block login,
claim, permit, or Core.

## 10. Error behavior matrix

| Stable code | Launcher behavior |
| --- | --- |
| `invalid_token` | Refresh once. If it persists, clear local session and require login. |
| `token_expired` | Refresh once, then retry the original call once. If it persists, sign out. |
| `insufficient_scope` | Do not retry. Sign out and show "update required" / permission error. |
| `identity_not_linked` | Do not retry. Show the agreed link/support flow (product decision pending). |
| `account_pending` | Do not launch. Show pending-account message. |
| `account_suspended` | Sign out local authorization; show restricted-account message. |
| `license_expired` | Clear entitlement; offer coupon/support path; do not launch. |
| `session_conflict` | Re-read `/v1/me`; follow the agreed conflict policy; do not steal blindly. |
| `rate_limited` | Honor `Retry-After`; bounded backoff; no tight loop. |
| `upstream_unavailable` | Retryable; keep the refresh token; block launch; surface retry. |
| Unknown code | Generic failure; no authorization; log code + request_id only. |

Identity login errors (`invalid_grant`, `invalid_client`, `access_denied`,
`server_error`, `rate_limited`) are mapped separately to user-safe login
messages. They never fall back to password or legacy Supabase auth.

## 11. Security invariants

1. One auth pool: identity/Discord only. No password, registration, recovery,
   or synthetic proxy auth user in the new line.
2. The Launcher has no Supabase URL/key/session and makes no direct
   PostgREST/RPC call. The new-line bundle is tested for absence.
3. No service-role key, admin service token, or `proxy:admin` scope in the
   Launcher or browser.
4. Tokens, codes, verifiers, permits, runtime credentials, machine proofs, and
   coupon codes are never logged, shown in error text, put in URLs (except the
   one-time authorization code), or written to disk except the refresh token in
   the OS vault.
5. Exact loopback redirect, PKCE S256, state validation, one-use callback.
6. HTTPS only; no redirect following; bounded bodies; strict JSON validation.
7. Server authoritative for identity mapping, account status, license, ban/app
   access, session claim, heartbeat, and permits. Local state never grants.
8. Core receives only a fresh permit + Runtime Config v1; no unsigned,
   cached, synthesized, or legacy fallback.
9. Clean line separation: no import or reuse of `5.1.6` Supabase sessions,
   trust state, or credentials.
10. Fail closed on any contract violation, storage failure, or ambiguous
    security outcome.

## 12. P1 test obligations

The P1 implementation is not complete until these exist and pass:

- PKCE/state/callback tests: wrong state, duplicate query keys, wrong path,
  wrong Host, timeout, replay, oversized request, browser failure.
- Token exchange tests: malformed responses, wrong token type, oversized
  tokens, missing refresh, insecure endpoint, redirect response.
- Refresh tests: single-flight, rotation persistence, ambiguity rule, invalid
  grant, 5xx preservation, no old-token reuse.
- Vault tests: atomic replacement, unavailable vault fails closed, legacy key
  is never read, sign-out clears all new-line material.
- HTTP tests: envelope parsing, unknown code, retry/backoff, 429
  `Retry-After`, no redirect, response size limit, timeout.
- Session tests: `/v1/me` mapping, claim interval, heartbeat schedule,
  release idempotency, conflict handling, restore/offline behavior.
- Permit tests: exact Runtime Config v1 validation, stale challenge, replay,
  malformed permit, no disk/log exposure, Core receives the bundle once.
- Build guard tests: the new-line artifact contains no Supabase host/key,
  `launcher_bridge`, `web_sessions`, `identity_links`, bridge URL, password
  strings, or recovery surface; it contains no `proxy:admin`.
- Logging tests: redaction of Authorization, JWT, access/refresh tokens,
  permits, runtime credentials, machine proofs, coupon codes, and authorization
  codes.
- Staging E2E: Discord login -> code exchange -> `/v1/me` -> claim ->
  heartbeat -> Core challenge -> permit -> Core running -> release; expired
  access refresh; revoked session; suspended account; expired license;
  API/network failure; no legacy backend contact.
- `5.1.6` regression suite continues to pass unchanged.

## 13. Pending decisions

All **PENDING** items above are tracked with evidence and owners in
[gap-and-conflict-register.md](gap-and-conflict-register.md) and must be
resolved in [p0-signoff-checklist.md](p0-signoff-checklist.md) before P1.
