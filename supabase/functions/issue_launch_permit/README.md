# `issue_launch_permit` — NEKO-AUTH-LITE v1

**Status: branch implementation only.** Do not deploy this function or apply
Lite migration to hosted production while deployed Core still expects S0.

## Request

`POST` with `Authorization: Bearer <Supabase access token>`.

```json
{
  "version": 1,
  "contractRevision": "lite-v1",
  "correlationId": "0123456789abcdef0123456789abcdef",
  "challenge": "<43-character base64url Core challenge>"
}
```

Exact fields only. No client-supplied `userId`, `sessionId`, `licenseId`,
`installationId`, `configurationDigest`, `processName`, `targetPid`, `mode`,
`product`, or `scope` is accepted.

## Authority

Function validates bearer with Supabase Auth. Caller-scoped RPC
`launcher.authorize_launch_permit(text)` then checks active profile,
entitlement, exact Auth-session ownership, and a fresh 90-second Launcher
heartbeat under same per-user advisory transaction lock as session claims.

`JWT session_id == launcher_sessions.auth_session_id` is mandatory. Auth B from
same account cannot issue a permit owned by Auth A.

## Permit

Backend private key remains server-only. Header is `RS256`, `neko-launch+jwt`,
`neko-prod-key-2`. Permit lifetime is 30 seconds. Claims are exactly `iss`,
`aud`, `sub`, `product`, `scope`, `challenge`, `jti`, `iat`, `exp`, plus retained
`nbf`. S0 session/install/license/digest/PID/mode claims are absent.

## Local validation

```bash
npx --yes tsx --test service_test.ts migration_contract_test.ts runtime_contract_test.ts
npx --yes deno check index.ts service.ts
npx --yes deno fmt --check index.ts service.ts *_test.ts
```

Tests generate in-memory keys only. No hosted mutation, function deployment,
or production-key validation occurs.

```text
HOSTED LITE DEPLOYMENT = NOT PERFORMED
PRODUCTION CUTOVER = NOT PERFORMED
CORE LITE MIGRATION = REQUIRED
LITE CROSS-COMPONENT E2E = NOT YET EXECUTED
```
