# NekoProxyCore — S0 Security Contract Freeze Request

> **HISTORICAL — REQUEST SUPERSEDED BY A LATER BASELINE.** Use
> [`../blocked/neko-auth-s0-production-handoff.md`](../blocked/neko-auth-s0-production-handoff.md)
> for current repository guidance.

วันที่จัดทำ: 2026-08-03
Repository: `D:\NekoProxyCore`
Branch: `feature/neko-headless`
ผู้ร้องขอ: NekoProxyCore Team
ผู้รับคำขอ: Launcher, Backend, Security และ Core teams
สถานะ: **ACTION REQUIRED — CROSS-TEAM CONTRACT FREEZE**

เอกสารอ้างอิง:

- `tools/CORE_SECURITY_IMPLEMENTATION_HANDOFF.md`
- `tools/STEP_E_SECURITY_AUTHORIZATION_REPORT.md`
- `tools/LAUNCHER_CORE_AUTHORIZATION_ADAPTER_HANDOFF.md`
- `tools/PROCESSMODE_TEST_REPORT.md`

> เอกสารนี้เป็น sanitized contract-freeze request ไม่มี production endpoint, access token, proxy credential, private key, customer identifier หรือ raw runtime configuration

---

## 1. Subject

**Request: S0 Security Contract Freeze for NekoProxyCore Protocol v2 and Online Launch Authorization**

---

## 2. Request summary

ทีม NekoProxyCore ขอเปิดกระบวนการ **S0 Security Contract Freeze** สำหรับ production online launch authorization ระหว่าง Launcher, Backend, Security และ Core

การ freeze นี้ไม่ใช่ความรับผิดชอบของ Launcher ฝ่ายเดียว เนื่องจาก contract ครอบคลุมหลาย trust boundaries:

- Launcher เป็น consumer/orchestrator และ forward permit แบบ opaque
- Backend เป็น authorization authority และผู้ sign permit
- Security อนุมัติ claims, time, key, replay, revocation และ credential policy
- Core สร้าง challenge, verify permit และบังคับ fail-closed ก่อน runtime side effects

ปัจจุบัน Core มี checkpoint แบบ fail-closed แล้ว:

- มี innermost `IProxyStartAuthorizer`
- default runtime path ปฏิเสธ start เมื่อไม่มี authorization
- authorization ถูกตรวจสอบก่อน publish `Starting` และก่อน engine side effects
- authorizer exception ถูก map เป็น typed `AuthorizationUnavailable` ด้วยข้อความ sanitized
- challenge generation ใช้ cryptographic randomness 256 bits และ base64url ไม่มี padding
- challenge lifecycle ใช้ monotonic expiry ไม่เกิน 30 วินาที, one outstanding challenge,
  atomic one-attempt consumption, replay rejection และ concurrent acceptance สูงสุดหนึ่งครั้ง

อย่างไรก็ตาม สถานะยังเป็น **PARTIAL/BLOCKED** และยังไม่ใช่ production-ready เนื่องจาก production contract สำหรับ protocol, challenge encoding/schema/error mapping, canonical configuration, JWT claims/time/key policy, Backend issuance, continuous authorization และ proxy-access material ยังไม่ได้ freeze แม้ Core challenge primitive/lifecycle ภายในจะมี verified checkpoint แล้ว

เพื่อให้ Core, Launcher และ Backend implement revision เดียวกันโดยไม่ต้องมี insecure compatibility fallback ขอให้ทั้งสี่ทีมร่วม review และอนุมัติรายการในเอกสารนี้

---

## 3. Required freeze decisions

### 3.1 Launcher ↔ Core protocol v2

ขอให้ freeze:

1. production protocol version เป็น version `2`
2. production host ต้อง reject protocol v1 `start`
3. exact JSON schemas สำหรับ:
   - `challenge` request/response
   - `start` request/response
   - `status` request/response
   - `stop` request/response
4. exact field names และ JSON types
5. required และ optional fields
6. property/command case-sensitivity
7. unknown-property policy
8. duplicate-property policy โดยต้อง reject duplicate security-sensitive fields
9. UTF-8 framing policy
10. delimiter หรือ length-prefix framing
11. partial read/write behavior
12. maximum sizes สำหรับ:
    - frame
    - compact JWT/permit
    - JWT segments
    - correlation ID
    - process name
    - profile/server references
    - response
