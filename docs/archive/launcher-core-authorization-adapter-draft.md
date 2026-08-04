# Launcher ↔ Backend ↔ NekoProxyCore Authorization Adapter Handoff

> **HISTORICAL — SUPERSEDED DRAFT.** Use
> [`../neko-auth-s0-production-handoff.md`](../neko-auth-s0-production-handoff.md)
> for the current technical baseline and stop rules.

วันที่จัดทำ: 2026-08-03
ผู้รับผิดชอบปลายทาง: Launcher, Backend, Security และ NekoProxyCore teams
เอกสารอ้างอิงหลัก: `tools/STEP_E_SECURITY_AUTHORIZATION_REPORT.md`
สถานะ contract: **INTEGRATION DRAFT — REQUIRED FOR STEP E, NOT YET PRODUCTION-READY**

> เอกสารนี้เป็น sanitized integration contract สำหรับให้ทีม Launcher เตรียม adapter และ lifecycle orchestration ล่วงหน้า ไม่มี endpoint จริง, access token, proxy credential, private key, customer identifier หรือ runtime secret

---

## 1. เป้าหมาย

Launcher ต้องไม่สามารถเริ่ม ProcessMode ด้วย local state หรือ boolean ของตัวเองเพียงอย่างเดียว การเริ่มแต่ละครั้งต้องผ่านเงื่อนไขทั้งหมดดังนี้:

1. Launcher ตรวจพบ target ที่ canonical เป็น `pso2.exe` ก่อนเริ่ม Core host flow
2. Launcher มี authenticated account, active entitlement, installation, claimed session และ heartbeat ใหม่
3. Core ออก one-use challenge ใหม่สำหรับ start attempt นั้น
4. Launcher ส่ง challenge และ command binding ไปขอ short-lived permit จาก Backend แบบ online
5. Backend ตรวจ account/license/installation/session/heartbeat/configuration ฝั่ง server
6. Backend เซ็น permit ด้วย RS256 private key ที่ไม่อยู่ใน client
7. Launcher ส่ง permit ให้ Core ผ่าน bounded current-user named pipe เท่านั้น
8. Core ตรวจ signature, claims, time, challenge และ configuration hash เอง
9. Core ตรวจ `pso2.exe` ซ้ำก่อน runtime/driver/network side effects
10. Launcher ถือว่าเริ่มสำเร็จเมื่อได้รับ typed `Running` response จาก Core เท่านั้น

`Popen` สำเร็จ, Core process ยังอยู่, pipe เชื่อมได้ หรือ Launcher state เป็น `AUTHENTICATED` **ไม่ใช่** หลักฐานว่า ProcessMode เริ่มสำเร็จ

---

## 2. Security authority ที่ใช้

ระบบ authorization ที่ต้องใช้คือ **Backend-issued, short-lived, one-use RS256 JWT launch permit** ผูกกับ **Core-generated cryptographic challenge** และ **SHA-256 ของ canonical start configuration**

### Root of trust

| Component | หน้าที่ | สิ่งที่ห้ามเชื่อเป็น authorization เดี่ยว ๆ |
|---|---|---|
| Backend | authority ของ account, product, license, installation และ launcher session; เซ็น permit | client-supplied user/license/authorized state |
| Launcher | ตรวจ local preconditions และประสาน challenge/permit/start | state ภายใน Launcher, process identity, raw session ID |
| Core | สร้าง challenge, verify permit และบังคับ gate ก่อน engine start | Launcher PID/path, Windows user, unsigned JSON, process name อย่างเดียว |
| Proxy Server | บังคับ proxy access material ที่ expire/revoke ได้ | static reusable password ใน bundle |

### Permit policy ที่ Launcher ต้องรองรับ

- Algorithm: exact `RS256`
- Header: exact `typ=JWT`, `alg=RS256`, known `kid`
- Recommended TTL: 30 วินาที
- Hard maximum lifetime: 60 วินาที
- Allowed clock skew: ไม่เกินประมาณ 5 วินาที
- One permit ต่อ one Core challenge และ one start configuration
- Core consume authorization attempt ครั้งแรกเสมอ ไม่ว่าผล verify จะผ่านหรือไม่
- Retry ต้องเริ่มใหม่จากการขอ challenge ใหม่และขอ permit ใหม่

Launcher ไม่ต้องและไม่ควร verify permit เพื่อใช้ตัดสิน start แทน Core จะ decode เพื่อ debug ก็ไม่ได้ เพราะเสี่ยงทำ claim/token หลุด log การ verify ที่มีผลด้าน security ต้องเกิดใน Core

---

## 3. ลำดับการเริ่ม Core ที่ Launcher ต้องทำ

### 3.1 Pre-target state

Launcher ทำ authentication, entitlement/session orchestration และ heartbeat ได้ตามปกติ แต่ต้องยังไม่ทำสิ่งต่อไปนี้:

- ห้าม spawn Core host
- ห้ามเริ่ม proxy helper
- ห้าม activate driver/network path
- ห้ามขอ launch permit ล่วงหน้า

Launcher ต้องเฝ้ารอ exact `pso2.exe` แบบ event-based หรือ bounded detection flow ห้ามเปลี่ยนเป็น polling loop ที่ไม่มี timeout/cancellation

### 3.2 Local Launcher checks

เมื่อพบ target แล้ว Launcher ต้องตรวจ local state ก่อน spawn Core:

