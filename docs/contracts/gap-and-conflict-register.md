# Launcher Contract Gap and Conflict Register

**Status:** P0 review artifact
**Date:** 2026-10-25
**Audited revision:** `9f34b1e`
**Baseline:** NEKO Unified Platform, contract baseline v0 (2026-10-25)
**Rule:** This register reports conflicts. It does not define a parallel
contract. Proposed request fields are Launcher needs for the contract owner to
ratify, not new authority.

## Severity

- **BLOCKER** — prevents P0 sign-off or P1 start.
- **MAJOR** — must be resolved before the affected endpoint's implementation
  slice is accepted.
- **MINOR** — must be resolved before the contract freeze; no security or
  architecture impact.

## Register

| ID | Severity | Conflict | Current evidence | v0 requirement | Owner |
| --- | --- | --- | --- | --- | --- |
| G1 | BLOCKER | Current new-line flow mints a Supabase session through `launcher_bridge` and relies on `launcher_v2.web_sessions` / `identity_links`. | `launcher/src/neko_launcher/infrastructure/auth/web_auth.py:561` (bridge exchange); `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py:123` (adopts bridge session); `supabase/functions/launcher_bridge/service.ts:114` (session minting); `supabase/migrations/20261025131000_create_launcher_v2_claim_permit.sql:145` (allowlist gate). | Non-negotiables 3 and 5: no bridge session minting, no synthetic proxy Auth users, no `web_sessions` allowlist; Launcher -> Neko Proxy API only. | Launcher + Proxy API + Contracts |
| G2 | BLOCKER | Launcher embeds Supabase URL/publishable key and uses direct PostgREST/RPC/table access for auth, claim, heartbeat, release, termination reason, permit, and coupons. | `launcher/src/neko_launcher/infrastructure/defaults.py:8`; `launcher/src/neko_launcher/infrastructure/config.py:82`; `launcher/src/neko_launcher/bootstrap/app_factory.py:379`; `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py:265`, `:333`, `:370`. | Non-negotiable 2: no Supabase key/session or proxy DB access in the new line. | Launcher |
| G3 | BLOCKER | Identity token contract is still bridge-specific: `aud=neko-launcher-bridge`, `scope=launcher:login`, 300 s TTL, no refresh grant. | Identity repo `lib/launcher/jwt.ts:11` and `:33`; identity repo `app/api/launcher/token/route.ts:57` accepts only `authorization_code` and returns no refresh token at `:187`. | v0: `aud=neko-proxy-api`, `scope="proxy:launch proxy:read"`, 10 min, refresh token 30 days sliding, rotate on use, reuse revokes family. | Identity + Contracts |
| G4 | BLOCKER | Authorization-code token request requires `redirect_uri` in the live identity service, but the v0 request sketch omits it. | Identity repo `app/api/launcher/token/route.ts:61` requires it; Launcher sends it at `launcher/src/neko_launcher/infrastructure/auth/web_auth.py:518`. | v0 lists `code + code_verifier + client_id` only. | Contracts + Identity |
| G5 | BLOCKER | Refresh rotation and sign-out are undefined on the client side. No revocation endpoint; ambiguous refresh outcome can trigger family revocation; current Launcher has no identity refresh implementation (Supabase SDK auto-refreshes a Supabase session instead). | `docs/contracts/launcher-consumer-contract.md` sections 4.4/4.6; current refresh is `supabase-py` session refresh in `SupabaseGateway` construction at `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py:67`. | v0 states rotate-on-use and reuse revokes family; no refresh error/idempotency/grace or logout revocation semantics. | Identity + Contracts |
| G6 | BLOCKER | Session claim request, binding, and conflict policy are underspecified. Current RPC binds to Supabase `auth.uid()` + JWT `session_id`, requires product/installation/display name, and is latest-claim-wins. | `supabase/migrations/20261025131000_create_launcher_v2_claim_permit.sql:116` (signature), `:136` (auth session binding), `:237` (revokes prior sessions); `docs/current/neko-auth-lite.md:20` (`LATEST_CLAIM_WINS`). | v0 response is `session_id`, `runtime_config_version`, `heartbeat_interval_seconds`; error includes `session_conflict`, but request/binding/conflict behavior is not defined. | Contracts + Proxy API |
| G7 | MAJOR | Heartbeat interval and staleness are fixed in the current client/server instead of server-provided. | `launcher/src/neko_launcher/ui/app_window.py:89` (30,000 ms); `supabase/migrations/20261025131000_create_launcher_v2_claim_permit.sql:319` (90 s); `docs/current/neko-auth-lite.md` heartbeat target. | v0 claim returns `heartbeat_interval_seconds`; stale window is not defined. | Contracts + Proxy API |
| G8 | BLOCKER | Launch-permit v0 says only "signed permit + runtime config"; the frozen Core contract requires an exact request and response shape, including `machineProof`, `contractRevision=runtime-config-v1`, correlation ID, 30 s permit, and a 120 s Runtime Config v1 object. | `launcher/src/neko_launcher/infrastructure/core/launch_permit_gateway.py:62` (request), `:142` (exact success keys); `supabase/functions/issue_launch_permit/service.ts:58` (request keys), `:406` (response); `launcher/src/neko_launcher/application/runtime_proxy_config.py:48` (Runtime Config v1). | v0 endpoint exists but request/response fields are unspecified; Core is unchanged. | Contracts + Proxy API |
| G9 | MAJOR | Session termination reason currently comes from direct table reads; v0 has no termination-reason field or denial detail. | `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py:265`; `launcher/src/neko_launcher/application/services.py:427`. | `/v1/me` returns ban/app-access state only; heartbeat denial detail is unspecified. | Proxy API + Contracts |
| G10 | MAJOR | Public status is read from the Control Room origin and uses a Launcher-specific shape; v0 says Proxy API `/public/status`, sanitized. | `launcher/src/neko_launcher/infrastructure/defaults.py:14`; `launcher/src/neko_launcher/infrastructure/proxy_status_client.py:59`. | v0 `GET /public/status`, no auth, sanitized; response shape not defined. | Proxy API + Contracts |
| G11 | MAJOR | Coupon request/response and coupon-specific error codes are not in v0; current RPC has its own result/error vocabulary. | `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py:370`. | v0 only defines `POST /v1/coupons/redeem` with `Idempotency-Key`; stable error list has no coupon codes. | Contracts + Proxy API |
| G12 | MAJOR | Shared error envelope is not universal today; identity uses OAuth-style errors. `request_id`, `Retry-After`, and idempotency semantics are unspecified. | Identity repo `app/api/launcher/token/route.ts:43` and `:57`; current permit rate limit returns `Retry-After: 60` (`docs/current/neko-auth-lite.md`); v0 envelope only. | Non-negotiable 6 says all errors use `{error:{code,message,request_id,retryable}}`; details for identity exceptions and retry metadata are missing. | Contracts + Identity + Proxy API |
| G13 | MAJOR | `/v1/me` field schemas (license summary, ban/app-access state) and UI mapping are undefined; current model expects username/email/entitlement from Supabase. | `launcher/src/neko_launcher/application/services.py:156`; `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py:395` (`_to_user`); `launcher/src/neko_launcher/domain/models.py` entitlement/user models. | v0 names only the broad fields; no nested schema. | Contracts + Proxy API |
| G14 | BLOCKER | Proxy-domain schema and permit Edge Function currently live in the Launcher repository, which v0 makes the wrong owner. | `supabase/migrations/20261025130000_create_launcher_v2_auth_foundation.sql`; `supabase/migrations/20261025131000_create_launcher_v2_claim_permit.sql`; `supabase/functions/issue_launch_permit/`; `supabase/functions/launcher_bridge/`. | Non-negotiables 3 and 4: Proxy owns proxy account/license/session/runtime config; Launcher has no proxy DB access. | Repo owners + Contracts |
| G15 | BLOCKER | Existing P0/P1/P2 documents and tests encode the superseded bridge/allowlist architecture. | `docs/current/web-auth-launcher.md:1`; `docs/current/p0-p5-status-audit.md:10`; `docs/superpowers/plans/2026-10-25-web-auth-separation-and-5-3-0-cutover.md:13`; `launcher/tests/test_launcher_v2_bridge_support_migration.py`. | New non-negotiables 3 and 5; bridge/allowlist not allowed for the new line. | Launcher docs/contracts owner |
| G16 | MAJOR | Offline/restore behavior is undefined. Current Launcher restores a persisted Supabase session locally; the new line needs a network refresh plus `/v1/me` before authorization. | `launcher/src/neko_launcher/application/services.py:283`; `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py:168`. | v0 has no offline or cached-authorization rule. | Product + Contracts |
| G17 | MINOR | Client version / protocol negotiation and request correlation are undefined. | Current Launcher has only an ad-hoc `User-Agent: NekoLauncherWebAuth/1` at `launcher/src/neko_launcher/infrastructure/auth/web_auth.py:116`; v0 has no client-version header or protocol version. | No requirement. | Contracts |
| G18 | MINOR | Identity issuer normalization is not frozen. | Identity repo signs `iss: publicEnv.siteUrl` at `lib/launcher/jwt.ts:34`; v0 says `iss=<identity origin>`. | No exact canonical string. | Identity + Contracts |
| G19 | MAJOR | Per-endpoint scope matrix is incomplete. | v0 token scope is only `proxy:launch proxy:read`; coupons and heartbeat/release scope are not stated. | No endpoint-to-scope table. | Contracts |
| G20 | MAJOR | New-line configuration and tests still assert the embedded Supabase values; there is no build guard that the new line is Supabase-free. | `launcher/tests/test_config.py:35` asserts the embedded URL/key; `launcher/tests/test_supabase_gateway.py` exercises the old gateway; no new-line absence guard exists. | Non-negotiable 2 and 8. | Launcher |

