# Proxy API Launcher Contract — P1 Slice 2

**Status:** Implemented contract for source/dev slice 2; not a release contract
**Date:** 2026-10-25
**Applies to:** `NEKO_PROXY_API_URL` new-line path only
**Does not apply to:** `5.1.6` and the legacy bridge path
**Companion:** [5.3.0-proxy-api-launcher.md](5.3.0-proxy-api-launcher.md)

This document is the launcher-side contract for the code shipped in P1 slice 2.
The future `Neko-Contracts` repository remains the authority for the shared
OpenAPI/JWT/error schema; this file records the exact client behavior already
implemented here. The Proxy API claim/heartbeat/release/permit routes are
planned but not deployed in the Proxy API repository; live verification is an
open item.

## 1. Endpoints and exact requests

All Proxy API calls use:

- HTTPS origin from `NEKO_PROXY_API_URL`, no path/query/fragment.
- `Accept: application/json`, `Cache-Control: no-store`, and
  `User-Agent: NekoLauncher/<version>`.
- `Authorization: Bearer <access_token>`.
- 10-second timeout, 64 KiB response limit, no redirect following.
- No cookies, browser storage, or query-string tokens.
- No token, permit, runtime credential, or coupon value in logs.

### 1.1 Account status preflight

```http
GET {NEKO_PROXY_API_URL}/v1/me
```

Success requires `identity_user_id`, `proxy_account_id`, `status`, and
`display_name` (nullable). `status` is one of `pending`, `active`, `suspended`,
`closed`. Called after login and on restore, before claim.
`pending` maps to `account_pending`; `suspended`/`closed` map to
`account_suspended`. The license summary and identity-access fields are not
consumed yet.

### 1.2 Identity refresh

```http
POST {NEKO_IDENTITY_BASE_URL}/api/launcher/token
Accept: application/json
Content-Type: application/json
Cache-Control: no-store
Pragma: no-cache
User-Agent: NekoLauncher/<version>

{
  "grant_type": "refresh_token",
  "client_id": "neko-launcher",
  "refresh_token": "<current refresh token>"
}
```

Success requires `token_type=Bearer`, non-empty access and refresh tokens, and
`expires_in` in `1..3600`. The returned refresh token replaces the stored token
before the new access token is used. The access token stays in memory.

The live identity service currently implements only `authorization_code`; this
request is blocked until identity ships the refresh grant (open item 1).

### 1.3 Authorization-code login (unchanged identity flow)

```text
GET  {identity}/launcher/authorize   PKCE S256, exact redirect
POST {identity}/api/launcher/token   grant_type=authorization_code
```

`WebAuthClient.authenticate_identity()` requires the identity response to
contain a refresh token. It does not call `launcher_bridge` and does not create
a Supabase session.

### 1.4 Session claim

```http
POST {NEKO_PROXY_API_URL}/v1/session/claim
Idempotency-Key: <16-128 printable ASCII characters>
Content-Type: application/json

{
  "installation_key_hash": "<64 lowercase hex>",
  "display_name": "<optional, max 120>"
}
```

The launcher generates one UUIDv4 hex key per logical claim. The same key is
reused if the call is retried after a token refresh; it is never reused for a
different body. Success response fields:

- `session_id` (UUID, required);
- `installation_id` (UUID; tolerated as optional for the prose variant);
- `runtime_config_version` (integer >= 1, required);
- `heartbeat_interval_seconds` (10–60, required);
- `license_valid_until` (ISO date-time; optional in the client parser);
- `server_time` (ISO date-time; optional in the client parser).

The client maps this to `SessionClaim` with an active entitlement using
`license_valid_until` (or no expiry when absent), `installation_id`,
`runtime_config_version`, and the server heartbeat interval.

### 1.5 Heartbeat

```http
POST {NEKO_PROXY_API_URL}/v1/session/heartbeat
Content-Type: application/json

{ "session_id": "<claimed UUID>" }
```

Success requires `session_id` (matching the request), `status=active`,
`next_heartbeat_seconds` in 10–60, and an optional `server_time`. The launcher
updates its schedule from `next_heartbeat_seconds`; the UI clamps the interval
to 10–60 seconds and reschedules after each tick. The server treats a session
stale after 90 seconds.

