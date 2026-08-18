# AI Implementation Prompt: Launcher รองรับหลายเครื่อง แต่ใช้งานได้ครั้งละ 1 session

> **Status: IMPLEMENTATION HANDOFF — LAUNCHER**
>
> **Target:** AI/ทีมที่แก้ Desktop Launcher
>
> **Source repository:** `Neko-Family-Proxy`
>
> **Component scope:** `launcher/`
>
> **Matching Backend contract:** [`backend-single-active-session-ai-prompt.md`](backend-single-active-session-ai-prompt.md)
>
> เอกสารนี้เป็นข้อกำหนด implementation และ verification ไม่ใช่คำอนุมัติ deploy production

## คำสั่งหลักสำหรับ AI ผู้ลงมือแก้

ปรับ Desktop Launcher ให้รองรับนโยบายต่อไปนี้อย่างสมบูรณ์:

> บัญชีเดียวกันล็อกอินหรือจดจำไว้บนเครื่องใดก็ได้และไม่จำกัดจำนวน installation แต่มี active Launcher session ได้ครั้งละ 1 session เท่านั้น การ claim session ล่าสุดสำเร็จจะยกเลิก session ก่อนหน้า และ Launcher เครื่องเดิมต้องหยุด ProxyCore, ล้าง local authentication, กลับหน้า Login และแจ้งผู้ใช้เมื่อ Backend ยืนยันว่า session เดิมใช้ต่อไม่ได้

ก่อนแก้โค้ด:

1. อ่านโครงสร้างและ flow จริงของ `launcher/` ทั้ง application, infrastructure, UI และ tests
2. ตรวจสถานะ working tree และรักษาการแก้ไขที่ไม่เกี่ยวข้องของผู้ใช้ ห้าม revert, overwrite หรือ commit งานอื่น
3. อ่าน Backend contract ที่ `docs/current/backend-single-active-session-ai-prompt.md`
4. ตรวจ signature และ response ที่ Backend staging deploy จริงก่อนทำ E2E; migration ใน repository เพียงอย่างเดียวไม่ใช่หลักฐานว่า production ถูก deploy แล้ว
5. เขียนหรือปรับ tests ก่อน implementation และรันให้เห็น failure ของ behavior ที่ยังขาด
6. แก้เฉพาะ Launcher ในงานนี้ ห้ามแก้ Backend schema/RPC เพื่อหลบ client bug
7. ห้าม commit, push, deploy หรือแตะ production เว้นแต่ได้รับคำสั่งชัดเจน
8. ห้ามอ่าน แสดง log หรือฝัง service-role key, refresh token, access token หรือ secret ใด ๆ

---

## 1. Business behavior ที่ต้องได้

### 1.1 Latest successful claim wins

ลำดับตัวอย่างที่ต้องรองรับ:

1. เครื่อง A sign in และ `claim_session`: สำเร็จ
2. เครื่อง B sign in ด้วยบัญชีเดียวกันและ `claim_session`: สำเร็จ โดยไม่แสดง device-limit error
3. Backend revoke session ของ A และให้ session ใหม่แก่ B แบบ transactional
4. heartbeat ครั้งถัดไปของ A คืน `false`
5. Launcher A หยุด ProxyCore ทันที ล้าง local session กลับหน้า Login และแสดงข้อความที่เข้าใจได้
6. heartbeat ของ B คืน `true` และ B ใช้งานต่อ
7. A สามารถ sign in ใหม่ภายหลังและกลายเป็น session ล่าสุดแทน B ได้

ห้ามทำให้ client สองเครื่องแย่ง session กันอัตโนมัติแบบ ping-pong หลังถูกดีดออก เครื่องที่ได้รับ authoritative heartbeat `false` ต้องล้าง persisted authentication และรอให้ผู้ใช้ sign in ใหม่เอง

### 1.2 Installation ไม่เท่ากับ active session

