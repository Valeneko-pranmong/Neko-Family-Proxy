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
- เก็บ Launcher รุ่นแรกไว้ที่ `original-code/v1/` เพื่ออ้างอิงเท่านั้น
- รวม `admin-web/` เป็นโฟลเดอร์ปกติของ repository หลัก
- ไม่ใส่ `ProxyCore/` หรือ `ProxyCore.rar` ใน GitHub โดยเด็ดขาด

## ทำเสร็จแล้ว

### โครงสร้าง Source Control

- ย้าย `NekoLauncher.py` และ `NekoLauncher.spec` รุ่นเดิมไปไว้ใน
  `original-code/v1/`
- Legacy archive ยังมี endpoint และวิธีเก็บรหัสผ่านรุ่นเก่า จึงห้ามนำกลับมาใช้
  และต้องตรวจ/ลบก่อนเปิด repository เป็น public
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
- มี unit tests สำหรับ controller, event bus, workflow, Supabase adapter,
  secure storage และ installation identity
- ต่อ Supabase Auth สำหรับสมัครสมาชิก/Login/Logout/restore session แล้ว
- ต่อ Coupon, entitlement, session claim/heartbeat/release และ guard ก่อนเปิด
  ProxyCore แล้ว
- มี UI ภาษาไทยสำหรับ Login/Register/Redeem Coupon และสถานะสิทธิ์ใช้งาน
- มี PyInstaller spec และ Windows installer/release workflow โดยไม่รวม
  `ProxyCore`

### Admin Web

- แปลหน้า Admin เป็นภาษาไทยแล้ว
- เปลี่ยนธีมจาก dark mode เป็นพื้นขาว ตัดชมพูอ่อน และรองรับหน้าจอมือถือ
- เพิ่มหน้า `/guide` เป็นคู่มือการใช้งานภาษาไทย
- เพิ่มคู่มือแบบไฟล์ Markdown ที่ `admin-web/USER_GUIDE_TH.md`
- ทดสอบด้วย `npm run build`, `npm run lint` และ `npm test` ผ่านทั้งหมด
- อัปเดต Next.js เป็น 16.2.11 และ pin patched PostCSS/Sharp; production audit
  ไม่มี vulnerability
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

ตรวจสอบกับ project จริงแล้วเมื่อ 25 กรกฎาคม 2026:

- ประวัติ migration ฝั่ง local ตรงกับ project จริง
- Apply migration hardening สำหรับ concurrent license update, สิทธิ์เขียนตาราง
  และ foreign-key index แล้ว
- เปิด `launcher` schema ผ่าน Data API แล้ว
- Security advisor ไม่มีรายการระดับ WARN/ERROR
- ยังไม่มี test account หรือข้อมูลทดสอบ จึงยังต้องรัน
  `supabase/SECURITY_TEST_PLAN.md` ก่อนเปิด UI ให้ผู้ใช้

## สถานะที่ยังไม่เสร็จ / ข้อจำกัดปัจจุบัน

1. Launcher flow ถูกต่อครบใน source และ unit tests แล้ว แต่ live integration
   test ยังไม่ได้รัน เนื่องจาก repository ไม่มี disposable test credentials
   หรือคูปองทดสอบ
2. Migration Coupon (`20260725110225_create_coupon_redemption.sql`) ถูก apply
   ไปยัง Supabase project และเปิด Data API แล้ว แต่ยังต้องทดสอบ RLS และ
   concurrency ด้วย test account ให้ครบก่อนเปิดใช้ Coupon UI
3. `admin-web/` มี source พร้อมใช้งานและ build ผ่าน แต่ต้องตั้งค่า secret ฝั่ง server,
   allowlist, production URL และทดสอบสิทธิ์ Admin ให้ครบ
4. `ProxyCore` ไม่อยู่ใน repository ตามการออกแบบ ต้องจัดส่งผ่าน controlled
   channel ตาม `RUNTIME_DISTRIBUTION.md` และทดสอบ runtime จริงแยกต่างหาก
5. Windows executable build และ smoke test ผ่านในเครื่อง local แล้ว แต่
   installer workflow ยังต้องรันบน GitHub Actions ครั้งแรก และ artifact
   รุ่นแรกยังไม่ได้ code-sign
6. `original-code/v1/` ยังมี legacy endpoint และ plaintext password
   persistence ห้ามเผยแพร่เป็น public ก่อน sanitize/rotate
7. Full npm audit ยังมีรายการจากเครื่องมือ dev แต่
   `npm audit --omit=dev --audit-level=high` สำหรับ production ผ่านแล้ว

## ลำดับงานถัดไปที่แนะนำ

### P0 - ความปลอดภัยและฐานข้อมูล

1. ตรวจสอบไฟล์ที่จะเผยแพร่ด้วย repository safety check และ sanitize/rotate
   legacy endpoint ใน `original-code/v1/`
2. ยืนยัน migration ที่อยู่บน Supabase project จริงและให้ประวัติ local ตรงกัน
3. ทดสอบ migration Coupon ที่ apply แล้วด้วย test account
4. เปิด `launcher` schema ใน Supabase Data API ตามเอกสาร
   `supabase/README.md`
5. ทดสอบ RLS, role escalation, coupon replay, concurrent redeem และ
   session takeover ด้วย test account

### P1 - ต่อระบบใช้งานจริง

1. ใส่ publishable key ในเครื่องทดสอบและรัน Launcher กับ Auth project จริง
2. ยืนยัน email confirmation, session restore และ sign-out บน Windows
3. ยืนยัน heartbeat/revoke เมื่อ Login ซ้ำจาก client ที่สอง
4. ยืนยัน Launcher ไม่เริ่ม ProxyCore เมื่อ license หมดอายุหรือ session ถูก revoke
5. ตั้งค่า Admin server secret, allowlist และ production URL ผ่านระบบ hosting
6. ทดสอบ Admin role, mutation RPC และ audit trail ด้วย disposable admin

### P2 - ทดสอบและเตรียมส่งมอบ

1. รัน manual `Supabase integration` workflow ด้วย disposable account และ
   fresh coupon เพื่อยืนยัน Auth, Coupon replay และ single-session บน project จริง
2. รัน `CI` workflow บน Pull Request แรกและแก้ความต่างของ GitHub runner หากมี
3. รัน `Windows release` แบบ manual เพื่อตรวจ installer artifact และ checksum
4. กำหนด code-signing certificate ก่อน release ให้ลูกค้าจริง
5. ตรวจสอบโลโก้ ธีมชมพู ข้อความ และ runtime จริงบน Windows ก่อน tag release
6. เปิด Pull Request ให้ทีม review แล้วจึงสร้าง tag `v*`

## คำสั่งสำหรับผู้รับช่วงงาน

ตรวจสถานะ:

```powershell
git status --short --untracked-files=all
git add --dry-run .
```

รัน Launcher checks:

```powershell
Set-Location launcher
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q -m "not integration"
```

รัน Admin web:

```powershell
Set-Location admin-web
npm ci
npm run lint
npm test
npm audit --omit=dev --audit-level=high
```

ข้อควรระวัง:

- ห้าม commit `.env`, service-role key, private key, customer data หรือ
  `ProxyCore` ทุกกรณี
- อย่าใช้ `git add -f` กับไฟล์ที่ถูก ignore
- อย่านำ legacy code จาก `original-code/v1/` กลับมาใช้ และตรวจ migration จริง
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
