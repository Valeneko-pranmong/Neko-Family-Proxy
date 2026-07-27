# คู่มือตั้งค่า SMTP สำหรับ Supabase (Production)

Supabase ใช้ SMTP สำหรับส่งอีเมล **password reset** และ **email confirmation**
ระบบ built-in ของ Supabase มี rate limit ต่ำ (3-4 ฉบับ/ชม.) จึงควรตั้ง custom SMTP

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

### 3. ตั้งค่า Redirect URL

ใน **Authentication → URL Configuration**:

- **Site URL**: `https://your-domain.com/reset-password/`
- **Redirect URLs** (เพิ่ม):
  - `https://your-domain.com/reset-password/`
  - `https://valeneko-pranmong.github.io/Neko-Family-Proxy/reset-password/`

> ⚠️ URL ต้องตรงกับที่ host ไฟล์ `docs/reset-password/index.html`

### 4. ปรับ Email Template

ใน **Authentication → Email Templates → Reset Password**:

```html
<h2>ตั้งรหัสผ่านใหม่ — Neko Family Proxy</h2>
<p>มีคนขอตั้งรหัสผ่านใหม่สำหรับบัญชีของคุณ</p>
<p>
  <a href="{{ .SiteURL }}/reset-password/#access_token={{ .Token }}&type=recovery">
    คลิกที่นี่เพื่อตั้งรหัสผ่านใหม่
  </a>
</p>
<p>ลิงก์นี้จะหมดอายุใน 1 ชั่วโมง</p>
<p>หากคุณไม่ได้ขอ กรุณาเพิกเฉยอีเมลนี้</p>
```

### 5. Deploy Redirect Page

ไฟล์ `docs/reset-password/index.html` ต้อง deploy ไปที่ URL ที่ตั้งใน Redirect URL

**วิธีที่ 1: GitHub Pages**
1. ไปที่ repo Settings → Pages
2. Source: `Deploy from a branch`
3. Branch: `main`, folder: `/docs`
4. URL จะเป็น: `https://valeneko-pranmong.github.io/Neko-Family-Proxy/reset-password/`

**วิธีที่ 2: Netlify / Vercel**
- ชี้ root ไปที่ `docs/` แล้วตั้ง custom domain

### 6. อัปเดต Anon Key ใน Redirect Page

แก้ไฟล์ `docs/reset-password/index.html`:
```js
const SUPABASE_ANON_KEY = 'eyJhbGci...your_real_key_here';
```

### 7. ทดสอบ

1. ในแอป → แท็บ "ลืมรหัสผ่าน" → กรอกชื่อผู้ใช้ → กด "ส่งลิงก์ตั้งรหัสผ่านใหม่"
2. เช็คอีเมล (recovery_email ของผู้ใช้นั้น)
3. คลิกลิงก์ → หน้าเว็บจะเปิด → กรอกรหัสผ่านใหม่
4. กลับไปแอป → เข้าสู่ระบบด้วยรหัสผ่านใหม่

### Troubleshooting

| ปัญหา | แก้ไข |
|--------|-------|
| ไม่ได้รับอีเมล | ตรวจ SMTP credentials, เช็ค spam folder |
| ลิงก์หมดอายุ | เพิ่ม token expiry ใน Auth Settings (default 1 ชม.) |
| "ลิงก์ไม่ถูกต้อง" | ตรวจ Redirect URL ว่าตรงกับ URL ที่ host |
| rate limit | เพิ่ม minimum interval, หรือเปลี่ยน SMTP provider |