1. process name canonical เท่ากับ `pso2.exe`
2. authenticated session ยังมี access token ใช้งานได้
3. product/entitlement state ที่ Launcher รู้จักไม่ inactive
4. installation identity/hash พร้อมและตรง schema
5. มี claimed launcher `sessionId`
6. heartbeat ล่าสุดสำเร็จและยังไม่ stale ตาม policy
7. selected configuration เป็น opaque references ที่ allow-list ฝั่ง client รู้จัก เช่น `profile-0`, `server-0`
8. ไม่มี start flow อื่นกำลังทำงานหรือ Core instance ที่ Launcher เป็นเจ้าของกำลัง Running

Local checks เหล่านี้เป็น fail-fast UX เท่านั้น Backend และ Core ต้องตรวจส่วนที่เกี่ยวข้องซ้ำ ห้ามถือว่า local checks เป็น security proof

### 3.3 Spawn Core host

หลัง target detection และ local checks ผ่านแล้ว:

- spawn production Core executable โดย **ไม่มี permit/token/credential ใน argv หรือ environment**
- ใช้ executable path ที่ติดตั้งและตรวจ integrity/code-signing ตาม release policy
- ห้ามใช้ shell command string; ใช้ argument list ที่คงที่
- Launcher เก็บ ownership handle/PID ไว้สำหรับ bounded cleanup เท่านั้น
- การ spawn Core ยังต้องไม่มี runtime/driver/network side effect
- รอ named pipe readiness แบบ bounded timeout
- pipe ต้องเป็น current-user-only และมี bounded frame size

ชื่อ executable, named pipe, mutex และ timeout จริงต้อง freeze ร่วมกับ Core ก่อน integration ห้าม Launcher hard-codeค่าชั่วคราวจากเอกสารนี้

### 3.4 Request Core challenge

Launcher ส่งคำสั่ง `challenge` ผ่าน pipe หลัง Core พร้อมรับ control message แล้ว Core ต้องตอบ challenge ใหม่ที่:

- สุ่มอย่างน้อย 256 bits ด้วย cryptographic RNG
- base64url แบบไม่มี padding
- ความยาวและ schema ถูกจำกัด
- เก็บใน memory ของ Core เท่านั้น
- อายุไม่เกิน 30 วินาทีด้วย monotonic deadline
- ใช้ได้กับ Core process/start attempt ปัจจุบันเท่านั้น

Launcher ต้องเก็บ challenge ใน memory ชั่วคราวและห้าม log/persist แม้ challenge ไม่ใช่ credential โดยตัวมันเอง

### 3.5 Request permit from Backend

Launcher เรียก authenticated Backend permit issuance channel ผ่าน TLS โดยใช้ Supabase bearer access token ใน HTTP authorization header ตาม SDK/gateway ที่อนุมัติ

Sanitized request contract:

```json
{
  "sessionId": "<launcher-session-uuid>",
  "installationKeyHash": "<64-lowercase-hex>",
  "challenge": "<core-generated-base64url>",
  "command": {
    "protocolVersion": 2,
    "processName": "pso2.exe",
    "profileReference": "profile-0",
    "serverReference": "server-0"
  }
}
```

Launcher **ห้ามส่ง** field ต่อไปนี้เพื่อให้ Backend เชื่อเป็นความจริง:

- `userId`
- role/admin flag
- `authorized=true`
- license/entitlement status
- permit claims ที่ client สร้างเอง
- proxy credential หรือ server URI จริง

Backend ต้อง resolve authenticated user จาก bearer token และ resolve license/installation/session relationships จาก server-side rows เท่านั้น

Backend success response ควรเป็น bounded object ที่มี permit เพียงตัวเดียว เช่น:

```json
{
  "permit": "<compact-signed-jwt>"
}
```

ชื่อ endpoint, response envelope และ maximum HTTP body size เป็น **TBD ร่วมกับ Backend** แต่ semantics ด้าน authorization ในเอกสารนี้เป็นข้อบังคับ

### 3.6 Send authorized start to Core

Launcher ส่ง `start` frame protocol v2 ผ่าน pipe เดิม โดย permit อยู่ใน message body เท่านั้น:

```json
{
  "version": 2,
  "command": "start",
  "correlationId": "launcher-001",
  "processName": "pso2.exe",
  "profileReference": "profile-0",
  "serverReference": "server-0",
  "permit": "<compact-signed-jwt>"
}
```

กฎของ Launcher:

- ใช้ permit ภายใน memory และส่งครั้งเดียว
- ห้าม retry `start` frame เดิมเมื่อ timeout หรือ pipe disconnect เพราะไม่รู้ว่า Core consume challenge แล้วหรือยัง
- retry ใหม่ต้อง stop/resolve attempt เดิมตาม state แล้วขอ challenge + permit ใหม่
- correlation ID ต้องเป็น opaque non-secret identifier และห้ามใช้ account/session/license/token เป็นค่า
- frame ต้องไม่เกิน maximum ที่ Core freeze ไว้; checkpoint ปัจจุบันใช้ 8 KiB แต่ protocol v2 maximum ต้องยืนยันร่วมกัน

### 3.7 Wait for typed readiness

Launcher ต้องรอ typed response ที่ correlation ID ตรงกัน เช่น:

```json
{
  "version": 2,
  "kind": "result",
  "correlationId": "launcher-001",
  "status": "Running",
  "succeeded": true
}
```

เริ่ม gameplay/proxy lifecycle สำเร็จได้เมื่อครบทุกข้อ:

- response parse ผ่าน bounded schema
- protocol version ตรงกัน
- `kind=result`
- correlation ID ตรงกับ request
- `succeeded=true`
- `status=Running`
- ไม่มี `errorCode`

