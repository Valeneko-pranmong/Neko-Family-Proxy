# P0 Sign-off Checklist — Launcher Contract

**Status:** awaiting contract-owner review
**Date:** 2026-10-25
**Baseline:** NEKO Unified Platform contract baseline v0
**Related:** [launcher-consumer-contract.md](launcher-consumer-contract.md),
[gap-and-conflict-register.md](gap-and-conflict-register.md)

P0 is a design/sign-off gate. No Launcher runtime code, schema, deployment,
tag, or publication is authorized by this checklist. P1 starts only after the
decisions below are recorded and the contract is frozen.

## 1. Decisions required

| ID | Decision | Launcher position / recommendation | Owner | Blocks |
| --- | --- | --- | --- | --- |
| D1 | Identity access-token migration: `aud=neko-proxy-api`, `scope="proxy:launch proxy:read"`, 10-minute lifetime. | Required. The Launcher will not accept a bridge-audience token in the new line. | Identity + Contracts | All P1 |
| D2 | Authorization-code request must include `redirect_uri` (live identity requires it; v0 sketch omits it). | Include `redirect_uri` in the frozen request schema. This matches the live server and the current Launcher. | Contracts + Identity | Login |
| D3 | Refresh-token ambiguity: rotate-on-use plus reuse-revocation has a crash/timeout window. Choose idempotent refresh, a bounded previous-token grace, or explicit re-login acceptance. | Until resolved, the client will not resend an old token after an ambiguous refresh and will require login. A server-side idempotent refresh is preferred. | Identity + Contracts | Refresh |
| D4 | Refresh-token revocation / logout endpoint. | A local clear is not a server-side logout. Define `POST` revocation (or an equivalent) and its error semantics. Until then, sign-out is documented as local-only. | Identity + Contracts | Sign-out security |
| D5 | Claim request fields, installation binding, and conflict policy (`latest-claim-wins` vs `session_conflict`). | Preserve the current installation fields if they are still required; define one explicit conflict policy and its user outcome. Do not leave both behaviors implicit. | Contracts + Proxy API | Session |
| D6 | Permit request binding: session ID/installation in the body or derived server-side; confirm `machineProof` remains mandatory. | The permit must be bound to the claimed session and a fresh Core challenge. Preserve `machineProof` unless the security model explicitly replaces it. | Contracts + Proxy API | Permit |
| D7 | Permit response shape and Runtime Config v1 compatibility. | Preserve the current exact `runtime-config-v1` request/response keys, 30-second permit, 120-second Runtime Config window. Any change needs a version and a Core-side plan. | Contracts + Proxy API | Permit / Core |
| D8 | `/v1/me` typed schema: identity/proxy IDs, status enum, display name, license summary, ban/app-access state. | Provide a typed schema and field nullability. Do not require the client to parse free-form text. | Contracts + Proxy API | UI / session |
| D9 | Session termination reason / heartbeat denial detail. | Add a safe reason code (replaced, revoked, license_expired, account_restricted) or accept a generic client message. The client will not read proxy tables. | Proxy API + Contracts | Session UX |
| D10 | Public status response schema and origin. | Preserve the current `ok/proxy/status/load_level/average_30m` shape if possible; otherwise version it. The new line must not call the Control Room. | Proxy API + Contracts | Status |
| D11 | Coupon request/response and coupon-specific error codes. | Freeze `{code}` plus `product_code`, `days_added`, `valid_until`, and map coupon errors to stable codes or a documented extension. | Contracts + Proxy API | Coupons |
| D12 | Error envelope scope: identity OAuth-style errors vs shared envelope; define `request_id`, `Retry-After`, and user-safe `message`. | Keep OAuth errors for the token endpoint only if explicitly documented; use the shared envelope for Proxy API. Provide `Retry-After` on 429. | Contracts + Identity + Proxy API | Error handling |
| D13 | Idempotency-Key semantics: format, scope, TTL, body binding, replay response, conflict status. | Client will use UUIDv4 per logical operation and reuse it only for identical retries. Server must define replay/conflict behavior. | Contracts + Proxy API | Claim/permit/coupon |
| D14 | Heartbeat interval, stale timeout, and failure budget. | Server-provided interval is authoritative. Define the stale window and what the client may display before it stops new launches. | Contracts + Proxy API | Heartbeat |
| D15 | Client version / protocol negotiation and request correlation header. | Add a version header or equivalent before P1; the Launcher needs a way to detect an incompatible API without guessing. | Contracts | Compatibility |
| D16 | Offline/restore behavior and cached-profile display. | No cached authorization and no offline launch. A cached profile may be displayed only with an explicit "offline/unverified" state if product approves. | Product + Contracts | Restore UX |
| D17 | Per-endpoint scope matrix, especially coupon redeem, heartbeat, and release. | Freeze a scope for every endpoint; the token's two scopes are not sufficient to infer all of them. | Contracts | Authorization |
| D18 | Ownership/move plan for `launcher_v2` schema, `issue_launch_permit`, and `launcher_bridge`. | New line must not depend on them. Plan the move/retirement separately; no production change in P0/P1. | Repo owners + Contracts | Architecture |
| D19 | Update or supersede the current bridge/allowlist P0–P5 documents. | Mark `docs/current/web-auth-launcher.md`, `p0-p5-status-audit.md`, `launcher-bridge-staging-runbook.md`, and the separation plan as historical/superseded for the new line. | Launcher docs owner | P1 clarity |

