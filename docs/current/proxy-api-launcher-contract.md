# Proxy API Launcher Contract — P1 Slice 1

**Status:** Implemented contract for source/dev slice 1; not a release contract
**Date:** 2026-10-25
**Applies to:** `NEKO_PROXY_API_URL` new-line path only
**Does not apply to:** `5.1.6` and the legacy bridge path
**Companion:** [5.3.0-proxy-api-launcher.md](5.3.0-proxy-api-launcher.md)

This document is the launcher-side contract for the code shipped in P1 slice 1.
The future `Neko-Contracts` repository remains the authority for the shared
OpenAPI/JWT/error schema; this file records the exact client behavior already
implemented here.

## 1. Endpoints and exact requests

### 1.1 Account status preflight

```http
GET {NEKO_PROXY_API_URL}/v1/me
Authorization: Bearer <access_token>
Accept: application/json
Cache-Control: no-store
User-Agent: NekoLauncher/<version>
```

- No request body, cookies, query string, or browser storage.
- Timeout: 10 seconds (default; bounded transport).
- Maximum accepted response: 64 KiB.
- HTTPS only; redirects are not followed.
- Called immediately after a successful identity login and on session restore.
- Success requires a JSON object with:
  - `identity_user_id` (non-empty ASCII, bounded);
  - `proxy_account_id` (non-empty ASCII, bounded);
  - `status` in `pending`, `active`, `suspended`, `closed`;
  - `display_name` (bounded user text; Unicode allowed, control characters
    rejected).
- License summary and ban/app-access fields are reserved for later slices;
  their schemas are not consumed yet.
- `status=pending` maps to `account_pending`; `suspended`/`closed` map to
  `account_suspended`.

### 1.2 Refresh-token exchange

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

- Timeout: 10 seconds; maximum response 64 KiB; HTTPS only; no redirects.
- Success requires `token_type=Bearer`, non-empty access and refresh tokens,
  and `expires_in` in `1..3600`.
- The returned refresh token replaces the stored token before the new access
  token is used. The access token stays in memory.
- The live identity service currently implements only `authorization_code`;
  this request is blocked until identity ships the refresh grant (open item 1).

### 1.3 Authorization-code login (unchanged identity flow)

The launcher continues to use:

```text
GET  {identity}/launcher/authorize   PKCE S256, exact redirect
POST {identity}/api/launcher/token   grant_type=authorization_code
```

The new-line exchange calls `WebAuthClient.authenticate_identity()` and
requires the identity response to contain a refresh token. It does not call
`launcher_bridge` and does not create a Supabase session.

## 2. Retry and timeout rules

| Condition | Slice-1 behavior |
| --- | --- |
| `GET /v1/me` returns `401 invalid_token` or `401 token_expired` | Refresh once, then retry the GET once. If either step fails, login/restore fails closed. |
| Refresh endpoint returns `invalid_grant`, `invalid_token`, `token_expired`, `invalid_client` | Terminal; clear the stored refresh token and require interactive login. |
| `403 insufficient_scope` | No retry; update-required message. |
| `409 identity_not_linked`, `account_pending`, `account_suspended`, `license_expired`, `session_conflict` | No blind retry; show the mapped message. |
| `429 rate_limited` | No automatic retry in slice 1; expose `retryable=true`. `Retry-After` parsing is deferred. |
| `503 upstream_unavailable` / 5xx | No automatic retry in slice 1; expose `retryable=true`. |
| Timeout | No automatic retry; `timeout` / retryable; login preflight clears the new refresh token, restore keeps it. |
| Network error | No automatic retry; `network_error` / retryable; same storage rule as timeout. |
| Malformed JSON or missing fields | `invalid_response`, non-retryable; fail closed. |
| HTTP redirect | Not followed; treated as an error. |
| Permit / claim / coupon | Not implemented in this slice; no retry rules apply yet. |

Bounded values are implemented in
`launcher/src/neko_launcher/infrastructure/auth/proxy_api_gateway.py`:
10-second default timeout, 64 KiB response limit, no redirect handler, HTTPS
origin validation, and 1..3600 seconds for `expires_in`.

## 3. Refresh-token storage and access-token lifetime

- Refresh token: Windows Credential Manager through `KeyringSecureStore`, under
  the new key `proxy-api-refresh-token`.
