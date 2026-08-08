# คู่มือ Debug Console ของ Neko Launcher

เอกสารนี้อธิบายโหมดวินิจฉัยสำหรับติดตามว่า Launcher กำลังทำอะไร เหตุใด
`NekoProxyCore` ยังไม่เริ่ม และ Core หยุดที่ขั้นตอนใด โหมดนี้ใช้สำหรับพัฒนาและ
แก้ปัญหาเท่านั้น ไม่ได้ข้าม authentication, entitlement, launch permit หรือ
authorization gate ใด ๆ

## เปิดใช้งาน

ต้อง build `launcher/dist/NekoLauncher.exe` ก่อน ตาม
[คู่มือ build](build-windows-executable.md)

จากโฟลเดอร์ `launcher` ให้ดับเบิลคลิก `NekoLauncherDebugConsole.cmd` หรือรัน:

```powershell
.\NekoLauncherDebugConsole.cmd
```

สคริปต์จะเปิดหน้าต่าง Console, เรียก `NekoLauncher.exe --debug` และแสดงรายการ
ใหม่จาก `debug.log` แบบต่อเนื่อง อาร์กิวเมนต์ `--debug` ใช้กับ packaged EXE
เพราะสามารถผ่าน Windows UAC elevation boundary ได้

การรันจาก source ยังเปิดด้วย environment variable ได้:

```powershell
$env:NEKO_DEBUG = "1"
python -m neko_launcher.main
```

Launcher อนุญาตให้ทำงานครั้งละหนึ่ง instance หากมีตัวปกติค้างอยู่ ให้ Exit
จากไอคอนใน System Tray ก่อนเปิด Debug Console

## ลำดับสถานะหลัก

| สถานะ | ความหมาย |
| --- | --- |
| `LAUNCHER_START` | Launcher เริ่มทำงานโดยเปิด debug แล้ว |
| `WAITING_FOR_GAME` | ยังไม่พบ `pso2.exe`; Core ยังไม่ควรเริ่ม |
| `GAME_PROCESS_DETECTED` | ตรวจพบ `pso2.exe` แล้ว |
| `PROXY_START_BLOCKED` | เงื่อนไขก่อนเริ่ม Core ไม่ผ่าน เช่น ยังไม่ login, ไม่มี session หรือ entitlement ไม่ active |
| `PROXY_START_REQUESTED` | เงื่อนไขเบื้องต้นผ่านและ Launcher เริ่ม orchestration |
| `COMMAND_VALIDATE` | ตรวจคำสั่งเริ่มงาน |
| `ACCESS_CONTEXT_VALIDATE` | ตรวจ authentication, session และ entitlement context |
| `TARGET_WAIT` / `TARGET_RECHECK` | รอและตรวจ identity ของ `pso2.exe` ซ้ำ |
| `HOST_START` | พยายามเปิด `NekoProxyCore.exe` |
| `CONTROL_CHANNEL_WAIT` | รอ named-pipe control channel จาก Core |
| `CHALLENGE_REQUEST` / `TARGET_BIND` | ทำ challenge และผูก Core กับ process เป้าหมาย |
| `PERMIT_REQUEST` | ขอ launch permit จากบริการที่ได้รับอนุญาต |
| `AUTHORIZED_START` | ส่งคำสั่งเริ่มที่ได้รับ authorization แล้ว |
| `RUNNING_VERIFY` | ตรวจว่า Core เข้าสู่สถานะทำงานจริง |
| `CLEANUP` | คืนทรัพยากรหลังจบหรือเกิดข้อผิดพลาด |

Console จะแสดง `PID`, `Exit Code`, `WinError` และ exception ที่ sanitize แล้วเมื่อ
มีข้อมูล หาก Core ปิดทันที ให้ตรวจ `Exit Code` พร้อม `core_stderr-*.log` เป็นอันดับแรก

## ไฟล์ log

ไฟล์ทั้งหมดอยู่ใต้:

```text
%LOCALAPPDATA%\NEKO FAMILY\logs
```

- `debug.log` — timeline ของ Launcher และ Core orchestration
- `core_stdout-<attempt-id>.log` — standard output ของ Core ในแต่ละครั้ง
- `core_stderr-<attempt-id>.log` — standard error ของ Core ในแต่ละครั้ง

ในหน้า Dashboard เมื่อเปิด debug จะมีปุ่ม **DEBUG MODE** ในกล่อง Connection
Status ภายในหน้าต่างมี **Copy Debug**, **Open Logs** และ **Retry ProxyCore**

## วิเคราะห์กรณี Core ไม่เริ่ม

1. `WAITING_FOR_GAME` หมายถึงยังไม่พบ process ชื่อ `pso2.exe` ซึ่งเป็นพฤติกรรมปกติ
2. `PROXY_START_BLOCKED` ให้ดูค่า `reason` แล้วแก้ authentication, session หรือ entitlement
3. หยุดที่ `HOST_START` ให้ตรวจ path ของ Core, สิทธิ์ไฟล์ และ `WinError`
4. หยุดที่ `CONTROL_CHANNEL_WAIT` ให้ตรวจว่า Core เปิด named pipe ตาม contract หรือไม่
5. หยุดที่ `PERMIT_REQUEST` ให้ตรวจ network, session และ permit service โดยห้ามใส่ secret ลงใน log
6. มี `Exit Code` ให้เปิด stdout/stderr ของ attempt เดียวกันเพื่อหาสาเหตุจาก Core

## ข้อควรระวัง

ตัว sanitize จะปิดบัง token, password และรูปแบบ secret ที่รู้จัก แต่ log ยังอาจมี
path, PID และข้อมูลวินิจฉัยของเครื่อง ห้ามแนบ log สู่ issue หรือส่งต่อภายนอกก่อน
ตรวจเนื้อหา โหมด debug ต้องไม่ถูกใช้เป็น authorization bypass หรือ release gate
