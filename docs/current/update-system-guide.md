# คู่มือระบบอัปเดต และการออก 5.2.3 ให้ 5.2.2 อัปเดตได้

อัปเดต: 2026-10-28 · ใช้กับ line 5.2.x (Core freeze ที่ 5.2.0)

เอกสารนี้อธิบายว่า client ตัดสินใจ "เห็น/ไม่เห็น/บังคับ" release อย่างไร และต้องผลิต release ถัดไป (5.2.3) อย่างไรให้เครื่องที่ติดตั้ง 5.2.2 stable อยู่แล้วอัปเดตได้จริง

---

## 1. ระบบอัปเดตตัดสินจาก 3 ชั้น

### ชั้นที่ 1 — Trust profile ที่ติดตั้งไว้ ( installer เป็นผู้กำหนด )

ทุกเครื่องมีไฟล์ `trust\update-profile-v1.json` (ติดตั้งโดย installer) ซึ่งกำหนด:

- `channel`: `stable` หรือ `preview`
- `release_keys`: รายการคีย์ที่ใช้ตรวจลายเซ็น envelope (เช่น `neko-update-prod-3`)
- profile ถูกเซ็นโดย profile-authority key (`neko-update-profile-v520-2`)

**สำคัญ: updater ไม่เคยเปลี่ยนไฟล์ profile** — อัปเดตได้เฉพาะ launcher/updater/Core ฉะนั้นการเปลี่ยนช่องทาง (preview → stable) หรือเปลี่ยนคีย์ ทำได้ทางเดียวคือติดตั้ง installer ใหม่

### ชั้นที่ 2 — ช่องทางเลือก feed

| profile channel | แหล่งที่ตรวจ | รับเฉพาะ |
|---|---|---|
| `stable` | `releases/latest` | release ที่ `draft=false` และ `prerelease=false` |
| `preview` | `releases?per_page=100` | release แรกที่ `prerelease=true` |

ผลที่ตามมา:

- release stable **มองไม่เห็น** จากเครื่อง preview (ขึ้น "เป็นเวอร์ชันล่าสุดแล้ว")
- release prerelease **มองไม่เห็น** จากเครื่อง stable
- envelope ต้องมี `channel` ตรงกับ profile (`github_release_binding._expected_channel`) ไม่งั้น `RELEASE_MANIFEST_REJECTED`

### ชั้นที่ 3 — Envelope (release-v2.json)

ทุก release ต้องมี asset `release-v2.json` เซ็นด้วยคีย์ที่ profile ไว้ใจ และบรรจุ:

- `channel`, `release_id` (เช่น `stable-0026`), `release_sequence` (seq)
- `minimum_supported_sequence`
- `mandatory`
- `components`: launcher / updater / core (version + sha256 + size + installed identity)

กติกาที่ client ใช้ (`software_update_policy.py`):

- `remote.sequence < local.high_water` → `DOWNGRADE_REJECTED` (ห้ามถอยรุ่น)
- `remote.sequence == local.sequence` แต่ binding ต่าง → `SAME_SEQUENCE_IDENTITY_CONFLICT`
- `mandatory = remote.mandatory OR local.committed.sequence < remote.minimum_supported_sequence`
  - ถ้า mandatory → state `MANDATORY` (บังคับอัปเดตก่อนใช้งาน)
  - ถ้าไม่ → state `AVAILABLE` (แจ้งให้ผู้ใช้กดอัปเดต)
- ระบบไม่บังคับปิดระหว่างเล่นเกม/เชื่อมต่อ proxy

---

## 2. สถานะของแต่ละรุ่น (ณ 2026-10-28)

| รุ่น | Profile (ติดตั้ง) | คีย์ที่ไว้ใจ | Baseline | เห็น stable ล่าสุด? |
|---|---|---|---|---|
| 5.1.6 | `neko-update-profile-v512-1` (stable) | prod-1 เท่านั้น | `stable-0013` seq 13 min 9 | ❌ ตรวจลายเซ็นไม่ผ่าน (คนละคีย์) → ต้องติดตั้งใหม่ manual |
| 5.2.1 | preview | prod-3 | `preview-0016` seq 16 min 16 | ❌ ช่อง preview มองไม่เห็น stable → ขึ้น "ล่าสุด" |
| 5.2.2 | `trust/update-profile-v1.json` (stable, sha `380e7df6…`) | prod-3 | `stable-0026` seq 26 min 26 | ✅ เห็น 5.2.3 stable (seq 27) |
| 5.2.3 | `trust/update-profile-v1.json` (stable, sha `380e7df6…`) | prod-3 | `stable-0027` seq 27 min 27 | — (คือรุ่นปัจจุบัน) |

