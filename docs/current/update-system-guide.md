# คู่มือระบบอัปเดต — สถานะจริงหลัง 5.2.3 re-release (2026-10-28)

> **คนที่ทำแพทต่อ:** ใช้ [5.2.x-patch-runbook.md](5.2.x-patch-runbook.md) เป็น checklist/คำสั่งจริง

เอกสารนี้อธิบายว่าทำไม 5.2.2 อัปเดตอัตโนมัติไป 5.2.3 ไม่ได้, 5.2.3 ที่ re-release แก้อะไร, และการออกรุ่นถัดไปต้องทำอย่างไรให้ไม่พังซ้ำ

---

## 1. สรุปสถานะ

| รุ่น | สถานะ | อัปเดตในแอปได้? |
|---|---|---|
| 5.1.6 | legacy stable | ไม่ได้ (คนละ trust key) — ติดตั้งใหม่ |
| 5.2.2 | stable ที่ยังเป็น `releases/latest` | ไม่ได้ — updater ตรวจ Core ไม่ผ่าน |
| 5.2.3 | **fixed re-release, manual non-latest** (`stable-0028`, seq 28) | ใช้ได้หลังติดตั้ง 5.2.3 ครั้งเดียว |
| 5.2.4 | **ยกเลิก** (ถูกลบ release/tag) | — |

ตัวเลขล่าสุด: 5.2.3 fixed envelope `stable-0028` seq 28 min 28, updater `b0b991f5…`, launcher `70e7b571…`, installer `674a968d…`

---

## 2. กลไกการตัดสินของ client

1. **Trust profile ที่ installer ติดตั้ง** (`trust/update-profile-v1.json`) กำหนด channel (`stable`) และคีย์ที่ไว้ใจ (`neko-update-prod-3`)
2. **Channel** เลือก feed: stable อ่าน `/releases/latest`, preview อ่าน `/releases?per_page=100`
3. **Envelope** (`release-v2.json`) ต้องเซ็นด้วยคีย์ที่ profile ไว้ใจ, channel ตรง, และมี launcher/updater/core ครบ

จากนั้น client จะ:
- เทียบ **updater ที่ติดตั้งในเครื่อง** กับ updater ใน envelope ปลายทาง (`verify_installed_updater`)
- stage เฉพาะ launcher/core (**ไม่เคย stage หรือแทนที่ updater**)
- spawn `NekoUpdater.exe` ที่ติดตั้งอยู่เพื่อ apply

จุดที่ 3 คือข้อจำกัดสำคัญ: **feed เปลี่ยน updater binary ให้ client เองไม่ได้**

---

## 3. ทำไม 5.2.2 → 5.2.3 (ครั้งแรก) ถึงล้มเหลว

### ชั้นที่ 1 — updater hash

`verify_installed_updater` เอา hash/size ของ `NekoUpdater.exe` ที่ติดตั้ง (5.2.2 = `35f4532c…`, 11,281,597 B) ไปเทียบกับ updater ใน manifest (`bb2cee9d…`, 11,280,446 B) → `UPDATER_SIZE_MISMATCH` → `UPDATER_INCOMPATIBLE`

การ pin manifest ให้ใช้ updater 5.2.2 แก้ชั้นนี้ได้ (resolver ผ่าน) แต่ไม่พอ

### ชั้นที่ 2 — Core inventory (ตัวจริง)

หลัง pin แล้ว live test ไปถึงขั้น apply แต่ updater 5.2.2 ตรวจ Core เดิมด้วย `verify_canonical_core_bundle` ที่ต้องการ schema `rid` / `executable` / `files[]` ขณะที่ Core authority ที่ freeze 5.2.0 ใช้ schema เดิม `file_count` + `files{path: sha256}`

ผลลัพธ์: `CORE_INVENTORY_INVALID` ก่อนไฟล์ใดถูกแทนที่ — **ทุกครั้ง ไม่ว่าจะแก้ feed อย่างไร**

เพราะการตรวจอยู่ใน `NekoUpdater.exe` ตัวที่ติดตั้งอยู่ จึงแก้จาก server ไม่ได้ ต้องเปลี่ยน updater binary ซึ่ง client เก่าโหลดเองไม่ได้ → ทางออกเดียวคือ **ติดตั้งใหม่หนึ่งครั้ง**

### ชั้นที่ 3 — Core preflight (เจอตอนทดสอบ apply จริง)

หลังแก้ inventory แล้ว probation ยังเรียก `NekoProxyCore.exe --update-preflight` แต่ Core freeze 5.2.0 ไม่มี flag นี้ (exit 2, ไม่มี output) → `SELFTEST_FAILED`

updater จึงต้องข้าม preflight สำหรับ Core schema เดิม โดยยังตรวจ inventory ครบ 1,023 ไฟล์

---

## 4. 5.2.3 re-release แก้อะไร

`verify_canonical_core_bundle` รองรับทั้งสอง schema:

- canonical: เหมือนเดิม
- frozen 5.2.0 authority: ตรวจ `source_commit`, `file_count`, SHA-256 ทุกไฟล์, mandatory files, และปฏิเสธไฟล์ที่ไม่อยู่ใน manifest