13. connect/challenge/start/status/stop/read/write timeouts
14. correlation request/response matching
15. malformed/disconnected/timeout behavior

Security recommendation:

- reject unknown fields ใน security-sensitive requests
- reject duplicate fields
- permit เป็น mandatory, non-empty และ bounded สำหรับ `start`
- correlation ID เป็น opaque, bounded และ non-secret

---

### 3.2 Core challenge lifecycle

ขอให้ Security, Launcher และ Core freeze:

1. challenge มี entropy อย่างน้อย 256 bits
2. encoding เป็น base64url ไม่มี padding
3. exact decoded และ encoded size
4. challenge lifetime และ expiry boundary
5. maximum outstanding challenges
6. ออก challenge ใหม่แล้ว challenge เดิมถูก invalidate หรือไม่
7. จุดที่ request ถูกถือว่าเป็น authorization attempt
8. consume challenge ก่อนหรือหลัง structural JWT parse ระดับใด
9. failure, invalid signature, invalid claims, timeout, disconnect และ target หายต้อง consume หรือไม่
10. concurrent start policy
11. retry policy
12. Core restart semantics
13. expired/replayed error mapping

Core proposal:

- challenge lifetime ไม่เกิน 30 วินาที
- ใช้ monotonic clock สำหรับ challenge expiry
- มี one outstanding challenge ต่อ host/start state
- consume แบบ atomic เมื่อ request ผ่าน bounded structural admission แล้ว
- consume ไม่ว่าผล permit verification จะผ่านหรือไม่
- concurrent callers สำเร็จได้มากสุดหนึ่ง attempt
- failure หลัง challenge issuance ต้องขอ challenge และ permit ใหม่ ห้าม reuse

---

### 3.3 Canonical configuration binding

ขอให้ freeze exact canonical representation:

1. UTF-8 ไม่มี BOM
2. LF line endings
3. ต้องมี LF หลังบรรทัดสุดท้าย
4. fixed key order
5. exact process name และ casing
6. normalization/case policy
7. profile reference format
8. server reference format
9. SHA-256 digest encoding เช่น lowercase hex หรือ base64url
10. constant-time comparison requirement
11. positive และ negative shared fixtures

Current draft:

```text
protocolVersion=2
processName=pso2.exe
profileReference=profile-0
serverReference=server-0
```

Required fixture outputs:

- `canonical-config.txt`
- `canonical-config.sha256`
- process/profile/server mismatch vectors
- line-ending/casing/order mismatch vectors

ห้าม hash arbitrary client JSON และห้าม include credential ใน canonical configuration

---

### 3.4 Strict RS256 launch permit contract

ส่วนนี้ต้องให้ Backend และ Security เป็นผู้อนุมัติหลัก โดย Launcher ต้องยืนยันว่าจะ forward permit แบบ opaque เท่านั้น

#### JWT header

ขอให้ freeze:

- exact `typ`
- exact `alg=RS256`
- `kid` format และ maximum size
- duplicate header-property policy
- unknown header-property policy
- `crit` header policy
- compact JWT total/segment size limits
- exact public-key format

ต้อง reject:

- `alg=none`
- HS algorithms
- unsupported algorithms
- missing/unknown/retired `kid`
- malformed base64url/JSON/UTF-8
- duplicate security-relevant properties
- unsupported critical headers

#### JWT claims

ขอ exact name, JSON type, representation และ validation policy สำหรับ:

| Claim | Required freeze decision |
|---|---|
| `iss` | exact trusted issuer |
| `aud` | exact Core launch audience; string หรือ array policy |
| `sub` | UUID representation และ semantic owner |
| `sid` | Launcher session UUID policy |
| `iid` | installation UUID policy |
| `lid` | license UUID policy |
| `product` | exact approved product value |
| `scope` | exact scalar `proxy:start` หรือ alternative frozen representation |
| `cfg` | canonical SHA-256 digest encoding |
| `challenge` | exact Core challenge representation |
| `jti` | format, maximum size และ minimum entropy representation |
| `iat` | required NumericDate representation |
| `nbf` | required NumericDate representation |
| `exp` | required NumericDate representation |

