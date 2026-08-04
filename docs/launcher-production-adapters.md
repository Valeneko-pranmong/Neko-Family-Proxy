# Launcher Production Adapters — NEKO-AUTH-S0

**สถานะเอกสาร:** Launcher implementation specification / handoff

**สถานะระบบ:** `BACKEND/SECURITY TECHNICAL BASELINE APPROVED — LAUNCHER ACCEPTANCE PENDING — PRODUCTION BLOCKED`

**Contract ID:** `NEKO-AUTH-S0`

**Accepted baseline candidate:** `s0-rc1`

**Contract package SHA-256:** `6697351b6b280afc566fedaaa1a6cfe207b1ea1d803c2eb613b4c1a891e192df`

**Canonical configuration SHA-256 (synthetic fixture):** `92ac70d0f9b100ba664f2bb205b2c042bc1058f779e94e759822d906ea880871`

**Source of truth:** `Backend Security/security-contract/NEKO-AUTH-S0/s0-rc1/`

**Central handoff:** [`neko-auth-s0-production-handoff.md`](neko-auth-s0-production-handoff.md)

> เอกสารนี้แปลง central handoff เป็นข้อกำหนดฝั่ง Launcher เท่านั้น ไม่ใช่ production release approval หากข้อความใดขัดกับ package `s0-rc1` ให้ยึด package เป็น source of truth และหยุด production wiring จนกว่า owner จะ reconcile สำเร็จ

---

## 1. คำตัดสินปัจจุบัน

Production composition ใน `launcher/src/neko_launcher/main.py` ต้องคง:

```text
AuthorizationPendingProxyGateway
```

จนกว่า release checklist ใน §13 จะผ่านครบ ห้าม wire `AuthorizedProxyGateway` เข้าสู่ production จากเอกสารนี้เพียงอย่างเดียว

สิ่งที่ `s0-rc1` อนุมัติเป็น technical baseline แล้ว:

- Protocol v2, framing, strict JSON และ typed wire errors
- canonical start configuration และ SHA-256 binding
- Core challenge/admission semantics
- JWT/RS256 launch-permit verification และ key lifecycle
- Backend start-authority request/response schemas
- continuous-authorization policy และ Launcher ↔ Backend `renewal.schema.json`
- immutable artifact-manifest schemaในขอบเขตเดิม
- synthetic positive/negative fixtures
- fail-closed secrecy, timeout และ cleanup rules

สิ่งที่ยัง block Launcher production implementation/composition:

1. Launcher Owner และ Core Owner ยังไม่ accept revision/hash เดียวกัน
2. package ยังไม่มี Launcher ↔ Core renewal wire, signed-renewal token/runtime semantics และ runtime ID contract
3. manifest schema ยังไม่ปิด path traversal, collision, reparse point และ resolved-root semantics
4. Named Pipe contract ยังไม่ pin exact process-binding algorithm และ fixtures
5. production endpoint/public configuration, signed Core bundle และ production public-key artifacts ยังไม่ถูก release
6. S1 downstream proxy-access mechanism และ real cross-repository E2E ยังไม่ผ่าน
7. QA/Security/Release ยังไม่อนุมัติ artifact/evidence ชุดเดียวกัน

Launcher ทำ unit seams หรือ security spikesตาม candidate decisionsได้ แต่ต้อง fail closed และห้ามอ้างว่าเป็น production contract จน Backend/Security ออก revision/package hash ใหม่และ owner ทุกฝ่าย accept ใหม่

---

## 2. Package verification และ acceptance

ก่อน implement ให้ตรวจ packageจาก directory ของ package:

```bash
python validate_package.py
```

ผลของ `s0-rc1` ต้องเป็น:

```text
PASS contractRevision=s0-rc1
PASS files=15
PASS canonicalSha256=92ac70d0f9b100ba664f2bb205b2c042bc1058f779e94e759822d906ea880871
PASS packageSha256=6697351b6b280afc566fedaaa1a6cfe207b1ea1d803c2eb613b4c1a891e192df
PASS syntheticRs256Vector=valid-launch-01
PASS privateKeyMarkers=0
```