หมายเหตุ: 5.2.1 (และ 5.2.2a preview builds) ไม่เคยถูก publish เป็น GitHub release; มีเฉพาะเครื่องทดสอบ

---

## 3. สูตรของ 5.2.3 ที่ทำให้ 5.2.2 อัปเดตได้

ต้องครบทุกข้อ:

1. **Channel = `stable`** และเซ็นด้วย **prod-3** (`neko-update-prod-3`) — เหมือน 5.2.2
2. **`release_id = stable-0027`, `release_sequence = 27`** (ledger floor 25 → 26 ถูกใช้แล้ว; ถัดไป 27)
3. **`minimum_supported_sequence`**
   - `27` → **บังคับ** ทุกเครื่อง seq < 27 (รวม 5.2.2 = seq 26) อัปเดตก่อนใช้งาน
   - `≤ 26` → เป็นอัปเดตแบบ **ให้ผู้ใช้กด** (AVAILABLE)
4. **launcher/updater version = `5.2.3`** ตรงกับ tag `v5.2.3` (validator บังคับ launcher/updater = tag)
5. **core version คงเป็น `5.2.0`** ได้ (Core freeze; publisher รองรับ core ต่ำกว่า tag และยังบังคับ identity sha ครบ)
6. **Installer** ต้อง rebuild ด้วย **stable profile + stable baseline envelope (`stable-0027`)** (installer ฝัง profile + baseline)
7. **tag `v5.2.3`** ชี้ commit ที่ build จริง และ **push ก่อน stage** (stager ตรวจทั้ง local และ remote tag binding)
8. **Publish เป็น non-prerelease (stable)** เท่านั้น → ติด `releases/latest` ให้เครื่อง stable เห็น
9. Assets **5 ไฟล์พอดี**: `NekoFamilyProxy-Installer.exe`, `NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, `release-v2.json`

---

## 4. ขั้นตอนผลิต 5.2.3 (คำสั่งจริง)

> ปรับ version/paths ตามจริง; ตัวอย่างอิงวิธีที่ใช้ผลิต 5.2.2 stable (seq 26)
> stager จะปฏิเสธถ้า working tree ไม่ clean — commit ให้เรียบร้อยก่อน stage

### 4.1 เตรียม source + binaries

```powershell
# 1) bump version
#    launcher/pyproject.toml: version = "5.2.3"
git add launcher/pyproject.toml && git commit -m "release(5.2.3): bump version"
git tag -a v5.2.3 -m "Release v5.2.3" <commit>
git push origin v5.2.3            # ต้อง push ก่อน stage

# 2) build launcher/updater ด้วย PyInstaller (ตาม docs/current/5.2.2-build-runbook.md)
#    - NekoLauncher.exe --tk-self-test ต้อง exit 0
#    - NekoUpdater.exe --self-check ต้อง exit 0
```

### 4.2 สร้าง metadata + เซ็น envelope (channel stable, seq 27)

```powershell
$B = "$env:TEMP\neko-build-venv\Scripts\python.exe"   # build venv (Python 3.12, PyInstaller 6.21)
$W = "$env:TEMP\neko-523-build"
# metadata.json = payload ของ 5.2.2 แต่แก้:
#   channel = "stable"
#   release_id = "stable-0027"
#   release_sequence = 27
#   minimum_supported_sequence = 27   # หรือ <=26 ถ้าไม่บังคับ
#   components.launcher/updater.version = "5.2.3" (hash/size ต้องตรงไฟล์จริง)
& $B scripts\build_software_release_v2.py `
  --input            "$W\metadata.json" `
  --launcher-artifact "$W\NekoLauncher.exe" `
  --updater-artifact  "$W\NekoUpdater.exe" `
  --core-artifact     "$W\NekoProxyCore.zip" `
  --private-key-file  "H:\...\Project manager\.vault\keys\custody\neko-update-prod-3.pem" `
  --key-id            neko-update-prod-3 `
  --public-key-file   "$W\neko-update-prod-3.pub" `
  --output            "$W\stage\payload\baseline\release-v2.json"
