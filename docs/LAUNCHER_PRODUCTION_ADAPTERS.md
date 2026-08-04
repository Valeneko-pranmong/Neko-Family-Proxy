# Launcher Production Adapters

**สถานะเอกสาร:** Implementation specification / handoff

**สถานะระบบ:** `DESIGN READY / IMPLEMENTATION PARTIAL / PRODUCTION BLOCKED`

**ขอบเขต:** Launcher → Backend Authorization → NekoProxyCore

**อ้างอิง contract:** `launcher-s0-proposal-01` (ยังไม่ frozen และยังไม่อนุมัติให้ต่อ production)

> เอกสารนี้อธิบาย adapter ที่ต้องมีเพื่อแทน `AuthorizationPendingProxyGateway` ใน production เท่านั้น ไม่ได้แปลว่า endpoint, protocol, key policy หรือ Core artifact ได้รับอนุมัติแล้ว ห้ามนำค่าที่ยังเป็น TBD ไปเดาหรือต่อ production เอง

## 1. สถานะปัจจุบัน

Production composition ใน `launcher/src/neko_launcher/main.py` ยังสร้าง:

```text
AuthorizationPendingProxyGateway
```

Gateway นี้ fail closed เมื่อสั่งเริ่ม Proxy และไม่มี Core, permit หรือ proxy side effect ส่วน orchestration scaffold อยู่ใน `launcher/src/neko_launcher/application/authorized_core.py` โดยมี boundary หลักแล้ว ได้แก่:

- `CoreProcessAdapter`
- `CoreControlChannel`
- `LaunchPermitGateway`
- `LaunchPrecondition`
- `ProcessTargetDetector`
- `AuthorizedCoreOrchestrator`
- `OpaquePermit`, `CoreChallenge`, `CoreStatus`
- `LaunchAccessContext`, `OpaqueStartCommand`

สิ่งที่ยังไม่มีคือ implementation production ของ process host, named-pipe channel, Backend permit issuance, production context/command composition และ runtime authorization monitor ดังนั้นการเชื่อมต่อ Proxy จริงยังถูก block โดยเจตนา

## 2. Production composition เป้าหมาย

```text
Launcher UI / ApplicationController
        |
        v
AuthorizedProxyGateway                 (facade ที่แทน AuthorizationPendingProxyGateway)
        |
        v
AuthorizedCoreOrchestrator
        |-- WindowsProcessTargetDetector
        |-- SupabaseHeartbeatLaunchPrecondition
        |-- VerifiedCoreProcessAdapter
        |-- NamedPipeCoreControlChannel
        `-- BackendLaunchPermitGateway

หลัง Running:
        |-- RuntimeAuthorizationMonitor (เมื่อ policy ถูก freeze)
        |-- target/Core/session monitoring
        `-- bounded stop/cleanup
```

ลำดับ start ที่ production ต้องใช้เพียงเส้นทางเดียว:

```text
validate opaque command + local access context
→ wait exact pso2.exe
→ fresh online heartbeat
→ recheck same target
→ verify approved Core manifest
→ spawn owned Core host without secrets
→ wait current-user control channel
→ request one Core challenge
→ request one Backend permit
→ send authorized start exactly once
→ accept only matching typed Running
→ monitor and perform bounded cleanup
```

ห้ามมี legacy/direct path ที่ข้าม challenge, permit หรือ authorization orchestrator

## 3. Adapter รายตัว

### 3.1 `AuthorizedProxyGateway` — application facade

**หน้าที่**

- implement `ProxyGateway.start()` และ `ProxyGateway.stop()` ที่ application layer ใช้อยู่
- snapshot authenticated user, entitlement, claimed Launcher session และ installation identity เพื่อสร้าง `LaunchAccessContext`
- resolve เฉพาะ `profileReference` และ `serverReference` แบบ opaque เพื่อสร้าง `OpaqueStartCommand`
- เรียก `AuthorizedCoreOrchestrator` โดยไม่สร้าง authorization flow ซ้ำเอง
- map `AuthorizedCoreErrorCode` ไปข้อความ UI ที่ allow-list แล้ว
- เก็บ cancellation handle และสถานะ owned attempt/runtime สำหรับ `stop()`

**ข้อบังคับ**

