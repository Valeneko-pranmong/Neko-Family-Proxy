# Neko Control Room

ระบบหลังบ้านแบบรันเองบนเครื่อง แยกจากบัญชี ChatGPT และตรวจสิทธิ์ผู้ดูแลผ่าน Supabase

## โครงสร้าง

- `standalone/src/` — หน้าเว็บ แยก HTML, CSS และ JavaScriptเพื่อดูแลโค้ดง่าย
- `standalone/dist/neko-control.html` — ไฟล์ HTML เดียวที่ build พร้อมใช้งาน
- `admin-api/src/` — Local API และระบบ session
- `scripts/build-standalone.mjs` — รวม source เป็น HTML ไฟล์เดียว
- `tests/admin-api.test.mjs` — ทดสอบ login และสิทธิ์ admin

## เริ่มใช้งาน

1. กำหนด `SUPABASE_URL` และ `SUPABASE_SECRET_KEY` ในไฟล์ `.env`
2. ตรวจว่าผู้ใช้มีบัญชี Email/Password ใน Supabase Auth
3. ตรวจว่า `public.profiles` มีแถวที่ `id` ตรงกับผู้ใช้ และ `role` เป็น `admin`
4. เปิด PowerShell ที่โฟลเดอร์ `admin-web` แล้วรัน:

```powershell
.\start-admin.ps1
```

5. เปิด `http://127.0.0.1:8787`

ระบบจะตรวจ Email/Password กับ Supabase Auth และอนุญาตเฉพาะผู้ใช้ที่มี `role = admin` เท่านั้น

## คำสั่งสำคัญ

```powershell
npm run build
npm test
npm start
```

อ่านวิธีตั้งค่าเพิ่มเติมได้ที่ `LOCAL_ADMIN_GUIDE_TH.md`
