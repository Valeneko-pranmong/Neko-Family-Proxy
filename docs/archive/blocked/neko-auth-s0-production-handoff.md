# NEKO-AUTH-S0 — Central Production Adapter Handoff

**เอกสารกลางสำหรับ:** Launcher Team, NekoProxyCore Team, Backend/Security, Proxy Server/Security S1 และ QA/Release
**Contract ID:** `NEKO-AUTH-S0`
**Contract revision:** `s0-rc1`
**Contract package SHA-256:** `6697351b6b280afc566fedaaa1a6cfe207b1ea1d803c2eb613b4c1a891e192df`
**Canonical configuration SHA-256 (synthetic fixture):** `92ac70d0f9b100ba664f2bb205b2c042bc1058f779e94e759822d906ea880871`
**สถานะ:** `FAIL-CLOSED RELEASE GATE IMPLEMENTED/LOCALLY VERIFIED — LAUNCHER/CORE ACCEPTANCE PENDING — PRODUCTION RELEASE BLOCKED`
**Source package:** `Backend Security/security-contract/NEKO-AUTH-S0/s0-rc1/`

> เอกสารนี้เป็น implementation handoff กลางที่ pin กับ package ข้างต้น ไม่ใช่ production release approval ไม่มี production endpoint, private/signing key, bearer token, permit, credential, customer/session/installation identifier หรือ raw proxy configuration ทีมใดพบว่าข้อความในเอกสารเดิมขัดกับ package `s0-rc1` ให้ยึด package เป็น source of truth และหยุด production wiring จนกว่าจะ reconcile สำเร็จ

---

## 1. คำตัดสินและ stop rules

### 1.1 สิ่งที่อนุมัติแล้วในระดับ technical baseline

- Protocol v2, framing, strict JSON และ typed wire errors
- canonical start configuration และ SHA-256 binding
- Core challenge lifecycle และ admission semantics
- JWT/RS256 header, claims, time, replay และ key lifecycle
- Backend authority request/response schemas
- continuous authorization/renewal policy
- immutable artifact-manifest schema
- synthetic positive/negative fixtures
- fail-closed secrecy, timeout และ cleanup rules

> ขอบเขต renewal ที่อนุมัติใน `s0-rc1` ครอบ policy และ `renewal.schema.json` ฝั่ง Launcher ↔ Backend เท่านั้น ยังไม่ครอบ Launcher ↔ Core renewal wire, signed-renewal token/runtime semantics; artifact schemaยังไม่ปิด path-safety semantics และ Named Pipeยังไม่ pin process-binding algorithm ทั้งสามส่วนต้องรอ revision/hashใหม่ตาม §11 ก่อน production

### 1.2 สิ่งที่ยังไม่อนุมัติ

- Launcher Owner acceptance
- NekoProxyCore Owner acceptance
- production endpoint และ deployment-specific public configuration
- production signing/public-key release artifacts
- final signed Core release bundle
- S1 downstream proxy-access mechanism
- real authorized cross-repository E2E
- QA/Security/Release approval

### 1.3 Stop rules

1. ห้ามเปิด production wiring ถ้า package revision/hash ไม่ตรง
2. ห้ามใช้ proposal เก่า, placeholder หรือค่าที่เดาเองแทน `s0-rc1`
3. ห้ามสร้าง local signer, offline permit, allow-all หรือ protocol-v1 fallback
4. ห้ามส่ง server-owned identity fields ใน authority request body
5. ห้ามเริ่ม runtime ก่อน Core verify permit และ recheck exact target
6. ห้าม release ถ้า continuous authorization หรือ S1 proxy-access ยังไม่ผ่าน
7. เมื่อ contract เปลี่ยน ต้องออก revision/package hash ใหม่และให้ทุก owner accept ใหม่

---

## 2. Package verification และ acceptance record

ก่อนเริ่ม implementation ให้แต่ละทีมรันจาก package directory:

```bash
python validate_package.py
```

ผลที่ต้องได้จาก package ปัจจุบัน:

```text
PASS contractRevision=s0-rc1
PASS files=15
PASS canonicalSha256=92ac70d0f9b100ba664f2bb205b2c042bc1058f779e94e759822d906ea880871
PASS packageSha256=6697351b6b280afc566fedaaa1a6cfe207b1ea1d803c2eb613b4c1a891e192df
PASS syntheticRs256Vector=valid-launch-01
PASS privateKeyMarkers=0
```

แต่ละทีมต้องบันทึกใน repository ของตน:

```text
Contract ID: NEKO-AUTH-S0
Accepted revision: s0-rc1
Accepted package SHA-256: 6697351b6b280afc566fedaaa1a6cfe207b1ea1d803c2eb613b4c1a891e192df
Consumer revision: <commit SHA>
Package validation: PASS
Owner decision: ACCEPT / REJECT พร้อมเหตุผล
```

คำว่า `FROZEN` ใช้ได้เมื่อ Launcher, Core, Backend/Security และ Release governance รับ revision/hash เดียวกันแล้วเท่านั้น

---

## 3. Trust boundaries และ production composition