Launcher acceptance record ต้องระบุ:

```text
Contract ID: NEKO-AUTH-S0
Accepted revision: s0-rc1
Accepted package SHA-256: 6697351b6b280afc566fedaaa1a6cfe207b1ea1d803c2eb613b4c1a891e192df
Consumer revision: <full commit SHA>
Package validation: PASS
Owner decision: ACCEPT / REJECT พร้อมเหตุผล
```

คำว่า `FROZEN` ใช้ได้เมื่อ Launcher, Core, Backend/Security และ Release governance รับ revision/hash เดียวกันแล้วเท่านั้น Acceptance ของ `s0-rc1` ต้องจำกัดเฉพาะสิ่งที่ packageกำหนด และต้อง accept revision/hash ใหม่อีกครั้งสำหรับ gaps ใน §10

---

## 3. Production composition เป้าหมาย

```text
Launcher UI / authenticated application context
        |
        v
AuthorizedProxyGateway
        |
        v
AuthorizedCoreOrchestrator
        |-- ExactPso2ProcessTargetDetector
        |-- BackendFreshHeartbeatPrecondition
        |-- VerifiedCoreProcessAdapter
        |-- NamedPipeCoreControlChannel
        |-- BackendLaunchPermitGateway
        `-- RuntimeAuthorizationClient

หลัง Running:
        |-- mandatory 15-second renewal loop
        |-- target/Core/session monitoring
        `-- bounded stop/cleanup
```

Authority boundaries:

- Backend/Security เป็น authorization authority และถือ production private keyเท่านั้น
- Launcher เป็น orchestrator; ห้าม decode, sign, refresh, persist หรือใช้ permit claims ตัดสินสิทธิ์
- Core เป็น enforcement boundary; Launcher state และ Named Pipe ACL ใช้แทน permit verificationไม่ได้
- Proxy Server/Security S1 เป็น enforcement boundary ของ downstream proxy access

เส้นทาง start ที่ production ต้องมีเพียงทางเดียว:

```text
single-flight
→ validate local command/access context
→ wait exact pso2.exe and retain PID + creation identity/handle
→ fresh online heartbeat
→ recheck target
→ verify signed Core bundle and spawn owned Core without secrets
→ wait/bind strict control channel to owned Core
→ recheck target
→ request one Core challenge
→ recheck target
→ build canonical configuration + digest
→ request one Backend permit
→ check cancellation + recheck target
→ send one exact Protocol v2 start frame
→ accept matching typed Running only
→ begin mandatory renewal loop
→ monitor target/Core/session
→ bounded stop/cleanup
```

ห้ามมี legacy/direct/offline/allow-all/local-signer/debug path ที่ข้าม flow นี้

---

## 4. Frozen Launcher wire values

| รายการ | ค่า `s0-rc1` |
|---|---|
| Protocol | JSON integer `2` |
| Frame | unsigned 4-byte big-endian length + payload |
| Payload | strict UTF-8, no BOM, `1..8192` bytes |
| JSON | exact case; reject unknown/duplicate fieldsและ wrong types |
| Correlation ID | lowercase hex 32 characters |
| Permit transport | compact ASCII, `1..4096` characters |
| Challenge | CSPRNG 32 bytes; unpadded base64url 43 characters |
| Challenge lifetime | 30 seconds, monotonic time |
| Target | exact `pso2.exe`; PID `1..4294967295` |
| Mode | `ProcessMode` |
| Profile reference | `^profile-[0-9]{1,6}$` |
| Server reference | `^server-[0-9]{1,6}$` |
| Success | matching typed `Running` response only |

### 4.1 Protocol v2 requests

`challenge`:

```json
{
  "version": 2,
  "command": "challenge",
  "correlationId": "<32-lowercase-hex>"
}
```

