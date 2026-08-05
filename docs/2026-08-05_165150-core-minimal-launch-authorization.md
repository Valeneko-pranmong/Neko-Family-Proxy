# แผนลดระบบ Authorization — ทีม NekoProxyCore

> **For Hermes:** ใช้แผนนี้เป็น execution handoff แบบ task-by-task หลัง Product/Security/Launcher ยืนยันขอบเขต “Minimal Launch Authorization” แล้วเท่านั้น

**Goal:** ทำให้ NekoProxyCore เปิดใช้งานจาก Launcher ได้จริง โดย Coreปฏิเสธทุก startที่ไม่มี Backend-signed permit และ reuse implementation initial authorizationที่มีอยู่แทนการขยายระบบต่อ

**Architecture:** คง `Protocol v2 + one-time challenge + RS256 permit + strict Core verifier + authorized-start boundary` ซึ่งมี source/testอยู่แล้ว เพิ่มเพียง production public-key composition, lifecycle/packaging และ cross-repository E2E ตัด continuous renewal, runtime attestation, signed manifest และ process-binding hardeningออกจาก Minimal V1

**Tech Stack:** .NET 6, C#, Windows Named Pipe, RS256/SHA-256, `NekoProxyCore.Host`, existing headless runtime

**แผนคู่กัน:** `2026-08-05_165150-launcher-minimal-launch-authorization.md`

---

## 1. เป้าหมายความปลอดภัยที่ Core ต้องรับผิดชอบ

Core รุ่น Minimal V1 ต้องรับประกัน:

1. เปิด EXEตรงโดยไม่มี permitแล้ว engineเริ่มไม่ได้
2. permitต้องมาจาก Backend signerที่ Coreรู้จักผ่าน bundled public key
3. invalid signature, unknown key, expired permit, wrong challenge, wrong configuration/PID หรือ replay ต้อง fail closedก่อน engine side effect
4. permitหนึ่งใบอนุญาต startได้สูงสุดหนึ่งครั้ง
5. Coreไม่มี private signing key, shared secret, local signer หรือ allow-all verifier
6. production entry pointทุกทางต้องผ่าน authorizerเดียวกัน
7. target `pso2.exe`/PIDต้องตรงตอน start และ runtimeต้องหยุดเมื่อ targetจบตาม lifecycleเดิม
8. permit/claims/private key/reusable proxy credentialห้ามอยู่ใน log, dump annotation, config หรือ artifact

### สิ่งที่ Coreไม่พยายามป้องกัน

- ผู้โจมตีที่ patch Core binaryเพื่อข้าม authorizer
- debugger/adminที่ควบคุมเครื่องลูกค้าทั้งหมด
- immediate session revocationหลัง Coreเริ่มแล้ว
- การพิสูจน์ว่า Launcher binaryหรือ Core bundleไม่ถูกแก้ผ่าน remote/runtime attestation

เป้าหมายคือทำให้การเปิด Coreตรง ๆ หรือปลอมข้อความง่าย ๆ ใช้งานไม่ได้ ไม่ใช่สร้าง DRMที่ไม่มีทาง bypass

---

## 2. ใช้ของที่มีอยู่ ไม่ rewrite

Sourceปัจจุบันมีชิ้นส่วนสำคัญแล้ว:

- `NekoProxyCore.Core/StrictLaunchPermitVerifier.cs`
- `NekoProxyCore.Core/CoreChallengeService.cs`
- `NekoProxyCore.Core/AuthorizationContracts.cs`
- `NekoProxyCore.Core/ProductionAuthorizationComposition.cs`
- `NekoProxyCore.Host/Protocol/ControlProtocol.cs`
- `NekoProxyCore.Host/HeadlessControlServer.cs`
- `Tests/StrictLaunchPermitVerifierTests.cs`
- `Tests/HeadlessHostProtocolTests.cs`

Minimal V1ต้อง **reuse** implementationเหล่านี้ ห้ามออกแบบ verifier/protocolใหม่ถ้า initial start flowปัจจุบันทำงานได้

### คงไว้ — ห้ามลด

- strict RS256 signature verification
- immutable exact `kid → public key` allow-listใน release
- 30-second permit lifetimeตาม codeปัจจุบัน
- one-use Core challengeและ JTI replay store
- canonical configuration digest, exact target PID/mode binding
- no permit → `AuthorizationRequired`
- verificationก่อน `Starting`/engine/network/driver side effect
- no private key/local signer/offline permitใน Core

### หยุดทำใน Minimal V1