### 1.6 Release

```http
POST {NEKO_PROXY_API_URL}/v1/session/release
Content-Type: application/json

{ "session_id": "<claimed UUID>" }
```

Success requires `session_id` and a boolean `released`. Release is best effort
on explicit sign-out and normal exit; a released=false response is accepted.
A released session grants no authority.

### 1.7 Launch permit

```http
POST {NEKO_PROXY_API_URL}/v1/launch-permit
Idempotency-Key: <same key for the logical permit attempt>
Content-Type: application/json

{
  "session_id": "<claimed UUID>",
  "challenge": "<43-char base64url Core challenge>",
  "correlation_id": "<32 lowercase hex>"
}
```

Success requires exactly:

```json
{
  "permit": "<compact JWT>",
  "token_type": "neko-launch+jwt",
  "expires_in_seconds": 30,
  "correlation_id": "<same 32-hex id>",
  "runtime_config": {
    "schema_version": 1,
    "config_version": 42,
    "endpoint_id": "jp-01",
    "host": "proxy.example.invalid",
    "port": 8388,
    "protocol": "shadowsocks",
    "cipher": "aes-256-gcm",
    "credential": "<redacted>",
    "issued_at": 1792931696,
    "expires_at": 1792931816
  }
}
```

The launcher:

- validates the envelope, token type, 30-second lifetime, correlation ID, and
  compact JWT shape;
- maps the snake_case `runtime_config` into the frozen Core Runtime Config v1
  object with exact field names and the 120-second issued/expiry window;
- treats the permit as opaque and passes it unchanged to Core;
- never parses, verifies, translates, repairs, logs, or persists the permit or
  runtime credential;
- fails closed on any missing, extra, or invalid runtime-config field.

The permit JWT claims remain the frozen Core contract (`RS256`,
`typ=neko-launch+jwt`, `kid=neko-prod-key-2`, 30 s, `iss=neko-backend`,
`aud=neko-proxy-core`, `challenge`, `runtime_config_version`,
`runtime_config_sha256`). Core verifies them; the launcher does not.

## 2. Retry, timeout, and idempotency rules

| Condition | Behavior |
| --- | --- |
| Any Proxy API call returns `401 invalid_token` / `token_expired` | Refresh once through the identity endpoint, then retry the same operation once with the same idempotency key. |
| Refresh fails (HTTP error, timeout, network, 5xx, invalid response) | Fail closed: clear the refresh token and require interactive login. Never retry the old token. |
| `403 insufficient_scope` | No retry; sign out / update required. |
| `409 session_conflict` on claim/heartbeat | Apply latest-claim-wins behavior: show the displaced-session message; a displaced heartbeat ends local authorization. |
| `409 session_conflict` on release | Best effort; accepted as a non-fatal release failure. |
| `409 idempotency_key_conflict` | No retry; surfaces as a request error. |
| `429 rate_limited` | No automatic retry in this slice; expose `retryable=true`. `Retry-After` is not parsed yet. |
| `503 upstream_unavailable` / 5xx | No automatic retry for claim/heartbeat/release/permit; the UI shows a retryable error. |
| Timeout / network error | No automatic retry; mapped to a retryable error. Login preflight clears the new refresh token; a successful refresh followed by a preflight failure keeps the new token. |
| Malformed JSON / missing fields | `invalid_response`, fail closed. |
| HTTP redirect | Not followed; treated as an error. |

Idempotency keys are client-generated UUIDv4 hex strings (32 printable
characters), 16–128 characters per the API contract. A key is generated once
per logical claim/permit operation and reused for the one 401 refresh-retry.
There is no blind retry loop.

## 3. Refresh-token storage and access-token lifetime

- Refresh token: Windows Credential Manager through `KeyringSecureStore`, under
  the new key `proxy-api-refresh-token`.
- Access token: memory only (`ProxyApiAuthGateway._access_token`); never written
  to the vault, disk, registry, logs, or crash reports.
- No Supabase session, Supabase storage key, or `SupabaseAuthStorage` is used by
  the new path.
- Legacy keys are neither read nor migrated. The new line starts clean.
- A successful login stores the refresh token before the account preflight. A
  failed login preflight clears the new refresh token and access token.