## Evidence detail for blockers

### G1 / G2 / G14 — architecture boundary

The current 5.2.0 path is:

```text
Launcher -> launcher_bridge (Supabase Edge Function)
         -> validates identity JWT (aud=neko-launcher-bridge)
         -> mints Supabase session
         -> inserts launcher_v2.web_sessions allowlist row
Launcher -> Supabase PostgREST/RPC with the Supabase session
```

Contract v0 requires:

```text
Launcher -> identity (PKCE/token only)
Launcher -> Neko Proxy API (Bearer identity access token)
Neko Proxy API -> its own database (proxy account/license/session/permit)
```

These are not reconcilable by configuration. The new line needs a separate
gateway and a separate build path. The current bridge, `launcher_v2` schema,
allowlist, and Edge Functions remain useful only as historical/legacy
artifacts; they must not be wired into the new line.

No deletion or production migration is authorized in P0/P1 by this register.

### G3 / G4 / G5 — identity changes required

The live identity service still issues a 5-minute, bridge-audience token with
`scope=launcher:login` and no refresh token. Contract v0 requires a 10-minute,
`neko-proxy-api`-audience access token plus an opaque rotating refresh token.
This is an identity-repository change, not a Launcher workaround. The Launcher
must not accept a bridge-audience token "for compatibility" in the new line.

