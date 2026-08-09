# บันทึกสถานะงาน: Launcher → Backend Permit → NekoProxyCore

บันทึกเมื่อ: 9 สิงหาคม 2026

## สถานะ ณ จุดหยุด

ทำงานต่อจากจุดหยุดและทดสอบเสร็จแล้ว ไม่มี process build/test ที่ยังทำงานอยู่

- Repository: `E:\Github\Neko-Family-Proxy`
- Branch: `main` ตรงกับ `origin/main` ก่อน local edits
- Base HEAD: `8f1708a` (`docs: add progress tracking notes`)
- ยังไม่ได้ commit หรือ push
- Working tree มี source/test ที่แก้ค้างอยู่ 10 ไฟล์ และไฟล์บันทึกนี้อยู่ที่ `docs/ทำถึงใหน.md`
- Production ยังเป็น **BLOCKED — BACKEND ACTION REQUIRED**
- Local verification และ EXE artifact ใหม่ผ่านตามหลักฐานด้านล่าง
- Staging/real backend E2E ยังไม่ได้ทำ เพราะไม่มี production-ready permit issuer/approved staging credentials ใน checkout นี้
- ไฟล์สถานะเดิมที่ root ถูกย้ายมาไว้ใต้ `docs/` เพื่อจัดโครงสร้างเอกสารให้ชัดเจน โดยยังไม่ได้ commit หรือ push

## Root cause ที่ตรวจพบ

Production Supabase project ถูกตรวจแบบ read-only แล้ว:

- ไม่พบ Edge Function `issue_launch_permit`
- พบเพียง `reset-password` ที่ ACTIVE
- ไม่พบชื่อ secret `RS256_PRIVATE_KEY` และ `RS256_KID`
- endpoint permit จึงล้มด้วย `FunctionsHttpError` HTTP 404
- prototype ใน `supabase/functions/issue_launch_permit/index.ts` ระบุ `EXPERIMENTAL / PRODUCTION BLOCKED` และยังไม่ปลอดภัยสำหรับ deploy เพราะยังไม่ verify JWT/active session/entitlement/challenge/configuration/PID จาก authoritative server state

ไม่ได้ deploy function, ไม่แก้ production config และไม่สร้าง signing key ชั่วคราว

## สิ่งที่แก้แล้วใน working tree

### Launcher permit/auth flow

- ใช้ authenticated Supabase client/session เดิม
- sync current access token เข้า Functions client ผ่าน `set_auth()`
- ส่ง request แบบ camelCase ตาม `s0-rc1`
- ไม่ส่ง client-owned identity claims เช่น user/session/license/installation ID
- permit ยังคงเป็น opaque value และไม่ decode/log/persist
- เพิ่ม fresh active-session heartbeat ก่อนเริ่ม Core host
- เพิ่ม cancellation check หลัง heartbeat ก่อน Core host side effect
- คง fail-closed ทุก failure path

### Timeout hardening ล่าสุด

- ตั้ง Supabase PostgREST และ Functions client timeout ที่ 10 วินาทีใน production client composition
- permit gateway ตรวจว่า concrete HTTP client timeout ไม่เกิน operation deadline; ถ้าไม่ bounded จะ fail closed เป็น `PERMIT_TIMEOUT`
- heartbeat precondition เรียก `heartbeat_session_with_timeout()` และตรวจ concrete PostgREST HTTP timeout ก่อน RPC
- แก้ heartbeat RPC ให้ใช้ client schema ที่ compose ไว้โดยตรง เพื่อไม่สร้าง schema client ใหม่ที่ทำ timeout/MockTransport หลุด

### Authority response hardening ล่าสุด

success response ต้องมี exact fields เท่านั้น:

- `version=1`
- `contractRevision=s0-rc1`
- `correlationId` ตรงกับ request
- `succeeded=true`
- `permit` เป็น ASCII ความยาว `1..4096`
- `expiresInSeconds=30`
- reject unknown/additional fields และ contradictory response แบบ fail closed

หมายเหตุ: authoritative package path ที่ docs อ้าง (`Backend Security/security-contract/NEKO-AUTH-S0/s0-rc1`) ไม่ได้อยู่ใน working tree, local branches, Git objects หรือ GitHub code search ที่เข้าถึงได้ จึงอ้าง bounds จาก local handoff docs ซึ่งระบุ permit `1..4096` และ `expiresInSeconds=30`

### Diagnostics

- เพิ่ม typed permit diagnostic categories สำหรับ 401/403/404/5xx/timeout/malformed response/missing field/missing auth session
- customer-facing error ยังคง generic
- development metadata มีทั้ง key และ value allow-list
- strict correlation ID, numeric ranges, fixed function/stage และ allow-listed exception classes
- ไม่ log token, Authorization header, raw permit, private key หรือ arbitrary backend body

## Tests ที่เพิ่ม/แก้