```text
Launcher UI / authenticated application context
  │
  ├─ local fail-fast context + fresh online heartbeat
  ├─ exact pso2.exe detector (PID + creation identity/owned handle)
  ├─ verified Core artifact/process owner
  ├─ strict Protocol v2 Named Pipe client
  └─ authenticated Backend authority client
          │
          ├─ start authority: signed short-lived launch permit
          └─ renewal authority: signed short-lived renewal material

NekoProxyCore headless host
  ├─ current-user-only Named Pipe server + anti-squatting identity controls
  ├─ one-outstanding cryptographic challenge store
  ├─ strict RS256 verifier + immutable public-key allow-list
  ├─ canonical config/target/replay enforcement
  ├─ innermost authorized-start boundary
  ├─ runtime renewal/expiry/revocation enforcement
  └─ bounded runtime cleanup

Proxy Server/Security S1
  └─ short-lived/non-reusable runtime-bound downstream access
```

Authority boundaries:

- Backend/Security เป็น authorization authority และถือ production private keyเท่านั้น
- Launcher เป็น orchestrator; ไม่ decode, sign, refresh, persist หรือใช้ claims ตัดสินสิทธิ์
- Core เป็น enforcement boundary; Named Pipe ACL หรือ Launcher state ไม่แทน permit verification
- Proxy Server/Security S1 เป็น enforcement boundary ของ downstream proxy access

---

## 4. Frozen protocol values

| รายการ | ค่า `s0-rc1` |
|---|---|
| Protocol | JSON integer `2` |
| Framing | unsigned 4-byte big-endian length + payload |
| Payload | strict UTF-8, no BOM, `1..8192` bytes |
| JSON | exact case; reject unknown/duplicate fields and wrong types |
| Correlation ID | lowercase hex 32 characters |
| Permit transport | compact ASCII, `1..4096` characters |
| Challenge | CSPRNG 32 bytes; unpadded base64url 43 chars |
| Challenge lifetime | 30 seconds, monotonic time |
| Target | exact `pso2.exe`; PID `1..4294967295` |
| Mode | `ProcessMode` |
| Profile reference | `^profile-[0-9]{1,6}$` |
| Server reference | `^server-[0-9]{1,6}$` |
| Success readiness | matching typed `Running` response only |

Commands and required fields:

### `challenge` request

```json
{
  "version": 2,
  "command": "challenge",
  "correlationId": "<32-lowercase-hex>"
}
```

### `start` request

```json
{
  "version": 2,
  "command": "start",
  "correlationId": "<32-lowercase-hex>",
  "processName": "pso2.exe",
  "targetPid": 4242,
  "mode": "ProcessMode",
  "profileReference": "profile-0",
  "serverReference": "server-0",
  "permit": "<opaque-compact-permit>"
}
```

### `status` / `stop`

มีเฉพาะ `version`, `command`, `correlationId` ตาม `protocol.schema.json`

Launcher และ Core ต้อง generate/parse จาก exact schema; ห้ามเพิ่ม optional production field โดยไม่ออก contract revision ใหม่

---

## 5. Canonical configuration และ target binding

Canonical bytes ต้องเรียงและ encode แบบ exact UTF-8/no BOM/LF/final LF:

```text
protocolVersion=2
mode=ProcessMode
processName=pso2.exe
targetPid=<validated PID>
profileReference=<validated profile-N>
serverReference=<validated server-N>
```

ข้อบังคับ:

1. Launcher detect exact target ก่อน spawn Core และเก็บ PID พร้อม creation identity/handle เพื่อป้องกัน PID reuse
2. Launcher recheck target เดิมหลัง heartbeat, หลัง channel ready, หลัง challenge, หลัง permit และก่อนส่ง start
3. Launcher สร้าง canonical bytes โดยแทนค่าที่ validate แล้วโดยไม่ normalize เพิ่ม จากนั้นคำนวณ SHA-256 lowercase hex
4. Authority request ส่ง `configurationDigest`, `processName`, `targetPid`, `mode`, `product`, `scope`
5. Backend bind permit กับ digest, challenge, target PID, mode และ server-resolved identity
6. Core สร้าง canonical bytesจาก start request ตาม algorithm เดียวกันและเทียบ digest/claims แบบ constant-timeเมื่อเหมาะสม
7. Core recheck PID/name เดิมหลัง permit verification และก่อน publish `Starting` หรือ runtime side effect
8. target หายหรือถูกแทนต้องคืน `ProcessExited` และ engine start count เป็นศูนย์

---

## 6. Backend authority request — ห้ามส่ง client-owned identity

Authenticated transport เช่น bearer session เป็นแหล่ง caller identity; request body ต้องตรง `authority-request.schema.json` เท่านั้น:

```json
{
  "version": 1,
  "contractRevision": "s0-rc1",
  "correlationId": "<32-lowercase-hex>",
  "challenge": "<43-char-base64url>",
  "configurationDigest": "<64-lowercase-hex>",
  "processName": "pso2.exe",
  "targetPid": 4242,
  "mode": "ProcessMode",
  "product": "neko-family-proxy",
  "scope": "proxy:start"
}
```

**ห้ามใส่ใน body:** `sub`, user ID, `sid`/session ID, `iid`/installation ID, `lid`/license ID หรือ installation hash ที่ใช้เป็น authority claim

Backend ต้อง resolve และตรวจจาก authenticated server state:

- authenticated user และ disabled/revoked state
- active entitlement/license
- claimed active session และ ownership
- installation binding
- fresh heartbeat
- product/scope
- challenge/configuration/target binding
- replay/rate policy
- signer/key availability

