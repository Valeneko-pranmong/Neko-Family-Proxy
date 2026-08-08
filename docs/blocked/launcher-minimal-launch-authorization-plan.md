# แผนลดระบบ Authorization — ทีม Launcher

> **สถานะ: DRAFT / PRODUCTION BLOCKED — reviewed 8 August 2026.** ใช้สำหรับ
> วางแผนหลัง Product, Security และ Core อนุมัติขอบเขตเท่านั้น ห้ามใช้เป็น
> production release approval หรือแทน baseline ใน
> [`neko-auth-s0-production-handoff.md`](neko-auth-s0-production-handoff.md)

> **For Hermes:** ใช้แผนนี้เป็น execution handoff แบบ task-by-task หลัง Product/Security/Core ยืนยันขอบเขต “Minimal Launch Authorization” แล้วเท่านั้น

**Goal:** ทำให้ Launcher เปิด NekoProxyCore ได้จริงโดยใช้ระบบอนุญาตขั้นต่ำที่ยัง fail closed: ผู้ใช้ต้อง login, Backend ออก permit อายุสั้นที่เซ็นด้วย private key, Launcher ส่ง permit แบบ opaque และ Core เป็นผู้ตรวจเอง

**Architecture:** คงเส้นทางเดียว `Login → ตรวจสิทธิ์และออก permit ที่ Backend → Launcher เปิด Core → Core challenge → Launcher ส่ง permit → Core ตอบ Running` โดย reuse Protocol v2 และ initial-start verifier ที่มีอยู่แล้ว ตัดระบบ renewal ทุก 15 วินาที, runtime artifact attestation, process-binding หลายชั้น และ release bureaucracy ที่ไม่ได้จำเป็นต่อการเปิดใช้งานครั้งแรก

**Tech Stack:** Python 3.11, Supabase/authenticated backend, PyInstaller, Windows process/Named Pipe, opaque RS256 launch permit

**แผนคู่กัน:** [`core-minimal-launch-authorization-plan.md`](core-minimal-launch-authorization-plan.md)

---

## 1. เป้าหมายความปลอดภัยที่ยอมรับร่วมกัน

Launcher รุ่นนี้ต้องรับประกันเพียงขอบเขตต่อไปนี้:

1. ผู้ใช้ที่ยังไม่ได้ login หรือไม่มี entitlement ขอ permit ไม่ได้
2. ทุกการกด Start ต้องขอ permit ใหม่จาก Backend; ไม่มี offline permit และไม่มี cached permit
3. Backend เป็นผู้ถือ private signing key เพียงแห่งเดียว
4. Launcher ไม่ตัดสินสิทธิ์จากข้อความ `allowed=true` และไม่ sign permit เอง
5. Launcher มอง permit เป็น opaque string อายุสั้น เก็บในหน่วยความจำชั่วคราว และส่งให้ Core เพียงครั้งเดียว
6. Core ต้องตอบ typed `Running` จึงถือว่า Start สำเร็จ
7. token, permit, private key และ reusable proxy credential ห้ามอยู่ใน argv, environment, config, log, traceback หรือ artifact
8. เมื่อเกิด error ต้อง cleanup เฉพาะ Core process ที่ Launcher เป็นผู้สร้าง

### สิ่งที่ไม่ได้พยายามรับประกัน

- ไม่พยายามป้องกันผู้ใช้ระดับ reverse engineer ที่ patch binary ของ Launcher/Core เอง
- ไม่ถือว่า PyInstaller one-file EXE เป็น security boundary; ใช้เพื่อการแจกจ่ายเท่านั้น
- ไม่บังคับ logout/revocation ให้หยุด Core ภายใน 15–30 วินาที; permit นี้อนุญาต “การเริ่มหนึ่งครั้ง” ไม่ใช่ continuous authorization
- ไม่ทำ runtime attestation ว่าไฟล์ Core ทุกไฟล์ไม่ถูกแก้ไข
- ไม่สร้าง PKI, JWKS, certificate chain หรือ key service ฝั่งเครื่องผู้ใช้

ความเสี่ยงที่ยอมรับคือ session อาจถูก revoke หลังเริ่มแล้วแต่ Core ยังทำงานต่อจนผู้ใช้ Stop, Launcher ปิด, Core ปิด หรือ target process จบ หากธุรกิจต้องการ immediate revocation ค่อยเพิ่มเป็น Phase 2 หลังระบบพื้นฐานใช้งานได้

