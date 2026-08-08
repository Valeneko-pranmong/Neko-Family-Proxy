# Launcher S0 Consumer Contract Proposal

> **HISTORICAL — SUPERSEDED PROPOSAL.** Use
> [`../blocked/neko-auth-s0-production-handoff.md`](../blocked/neko-auth-s0-production-handoff.md)
> for the current technical baseline and stop rules.

**Work item:** `Launcher-S0-Consumer-01`
**Status:** `PROPOSED — DESIGN READY / IMPLEMENTATION PARTIAL`
**Owner:** Launcher Team
**Required reviewers:** Core + Backend + Security + Connector
**Contract revision:** `launcher-s0-proposal-01`
**Approval state:** Not frozen; not approved for production wiring

> Sanitized proposal only. It contains no production endpoint, token, permit, credential, private key, customer identifier, or raw proxy configuration.

## 1. Ownership and stop rule

### OWNED BY LAUNCHER — PROPOSED

Launcher proposes and can implement after cross-team approval:

- protocol v2 consumer schemas and strict client parsing;
- frame encoding/size limits used by the Launcher client;
- Launcher-side timeout ceilings;
- correlation generation/validation;
- typed Launcher lifecycle states and allow-listed UI mappings;
- exact orchestration, retry, ambiguity, and owned-process cleanup behavior;
- opaque profile/server reference validation;
- artifact identity requirements consumed before Core spawn.

### REQUIRES CORE APPROVAL / CORE OWNERSHIP

- Core command support and response semantics;
- named-pipe and mutex identities;
- challenge generation/lifetime/consumption;
- final executable/RID/dependency manifest;
- typed Core readiness and status behavior;
- current-user pipe ACL implementation.

### REQUIRES BACKEND/SECURITY DECISION

- permit endpoint and HTTP envelope;
- JWT header/claims, issuer, audience, key IDs, TTL, skew, signing and rotation;
- authenticated identity source and authority checks;
- rate limits and Backend error taxonomy;
- continuous authorization and revocation policy;
- short-lived proxy access material.

Launcher will stop at typed interfaces and fixture hooks for every Backend/Security-owned item. No draft value below is frozen until all required reviewers approve the same revision/hash.

## 2. Protocol and transport

All values in this section are **PROPOSED — OWNED BY LAUNCHER, REQUIRES CORE + SECURITY APPROVAL**.

| Item | Exact proposed value |
|---|---|
| Protocol version | JSON integer `2` |
| Transport | Windows current-user-only named pipe; exact name is Core-owned and pending approval |
| Frame | 4-byte unsigned big-endian payload length followed by exactly that many UTF-8 bytes |
| Maximum JSON payload | `8192` bytes |
| Maximum response payload | `8192` bytes |
| Zero-length frame | Reject |
| Length above maximum | Reject before payload allocation/read |
| Encoding | Strict UTF-8, no BOM; reject malformed sequences and BOM |
| JSON top level | Exactly one object; no trailing non-whitespace data |
| Field names | Case-sensitive exact lower camel case |
| Command/status values | Case-sensitive exact values documented below |
| Unknown fields | Reject every request and response |
| Duplicate fields | Reject every duplicate field, including equal-valued duplicates |
| Numbers | JSON integers only where specified; reject booleans/floats/coercion |
| Partial reads/writes | Loop until complete within one operation deadline; EOF before completion is failure |
| Correlation ID | Lowercase hexadecimal, exactly 32 ASCII characters (`uuid4().hex`) |
| Process name | Exact ASCII `pso2.exe`, 8 characters |
| Opaque reference | Regex `^(profile|server)-[0-9]{1,6}$`, maximum 14 ASCII characters |
| Challenge | Non-empty base64url without padding; exact length is Core/Security-owned |
| Permit | Non-empty opaque compact value, maximum `4096` ASCII characters; Launcher does not decode |

The pipe name and mutex name cannot be selected by Launcher alone. Until Core publishes approved identities, production channel composition remains unavailable.

## 3. Exact protocol v2 schemas