หาก Core process ยังอยู่แต่ไม่ได้ `Running` ภายใน timeout ให้ถือว่า start ล้มเหลวและทำ bounded cleanup ห้าม infer readiness จาก `Popen`, pipe connection, PID หรือ status `Starting`

---

## 4. สิ่งที่แต่ละ component ต้องตรวจ

### 4.1 Launcher ตรวจ

- exact target process detection ก่อน spawn Core
- local auth/session/entitlement/install state เพื่อ fail-fast
- heartbeat สำเร็จและไม่ stale ก่อนขอ permit
- opaque configuration references และ protocol schema
- Core executable path/integrity ตาม release policy
- single in-flight start orchestration
- bounded pipe/connect/request/readiness timeouts
- correlation ID ของ response
- typed `Running` readiness
- target exit, Launcher exit และ failure cleanup
- permit ไม่ปรากฏใน argv/env/disk/log/telemetry/crash report

### 4.2 Backend ตรวจและเป็น authority

- bearer access token valid และมี authenticated user
- account/profile active
- product active
- license เป็นของ user เดียวกัน, active, started และไม่ expired/revoked/suspended
- installation เป็นของ user เดียวกันและไม่ revoked
- launcher session เป็นของ user เดียวกันและไม่ revoked/taken-over
- session เชื่อม installation และ license แถวเดียวกับที่ตรวจ
- heartbeat สด แนะนำไม่เกิน 60 วินาที
- requested configuration อยู่ใน server-side allow-list/product policy
- challenge/config/request schema และขนาดถูกต้อง
- signing key พร้อม; ถ้าไม่พร้อมต้อง fail closed
- ออก permit ที่มี claims/header/TTL ตรง contract เท่านั้น

### 4.3 Core ตรวจ

- bounded protocol v2 frame และ mandatory permit
- compact JWT size/shape ก่อน crypto processing
- exact known `kid`, exact `alg=RS256`, valid signature
- exact `iss`, `aud`, `scope=proxy:start`, product
- required UUID/string/time claims และไม่มี duplicate claims
- `iat`, `nbf`, `exp`, skew และ `exp-iat <= 60s`
- constant-time challenge comparison กับ outstanding challenge
- canonical configuration hash ตรง `cfg`
- challenge ยังไม่หมดอายุและยังไม่ถูก consume
- consume attempt แบบ atomic ก่อนออกจาก authorization path
- opaque start configuration valid
- target `pso2.exe` ยังทำงานก่อน engine start
- concurrent/repeated start ไม่ทำให้เกิด runtime ซ้ำ

Core ต้องทำ checks เหล่านี้ก่อน mode controller/engine/driver/helper/network side effects ทุกชนิด

---

## 5. Canonical configuration binding

Launcher และ Backend ต้องสร้าง command object เดียวกัน แต่ Core และ Backend เป็นผู้คำนวณ/ตรวจ security hash ตาม serialization ที่ freeze ร่วมกัน

Canonical text draft:

```text
protocolVersion=2\n
processName=pso2.exe\n
profileReference=profile-0\n
serverReference=server-0\n
```

กฎ:

- UTF-8 ไม่มี BOM
- key order ตายตัวตามตัวอย่าง
- line ending เป็น LF (`\n`) ทุกบรรทัด รวมบรรทัดสุดท้าย
- `processName` normalize เป็น lowercase canonical `pso2.exe`
- opaque references ห้าม trim/normalize หลัง validation; ต้องส่งค่าที่ canonical แล้ว
- `cfg` เป็น lowercase hex SHA-256 หรือ encoding อื่นที่ Security freeze เพียงแบบเดียว

ทีม Launcher ต้องเตรียม shared fixture loader/test แต่ไม่ต้องสร้าง permit เอง Shared fixtures ขั้นสุดท้ายต้องมาจาก Backend/Core และมี canonical text + expected hash + public signature vectors ที่ไม่มี credential จริง

---

## 6. Required JWT claims ที่ Launcher ต้องส่งผ่านโดยไม่แก้ไข

Core คาดว่า permit มี claims อย่างน้อย:

| Claim | Binding |
|---|---|
| `iss` | trusted Backend issuer |
| `aud` | exact Core launch audience |
| `sub` | authenticated user UUID |
| `sid` | launcher session UUID |
| `iid` | installation row UUID |
| `lid` | license row UUID |
| `product` | exact product code |
| `scope` | exact `proxy:start` |
| `cfg` | hash ของ canonical configuration |
| `challenge` | Core one-use challenge |
| `jti` | random token ID อย่างน้อย 128 bits |
| `iat` | issued-at |
| `nbf` | not-before |
| `exp` | expiry |

Launcher adapter ต้องถือ permit เป็น opaque string: ห้ามแก้, re-sign, refresh, merge claims หรือเปลี่ยน encoding

---

## 7. Adapter interface ที่ Launcher ควรเตรียม

Launcher Python layer ควรแยก abstraction อย่างน้อยดังนี้ ชื่อจริงปรับตาม convention ของ repository ได้:

```text
CoreProcessAdapter
  start_host_without_secrets() -> OwnedCoreProcess
  wait_for_control_channel(timeout) -> None
  stop_gracefully(timeout) -> StopResult
  kill_owned_process_after_timeout() -> None

CoreControlChannel
  request_challenge(correlation_id, timeout) -> CoreChallenge
  start_authorized(command, permit, correlation_id, timeout) -> CoreResult
  get_status(correlation_id, timeout) -> CoreStatus
  stop(correlation_id, timeout) -> CoreResult

LaunchPermitGateway
  issue_launch_permit(session_id, installation_key_hash, challenge, command) -> OpaquePermit

ProcessTargetDetector
  wait_for_exact_pso2(timeout, cancellation) -> TargetProcess
  is_same_target_still_running(target) -> bool

AuthorizedCoreOrchestrator
  wait target → local checks → spawn Core → challenge → Backend permit
  → Core start → wait typed Running → monitor → bounded cleanup
```