Signer/database/authority ambiguity ต้อง fail closed และห้าม automatic retry หลัง ambiguous issuance result; attempt ใหม่ต้องเริ่มด้วย challenge ใหม่

Authority response ต้องตรง `authority-response.schema.json` และ success ต้องมี `expiresInSeconds=30`

---

## 7. Permit verifier และ key policy

Core verifier ต้องบังคับทั้งหมด:

- compact JWT สาม segmentsเท่านั้น
- `alg=RS256`
- `typ=neko-launch+jwt`
- exact known `kid`; ไม่มี first-key fallback
- ไม่มี `crit`; reject unknown/duplicate header หรือ claim
- exact `iss=neko-backend`
- scalar `aud=neko-proxy-core`
- `product=neko-family-proxy`
- scalar `scope=proxy:start`
- string claims: `iss aud sub sid iid lid product scope cfg challenge mode jti`
- integer claims: `target_pid iat nbf exp`
- string claim ทุกตัวต้อง non-empty; ห้ามยอมรับ null, whitespace-only หรือ implicit type coercion
- identifier string claims `iss`, `aud`, `sub`, `sid`, `iid`, `lid`, `product`, `scope`, `cfg`, `challenge` และ `mode` ต้องใช้ ASCII และยาวไม่เกิน 128 characters; `jti` ต้องใช้ ASCII และยาวไม่เกิน 64 characters
- `nbf=iat`, `exp=iat+30`, maximum lifetime 30 seconds
- `iat`, `nbf`, `exp` ต้องเป็น JSON integer NumericDate เท่านั้น; reject float, string, boolean และ overflow
- future `iat/nbf` tolerance 2 seconds: reject เมื่อ `iat > now + 2` หรือ `nbf > now + 2`
- expiration boundary ตาม `s0-rc1`: reject เมื่อ `now >= exp + 2`; ดังนั้น `now=exp-1`, `now=exp`, `now=exp+1` ยังอยู่ใน skew allowance และ `now=exp+2` ต้อง reject
- untrusted/unavailable/non-monotonic wall-clock authority ต้อง fail closed
- challenge, configuration digest, mode และ target PID match
- atomic one-use challenge/JTI/replay enforcement
- verification และ target recheck ต้องเสร็จก่อน `Starting` และ side effects

Production public keys ต้องเป็น immutable release-bundled allow-list ที่ผ่าน signed release/change control ไม่มี token-controlled URL/JWKS และไม่มี first-key fallback การ rotation ใช้ old+new key ใน signed releaseได้ไม่เกิน 24 ชั่วโมง; revoked/retired key ต้อง reject ตาม effective manifest ทันที

---

## 8. Challenge admission semantics

Core มี one outstanding challenge ต่อ host; challenge ใหม่ invalidate ค่าเก่า

Consume challenge เฉพาะเมื่อ request ผ่าน admission ครบ:

1. ได้ complete bounded frame
2. strict UTF-8/JSON/schema ผ่าน
3. permit เป็น structurally bounded compact three-segment value

- disconnect หรือ malformed inputก่อน admission: ไม่ consume
- admitted verification failure, timeout, disconnect หรือ ambiguous result: consume
- success: consume
- consumed/expired/replaced challenge ห้าม restore
- retry หลัง admitted outcome ต้องเริ่ม challenge + authority permit ใหม่
- concurrent double-use สำเร็จได้สูงสุดหนึ่ง request

---

## 9. Launcher production adapters

### 9.1 `AuthorizedProxyGateway`

- เป็น production facade เดียวแทน `AuthorizationPendingProxyGateway`
- snapshot local fail-fast facts แต่ไม่ serialize server-owned identity ใน authority body
- สร้าง target-bound command หลัง detect target
- map typed errorsด้วย trusted allow-list
- single-flight และถือ attempt/runtime cancellation state

### 9.2 `ExactPso2ProcessTargetDetector`

```text
wait_for_exact_pso2(deadline, cancellation) -> TargetIdentity(pid, creation_identity/handle)
is_same_target_still_running(target) -> bool
```

ต้องป้องกัน PID reuse, ใช้ monotonic deadline, fail closed เมื่อ access denied/error และ recheck ทุก boundary ตาม §5

### 9.3 `BackendFreshHeartbeatPrecondition`

- probe online ใหม่ทุก admitted start attempt
- server ตรวจ authenticated session/installation relationship
- false/error/timeout/cancellation → ไม่มี Core spawn/challenge/permit/start
- heartbeat เป็น precondition ไม่ใช่ permit และไม่ใช่ continuous authorization

### 9.4 `VerifiedCoreProcessAdapter`

- parse manifest แบบ exact `artifact-manifest.schema.json`
- pin `contractId=NEKO-AUTH-S0`, revision และ package SHA
- verify immutable signed release trust anchor ก่อนเชื่อ manifest
- verify `rid=win-x64`, `executable=NekoProxyCore.exe`, path/size/SHA-256 ของ complete file set
- manifest path ทุกค่าต้องเป็น normalized relative path ใช้ `/` เป็น separatorเท่านั้น; ห้าม absolute/rooted/drive/UNC, leading separator, backslash, `.`/`..`/empty segment และ trailing separator
- reject duplicate pathและ Windows case-insensitive collision ก่อนเปิดไฟล์
- reject symlink/junction/reparse pointทุก componentและ final file; เปิด/ตรวจผ่าน race-safe handles แล้วพิสูจน์ final resolved pathอยู่ใต้ immutable bundle root
- reject missing/extra/hash/size/path/signature mismatch
- fixed argv, no shell, explicit environment allow-list
- ไม่มี token/permit/credential/raw config ใน argv/env/disk/log
- ใช้ owned handle/job object; kill ได้เฉพาะ process ที่ตัวเองสร้าง
- process/PID/pipe existence ไม่ใช่ readiness