The live token endpoint also requires `redirect_uri`; v0 must include it in the
authorization-code grant. The current Launcher already sends it, so this is a
documentation/contract correction rather than a client change.

The refresh design creates a real crash/ambiguity window. The contract should
choose one of:

1. idempotent refresh with a replayable response for the same request;
2. a bounded grace where the immediately previous refresh token remains valid
   until the new one is first used;
3. explicit acceptance that a crash between server rotation and local vault
   write forces an interactive login.

Until one is chosen, the Launcher's safe rule is "never retry an ambiguous
refresh with the old token" (see consumer contract 4.4).

### G6 / G7 — session lifecycle

The current backend contract is latest-claim-wins: a new claim revokes the
previous active session, heartbeat is required every 30 seconds, and the
server considers a session stale after 90 seconds. Contract v0 adds
`session_conflict` and a server-provided `heartbeat_interval_seconds` but does
not say whether latest-claim-wins remains the policy or whether a second
device must be rejected with `session_conflict`.

The answer changes both UX and tests:

- latest-claim-wins: the displaced device gets a "replaced" message; claim
  succeeds for the new device;
- conflict: the second claim fails; the user must release or sign out the
  first device.

The claim request also needs a decision on installation identity. The current
RPC stores `installation_key_hash` and `display_name`; the new API may derive
the account from the bearer token but still needs an installation binding for
permit proof and multi-device policy.

### G8 — permit compatibility

NekoProxyCore is unchanged. The Launcher currently validates the exact
permit response key set and rejects anything else. If Neko Proxy API returns a
new response shape, the new-line Launcher cannot start Core without a launcher
change and a contract revision. The contract should preserve the existing
`runtime-config-v1` wire shape for the first API version and add fields only
through an explicit version. The Launcher must never translate or repair a
permit.

The request needs an explicit binding to the claimed session. Without it, a
valid identity token could request a permit for a superseded session, which is
exactly what the current `SessionInactive`/`SessionMismatch` checks prevent.
The contract must define whether the binding is a request field or derived
server-side.

### G14 — repository ownership

The shared context assigns proxy-domain data to Neko Proxy API. The current
Launcher repository contains:

- `launcher_v2` profile/link/web-session/license/installation/session tables;
- claim/heartbeat/release/permit RPCs;
- `issue_launch_permit` Edge Function and its tests;
- `launcher_bridge` Edge Function and its tests.

P0 does not authorize moving or deleting them. The conflict is recorded so P1
does not add new-line dependencies on these artifacts and the owning repo can
plan the move/retirement after `5.1.6` support is no longer needed.

## 2026-10-25 slice-2 dispositions

