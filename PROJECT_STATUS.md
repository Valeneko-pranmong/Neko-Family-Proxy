# Neko Family Proxy - Project Status and Team Handoff

> อัปเดตล่าสุด: 25 กรกฎาคม 2026  
> เอกสารนี้เป็นจุดส่งต่องานหลักสำหรับทีม ผู้รับช่วงควรอ่านไฟล์นี้ก่อนเริ่มแก้โค้ด

## เป้าหมายของการ Rebuild

เปลี่ยนจากโปรแกรมแจกภายในกลุ่มให้เป็นโครงสร้างที่พร้อมพัฒนาเป็นผลิตภัณฑ์จริง
โดยมีการสมัครสมาชิก/เข้าสู่ระบบผ่าน Supabase, ระบบสิทธิ์แบบเติม Coupon,
ระบบควบคุมการเข้าสู่ระบบซ้ำ และหน้า Admin ที่แยกสิทธิ์ชัดเจน

การตัดสินใจที่ยืนยันแล้ว:

- ตัด Easy Donate ออกทั้งหมด ใช้ Admin ออก Coupon ให้ลูกค้าเอง
- ตัด Game Monitor และ Network Monitor ออกจาก Launcher V2
- คงธีมสีชมพู โลโก้ และไอคอนเดิมของ Neko Family
- เก็บ Launcher รุ่นแรกไว้ที่ `original-code/v1/`
- รวม `admin-web/` เป็นโฟลเดอร์ปกติของ repository หลัก
- ไม่ใส่ `ProxyCore/` หรือ `ProxyCore.rar` ใน GitHub โดยเด็ดขาด

## ทำเสร็จแล้ว

### โครงสร้าง Source Control

- ย้าย `NekoLauncher.py` และ `NekoLauncher.spec` รุ่นเดิมไปไว้ใน
  `original-code/v1/`
- ตรวจสอบแล้วว่าไฟล์ V1 ที่ archive มี hash ตรงกับไฟล์เดิม
- ลบ build artifact รุ่นเก่า (`build/`, `dist/`, `__pycache__/`) โดยส่งไป
  Recycle Bin เพื่อให้กู้คืนได้
- รวม source ของ `admin-web/` เข้า repository หลักแล้ว
- สำรองประวัติ Git เดิมของ `admin-web` ไว้ใน
  `original-code/admin-web-history.bundle` (ไฟล์นี้ถูก ignore ไม่ขึ้น GitHub)
- เพิ่มกติกาใน `.gitignore` และ `.gitattributes` สำหรับ secret, dependency,
  build output, line ending และ proprietary runtime
- เพิ่มเอกสารทีม:
  - `CONTRIBUTING.md`
  - `REPOSITORY_LAYOUT.md`
  - ไฟล์นี้ `PROJECT_STATUS.md`

### Launcher V2

โครงสร้างใหม่อยู่ใน `launcher/` แยกเป็น domain, application, infrastructure
และ UI แล้ว โดยมี:

- state model สำหรับ auth, entitlement และ proxy lifecycle
- event bus และ controller สำหรับลำดับการทำงาน
- process manager ที่เก็บ process handle ของตัวเอง ไม่ใช้ `taskkill` แบบกว้าง
- guard เมื่อไม่พบ executable
- UI shell ที่ใช้ธีมสีชมพูและโหลดโลโก้/ไอคอนเดิม
- ตัด model/event ของ Game Monitor และ Network Monitor ออกแล้ว
- มี unit tests สำหรับ controller และ event bus

ขณะนี้ Launcher V2 เป็น shell ที่พร้อมต่อ adapter จริง แต่ยังไม่ใช่
ระบบ Login/Coupon แบบ end-to-end

### Admin Web

- แปลหน้า Admin เป็นภาษาไทยแล้ว
- เปลี่ยนธีมจาก dark mode เป็นพื้นขาว ตัดชมพูอ่อน และรองรับหน้าจอมือถือ
- เพิ่มหน้า `/guide` เป็นคู่มือการใช้งานภาษาไทย
- เพิ่มคู่มือแบบไฟล์ Markdown ที่ `admin-web/USER_GUIDE_TH.md`
- ทดสอบด้วย `npm run build`, `npm run lint` และ `npm test` ผ่านทั้งหมด
- เผยแพร่เวอร์ชันล่าสุดแบบ private สำหรับทีมแล้วที่
  `https://neko-control-room.sachems-flyby2za1.chatgpt.site`

### Supabase

มี migration ใน `supabase/migrations/` สำหรับ:

- profiles, products, licenses
- installation และ launcher session
- session claim/heartbeat/release
- foreign-key/index และ RLS
- coupon batch, coupon hash, redemption attempt และการ redeem แบบ transaction

แนวทาง Coupon ถูกออกแบบไว้แล้วใน [supabase/COUPONS.md](supabase/COUPONS.md):

- Admin สร้าง batch และกำหนดจำนวนวัน/จำนวน key
- แสดง plaintext key ให้ Admin เพียงครั้งเดียว
- Database เก็บเฉพาะ SHA-256 hash
- Coupon ใช้ได้ครั้งเดียวและรองรับการต่ออายุสิทธิ์
- จำกัดความพยายาม redeem และล็อก concurrent redemption

## สถานะที่ยังไม่เสร็จ / ข้อจำกัดปัจจุบัน

1. Launcher ยังไม่ได้ต่อ Supabase Auth จริง ต้องทำ adapter สำหรับ register,
   login, logout, refresh session และ `getUser`.