- renewal challenge/renewal tokenทุก 15 วินาที
- Core-enforced continuous session authorization
- signed artifact manifestและ runtime file-set verification
- exact Named Pipe server-process binding algorithm/race matrix
- certificate chain, JWKS downloadหรือ automatic key rotation
- contract revision packageใหม่สำหรับทุก implementation detail
- S1 downstream-access designภายใน Core authorization task; แต่ยังห้าม ship reusable proxy credential
- เพิ่ม negative fixturesต่อเนื่องหลัง acceptance matrixใน §8ครบแล้ว

> โค้ด strict parsing/replay/target bindingที่เขียนและผ่าน testแล้วไม่ใช่ส่วนที่ควรถอด เพราะการถอดสร้าง regressionมากกว่าลดงาน การลดงานคือหยุดเพิ่ม layerใหม่และ wireของที่มีให้ productionใช้งานได้

---

## 3. Minimal V1 wire ที่ Coreรับ

```text
challenge request
→ Coreสร้าง random one-time challenge อายุ 30 วินาที

start request
→ Protocol v2
→ pso2.exe + targetPid + ProcessMode
→ profile/server references
→ opaque compact RS256 permit

Core verification
→ exact known kid/public key
→ signature valid
→ expected issuer/audience/product/scope
→ exp/iat/nbf validตาม verifierปัจจุบัน
→ challengeตรงและใช้ครั้งเดียว
→ config digest/target PID/modeตรง
→ jtiยังไม่เคยใช้
→ targetยังอยู่
→ จึง publish Startingและเริ่ม engine
```

อย่าเปลี่ยน claim/schemaเพียงเพื่อทำให้เอกสารสั้นลง หาก verifierกับ Backendสามารถใช้ initial permit shapeปัจจุบันได้ ให้ freeze shapeนั้นเป็น `Minimal V1` และเดินหน้าทดสอบ E2E

---

## 4. Task 1 — รักษา baseline และแยก user workก่อนแก้

**Objective:** ไม่ทำลาย working treeปัจจุบันซึ่งมี staged documentation/artifact cleanupจำนวนมาก

**Files:** ไม่มีการแก้ใน taskนี้

**Steps:**

1. ตรวจว่า branchคือ `feature/neko-headless` และ HEADตรง `origin/feature/neko-headless`
2. ตรวจ `git status --short` และบันทึกไฟล์ที่เป็นงานค้างของผู้อื่น
3. ห้าม reset/checkout/clean staged changesที่มีอยู่
4. ก่อน implementจริง ให้ ownerเลือกว่าจะ commit/stashงานค้างหรือสร้าง clean worktreeใหม่จาก exact HEAD
5. ใช้ frozen baselineเดิมเป็น ancestry; ห้ามย้ายไป `main`

**Verification:**

```bash
git branch --show-current
git rev-parse HEAD
git rev-parse origin/feature/neko-headless
git status --short
```

Expected: branch/commitตรงกัน และมีบันทึกชัดเจนว่างานใด pre-existing

---

## 5. Task 2 — Wire production public keyแบบง่าย

**Objective:** ให้ `ProductionAuthorizationComposition` สร้าง strict verifierจริงแทน `AuthorizationRequiredStartAuthorizer` เมื่อ production public keyพร้อม

**Files:**
- Modify: `NekoProxyCore.Core/ProductionAuthorizationComposition.cs`
- Modify: `NekoProxyCore.Host/Program.cs`
- Modify: `NekoProxyCore.Host/NekoProxyCore.Host.csproj`
- Create: `NekoProxyCore.Host/Authorization/ProductionPublicKeys.cs`
- Test: `Tests/ProductionAuthorizationCompositionTests.cs`

**Steps:**

1. รับ production public keyจาก Backend/Securityเป็น public materialเท่านั้น
2. bundle public keyหรือ RSA public parametersเป็น read-only release resource
3. pin exact `kid` และมี key allow-listขนาดเล็ก เช่น current keyหนึ่งตัว; ไม่มี first-key fallback
4. compositionสร้าง:
   - immutable public-key resolver
   - `S0Rc1CanonicalConfigurationSerializer`
   - trusted UTC clock implementationที่มีอยู่
   - in-memory replay store
   - `StrictLaunchPermitVerifier`
   - `ChallengePermitStartAuthorizer`
5. หาก public key resourceหาย/parseไม่ได้ ให้ host fail closed; ห้าม fallbackเป็น allow-allหรือ local signer
6. private keyห้ามเข้า repository, source generator, fixtureที่ ship, environmentหรือ artifact
7. key rotationใน Minimal V1ทำด้วย app updateที่ bundle old/new public keyชั่วคราว ไม่ทำ JWKS/network key fetch