ข้อบังคับด้าน adapter design:

- `LaunchPermitGateway` รับ bearer token จาก existing authenticated HTTP infrastructure ห้ามส่ง tokenเข้า method logs/repr
- `OpaquePermit` ควรเป็น redacted/sensitive type ที่ `repr`/exception ไม่แสดงค่า
- `CoreControlChannel` ต้อง serialize permit ตรงลง pipe buffer ห้ามเขียน temporary file
- process adapter ห้ามรับ permit/access token/proxy credential เป็น parameter
- orchestration ต้องรองรับ cancellation และ bounded timeout ทุก network/IPC/process wait
- มี lock/state machine ป้องกัน duplicate start
- dependency boundaries ต้อง mock/fake ได้สำหรับ unauthorized and cleanup tests

---

## 8. Launcher state machine ที่แนะนำ

```text
Idle
  → WaitingForTarget
  → LocalPreconditionsValidated
  → CoreStarting
  → ControlChannelReady
  → ChallengeReceived
  → PermitRequested
  → StartSubmitted
  → Running
  → Stopping
  → Idle
```

ทุก transition failure ก่อน `Running` ต้องไป:

```text
Failed → bounded graceful stop → owned-process kill fallback → Idle/Error
```

ข้อจำกัดสำคัญ:

- target หายก่อนส่ง `start`: ยกเลิก flow, ไม่ขอ/ไม่ใช้ permit และ stop Core
- target หายหลังขอ permitแต่ก่อน `Running`: ส่ง start เดิมซ้ำไม่ได้; cleanup
- Backend timeout/failure: fail closed และ stop Core
- Core timeout/disconnect หลังส่ง start: ห้าม retry permit เดิม; query typed status ได้เฉพาะ contract ที่ Core อนุมัติ มิฉะนั้น cleanup แล้วเริ่ม attempt ใหม่
- Launcher shutdown: graceful stop ก่อน แล้ว kill เฉพาะ Core process ที่ Launcher เป็นเจ้าของหลัง timeout
- target exit ขณะ Running: Core ต้องหยุด runtimeเอง และ Launcher monitor เพื่อยืนยัน cleanup

---

## 9. Typed errors ที่ Launcher ต้องรองรับ

| Error code | Launcher behavior |
|---|---|
| `AuthorizationRequired` | อย่า retry start เดิม; ขอ challenge/permit ใหม่เมื่อ preconditions พร้อม |
| `AuthorizationInvalid` | fail closed; ไม่แสดง claim detail; บันทึกเฉพาะ code |
| `AuthorizationExpired` | ขอ challengeและ permit ใหม่ทั้งชุด |
| `AuthorizationReplay` | ถือว่า attempt ถูก consume; cleanup และเริ่มใหม่ทั้งชุด |
| `AuthorizationUnavailable` | Backend/key/verification unavailable; fail closed พร้อม retry policy แบบ bounded |
| `SessionInactive` | กลับไป session claim/auth UX; ห้ามเริ่ม Core ต่อ |
| `ProcessNotFound` | กลับ `WaitingForTarget`; Core/proxy ต้องไม่ Running |
| `ProcessExited` | cleanup และรอ target attempt ใหม่ |
| `AlreadyRunning` | reconcile typed status; ห้าม spawn Core/runtime ซ้ำ |
| `Timeout` / `Cancelled` / start-stop errors | bounded cleanup; ห้าม reuse permit |

Wire response ต้องไม่มี exception message, token, claims, user/session/license/installation ID หรือ proxy detail Launcher ควร map error code เป็น user-facing message ที่ sanitized

---

## 10. Secret-handling requirements

Permit, bearer token และ proxy access material ห้ามอยู่ใน:

- process argv หรือ command line string
- environment variable ที่ส่งเข้า Core
- temporary/config/cache file
- Python `repr`, exception, traceback context หรือ dataclass dump
- structured log fields
- telemetry, correlation ID หรือ analytics event
- clipboard
- crash report/minidump annotation
- test snapshot/fixture/report

Launcher ต้องมี redaction tests โดยใช้ sentinel token และตรวจ log/temp/output แบบไม่พิมพ์ค่าจริง การลบ permit reference จาก memory หลังส่งเป็น hygiene ที่ควรทำ แต่ห้ามอ้างว่าสามารถรับประกัน memory erasure ใน Python ได้

Proxy credential เป็น boundary แยกจาก launch permit Launcher ต้องไม่ bundle static reusable Shadowsocks credential และต้องเตรียมรับ per-session/short-lived proxy access material ผ่านช่องทางที่ Security อนุมัติในภายหลัง

---

## 11. Continuous authorization

Launch permit อนุญาต start event เพียงครั้งเดียว ยังไม่พิสูจน์ว่า revoked session จะหยุด Core ที่ Running ทันที

Launcher ต้องเตรียม adapter seam สำหรับ renewal/revocation policy แต่ยังห้าม invent protocol ก่อน Security freeze:

```text
RuntimeAuthorizationMonitor
  renew_or_validate(runtime_binding, challenge, cancellation) -> RenewalDecision
```

สถานะปัจจุบัน:

- minimum: ทุก start ต้อง online-authorized, Core หยุดเมื่อ `pso2.exe` ปิด
- recommended: signed short-interval renewal ที่ Core ตรวจและ fail closed หลัง bounded grace period
- renewal interval, grace period, runtime-binding claims และ revocation SLA: **TBD by Backend/Security**