- A restore refresh failure clears the stored token and requires interactive
  login (fail-closed, no grace). A restore where refresh succeeds but the
  subsequent account preflight fails transiently keeps the newly rotated token.
- Sign-out clears memory and the stored refresh token. Because contract v0 has
  no refresh-revocation endpoint, sign-out is local-only.
- Token values are excluded from `repr()`; errors contain only a code, HTTP
  status, safe `request_id`, retryability, and a Thai user message.

## 4. Error mapping

The launcher uses the shared envelope:

```json
{
  "error": {
    "code": "invalid_token",
    "message": "non-sensitive server text",
    "request_id": "safe correlation id",
    "retryable": false
  }
}
```

The server `message` is not displayed. The launcher displays a fixed Thai
message for the code and keeps `request_id` for support.

### 4.1 Shared and Proxy API codes

| Code | Thai UI message | Behavior |
| --- | --- | --- |
| `invalid_token` | เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่ | Refresh once; then clear/sign out on failure. |
| `token_expired` | เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่ | Refresh once; then clear/sign out on failure. |
| `insufficient_scope` | โปรแกรมนี้ไม่มีสิทธิ์เชื่อมต่อระบบ กรุณาอัปเดตโปรแกรม | No retry; sign out / update. |
| `identity_not_linked` | บัญชี Discord นี้ยังไม่ได้เชื่อมกับบัญชี Neko Family กรุณาติดต่อฝ่ายบริการ | No retry; linking/support instruction. |
| `account_pending` | บัญชีนี้อยู่ระหว่างการตรวจสอบ กรุณารอหรือติดต่อฝ่ายบริการ | No launch; show pending state. |
| `account_suspended` | บัญชีนี้ไม่สามารถใช้งานได้ กรุณาติดต่อฝ่ายบริการ | No launch; clear local authorization. |
| `account_closed` | บัญชีนี้ถูกปิดการใช้งาน กรุณาติดต่อฝ่ายบริการ | No launch; clear local authorization. |
| `license_expired` | สิทธิ์ใช้งานหมดอายุ กรุณาเติมวันหรือติดต่อฝ่ายบริการ | Show expired; no launch. |
| `license_inactive` | สิทธิ์ใช้งานยังไม่พร้อมใช้งาน กรุณาติดต่อฝ่ายบริการ | Show unavailable; no launch. |
| `session_conflict` | บัญชีนี้ถูกใช้งานบนเครื่องอื่น กรุณาออกจากระบบบนเครื่องนั้นก่อน | Displaced/stale; end local session. |
| `rate_limited` | ทำรายการบ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่ | No automatic retry; retryable. |
| `upstream_unavailable` | ระบบปลายทางไม่พร้อมใช้งาน กรุณาลองใหม่ | No automatic retry; retryable. |
| `runtime_config_unavailable` | ระบบตั้งค่าไม่พร้อมใช้งาน กรุณาลองใหม่ | Launch denied closed; retryable. |
| `idempotency_key_conflict` | คำขอนี้ถูกใช้ไปแล้ว กรุณาลองใหม่ | No retry. |
| `invalid_request` | คำขอไม่ถูกต้อง กรุณาลองใหม่ | No retry. |
| `not_found` | ไม่พบข้อมูลที่ร้องขอ | No retry. |
| `method_not_allowed` | คำขอนี้ไม่รองรับ | No retry. |
| `payload_too_large` | ข้อมูลคำขอมีขนาดใหญ่เกินไป | No retry. |
| `internal_error` | ระบบขัดข้อง กรุณาลองใหม่ | No blind retry; reconcile by reading state. |
| `coupon_invalid` | คูปองไม่ถูกต้องหรือใช้งานไม่ได้ | Later coupon slice. |
| `coupon_already_redeemed` | คูปองนี้ถูกใช้กับบัญชีนี้แล้ว | Later coupon slice. |
| Unknown code | เกิดข้อผิดพลาด กรุณาลองใหม่ | Generic fail-closed fallback. |

### 4.2 Internal/identity codes

