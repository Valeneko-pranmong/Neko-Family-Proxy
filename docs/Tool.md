# เครื่องมือที่ต้องใช้สำหรับพัฒนา Neko Family Proxy

> **สถานะ: CURRENT — reviewed 8 August 2026.** เอกสารนี้เป็น checklist สำหรับ
> เตรียมเครื่อง Windows ของผู้พัฒนาใหม่ คำสั่งทั้งหมดให้รันจาก PowerShell
> เว้นแต่จะระบุเป็นอย่างอื่น

## 1. เครื่องมือที่ต้องติดตั้ง

| เครื่องมือ | เวอร์ชันที่แนะนำ | จำเป็นเมื่อ | คำสั่งติดตั้งบน Windows |
| --- | --- | --- | --- |
| Git | รุ่นปัจจุบัน | clone, branch และตรวจ diff | `winget install --id Git.Git -e` |
| Python | `3.11` | พัฒนา ทดสอบ และ build Launcher | `winget install --id Python.Python.3.11 -e` |
| PowerShell | Windows PowerShell 5.1 หรือ PowerShell 7 | รันคำสั่งพัฒนาและ script | มีมากับ Windows; PowerShell 7 ใช้ `winget install --id Microsoft.PowerShell -e` |

ปิดและเปิด PowerShell ใหม่หลังติดตั้ง แล้วตรวจสอบว่าเครื่องมือพร้อมใช้งาน:

```powershell
git --version
py -3.11 --version
py -3.11 -m pip --version
```

> ไม่ต้องติดตั้ง `pytest`, `ruff` หรือ `PyInstaller` แยกทีละตัว เพราะโปรเจกต์
> ระบุเวอร์ชันไว้ใน `launcher/pyproject.toml` แล้ว

## 2. Clone และเตรียม Python environment

```powershell
git clone <REPOSITORY-URL> Neko-Family-Proxy
Set-Location .\Neko-Family-Proxy\launcher

py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,release]"
```

คำสั่งติดตั้งชุดสุดท้ายจะลงเครื่องมือและ dependency ต่อไปนี้จาก
`launcher/pyproject.toml`:

- Runtime: `customtkinter`, `keyring`, `Pillow`, `pystray`, `supabase`
- Development: `pytest`, `ruff`
- Release/build: `PyInstaller`

ทุกครั้งที่เปิด PowerShell ใหม่ ให้ activate environment ก่อนทำงาน:

```powershell
Set-Location .\Neko-Family-Proxy\launcher
.\.venv\Scripts\Activate.ps1
```

## 3. ตรวจสอบว่าเครื่องพร้อมพัฒนา

รันจาก root ของ repository:

```powershell
python scripts/check_repository_safety.py
Set-Location .\launcher
python -m ruff check src tests
python -m pytest -q -m "not integration"
python -m compileall -q src
```

ผลที่คาดหวัง:

- repository safety check จบโดยไม่มี error
- Ruff แสดงว่า checks ผ่าน
- pytest ไม่มี test ล้มเหลว
- compileall จบโดยไม่มี error

## 4. รัน Launcher จาก source

รันจากโฟลเดอร์ `launcher` และต้อง activate `.venv` แล้ว:

```powershell
python -m neko_launcher.main
```

ค่า Supabase URL และ publishable client key อยู่ใน source แล้ว ไม่ต้องสร้าง
`.env.local` สำหรับการรัน Launcher ปกติ และห้ามใส่ `service_role` key หรือ
secret key ลงใน desktop client หรือ repository

## 5. Build Windows EXE

รันจากโฟลเดอร์ `launcher`:

```powershell
python -m PyInstaller --clean --noconfirm NekoLauncher.spec
```

ตรวจสอบผลลัพธ์:

```powershell
Test-Path .\dist\NekoLauncher.exe
Get-Item .\dist\NekoLauncher.exe | Select-Object FullName,Length
```