Launcher heartbeat อย่างเดียวไม่ใช่ continuous authority เพราะ modified Launcher สามารถข้าม heartbeat flow ได้

---

## 12. Integration tests ที่ทีม Launcher ต้องเตรียม

### Target and sequencing

- ไม่มี `pso2.exe`: Core process/proxy/helper/driver activation count เป็นศูนย์
- detector timeout/failure: fail closed
- พบ target แล้ว target หายกลาง flow: permit/start ไม่ถูก reuse และ cleanup สำเร็จ
- repeated target event: ไม่เกิด Core/runtime ซ้ำ

### Authorization

- ไม่มี challenge: ไม่เรียก Backend permit issuance
- Backend unauthenticated/timeout/error: ไม่ส่ง Core start
- missing/empty permit: fail closed
- expired/invalid/replayed permit: typed error และ engine start count 0
- valid permitแต่ config ถูกเปลี่ยน: `AuthorizationInvalid`, engine start count 0
- valid permitแต่ไม่มี target: `ProcessNotFound`, engine start count 0
- retry ขอ challengeและ permit ใหม่ทุกครั้ง

### Transport and secrecy

- permit sentinel ไม่อยู่ใน argv/environment/log/temp/telemetry/error
- oversized/malformed frames ถูก reject
- pipe disconnect/partial frame/timeout ทำ bounded cleanup
- response correlation mismatch ถูก reject
- `Popen` success ไม่ถูกตีความเป็น `Running`

### Lifecycle

- valid authorized flow ได้ typed `Running`
- target exit ทำ bounded runtime/Core cleanup ตาม policy
- Launcher exit ทำ graceful stop แล้ว owned-process kill fallback เท่านั้น
- Core crash ไม่มี orphan helper/pipe/mutex/controller/temp state

ทีม Launcher และ Core ต้องใช้ cross-repository JSON/canonical-hash/signature fixtures ชุดเดียวกันเมื่อ protocol v2 freeze แล้ว

---

## 13. Integration readiness checklist

ทีม Launcher ควรเตรียมให้ครบก่อนประกอบจริง:

- [ ] exact `pso2.exe` detector และ cancellation/timeout
- [ ] local precondition service สำหรับ auth/entitlement/install/session/heartbeat
- [ ] owned Core process adapter ที่ spawn โดยไม่มี secrets
- [ ] bounded current-user pipe transport abstraction
- [ ] challenge request/response model สำหรับ protocol v2
- [ ] authenticated Backend permit gateway
- [ ] opaque/redacted permit type
- [ ] authorized start request และ typed result model
- [ ] correlation validation และ `Running` readiness gate
- [ ] single-flight state machine
- [ ] bounded graceful stop + owned-process kill fallback
- [ ] token/permit leak tests
- [ ] cross-repository fixture test hook
- [ ] renewal seam โดยยังไม่ hard-code policy

ค่าที่ต้องรอ freeze ก่อน hard-code:

- [ ] production Core executable name/path policy
- [ ] named pipe and mutex names
- [ ] protocol v2 exact JSON schema และ frame maximum
- [ ] Backend permit endpoint/response envelope/rate limits
- [ ] trusted issuer, audience, product และ key IDs
- [ ] canonical `cfg` encoding fixtures
- [ ] proxy short-lived access material contract
- [ ] continuous renewal/revocation SLA

---

## 14. สถานะ implementation ปัจจุบันของ NekoProxyCore

ณ วันที่เอกสารนี้จัดทำ:

- Core มี `IProxyStartAuthorizer` seam ที่ innermost `HeadlessRuntimeCoordinator.StartAsync`
- default Core path ใช้ `AuthorizationRequiredStartAuthorizer` และ fail closed
- missing authorization คืน typed `AuthorizationRequired`
- focused test ยืนยัน authorization failure แล้ว engine start count เป็นศูนย์
- typed authorization error taxonomy เริ่มเพิ่มแล้ว
- Core มี challenge primitive/lifecycle แล้ว: 256-bit cryptographic randomness, base64url,
  monotonic expiryไม่เกิน 30 วินาที, one outstanding challenge, atomic one-attempt
  consumption, replay rejection และ concurrency tests
- **ยังไม่มี** protocol endpoint ที่ Launcher ใช้ขอ challenge
- **ยังไม่มี** RS256 JWT verifier/public key ring
- **ยังไม่มี** protocol v2 `challenge`/mandatory `permit` frame
- Host protocol ปัจจุบันยังเป็น checkpoint version 1 และไม่ใช่ production integration contract
- production host/named pipe executable ยังไม่ freeze
- generic Core start/stop failures map เป็น allow-listed typed message และไม่ส่ง raw
  runtime exception detail ออกนอก boundary
- Backend permit issuance และ proxy short-lived credential ยังไม่ implemented/evidenced ใน repository นี้

สถานะ Launcher หลังทำ S1 scaffolding:

- มี `AuthorizedCoreOrchestrator` และ protocol interfaces สำหรับ process/channel/permit/detector
  โดยยังไม่กำหนด wire schema, endpoint, pipe name หรือ production timeout ที่ S0 ยังไม่ freeze
- `OpaquePermit` ปิดค่าใน `str`/`repr`; permit เปิดค่าได้เฉพาะ direct transport boundary
- มี exact `pso2.exe` target identity detector แบบ bounded/cancellable และตรวจ PID เดิมซ้ำ
- orchestration เป็น single-flight, ตรวจ target ซ้ำก่อนส่ง start, ต้องได้ typed `Running`
  เท่านั้น และ cleanup แบบ graceful-stop/owned-process kill fallback