- `start()` ต้องเป็น single-flight ทั้งระดับ facade และ orchestrator
- ห้ามรับหรือ resolve raw proxy endpoint, port, cipher, password หรือ static credential
- ห้ามแสดง `str(exc)` จาก adapter, HTTP, IPC หรือ process boundary
- `stop()` ต้อง idempotent ในมุม UX แต่ต้องไม่รายงาน cleanup สำเร็จถ้า contract กำหนด typed stop failure

### 3.2 `WindowsProcessTargetDetector` — exact target identity

Implement `ProcessTargetDetector`:

```text
wait_for_exact_pso2(timeout, cancellation) -> TargetIdentity | None
is_same_target_still_running(target) -> bool
```

`TargetIdentity` ควร bind อย่างน้อย PID และ process creation time/handle เพื่อป้องกัน PID reuse และต้องตรวจ executable basename แบบ exact `pso2.exe` ตาม contract ที่อนุมัติ

**พฤติกรรมบังคับ**

- ใช้ monotonic deadline และรองรับ cancellation
- ไม่ spawn Core ระหว่างยังไม่พบ target
- recheck target เดิมหลัง heartbeat, หลัง channel ready, หลัง challenge, หลัง permit และก่อนส่ง start
- access denied, malformed process data หรือ detector exception ต้อง fail closed เป็น typed error; ห้ามถือว่า target ยังทำงาน

### 3.3 `SupabaseHeartbeatLaunchPrecondition` — fresh online gate

ใช้ `OnlineHeartbeatLaunchPrecondition` หรือ production wrapper ที่ implement `LaunchPrecondition.require_fresh(...)`:

```text
require_fresh(session_id, installation_key_hash, timeout) -> None
```

Adapter ต้องเรียก authenticated Backend/Supabase heartbeat ใหม่สำหรับ start attempt ทุกครั้ง และ Backend ต้องตรวจ session + installation binding แบบ server-side

**ข้อบังคับ**

- heartbeat success เก่าหรือ periodic grace ใช้แทน fresh probe ไม่ได้
- false, timeout, network error, malformed response และ cancellation ต้อง block Core spawn
- bearer/access token ต้องมาจาก authenticated gateway/secure session infrastructure ไม่รับผ่าน loggable argument หรือ config file
- บันทึกได้เฉพาะ sanitized outcome, duration bucket และ correlation ที่ไม่ใช่ secret

> Fresh heartbeat เป็น precondition เท่านั้น ไม่ใช่ตัวแทน launch permit และไม่ใช่ continuous authorization

### 3.4 `VerifiedCoreProcessAdapter` — artifact verification และ owned host

Implement `CoreProcessAdapter`:

```text
start_host_without_secrets() -> None
wait_for_control_channel(timeout) -> None
stop_gracefully(timeout) -> bool
kill_owned_process_after_timeout() -> None
```

**ก่อน spawn**

1. โหลด manifest ที่อนุมัติด้วย strict UTF-8 without BOM
2. ตรวจ contract revision/hash, Core version, RID และ ordered complete file list
3. ตรวจ SHA-256 ของไฟล์ทุกไฟล์
4. reject missing, extra หรือ hash mismatch
5. ตรวจ code-signing/publisher policy เมื่อ Security/Release freeze แล้ว

**การ spawn**

- ใช้ executable และ fixed argument list จาก approved manifest เท่านั้น
- ไม่ใช้ shell
- working directory ต้องเป็น bundle ที่ verified
- สร้าง process ownership handle/job object เพื่อ cleanup เฉพาะ Core ที่ Launcher สร้าง
- environment ต้องเป็น explicit allow-list; ห้ามส่ง permit, bearer token, proxy credential หรือ raw configuration
- ห้าม infer readiness จาก `Popen`, PID, process survival หรือ pipe existence

**การหยุด**

- ขอ graceful typed stop ผ่าน control channel ก่อน
- รอ owned process ด้วย bounded timeout
- kill ได้เฉพาะ owned process หลัง timeout
- partial spawn failure ต้องเข้าสู่ cleanup เช่นเดียวกับ spawn สำเร็จ
- ห้าม kill process จากชื่อเพียงอย่างเดียว

ค่าที่ยังต้อง freeze: executable basename/final bundle, manifest schema/hash, fixed argv, signature policy และ Core mutex identity

### 3.5 `NamedPipeCoreControlChannel` — strict protocol v2 client

Implement `CoreControlChannel`:

```text
request_challenge(correlation_id, timeout) -> CoreChallenge
start_authorized(command, permit, correlation_id, timeout) -> CoreStatus
stop(correlation_id, timeout) -> CoreStatus
```