Launcher requirements:

- ต้องไม่สร้างหรือ sign permit เอง
- ต้องไม่แก้ claims/header
- ต้องไม่ใช้ decoded claims เป็น authorization authority
- ต้องไม่ persist permit
- ต้องไม่ส่ง permitผ่าน argv, environment, log, telemetry หรือ crash detail

---

### 3.5 Permit time policy

ขอให้ Backend และ Security freeze:

1. recommended permit TTL
2. maximum permit lifetime
3. allowed clock skew
4. future-issued tolerance
5. exact `iat`, `nbf`, `exp` boundary semantics
6. NumericDate เป็น integer seconds เท่านั้นหรืออนุญาต fractional values
7. behavior เมื่อ Core wall clock ผิด
8. behavior เมื่อ Backend clock และ Core clockต่างกันเกิน policy
9. renewal/grace policy หากใช้ permit ต่อเนื่อง

Current proposal:

- permit TTL ประมาณ 30 วินาที
- hard reject เมื่อ `exp - iat > 60` วินาที
- allowed skew ไม่เกินประมาณ 5 วินาที
- JWT time claims ใช้ injectable UTC wall clock
- challenge expiry ใช้ monotonic clockแยกจาก JWT wall clock

---

### 3.6 Public-key custody and rotation

ขอให้ Backend และ Security ส่งหรือยืนยันเฉพาะ:

1. approved dedicated test public/private key pair สำหรับ fixtures เท่านั้น
2. production public verification keys หรือ approved immutable public-key manifest
3. exact `kid → public key` mapping
4. public-key format เช่น PEM, DER หรือ JWK
5. normal rotation sequence
6. overlap duration
7. old-key retirement policy
8. emergency revocation policy
9. unknown/retired `kid` behavior
10. signed remote key-manifest policy หากมี

ข้อบังคับ:

- production private signing key ต้องอยู่ใน Backend/Security custody เท่านั้น
- production private keyห้ามถูกส่งให้ Core หรือ Launcher
- production private keyห้ามอยู่ใน repository, fixture, build หรือ release artifact
- key resolverห้าม fetch arbitrary URLจาก token header
- unknown `kid` ต้อง reject และห้าม fallback ไป key แรกหรือทุก key

---

### 3.7 Backend permit issuance

ขอให้ Backend freeze:

1. permit-issuance request schema
2. permit-issuance response schema
3. authenticated identity source
4. server-side validations สำหรับ:
   - authentication
   - entitlement/license
   - active installation
   - active session
   - heartbeat
   - product
   - challenge binding
   - canonical configuration binding
5. Backend error taxonomy
6. request timeout
7. retry policy
8. rate-limit policy
9. signer-unavailable behavior
10. one-permit-per-start-attempt semantics
11. replay/reissue policy
12. audit/metrics policyแบบ sanitized

Required security behavior:

- Backend signer unavailable ต้อง fail closed
- permit ต้องออกใหม่สำหรับทุก start attempt
- Launcher ห้ามสร้าง, sign หรือ substitute permit
- identity relationships ต้อง resolve server-side ไม่ใช่เชื่อ raw IDs จาก client

---

### 3.8 Launcher production state machine

ขอให้ Launcher ยืนยัน exact production order:

```text
ตรวจพบ pso2.exe
→ local fail-fast validation
→ เปิด Core host โดยไม่ส่ง secret ผ่าน argv/environment
→ รอ typed Core readiness
→ ขอ Core challenge
→ ส่ง challenge และ configuration context ให้ Backend
→ รับ Backend-signed permit
→ ส่ง start พร้อม permitหนึ่งครั้ง
→ รอ typed Running
→ monitor target/Core/session
→ cleanup เมื่อ stop/exit/failure
```

ต้อง freeze behavior สำหรับ:

- target ยังไม่พบ
- target หายก่อน request permit
- target หายหลังได้ permitแต่ก่อน `start`
- target หายระหว่าง Core startup
- pipe disconnect
- challenge timeout
- Backend timeout
- start timeout
- duplicate click หรือ concurrent start
- Launcher crash
- Core crash/restart
- retry หลัง failure
- stop/cleanup timeout