- `installation_key_hash` ใช้ระบุ installation ที่จดจำใน Backend เท่านั้น
- ห้ามใช้จำนวน installation history มาบล็อก login ฝั่ง Launcher
- ห้ามลบหรือสร้าง installation identity ใหม่เพื่อหลบข้อจำกัด
- `max_devices` ใน response เป็น legacy compatibility field ไม่ใช่จำนวน historical installations ที่อนุญาต
- `installation_revoked` ยังเป็น hard deny สำหรับ installation นั้น
- `device_limit_reached` ต้องเก็บ safe legacy handling ไว้สำหรับ Backend รุ่นเก่า แต่ไม่ควรถูกแสดงเป็นนโยบายปัจจุบัน

### 1.3 Session restore ถือเป็นการ claim ล่าสุด

หาก Launcher restore Supabase Auth session ที่เก็บไว้ได้ตอนเปิดโปรแกรม:

- ต้องเรียก `claim_session` ตาม contract เดิม
- หาก claim สำเร็จ installation นี้จะเป็น active session ล่าสุดและอาจแทน session ของเครื่องอื่น
- หาก Backend ปฏิเสธแบบ terminal เช่น installation ถูก revoke, account ถูก restrict หรือ authentication ใช้ไม่ได้ ต้องล้าง persisted authentication และคงอยู่หน้า Login
- หากไม่มี license แต่บัญชียังใช้งานได้ ให้คง authenticated account flow ที่ใช้เติมคูปองได้ตาม behavior เดิม
- หากเป็น network/service failure ชั่วคราว ห้ามปลอมว่า claim สำเร็จและห้ามเริ่ม ProxyCore

---

## 2. Current Launcher evidence ที่ต้องตรวจซ้ำ

ณ วันที่จัดทำเอกสาร repository มีจุดที่เกี่ยวข้องดังนี้ แต่ AI ต้องอ่าน source ปัจจุบันก่อนแก้ เพราะ branch อาจเปลี่ยนแล้ว:

| Concern | Current path |
|---|---|
| Supabase Auth และ session RPC adapter | `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py` |
| Login, restore, claim, heartbeat, sign-out flow | `launcher/src/neko_launcher/application/services.py` |
| State transition และการหยุด Proxy | `launcher/src/neko_launcher/application/controller.py` |
| Gateway protocols | `launcher/src/neko_launcher/application/ports.py` |
| Session/domain state | `launcher/src/neko_launcher/domain/models.py` |
| Domain events | `launcher/src/neko_launcher/domain/events.py` |
| UI state, heartbeat timer และหน้า Login | `launcher/src/neko_launcher/ui/app_window.py` |
| Login copy/layout | `launcher/src/neko_launcher/ui/views/auth_view.py` |
| Installation identity | `launcher/src/neko_launcher/infrastructure/storage/installation.py` |
| Local Supabase session storage | `launcher/src/neko_launcher/infrastructure/storage/secure_store.py` |
| Service unit tests | `launcher/tests/test_services.py` |
| Supabase adapter tests | `launcher/tests/test_supabase_gateway.py` |
| Controller tests | `launcher/tests/test_controller.py` |
| UI tests | `launcher/tests/ui/test_app_window.py` |
| Disposable Supabase E2E | `launcher/tests/integration/test_supabase_e2e.py` |

Current code appears to contain preparatory behavior already:

- `claim_session` uses the existing three RPC parameters
- heartbeat runs approximately every 30 seconds
- authoritative heartbeat `false` triggers forced local sign-out
- local Supabase authentication is cleared even if remote sign-out fails
- controller sign-out stops ProxyCore and clears session state
- transient heartbeat exceptions are tolerated three times
- `installation_revoked` and legacy `device_limit_reached` map to typed device denial

Do not rewrite working behavior blindly. Confirm it with tests, identify gaps, and make the smallest coherent change. Known areas that deserve explicit verification include terminal error typing, stale heartbeat races, duplicate queued heartbeats, user-facing policy text, and obsolete comments that still describe an active-device limit.

---

## 3. Wire contract ที่ Launcher ต้องรักษา

### 3.1 Claim session

Launcher must continue calling:

```text
launcher.claim_session(
  p_product_code text,
  p_installation_key_hash text,
  p_display_name text
)
```

Payload shape:

```json
{
  "p_product_code": "neko-family-proxy",
  "p_installation_key_hash": "<64 lowercase hexadecimal SHA-256 characters>",
  "p_display_name": "<display name up to 120 characters>"
}
```

Compatible response contains at least:

```json
{
  "session_id": "<UUID>",
  "installation_id": "<UUID>",
  "license_id": "<UUID>",
  "product_code": "neko-family-proxy",
  "valid_until": "<ISO-8601 timestamp with timezone>",
  "max_devices": 1
}
```

Launcher requirements:

- continue parsing `session_id`, `product_code`, `valid_until`, and legacy `max_devices`
- tolerate additional unknown fields
- do not require incompatible renamed fields
- never consider a claim successful without a valid non-empty `session_id` and parseable entitlement response
- never start ProxyCore from stale local entitlement data without an active claimed session

### 3.2 Heartbeat

Keep calling:

```text
launcher.heartbeat_session(p_session_id uuid) returns boolean
```

Interpretation:

- `true`: current Launcher session remains usable
- `false`: authoritative terminal result for this session; it may have been replaced, revoked, released, or invalidated by entitlement/account policy
- exception/timeout: transport failure, not proof of replacement

Because the current Backend response is only boolean, Launcher must not claim it knows the exact server reason. Use user copy that prominently covers replacement without being false, for example:

> เซสชันนี้ถูกยกเลิกหรือบัญชีถูกเข้าสู่ระบบจากเครื่องอื่น กรุณาเข้าสู่ระบบใหม่

Do not change the heartbeat RPC to a new response object in this task unless Backend and Launcher owners explicitly approve a versioned contract.

### 3.3 Release

Keep calling:

```text
launcher.release_session(p_session_id uuid) returns boolean
```

Release is best-effort client cleanup. A release for an old session must not affect the newly active session; Backend owns that guarantee. Launcher must always clear local state even if release or remote Auth sign-out fails.

---

## 4. Required Launcher implementation

### 4.1 Model terminal session outcomes explicitly

Inspect the existing error hierarchy in:

- `launcher/src/neko_launcher/application/errors.py`
- `launcher/src/neko_launcher/infrastructure/auth/supabase_gateway.py`
- `launcher/src/neko_launcher/application/services.py`

Implement typed outcomes sufficient to distinguish:

1. installation authorization denial (`installation_revoked` and legacy `device_limit_reached`)
2. account/auth terminal denial (`account_restricted`, `not_authenticated`, or equivalent approved Backend codes)
3. missing/invalid entitlement that may still allow the signed-in user to redeem a coupon
4. transient transport/service failure

Terminal authorization failures during sign-in, restore, claim, or heartbeat must fail closed and clear local authentication. A generic temporary RPC failure must not be mislabeled as “logged in elsewhere.”

Do not expose raw Supabase/PostgREST/SQL exception text to the UI. Public messages must come from an allow-listed mapping of stable server codes.

### 4.2 Claim the new session before marking the Launcher ready

For explicit sign-in and restored authentication:

1. authenticate with Supabase Auth
2. call `claim_session` with current installation identity
3. parse and validate the response
4. update entitlement and active `session_id`
5. only then enable actions that require a Launcher session or start auto-launch behavior

Exception: an account with no current license may remain signed in for the existing coupon-redemption workflow, but it must have no active Launcher session and cannot start Tweaker/ProxyCore through protected flow.

If claim is denied by installation/account/auth policy:

- best-effort release only the locally known old Launcher session, if one exists
- best-effort remote Auth sign-out
- always clear persisted local Auth in a `finally`-equivalent path
- reset controller state to signed out
- do not auto-retry claim
- show safe Thai copy

### 4.3 Heartbeat replacement handling

Heartbeat behavior must be:

- run only when a non-empty active `session_id` exists
- interval remains approximately 30 seconds unless product requirements change
- only one heartbeat request may be in flight or queued at a time
- reset transient-failure count after any successful RPC response or new session claim
- tolerate the existing bounded number of transient transport failures
- treat an explicit `false` response as terminal immediately; do not wait for three failures
- stop ProxyCore immediately even if PSO2 is currently running
- clear session and entitlement state
- clear local Supabase authentication even when network sign-out fails
- return UI to Login
- surface replacement-aware, non-deceptive Thai copy
- never automatically reclaim after authoritative `false`

Do not terminate a user-owned PSO2 process merely because the Launcher session was replaced. Stop only processes/connections owned by the Launcher according to existing process-ownership policy, especially ProxyCore. If current Launcher explicitly owns a child Tweaker process, preserve the approved shutdown policy rather than inventing a new one.

### 4.4 Prevent stale heartbeat races

Capture the `session_id` used for each heartbeat request. Before applying a terminal heartbeat result, compare it with the controller's current `session_id`.

If a heartbeat response belongs to an older local session and a newer claim has already succeeded in this Launcher process:

- ignore the stale response for state mutation
- do not sign out the newer session
- do not release the newer session
- do not overwrite the newer entitlement
- optionally record a sanitized diagnostic event without identifiers or tokens

Add a deterministic unit test for this race. Do not rely only on the UI's single-thread executor as the safety boundary; the application service should protect its own session-generation/state invariant.

### 4.5 Stop protected runtime before clearing state

On replacement or terminal session invalidation:

1. prevent new protected launch/start requests
2. stop ProxyCore through the existing gateway/controller ownership path
3. clear active Launcher session and entitlement state
4. clear Auth and return to Login

The controller and UI must never temporarily show `AUTHENTICATED + active controls` after terminal invalidation. Verify state-transition ordering with tests.

If ProxyCore stop fails:

- preserve fail-closed state in the Launcher
- do not retain an active `session_id`
- record only sanitized diagnostics
- show a safe generic failure message if necessary
- do not restore access merely because cleanup failed

### 4.6 UI copy

Add visible, concise policy text near Login or an appropriate account-access location:

> บัญชีเดียวใช้งานได้ครั้งละ 1 เครื่อง การเข้าสู่ระบบที่เครื่องนี้จะสิ้นสุดเซสชันของเครื่องก่อนหน้า

For a heartbeat returning `false`, use copy equivalent to:

> เซสชันนี้ถูกยกเลิกหรือบัญชีถูกเข้าสู่ระบบจากเครื่องอื่น กรุณาเข้าสู่ระบบใหม่

For explicit installation revocation:

> เครื่องนี้ไม่สามารถใช้บัญชีนี้ได้ กรุณาติดต่อฝ่ายบริการ

For legacy `device_limit_reached`, keep a safe compatibility message but do not describe it as the current policy. Prefer wording that asks the user to update/retry/contact support rather than stating that historical devices are permanently limited.

Remove or update obsolete Launcher comments/help text equivalent to:

- another active device blocks this claim
- account has reached lifetime device count
- coupon claim may fail simply because another device is active

Do not expose `session_id`, full installation hash, tokens, internal error code, SQL text, or stack trace in customer UI.

### 4.7 Diagnostics and security

Permitted diagnostics:

- stable stage such as `SESSION_CLAIMED`, `HEARTBEAT_REJECTED`, `LOCAL_SIGN_OUT_COMPLETED`
- sanitized reason category such as `session_invalidated`, `transport_failure`
- timing and retry count without credentials

Forbidden diagnostics:

- access/refresh tokens
- Authorization headers
- service-role/publishable key values
- password or coupon plaintext
- full installation hash
- raw Supabase exception payload containing customer/internal data

A publishable Supabase key may be embedded as designed. A service-role or secret key must never exist in Launcher source, config, build artifact, logs, tests, or docs.

---

## 5. Error behavior matrix