**Verification:**

- production compositionคืน `ChallengePermitStartAuthorizer`
- missing/corrupt keyทำให้ startไม่ได้
- unknown `kid`ถูกปฏิเสธ
- artifact scanไม่พบ private-key marker

---

## 6. Task 3 — ยืนยัน authorized-start boundaryทุก entry point

**Objective:** ป้องกัน UI/legacy/CLI/test production pathข้าม permit verifier

**Files:**
- Review/Modify: `NekoProxyCore.Core/HeadlessRuntimeCoordinator.cs`
- Review/Modify: `NekoProxyCore.Core/ProcessModeController.cs`
- Modify: `NekoProxyCore.Host/Program.cs`
- Test: `Tests/HeadlessRuntimeTests.cs`
- Test: `Tests/LegacyMainControllerContractTests.cs`
- Test: `Tests/S0Rc1ReviewRegressionTests.cs`

**Steps:**

1. traceทุก callไปยัง engine start
2. production headless hostต้อง inject authorizerจาก `ProductionAuthorizationComposition`
3. start requestไม่มี admitted challenge/permitต้องคืน `AuthorizationRequired`
4. verificationต้องจบก่อน publish `Starting`, network, driverหรือ engine call
5. legacy UI/CLI entryที่ไม่ส่ง permitต้อง fail closed หรือไม่รวมใน headless production artifact
6. ไม่มี compile flag, environment variable, debug commandหรือtest hookที่เปิด allow-allใน release
7. valid requestเกิด engine start exactly once

**Verification:**

```bash
dotnet test Tests/Tests.csproj -c Release -p:Platform=x64 --no-restore --nologo
```

Expected: direct/no-permit/legacy negatives engine start count `0`; valid permit count `1`

---

## 7. Task 4 — Lifecycle แบบง่าย ไม่มี renewal

**Objective:** ใช้ start authorizationครั้งเดียวและ lifecycleที่คาดเดาได้ แทนระบบ renewalที่ยังทำให้งานค้าง

**Files:**
- Review/Modify: `NekoProxyCore.Core/HeadlessRuntimeCoordinator.cs`
- Review/Modify: `NekoProxyCore.Core/ProcessModeController.cs`
- Review/Modify: `NekoProxyCore.Host/HeadlessControlServer.cs`
- Test: `Tests/HeadlessRuntimeTests.cs`
- Test: `Tests/HeadlessHostProtocolTests.cs`

**Steps:**

1. permit authorizeเฉพาะ transition `Stopped → Running` หนึ่งครั้ง
2. permitหมดอายุหลัง Runningแล้วไม่บังคับ stop; นี่คือ semanticsที่ยอมรับของ Minimal V1
3. runtimeหยุดเมื่อได้รับ typed `stop`, target PIDจบ, engine failure หรือ Core processปิด
4. startครั้งใหม่หลัง Stopต้องใช้ challengeและ permitใหม่
5. replay startขณะ Runningต้องไม่สร้าง engineตัวที่สอง
6. ไม่เพิ่ม renewal command, runtime ID, grace periodหรือ local heartbeat timestamp
7. cleanupต้องมี timeoutและคืน `Stopped`/`StopFailed`ตาม behaviorปัจจุบัน

**Accepted tradeoff:** Backendไม่สามารถ revoke Coreที่ Runningอยู่แบบทันที การแก้คือให้ผู้ใช้ Stop/ปิด Launcher/ปิด target หรือเพิ่ม continuous authorizationภายหลังเมื่อมี requirementจริง

---

## 8. Task 5 — ลด packagingให้เป็น artifactใช้งานได้

**Objective:** สร้าง Core release artifactธรรมดาที่ Launcherเปิดได้ โดยไม่รอ signed runtime manifest system

**Files:**
- Modify if required: `NekoProxyCore.Host/NekoProxyCore.Host.csproj`
- Modify: release/build documentationที่ current ownerเลือกหลัง implementation

**Steps:**

1. publish `NekoProxyCore.Host` เป็น `win-x64`
2. รวม dependencies/runtime filesที่จำเป็นและ bundled public key resource
3. ไม่ต้องมี runtime manifest verifier, recursive file hash validationหรือ path/reparse scannerใน Minimal V1
4. release pipelineบันทึก SHA-256ของ ZIP/EXEเพื่อ traceabilityตามปกติ
5. Launcherใช้ fixed approved install path; packaging hashเป็น release evidence ไม่ใช่ authorization conditionตอน runtime
6. scan outputเพื่อยืนยันไม่มี private key, permit, token, passwordหรือ reusable proxy credential