2. Launcher ยังไม่ได้เรียก RPC สำหรับ entitlement และ session control จริง
   จึงยังไม่สามารถกัน Login ซ้ำแบบใช้งานจริงได้
3. หน้าสมัครสมาชิก, หน้า Login และหน้า Redeem Coupon ของฝั่ง Launcher ยังต้อง
   เชื่อมกับ state/controller ใหม่
4. Migration Coupon (`20260725091805_create_coupon_redemption.sql`) เป็นไฟล์
   local ที่เตรียมไว้ แต่ยังต้องตรวจสอบและ apply ไปยัง Supabase project ผ่าน
   workflow ที่มีสิทธิ์ เนื่องจาก Supabase MCP ปัจจุบันตอบ HTTP 451
   (`no_biscuit_no_service`)
5. `admin-web/` มี source พร้อมใช้งาน แต่ต้องตั้งค่า secret ฝั่ง server,
   allowlist, production URL และทดสอบสิทธิ์ Admin ให้ครบ
6. `ProxyCore` ไม่อยู่ใน repository จึงต้องมีวิธีแจก runtime แยกต่างหากก่อน
   ทดสอบการเชื่อมต่อจริงหรือทำ installer
7. `original-code/v1/` ยังมีค่า endpoint รุ่นเก่า ควรตรวจสอบ/rotate/redact
   ก่อน push repository เป็น public
8. ยังไม่มี CI pipeline สำหรับ launcher และ admin-web
9. `npm install` รายงาน dependency vulnerabilities 18 รายการ ต้องแยกตรวจ
   และอัปเดตก่อนใช้งาน production โดยเฉพาะรายการระดับ high

## ลำดับงานถัดไปที่แนะนำ

### P0 - ความปลอดภัยและฐานข้อมูล

1. ตรวจสอบไฟล์ที่จะเผยแพร่ด้วย secret scan และ review
   `original-code/v1/NekoLauncher.py`
2. ยืนยัน migration ที่อยู่บน Supabase project จริง
3. Apply migration Coupon ที่ยัง pending ผ่าน Supabase CLI/MCP/SQL editor
   ที่ทีมอนุมัติ
4. เปิด `launcher` schema ใน Supabase Data API ตามเอกสาร
   `supabase/README.md`
5. ทดสอบ RLS, role escalation, coupon replay, concurrent redeem และ
   session takeover ด้วย test account

### P1 - ต่อระบบใช้งานจริง

1. เพิ่ม Supabase client ฝั่ง Launcher โดยใช้ publishable/anon key เท่านั้น
2. ทำ flow สมัครสมาชิก, Login, Logout และ session refresh
3. ทำ `claim_session` เมื่อ Login และ heartbeat ตามช่วงเวลา
4. เมื่อมี session ใหม่ ให้ session เก่าถูก revoke/ปิดการใช้งานอย่างชัดเจน
5. ต่อ `get entitlement` และบังคับตรวจสิทธิ์ก่อนเริ่ม proxy
6. เพิ่มหน้า Redeem Coupon และข้อความ error ที่ไม่เปิดเผยข้อมูลภายใน
7. ต่อ Admin web กับ Supabase server client และตรวจสิทธิ์ Admin ทุก route

### P2 - ทดสอบและเตรียมส่งมอบ

1. เพิ่ม integration test สำหรับ Auth, Coupon และ single-session behavior
2. เพิ่ม lint/build/test ใน GitHub Actions
3. กำหนดวิธีจัดเก็บและแจก `ProxyCore` แยกจาก source repository
4. สร้าง installer/release pipeline โดยไม่ฝัง secret ใน artifact
5. ตรวจสอบโลโก้ ธีมชมพู และข้อความทุกหน้าก่อน release
6. Commit เป็นชุดเล็ก ๆ ตาม feature แล้วเปิด Pull Request ให้ทีม review

## คำสั่งสำหรับผู้รับช่วงงาน

ตรวจสถานะ:

```powershell
git status --short --untracked-files=all
git add --dry-run .
```

รัน Launcher checks:

```powershell
Set-Location launcher
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

รัน Admin web:

```powershell
Set-Location admin-web
npm install
npm run lint
npm run build
```

ข้อควรระวัง:

- ห้าม commit `.env`, service-role key, private key, customer data หรือ
  `ProxyCore` ทุกกรณี
- อย่าใช้ `git add -f` กับไฟล์ที่ถูก ignore
- อย่า push จนกว่าจะ review legacy endpoint ใน V1 และตรวจ migration จริง
- ก่อนแก้ schema ให้สร้าง migration ใหม่ ห้ามแก้ migration ที่เคย apply แล้ว

## Definition of Done สำหรับ Rebuild รุ่นแรก

ถือว่า MVP พร้อมให้ทีมทดสอบเมื่อ:

- สมัคร/Login/Logout ผ่าน Supabase ได้
- Login ซ้ำถูกป้องกันและ session เก่าถูก revoke
- Redeem Coupon สำเร็จเพียงครั้งเดียวและต่ออายุ license ได้
- Admin สร้าง/revoke Coupon และเห็น audit trail ได้
- RLS ป้องกัน customer อ่าน/แก้ข้อมูลของคนอื่น
- Launcher ไม่เริ่ม proxy หากไม่มี entitlement หรือ runtime ที่ได้รับอนุญาต
- CI ผ่าน และ repository ไม่มี secret หรือ proprietary runtime