| Code | Thai UI message | Source |
| --- | --- | --- |
| `invalid_grant` | เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่ | Refresh rejected. |
| `invalid_client` | โปรแกรมไม่ได้รับอนุญาต กรุณาอัปเดตโปรแกรม | Identity client rejected. |
| `access_denied` | คุณยกเลิกการเข้าสู่ระบบ | Identity callback denial. |
| `server_error` | ระบบล็อกอินขัดข้อง กรุณาลองใหม่ | Identity server error. |
| `network_error` | เชื่อมต่อระบบไม่ได้ กรุณาตรวจสอบอินเทอร์เน็ตแล้วลองใหม่ | Transport failure. |
| `timeout` | เชื่อมต่อระบบนานเกินไป กรุณาลองใหม่ | Transport timeout. |
| `invalid_response` | ระบบตอบกลับไม่ถูกต้อง กรุณาลองใหม่ | Malformed JSON or invalid fields. |
| `http_error` | ระบบขัดข้อง กรุณาลองใหม่ | Unexpected HTTP status without an envelope. |
| `credential_store_unavailable` | จัดเก็บข้อมูลล็อกอินไม่สำเร็จ กรุณาลองใหม่ | Windows credential vault failure. |

If an error response has no usable envelope, the gateway falls back by status:
`400 -> invalid_request`, `401 -> invalid_token`, `403 -> insufficient_scope`,
`404 -> not_found`, `405 -> method_not_allowed`, `409 -> session_conflict`,
`413 -> payload_too_large`, `429 -> rate_limited`,
`5xx -> upstream_unavailable`, other -> `http_error`. OAuth-style
`{"error": "invalid_grant"}` is accepted for the refresh endpoint.

## 5. Session policy and Core handoff

- **LATEST_CLAIM_WINS.** A new claim makes that installation the active
  session; the server revokes the prior session. The displaced client receives
  `409 session_conflict` on heartbeat and ends local authorization with the
  displaced-session message.
- Claim from the same installation while its session is active is idempotent at
  the server.
- Heartbeat interval is server-provided (10–60 s); the server considers the
  session stale after 90 s.
- Release is best effort on sign-out and normal exit.
- Termination reasons are derived from heartbeat errors, not proxy DB reads:
  - `session_conflict -> REPLACED`;
  - `account_suspended` / `account_closed -> ACCOUNT_RESTRICTED`;
  - `license_expired` / `license_inactive -> LICENSE_UNAVAILABLE`;
  - invalid/expired authentication -> `HeartbeatAuthInvalid` and local sign-out.
- Permit issuance requires an active claimed session, a fresh Core challenge,
  a fresh online heartbeat, and a Runtime Config v1 response. The existing
  named pipe/process behavior is unchanged; the launcher does not verify the
  permit signature itself.
- The installer-credential startup check stays enabled because the claim
  carries `installation_key_hash`; this is a deliberate slice-2 decision. No
  installer or release behavior changed.

## 6. Feature flags and rollout gate

| Variable | Behavior |
| --- | --- |
| `NEKO_PROXY_API_URL` | New-line switch. Unset/empty = disabled. Must be an HTTPS origin with no path/query/fragment. Source/dev only; rejected in frozen builds. Mutually exclusive with `NEKO_AUTH_BRIDGE_URL`. Implies web auth and web-only mode. |
| `NEKO_IDENTITY_BASE_URL` | Optional identity origin override. |
| `NEKO_AUTH_BRIDGE_URL` | Legacy bridge only; still works when `NEKO_PROXY_API_URL` is unset. |
| `NEKO_WEB_AUTH_ENABLED` | Legacy bridge enablement. The new path does not require it because `NEKO_PROXY_API_URL` is its switch. |
| `NEKO_WEB_AUTH_ONLY` | Must not be `0` with `NEKO_PROXY_API_URL`; the new path is web-only. |
| `NEKO_LAUNCHER_SCHEMA` | Legacy only; not used by the new path. |

Rollout gate:

- `NEKO_PROXY_API_URL` is disabled by default.
- The new path is source/dev only and is rejected in frozen/release builds.
- No publication, tag, installer, updater, or release-feed change is authorized.
- No production migration or account is used.
- `5.1.6` remains unchanged and continues to select its legacy path.
- Coupons, `/public/status`, bridge/Supabase removal, live staging E2E, and the
  `5.3.0` cutover remain later slices.

