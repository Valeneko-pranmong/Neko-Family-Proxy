# `issue_launch_permit` — Lite v1 + Runtime Config v1

**Status: branch implementation only.** This function accepts both the deployed
`lite-v1` contract and the forward `runtime-config-v1` contract. Do not deploy
or apply the Runtime Config migration without the separate production gate.

## Request

`POST` with `Authorization: Bearer <Supabase access token>`.

```json
{
  "version": 1,
  "contractRevision": "lite-v1 | runtime-config-v1",
  "correlationId": "0123456789abcdef0123456789abcdef",
  "challenge": "<43-character base64url Core challenge>"
}
```

Exact fields only. Unknown contract revisions fail closed. No client-supplied
`userId`, `sessionId`, `licenseId`, `installationId`, `configurationDigest`,
`processName`, `targetPid`, `mode`, `product`, or `scope` is accepted.

## Authority

Function validates bearer with Supabase Auth. Caller-scoped RPC
`launcher.authorize_launch_permit(text)` then checks active profile,
entitlement, exact Auth-session ownership, and a fresh 90-second Launcher
heartbeat under same per-user advisory transaction lock as session claims.

`JWT session_id == launcher_sessions.auth_session_id` is mandatory. Auth B from
same account cannot issue a permit owned by Auth A.

## Permit contracts

Backend private key remains server-only. Both paths use the legacy-compatible
header `RS256`, `neko-launch+jwt`, `neko-prod-key-2` and a 30-second permit.

### `lite-v1`

This path preserves the pre-Runtime-Config response exactly: `version`,
`contractRevision`, `correlationId`, `succeeded`, `permit`, and
`expiresInSeconds`. Claims are exactly `iss`, `aud`, `sub`, `product`, `scope`,
`challenge`, `iat`, `nbf`, `exp`, and `jti`. It does not load active runtime
config, and neither `runtimeConfig` nor `runtime_config_*` fields are present.

### `runtime-config-v1`

This path binds the active runtime config with signed claims
`runtime_config_version` and `runtime_config_sha256`. Claims are exactly `iss`,
`aud`, `sub`, `product`, `scope`, `challenge`, `jti`, `iat`, `exp`, `nbf`,
`runtime_config_version`, and `runtime_config_sha256`.

The response returns `runtimeConfig` with `schemaVersion: 1`, `configVersion`,
`endpointId`, `host`, `port`, `protocol: "shadowsocks"`, `cipher`, `credential`,
`issuedAt`, and `expiresAt` (lifetime exactly 120 seconds). The permit binds the
canonical ASCII serialization hash of this exact config. Missing, unavailable,
or invalid runtime config fails closed without affecting `lite-v1`.

## Local validation

```bash
deno test --allow-read service_test.ts runtime_contract_test.ts
```

Tests generate in-memory keys only. No hosted mutation, function deployment, or
production-key validation occurs.

```text
HOSTED RUNTIME CONFIG DEPLOYMENT = NOT PERFORMED
PRODUCTION CUTOVER = NOT PERFORMED
CORE PROTOCOL V3 MIGRATION = REQUIRED
RUNTIME CONFIG CROSS-COMPONENT E2E = NOT YET EXECUTED
```
