# คู่มือ Build `NekoLauncher.exe`

> **สถานะ: CURRENT — reviewed 8 August 2026.** คู่มือนี้อธิบายการ build และ
> smoke test เท่านั้น การ build สำเร็จไม่ถือเป็น production approval.

เอกสารนี้ใช้สำหรับผู้พัฒนาที่ต้องการสร้างไฟล์ Windows แบบ one-file ด้วย
PyInstaller

## 1. สิ่งที่ต้องเตรียม

Build บน Windows และใช้ Python `3.11` ขึ้นไป

ไฟล์/โฟลเดอร์ที่ต้องมี:

| รายการ | ตำแหน่ง | ใช้ทำอะไร |
| --- | --- | --- |
| source code | `launcher/src/neko_launcher/` | โค้ดโปรแกรม |
| PyInstaller spec | `launcher/NekoLauncher.spec` | กำหนดวิธีสร้าง EXE |
| package/dependencies | `launcher/pyproject.toml` | รายการ package ที่ต้องติดตั้ง |
| ไอคอน | `icon_app.ico` | ไอคอนของ EXE |
| โลโก้ | `image_11.png` | รูปที่แสดงในโปรแกรม |
| ฟอนต์ภาษาไทย | `Sarabun-Regular.ttf`, `Sarabun-Bold.ttf` | ฟอนต์ Sarabun สำหรับแสดงผล UI |
| ProxyCore ที่ได้รับอนุมัติ | `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\` | runtime ภายนอกที่ทีมจัดการและแจกเอง |
| Supabase client configuration | `launcher/src/neko_launcher/infrastructure/defaults.py` | URL และ publishable key |

ProxyCore เป็น runtime ภายนอกที่แจกผ่านช่องทางควบคุมของทีมเท่านั้น ห้ามนำ
runtime ที่ไม่ทราบแหล่งที่มาหรือไม่มี checksum มาใช้ และห้ามวาง
ProxyCore หรือ V2Ray ลงใน PyInstaller payload ของ `NekoLauncher.exe`

## 2. เตรียม Python environment

เปิด PowerShell ที่ root ของ repository:

```powershell
Set-Location D:\Neko-Family-Proxy
Set-Location .\launcher

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,release]"
```

ถ้า PowerShell ไม่อนุญาตให้ activate environment ให้รัน:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

## 3. ตั้งค่า Supabase

ค่า Supabase URL และ publishable key อยู่ใน
`launcher/src/neko_launcher/infrastructure/defaults.py` แล้ว ไม่ต้องสร้าง
ไฟล์ `.env.local`

ข้อควรระวัง:

- ใช้เฉพาะ Supabase publishable/anon key
- ห้ามใส่ `service_role` key หรือ secret key
- publishable key สามารถถูกดึงออกจาก EXE ได้โดยตั้งใจ และต้องไม่ใช้
  service-role/secret key

## 4. เตรียม ProxyCore แยกจาก EXE

วาง runtime ที่ได้รับอนุมัติไว้ที่:

```text
%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe
```

ถ้า ProxyCore มีโฟลเดอร์ประกอบ เช่น `bin`, `data`, `i18n`, `logging` หรือ
`mode` ให้คงโครงสร้าง runtime ภายนอกเดิมไว้ `NekoLauncher.spec` ต้องไม่ฝัง
ProxyCore หรือ V2Ray เข้า Launcher EXE

ตรวจสอบไฟล์หลักก่อน Build:

```powershell
Test-Path "$env:LOCALAPPDATA\NEKO FAMILY\ProxyCore\NekoProxyCore.exe"
```

ควรได้ผลลัพธ์เป็น `True`

## 5. ตรวจสอบโค้ดก่อน Build

รันจากโฟลเดอร์ `launcher`:

```powershell
python -m ruff check src tests
python -m pytest -q -m "not integration"
python -m compileall -q src
```

ถ้าจะรัน integration test ต้องใช้ Supabase project สำหรับทดสอบโดยเฉพาะ:

```powershell
python -m pytest -q -m integration
```

## 6. Build EXE

ยังอยู่ในโฟลเดอร์ `launcher` แล้วรัน:

```powershell
python -m PyInstaller --clean --noconfirm NekoLauncher.spec
```

ไฟล์ที่ได้:

```text
launcher\dist\NekoLauncher.exe
```

โฟลเดอร์ `launcher\build\` เป็นไฟล์ชั่วคราวของ PyInstaller และสามารถลบได้
เมื่อไม่ต้องการใช้ผลลัพธ์ระหว่าง Build แล้ว

## 7. ตรวจสอบ EXE หลัง Build

ตรวจสอบว่าไฟล์ถูกสร้าง:

```powershell
Test-Path .\dist\NekoLauncher.exe
Get-Item .\dist\NekoLauncher.exe | Select-Object FullName,Length
```

เปิดโปรแกรม:

```powershell
Start-Process .\dist\NekoLauncher.exe
```

ตรวจ flow ด้วยบัญชีทดสอบ:

1. Login สำเร็จแล้วต้องไปหน้าหลักโปรแกรม
2. บัญชีที่ยังไม่มี license ต้องแสดง `เหลือ 0 วัน`
3. Redeem coupon แล้วจำนวนวันต้องเพิ่มขึ้น
4. เลือก path ของ `Tweaker.exe`
5. กด `เริ่มใช้งาน`
6. ตรวจว่า `NekoProxyCore.exe` จาก runtime ภายนอกและ `Tweaker.exe` ทำงานตามลำดับ
7. กดหยุด Proxy/ปิดโปรแกรม แล้วตรวจว่าโปรเซสที่ launcher เปิดถูกปิด

ถ้า EXE แจ้งว่าไม่พบ ProxyCore ให้ตรวจ runtime ภายนอกที่
`%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe` ห้ามแก้ spec เพื่อฝัง
Core/V2Ray และห้ามใช้ environment-variable path override

## 8. การใช้ runtime แยกจาก EXE

Launcher ใช้ runtime แยกจาก EXE เสมอ โดยติดตั้งไว้ที่:

```text
%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe
```

สำหรับเครื่องลูกค้า แนะนำให้เก็บ runtime แยกเฉพาะเมื่อมีขั้นตอนติดตั้งและ
ตรวจสอบ version/checksum ที่ชัดเจน

## 9. ไฟล์ที่ไม่ควรส่งมอบหรือ commit

- Supabase `service_role` key หรือ secret ใด ๆ
- private signing key
- ไฟล์ใน `launcher/build/`
- runtime ProxyCore ที่ไม่ผ่านการอนุมัติ

ไฟล์ส่งมอบหลักคือ:

```text
launcher\dist\NekoLauncher.exe
```