อาจเพิ่ม `get_status(...)` หลัง Core และ Security อนุมัติ semantics สำหรับ reconciliation แล้วเท่านั้น

**Transport requirements ตาม proposal ปัจจุบัน**

- Windows named pipe แบบ current-user-only; exact pipe name ยังเป็น Core-owned TBD
- frame = unsigned 4-byte big-endian length + strict UTF-8 JSON payload
- payload/response ceiling 8192 bytes
- reject zero length, oversize ก่อน allocate/read, BOM, malformed UTF-8 และ trailing data
- reject unknown fields, duplicate fields, wrong case, float/boolean coercion และ schema mismatch
- partial read/write ต้องวนภายใต้ operation deadline เดียว
- correlation ID ต้องเป็น lowercase hex 32 ตัวและ response ต้องตรงกับ request

**Permit boundary**

- เรียก `OpaquePermit.reveal_for_transport()` เฉพาะจุด serialize `start` frame ลง pipe buffer
- ห้ามคัดลอก permit ไป log, exception, temp file, telemetry, argv หรือ environment
- หลัง write/read timeout, disconnect, malformed response หรือ correlation mismatch ให้ถือ start outcome ว่า ambiguous ห้าม retransmit frame เดิมและห้าม reuse permit

**Readiness**

รับว่าสำเร็จเฉพาะ typed response ที่มี `succeeded=true`, correlation ตรง และ `status=Running` เท่านั้น

### 3.6 `BackendLaunchPermitGateway` — central authorization authority

Implement `LaunchPermitGateway`:

```text
issue_launch_permit(
    session_id,
    installation_key_hash,
    challenge,
    command,
    timeout,
) -> OpaquePermit
```

**Request ที่ Backend ต้องได้รับ**

- authenticated caller context จาก bearer/JWT session ที่ Launcher มีอยู่
- claimed Launcher session ID
- installation key hash
- one-time Core challenge
- canonical opaque start configuration หรือ approved configuration hash
- request correlation/idempotency fields ตาม contract ที่ freeze แล้ว

**Backend checks ที่ต้อง authoritative และ atomic เท่าที่จำเป็น**

- user ยัง authenticated และไม่ถูก disable/revoke
- entitlement/license active สำหรับ product
- claimed session active และเป็นของ user เดียวกัน
- installation binding ตรง
- fresh heartbeat policy ผ่าน
- challenge ถูกต้อง, ยังไม่หมดอายุ, ยังไม่ถูกใช้ และ bind กับ Core/runtime attempt
- profile/server reference อยู่ในสิทธิ์และ config hash ตรง
- rate limit, signer และ key version พร้อมใช้งาน

**Response handling**

- success ต้องคืน opaque signed permit ที่ non-empty และอยู่ในขนาดสูงสุดตาม frozen contract
- Launcher ห้าม decode หรือใช้ claims เพื่อตัดสินสิทธิ์แทน Core/Backend
- HTTP status/body ต้อง map เป็น allow-listed typed failure เท่านั้น
- reject success body ที่ missing/extra/wrong-type/oversize
- timeout หรือผลลัพธ์กำกวมต้องไม่ retry permit request เดิมแบบอัตโนมัติ เว้นแต่ frozen Backend contract กำหนด idempotency ชัดเจน; attempt ใหม่ต้องขอ challenge ใหม่

**Backend/Security TBD ก่อน implement production**

- endpoint/RPC และ exact HTTP request/response envelope
- JWT header/claims, issuer, audience, product, scope, TTL และ skew
- signer/key custody, JWKS/key distribution, rotation, retirement และ revocation
- body limit, rate limit, idempotency และ typed error taxonomy
- canonical configuration encoding/hash พร้อม positive/negative fixtures

### 3.7 `RuntimeAuthorizationMonitor` — continuous authorization

Boundary นี้ยังเป็น policy TBD และยังไม่ควร invent protocol:

```text
renew_or_validate(runtime_binding, challenge, cancellation) -> RenewalDecision
```

เมื่อ Security freeze แล้ว adapter ต้องรองรับ signed renewal/revalidation, bounded grace period และ revocation response โดย Core เป็น enforcement boundary ที่ modified Launcher ข้ามไม่ได้

ต้องกำหนดร่วมกันก่อน implement:

- renewal interval และ jitter
- runtime-binding claims
- offline/grace behavior
- session/license revocation SLA
- Backend outage behavior
- stop/cleanup semantics เมื่อ renewal ล้มเหลว