Schemas below are **PROPOSED**. Every property shown is required. No additional properties are accepted.

### 3.1 Challenge request

```json
{
  "version": 2,
  "command": "challenge",
  "correlationId": "0123456789abcdef0123456789abcdef"
}
```

Field contract:

| Field | Type | Exact rule |
|---|---|---|
| `version` | integer | exact `2` |
| `command` | string | exact `challenge` |
| `correlationId` | string | exact 32 lowercase hex |

### 3.2 Challenge response — success

```json
{
  "version": 2,
  "kind": "challenge",
  "correlationId": "0123456789abcdef0123456789abcdef",
  "succeeded": true,
  "challenge": "syntheticBase64urlChallenge"
}
```

Required rules:

- `kind` exact `challenge`;
- `succeeded` exact JSON boolean `true`;
- `challenge` mandatory and bounded;
- `status` and `errorCode` forbidden.

### 3.3 Start request

```json
{
  "version": 2,
  "command": "start",
  "correlationId": "0123456789abcdef0123456789abcdef",
  "processName": "pso2.exe",
  "profileReference": "profile-0",
  "serverReference": "server-0",
  "permit": "opaque-signed-value"
}
```

All seven fields are mandatory. `permit` is serialized only into the direct pipe buffer and is forbidden from argv, environment, files, logs, telemetry, UI, and exception details.

### 3.4 Status request

```json
{
  "version": 2,
  "command": "status",
  "correlationId": "0123456789abcdef0123456789abcdef"
}
```

### 3.5 Stop request

```json
{
  "version": 2,
  "command": "stop",
  "correlationId": "0123456789abcdef0123456789abcdef"
}
```

### 3.6 Result response — success

```json
{
  "version": 2,
  "kind": "result",
  "correlationId": "0123456789abcdef0123456789abcdef",
  "succeeded": true,
  "status": "Running"
}
```

Allowed `status` values are exact `Running` and `Stopped`. A successful `start` must return `Running`; pipe connection, PID, process survival, `Starting`, or absent status is not readiness.

### 3.7 Result response — failure

```json
{
  "version": 2,
  "kind": "result",
  "correlationId": "0123456789abcdef0123456789abcdef",
  "succeeded": false,
  "status": "Failed",
  "errorCode": "AuthorizationUnavailable"
}
```

Failure requires exact `status=Failed` and one allow-listed `errorCode`. Arbitrary message/detail/stack/identifier fields are forbidden.

Proposed allow-list:

- `AuthorizationRequired`
- `AuthorizationInvalid`
- `AuthorizationExpired`
- `AuthorizationReplay`
- `AuthorizationUnavailable`
- `SessionInactive`
- `ProcessNotFound`
- `ProcessExited`
- `AlreadyRunning`
- `ProtocolInvalid`
- `Timeout`
- `Cancelled`
- `StartFailed`
- `StopFailed`

Core/Security must approve the final taxonomy and semantics.

## 4. Timeout proposal

All values are **PROPOSED — Launcher ceiling; Core must support compatible deadlines**.

| Operation | Deadline |
|---|---:|
| Exact target wait | 120.0 s |
| Pipe connect/readiness | 5.0 s |
| Single frame write | 2.0 s |
| Single frame read | 5.0 s |
| Challenge round trip | 5.0 s |
| Backend permit request | 10.0 s |
| Authorized start / typed Running | 15.0 s |
| Status round trip | 3.0 s |
| Graceful stop | 10.0 s |
| Owned-process exit after stop | 5.0 s |
| Owned-process kill wait | 5.0 s |

Rules:

- deadlines use monotonic time locally;
- each operation has one total deadline, not a reset per partial read/write;
- cancellation terminates the attempt and enters bounded cleanup;
- no unbounded wait is permitted;
- timeout values do not define JWT/challenge validity; those remain Security/Core-owned.

## 5. Opaque start configuration

This section is **PROPOSED — OWNED BY LAUNCHER, canonical hash requires joint approval**.

Launcher accepts only a typed command containing:

```text
protocolVersion=2
processName=pso2.exe
profileReference=profile-0
serverReference=server-0
```

Validation:

- `processName` must already equal exact `pso2.exe`;
- profile/server values must match their exact regex and ASCII/length bounds;
- references are opaque; Launcher does not load or forward endpoint, port, cipher, password, or raw proxy settings;
- Launcher does not trim, case-fold, or otherwise normalize a reference after validation;
- canonical bytes/hash algorithm and shared positive/negative fixtures require Core + Backend + Security approval before production use.

## 6. Launcher lifecycle state machine

States below are **PROPOSED — OWNED BY LAUNCHER**:

```text
Idle
→ WaitingForTarget
→ LocalPreconditionsValidated
→ HeartbeatValidated
→ CoreStarting
→ ControlChannelReady
→ ChallengeReceived
→ PermitRequested
→ StartSubmitted
→ Running
→ Stopping
→ Idle
```

Any failure before `Running` follows:

```text
Failed
→ best-effort typed stop when channel exists
→ bounded graceful owned-host stop
→ owned-host kill only after timeout
→ Idle with allow-listed error
```

Exact order for one attempt:

1. acquire single-flight lock;
2. validate authenticated context, active entitlement, claimed session, installation hash, and opaque references;
3. wait for exact `pso2.exe` and retain target identity;
4. perform a new online heartbeat precondition; periodic heartbeat grace is not admissible evidence;
5. recheck the same target identity;
6. validate approved artifact manifest and spawn Core with a fixed argument list and no inherited sensitive environment;
7. connect to the approved current-user pipe within deadline;
8. recheck target; request one challenge;
9. recheck target; request one Backend permit;
10. recheck cancellation and target;
11. send authorized `start` exactly once;
12. accept readiness only from matching typed `Running` response;
13. monitor target/Core/session and perform bounded cleanup.

## 7. Retry and ambiguity rules

**PROPOSED — OWNED BY LAUNCHER, REQUIRES CORE/BACKEND APPROVAL**:

- no permit is requested before a challenge is received;
- no challenge or permit is reused after any failure;
- no `start` frame is retransmitted after write timeout, read timeout, disconnect, cancellation, malformed response, or correlation mismatch;
- an ambiguous start attempt is resolved by bounded cleanup; a later attempt starts from target/preconditions/challenge/permit again;
- duplicate/concurrent start is rejected before a second target/heartbeat/host/permit flow;
- target loss after heartbeat but before host spawn produces zero host side effects;
- target loss after host spawn triggers bounded cleanup;
- only a contract-approved typed status query may reconcile an ambiguous result; until approved, Launcher cleans up rather than guessing;
- stop is idempotent from Launcher UX but a stop failure remains a typed failure and cannot be reported as successful cleanup.

## 8. Launcher states and allow-listed Thai UI mapping

**PROPOSED — OWNED BY LAUNCHER**:

| Typed condition | Thai UI message |
|---|---|
| `AuthorizationRequired` | `ยังไม่ได้รับอนุญาตให้เริ่มการเชื่อมต่อ กรุณาลองใหม่` |
| `AuthorizationInvalid` | `การอนุญาตเริ่มใช้งานไม่ถูกต้อง กรุณาลองใหม่` |
| `AuthorizationExpired` | `การอนุญาตหมดอายุ กรุณาลองใหม่` |
| `AuthorizationReplay` | `คำขอเริ่มใช้งานถูกใช้แล้ว กรุณาลองใหม่` |
| `AuthorizationUnavailable` | `ตรวจสอบสิทธิ์ออนไลน์ไม่ได้ กรุณาลองใหม่` |
| `SessionInactive` | `เซสชันไม่พร้อมใช้งาน กรุณาเข้าสู่ระบบใหม่` |
| `ProcessNotFound` | `ยังไม่พบ pso2.exe จึงยังไม่เริ่มการเชื่อมต่อ` |
| `ProcessExited` | `pso2.exe ปิดแล้ว การเชื่อมต่อถูกหยุด` |
| `AlreadyRunning` | `การเชื่อมต่อกำลังทำงานอยู่แล้ว` |
| protocol/malformed/correlation failure | `การสื่อสารกับระบบไม่ถูกต้อง กรุณาลองใหม่` |
| timeout | `ระบบใช้เวลานานเกินกำหนด กรุณาลองใหม่` |
| cancellation | `ยกเลิกการเริ่มใช้งานแล้ว` |
| start/stop failure | `เริ่มหรือหยุดการเชื่อมต่อไม่สำเร็จ กรุณาลองใหม่` |

