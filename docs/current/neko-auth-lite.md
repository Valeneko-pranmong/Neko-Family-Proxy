# NEKO-AUTH-LITE v1

**Status:** Phase 2.5 technical security gate **CLOSED/PASS**. Released through the 5.1.x production line. 5.1.6 remains public stable on the legacy password/recovery backend. 5.2.0 is a separate web-auth-only preview line; it does not auto-update 5.1.6 and requires a full uninstall before installation. 5.3.0 is the planned legacy cutover.

```text
SESSION_POLICY = LATEST_CLAIM_WINS
PERMIT_CONTRACT = LITE_V1
```

## Threat model

Core proxy start needs both an active Launcher authorization session and a valid
Backend-signed permit. Missing either condition denies start. Backend resolves
identity and entitlement from validated Supabase bearer-token state. Request
body never supplies trusted user, Launcher session, license, or installation
identity.

## Single Launcher session

**LATEST CLAIM WINS.** `launcher.claim_session` takes the existing per-user
transaction advisory lock. Every valid claim atomically revokes any prior active
Launcher session and inserts the replacement. The old Launcher session loses
future heartbeat authority and its bound Auth session loses future permit
authority.

Installation rows remain reusable history. A may claim, then B, then C, then A
again without a permanent device lock or revoke. Existing unique partial index
`launcher_sessions_one_active_per_user_idx` enforces one unrevoked session per
user. Normal `release_session` immediately revokes only caller-owned session.

Heartbeat target: 30 seconds. Backend stale timeout: 90 seconds. Heartbeat and
release require `auth.uid()`, current validated JWT `session_id`, matching
`launcher_sessions.auth_session_id`, and live `auth.sessions` ownership.

Claim, release, and permit authorization take same per-user advisory transaction
lock. Their state decision is linearized. A permit already signed before a
normal release is a 30-second launch-time snapshot; release blocks later permit
authorization but does not retroactively revoke that signed capability. Lite has
no continuous authorization or permit renewal.

## Exact Auth-session binding

Permit authorization requires:

```text
permit caller JWT session_id == active Launcher Session auth_session_id
```

A second Supabase Auth session for same account may authenticate and claim,
superseding first session. Superseded Auth session cannot request a permit:
Backend returns `SessionInactive`, never permit.

## Permit rate limit

`issue_launch_permit` consumes one per-user attempt after authentication and
before authorization. The default window is 10 attempts per 60 seconds,
serialized by a per-user advisory lock. Exhausted callers receive HTTP 429
`RateLimited` with `Retry-After: 60`; the attempt log is stored in
`launcher.permit_attempts`, which has RLS forced and no client grants.

## Lite permit API

`POST issue_launch_permit` with `Authorization: Bearer <Supabase access token>`:

```json
{
  "version": 1,
  "contractRevision": "lite-v1",
  "correlationId": "0123456789abcdef0123456789abcdef",
  "challenge": "<core-generated-challenge>"
}
```

Unknown fields and S0 fields reject. Product and scope are Backend constants:
`neko-family-proxy` and `proxy:start`.

Successful permit: RS256, `typ=neko-launch+jwt`, `kid=neko-prod-key-2`, 30
seconds. Claims: `iss`, `aud`, `sub`, `product`, `scope`, `challenge`, `jti`,
`iat`, `exp`; `nbf` retained. No `sid`, `iid`, `lid`, `cfg`, `target_pid`, or
`mode` claims.

## Core boundary

Core creates and verifies challenge, verifies Lite permit, and permits exactly
authorized START. Launcher keeps runtime command fields such as target PID and
profile/server references for Core runtime transport; they are not Lite permit
inputs or claims. No continuous permit renewal belongs to Lite.

## Retained hardening

Owned Core lifecycle, bounded IPC, malformed JSON rejection, correlation IDs,
named-pipe server PID validation, and exact-child cleanup remain useful
defensive controls. They are not Lite release blockers.

## Historical release blockers (cleared)

The pre-production gate listed these blockers:
`BACKEND_PERMIT_ISSUER_UNAVAILABLE`, `CORE_PUBLIC_KEY_UNAVAILABLE`,
`CORE_AUTHORIZED_START_UNAVAILABLE`,
`SINGLE_ACTIVE_SESSION_ENFORCEMENT_UNAVAILABLE`,
`SESSION_CONCURRENCY_PROTECTION_UNAVAILABLE`,
`CORE_CHALLENGE_VERIFICATION_UNAVAILABLE`, `LITE_E2E_UNVERIFIED`.
The active gate in `production_authorization.py` now reports no blockers, and
`app_factory.py` composes the production authorization adapters.

S0 configuration SHA/PID cryptographic binding,
package-SHA ceremony, continuous renewal, advanced replay DB, strict pipe proof,
anti-debugging, and S1 are historical or optional hardening—not Lite blockers.

## Deployment status

```text
HOSTED LITE DEPLOYMENT = MIGRATION DEPLOYED AND VERIFIED
CURRENT PUBLIC STABLE = v5.1.6 (legacy password/recovery backend)
NEXT LINE = v5.2.0 WEB-AUTH-ONLY PREVIEW (SEPARATE INSTALL; UNINSTALL 5.1.6 FIRST)
WEB AUTH TRANSITION = LAUNCHER IMPLEMENTED, FLAG OFF; BRIDGE/MAPPING PENDING
LAUNCHER PRODUCTION AUTHORIZATION = ENABLED (NO BLOCKERS)
CORE LITE MIGRATION = VERIFIED AT CORE AUTHORITY
LITE CROSS-COMPONENT E2E = PHASE 2.5 TECHNICAL SECURITY GATE PASS
HOSTED_MIGRATION = 20260821120000_neko_auth_lite_latest_claim_wins
TEMPORARY_AUTOTEST_USER_ENTITLEMENT = CLEANED UP
FINAL_ACTIVE_TEST_SESSIONS = 0
NEXT CUTOVER = v5.3.0 (LEGACY 5.1.6 REMOVAL; PLANNING)

## Web auth transition (in progress)

The Launcher now contains the browser + loopback + PKCE flow for NEKO NETWORK ID (Discord) behind `NEKO_WEB_AUTH_ENABLED` and a required `NEKO_AUTH_BRIDGE_URL`. The identity token is a custom 5-minute bearer that must be exchanged by the proxy bridge for a real Supabase session. The 5.1.6 legacy line keeps password login; 5.2.0 is the separate web-auth-only preview target and must remove password/recovery. Web auth is not enabled in production until the bridge, identity→proxy mapping, one-time link/claim flow, installer separation, and staging E2E are complete. See [web-auth-launcher.md](web-auth-launcher.md) and the [separation plan](../superpowers/plans/2026-10-25-web-auth-separation-and-5-3-0-cutover.md).

## Phase 2.5 closure

The verified distinct-auth proof recorded pairwise-distinct Auth sessions, the
A→B→C→A replacement sequence, old A/B/C heartbeat denial, and old A/B/C future
permit denial as HTTP 403 `SessionInactive`. Successful permits, Core starts,
and Core challenges were all zero. Remembered installation A was reused and
final cleanup passed.

Original run Edge evidence was **A=MISSING, B=PASS, C=PASS**. A supplemental
old-A Edge run independently passed. The original run must not be represented
as containing all three Edge logs.

Historical `FIRST_ACTIVE_WINS` behavior remains superseded history and is not
erased. `HISTORICAL_FORCE_PUSH_VIOLATION = RECORDED` remains recorded;
`PROCESS_COMPLIANCE = FAIL` until Owner explicitly waives it.
```