- `ApplicationController` ปฏิเสธ start ก่อนตรวจพบ `pso2.exe` แม้ auth/session ผ่านแล้ว
- production composition ไม่ใช้ legacy `ProxyProcessManager`; ระหว่าง S0 ยังไม่ freeze จะใช้
  fail-closed gateway และไม่ spawn Core
- adapter scaffolding ยัง **ไม่ถูก wire production** เพราะ Backend permit issuance และ protocol v2
  contract ยังไม่มี approved revision/fixtures

ดังนั้นทีม Launcher สามารถเตรียม interfaces, state machine, sensitive-data handling และ test harness ตามเอกสารนี้ได้ แต่ **ห้ามเชื่อม production หรือสร้าง fallback ที่ bypass permit** ระหว่างรอ Core/Backend contract สมบูรณ์

---

## 15. Definition of ready-to-integrate

เริ่ม cross-repository integration ได้เมื่อมีหลักฐานครบอย่างน้อย:

1. Backend freeze permit endpoint และ authority validation contract
2. Security freeze JWT claims, issuer/audience/product, TTL/skew และ key rotation
3. Core freeze protocol v2 challenge/start schemas, pipe identity และ frame limits
4. Backend/Core publish canonical hash + RS256 signature fixtures
5. Core tests ยืนยันทุก authorization failure มี engine start count 0
6. Launcher adapter tests ยืนยันไม่มี Core start ก่อน `pso2.exe` และไม่มี permit leak
7. ทั้งสอง repository ผ่าน cross-language fixtures เดียวกัน
8. continuous authorization และ proxy credential architecture มี documented decision

จนกว่าจะครบ เงื่อนไข Step E ยังคงเป็น **BLOCKED/PARTIAL** และ production release ยังเป็น **NOT GRANTED**

---

## 16. แผนงานความปลอดภัยร่วมสำหรับ Core และ Launcher

ส่วนนี้เป็นลำดับงาน source of truth สำหรับทั้งสองทีม ห้ามสลับลำดับจนเกิด implementation ที่อ้าง schema หรือ security policy ที่ยังไม่ freeze

### Phase S0 — Contract and security freeze

**ทำร่วมกัน: Core + Launcher + Backend + Security**

ต้องตกลงและบันทึกค่าต่อไปนี้ก่อนเขียน production protocol:

- protocol version เป็น `2`
- exact challenge request/response schema
- exact authorized start request/response schema
- JSON field names, casing, required/optional fields และ unknown-field policy
- maximum pipe frame, JWT และ Backend request/response sizes
- canonical configuration serialization และ expected SHA-256 encoding
- exact JWT algorithm, header, claims, issuer, audience, product, scope, TTL และ skew
- challenge lifetime, consume semantics และ concurrent-attempt policy
- key IDs, public-key distribution และ rotation procedure
- Core executable identity, pipe identity, mutex identity และ connect/readiness timeouts
- Backend endpoint semantics, HTTP error mapping และ rate limits
- continuous renewal/revocation SLA
- short-lived proxy access material architecture

**Deliverables:**

- sanitized protocol v2 schema
- canonical configuration fixture
- positive/negative JWT signature vectorsโดยใช้ test key เท่านั้น
- typed error mapping table
- threat-model approval จาก Security

**Exit gate:** ทุกทีม sign off contract revision เดียวกัน ห้ามมีค่าที่ security-critical ระบุเป็น TBD ก่อนเริ่ม Phase S2/S3

### Phase S1 — Parallel adapter scaffolding without production bypass

Phase นี้ Core และ Launcher ทำคู่ขนานได้หลัง S0 ส่วนที่เกี่ยวข้อง freeze แล้ว

#### Core team

- คง `IProxyStartAuthorizer` ที่ innermost runtime start seam
- คง default path เป็น `AuthorizationRequired`; ห้ามเพิ่ม allow-all/offline fallback
- แยก interfaces สำหรับ challenge store, permit verifier, key resolver และ monotonic clock
- เตรียม typed authorization results ที่ไม่มี raw validation detail
- เพิ่ม test seam สำหรับ engine-start count และ alternate entry-point bypass

#### Launcher team

- สร้าง `CoreProcessAdapter`, `CoreControlChannel`, `LaunchPermitGateway` และ orchestrator interfaces
- สร้าง sensitive `OpaquePermit` type ที่ redacted ใน `repr`/log/error
- สร้าง exact `pso2.exe` detector พร้อม cancellation และ bounded timeout
- สร้าง single-flight lifecycle state machine
- สร้าง graceful-stop และ owned-process kill fallback
- ใช้ fake transport/Backend สำหรับ tests เท่านั้น ห้ามเพิ่ม production fake permit หรือ local signing

**Exit gate:** ทั้งสองทีม build/test ผ่านใน repository ตนเอง และไม่มี code path production ที่ bypass permit

### Phase S2 — Core challenge and verifier

**เจ้าของหลัก: Core team; reviewers: Security + Backend**

ทำตาม vertical security slices:

1. cryptographic challenge generation อย่างน้อย 256 bits
2. base64url validation และ bounded representation
3. monotonic expiry ไม่เกิน 30 วินาที
4. atomic one-attempt consumption รวม failure path
5. canonical configuration hashing
6. exact `kid` public-key resolver โดย unknown key ต้อง reject
7. strict RS256 signature verification
8. required claims/duplicate claims/type/UUID/time validation
9. constant-time challenge/config comparisons
10. verifier placement ก่อน controller/engine/driver/network side effects