---

## 2. สิ่งที่คงไว้และสิ่งที่หยุดทำ

### คงไว้ — ห้ามลด

- Backend-signed permit แบบ asymmetric signature
- permit อายุ 30 วินาทีตาม verifier ปัจจุบัน
- one-time `challenge` และ `jti`/replay protection
- binding กับ configuration digest, `pso2.exe`, target PID และ `ProcessMode`
- production private key อยู่ Backend เท่านั้น; Core bundle มีเฉพาะ public key
- no permit / invalid permit / expired permit / replay → Core engine start count ต้องเป็นศูนย์
- fail-closed เมื่อ Backend, Core channel หรือ key material ใช้งานไม่ได้

### หยุดทำใน Minimal V1

- แยก fresh-heartbeat request ก่อนขอ permit: ให้ Backend ตรวจ session, entitlement และ heartbeat/server stateในคำขอ permitครั้งเดียว
- renewal loop ทุก 15 วินาทีและ signed-renewal protocol
- runtime ID และ renewal challenge schema
- signed artifact manifest ที่ตรวจทุก path/hash/reparse pointตอน runtime
- `GetNamedPipeServerProcessId` race-proof identity chain หลายขั้น
- contract package/revision ใหม่ทุกครั้งที่แก้รายละเอียดภายในซึ่งไม่เปลี่ยน wire contract
- S1 downstream access เป็น blocker ของงาน Launcher↔Core; ให้เป็น workstream แยก แต่ยังห้าม bundle reusable proxy credential
- exhaustive security test matrix ที่ไม่เกี่ยวกับ acceptance criteriaใน §8

> อย่าลบโค้ดที่ทำเสร็จและไม่ขวางงานเพียงเพราะอยู่นอก Minimal V1 ให้หยุดขยายก่อน และค่อยลบเฉพาะส่วนที่ทำให้ production composition เปิดไม่ได้หรือเพิ่ม dependency ที่ไม่ใช้

---

## 3. Minimal V1 flow

```text
ผู้ใช้ login สำเร็จ
→ ผู้ใช้กด Start
→ Launcher ตรวจ local authenticated context และ entitlement ที่มีอยู่
→ หา exact pso2.exe และเก็บ PID
→ เปิด Core process โดยไม่มี secret ใน argv/env
→ ขอ challenge จาก Core
→ สร้าง canonical configuration/digest ตาม format ปัจจุบัน
→ เรียก Backend หนึ่งครั้งด้วย authenticated transport
→ Backend ตรวจ user/session/entitlement/server state แล้วออก signed permit อายุ 30 วินาที
→ Launcher ส่ง start + opaque permit ให้ Coreหนึ่งครั้ง
→ สำเร็จเมื่อ Coreตอบ Running ที่ correlation ตรงกันเท่านั้น
→ monitor Core และ target; Stop/exit ทำ bounded cleanup
```

ห้าม retry `start` เดิมแบบอัตโนมัติ หากผลกำกวมให้ cleanup แล้วเริ่ม flow ใหม่ด้วย challenge และ permit ใหม่

---

## 4. Task 1 — Freeze ขอบเขต Minimal V1 โดยไม่ redesign wire

**Objective:** ใช้ Protocol v2 และ initial launch-permit shape ที่ Core รองรับอยู่แล้ว เพื่อหลีกเลี่ยงการสร้าง contract รอบใหม่

**Files:**
- Modify: `launcher/src/neko_launcher/application/authorized_core.py`
- Modify: `launcher/src/neko_launcher/application/production_authorization.py`
- Test: `launcher/tests/test_authorized_core.py`
- Test: `launcher/tests/test_production_authorization.py`

**Steps:**

1. คง `OpaquePermit`, `CoreChallenge`, `TargetBoundStartCommand` และ canonical bytes ปัจจุบัน
2. คง `challenge → backend permit → start` เป็นเส้นทางเดียว
3. เปลี่ยน production blockers ให้เหลือเฉพาะของ Minimal V1:
   - Backend permit issuerพร้อม
   - production public keyพร้อมใน Core
   - Launcher process/channel adapterพร้อม
   - production composition wired
   - minimal E2Eผ่าน
4. เอา renewal contract, signed manifest, S1 และ full release-governance blockers ออกจาก gate ของ Launcher↔Core Minimal V1
5. ไม่สร้าง protocol v3 และไม่แก้ field names หาก Core verifier ปัจจุบันรับได้อยู่แล้ว