- authenticated Supabase SDK 2.31.0 transport และ Bearer header ผ่าน `httpx.MockTransport`
- 401/403/404/500 classification
- Python/httpx timeout classification
- malformed/missing permit response
- strict `s0-rc1` success envelope และ rejection cases
- concrete Functions/PostgREST timeout enforcement
- missing current session
- replaced/revoked heartbeat fail before Core host start
- cancellation during heartbeat fail before Core host start
- diagnostics spoof/secret-leak rejection

## ผลทดสอบล่าสุดจริง

คำสั่งล่าสุดหลัง timeout/cancellation/response-envelope edits:

```text
uv run pytest -q tests/test_launch_permit_gateway.py \
  tests/test_supabase_gateway.py \
  tests/test_authorized_core.py
```

ผล:

```text
81 passed in 0.54s
```

ก่อน edits ล่าสุด เคยผ่าน:

- focused permit/auth/diagnostics/orchestration: 77 passed
- non-integration suite โดย exclude Tk environment test: 229 passed, 3 deselected
- UI suite: 23 passed
- Ruff และ compileall: passed

ผลก่อน edits ล่าสุดถือเป็น **stale evidence** และต้องรันใหม่ก่อนส่งมอบ

## Windows EXE

เคย build `launcher/dist/NekoLauncher.exe` สำเร็จหลายรอบ และ real startup smoke ผ่านก่อน timeout/cancellation/strict-response edits ล่าสุด

artifact รอบก่อนล่าสุดที่บันทึกไว้:

- size: `65,063,210` bytes
- SHA-256: `b2c451eb06626387534ba2e629dd26c8a6889e55986a7cbffeed3d917485a666`
- archive มี `ProxyCore/NekoProxyCore.exe` และ `ProxyCore/nfdriver.sys`
- startup smoke: process อยู่รอดอย่างน้อย 5 วินาทีและ cleanup ไม่มี leftover launcher PID

**สำคัญ:** EXE นี้สร้างก่อน source edits ล่าสุด จึงเป็น artifact เก่าและต้อง rebuild + smoke ใหม่ก่อนส่งมอบ

Known build warnings รอบก่อน:

- unresolved `NDIS.SYS`
- unresolved `fwpkclnt.sys`

PyInstaller build ยัง exit code 0

## จุดที่กำลังจะทำตอนถูกสั่งหยุด

กำลัง triage independent-review findings ของ Core control channel และ stop cleanup แต่ยังไม่ได้แก้ไฟล์เหล่านี้:

- `launcher/src/neko_launcher/infrastructure/core/core_control_channel.py`
- `launcher/src/neko_launcher/infrastructure/core/authorized_proxy_gateway.py`
- `launcher/src/neko_launcher/infrastructure/core/core_process.py`

งานค้างที่ reviewer พบ:

1. Core Protocol v2 response parser ยัง permissive:
   - `json.loads()` ยังรับ duplicate fields
   - unknown fields ยังไม่ถูก reject
   - challenge ยังไม่ enforce exact 43-character base64url
   - result ยังไม่ enforce invariant ระหว่าง `succeeded/status/errorCode`
2. Named Pipe timeout ปัจจุบัน bounded เฉพาะ open retry; read/write ยังไม่มี one-total monotonic deadline ที่พิสูจน์ได้
3. `AuthorizedProxyGateway.stop()` เรียก process graceful stop โดยตรง, ยังไม่ส่ง typed protocol stop, ignore `False`, และไม่ force-kill owned process เมื่อ graceful stop timeout
4. process detector เปลี่ยน observation exception เป็น `False` ซึ่งอาจทำให้ healthy runtime ถูก stop จาก transient observation error
5. auto-start latch ไม่ retry safe pre-permit transient failure ขณะ game process เดิมยังอยู่

ข้อ 4–5 ยังไม่ได้ตัดสิน implementation เพราะต้องแยก safe retry จาก ambiguous permit/start outcome และต้องไม่ weaken authorization/replay behavior

## Modified files ปัจจุบัน

```text
launcher/src/neko_launcher/application/authorized_core.py
launcher/src/neko_launcher/application/diagnostics.py
launcher/src/neko_launcher/bootstrap/app_factory.py
launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py
launcher/src/neko_launcher/infrastructure/core/launch_permit_gateway.py
launcher/src/neko_launcher/infrastructure/diagnostics_logger.py
launcher/tests/test_authorized_core.py
launcher/tests/test_diagnostics.py
launcher/tests/test_launch_permit_gateway.py
launcher/tests/test_supabase_gateway.py
ทำถึงใหน.md
```

ก่อนเพิ่มไฟล์บันทึกนี้ diff ของ 10 ไฟล์มีประมาณ:

```text
950 insertions, 76 deletions
```

## ขั้นตอนแนะนำเมื่อทำต่อ