## 7. Supabase-free and bridge-free guard

- `app_factory` imports `SupabaseGateway` only inside the legacy branch.
- Proxy mode composes `ProxyApiAuthGateway`,
  `ProxyApiEntitlementGateway`, and `ProxyApiPermitGateway`.
- A test composes proxy dependencies with empty Supabase URL/key and asserts the
  Supabase gateway is not constructed.
- A subprocess test imports the bootstrap module and asserts
  `neko_launcher.infrastructure.auth.supabase_gateway` is not loaded.
- New proxy modules contain no Supabase or bridge imports.
- The legacy bridge and `launcher_v2` remain in the repository and are not
  removed in this slice.

## 8. Removal map (no removal performed in this slice)

| Artifact | Current state | New-line replacement | Removal gate |
| --- | --- | --- | --- |
| `WebAuthClient.authenticate()` and `_exchange_bridge` | Retained legacy | `authenticate_identity()` + `ProxyApiAuthGateway` | After 5.1.6 support ends / 5.3.0 gate |
| `SupabaseGateway.sign_in_with_web` | Retained legacy | `ProxyApiAuthGateway.sign_in_with_web` | Same bridge retirement gate |
| `NEKO_AUTH_BRIDGE_URL` | Retained legacy | `NEKO_PROXY_API_URL` | After 5.1.6 support ends |
| `launcher_v2.web_sessions` | Retained; never called by new line | Proxy API session ownership | After legacy retirement |
| `launcher_bridge` | Retained; never called by new line | Identity + Proxy API | Bridge retirement gate |
| `SupabaseGateway` claim/heartbeat/release/permit methods | Retained legacy | Proxy API session/permit endpoints | Per-slice replacement, then cleanup |
| Top-level `SupabaseGateway` import in app factory | Moved into legacy branch | Lazy legacy import | Full removal after legacy retirement |
| Embedded Supabase URL/publishable key defaults | Legacy only; not required in proxy mode | No Supabase dependency in new line | Release-build guard and removal slice |
| `NEKO_LAUNCHER_SCHEMA` | Legacy only | No schema selection in new line | Legacy cleanup |
| `HttpAccountRecoveryGateway` | Legacy only | No recovery in new line | Legacy cleanup |

No source deletion is part of P1 slice 2. Do not apply `launcher_v2` migrations,
deploy the bridge, or remove legacy code until the owning repositories and
release gates allow it.

## 9. Test coverage added

- `test_proxy_api_gateway.py`: `/v1/me`, claim, heartbeat, release, permit
  request/response contracts; all shared error codes; additional API codes;
  timeouts; malformed JSON; invalid runtime-config envelopes; token redaction.
- `test_proxy_api_auth.py`: refresh-token-only storage; fail-closed refresh;
  preflight; restore; account status; sign-out; password/recovery rejection;
  no Supabase construction; no Supabase import.
- `test_proxy_api_entitlement.py`: claim mapping, idempotency-key stability
  across token refresh, heartbeat interval, session conflict, account/license
  denials, release, coupon deferral.
- `test_proxy_api_permit.py`: permit success, runtime-config v1 mapping, one
  refresh retry, invalid runtime config, diagnostic mapping, secret redaction.
- `test_proxy_api_config.py`: flag off/on, HTTPS origin, frozen rejection,
  bridge mutual exclusion, web-only enforcement, legacy bridge unchanged.
- `test_web_auth.py`: identity-only exchange without a bridge.
- UI heartbeat test: server interval is used and clamped to 10–60 seconds.

## 10. Open questions

1. Identity must ship the `refresh_token` grant/rotation before a real staging
   login can complete.
2. Proxy API slice 2A must deploy claim/heartbeat/release/permit before live
   permit and Core E2E can be verified.
3. Freeze the `/public/status` shape and coupon error schema for later slices.
4. Define refresh-token revocation/logout; sign-out is local-only.
5. Confirm `Retry-After` and final idempotency replay semantics; the client
   currently does not auto-retry rate-limited/5xx writes.
6. Populate and consume the `/v1/me` license summary and identity-access fields
   when their nested schema is frozen.
7. Verify the Proxy API permit issuer key/JWKS and the signed permit against
   Core in staging; the launcher intentionally does not verify it.