`start`:

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

`status` และ `stop` มีเฉพาะ `version`, `command`, `correlationId` ตาม `protocol.schema.json` ห้ามเพิ่ม optional production field หรือ reuse command เหล่านี้เพื่อ renewal

### 4.2 Canonical configuration

Launcher ต้องสร้าง exact UTF-8/no BOM/LF/final LF bytes:

```text
protocolVersion=2
mode=ProcessMode
processName=pso2.exe
targetPid=<validated PID>
profileReference=<validated profile-N>
serverReference=<validated server-N>
```

ใช้ค่าที่ validate แล้วโดยไม่ normalize เพิ่ม จากนั้นคำนวณ SHA-256 lowercase hex Target ต้องถูก recheckหลัง heartbeat, channel ready, challenge, permit และก่อนส่ง `start`; target หายหรือถูกแทนต้อง fail เป็น `ProcessExited` โดยไม่มี Core engine side effect

---

## 5. Launcher adapters

### 5.1 `AuthorizedProxyGateway`

Production facade เดียวที่จะแทน `AuthorizationPendingProxyGateway` เมื่อ gatesผ่าน:

- implement application `ProxyGateway.start()` / `stop()`
- snapshot local fail-fast factsโดยไม่ serialize server-owned identityใน authority body
- สร้าง target-bound commandหลัง detect exact target
- เรียก `AuthorizedCoreOrchestrator` เพียงเส้นทางเดียว
- map typed errorsผ่าน trusted allow-list; unknown codeเป็น `AuthorizationUnavailable`
- ถือ attempt/runtime cancellation state และบังคับ single-flight
- ห้ามรับ raw endpoint, port, cipher, password หรือ static proxy credential
- ห้ามเผย arbitrary `str(exc)` ใน UI/log/telemetry

### 5.2 `ExactPso2ProcessTargetDetector`

```text
wait_for_exact_pso2(deadline, cancellation)
  -> TargetIdentity(pid, creation_identity/owned_handle)
is_same_target_still_running(target) -> bool
```

ข้อบังคับ:

- match basename exact `pso2.exe`
- PIDอยู่ใน `1..4294967295`
- retain creation identity หรือ owned handleเพื่อป้องกัน PID reuse
- ใช้ monotonic total deadline สูงสุด 120 วินาทีและรองรับ cancellation
- access denied, malformed process data, API error หรือ ambiguity ต้อง fail closed
- detector ห้าม spawn Core และต้อง recheck targetทุก boundaryใน §3

### 5.3 `BackendFreshHeartbeatPrecondition`

- probe Backend onlineใหม่ทุก admitted start attempt
- Backendตรวจ authenticated session/installation relationshipจาก server state
- false/error/timeout/cancellation → Core spawn/challenge/permit/start side effectเป็นศูนย์
- cached heartbeat หรือ periodic graceใช้แทน fresh probeไม่ได้
- heartbeat เป็น precondition ไม่ใช่ permitและไม่ใช่ continuous authorization
- authenticated transport contextต้องมาจาก secure session infrastructure ไม่ใช่ loggable argument/config

### 5.4 `VerifiedCoreProcessAdapter`

ต้อง parse exact `artifact-manifest.schema.json` และ pin:

- `schemaVersion=1`
- `contractId=NEKO-AUTH-S0`
- `contractRevision=s0-rc1`
- exact package SHA-256
- bounded `coreVersion`
- `rid=win-x64`
- `executable=NekoProxyCore.exe`
- complete `files[]` ที่มี exact `path`, `sha256`, `size`
- ไม่มี additional properties

ต้อง verify immutable signed release trust anchorก่อนเชื่อ manifest และ reject missing/extra/hash/size/path/signature mismatch

Candidate path-safety requirementsที่ต้องรอ revisionใหม่ก่อน production:

- normalized relative paths ใช้ `/` เท่านั้น
- reject absolute/rooted/drive/UNC, leading separator, backslash, `.`, `..`, empty segment และ trailing separator
- reject duplicate path และ Windows case-insensitive collision
- reject symlink/junction/reparse pointทุก componentและ final file
- เปิด/ตรวจผ่าน race-safe handles และพิสูจน์ final resolved pathอยู่ใต้ immutable bundle root

Spawn requirements:

- fixed argv, no shell, verified immutable working directory
- explicit environment allow-list
- ไม่มี token/permit/credential/raw config ใน argv/env/disk/log
- retain owned process handle/job object; killเฉพาะ processที่ Launcherสร้าง
- partial spawn failureต้องเข้า cleanup
- process/PID/pipe existenceไม่ใช่ readiness

### 5.5 `NamedPipeCoreControlChannel`

- exact Protocol v2 framing/schema/deadline
- current-user-only ACL เป็น defense in depth ไม่ใช่ server identity proof
- retain non-inheritable owned Core process handleตลอด attempt
- handleต้องมีอย่างน้อย `SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION`
- หลัง connect และก่อน serialize/reveal/write permit ให้ตรวจ connected pipe server PIDด้วย `GetNamedPipeServerProcessId`
- เทียบ server PIDกับ `GetProcessId(ownedProcessHandle)`
- ก่อนและหลัง comparison ต้องยืนยัน owned processยังไม่ signaledและ creation identityยังตรง
- API unavailable/failure, mismatch, process exit/replacement หรือ disconnectต้องปิด pipeและ fail closedก่อน permit write
- ห้ามสร้าง start payloadที่มี permitก่อน identity sequenceผ่าน
- `OpaquePermit.reveal_for_transport()` ใช้เฉพาะ direct write buffer
- response correlationต้องตรง request และ successเฉพาะ typed `Running`
- หลัง ambiguous start outcomeห้าม retransmitหรือ reuse challenge/permit

ข้อกำหนด process-binding ข้างต้นเป็น central candidate decision; production implementationต้องรอ schema/algorithm/fixturesใน revisionใหม่

### 5.6 `BackendLaunchPermitGateway`

Production boundary:

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

Request body ต้องตรง `authority-request.schema.json` เท่านั้น:

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

ห้าม serialize `sub`, user ID, `sid`, session ID, `iid`, installation ID/hash, `lid` หรือ license IDลง body Backendต้อง resolve identity/entitlement/session/installation/heartbeatจาก authenticated server state

Response ต้องตรง `authority-response.schema.json`; successต้องมี `expiresInSeconds=30` Signer/database/authority ambiguityต้อง fail closed และห้าม automatic retryหลัง ambiguous issuance—attemptใหม่ต้องเริ่มด้วย challengeใหม่

`OpaquePermit` ต้อง redactedใน `repr`, `str` และ exception Launcherห้าม decode, re-sign, refresh, persistหรือ log permit

Launcher integration และ release artifactต้องสอดคล้องกับ verifier baseline: permitเป็น compact JWT สาม segments, `alg=RS256`, `typ=neko-launch+jwt`, ใช้ exact known `kid`, lifetime 30 วินาที และ future/expiration skew 2 วินาทีตาม package Core public keysต้องเป็น immutable release-bundled allow-list; ห้าม token-controlled URL/JWKS, first-key fallback หรือ local signer Production endpoint/deployment handleและ signed public-key release artifactsยังเป็น deployment blockers

### 5.7 `RuntimeAuthorizationClient`

Policyที่อนุมัติ:

- ขอ fresh Core renewal challengeทุก 15 วินาที
- ขอ signed renewal materialจาก Backendตาม `renewal.schema.json`
- forward opaque materialให้ Coreก่อน signed authorizationเดิมหมดอายุ
- Backend outage/invalid responseไม่มี offline success
- Launcher exitหรือ renewal failureต้อง trigger bounded Core stop
- Coreต้อง enforce signed expiryเองแม้ Launcherถูกแก้ไขหรือ crash