ทุก slice ต้องเริ่มด้วย failing test และยืนยันว่า failure มี engine start count เป็นศูนย์

**Exit gate:** Core authorization negative matrix ผ่านครบ รวม malformed, wrong algorithm, unknown key, expiry, replay, wrong challenge/config และ concurrent double-use

### Phase S3 — Backend permit authority

**เจ้าของหลัก: Backend team; reviewers: Security + Core**

- สร้าง authenticated permit issuance endpoint/RPC
- resolve user จาก bearer token เท่านั้น
- ตรวจ account/product/license/installation/session/heartbeat/configuration ฝั่ง server
- ออก permit ด้วย private key ใน approved secret custody เท่านั้น
- enforce TTL/header/claims ตาม frozen fixtures
- fail closed เมื่อ signer/database/authority dependency ไม่พร้อม
- rate-limit และบันทึกเฉพาะ sanitized outcome/key ID/aggregate metrics
- ออก short-lived proxy access material หรือเชื่อม server-side enforcement ตาม architecture ที่อนุมัติ

**Exit gate:** Backend negative matrix ผ่าน และ Core verify Backend-generated test-environment permit ได้จาก cross-language fixtures โดย private keyไม่เข้าฝั่ง client

### Phase S4 — Protocol v2 and production Core host

**เจ้าของหลัก: Core team; consumer reviewer: Launcher team**

- เพิ่ม bounded `challenge`, `start`, `status`, `stop` frames
- บังคับ mandatory permit ใน `start`
- reject protocol v1 start ใน production host
- ใช้ `CurrentUserOnly` named pipe เป็น transport isolation เพิ่มเติม
- ทำ single-instance lease และ deterministic cleanup
- production host ต้องเป็น headless `WinExe`, x64 และไม่มี console/form/tray/notification
- response ต้องมี allow-listed typed fields เท่านั้น
- freeze artifact path/name/hash manifest สำหรับ Launcher

**Exit gate:** runnable production host พร้อม artifact manifest; unauthorized pipe client เริ่ม engine ไม่ได้ และ permit sentinelไม่หลุด response/log/temp/crash artifacts

### Phase S5 — Launcher production wiring

**เจ้าของหลัก: Launcher team; reviewers: Core + Backend**

Launcher ต่อ flow จริงตามลำดับ:

```text
wait exact pso2.exe
→ local preconditions
→ spawn Core without secrets
→ wait bounded pipe readiness
→ request challenge
→ request online Backend permit
→ send authorized start once
→ wait typed Running
→ monitor target/session/runtime
→ bounded stop and cleanup
```

ข้อบังคับ:

- ไม่มี Core spawn ก่อน target detection
- ไม่มี permit request ก่อน Core challenge
- ไม่มี start เมื่อ Backend fail/timeout
- ไม่ reuse challenge/permit หลัง timeout, disconnect หรือ typed failure
- ไม่ infer readiness จาก process/PID/pipe/`Popen`
- ไม่มี token/permit/proxy material ใน argv/env/disk/log/telemetry

**Exit gate:** Launcher contract/security tests ผ่าน และใช้ production adapter path เดียวกับที่จะ ship

### Phase S6 — Cross-repository integration gate

**ทำร่วมกัน: Core + Launcher + Backend + QA**

รันจาก clean integration artifacts และ approved environment:

1. no target → no Core/proxy/driver activation
2. target present, no permit → engine start count 0
3. invalid/expired/replayed/config-mismatched permit → engine start count 0
4. valid permit, target absent at final Core check → engine start count 0
5. valid target + valid authorization → exactly one Core/runtime และ typed `Running`
6. gameplay traffic path และ sanitized server-side correlation ผ่าน
7. target exit, Launcher exit, Backend/session revocation policy และ Core crash cleanup ผ่าน
8. no orphan process/helper/pipe/mutex/controller/temp state
9. extracted release bundleไม่มี static reusable proxy credential หรือ server ปฏิเสธ direct reuse ตาม policy
10. permit/token sentinel absent จาก artifacts ทั้งหมด

**Exit gate:** QA ออกรายงาน PASS/FAIL/BLOCKED แบบ sanitized และ Security ลงนาม residual-risk statement

---

## 17. Ownership matrix และ dependency ระหว่างทีม

| Work item | Core | Launcher | Backend | Security/QA | Dependency |
|---|---|---|---|---|---|
| Protocol v2 schema | Owner | Consumer approver | Reviewer | Security approver | S0 |
| Exact target activation | Final recheck | Primary detector | — | QA | ทำคู่ขนานได้ |
| Challenge lifecycle | Owner | Transport consumer | Receives binding | Reviewer | Schema freeze |
| Permit issuance | Verifier consumer | Authenticated caller | Owner | Key/policy approver | Claims freeze |
| RS256 verification | Owner | Opaque forwarder | Fixture producer | Reviewer | Test keys/fixtures |
| Canonical config hash | Verifier | Exact command producer | Permit binding | Approver | Canonical fixture |
| Pipe/process lifecycle | Host owner | Client owner | — | QA | Host identity freeze |
| Secret handling | No token output | No token persistence | No secret response/log | Audit owner | ทุก phase |
| Proxy access enforcement | In-memory consumer | Must not bundle static secret | Material authority | Architecture approver | Server decision |
| Renewal/revocation | Core enforcement | Orchestration signal | Authority | SLA approver | Policy freeze |
| Real E2E gate | Artifact owner | Flow owner | Environment authority | Test/sign-off owner | S2–S5 complete |