### 9.5 `NamedPipeCoreControlChannel`

- exact Protocol v2 framing/schema/deadline
- current-user-only ACL เป็น defense in depth
- Launcher ต้องถือ non-inheritable owned process handle (`SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION`) ที่ได้จากการ spawnและ creation identityตลอด attempt
- หลัง connect pipeและก่อน serialize/write permit ให้เรียก Windows `GetNamedPipeServerProcessId` บน connected pipe handle แล้วเทียบกับ `GetProcessId(ownedProcessHandle)`
- ก่อนและหลัง identity comparison ต้องยืนยัน owned process handleยังไม่ signaledและ creation identityยังตรง; mismatch, API unavailable/failure, process exitหรือ replacementต้องปิด pipeและ fail closedก่อน permit write
- ห้ามเปิด permit valueหรือสร้าง start payloadที่มี permitก่อน identity sequenceผ่าน เพื่อป้องกัน same-user pipe squatting/PID reuse/TOCTOU
- permit reveal เฉพาะ direct write buffer
- correlation response ต้องตรง request
- ห้าม retransmit `start` หลัง ambiguous outcome
- success เฉพาะ typed `Running`

### 9.6 `BackendLaunchPermitGateway`

Production boundary ต้องรับ target-bound canonical command และ authenticated transport context แต่ serialize body ตาม §6 เท่านั้น ไม่ส่ง session/install/license identity fields

```text
issue_launch_permit(
  authenticated_transport,
  correlation_id,
  challenge,
  configuration_digest,
  process_name,
  target_pid,
  mode,
  product,
  scope,
  deadline
) -> OpaquePermit
```

`OpaquePermit` ต้อง redacted ใน `repr/str/exception`; ห้าม decode, re-sign, refresh, persist หรือ log

### 9.7 `RuntimeAuthorizationClient`

- ขอ fresh Core renewal challengeทุก 15 วินาที
- ขอ signed renewal materialตาม `renewal.schema.json`
- ส่ง renewal materialให้ Core ก่อน signed authorization เดิมหมดอายุ
- Backend outage/invalid response ไม่มี offline success
- Launcher exit หรือ renewal failure ต้อง trigger bounded Core stop แต่ Core ต้อง enforce expiryเองแม้ Launcher ถูกแก้ไข

### 9.8 `AuthorizedCoreOrchestrator` exact flow

```text
single-flight
→ validate local command/access context
→ wait exact pso2.exe and retain PID + creation identity
→ fresh online heartbeat
→ recheck target
→ verify signed Core bundle and spawn owned Core without secrets
→ wait/bind strict control channel to owned Core
→ recheck target
→ request one Core challenge
→ recheck target
→ build canonical config + digest
→ request one Backend permit using §6 schema
→ check cancellation + recheck target
→ send one exact Protocol v2 start frame
→ accept matching typed Running only
→ begin mandatory renewal loop
→ monitor target/Core/session
→ bounded stop/cleanup
```

---

## 10. Core production adapters

### 10.1 `ProtocolV2NamedPipeHost`

- headless `win-x64` host
- current-user-only pipe ACL, approved pipe/mutex identity และ anti-squatting design
- serverต้องเป็น processเดียวกับ production hostที่ Launcher spawn; ห้าม proxy/relay pipeจาก helper process เว้นแต่ contract revisionใหม่กำหนด identity chainแบบ exact
- one monotonic total deadlineต่อ operation
- reject protocol v1, unauthorized legacy start และ malformed requestsก่อน dispatch
- code-only responsesตาม schema ไม่มี arbitrary detail

### 10.2 `CoreChallengeStore`

- CSPRNG 32 bytes, 43-char unpadded base64url
- one outstanding, replacement invalidation, monotonic 30 seconds
- atomic admission/consume semanticsตาม §8

### 10.3 `StrictLaunchPermitVerifier`

- exact verificationตาม §7
- immutable key allow-listและ rotation/revocation policy
- constant-time sensitive comparisons
- engine/network/driver start count 0 ทุก verification failure

### 10.4 `AuthorizedStartBoundary`

- innermost boundaryที่ทุก UI/CLI/protocol/legacy/test production entry pointต้องผ่าน
- default no verifier/permit = `AuthorizationRequired`
- verify permit → verify config/target → recheck exact PID/name → publish `Starting` → start runtime
- no allow-all/offline/local signer/debug bypassใน production build
- valid concurrent/replayed startsสร้าง runtimeได้ exactly once

### 10.5 `RuntimeAuthorizationEnforcer`