อย่างไรก็ตาม `s0-rc1` ยังไม่มี Launcher ↔ Core renewal commands หรือ signed-renewal/runtime semantics จึง implementได้เฉพาะ fail-closed seam ห้ามเดา fields, reuse `start`/`challenge`, ใช้ cached permit, local heartbeat timestamp, grace period หรือ Launcher booleanเพื่อขยาย runtime

---

## 6. Typed error boundary

Wire allow-list:

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

Boundary-specific constraints:

| Boundary | Allowed errors |
|---|---|
| Core Protocol v2 | 17 codesทั้งหมดใน `protocol.schema.json` |
| Backend start authority | `AuthorizationRequired`, `AuthorizationInvalid`, `AuthorizationUnavailable`, `SessionInactive`, `EntitlementInactive`, `HeartbeatStale` |
| Backend renewal | `AuthorizationUnavailable`, `SessionInactive`, `EntitlementInactive`, `HeartbeatStale` |

Unknown code mapเป็น `AuthorizationUnavailable`; wireไม่มี detail/message field Launcher mapข้อความไทยจาก `typed-errors.json` เท่านั้น Local adapter errorsอาจมี internal enum แต่ห้าม serialize codeนอก schemaหรือเผย arbitrary exception text

---

## 7. Deadlines และ retry policy

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
| Core revocation stop | 5 s |

ทุก operationใช้ monotonic total deadlineเดียว ไม่ resetต่อ partial I/O และรองรับ cancellation Operation timeoutไม่เปลี่ยน permit validity

Retry rules:

- challenge/permit/startใช้ได้ attemptเดียว
- malformed/disconnectก่อน challenge admissionไม่ consume; admitted failure/timeout/disconnect/ambiguous outcome consume
- ห้าม retransmit `start` หลัง write timeout, disconnect, malformed responseหรือ correlation mismatch
- ห้าม reuse challenge/permitหลัง admittedหรือ ambiguous outcome
- attemptใหม่เริ่ม target/precondition/challenge/permitใหม่ทั้งหมด
- Backend/key/pipe outageต้อง fail closed ไม่มี offline/local signing fallback

---

## 8. Cleanup และ ownership

ทุก failureหลังเริ่ม hostต้อง cleanupแบบ bounded โดย retain typed root failure:

1. best-effort typed `stop` ถ้า channelที่ bindกับ owned Coreยังใช้ได้
2. graceful stop owned Core
3. bounded wait
4. killเฉพาะ owned process/jobหลัง timeout
5. release handles/channel/temp state
6. cleanup exceptionห้ามกลบ root failure

ห้าม killด้วย process name, unowned PID หรือ pipe identityเพียงอย่างเดียว Partial spawn, cancellation และ ambiguous startต้องไม่ทิ้ง orphan process/helper/pipe/mutex/controller/temp state

---

## 9. Secrecy requirements

ห้าม token, permit, private/signing key, service-role key, reusable proxy credential หรือ raw proxy configurationอยู่ใน:

- argv/process command line
- environment
- config/file/temp/cache/keyring/clipboard
- log/UI/exception/traceback
- telemetry/minidump/crash annotation
- package/test snapshot/output

Launcherเปิด opaque permitได้เฉพาะ direct transport buffer และต้องมี unique secret-sentinel testsที่ scan runtime/package artifactsจริง Evidenceห้ามมี secret, credential, customer/session/installation identifier หรือ raw runtime configuration

### 9.1 S1 downstream proxy access — hard release blocker

S0 launch permitไม่ใช่ Shadowsocks/proxy credentialและห้ามใช้แทน S1 Production releaseต้องมี short-lived/non-reusable downstream accessที่ bindกับ runtime/session/authorization, enforce expiry/revocation, ส่งผ่าน protected in-memory delivery และไม่มี static reusable credentialใน Launcher/Core/package/config ต้องผ่าน extracted-bundle/direct-proxy bypass tests, payload-free server-side counter evidence และ Security acceptance