หาก owner ฝั่งหนึ่งเปลี่ยน contract ต้องอัปเดต shared fixture revision และให้ consumer tests fail ก่อน merge ห้ามเปลี่ยน schema แบบ silent compatibility fallback

---

## 18. Shared artifact package สำหรับประกอบสองทีม

ก่อนเริ่ม integration ให้จัด sanitized package ที่ version-control ได้และมีอย่างน้อย:

```text
security-contract/
  protocol-v2.schema.json
  permit-issuance-request.schema.json
  permit-issuance-response.schema.json
  canonical-config.txt
  canonical-config.sha256
  jwt-positive-vectors.json
  jwt-negative-vectors.json
  typed-errors.json
  artifact-manifest.schema.json
  README.md
```

กฎของ package:

- ใช้ dedicated test key pair; commit ได้เฉพาะ public test key และ vectors ที่ Security อนุมัติ
- ห้ามมี production private key, bearer token, proxy credential, endpoint หรือ customer data
- ทุก fixture มี contract revision/hash
- Core และ Launcher CI ต้อง validate revision/hash เดียวกัน
- Backend CI ต้องสร้าง output ที่ผ่าน positive vectors และถูก rejectตาม negative vectors
- schema change ต้องผ่าน review จาก owner/consumer/Security และเพิ่ม migration note

---

## 19. Merge gates แยกตาม repository

### Core merge gate

- [ ] default unauthorized start fail closed
- [ ] challenge random/expiry/one-use tests ผ่าน
- [ ] strict RS256/header/claims/time/config verifier tests ผ่าน
- [ ] authorization failure matrix มี engine start count 0
- [ ] alternate runtime entry point bypass ไม่ได้
- [ ] protocol v2 bounded-frame tests ผ่าน
- [ ] secret sentinel scan ผ่าน
- [ ] production host build/publish smoke ผ่าน

### Launcher merge gate

- [ ] no Core spawn before exact `pso2.exe`
- [ ] no permit request without fresh challenge
- [ ] Backend failure/timeout fail closed
- [ ] no challenge/permit reuse
- [ ] typed `Running` เป็น readiness condition เดียว
- [ ] duplicate start ถูก single-flight block
- [ ] bounded stop/kill cleanup ผ่าน
- [ ] argv/env/log/temp/telemetry sentinel scan ผ่าน
- [ ] shared fixtures ผ่าน revision เดียวกับ Core

### Integration branch gate

- [ ] Core artifact identity/hash ถูก verify โดย Launcher packaging
- [ ] Backend permit ถูก Core verify ได้จริง
- [ ] authorized และ unauthorized E2E ผ่าน
- [ ] package extraction/direct proxy access gate ผ่าน
- [ ] continuous authorization/revocation case ผ่านตาม SLA
- [ ] ไม่มี secret ใน report/artifacts

---

## 20. สิ่งที่ห้ามทำระหว่างพัฒนา

- ห้ามสร้าง `allowAll`, `skipAuthorization`, offline permit หรือ environment/debug flag ใน production build
- ห้ามให้ Launcher sign permit หรือฝัง shared signing secret
- ห้ามใช้ raw `sessionId`, installation hash, process name, parent PID หรือ same-user pipe เป็น authorization proof
- ห้าม spawn Core รอไว้ก่อน `pso2.exe` เพียงเพื่อให้ startup เร็วขึ้น
- ห้ามส่ง permitผ่าน argv/environment/file
- ห้าม retry permit/challenge เดิมเพื่อแก้ timeout
- ห้ามดาวน์โหลดและ trust unsigned JWKS/key manifest โดยอัตโนมัติ
- ห้ามบรรจุ static reusable proxy credential แล้วอ้างว่า obfuscation เป็น security
- ห้ามรายงาน unit/contract test เป็น real integration PASS
- ห้ามประกาศ production-ready ก่อน Backend, Proxy Server และ Security gates ผ่าน

---

## 21. สถานะติดตามงานร่วม ณ จุดเริ่มต้น

| Boundary | Current state | งานถัดไป | Owner |
|---|---|---|---|
| Innermost Core authorization seam | PARTIAL/VERIFIED — fail-closed ก่อน runtime side effects | wire approved challenge/verifier หลัง S0 | Core |
| Core challenge | PARTIAL/VERIFIED — primitive/lifecycle + expiry/one-use/replay/concurrency ทำแล้ว | freeze schema แล้วเพิ่ม protocol endpoint | Core |
| RS256 verifier/key ring | NOT IMPLEMENTED | freeze keys/claims แล้วทำ strict verifier | Core + Security |
| Protocol v2 host | NOT IMPLEMENTED | challenge/start/status/stop และ named pipe host | Core |
| Launcher adapter | PARTIAL/VERIFIED — interfaces, opaque permit, exact detector, single-flight orchestration และ cleanup tests ทำแล้ว; production fail closed | wire approved channel/Backend adapters หลัง S0 | Launcher |
| Backend permit authority | NOT EVIDENCED | implement server validations/signer | Backend |
| Proxy access enforcement | BLOCKED/UNVERIFIED | เลือกและ implement non-reusable access | Backend + Proxy Server |
| Continuous authorization | POLICY TBD | freeze renewal/revocation SLA | Security + Backend + Core |
| Cross-repository fixtures | NOT CREATED | publish sanitized shared package | Core + Backend + Launcher |
| Production integration | BLOCKED | ทำหลัง S0–S5 ผ่าน | All teams + QA |

คำว่า **พร้อม** ให้ใช้เฉพาะราย boundary ตามตารางนี้ ภาพรวมระบบยังคง **BLOCKED/PARTIAL** จนกว่า Phase S6 และ release security gates จะผ่านจริง