- ออก fresh renewal challengeตาม contract
- verify signed renewal materialและ bind `runtimeId` + `configurationDigest`
- authorization ห้ามเกิน signed expiry
- renewal cadence 15 วินาที, material lifetime 30 วินาที
- Backend outage, invalid/expired renewal, revoked/inactive session → begin stopทันที
- stop deadline 5 วินาที; Core retain ownershipและรายงาน `StopFailed` ถ้า cleanupไม่สมบูรณ์
- modified/crashed Launcher ต้องไม่ทำให้ Core run เกิน signed authorization

### 10.6 `ProductionArtifactManifest` producer

สร้าง JSON ตรง schemaเท่านั้น:

- `schemaVersion=1`
- `contractId=NEKO-AUTH-S0`
- `contractRevision=s0-rc1`
- exact `contractPackageSha256`
- bounded `coreVersion`
- `rid=win-x64`
- `executable=NekoProxyCore.exe`
- `files[]` แต่ละรายการมี `path`, `sha256`, `size`
- ไม่มี additional properties

Release pipeline ต้อง sign/attest manifestและ bundleผ่าน trust mechanismที่ Security/Release อนุมัติ; local unsigned manifestกับ local hashesไม่ใช่ trust anchor

---

## 11. Continuous authorization exact flow และ contract gap ที่ต้องปิด

```text
Running established at T0
→ Core creates fresh renewal challenge
→ Launcher requests Backend renewal using authenticated transport
→ Backend resolves server identity/state and validates runtime binding
→ Backend returns signed renewal material, expiresInSeconds=30
→ Launcher forwards opaque renewal material to Core
→ Core verifies and atomically advances signed expiry
→ repeat every 15 seconds
```

`renewal.schema.json` ปัจจุบันกำหนดเฉพาะ Launcher ↔ Backend authority request/response:

- request: version, contractRevision, correlationId, command=`renew`, challenge, runtimeId, configurationDigest
- success: version, contractRevision, correlationId, kind=`renewal`, succeeded=true, permit, expiresInSeconds=30
- failure: code-only allow-list

### 11.1 Blocking gap ใน package `s0-rc1`

`protocol.schema.json` ของ `s0-rc1` มีเพียง `challenge`, `start`, `status`, `stop` และ **ยังไม่มี Core-control command/schema สำหรับ:**

1. ขอ fresh renewal challengeที่ bind กับ active `runtimeId`
2. ส่ง opaque signed renewal materialจาก Launcherเข้า Core
3. ส่ง typed renewal acceptance/rejectionและ current signed-expiry state

ดังนั้นห้าม Launcher/Core เดา field หรือ reuse `start`/`challenge` schemaเพื่อ renewal การ implement production continuous authorizationต้องรอ Backend/Security contract owner publish revisionถัดไปพร้อม:

- exact Launcher ↔ Core renewal challenge request/response schema
- exact renewal submission request/response schema
- exact signed-renewal material format, protected header, claims/types, audience/scope, runtime/config/session binding และ time rules
- runtime ID generation/representation/ownership
- correlation, admission, one-use, replayและ ambiguous-outcome semantics
- maximum frame/material sizesและ code-only errors
- cross-language signed-renewal positive/negative fixturesและ expected Core results
- updated package inventory, checksumsและ package SHA-256
- acceptanceใหม่จาก Launcher/Core/Backend/Security

ระหว่าง gapนี้ Core implementationทำได้เฉพาะ fail-closed seamที่ไม่มีทางเปิด production runtimeเกิน signed expiry Production wiring/releaseยัง `BLOCKED` และ checklist §19 ข้อ renewalห้ามติ๊กผ่านด้วย residual-risk acceptance

ห้ามใช้ local heartbeat timestamp, cached permit, network grace หรือ Launcher boolean เพื่อขยาย authorization หลัง signed expiry

### 11.2 Normative security addenda ที่ต้องบรรจุใน revision ถัดไป

ข้อกำหนด manifest path safety ใน §9.4 และ exact Named Pipe server identity ใน §9.5/§10.1 เป็น **central candidate decisions เพื่อปิด security gaps** แต่ยังไม่ได้อยู่ใน signed/hash-pinned `s0-rc1` package จึงยังไม่อนุญาตให้แต่ละทีม implementเป็น production contractโดยลำพัง

Backend/Security contract ownerต้องนำข้อกำหนดเหล่านี้พร้อม renewal gap §11.1 ไปออก package revision/hashใหม่ในครั้งเดียว โดยแก้/เพิ่ม:

- artifact manifest schemaให้ path grammarสอดคล้อง normalized relative `/` paths และเพิ่ม normative duplicate/case-collision/reparse/resolved-root semantics
- exact Windows pipe server process-binding algorithm, required access rights, race/failure orderingและ fixtures/tests
- renewal wire/token/runtime identityครบตาม §11.1
- checksums/package hash/approvalsของ revisionใหม่

Launcher/Coreทำ unit seamsหรือ spikesจาก candidate decisionsได้ แต่ production compositionต้อง fail closedและ acceptanceต้องอ้าง revision/hashใหม่เท่านั้น

---

## 12. Wire error taxonomy

Core/Backend wire responseใช้เฉพาะ:

- `AuthorizationRequired`
- `AuthorizationInvalid`
- `AuthorizationExpired`
- `AuthorizationReplay`
- `AuthorizationUnavailable`
- `SessionInactive`
- `EntitlementInactive`
- `HeartbeatStale`
- `ProcessNotFound`
- `ProcessExited`
- `ConfigurationMismatch`
- `ProtocolInvalid`
- `AlreadyRunning`
- `StartTimeout`
- `Cancelled`
- `StartFailed`
- `StopFailed`