## 4. Production configuration

Launcher config ต้องมีเฉพาะ public/non-secret identifiers ที่ freeze แล้ว เช่น contract revision, manifest location และ public Backend base URL ที่มีอยู่ตาม deployment convention

ห้ามเก็บใน environment, source, package หรือ config file:

- Backend secret/service-role key
- permit signing private key
- static reusable proxy credential
- customer/session bearer token แบบ plaintext persistence
- raw proxy password หรือ server secret

ข้อมูลที่ยังไม่ freeze ต้องทำให้ composition fail closed ตั้งแต่ startup หรือก่อน activation ไม่ใช้ placeholder production value

## 5. Error boundary และ UI mapping

Adapter ทุกตัวต้องคืน typed result หรือถูก orchestrator ลดรูปเป็น `AuthorizedCoreErrorCode` ห้ามเผย arbitrary adapter code/message

Current launcher-owned sanitized conditions:

- `AuthorizationContextUnavailable`
- `ConfigurationUnavailable`
- `DuplicateStart`
- `Cancelled`
- `TargetUnavailable`
- `TargetExited`
- `HeartbeatUnavailable`
- `ChallengeUnavailable`
- `PermitUnavailable`
- `RunningNotReached`
- `AdapterFailure`

หลัง protocol freeze อาจ map Core/Backend allow-list เช่น `AuthorizationRequired`, `AuthorizationInvalid`, `AuthorizationExpired`, `AuthorizationReplay`, `AuthorizationUnavailable` และ `SessionInactive` เข้าสู่ public Launcher taxonomy โดย mapping ต้องเป็น call-site-owned และ adapter ไม่สามารถ impersonate condition อื่นผ่านข้อความหรือ string code

Log/UI/telemetry ต้องไม่มี:

- exception text จาก remote/process/IPC adapter
- token, permit, challenge หรือ claim detail
- user/session/license/installation identifier
- endpoint, proxy configuration หรือ expected-vs-actual secret value
- traceback/minidump annotation ที่มี sensitive buffer

## 6. Timeout และ retry policy

ค่าต่อไปนี้ยังเป็น proposal และต้อง freeze พร้อม Core/Backend:

| Operation | Proposed deadline |
|---|---:|
| exact target wait | 120 s |
| control channel readiness | 5 s |
| challenge round trip | 5 s |
| Backend permit request | 10 s |
| authorized start / typed Running | 15 s |
| graceful stop | 10 s |
| owned-process exit | 5 s |
| owned-process kill wait | 5 s |

ทุก timeout ใช้ monotonic total deadline ไม่ reset ต่อ partial I/O และต้องรองรับ cancellation

Retry rules:

- challenge และ permit ใช้ได้ attempt เดียว
- ห้าม retransmit `start` หลัง ambiguous outcome
- attempt ใหม่เริ่มตั้งแต่ target/precondition/challenge/permit ใหม่
- duplicate/concurrent start ต้องถูก reject ก่อนเกิด side effect รอบที่สอง
- Backend/key/pipe outage ต้อง fail closed ไม่มี offline allow-all หรือ local signing fallback

## 7. Cleanup และ ownership

เมื่อ failure เกิดหลังเริ่ม spawn host แล้ว ให้ทำตามลำดับแบบ bounded:

1. best-effort typed `stop` เมื่อ channel ใช้งานได้
2. graceful stop เฉพาะ owned Core process
3. รอ bounded timeout
4. kill owned process เฉพาะเมื่อยังไม่หยุด
5. release handle/channel และกลับ state เป็น Idle พร้อม sanitized failure เดิม

Cleanup adapter exception ห้ามแทนที่ root public failure และต้องไม่ปล่อย orphan process/helper/pipe/mutex/controller/temp state

## 8. Test requirements ต่อ adapter

### Unit / contract tests

- strict positive/negative schema fixtures สำหรับ HTTP และ pipe
- malformed UTF-8, BOM, duplicate/unknown fields, wrong types, oversize และ partial frames
- correlation mismatch และ response status mismatch
- target PID reuse/exit ทุก boundary
- heartbeat false/timeout/exception/cancellation ทำให้ host side effect เป็นศูนย์
- permit endpoint false/timeout/malformed/typed failure ทำให้ `start` side effect เป็นศูนย์
- adapter exceptions รวมถึง exception ที่ `__str__` ล้มเหลวไม่หลุดออก UI/log
- partial host-start failure ถูก cleanup
- graceful-stop exception/false นำไป owned kill ตาม policy
- duplicate start มี flow เดียว