---

## 10. Contract gaps ที่ห้าม Launcher เดา

Backend/Security contract ownerต้องออก revision/package hash ใหม่ที่ปิดพร้อมกัน:

1. exact Launcher ↔ Core renewal challenge request/response
2. exact renewal submission request/response
3. signed-renewal format, protected header, claims/types, audience/scope, runtime/config/session binding และ time rules
4. runtime ID generation/representation/ownership
5. renewal correlation, admission, one-use, replay และ ambiguous-outcome semantics
6. renewal frame/material limits, code-only errors และ cross-language fixtures
7. manifest path grammar, duplicate/case-collision/reparse/resolved-root rulesและ negative fixtures
8. exact Windows pipe server-process binding algorithm, access rights, race/failure orderingและ fixtures
9. exact approved pipe/mutex identitiesและ current-user ACL contract
10. updated package inventory/checksums/package SHA-256 และ owner acceptances

Production wiring/releaseยัง `BLOCKED` และ renewal/manifest-path/pipe-identity checklistห้ามผ่านด้วย residual-risk acceptance

---

## 11. Launcher test matrix

### 11.1 Contract and orchestration

- package validator PASSและ revision/hashตรง acceptance record
- exact JSON schema; reject duplicate/unknown fields, wrong case/types, BOM และ malformed UTF-8
- oversize/truncated/partial frameและ monotonic total deadlines
- canonical config bytes/hashตรง cross-language fixture
- no target / heartbeat fail / artifact fail → host side effect 0
- PID replacementทุก boundary → no start
- authority bodyตรง schemaและไม่มี `sub`, `sid`, `iid`, `lid` หรือ installation hash
- JWT lexical negatives: empty/whitespace-only, non-ASCII identifier, identifierเกิน 128 และ `jti` เกิน 64 ต้อง reject
- NumericDate string/float/boolean/overflow ต้อง reject และ boundary `exp-1`, `exp`, `exp+1`, `exp+2`, future `iat/nbf +2/+3` ต้องตรง policy
- no challenge → no permit request
- ambiguous issuance/start → no automatic retry/reuse
- fake same-user pipe server → permitไม่ถูก reveal/write
- only matching typed `Running` is success
- duplicate/concurrent start → exactly one flow
- partial host start/cancellation → no orphan

### 11.2 Artifact and pipe identity

- exact manifest schema/trust anchor
- missing/extra/hash/size/signature mismatch reject
- absolute/drive/UNC/leading separator/backslash/`.`/`..`/empty/trailing path reject
- duplicate/case collision/symlink/junction/reparse/resolved-outside-root reject
- fake server, PID mismatch/reuse, owned-process exit/replacement, API failureและ disconnectก่อน permit write fail closed
- verify permit sentinelไม่ปรากฏใน serialized payloadก่อน identity sequenceผ่าน

### 11.3 Security and real E2E

- invalid/expired/replayed/config-mismatched permit → engine start 0
- target replacement → engine start 0
- valid target+permit → exactly one `Running`
- renewal successคง runtimeตาม signed windows
- renewal missing/invalid/expired/revoked/Backend outage → bounded stop
- Launcher exit/Core crash/target exit → no orphan
- secret-sentinel scanทุก surface
- S1 accessไม่ reusableหลัง extractionหรือ expiry พร้อม payload-free server-side counter evidence
- production-path cross-repository E2Eใช้ artifactsเดียวกับที่จะ ship

Revision ใหม่และ production artifactsยังไม่มีใน repository นี้ ดังนั้น testsของ candidate seamsไม่ใช่หลักฐาน production acceptance

---

## 12. Launcher work order