Unknown code map เป็น `AuthorizationUnavailable`; wire ไม่มี detail/message field Launcher/application mapping ข้อความไทยจาก `typed-errors.json` เท่านั้น

ขอบเขต enumต่อ schema:

| Boundary | Allowed error codes |
|---|---|
| Core Protocol v2 result | 17 codesทั้งหมดใน `protocol.schema.json` |
| Backend start authority response | `AuthorizationRequired`, `AuthorizationInvalid`, `AuthorizationUnavailable`, `SessionInactive`, `EntitlementInactive`, `HeartbeatStale` |
| Backend renewal failure | `AuthorizationUnavailable`, `SessionInactive`, `EntitlementInactive`, `HeartbeatStale` |

Backendห้ามส่ง Core-only code และ Core/Launcherห้ามขยาย enumใน wireโดยไม่ออก revisionใหม่

Local adapter error เช่น artifact invalid หรือ channel unavailable อาจมี internal enum แยกต่างหาก แต่ห้าม serializeเป็น wire codeที่ไม่มีใน schema และห้ามเผย arbitrary exception text

---

## 13. Timeout ceilings

| Operation | Maximum local deadline |
|---|---:|
| Target wait | 120 s |
| Pipe readiness | 5 s |
| Frame write | 2 s |
| Frame read/challenge | 5 s |
| Backend issuance | 10 s |
| Authorized start | 15 s |
| Status | 3 s |
| Graceful stop | 10 s |
| Owned-host exit | 5 s |
| Kill wait | 5 s |
| Renewal cadence | 15 s |
| Renewal material lifetime | 30 s |
| Core revocation stop deadline | 5 s |

ทุก wait ใช้ monotonic total deadlineเดียว ไม่ resetต่อ partial I/O และรองรับ cancellation ค่า operation timeoutไม่เปลี่ยน permit validity

---

## 14. Cleanup, ownership และ ambiguous outcomes

หลัง host-start attempt ทุก failure ต้องเข้า bounded cleanup:

1. best-effort typed stopถ้า channelที่ bindกับ owned Coreใช้ได้
2. graceful stop owned Core
3. bounded wait
4. killเฉพาะ owned process/jobหลัง timeout
5. release handles/channel/temp state
6. retain typed root failure; cleanup exceptionห้ามกลบ root failure

ห้าม killด้วย process name, PIDที่ไม่ได้ถือ ownership หรือ pipe identityเพียงอย่างเดียว

หลัง start write timeout/disconnect/correlation mismatch หรือ resultกำกวม ห้าม retransmit requestเดิมและห้าม reuse challenge/permit ต้อง cleanup/reconcileตาม frozen status semantics แล้วเริ่ม attemptใหม่ด้วย challengeใหม่

---

## 15. Secrecy requirements

ห้าม token, permit, private key, service-role key, reusable proxy credential หรือ raw proxy configurationอยู่ใน:

- argv/process command line
- environment
- config/file/temp/cache/keyring/clipboard
- log/UI/exception/traceback
- telemetry/minidump/crash annotation
- package/test snapshot/output

Launcherเปิด opaque valueได้เฉพาะ direct transport buffer Coreต้องไม่ echo permitหรือ claims detail Backendเก็บ production private keyใน approved server-side custodyเท่านั้น

ทุกทีมต้องมี unique secret-sentinel testsและ scan runtime/package artifactsจริง

---

## 16. S1 PROXY-ACCESS — hard release blocker

Production release **ห้ามผ่าน** จน Backend/Proxy Server/Securityส่งและทดสอบครบ:

- downstream access แบบ short-livedหรือ non-reusable
- bind กับ runtime/session/authorization
- expiryและ revocation enforcement
- protected in-memory delivery
- ไม่มี static reusable proxy credentialใน Launcher/Core/package/config
- extracted-bundle/direct-proxy bypass tests
- payload-free server-side counter evidence
- Security acceptance record

S0 launch permitไม่ใช่ Shadowsocks/proxy credential และห้ามนำไปใช้แทน S1 mechanism

---

## 17. Required test matrix

### 17.1 Shared contract

- package validator PASSและ revision/hashตรงทุก repo
- exact JSON schemas, duplicate/unknown fields, wrong types, BOM, malformed UTF-8
- oversize/truncated/partial frameและ total deadlines
- canonical config cross-language bytes/hash fixtureตรง
- positive vector `valid-launch-01` ACCEPT
- negative vectors `N-001..N-014` คืน expected codeและ engine start count 0
- JWT lexical negatives: empty/whitespace-only string, non-ASCII identifier, identifierยาวเกิน 128 และ `jti` ยาวเกิน 64 ต้อง reject
- NumericDate negatives: string/float/boolean/overflow ต้อง reject
- deterministic wall-clock boundaries: `now=exp-1`, `exp`, `exp+1` อยู่ใน skew allowance และ `now=exp+2` reject; future `iat/nbf` boundaryที่ `now+2`/`now+3` ต้องตรง policy

### 17.2 Launcher