- Access token: memory only (`ProxyApiAuthGateway._access_token`); never written
  to the vault, disk, registry, logs, or crash reports.
- No Supabase session, Supabase storage key, or `SupabaseAuthStorage` is used by
  the new path.
- Legacy keys (for example the Supabase session key) are neither read nor
  migrated. The new line starts clean.
- A successful login stores the refresh token before the account preflight.
  Any login-preflight failure in slice 1 clears the newly stored refresh token
  and the in-memory access token; a failed login does not leave a usable
  session.
- A restore refreshes first; a terminal refresh/auth error clears the stored
  token; a transient error keeps it for a later retry.
- Sign-out clears memory and the stored refresh token. Because contract v0 has
  no refresh-revocation endpoint, slice 1 sign-out is local-only.
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

The server `message` is not displayed. The launcher displays the fixed Thai
message for the code and keeps `request_id` for support.

### 4.1 Shared error codes

| Code | Thai UI message | Slice-1 behavior |
| --- | --- | --- |
| `invalid_token` | เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่ | Refresh once; if it persists, clear and sign out. |
| `token_expired` | เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่ | Refresh once; if it persists, clear and sign out. |
| `insufficient_scope` | โปรแกรมนี้ไม่มีสิทธิ์เชื่อมต่อระบบ กรุณาอัปเดตโปรแกรม | No retry; sign out / update required. |
| `identity_not_linked` | บัญชี Discord นี้ยังไม่ได้เชื่อมกับบัญชี Neko Family กรุณาติดต่อฝ่ายบริการ | No retry; show linking/support instruction. |
| `account_pending` | บัญชีนี้อยู่ระหว่างการตรวจสอบ กรุณารอหรือติดต่อฝ่ายบริการ | No launch; show pending state. |
| `account_suspended` | บัญชีนี้ไม่สามารถใช้งานได้ กรุณาติดต่อฝ่ายบริการ | No launch; clear local authorization. |
| `license_expired` | สิทธิ์ใช้งานหมดอายุ กรุณาเติมวันหรือติดต่อฝ่ายบริการ | Show entitlement state; claim flow is later. |
| `session_conflict` | บัญชีนี้ถูกใช้งานบนเครื่องอื่น กรุณาออกจากระบบบนเครื่องนั้นก่อน | Show conflict; do not steal a session. |
| `rate_limited` | ทำรายการบ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่ | No automatic retry; `retryable=true`. |
| `upstream_unavailable` | ระบบปลายทางไม่พร้อมใช้งาน กรุณาลองใหม่ | No automatic retry; `retryable=true`. |

### 4.2 Internal/identity codes

| Code | Thai UI message | Source |
| --- | --- | --- |
| `invalid_grant` | เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่ | Refresh rejected. |
| `invalid_client` | โปรแกรมไม่ได้รับอนุญาต กรุณาอัปเดตโปรแกรม | Identity client rejected. |
| `access_denied` | คุณยกเลิกการเข้าสู่ระบบ | Identity callback denial (existing WebAuthClient message may add the account-status context). |
| `server_error` | ระบบล็อกอินขัดข้อง กรุณาลองใหม่ | Identity server error. |
| `network_error` | เชื่อมต่อระบบไม่ได้ กรุณาตรวจสอบอินเทอร์เน็ตแล้วลองใหม่ | Transport failure. |
| `timeout` | เชื่อมต่อระบบนานเกินไป กรุณาลองใหม่ | Transport timeout. |
| `invalid_response` | ระบบตอบกลับไม่ถูกต้อง กรุณาลองใหม่ | Malformed JSON or missing/invalid fields. |
| `http_error` | ระบบขัดข้อง กรุณาลองใหม่ | Unexpected HTTP status without a usable envelope. |
| `credential_store_unavailable` | จัดเก็บข้อมูลล็อกอินไม่สำเร็จ กรุณาลองใหม่ | Windows credential vault failure. |
| Unknown code | เกิดข้อผิดพลาด กรุณาลองใหม่ | Forward-compatible fallback. |

If an error response has no usable envelope, the gateway falls back by status:
`401 -> invalid_token`, `403 -> insufficient_scope`,
`429 -> rate_limited`, `5xx -> upstream_unavailable`, other -> `http_error`.
OAuth-style `{"error": "invalid_grant"}` is accepted for the refresh endpoint.

