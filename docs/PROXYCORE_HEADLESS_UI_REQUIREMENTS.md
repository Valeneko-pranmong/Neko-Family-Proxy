# พฤติกรรมการเปิด ProxyCore/Netch เมื่อเริ่มเกม

เอกสารนี้บันทึกข้อกำหนดล่าสุดหลังยกเลิกการซ่อน ProxyCore/Netch
เพื่อให้ NekoLauncher ทำงานเรียบง่ายและไม่ค้างเป็น process ซอมบี้

## ข้อกำหนดปัจจุบัน

1. NekoLauncher ต้องมี System Tray ต่อไป
2. การซ่อนหรือแสดง NekoLauncher เป็นการควบคุมของผู้ใช้
3. เมื่อพบ `pso2.exe` ให้เปิด `ProxyCore.exe`/Netch แบบหน้าต่างปกติ
4. Launcher ไม่ต้องซ่อน ย่อ หรือย้ายหน้าต่าง Netch
5. Launcher ไม่ต้องสร้าง hidden desktop, window watcher หรือจัดการ tray ของ Netch
6. หลังเปิดสำเร็จ ให้ผู้ใช้ควบคุมและปิด Netch เอง
7. เมื่อเกมหรือ Launcher ปิด ไม่ต้องสั่งปิด Netch อัตโนมัติ

## Flow

```text
พบ pso2.exe
 └─ NekoLauncher เรียก ProxyCore.exe ด้วย Popen
    ├─ ไม่ส่ง SW_HIDE
    ├─ ไม่ส่ง CREATE_NO_WINDOW
    ├─ ไม่กำหนด STARTUPINFO.lpDesktop
    ├─ ไม่รอ startup stability
    └─ Netch แสดงหน้าต่างตามปกติ
```

## กลไกที่ยกเลิก

- `CreateDesktopW` และ `CloseDesktop`
- hidden/isolated Windows desktop
- PID-based window hiding
- window polling watcher
- การค้นหาและปิด orphan ProxyCore
- การตรวจ hash ของ process ที่กำลังทำงาน
- startup stability wait
- lifecycle diagnostic log
- background proxy start ที่เพิ่มขึ้นเพื่อรองรับกลไกซ่อน

## การจัดการ process

`ProxyProcessManager.start()` เก็บ `Popen` เฉพาะเพื่อไม่เปิด process ซ้ำ
ใน Launcher instance เดียวกัน

`ProxyProcessManager.stop()` ปล่อย reference ของ Launcher เท่านั้น
โดยไม่ใช้ `taskkill`, `terminate()` หรือ `kill()` กับ Netch

## Acceptance criteria

- เกมเริ่มแล้ว Netch เปิดและมองเห็นได้ตามปกติ
- NekoLauncher ไม่เปลี่ยนสถานะหน้าต่างเองเมื่อเกมเริ่ม
- NekoLauncher ยังตอบสนองและใช้ System Tray ได้
- ปิด NekoLauncher แล้ว process ของ Launcher ต้องจบ
- เปิด NekoLauncher ใหม่ได้โดยไม่ต้อง restart Windows
- Netch ที่เปิดอยู่ไม่ถูก Launcher ปิด

## หมายเหตุด้านความลับ

ข้อกำหนดนี้ให้ความสำคัญกับความเสถียรมากกว่าการซ่อนรายละเอียด ProxyCore
ผู้ใช้จึงสามารถเห็นชื่อ หน้าต่าง และค่าที่ Netch แสดงได้