ไฟล์ที่ได้คือ `launcher\dist\NekoLauncher.exe` ดูขั้นตอนเต็มและ smoke test ที่
[`current/build-windows-executable.md`](current/build-windows-executable.md)

ProxyCore ไม่ใช่ Launcher build input และต้องไม่ถูกฝังใน EXE; runtime ที่ทีม
อนุมัติจะติดตั้งแยกที่ `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\` และถูกจัดการ
โดยทีมเท่านั้น การ build สำเร็จไม่ถือเป็น production approval

## 6. เครื่องมือเสริมตามงาน

เครื่องมือต่อไปนี้ **ไม่จำเป็นสำหรับงาน Launcher ทั่วไป** ให้ติดตั้งเมื่อทำงาน
ส่วนนั้นเท่านั้น

### Supabase local development และ Edge Function

ต้องใช้ Docker Desktop และ Supabase CLI:

```powershell
winget install --id Docker.DockerDesktop -e
scoop install supabase
```

ถ้ายังไม่มี Scoop ให้ติดตั้งตามเอกสารทางการของ Scoop/Supabase ก่อน อย่าเดา URL
หรือรัน installation script ที่ไม่ทราบแหล่งที่มา หลังติดตั้งให้ตรวจสอบ:

```powershell
docker --version
supabase --version
```

เริ่ม Supabase local stack และ serve prototype Edge Function:

```powershell
Set-Location .\supabase
supabase start
supabase functions serve issue_launch_permit --env-file .env.local
```

`.env.local` ต้องเป็นไฟล์ local ที่ไม่ commit และห้ามนำ secret มาใส่ในเอกสาร
หรือ source code งาน integration ที่เชื่อม Supabase จริงควรใช้ disposable test
credentials ตาม `supabase/security-test-plan.md`

### GitHub CLI

ใช้เมื่อต้องตรวจ workflow, pull request หรือ release จาก command line:

```powershell
winget install --id GitHub.cli -e
gh --version
gh auth login
```

### Inno Setup

ใช้เฉพาะงานสร้าง Windows installer แบบเดียวกับ release workflow:

```powershell
winget install --id JRSoftware.InnoSetup -e
```

CI ติดตั้ง Inno Setup `6.7.1` ด้วย Chocolatey หากต้องสร้าง release ให้ตรวจ
`.github/workflows/release.yml` และไฟล์ installer ที่ได้รับอนุมัติก่อนเสมอ

## 7. Checklist สำหรับผู้พัฒนาใหม่

- [ ] ติดตั้ง Git
- [ ] ติดตั้ง Python 3.11 พร้อม `pip` และ `venv`
- [ ] Clone repository สำเร็จ
- [ ] สร้างและ activate `launcher/.venv`
- [ ] รัน `python -m pip install -e ".[dev,release]"` สำเร็จ
- [ ] repository safety check ผ่าน
- [ ] Ruff ผ่าน
- [ ] pytest ชุด non-integration ผ่าน
- [ ] รัน Launcher จาก source ได้
- [ ] Build `launcher/dist/NekoLauncher.exe` ได้เมื่อต้องส่งมอบ
- [ ] ติดตั้ง Docker/Supabase CLI เฉพาะเมื่อทำงานฐานข้อมูลหรือ Edge Function
- [ ] ไม่มี secret, token, service-role key หรือข้อมูลลูกค้าอยู่ในไฟล์ที่จะ commit

## 8. เอกสารที่เกี่ยวข้อง

- [`../README.md`](../README.md) — ภาพรวมโปรเจกต์
- [`../launcher/README.md`](../launcher/README.md) — การพัฒนา Launcher
- [`current/build-windows-executable.md`](current/build-windows-executable.md) — ขั้นตอน build EXE แบบเต็ม
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — กฎ contribution และ validation
- [`../supabase/README.md`](../supabase/README.md) — โครงสร้างฐานข้อมูล Supabase
- [`../supabase/security-test-plan.md`](../supabase/security-test-plan.md) — ข้อกำหนด integration/security test
