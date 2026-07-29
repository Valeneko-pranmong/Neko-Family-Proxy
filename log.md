# Change Log

## 29 กรกฎาคม 2026 — เปลี่ยนแผน Password Recovery

### สิ่งที่ทำในรอบนี้

- ตรวจ flow ปัจจุบันของ Launcher, Supabase schema และ Admin Tool แบบ
  read-only
- ยืนยันว่า Admin Tool มี server-side secret key และ dependency
  `@supabase/supabase-js` สำหรับเรียก Auth Admin API
- ยืนยันว่า Launcher มี application/gateway method `change_password()` อยู่แล้ว
  แต่ยังไม่มี UI ให้ผู้ใช้เรียก
- ยืนยันว่า `profiles.recovery_email` รับ `NULL` จึงสามารถหยุดส่ง recovery
  metadata จาก Launcher ได้ก่อน โดยยังไม่ต้องทำ destructive migration
- ตัดสินใจยกเลิก email reset, Send Email Hook และ email provider
- เลือก Admin-assisted Password Reset เป็นวิธีหลัก
- กำหนดให้รักษา Auth user ID และ License เดิม ไม่ลบบัญชีในการ reset ปกติ
- กำหนดให้ Admin Tool สร้าง temporary password ฝั่ง server, revoke Launcher
  sessions และแสดง password เพียงครั้งเดียว
- กำหนดให้ Launcher ใหม่ตัด Recovery Email/ลืมรหัสผ่าน และเพิ่ม UI
  เปลี่ยนรหัสผ่านหลัง Login

### ไฟล์เอกสารที่เปลี่ยน

- เขียน `สิ่งที่ต้องทำต่อไป.md` ใหม่ทั้งหมดเป็น workflow และ implementation
  handoff สำหรับ Launcher/Supabase
- สร้าง
  `D:\Neko-Family-Proxy admin tool\handoff admin team.md`
  สำหรับทีม Admin Tool
- สร้าง `log.md` ไฟล์นี้

### สิ่งที่ยังไม่ได้ทำ

- ยังไม่ได้แก้ source code ของ Launcher
- ยังไม่ได้แก้ source code ของ Admin Tool
- ยังไม่ได้สร้างหรือ apply database migration
- ยังไม่ได้เปลี่ยน Supabase Auth configuration
- ยังไม่ได้ปิด Vercel reset page
- ยังไม่ได้ build Launcher EXE ใหม่
- ยังไม่ได้ deploy Admin Tool หรือ Launcher รอบใหม่
- ยังไม่ได้ commit หรือ push Git

### สถานะที่ต้องระวัง

- Launcher release candidate ปัจจุบันยังมี Recovery Email และแท็บ
  “ลืมรหัสผ่าน”
- Vercel reset page ยัง online แต่ไม่มี Send Email Hook/provider ที่ส่งอีเมลจริง
- working tree ของ repository หลักมีการแก้ไขจากงานก่อนหน้าที่ยังไม่ได้ commit
- ควรทำ Admin Tool ให้พร้อมก่อนปล่อย Launcher ที่ตัด email reset

### ลำดับงานถัดไป

1. ทีม Admin Tool ทำตาม `handoff admin team.md`
2. ทดสอบ password reset กับ disposable customer
3. ทีม Launcher ทำตาม `สิ่งที่ต้องทำต่อไป.md`
4. build และทดสอบ EXE ใหม่
5. ทดสอบ end-to-end ทั้ง Admin Tool และ Launcher
6. deploy/release
7. บันทึก deployment ID, artifact hash และผลทดสอบเพิ่มในไฟล์นี้

## 29 กรกฎาคม 2026 — Implement และ deploy Admin-assisted Password Reset

### งานที่เสร็จ

- Admin Tool เพิ่มคำสั่ง `reset_user_password` ฝั่ง server:
  - ตรวจ admin session/RBAC และ target `customer`
  - บังคับยืนยัน Username
  - revoke Launcher sessions ก่อนเปลี่ยน Auth password
  - สร้างรหัสชั่วคราว 20 ตัวด้วย CSPRNG
  - เรียก Supabase Auth Admin API โดยไม่เผย secret ให้ browser
  - บันทึก `admin_password_reset` โดยไม่มี plaintext password
  - แสดงรหัสชั่วคราวครั้งเดียวและล้าง DOM/state เมื่อปิด dialog
- Supabase production apply migration
  `add_admin_password_reset_audit_event` สำเร็จ และตรวจ constraint แล้ว
- Admin Tool deploy production สำเร็จ:
  - URL: `https://neko-control-room.vercel.app`
  - Deployment: `dpl_Et3bAJzx4u3WiWEsRCghGFe9GZJg`
  - Git commit: `89d13f3`
  - สถานะ: READY
  - หลัง deploy: health 200, unauthenticated API 401, runtime errors 0
- Launcher ตัด Recovery Email, email reset method, reset redirect config และแท็บ
  “ลืมรหัสผ่าน” ออก
- Launcher เพิ่มข้อความให้ติดต่อผู้ดูแลและหน้าเปลี่ยนรหัสผ่านหลัง Login
- Launcher build ใหม่:
  - Path: `launcher/dist/NekoLauncher.exe`
  - Size: `132609853` bytes
  - SHA-256:
    `06A9624E494A268023FA4B4757DED7651FA8090580B7A8E6C85D0AE4C8EE5417`
  - Authenticode: NotSigned

### ผลทดสอบ

- Admin Tool: `npm test` ผ่าน `5/5`
- Launcher Ruff: ผ่าน
- Launcher unit tests: `32 passed, 2 deselected`
- Launcher EXE startup smoke test บน Windows เครื่องพัฒนา: ผ่าน
- Supabase advisors หลัง migration:
  - ไม่มี error ใหม่
  - มี WARN เดิมเรื่อง Leaked Password Protection ปิดอยู่
  - มี INFO เดิมเรื่อง RLS enabled โดยไม่มี client policy บนตารางภายใน

### งานที่ต้องทำก่อนแจกจริง

- รัน `scripts/e2e-password-reset.mjs` ด้วย production secret ที่เข้าถึงได้ หรือ
  ทดสอบด้วย admin login จริงและ disposable customer
- ทดสอบ EXE บน Windows เครื่องสะอาด และยืนยัน Npcap/`packet.dll`
- code-sign EXE ถ้ามี certificate
- เมื่อยืนยันว่า client เก่าเลิกใช้งานแล้วจึงปิด/ลบ Vercel reset page และทำ
  database cleanup migration เป็นงานแยก
