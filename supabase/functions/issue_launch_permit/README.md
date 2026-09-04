# `issue_launch_permit` — Runtime Config v1

**Status: branch implementation only.** Do not deploy this function or apply
Runtime Config migration to hosted production while deployed Core/Launcher still expects S0/lite-v1.

## Request

`POST` with `Authorization: Bearer *** access token>`.

```json
{
  "version": 1,
  "contractRevision": "runtime-config-v1",
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

## Permit & Runtime Config

Backend private key remains server-only. Header is `RS256`, `neko-launch+jwt`,
`neko-prod-key-2`. Permit lifetime is 30 seconds. Permit binds the active runtime
config with signed claims `runtime_config_version` and `runtime_config_sha256`.
Claims are exactly `iss`, `aud`, `sub`, `product`, `scope`, `challenge`, `jti`,
`iat`, `exp`, `nbf`, `runtime_config_version`, and `runtime_config_sha256`.

The response returns `runtimeConfig` with `schemaVersion: 1`, `configVersion`,
`endpointId`, `host`, `port`, `protocol: "shadowsocks"`, `cipher`, `credential`,
`issuedAt`, and `expiresAt` (lifetime exactly 120 seconds).
The permit binds the canonical ASCII serialization hash of this exact config.

## Local validation

```bash
deno test --allow-read service_test.ts runtime_contract_test.ts
```

Tests generate in-memory keys only. No hosted mutation, function deployment,
or production-key validation occurs.

```text
HOSTED RUNTIME CONFIG DEPLOYMENT = NOT PERFORMED
PRODUCTION CUTOVER = NOT PERFORMED
CORE PROTOCOL V3 MIGRATION = REQUIRED
RUNTIME CONFIG CROSS-COMPONENT E2E = NOT YET EXECUTED
```