ผลทดสอบกับ Core ที่ติดตั้งจริง: valid, 1,023 ไฟล์, 371,738,030 B, manifest `c262432c…`

### สัญญาของ line 5.2.x หลังจากนี้

- **updater bytes ถูก pin ที่ `b0b991f5…` (11,281,601 B)** — ห้าม rebuild เปลี่ยน hash จนกว่าจะมีกลไก self-replace ที่ปลอดภัย
- manifest ของ release ถัดไปต้องระบุ updater hash นี้ และ installer ต้อง stage ไฟล์เดียวกัน
- publisher บังคับ `updater.version == tag`; จึงใช้ version label ตาม tag ได้ แต่ **ไบต์ต้องเป็น b0b991f5… เสมอ**
- launcher version = tag; core คง 5.2.0 (`c262432c…`)
- sequence 28 ถูกใช้โดย 5.2.3 re-release แล้ว; รุ่นถัดไปต้องเป็น **seq 29**
- tag `v5.2.3` ถูก force-move ไปยัง commit ของ re-release (tag เดิมชี้ `da61a82`); อย่าทำซ้ำถ้าไม่จำเป็น — ครั้งต่อไปให้ bump version ใหม่แทน

---

## 5. การย้ายผู้ใช้ไป 5.2.3 (manual)

1. ปิด launcher/proxy/เกม
2. ถอนเวอร์ชันเดิมผ่าน Windows Settings > Apps
3. ติดตั้ง `NekoFamilyProxy-Installer.exe` 5.2.3 (re-release)
4. ล็อกอิน Discord ใหม่ (credential ในเครื่องถูกลบตอนถอน; วัน/สิทธิ์อยู่ฝั่ง server)
5. ตรวจ baseline เป็น `stable-0028`

**ห้ามประกาศ 5.2.3 เป็น latest จนกว่าผู้ใช้ 5.2.2 จะย้ายเสร็จ** — ถ้า feed stable ชี้ updater `b0b991f5…` เครื่อง 5.2.2 ที่ยังใช้ `35f4532c…` จะขึ้น `REINSTALL_REQUIRED` และถูกล็อกไม่ให้ login

---

## 6. การออก release ถัดไป (5.2.4)

1. bump launcher เป็น 5.2.4 แล้ว rebuild `NekoLauncher.exe` (updater **ไม่ต้อง rebuild**; ใช้ `b0b991f5…`)
2. สร้าง envelope: stable, `stable-0029`, seq 29, min 29, launcher 5.2.4, updater version 5.2.4 + hash `b0b991f5…`, core 5.2.0
3. เซ็นด้วย `neko-update-prod-3`
4. rebuild installer ด้วย pinned updater + baseline ใหม่; ต้องได้ 11/11 gates
5. **ทดสอบอัปเดตจริงจากเครื่อง 5.2.3 fixed** (stage → apply → state committed 29 → restart → self-tests) ก่อนเผยแพร่ — รอบนี้ผ่านแล้วด้วย launcher `3e060ae8…` / envelope `17b61458…`; ถ้า rebuild ให้ใช้ seq 30
6. เผยแพร่เป็น **non-latest manual ก่อน** (`make_latest=false`); จะ mark latest ก็ต่อเมื่อไม่มีเครื่อง 5.2.2 เหลือในระบบ

คำสั่ง build/publish โดยละเอียดดู `docs/current/5.2.x-patch-runbook.md`

---

## 7. Checklist ก่อน publish

- [ ] worktree clean; tag ชี้ commit ที่ build และ push แล้ว
- [ ] envelope: channel stable, seq ใหม่, min = seq, key prod-3
- [ ] updater hash = `b0b991f5…` (ห้ามเปลี่ยน)
- [ ] core คง 5.2.0 + identity `c262432c…`
- [ ] installer 11/11 gates + baseline envelope ใหม่
- [ ] staging มี 5 asset พอดี; ชื่อไฟล์ตรง
- [ ] suite เขียว, ruff, repository safety
- [ ] live update test จาก 5.2.3 fixed สำเร็จจริง (ไม่ใช่แค่ resolver ผ่าน)
- [ ] notes/hash/docs ตรงกับ asset จริง
- [ ] ถ้าเพิ่งมีเครื่อง apply ล้มเหลว: ใช้ sequence ถัดไป ไม่ reuse
- [ ] ก่อน publish: `releases/latest` ยังเป็น v5.2.2 และ plan non-latest/latest ชัดเจน

---

## 8. บทเรียนที่ต้องจำ

- การตรวจ updater binary ไม่ได้ป้องกันแค่การถูกแก้ไข — มันกันการอัปเดตข้ามรุ่นถ้าไบต์เปลี่ยน
- การ freeze Core ที่ schema ต่างจาก verifier ทำให้ update engine ใช้ไม่ได้ทั้ง line แม้ resolver จะผ่าน
- ต้องทดสอบ **apply จริง** ไม่ใช่แค่ `verify_installed_updater`/resolver ก่อน publish
- feed หนึ่งตัวรับ updater hash ได้ค่าเดียว จึงต้องวางแผนช่วงเปลี่ยนผ่าน population เสมอ
- การ rebrand/rewrite tag ควรเป็นทางเลือกสุดท้าย; ปกติให้ bump version ใหม่แทน