1. ตรวจ `git status`, `git diff --check` และอ่าน diff ปัจจุบันก่อนแก้ต่อ
2. ทำ RED tests สำหรับ strict Core response parsing ทีละ invariant
3. แก้ Named Pipe total deadline โดยไม่สร้าง unbounded worker/thread leak
4. เพิ่ม public orchestrator cleanup/stop path แล้วให้ `AuthorizedProxyGateway.stop()` ใช้ typed channel stop + graceful wait + owned-process kill fallback
5. ตัดสิน detection/retry policy โดยยึด fresh challenge/permit ทุก attempt และห้าม retry ambiguous issuance/start outcome
6. รัน focused tests ทั้ง permit/auth/diagnostics/Core channel/stop
7. รัน Ruff, compileall และ full non-integration suite; บันทึก Tk environment blocker แยกจาก product failures
8. ทำ independent review ใหม่กับ actual final diff
9. build Windows EXE ใหม่
10. ตรวจ archive, SHA-256 และ real EXE startup smoke ใหม่
11. รายงาน local/staging/production แยกกัน โดย production ยังต้องระบุ `BLOCKED — BACKEND ACTION REQUIRED`

## งานที่ทำต่อหลังจุดหยุด

### Core Protocol v2 และ Named Pipe

- เพิ่ม strict response envelope validation:
  - reject duplicate JSON fields ด้วย `object_pairs_hook`
  - reject unknown/additional fields
  - challenge ต้องเป็น unpadded base64url exact 43 ASCII characters
  - result ต้อง enforce `succeeded/status/errorCode` invariant และ allow-list error code
- เปลี่ยน named-pipe request เป็น one-total monotonic deadline ครอบคลุม open, write และ read
- เพิ่ม bounded retry สำหรับ transient non-blocking I/O และ Windows named-pipe non-blocking configuration
- เพิ่ม regression tests สำหรับ duplicate fields, unknown fields, challenge bounds, contradictory result และ read deadline

### Stop และ process/retry policy

- เพิ่ม public orchestrator `stop()` ให้ส่ง typed protocol stop ก่อน graceful cleanup
- `AuthorizedProxyGateway.stop()` ใช้ public orchestrator path ไม่แตะ private process internals โดยตรง
- graceful stop ที่คืน `False` หรือผิดพลาดจะ force-kill เฉพาะ owned Core process
- process observation error คืน `None` และ UI รักษา last known state; จะไม่ตีความ transient observation failure เป็น game exit
- automatic start retry ทำได้เฉพาะ typed pre-permit failure ที่ระบุชัด (`TargetUnavailable`, `ChallengeUnavailable`, `HeartbeatUnavailable`); ambiguous issuance/start result จะไม่ retry อัตโนมัติ

## ผลตรวจสอบหลังทำต่อจริง

- focused Core protocol/orchestration/process/UI suite: **84 passed**
- canonical non-integration suite excluding known broken Tk environment module: **257 passed, 3 deselected**
- real Windows named-pipe withheld-response read test: **passed in 0.23s**
- real Windows named-pipe withheld-peer write verification: **passed in 0.203s**
- Ruff: **passed**
- compileall: **passed**
- `git diff --check`: **passed**

### EXE artifact ใหม่จาก source ปัจจุบัน

- Build command: `uv run python -m PyInstaller --clean --noconfirm NekoLauncher.spec`
- Result: **PyInstaller build passed**
- Artifact: `launcher/dist/NekoLauncher.exe`
- Size: `65,136,784` bytes
- SHA-256: `afb7c874f84d086e21eaea574d99a098cf6619f074140f012e0c4d6e11bf200b`
- PE machine: `0x8664` (x64)
- PE subsystem: `2` (GUI)
- Real startup smoke: process PID `12476` อยู่รอด 5 วินาที และ cleanup process tree แล้วไม่เหลือ `NekoLauncher.exe`
- Known non-blocking packaging warnings: unresolved `NDIS.SYS` และ `fwpkclnt.sys`; build exit code 0 และ startup smoke ผ่าน

### Independent final review

- รอบแรกพบ blockers เรื่อง real Windows deadline, process observation, challenge retry classification และ open-retry sleep
- แก้ด้วย regression tests, real Windows pipe verification, typed observation failure, `check_returncode()` สำหรับ `tasklist`/`ps`, `CHALLENGE_UNAVAILABLE` และ remaining-deadline sleep clamp
- independent re-review รอบสุดท้ายหลังปิด creation-identity และ strict integer-version findings: **PASS** — `security_concerns=[]`, `logic_errors=[]`
- reviewer ให้ suggestions แบบ non-blocking เท่านั้น; ไม่มี finding ที่ต้องปิดเพิ่มก่อนส่งมอบ

Artifact นี้เป็น local build evidence เท่านั้น ไม่ใช่หลักฐาน signing, reproducibility, security approval หรือ production release approval

## Production release blockers ที่ยังไม่เปลี่ยน


Backend/Security ต้องมี production-ready permit issuer ที่:

- verify Supabase JWT จริง
- derive identity จาก authenticated server state
- validate active session/heartbeat/entitlement/license/installation/product/scope
- validate challenge/configuration/target PID/process binding
- enforce replay/rate-limit/audit/time/KID/key rotation policy
- provision approved RS256 signer และ matching immutable Core verifier key
- deploy `issue_launch_permit` และให้ staging credentials/accounts สำหรับ real E2E

ห้าม deploy prototype ปัจจุบันเพื่อทำให้ Launcher ผ่านแบบชั่วคราว