**Verification:**

```bash
cd launcher
python -m pytest -q tests/test_authorized_core.py tests/test_production_authorization.py
```

Expected: tests ของ canonical digest, opaque permit, fail-closed และ production gate ผ่านทั้งหมด

---

## 5. Task 2 — รวม heartbeat/entitlement validation ไว้ใน permit issuance

**Objective:** ลด network flow และ adapter หนึ่งชั้น โดยให้ Backend ตัดสินสิทธิ์ครบในคำขอ permit

**Files:**
- Modify: `launcher/src/neko_launcher/application/authorized_core.py`
- Modify: `launcher/src/neko_launcher/infrastructure/supabase_gateway.py`
- Test: `launcher/tests/test_authorized_core.py`
- Test: `launcher/tests/test_supabase_gateway.py`

**Steps:**

1. ลบ dependency `LaunchPrecondition`/`OnlineHeartbeatLaunchPrecondition` ออกจาก production orchestration
2. permit request ใช้ authenticated transport ของ session ปัจจุบัน
3. request bodyส่งเฉพาะข้อมูล start ที่ Backend ต้องตรวจ:
   - contract/wire versionที่ใช้อยู่
   - correlation ID
   - Core challenge
   - configuration digest
   - process name
   - target PID
   - mode/product/scope
4. ไม่ส่ง private key, password, service-role key หรือ reusable proxy credential
5. Backend endpoint/deployment handleเป็นค่าภายใน deployment; ไม่ต้องเผยเป็น public endpointใน repositoryหรือ handoff
6. Backend ต้องตรวจ authenticated user, active entitlement และ session stateก่อน sign; failureคืน typed codeแบบ sanitized
7. Launcherไม่ decode claimsและไม่เอา client-side booleanมาแทน permit

**Verification:**

- unauthenticated requestไม่เรียก Core start
- inactive entitlementไม่ได้ permit
- Backend unavailableไม่ได้ permitและไม่มี local fallback
- request bodyไม่มี private credential/server secret
- permitไม่ปรากฏใน repr/log/traceback

---

## 6. Task 3 — ทำ process/channel adapter แบบพอใช้จริง

**Objective:** เปิด Core, ติดต่อ Protocol v2 และ cleanup ได้จริงโดยไม่ทำ runtime attestation หลายชั้น

**Files:**
- Create: `launcher/src/neko_launcher/infrastructure/core_process.py`
- Create: `launcher/src/neko_launcher/infrastructure/core_control_channel.py`
- Modify: `launcher/src/neko_launcher/application/authorized_core.py`
- Test: `launcher/tests/test_core_process.py`
- Test: `launcher/tests/test_core_control_channel.py`

**Steps:**

1. หา `NekoProxyCore.exe` จากตำแหน่งที่ installer/bundleกำหนดแบบ fixed path
2. spawn ด้วย fixed executable, `shell=False`, fixed working directory และไม่มี secretใน argv/env
3. เก็บ `Popen`/Windows process handle ของ processที่ตนสร้างเพื่อ cleanup
4. ใช้ Named Pipe identity/versionปัจจุบันของ Core; จำกัด current userตาม implementationที่มี
5. implement frame write/read, correlation check และ timeoutเพียงชุดเดียว
6. permitถูก serialize เฉพาะตอนเขียน `start` frame
7. ไม่ทำ signed manifest, recursive hash scan, reparse-point walk หรือ pipe-server PID attestationใน Minimal V1
8. หาก channel fail, responseไม่ตรง, timeout หรือ non-Running ให้ stop/terminateเฉพาะ owned Core process

**Verification:**

- missing Core EXE → sanitized error
- Coreไม่เปิด pipe → timeoutและไม่มี orphan
- malformed/nonmatching response → fail closed
- valid challenge/start/Running → success
- permit sentinelไม่อยู่ใน command line, environment หรือ log

---

## 7. Task 4 — Wire production gateway ให้ใช้งานจริง

**Objective:** แทน `AuthorizationPendingProxyGateway` ด้วย adapterจริงเมื่อ dependency Minimal V1พร้อม

**Files:**
- Modify: `launcher/src/neko_launcher/application/production_authorization.py`
- Modify: `launcher/src/neko_launcher/main.py`
- Modify: `launcher/src/neko_launcher/application/authorized_core.py`
- Test: `launcher/tests/test_main.py`
- Test: `launcher/tests/test_production_authorization.py`

