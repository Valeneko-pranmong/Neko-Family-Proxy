# NEKO-AUTH-LITE v1

**Status:** implementation branch only. Not deployed. Not production cutover.

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

## Release blockers

Production composition remains fail closed until these exist and pass:
`BACKEND_PERMIT_ISSUER_UNAVAILABLE`, `CORE_PUBLIC_KEY_UNAVAILABLE`,
`CORE_AUTHORIZED_START_UNAVAILABLE`,
`SINGLE_ACTIVE_SESSION_ENFORCEMENT_UNAVAILABLE`,
`SESSION_CONCURRENCY_PROTECTION_UNAVAILABLE`,
`CORE_CHALLENGE_VERIFICATION_UNAVAILABLE`, `LITE_E2E_UNVERIFIED`.

S0 configuration SHA/PID cryptographic binding,
package-SHA ceremony, continuous renewal, advanced replay DB, strict pipe proof,
anti-debugging, and S1 are historical or optional hardening—not Lite blockers.

## Deployment status

```text
HOSTED LITE DEPLOYMENT = NOT PERFORMED
PRODUCTION CUTOVER = NOT PERFORMED
CORE LITE MIGRATION = REQUIRED
LITE CROSS-COMPONENT E2E = NOT YET EXECUTED
```