| ID | Disposition | Evidence / remaining work |
| --- | --- | --- |
| G5 | **CLOSED** | Refresh is fail-closed: any refresh failure clears the stored token and requires interactive login; no grace or idempotent refresh in v0. Unit coverage includes ambiguous refresh and store-write failure. |
| G6 | **CLOSED** | Proxy API v0/OpenAPI specify claim request (`installation_key_hash`, optional `display_name`, `Idempotency-Key`) and latest-claim-wins. `ProxyApiEntitlementGateway` implements it. |
| G7 | **CLOSED** | Server heartbeat is 30 s and stale after 90 s; claim/heartbeat return a 10–60 s interval, consumed by the launcher and UI. |
| G8 | **CLOSED (contract)** | Permit request/response is specified; `ProxyApiPermitGateway` preserves the opaque permit and maps Runtime Config v1 strictly. Live permit verification is still blocked because Proxy API has not deployed the route. |
| G9 | **CLOSED** | Termination reasons come from heartbeat error codes (`session_conflict`, account, license); no direct proxy DB reads. |
| G10 | **OPEN** | `/public/status` migration remains a later slice. |
| G11 | **OPEN** | Coupons remain a later slice. |
| G12 | **CLOSED for Proxy API endpoints** | Proxy API uses the shared envelope; the client maps both the envelope and OAuth-style identity refresh errors. Identity OAuth error shape remains a documented login exception. |
| G13 | **CLOSED for consumed fields** | `/v1/me` status/display name and claim `license_valid_until` are consumed; nested license/identity-access fields remain unconsumed. |
| G14 | **CLOSED as a launcher-side decision** | No new proxy schema or migration is added to this repository. Proxy-domain migrations are proposed to live in the Proxy API repository from slice 2; existing `launcher_v2` stays legacy. No production migration was executed. |
| G15 | **CLOSED for current docs** | Current docs and plan banners mark bridge/session-minting as legacy; historical documents remain for traceability. |
| G19 | **CLOSED** | Proxy API auth-and-trust defines the endpoint/scope matrix; launcher uses `proxy:read` and `proxy:launch` only. |
| G20 | **CLOSED** | Proxy mode composes with empty Supabase URL/key, `app_factory` lazy-imports `SupabaseGateway` only in the legacy branch, a subprocess test proves the proxy import graph does not load it, and new proxy modules contain no Supabase/bridge imports. |
| G16, G17, G18 | **OPEN** | Offline/restore product behavior, client protocol/version negotiation, and exact issuer normalization remain open (non-blocking for source/dev slices). |

**New external blocker (not a launcher code gap):** identity has not deployed the
refresh grant, and Proxy API has not deployed claim/heartbeat/release/permit.
Live staging login, permit issuance, and Core E2E remain blocked; do not claim
them until those endpoints exist.

## Confirmed aligned with v0

These current behaviors already match contract v0 and should be preserved:

- Identity base path, client ID, and exact redirect
  `http://127.0.0.1:53682/auth/callback`
  (`launcher/src/neko_launcher/infrastructure/auth/web_auth.py:21`).
- PKCE S256, 43–128 character verifier, random state, exact loopback host/path,
  one-use callback, no redirect following, bounded response, HTTPS validation.
- Access/refresh material is kept out of URLs and out of diagnostics logs;
  diagnostics redact JWT/Bearer/token/password/challenge patterns
  (`launcher/src/neko_launcher/application/diagnostics.py:78`).
- Windows Credential Manager storage exists and can be reused under a new
  namespace (`launcher/src/neko_launcher/infrastructure/storage/secure_store.py:12`).
- Core Runtime Config v1 validation and the 30-second permit window are
  already strict; Core changes are out of scope.
- Single-instance enforcement exists, which is a prerequisite for safe refresh
  token rotation.
- `5.1.6` is already treated as a frozen line with its own backend, installer
  path, and trust profile.

## Owner actions

1. **Contracts owner:** ratify or correct v0 for G3–G13 and G17–G19, then freeze
   the OpenAPI/JWT/error/fixture set in `Neko-Contracts`.
2. **Identity owner:** update audience, scope, TTL, refresh grant, revocation,
   issuer normalization, and error shape.
3. **Proxy API owner:** implement the planned `/v1/me`, claim, heartbeat,
   release, permit, coupon, and public-status routes; deploy the session binding
   and error codes in staging.
4. **Launcher owner:** keep `5.1.6` frozen; the authorized source/dev slices 1–2
   are the only implementation exception; do not wire bridge/Supabase into the
   new line and wait for sign-off for later slices.
5. **Repo owners:** plan the move/retirement of proxy-domain schema and Edge
   Functions; no production changes in P0/P1.

No item in this register authorizes a release, tag, deployment, or production
migration.