If a decision cannot be made before P1, the affected endpoint stays out of P1
scope. Do not implement a guessed default.

**Slice-2 closures (2026-10-25):** D3 (fail-closed refresh), D5 (claim fields +
latest-claim-wins), D6 (session-bound permit), D7 (Runtime Config v1), D8
(consumed `/v1/me` fields), D9 (heartbeat-derived termination reasons),
D14 (heartbeat interval/staleness), and D17 (scope matrix) are resolved by the
Proxy API v0/OpenAPI contract and the source/dev implementation. D1/D2 identity
deployment, D4 revocation, D10 status, D11 coupons, D12 identity envelope,
D13 retry/idempotency details, D15 protocol version, D16 offline behavior, and
D18 migration execution remain open.

## 2. P1 entry criteria

**Authorized exception (2026-10-25):** the owner authorized source/dev-only P1
slices 1–2 for the `NEKO_PROXY_API_URL` account preflight, session lifecycle,
and permit path. They are not release-capable, do not close this checklist, and
do not satisfy the criteria below for any later slice.

P1 (later slices) may start only when all of the following are true:

- Every **BLOCKER** in the gap register is closed or explicitly deferred with a
  named owner and a P1 exclusion.
- Identity staging issues a `neko-proxy-api`-audience access token and a
  rotating refresh token; the refresh and revocation behavior is documented.
- Neko Proxy API staging exposes the frozen `/v1` subset and returns the shared
  error envelope.
- The contract owner has frozen the request/response schemas and provided
  fixtures for `/v1/me`, claim, heartbeat, release, permit, coupons, and public
  status.
- The new-line build separation is approved: no Supabase key/session, no
  bridge, no allowlist, no admin token.
- `5.1.6` regression scope and frozen release artifacts are identified.
- No production endpoint, migration, or release is part of P1.

## 3. Proposed P1 slices (Launcher only)

Each slice is independently reviewable and must keep `5.1.6` untouched.

### S1 — Build-line and configuration isolation

- Introduce an explicit new-line build selection.
- New-line config contains only Proxy API/identity settings.
- Fail closed if Supabase, bridge, allowlist, or password settings are present
  in the new-line build.
- Add artifact guards that scan the new-line bundle for forbidden hosts,
  keys, symbols, and strings.
- Exit: guard tests prove the new line cannot construct a Supabase client or a
  bridge exchange.

### S2 — HTTP transport, envelope, idempotency, retry

- HTTPS-only transport with no redirects, bounded bodies, and timeouts.
- Strict shared-envelope parser and unknown-code handling.
- UUIDv4 idempotency keys, same-key retries, bounded backoff, 429
  `Retry-After`.
