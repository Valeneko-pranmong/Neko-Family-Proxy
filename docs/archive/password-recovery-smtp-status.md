# สถานะระบบอีเมลกู้คืนรหัสผ่าน

> **HISTORICAL.** ระบบนี้เลิกใช้แล้ว เอกสารปัจจุบันอยู่ที่
> [`../../launcher/README.md`](../../launcher/README.md) และ
> [`../../supabase/README.md`](../../supabase/README.md)

ระบบไม่ได้ใช้ SMTP, Send Email Hook, Resend หรือหน้าเว็บ reset password แล้ว

เมื่อผู้ใช้จำรหัสผ่านไม่ได้ ให้ติดต่อผู้ดูแลระบบ ผู้ดูแลจะตรวจสอบตัวตนและใช้
Admin Tool สร้างรหัสผ่านชั่วคราวฝั่ง server จากนั้นผู้ใช้เข้าสู่ระบบและเปลี่ยน
เป็นรหัสผ่านของตนเองใน Launcher

ข้อกำหนดด้านความปลอดภัย:

- ห้ามใส่ Supabase secret key ใน Launcher หรือ browser bundle
- ห้ามรับรหัสผ่านใหม่จาก browser ใน Admin-assisted reset รุ่นแรก
- ต้อง revoke Launcher session เดิมก่อนเปลี่ยน Auth password
- ห้ามบันทึกรหัสผ่านชั่วคราวใน log, audit, database หรือ browser storage
- `profiles.recovery_email` ยังไม่ถูกลบใน release นี้เพื่อรองรับ rollback

ไฟล์ handoff เดิมถูกลบแล้ว เพราะ workflow ถูกนำไปใช้และข้อมูลปัจจุบันถูกรวมใน
เอกสาร Launcher และ Supabase ข้างต้น