## 5. Feature flags and rollout gate

| Variable | Behavior in slice 1 |
| --- | --- |
| `NEKO_PROXY_API_URL` | The new-line switch. Unset/empty = disabled. Must be an HTTPS origin with no path, query, or fragment. Source/dev only; rejected in frozen builds. Mutually exclusive with `NEKO_AUTH_BRIDGE_URL`. Implies web auth and web-only mode. |
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
- Claim/permit/coupon/status slices remain blocked until their contract items
  are signed off.

## 6. Removal map (no removal performed in this slice)

| Artifact | Current state | New-line replacement | Removal gate |
| --- | --- | --- | --- |
| `WebAuthClient.authenticate()` and `_exchange_bridge` in `web_auth.py` | Retained for the legacy bridge path | `WebAuthClient.authenticate_identity()` + `ProxyApiAuthGateway` | Bridge retirement after 5.1.6 support ends / 5.3.0 gate |
| `SupabaseGateway.sign_in_with_web` | Retained for legacy | `ProxyApiAuthGateway.sign_in_with_web` | Same bridge retirement gate |
| `NEKO_AUTH_BRIDGE_URL` config field | Retained legacy | `NEKO_PROXY_API_URL` | After 5.1.6 support ends |
| `launcher_v2.web_sessions` migration/RPC allowlist | Retained; not called by new line | Neko Proxy API session ownership | After proxy API owns sessions and the legacy line is retired |
| `launcher_bridge` Edge Function | Retained; not called by new line | Identity + Proxy API | Bridge retirement gate |
| `SupabaseGateway` claim/heartbeat/release/permit/coupon methods | Retained legacy | Proxy API endpoints in later slices | Per-slice replacement, then 5.3.0 cleanup |
| `NEKO_LAUNCHER_SCHEMA` | Legacy only | No schema selection in new line | Legacy cleanup |
| Embedded Supabase URL/publishable key defaults | Legacy only; not constructed/required in proxy mode | No Supabase dependency in new line | Release-build guard and removal slice |
| `HttpAccountRecoveryGateway` | Legacy only | No recovery in new line | Legacy cleanup |

No source deletion is part of P1 slice 1. Do not apply the `launcher_v2`
migrations, deploy the bridge, or remove the legacy code until the owning
repositories and release gates allow it.

## 7. Test coverage added

- `launcher/tests/test_proxy_api_gateway.py`
  - `GET /v1/me` request/headers/timeout/Bearer boundary.
  - Refresh exchange request and rotated-token response.
  - All ten shared error codes and their Thai messages.
  - 401 invalid/expired, 403 insufficient scope, 409 identity/link/pending/
    suspended/license/conflict, 429, 503.
  - Timeout, network failure, malformed JSON, missing fields, invalid status,
    response-size limit, unsafe URLs, and token redaction.
- `launcher/tests/test_proxy_api_auth.py`
  - Refresh-token-only storage; access token in memory.
  - Preflight after login; one refresh on 401; terminal vs transient restore.
  - Account pending/suspended status enforcement.
  - Sign-out clearing; password/recovery rejection.
  - Proxy-mode `LauncherService` skips legacy claim on login and restore.
  - App composition does not construct `SupabaseGateway` in proxy mode, even
    with empty Supabase fields.
- `launcher/tests/test_proxy_api_config.py`
  - Flag default/off, HTTPS-origin validation, frozen rejection, bridge
    mutual exclusion, web-only enforcement, and unchanged legacy bridge config.
- `launcher/tests/test_web_auth.py`
  - Identity-only exchange without a bridge and refresh-token validation.

## 8. Open questions

1. Identity must ship the `refresh_token` grant and return a rotating refresh
   token before a real staging login can complete.
2. Freeze the `/v1/me` license summary and ban/app-access schemas.
3. Decide where `/public/status` lives and whether its current shape is
   preserved.
4. Define a refresh-token revocation/logout endpoint; sign-out is local-only
   today.
5. Define `Retry-After` and idempotency semantics for later write endpoints.
6. Decide whether slice 1 should keep the installer-credential startup check;
   the new path does not use the credential yet.
7. Freeze the claim request fields and the session-conflict policy before
   implementing claim/heartbeat.