**Steps:**

1. สร้าง production `ProxyGateway` facadeหนึ่งตัวที่เรียก Minimal V1 orchestrator
2. reuse session/auth stateจาก `SupabaseGateway`; ห้ามสร้าง loginระบบที่สอง
3. map Core/Backend failureเป็นข้อความ UI allow-listสั้น ๆ
4. `create_production_proxy_gateway()` คืน gatewayจริงเมื่อ dependenciesถูกประกอบครบ
5. หาก config/public deployment materialขาด ให้ fail closedพร้อมข้อความผู้ใช้ ไม่ fallbackเป็น Core startตรง
6. คง single-flight เพื่อป้องกันการกด Startซ้ำ

**Verification:**

- production windowประกอบ gatewayจริง
- logout/no entitlementยัง Startไม่ได้
- ไม่มี direct `subprocess` start pathจาก UIที่ข้าม orchestrator
- Startสำเร็จเฉพาะ typed `Running`

---

## 8. Task 5 — Minimal acceptance tests และ artifact

**Objective:** พิสูจน์ flowที่ shipจริง แทนการเพิ่มเอกสารหรือ test doublesอย่างเดียว

**Required tests:**

1. ไม่ login → ไม่มี permit requestและไม่มี Core process
2. loginแต่ entitlementไม่ active → ไม่มี valid permitและ Coreไม่ Running
3. Backend unavailable → fail closed ไม่มี offline fallback
4. invalid/expired/wrong-challenge permit → Core engineไม่เริ่ม
5. permitเดิมใช้ซ้ำ → ครั้งที่สองถูกปฏิเสธ
6. valid login + valid permit + targetตรง → `Running` หนึ่งครั้ง
7. Launcher Stop/Core failure/target exit → ไม่มี orphanที่ Launcherเป็นเจ้าของ
8. scan EXE/runtime logsแล้วไม่พบ permit/private key/reusable proxy credential sentinel

**Commands:**

```bash
cd launcher
python -m ruff check src tests
python -m pytest -q -m "not integration"
python -m PyInstaller --clean --noconfirm NekoLauncher.spec
cd ..
python scripts/check_repository_safety.py
```

จากนั้นทำ clean-machine smoke testด้วย `launcher/dist/NekoLauncher.exe` และ Core artifactที่ทีม Coreส่งให้

**Evidence ที่ต้องส่ง:**

- exact Launcher commit SHA
- exact Core commit/artifact SHA-256
- exact test commandsและ pass/fail count
- video/logแบบ sanitizedของ `login → Start → Running → Stop`
- ยืนยันว่าไม่มี secret/permit/private key/reusable proxy credentialใน evidenceหรือ artifact

---

## 9. Definition of Done — ทีม Launcher

- [ ] Login/session/entitlementเดิมยังทำงาน
- [ ] Backend permit callหนึ่งครั้งต่อ Start
- [ ] ไม่มี separate preflight heartbeat dependency
- [ ] ไม่มี renewal loopใน Minimal V1
- [ ] Launcherไม่ sign/decode/cache/log permit
- [ ] Coreถูกเปิดด้วย fixed pathและไม่มี secretใน argv/env
- [ ] challenge → permit → start → Runningทำงานจริง
- [ ] failureทุก boundaryไม่มี unauthorized Runningและไม่มี owned orphan
- [ ] PyInstaller one-file artifactสร้างและ smoke testผ่าน
- [ ] ทีม Coreยืนยัน contract/field/public keyชุดเดียวกัน

---

## 10. Phase 2 — เพิ่มเฉพาะเมื่อมีเหตุผลทางธุรกิจ

สิ่งต่อไปนี้ไม่ใช่เงื่อนไขของ Minimal V1 และห้ามเริ่มก่อน V1ผ่าน E2E:

- continuous authorization/rapid revocation
- signed artifact manifest/runtime attestation
- exact pipe server process identity hardening
- automatic key rotation/JWKS
- anti-tamper/obfuscationเพิ่มเติม
- remote telemetryและsecurity analytics

ทุก Phase 2 itemต้องมี threatหรือbusiness requirementที่วัดได้ ห้ามเพิ่มเพียงเพราะ “อาจจำเป็นในอนาคต”