| Backend/client outcome | Launcher behavior |
|---|---|
| Claim succeeds on a different installation | Accept new `session_id`; this machine is now latest active session |
| `installation_revoked` | Hard deny, clear local Auth, return Login, show installation-blocked copy |
| legacy `device_limit_reached` | Hard deny for compatibility, clear local Auth, safe support/update message |
| `account_restricted` | Hard deny, clear local Auth, return Login, account-support message |
| `not_authenticated` | Clear invalid local Auth, return Login, ask user to sign in again |
| `license_invalid` / no license | No protected session; preserve approved coupon flow if account Auth remains valid |
| heartbeat returns `true` | Keep current session; reset transient failure counter |
| heartbeat returns `false` for current session | Stop ProxyCore, clear local/Auth state, return Login immediately |
| heartbeat returns `false` for stale local session ID | Ignore for current state; do not sign out newer local session |
| heartbeat raises temporary transport error | Bounded retry/tolerance; fail closed after configured threshold |
| release/sign-out network call fails | Continue guaranteed local cleanup; never retain access because remote cleanup failed |

---

## 6. Tests required before completion

### 6.1 Supabase gateway unit tests

Update `launcher/tests/test_supabase_gateway.py` to prove:

- claim request uses schema `launcher`, function `claim_session`, and unchanged parameter names
- successful response parses compatible fields and tolerates extras
- malformed/missing `session_id` fails safely
- `installation_revoked` maps to typed installation denial
- legacy `device_limit_reached` remains safely typed but uses non-obsolete copy
- `account_restricted` and `not_authenticated` map to terminal typed outcomes
- `license_invalid` remains entitlement-specific
- raw internal exception text is not returned as customer copy
- heartbeat sends the exact `session_id` and distinguishes explicit `false` from exceptions

### 6.2 Service tests

Update `launcher/tests/test_services.py` to prove:

1. explicit sign-in claims a new session before protected actions become available
2. restored Auth claims a new session
3. claim success replaces local state with the newest `session_id`
4. terminal claim denial clears local Auth even if remote sign-out throws
5. missing license preserves only the approved coupon flow and cannot start protected runtime
6. heartbeat `true` keeps the session
7. heartbeat `false` immediately signs out and clears session/entitlement
8. heartbeat `false` stops a running ProxyCore
9. heartbeat `false` while game is running is not deferred
10. two transient heartbeat exceptions are tolerated and the configured threshold invalidates safely
11. a successful heartbeat/new claim resets the transient failure counter
12. stale heartbeat `false` cannot clear a newer local claim
13. authoritative `false` does not trigger automatic reclaim
14. release/sign-out failure cannot prevent local cleanup

### 6.3 Controller/UI tests

Update relevant controller and UI tests to prove:

- terminal invalidation transitions to signed-out Login state
- protected launch buttons become disabled
- ProxyCore stop is requested before/while access state is removed
- user sees replacement-aware Thai copy
- Login displays one-session policy copy
- explicit installation-revoked copy remains distinct
- heartbeat timer does not queue overlapping requests
- no stale error from an old heartbeat overwrites the newly claimed session UI

Do not make tests depend on real production credentials or production customer data.

### 6.4 Integration/E2E

With two independent Gateway instances and disposable staging users:

1. A signs in and claims installation A
2. A heartbeat is `true`
3. B signs in and claims installation B with the same account
4. B claim succeeds even when response/data still contains `max_devices = 1`
5. A heartbeat is `false`
6. Launcher-level handling on A clears Auth/session and stops protected runtime
7. B heartbeat remains `true`
8. A signs in again and claims successfully
9. B then receives `false`
10. explicitly revoked installation is still denied
11. restricted account cannot claim from either installation
12. clean up all disposable test data through the approved staging workflow

E2E must use approved staging/disposable credentials supplied through environment variables. Never hard-code them or print them.

---

## 7. Verification commands

Run from `launcher/` using the repository's supported Python environment:

```powershell
python -m ruff check src tests
python -m pytest -q -m "not integration"
```

When approved disposable Supabase staging credentials are available:

```powershell
python -m pytest -q -m integration
```

If Launcher packaging or UI/resource files change, also follow:

- `docs/current/build-windows-executable.md`
- the current `launcher/NekoLauncher.spec`