```

### 4.3 rebuild installer (stable profile + stable baseline)

```powershell
& $B installer\scripts\build_beta_installer.py `
  --candidate-dir     "$W\stage" `
  --launcher-sha256   <launcher sha> `
  --updater-sha256    <updater sha> `
  --core-authority    b7d9708bc2c9a97255a9ea2f8307ef66e2d81bf8 `
  --release-version   5.2.3 `
  --baseline-envelope "$W\stage\payload\baseline\release-v2.json" `
  --trust-profile     "E:\Neko-Family-Proxy\trust\update-profile-v1.json"   # stable profile
# ต้องได้ 11/11 GATE PASS + BUILD=PASS
```

### 4.4 ประกอบ staging (ต้องมี **ไม่เกิน 5 ไฟล์**)

```
$W\assets\
  NekoFamilyProxy-Installer.exe
  NekoLauncher.exe
  NekoUpdater.exe
  NekoProxyCore.zip
  release-v2.json
```

### 4.5 stage + publish (stable)

```powershell
# dry-run ก่อน
& $B scripts\publish_atomic_release.py `
  --staging-dir "$W\assets" `
  --tag v5.2.3 --target-commit <full sha ของ tag> `
  --title "NEKO FAMILY PROXY 5.2.3" `
  --notes-file "…\release-notes-5.2.3.md" `
  --expected-sequence 27 --expected-minimum-sequence 27 `
  --dry-run

# เอาออก --dry-run → สร้าง draft + อัปโหลด 5 assets
# แล้ว publish เป็น stable (non-prerelease):
gh release edit v5.2.3 --repo Valeneko-pranmong/Neko-Family-Proxy --draft=false
```

> **ห้ามใช้ `.github/workflows/release.yml` (rollout-stable) สำหรับ stable**: job นั้นบังคับ `prerelease=true` และยังบล็อก 5.2.x — ใช้เฉพาะ verify/rollout ของ preview

### 4.6 verify หลัง publish

```powershell
gh release view v5.2.3 --json isDraft,isPrerelease,tagName,targetCommitish,assets
gh api repos/Valeneko-pranmong/Neko-Family-Proxy/releases/latest   # ต้องได้ v5.2.3

& $B scripts\verify_github_release_assets.py `
  --release-json <gh api release json> --download-dir "$W\assets" `
  --public-key-file "$W\neko-update-prod-3.pub" `
  --expected-tag v5.2.3 --expected-target <sha> `
  --no-enforce-first-release
```

### 4.7 ทดสอบ path 5.2.2 → 5.2.3 (ต้องทำก่อนประกาศ)

1. เครื่องที่มี 5.2.2 stable (baseline `stable-0026`) เปิด Launcher
2. ต้องเห็นหน้า update (MANDATORY ถ้า min=27 / AVAILABLE ถ้า min≤26)
3. อัปเดตสำเร็จ → ตรวจ `%LOCALAPPDATA%\NEKO FAMILY\baseline\release-v2.json` = `stable-0027`
4. เปิดแอป ตรวจ login/Settings/Core + `--tk-self-test` exit 0

> ตัว updater เปลี่ยน launcher/updater/Core — profile ยังเป็น stable เดิม (ไม่ต้องติดตั้งใหม่)

---

## 5. จุดที่พลาดบ่อย (บทเรียนจริงจาก 5.1.6 → 5.2.2)