**Commands:**

```bash
dotnet test Tests/Tests.csproj -c Release -p:Platform=x64 --no-restore --nologo
dotnet publish NekoProxyCore.Host/NekoProxyCore.Host.csproj \
  -c Release -r win-x64 --self-contained false \
  -p:Platform=x64 -o artifacts/minimal-core
```

จากนั้นคำนวณ SHA-256ของ artifactและส่ง exact hashให้ทีม Launcher

---

## 9. Task 6 — Minimal acceptance matrix

**Objective:** หยุดเพิ่ม testเมื่อพิสูจน์ riskหลักครบ และย้ายไป E2Eจริง

**Core acceptance testsที่ต้องผ่าน:**

1. startโดยไม่มี permit → `AuthorizationRequired`, engine count `0`
2. bad signature/unknown kid → reject, engine count `0`
3. expired/future permit → reject, engine count `0`
4. wrong challenge → reject, engine count `0`
5. wrong configuration digest/PID/mode → reject, engine count `0`
6. replay/concurrent reuse → successสูงสุดหนึ่งครั้ง
7. valid permit + exact target → `Running`, engine count `1`
8. Stopหรือ target exit → runtimeหยุดและ cleanup
9. เปิด Core EXEตรงแล้วส่ง legacy/no-permit start → engine count `0`
10. artifact/log scanไม่พบ private key, token, permit sentinelหรือ reusable proxy credential

**ไม่ต้อง block Minimal V1ด้วย:**

- renewal outage/revocation matrix
- manifest traversal/collision/reparse matrix
- pipe server PID race fixtures
- JWKS/key-fetch failures
- remote attestation/anti-debug tests

---

## 10. Task 7 — Cross-repository E2Eกับ Launcher

**Objective:** พิสูจน์ artifactจริงจาก exact commits แทนเอกสารและ synthetic unit test

**Steps:**

1. ทีม Coreส่ง `win-x64` artifact + SHA-256 + commit SHAให้ Launcher
2. Launcherใช้ artifactนั้นจาก fixed install path
3. ใช้ Backend test deploymentที่มี signerจริงแต่ไม่มี secretใน evidence
4. รันกรณี:
   - no login/no permit
   - invalid permit
   - valid login/entitlement/target
   - replay
   - Stop
   - target exit
5. ยืนยัน valid flowเป็น `challenge → permit → start → Running` หนึ่งครั้ง
6. ยืนยัน negativesไม่มี engine side effectและไม่มี orphan
7. เก็บเฉพาะ sanitized typed result/count/timestamp/artifact identity

**Release evidence:**

- Core branch/full commit SHA
- Launcher branch/full commit SHA
- Core artifact SHA-256
- public key `kid` โดยไม่เผย private material
- exact test/build commandsและ pass/fail count
- explicit secret scan result

---

## 11. Definition of Done — ทีม Core

- [ ] ใช้ `feature/neko-headless` และ preserve frozen baseline ancestry
- [ ] production compositionใช้ strict verifierจริง
- [ ] bundled materialมีเฉพาะ public key
- [ ] no permit/invalid/expired/replay/config mismatchเริ่ม engineไม่ได้
- [ ] valid Backend permitเริ่ม engineได้ exactly once
- [ ] ไม่มี allow-all/local signer/shared secret/offline fallback
- [ ] ไม่มี renewal dependencyใน Minimal V1
- [ ] runtime stop/target-exit cleanupผ่าน
- [ ] `win-x64` artifactสร้างจาก exact reported commit
- [ ] Launcherใช้ artifactนั้นผ่าน real E2Eได้
- [ ] artifact/evidenceไม่มี private key, permit, tokenหรือ reusable proxy credential

---

## 12. Phase 2 — เพิ่มเมื่อ Minimal V1ใช้งานได้แล้ว

พิจารณาทีละข้อเฉพาะเมื่อมี threat/business requirementและ ownerชัดเจน:

- continuous authorizationเพื่อ rapid revocation
- short-lived downstream proxy accessหากสถาปัตยกรรมยังต้องใช้ reusable credential
- signed artifact manifest/runtime file integrity
- exact Named Pipe process identity hardening
- automatic public-key rotation
- anti-tamper/obfuscation

ห้ามนำ Phase 2กลับมาเป็น blockerของ `Backend-signed one-time start permit` เว้นแต่พบช่องโหว่จริงที่ทำให้ผู้ไม่มีสิทธิ์เปิด unmodified Coreได้โดยไม่ patch binary