- no target / heartbeat fail / artifact fail → host side effect 0
- PID replacementทุก boundary → no start
- authority requestไม่มี `sub/sid/iid/lid` และตรง schema
- no challenge → no permit request
- ambiguous issuance/start → no automatic retry/reuse
- fake same-user pipe server → permitไม่ถูกส่ง
- only matching typed `Running` is success
- duplicate start → exactly one flow
- partial host startและ cancellation → no orphan

### 17.3 Core

- protocol v1/no permit/alternate legacy entry → engine start 0
- strict JWT header/claim/time/key/config/target negatives → engine start 0
- pre-admission disconnectไม่ consume; admitted failure consume
- replay/concurrent double-use → successสูงสุดหนึ่ง
- target disappears after verification before `Starting` → engine start 0
- valid target+permit → exactly one runtime
- renewal missing/invalid/expired/revoked/Backend outage → stopตาม deadline
- modified Launcherไม่ทำให้ runtimeอยู่เกิน signed expiry

### 17.4 Artifact, secrecy และ S1

- manifest schema, trust anchor, missing/extra/hash/size/signature failures
- manifest paths: absolute/drive/UNC/leading separator/backslash/`.`/`..`/empty segment/trailing separator, duplicate, case collision, symlink/junction/reparse และ resolved-outside-root ต้อง reject
- pipe identity: fake same-user server, server PID mismatch, PID reuse, owned-process exit/replacement, identity API failureและ disconnectก่อน permit write ต้อง fail closedโดย permitไม่ถูกเปิดเผย
- clean machine package/install/start/stop
- token/permit/proxy sentinel scanทุก surface
- extracted bundleไม่มี direct reusable proxy bypass
- S1 expiry/revocation/server countersผ่าน

### 17.5 Real E2E

ใช้ production adapter pathและ artifactsเดียวกับที่จะ ship:

1. no target → no activation
2. target present/no permit → engine start 0
3. invalid/expired/replayed/config-mismatched permit → engine start 0
4. target replacement → engine start 0
5. valid target+valid permit → exactly one `Running`
6. renewal successคง runtimeตาม signed windows
7. revocation/outage/expiry → bounded stop
8. Launcher exit/Core crash/target exit → no orphan
9. S1 accessไม่ reusableหลัง extractionหรือ expiry

---

## 18. Team work orders

### Launcher Team

1. บันทึก acceptance ของ `s0-rc1` + package hash เฉพาะขอบเขตที่ packageกำหนด และรอ accept revision/hashใหม่สำหรับ renewal wire, manifest path safety และ pipe process bindingก่อน production
2. เปลี่ยน boundary commandให้มี target PID/modeและ canonical digest
3. แก้ authority clientให้ตรง §6; ห้ามส่ง server-owned identity fields
4. implement verified artifact/process adapterพร้อม immutable trust anchor
5. implement strict Named Pipe clientและ bind serverกับ owned Core
6. implement production heartbeat, permitและrenewal clients
7. wire orchestratorตาม §9.8โดยไม่มี bypass
8. map frozen errorsและผ่าน Launcher/security/E2E matrix
9. คง `AuthorizationPendingProxyGateway` จนทุก gateผ่าน

### NekoProxyCore Team

1. บันทึก acceptance ของ `s0-rc1` + package hash เฉพาะขอบเขตที่ packageกำหนด และรอ accept revision/hashใหม่สำหรับ renewal wire, manifest path safety และ pipe process bindingก่อน production
2. rebase/merge verified partial challenge/authorization seamsอย่างตรวจสอบได้
3. implement strict verifier/key resolver/replay/config/PID binding
4. implement Protocol v2 current-user Named Pipe headless host
5. วาง innermost authorized-start boundaryและปิด legacy bypass
6. implement mandatory runtime renewal/expiry enforcement
7. publish exact manifest + signed immutable `win-x64` bundle
8. ผ่าน Core/security/E2E matrix

### Backend/Security

1. ก่อนสั่ง production implementation ให้ publish contract revisionถัดไปเพื่อปิด renewal gap §11.1 พร้อม schemas, signed-renewal claims/time rules, fixtures, checksumsและ package SHAใหม่
2. publish production authority endpoint/deployment handleแยกจาก sanitized contract
3. enforce authenticated server-resolved identity; request schema exact
4. operate signer, immutable public-key release, rotation/revocation
5. implement start issuanceและrenewalตาม revisionที่ปิด gapแล้ว
6. fail closedและrate-limitพร้อม sanitized audit evidence
7. ร่วมตรวจ S1และ E2E

### Proxy Server/Security S1

1. ส่ง non-reusable runtime-bound access design/implementation
2. enforce expiry/revocationและ protected delivery
3. ส่ง extracted-package bypass testsและ payload-free counter evidence
4. บันทึก Security acceptance

### QA/Release

1. verify revisions, package hash, artifact identityและ clean worktrees
2. run complete shared/negative/secrecy/cleanup/E2E matrix
3. ตรวจ shipped artifacts ไม่ใช่ scaffold/test doubles
4. เก็บ role-level approvalsและห้าม releaseถ้า checklistไม่ครบ

---

## 19. Production release checklist — ต้องครบทุกข้อ