| อาการ | สาเหตุ | ทางแก้ |
|---|---|---|
| client ตรวจลายเซ็นไม่ผ่าน / update error | envelope เซ็นด้วยคีย์ที่ profile ไม่ไว้ใจ (5.1.6 ไว้ใจแค่ prod-1, 5.2.2 ใช้ prod-3) | ต้องมี bridge ที่เซ็นด้วยคีย์ที่เครื่องนั้นไว้ใจ (ถ้าไม่มี private key → migration manual) |
| client ขึ้น "เป็นเวอร์ชันล่าสุดแล้ว" ทั้งที่มีรุ่นใหม่ | คนละ channel (preview มองไม่เห็น stable) | ใช้ installer ย้าย channel |
| publish stable แล้ว client ไม่เห็น | เผลอ publish เป็น prerelease หรือ release ยังเป็น draft | stable ต้อง `prerelease=false`, `draft=false` |
| stager ปฏิเสธ "Local/Remote tag does not bind" | ยังไม่ tag หรือ tag ชี้ commit อื่น | สร้าง tag ที่ commit ที่ build + push ก่อน |
| stager ปฏิเสธ "extra or forbidden assets" | staging dir มีไฟล์เกิน 5 | ใช้โฟลเดอร์สะอาดที่มี 5 ไฟล์ |
| release body เป็น path ไฟล์ | ใช้ `--notes` กับ path | ใช้ `--notes-file` |
| draft-ID discovery ล้มหลังอัปโหลด | decode output ด้วย locale เดิม | แก้แล้วใน `b656f9e` (UTF-8) |
| Core version ต่ำกว่า tag แล้วถูกปฏิเสธ | validator บังคับทุก component = tag | แก้แล้วใน `5854a62` (core freeze) |
| publish 5.2.x stable ไม่ได้ | preview-only gate | แก้แล้วใน `829c4bb` (5.2.2+ ขึ้น stable ได้) |

---

## 6. Checklist ก่อน publish 5.2.3

- [ ] `launcher/pyproject.toml` = 5.2.3, tag `v5.2.3` push แล้ว ชี้ commit ที่ build
- [ ] envelope: channel stable, `stable-0027`, seq 27, min 27 (หรือ ≤26), คีย์ prod-3
- [ ] launcher/updater version = 5.2.3; core 5.2.0 + identity sha ตรง
- [ ] installer 11/11 gates + stable profile/baseline
- [ ] staging มี 5 ไฟล์พอดี, notes พร้อม (ไฟล์ .md)
- [ ] suite เขียว (`cd launcher; pytest -q`), ruff, `check_repository_safety.py`
- [ ] dry-run ผ่าน, publish แล้ว `releases/latest` = v5.2.3
- [ ] ทดสอบอัปเดตจาก 5.2.2 จริงสำเร็จ + baseline เปลี่ยนเป็น stable-0027
- [ ] บันทึก sign-off/vault (`RELEASES.md`, MANIFEST, `verify-vault -Full`)
- [ ] แจ้งเตือน: ถ้า min = 27 ผู้ใช้ 5.2.2 ทุกคนจะถูกบังคับอัปเดตก่อนใช้งาน (ไม่บังคับปิด session ที่กำลังเล่น)

---

## 7. ข้อห้าม / ข้อควรระวัง

- **ห้าม rotate คีย์หรือเปลี่ยน channel โดยไม่มี bridge** ที่เครื่องเดิมไว้ใจได้ — จะตัดขาดผู้ใช้เดิมทันที (เคส 5.1.6)
- **ห้ามแก้/ย้าย tag ที่ publish แล้ว** — sequence/binding ผูกกับ tag และ release
- **ห้าม publish stable-channel envelope เป็น prerelease** — เครื่อง preview จะดึงไปแล้ว reject (channel mismatch)
- **ห้ามใช้ sequence ซ้ำ** — ใช้ 27; sequence เดิมแต่ binding ต่าง = SAME_SEQUENCE_IDENTITY_CONFLICT
- **Authenticode**: ถ้าจะเซ็น installer ให้เซ็นก่อนคำนวณ hash/upload (envelope ไม่ผูก installer จึงไม่ต้องเซ็น envelope ใหม่); ถ้าจะเซ็น launcher/updater ต้องเซ็นก่อนสร้าง envelope และ re-run gates
- **Ledger**: การ allocate ตรง (แบบ 26) ไม่มี event ใน production ledger; ถ้าต้องการ event ต้องผ่าน `release_controller` ซึ่งต้องใช้ Core-authority custody index (ยังไม่มีบนเครื่อง build นี้)