### Secret-sentinel tests

ใส่ unique sentinel เป็น bearer token, permit และ proxy material แล้วตรวจว่าไม่อยู่ใน:

- argv/process command line
- child environment
- files/temp/cache/package
- logs, UI, exception และ traceback
- telemetry/crash artifacts
- test output/snapshot

### Production E2E gate

1. no target → no Core/proxy/driver activation
2. target present แต่ไม่มี permit → engine start count 0
3. invalid/expired/replayed/config-mismatched permit → engine start count 0
4. target หายก่อน final check → engine start count 0
5. valid target + valid permit → exactly one runtime และ typed `Running`
6. target exit, Launcher exit, Backend/session revocation และ Core crash cleanup ผ่าน
7. ไม่มี orphan และไม่มี direct reusable proxy bypass
8. ทดสอบด้วย clean release artifacts และ production adapter path เดียวกับที่จะ ship

## 9. Production wiring gate

เปลี่ยน `AuthorizationPendingProxyGateway` เป็น `AuthorizedProxyGateway` ได้ต่อเมื่อครบทุกข้อ:

- [ ] Core + Backend + Security + Launcher อนุมัติ contract revision/hash เดียวกัน
- [ ] exact named pipe/mutex identities และ current-user ACL ถูก freeze
- [ ] Backend permit endpoint/envelope/error/idempotency contract ถูก freeze
- [ ] JWT claims, signing keys, rotation, expiry, replay และ revocation policy ถูก freeze
- [ ] canonical config hash และ cross-repository fixtures ถูก publish พร้อม SHA-256
- [ ] Core executable/dependency manifest, fixed argv และ signature policy ถูกอนุมัติ
- [ ] production implementations ของ adapter ทุกตัวผ่าน unit/contract/security tests
- [ ] secret-sentinel และ clean-package gates ผ่าน
- [ ] real Launcher → Backend → Core E2E ผ่าน negative matrix และ exactly-one-Running case
- [ ] continuous authorization หรือ residual-risk decision ได้รับ Security sign-off
- [ ] QA และ Security อนุมัติ release

ถ้าข้อใดไม่ครบ production composition ต้องคง `AuthorizationPendingProxyGateway` และ fail closed ต่อไป

## 10. Ownership และงานถัดไป

| Adapter / decision | Owner หลัก | สถานะ |
|---|---|---|
| `AuthorizedProxyGateway` composition | Launcher | ยังไม่ implement production |
| exact target detector | Launcher | scaffold/test behavior มีบางส่วน; production review required |
| fresh heartbeat precondition | Launcher + Backend | scaffold มีแล้ว; production probe contract pending |
| verified Core process adapter | Launcher + Core + Release | blocked by artifact/manifest contract |
| named-pipe control channel | Launcher + Core | blocked by protocol/pipe identity approval |
| Backend permit gateway | Launcher + Backend | blocked by endpoint/envelope/authority contract |
| permit verifier/key ring | Core + Security | ยังไม่พร้อม production ตาม handoff ปัจจุบัน |
| continuous authorization | Backend + Core + Security | policy TBD |
| proxy-access enforcement | Backend + Proxy Server + Security | blocked/unverified |
| E2E release gate | ทุกทีม + QA | blocked |

ลำดับงานแนะนำ:

1. freeze S0 contract และ publish sanitized fixture package
2. implement/verify Core challenge + verifier + protocol host
3. implement Backend permit authority และ security controls
4. implement Launcher production adapters หลัง exact contracts พร้อม
5. ต่อ composition โดยไม่มี bypass path
6. รัน cross-repository security/E2E matrix
7. เปลี่ยนสถานะ production ได้เมื่อ QA/Security sign-off เท่านั้น

## 11. เอกสารอ้างอิง

- `docs/LAUNCHER_S0_CONTRACT_PROPOSAL.md`
- `docs/LAUNCHER_S0_CONNECTOR_HANDOFF.md`
- `docs/LAUNCHER_CORE_AUTHORIZATION_ADAPTER_HANDOFF.md`
- `docs/S0_SECURITY_CONTRACT_FREEZE_REQUEST.md`
- `launcher/src/neko_launcher/application/authorized_core.py`
- `launcher/src/neko_launcher/infrastructure/unavailable_gateway.py`
- `launcher/src/neko_launcher/main.py`
