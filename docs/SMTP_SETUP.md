# คู่มือตั้งค่า SMTP สำหรับ Supabase (Production)

Supabase ใช้ SMTP สำหรับส่งอีเมล **password reset** และ **email confirmation**
ระบบ built-in ของ Supabase มี rate limit ต่ำและไม่เหมาะกับ production
จึงควรตั้ง Custom SMTP ก่อนเปิดใช้จริง

> ตั้งแต่ 3 มิถุนายน 2026 โปรเจกต์ Free tier ใหม่ที่ใช้ SMTP เริ่มต้นของ
> Supabase ไม่สามารถปรับ Email Template ได้ ต้องตั้ง Custom SMTP ก่อน

## ขั้นตอน

### 1. เลือก SMTP Provider

| Provider | Free Tier | หมายเหตุ |
|----------|-----------|----------|
| **Resend** | 3,000 ฉบับ/เดือน | แนะนำ — setup ง่าย |
| **Brevo (Sendinblue)** | 300 ฉบับ/วัน | ฟรีเยอะ |
| **Mailgun** | 1,000 ฉบับ/เดือน (3 เดือนแรก) | enterprise-grade |
| **AWS SES** | $0.10/1,000 ฉบับ | ถูกสุดสำหรับ volume สูง |
| **Gmail SMTP** | 500 ฉบับ/วัน | ไม่แนะนำสำหรับ production |

### 2. ตั้งค่าใน Supabase Dashboard

1. ไปที่ **Project Settings → Authentication → SMTP Settings**
2. เปิด **Enable Custom SMTP**
3. กรอกข้อมูล:

| ฟิลด์ | ตัวอย่าง (Resend) |
|-------|-------------------|
| **Sender email** | `noreply@nekofamily.com` |
| **Sender name** | `Neko Family Proxy` |
| **Host** | `smtp.resend.com` |
| **Port** | `465` |
| **Username** | `resend` |
| **Password** | `re_xxxxxxxxxxxx` (API Key) |
| **Minimum interval** | `30` (วินาที) |

4. กด **Save**

### 3. Deploy หน้า reset บน Vercel

1. สร้าง Vercel Project จาก repository นี้
2. ตั้ง **Root Directory** เป็น `docs`
3. ตั้ง Framework เป็น **Other**
4. ไม่ต้องใช้ build command
5. สร้าง Preview Deployment และทดสอบหน้า
   `/reset-password/` ก่อน promote เป็น Production
6. จด URL production แบบถาวร เช่น
   `https://neko-family-reset.vercel.app/reset-password/`

ไฟล์ `reset-password/config.js` มีได้เฉพาะ Supabase URL และ Publishable key
ซึ่งเป็น public client configuration ห้ามใส่ `SUPABASE_SECRET_KEY`,
service-role key หรือ SMTP credential

### 4. ตั้งค่า Redirect URL

ใน **Authentication → URL Configuration**:

- **Site URL**: URL production ของหน้า reset
- **Redirect URLs**: เพิ่ม URL production แบบตรง path ทุกตัวอักษร
- Preview URL ใช้ทดสอบชั่วคราวได้ แต่ห้ามตั้งเป็นค่าถาวร

จากนั้นใส่ URL production เดียวกันใน
`launcher/src/neko_launcher/infrastructure/defaults.py` ที่
`PASSWORD_RESET_REDIRECT_URL` แล้ว build Launcher ใหม่

### 5. ปรับ Email Template

ใน **Authentication → Email Templates → Reset Password**:

```html
<h2>ตั้งรหัสผ่านใหม่ — Neko Family Proxy</h2>
<p>มีคนขอตั้งรหัสผ่านใหม่สำหรับบัญชีของคุณ</p>
<p>
  <a href="{{ .ConfirmationURL }}">
    คลิกที่นี่เพื่อตั้งรหัสผ่านใหม่
  </a>
</p>
<p>หากคุณไม่ได้ขอ กรุณาเพิกเฉยอีเมลนี้</p>
```

ใช้ `ConfirmationURL` เพื่อให้ Supabase ตรวจ token ก่อน redirect ไปยัง URL
ที่ Launcher ส่งใน `redirect_to` ไม่ควรประกอบ access token เองใน template

### 6. ทดสอบ

1. ในแอป → แท็บ "ลืมรหัสผ่าน" → กรอกชื่อผู้ใช้ → กด "ส่งลิงก์ตั้งรหัสผ่านใหม่"
2. เช็คอีเมลของบัญชีทดสอบที่ย้าย Auth email เป็นอีเมลจริงแล้ว
3. คลิกลิงก์ → หน้าเว็บจะเปิด → กรอกรหัสผ่านใหม่
4. กลับไปแอป → เข้าสู่ระบบด้วยรหัสผ่านใหม่

### Troubleshooting

| ปัญหา | แก้ไข |
|--------|-------|
| ไม่ได้รับอีเมล | ตรวจ SMTP credentials, เช็ค spam folder |
| ลิงก์หมดอายุ | เพิ่ม token expiry ใน Auth Settings (default 1 ชม.) |
| "ลิงก์ไม่ถูกต้อง" | ตรวจ Redirect URL ว่าตรงกับ URL ที่ host |
| rate limit | เพิ่ม minimum interval, หรือเปลี่ยน SMTP provider |
| กดแล้วไม่มีอีเมลแต่ UI แจ้งสำเร็จ | เป็นข้อความแบบ anti-enumeration; ตรวจ Auth/SMTP logs และยืนยันว่า Auth email ถูกย้ายเป็นอีเมลจริง |