No arbitrary exception string, protocol payload, identifier, endpoint, expected claim, or token fragment may reach the UI.

## 9. Artifact identity proposal

**PROPOSED — Launcher consumer requirements; exact artifact set requires Core approval**:

| Item | Proposal |
|---|---|
| Executable basename | `NekoProxyCore.exe` |
| Architecture/RID | Windows x64 / `win-x64` |
| Packaging | immutable versioned Core bundle staged before Launcher packaging |
| Manifest basename | `NekoProxyCore.manifest.json` |
| Manifest encoding | strict UTF-8 without BOM; canonical JSON fixture jointly approved |
| Manifest fields | contract revision/hash, Core version, RID, ordered complete file list, lowercase SHA-256 per file |
| Hash verification | every required file before spawn and before package inclusion; missing/extra/mismatch fails closed |
| Executable invocation | fixed argument list approved by Core; no shell; no permit/token/credential/config secret |
| Pipe name | `REQUIRES CORE DECISION` |
| Mutex name | `REQUIRES CORE DECISION` |
| Code-signing policy | `REQUIRES SECURITY/RELEASE DECISION` |

The existing optional `ProxyCore` directory and legacy `ProxyCore.exe` distribution text are not sufficient for this proposal. Production release must fail when the approved manifest or complete dependency set is absent.

## 10. Required cross-team decisions

### Core

- approve/modify exact schemas, framing, limits, statuses, and error taxonomy;
- provide pipe/mutex identities;
- provide challenge representation/lifecycle;
- provide final executable/RID/dependency manifest and fixed host arguments;
- confirm partial-frame and timeout behavior.

### Backend

- provide permit request/response schema and authenticated endpoint/RPC semantics;
- define server-side authority checks and typed errors;
- define request/body bounds and rate limiting;
- confirm one-attempt/reissue behavior.

### Security

- approve protocol bounds and leakage policy;
- freeze JWT header/claims/issuer/audience/product/scope/TTL/skew;
- freeze key custody/rotation/revocation;
- freeze canonical config hash encoding and fixtures;
- freeze continuous authorization and proxy-access architecture.

### Joint

- publish a versioned sanitized fixture package with revision and SHA-256;
- approve change control and cross-repository gates.

## 11. Launcher merge and exit gates

Launcher merge gate for contract-independent code:

- deterministic unit tests for every blocked precondition and zero side effects;
- Ruff and non-integration unit suite pass;
- production composition remains `AuthorizationPendingProxyGateway`;
- no secret-bearing argv/environment/file/log/UI path;
- documents report `DESIGN READY / IMPLEMENTATION PARTIAL`.

Production wiring gate:

- one approved contract revision/hash across Launcher/Core/Backend/Security;
- approved fixtures and artifact manifest available;
- L1–L5 production adapters pass security tests;
- clean-package and cross-repository negative matrix pass.

Cross-repository exit gate:

- real ship artifacts produce exactly one typed `Running` runtime only for valid target + valid Backend permit;
- every absent/invalid/replayed/expired/mismatched authorization case has engine side effects zero;
- bounded cleanup leaves no orphan;
- secret sentinel and direct-proxy bypass gates pass;
- QA and Security sign off.

## 12. Requested review response

```text
Team:
Owner:
Approver:
Reviewed proposal revision: launcher-s0-proposal-01
Decision: APPROVED / APPROVED WITH CHANGES / BLOCKED
Requested changes:
Security-impacting TBDs:
Expected fixture/artifact delivery:
Repository merge gate:
Cross-repository exit gate:
```
