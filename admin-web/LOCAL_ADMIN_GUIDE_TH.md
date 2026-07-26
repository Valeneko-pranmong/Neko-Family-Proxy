# คู่มือ Neko Control แบบรันเอง

เวอร์ชันนี้ถอด ChatGPT login ออกแล้ว และใช้ Local Admin API บนเครื่องผู้ดูแล
หน้าเว็บที่ส่งมอบคือ `standalone/dist/neko-control.html`

## ตั้งค่าครั้งแรก

1. เปิด PowerShell ในโฟลเดอร์ `admin-web`
2. รัน `.\start-admin.ps1` หนึ่งครั้ง
3. เปิดไฟล์ `.env` ที่ถูกสร้างขึ้น
4. ตั้งค่าอย่างน้อย:

```text
SUPABASE_URL=https://miikoutrnxsunbndecqh.supabase.co
SUPABASE_SECRET_KEY=ใส่ Supabase Secret Key
```

ห้ามส่งไฟล์ `.env` ให้ผู้อื่น และห้ามใส่ Secret Key ลงใน `neko-control.html`

## เริ่มใช้งาน

รัน:

```powershell
.\start-admin.ps1
```

จากนั้นเปิด:

```text
http://127.0.0.1:8787/
```

ระบบจะถาม Email และ Password ของบัญชี Supabase Auth จากนั้นตรวจ
`public.profiles.role` ของบัญชีนั้น ถ้าเป็น `admin` จะเปิดหน้า Control Room

## โครงสร้างที่แก้ไขได้

- `standalone/src/sections/` — แต่ละหน้าของเว็บ
- `standalone/src/ui/` — ตาราง ปุ่ม toast และ layout
- `standalone/src/api.js` — จุดเรียก Local Admin API
- `admin-api/src/routes/admin.mjs` — คำสั่งที่อ่าน/แก้ไข Supabase
- `admin-api/src/auth.mjs` — Supabase Email/Password, role และ local session

หลังแก้ frontend ให้รัน:

```powershell
npm run build:standalone
```

ผลลัพธ์จะอยู่ที่ `standalone/dist/neko-control.html` เพียงไฟล์เดียว

## ขอบเขตความปลอดภัย

- API เปิดที่ `127.0.0.1` เท่านั้น
- อย่าเปลี่ยน `ADMIN_HOST` เป็น `0.0.0.0`
- อย่าเปิด port 8787 ออกอินเทอร์เน็ต
- Session ถูกเก็บใน memory และหายเมื่อปิด server
- บัญชีที่ `profiles.role` ไม่ใช่ `admin` จะเข้า Control Room ไม่ได้