ข้อบังคับ:

- `pso2.exe` detection เป็น activation precondition เท่านั้น ไม่ใช่ authorization proof
- Launcher ต้องไม่ start Core ProcessMode ก่อนตรวจพบ `pso2.exe`
- Core ต้องตรวจ `pso2.exe` ซ้ำหลัง authorization และก่อน engine start
- ทุก failure หลัง challenge issuance ต้องขอ challenge และ permit ใหม่
- ห้าม reuse challenge/permit หลัง timeout, disconnect หรือ failed start

---

### 3.9 Typed errors and sanitized responses

ขอให้ทุกทีม freeze typed errors ขั้นต่ำ:

- `AuthorizationRequired`
- `AuthorizationInvalid`
- `AuthorizationExpired`
- `AuthorizationReplay`
- `AuthorizationUnavailable`
- `SessionInactive`
- `ProcessNotFound`
- `ProcessExited`
- lifecycle errors เดิม

External response/log/telemetry ห้ามมี:

- raw permit/JWT
- token fragments
- decoded JWT header/claims
- user/session/license/installation IDs
- exception message/stack
- expected issuer/audience/challenge/config digest
- private keyหรือ reusable key material
- proxy endpoint/credential
- raw runtime configuration

Response ต้อง serialize จาก allow-list เท่านั้น เช่น:

- protocol version
- kind
- correlation ID
- typed status
- succeeded
- typed error code
- challenge fieldsเฉพาะ challenge response

---

### 3.10 Continuous authorization and proxy access

รายการนี้อาจไม่บล็อก challenge primitive ทุกส่วน แต่ยังบล็อก production security readiness

ขอให้ Backend, Security, Launcher และ Core freeze:

1. heartbeat/renewal interval
2. renewal challenge-response contract
3. grace period
4. entitlement/session revocation SLA
5. Core fail-closed stop deadlineเมื่อ renewal หมดอายุ
6. behavior เมื่อ Backend unavailable ชั่วคราว
7. Launcher crash/restart behaviorระหว่าง runtime
8. short-lived proxy access material contract
9. downstream credential expiry/revocation
10. protected in-memory delivery pathเข้า Core
11. package extraction/direct proxy bypass test
12. prohibition of static reusable proxy credentialsใน shipped bundle

ห้ามส่ง proxy credential ผ่าน argv, environment, disk, log, status หรือ crash detail

---

## 4. Requested shared contract package

ขอให้ผลการ freeze ถูกส่งเป็น versioned และ sanitized package ที่ทุก repository ใช้ revision เดียวกัน:

```text
security-contract/
  protocol.schema.json
  authority-request.schema.json
  authority-response.schema.json
  canonical-config.txt
  canonical-config.sha256
  signature-positive-vectors.json
  signature-negative-vectors.json
  typed-errors.json
  artifact-manifest.schema.json
  README.md
```

Package ต้องระบุ:

- contract revision
- contract/package SHA-256
- effective date
- owner ของแต่ละ boundary
- consumer approver
- Security reviewer
- repository-specific merge gates
- cross-repository exit gates
- change-control policy

Package ต้องไม่มี:

- production private key
- production access tokenหรือ JWT
- proxy credential
- production endpoint
- customer/account/session/license/installation identifiers
- raw runtime configuration
- unsanitized logs

ใช้ได้เฉพาะ dedicated non-production test keys และ synthetic identifiers ที่ Security อนุมัติ

---

## 5. Ownership request

ขอให้ระบุชื่อ owner และ approver สำหรับแต่ละ workstream:

| Workstream | Implementing owner | Required approver |
|---|---|---|
| Protocol v2 schema และ Launcher state machine | Launcher | Core + Security |
| Challenge, verifier, runtime seam และ Core host | Core | Launcher + Security |
| Permit issuance และ signing service | Backend | Security + Core |
| Claims/time/key/revocation policy | Security | Backend + Core + Launcher |
| Shared fixtures/test vectors | Joint owner | All four teams |
| Cross-repository E2E and negative matrix | QA/Security + teams | Security release authority |
| Short-lived proxy access material | Backend/Proxy Server | Security + Core |

---

## 6. S0 freeze acceptance criteria