1. บันทึก acceptance `s0-rc1` + exact package hashเฉพาะขอบเขตที่ packageกำหนด
2. รอ accept revision/hashใหม่สำหรับ renewal wire, manifest path safety และ pipe process bindingก่อน production
3. เปลี่ยน boundary commandให้มี target PID/modeและ canonical digest
4. แก้ authority clientให้ตรง §5.6และไม่ส่ง server-owned identity fields
5. implement exact detectorและ fresh authenticated heartbeat precondition
6. implement verified artifact/process adapterพร้อม immutable trust anchor
7. implement strict Named Pipe clientและ bind serverกับ owned Coreก่อน reveal permit
8. implement permit gatewayและ fail-closed renewal seam
9. wire orchestratorตาม §3โดยไม่มี bypass
10. map frozen errorsและผ่าน Launcher/security/E2E matrix
11. คง `AuthorizationPendingProxyGateway` จนทุก gateผ่าน

---

## 13. Production wiring/release checklist

- [ ] Launcher Owner accepts `NEKO-AUTH-S0/s0-rc1` และ exact package SHA
- [ ] Core Owner accepts revision/hashเดียวกัน
- [ ] Backend/Security approval validและ package validator PASS
- [ ] production authority endpoint/deployment handleและ immutable public-key release artifactsพร้อม
- [ ] Launcher authority requestตรง schemaและไม่มี server-owned identity fields
- [ ] Protocol v2/canonical config/PID/mode bindingตรงทุกฝั่ง
- [ ] challenge admission/replay/concurrency semanticsผ่าน
- [ ] strict Core verifier/key allow-listและ fixturesผ่าน
- [ ] mandatory renewalและ Core signed-expiry enforcementผ่าน
- [ ] revisionใหม่ปิด manifest path-safety semanticsและ negative testsผ่าน
- [ ] revisionใหม่ปิด exact Named Pipe server identity bindingและ negative testsผ่าน
- [ ] revisionใหม่ปิด Launcher ↔ Core renewal wire/runtime/token semanticsและ fixturesผ่าน
- [ ] immutable signed `win-x64` Core bundleและ manifestผ่าน
- [ ] no legacy/offline/allow-all/local-signer/debug bypass
- [ ] typed errorsตรง schemaและไม่มี arbitrary detail
- [ ] timeout/cancellation/ambiguous outcome/bounded cleanup/no-orphanผ่าน
- [ ] secret-sentinel scanผ่าน runtimeและ packageจริง
- [ ] S1 runtime-bound downstream access, expiry/revocation, protected delivery, extraction bypass และ server countersผ่านพร้อม Security accept
- [ ] real production-path cross-repository E2Eผ่าน
- [ ] QA/Security/Releaseอนุมัติ revision/hash/artifacts/evidenceชุดเดียวกัน

หากข้อใดไม่ครบ Launcherต้องคง fail-closed production compositionและสถานะ `PRODUCTION BLOCKED`

---

## 14. Definition of Done และหลักฐานส่งกลับ

Launcher handoffต้องมี:

- repository, branch, full commit SHA และ clean/dirty state
- accepted contract revision/package SHA
- files changedและ exact production composition path
- exact commandsพร้อม unabridged pass/fail counts
- shared fixture, negative/security/secrecy/cleanup results
- immutable artifact/endpoint/release handlesที่ตรวจย้อนกลับได้
- unresolved itemsแยก owner
- explicit statementว่า evidenceไม่มี secret/credential/raw runtime config
- Launcher Owner decisionและ reviewer decision

เอกสารหรือ test doublesอย่างเดียวใช้แทน production implementation, shipped artifacts และ real executionไม่ได้

---

## 15. Source-of-truth files

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

Repository references:

- [`neko-auth-s0-production-handoff.md`](neko-auth-s0-production-handoff.md)
- `docs/archive/launcher-s0-connector-handoff.md` (historical)
- `docs/archive/launcher-core-authorization-adapter-draft.md` (historical)
- `launcher/src/neko_launcher/application/authorized_core.py`
- `launcher/src/neko_launcher/infrastructure/unavailable_gateway.py`
- `launcher/src/neko_launcher/main.py`