- [ ] Launcher Owner accepts `NEKO-AUTH-S0/s0-rc1` และ exact package SHA
- [ ] Core Owner accepts revision/hashเดียวกัน
- [ ] Backend/Security approvalยัง validและ package validator PASS
- [ ] Launcher authority requestตรง schemaและไม่มี server-owned identity fields
- [ ] Protocol v2/canonical config/PID/mode bindingตรงทุกฝั่ง
- [ ] strict Core verifier + immutable key allow-listผ่าน fixturesทั้งหมด
- [ ] JWT empty/non-ASCII/length/typeและ exact NumericDate boundary testsผ่าน
- [ ] challenge admission/replay/concurrency semanticsผ่าน
- [ ] mandatory 15-second renewalและ Core signed-expiry enforcementผ่าน
- [ ] manifest exact schema + signed immutable trust anchorผ่าน
- [ ] revisionใหม่ปิด manifest path traversal/collision/reparse/root-containment semanticsและ negative testsผ่าน
- [ ] revisionใหม่ปิด exact Named Pipe ACL + race-safe owned-Core server identity bindingและ negative testsผ่าน
- [ ] revisionใหม่ปิด Launcher↔Core renewal wire, runtime ID, signed-renewal claims/time/key/replay semanticsและ fixturesผ่าน
- [ ] no legacy/offline/allow-all/local signer/debug bypass
- [ ] typed wire errorsตรง schemaและไม่มี arbitrary detail
- [ ] timeout/cancellation/ambiguous outcome/bounded cleanup/no-orphanผ่าน
- [ ] secret-sentinel scanผ่าน runtimeและ packageจริง
- [ ] S1 non-reusable downstream proxy accessผ่านและ Security accept
- [ ] real production-path cross-repository E2E ผ่าน
- [ ] QA/Security/Releaseอนุมัติ revision/hash/artifacts/evidenceชุดเดียวกัน

หากข้อใดไม่ครบ สถานะต้องเป็น `PRODUCTION BLOCKED` และ Launcherต้องคง fail-closed composition

---

## 20. Definition of Done และหลักฐานส่งกลับ

แต่ละทีมส่งกลับหนึ่ง handoffที่มี:

- repository, branch, full commit SHA, clean/dirty state
- accepted contract revisionและ package SHA
- files changedและ production composition path
- exact commands + unabridged pass/fail counts
- shared fixture results
- negative/security/secrecy/cleanup results
- immutable artifact/endpoint/release handleที่ตรวจย้อนกลับได้
- unresolved itemsแยก owner
- explicit statementว่าไม่มี secret/credential/raw runtime configใน evidence
- owner decisionและ reviewer decision

Connector รับได้เมื่อ source, tests, artifact identity, contract revision/hashและรายงานตรงกัน ห้ามใช้เอกสารอย่างเดียวแทน implementationและ real execution

---

## 21. Source-of-truth files

ภายใต้ `Backend Security/security-contract/NEKO-AUTH-S0/s0-rc1/`:

- `README.md`
- `PACKAGE-SHA256.txt`
- `SHA256SUMS`
- `approvals.md`
- `protocol.schema.json`
- `authority-request.schema.json`
- `authority-response.schema.json`
- `renewal.schema.json`
- `artifact-manifest.schema.json`
- `typed-errors.json`
- `canonical-config.txt`
- `canonical-config.sha256`
- `signature-positive-vectors.json`
- `signature-negative-vectors.json`
- `validate_package.py`

---

## Final decision

เอกสารนี้ supersede คำแนะนำ adapter เดิมที่ขัดกับ `s0-rc1` แต่ไม่เปลี่ยนสถานะ approvals: Backend/Security technical baselineพร้อมแล้ว; Launcher/Core acceptance, implementation, S1, real E2E และ Release approvalยังต้องส่งหลักฐานจริง Production wiringและreleaseยัง `BLOCKED` จน checklist §19 ผ่านครบ

---

## 22. 2026-08-05 fail-closed production-composition progress

ตรวจจาก repository นี้บน branch `main` ที่
`1ea639ff042e06bbea57d0f46e93fd0e7f718970` ซึ่งตรงกับ `origin/main` ก่อนแก้ไข:

- เพิ่ม `ProductionAuthorizationGate` ที่ pin `NEKO-AUTH-S0/s0-rc1` และ package SHA-256 ข้างต้น
- ระบุ blocker ที่ยังเปิดแบบ machine-readable และให้ `is_ready=false` จน blocker เป็นศูนย์
- ให้ Launcher composition root เรียก `create_production_proxy_gateway()` แทนการสร้าง pending gateway โดยตรง
- factory ปัจจุบันคืน `AuthorizationPendingProxyGateway` เท่านั้น จึงไม่มี partial/implicit production enablement
- หาก gate ถูกตั้ง ready ก่อนมี approved production adapters factory จะ throw และ fail closed แทนการเปิด start

หลักฐาน fresh local:

```text
uv run --frozen --extra dev python -m ruff check src tests
All checks passed

uv run --frozen --extra dev python -m pytest -q -m "not integration"
112 passed, 2 deselected

python scripts/check_repository_safety.py
Repository safety check passed
```

ไฟล์ implementation/test ของ progress นี้ยังเป็น working-tree changes และยังไม่มี commit/release approval
ผลนี้พิสูจน์เฉพาะ contract pinning และ fail-closed composition; ไม่ได้พิสูจน์ Backend issuance,
approved public-key release, `start → Running`, renewal, S1 access, signed bundle หรือ production readiness