S0 จะถือว่า complete เมื่อ:

1. Launcher, Backend, Core และ Security อ้างอิง contract revision/hash เดียวกัน
2. protocol schemas ได้รับ approval ครบ
3. canonical configuration text/hash fixtures ได้รับ approval
4. positive/negative RS256 test vectors ได้รับ approval
5. challenge lifetime/consumption/retry/concurrency semantics ไม่มี security-impacting TBD
6. JWT header/claims/time/key policy ไม่มี security-impacting TBD
7. Backend issuance schema และ signer failure policy freeze แล้ว
8. Launcher state machine และ cleanup/retry policy freeze แล้ว
9. typed errors และ leakage policy freeze แล้ว
10. ทุก workstream มี owner, approver และ merge gate
11. contract change-control กำหนดให้ update fixtures ก่อน implementation compatibility changes
12. package ผ่าน sanitized-content review

---

## 7. Requested response format

ขอให้แต่ละทีมตอบในรูปแบบต่อไปนี้:

```text
Team:
Owner:
Approver:
Reviewed contract revision:
Decision: APPROVED / APPROVED WITH CHANGES / BLOCKED
Requested changes:
Security-impacting TBDs:
Expected fixture/artifact delivery:
Repository merge gate:
Cross-repository exit gate:
```

หาก status เป็น `BLOCKED` ขอให้ระบุ:

- exact decision owner
- missing input/approval
- incompatible requirement
- earliest dependencyที่ต้องแก้ก่อน

ห้ามแก้ blocker ด้วย offline, allow-all, local-signing หรือ compatibility fallback ที่ลด security

---

## 8. Core behavior while S0 is pending

ระหว่าง S0 ยังไม่ complete ทีม Core จะ:

- รักษา default runtime path ให้ fail closed
- ไม่เปิด production named-pipe host
- ไม่ implement production permit contractจากค่าตัวอย่างโดยพลการ
- ไม่ hard-code production issuer/audience/key IDs/public keysจาก draft
- ไม่เพิ่ม `AllowAllAuthorizer`
- ไม่เพิ่ม offline/debug authorization fallback
- ไม่ให้ Launcher PID/path/signature, same-user pipe, mutex หรือ process detection เป็น authorization proof
- ไม่รับ production secret ผ่าน argv/environment/file
- ทำเฉพาะงานที่ไม่ผูกกับ unfrozen contract และมี TDD evidence

---

## 9. Short message for Teams/Discord

> ขอเปิด S0 Security Contract Freeze สำหรับ NekoProxyCore online launch authorization ครับ ต้อง review ร่วมระหว่าง Launcher + Backend + Security + Core ไม่ใช่ Launcher ฝ่ายเดียว
>
> รายการที่ต้อง freeze: protocol v2 schemas, challenge lifetime/atomic consumption/retry, canonical config + SHA-256 fixture, strict RS256 header/claims/time policy, test key/signature vectors, Backend permit issuance, key rotation, Launcher state machine, continuous authorization, proxy-access material และ typed sanitized errors
>
> ขอ output เป็น versioned `security-contract` package พร้อม revision/hash และ approver ของทุกทีม ห้ามมี production private key/token/proxy credential/endpoint/customer identifiers
>
> ระหว่างยังไม่ freeze Core จะคง fail-closed และไม่เพิ่ม offline/allow-all/local-signing fallback ตาม `tools/CORE_SECURITY_IMPLEMENTATION_HANDOFF.md`

---

## 10. Requested action

กรุณา:

1. แต่งตั้ง owner และ approver จาก Launcher, Backend, Security และ Core
2. นัด S0 contract review
3. ตอบ decision ตามรูปแบบในหัวข้อ 7
4. ส่ง revisioned `security-contract` package
5. ระบุ contract revision/hash ที่ทุก repository ต้องใช้
6. ปิด security-impacting TBDs ก่อนเริ่ม production C2–C6 implementation

เมื่อ S0 ผ่าน ทีม Core จะดำเนินงาน security implementation ด้วย TDD ตามลำดับ challenge lifecycle, canonical configuration, strict RS256 verifier, innermost runtime integration, protocol v2 และ production host โดยใช้ shared fixtures revision เดียวกับ Launcher และ Backend