- Redaction tests for every sensitive field.
- Exit: mock-server contract tests for success, 4xx, 5xx, 429, malformed
  envelope, oversized body, redirect, and timeout.

### S3 — Identity PKCE and refresh-token vault (no bridge)

- Exact loopback/PKCE/state flow.
- Authorization-code exchange including `redirect_uri`.
- Single-flight refresh with atomic vault replacement and the ambiguous-result
  rule.
- New-line credential-store namespace; no legacy read.
- Exit: login/refresh tests and a guard proving no bridge exchange exists.

### S4 — `/v1/me` and session lifecycle

- Profile/status/license display mapping without Supabase user IDs.
- Claim with server-provided heartbeat interval.
- Heartbeat scheduling, failure classification, release, restore, offline
  state.
- Session conflict policy from D5.
- Exit: session state-machine tests and server-authority tests proving local
  cache never authorizes launch.

### S5 — Permit and Runtime Config

- Preserve the current `runtime-config-v1` request/response shape through Neko
  Proxy API.
- Fresh challenge, fresh heartbeat, idempotency key, single-flight start.
- Strict validation; no disk/log exposure; no legacy fallback.
- Exit: permit tests against real staging Proxy API and Core; malformed
  response fails closed; stale challenge/rate limit are handled.

### S6 — Coupons, status, UI mapping

- Coupon redeem with idempotency and server-authoritative entitlement refresh.
- Public status from Neko Proxy API.
- Error-code-to-user-message mapping; account pending/suspended/license expired
  states.
- Exit: UI tests for each state; status failure isolated.

### S7 — Staging E2E and release-readiness evidence

- Full Discord login -> `/v1/me` -> claim -> heartbeat -> Core challenge ->
  permit -> Core running -> release.
- Expired access refresh, revoked session, suspended account, expired license,
  rate limit, API outage, malformed response.
- Legacy `5.1.6` regression suite passes unchanged.
- Packaged Windows smoke with no Supabase/bridge strings.
- No publication, tag, or production migration.
- Exit: evidence bundle reviewed by the owner; publication remains a separate
  approval.

## 4. Verification commands

For P0 documentation changes (from the repository root):

```bash
launcher/.venv/Scripts/python.exe -B scripts/check_repository_safety.py
launcher/.venv/Scripts/python.exe -m pytest -q tests
```

For Launcher checks (from `launcher/`), matching `.github/workflows/ci.yml`:

```bash
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m pytest -q -m "not integration"
```

For P1 implementation, in addition:

```bash
# Launcher suite
cd launcher
.venv/Scripts/python.exe -m pytest -q -m "not integration"

# Security checks (when the tools are installed)
.venv/Scripts/python.exe -m pip_audit
.venv/Scripts/python.exe -m bandit -r src

# New-line build guard (P1-created)
# Must fail if the artifact contains Supabase/bridge/allowlist/password strings.
```

Staging E2E requires the owner to provide identity test access, a Discord test
account, and a next-line proxy account with a short-lived entitlement. No
production credentials.

## 5. P0 verification evidence (2026-10-25)

- Repository safety check: **PASS**.
- Launcher Ruff check: **PASS**.
- Launcher test suite (`-m "not integration"`): **2,631 passed, 4 skipped,
  7 deselected**.
- Root tests (`tests/`): **74 passed, 1 environment-limited failure**.
  `tests/test_e2e_release_pipeline.py::test_release_controller_e2e` requires
  `E:\Github\artifacts\...\base-metadata.json`, which is not present on this
  host; it is unrelated to documentation changes.
- Relative-link check and secret-pattern scan for `docs/contracts/`: **PASS**.
- No runtime code, schema, migration, or release artifact changed by P0.

## 6. P0 gate statement

When the decisions in section 1 are recorded and the P1 entry criteria in
section 2 are met, P0 is complete. The authorized source/dev slices 1–2 are the
only exception. Until then:

- do not implement beyond the authorized source/dev slices;
- do not modify `5.1.6`;
- do not deploy migrations or functions;
- do not tag, publish, or enable web auth in production;
- report any new conflict to the contract owner rather than inventing a
  parallel contract.