Build the real Windows executable and perform the documented smoke test before claiming release readiness. Unit tests alone do not prove staging/production session replacement.

---

## 8. Out of scope unless separately approved

- changing Backend RPC names, parameters, or heartbeat boolean response
- WebSocket/SSE real-time kick channel
- deleting `max_devices` columns or response fields
- hardware fingerprinting or hardware attestation
- deleting historical installation records
- allowing multiple concurrent active sessions
- exposing service-role credentials to Launcher
- killing unrelated/user-owned game processes
- production deployment or migration approval

Heartbeat polling is sufficient for this version: database invalidation is immediate, while the displaced Launcher detects it within the next heartbeat interval. Real-time push may be designed later as a backward-compatible enhancement.

---

## 9. Acceptance criteria

งาน Launcher เสร็จเมื่อครบทั้งหมด:

- [ ] Sign in/restore จาก installation ใหม่ claim ได้โดยไม่บล็อกจาก installation history
- [ ] Launcher รักษา RPC signatures และ response compatibility เดิม
- [ ] Session ล่าสุดเท่านั้นถูกเก็บเป็น active local session
- [ ] heartbeat `false` ของ current session หยุด ProxyCore และกลับ Login ทันที
- [ ] local Auth ถูกล้างแม้ remote release/sign-out ล้มเหลว
- [ ] ไม่มี automatic reclaim หลังถูกดีดออก
- [ ] stale heartbeat result ไม่สามารถ sign out session ใหม่กว่าใน process เดียวกัน
- [ ] heartbeat request ไม่ซ้อนหรือสะสมใน queue
- [ ] transient network failure ไม่ถูกแจ้งผิดว่า login ซ้อนในครั้งแรก
- [ ] `installation_revoked`, account restriction, no-license และ transport error แยก behavior ถูกต้อง
- [ ] UI อธิบายว่าใช้ได้หลายเครื่องแต่ active ได้ครั้งละ 1 เครื่อง
- [ ] legacy `device_limit_reached` handling ยัง fail closed แต่ไม่ถูกนำเสนอเป็นนโยบายใหม่
- [ ] protected actions ใช้งานไม่ได้เมื่อไม่มี active `session_id`
- [ ] ไม่มี secret/token/raw internal error ใน UI, logs, tests หรือ build artifact
- [ ] Ruff ผ่าน
- [ ] non-integration tests ผ่านพร้อมรายงานจำนวนจริง
- [ ] staging two-client E2E ผ่าน หรือรายงาน blocker ว่ายังไม่มี approved staging credentials โดยไม่กล่าวอ้างว่า E2E ผ่าน
- [ ] Windows build/smoke test ผ่านหากมีการเปลี่ยน packaging/UI/runtime artifact

---

## 10. Final report ที่ AI ต้องส่งกลับ

รายงานผลแบบกระชับแต่ตรวจสอบได้ โดยระบุ:

1. behavior เดิมและ gap ที่พบจริง
2. ไฟล์ที่แก้ พร้อมเหตุผล
3. error types/mapping ที่เพิ่มหรือเปลี่ยน
4. exact RPC contract ที่รักษาไว้
5. flow เมื่อ claim/heartbeat บ่งชี้ว่า session ใช้ต่อไม่ได้
6. race/overlapping-heartbeat protection
7. UI copy ที่ใช้จริง
8. คำสั่งทดสอบและจำนวน passed/failed/skipped จริง
9. staging two-client E2E evidence หรือ blocker ที่ตรงไปตรงมา
10. Windows build/smoke status ถ้าเกี่ยวข้อง
11. security/log redaction checks
12. remaining blockers และสิ่งที่ต้องประสาน Backend
13. ยืนยันชัดเจนว่าได้หรือไม่ได้แก้ production

ห้ามสรุปว่า “รองรับสมบูรณ์แล้ว” จาก mock/unit tests เพียงอย่างเดียว หากยังไม่ได้ทดสอบ Backend staging ที่ deploy contract ใหม่จริง ให้ระบุว่า Launcher code พร้อมระดับใดและ integration ยังถูก block ด้วยอะไร
