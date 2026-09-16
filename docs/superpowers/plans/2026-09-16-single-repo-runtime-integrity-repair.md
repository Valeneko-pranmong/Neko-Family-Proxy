# Runtime Mandatory Update + Integrity Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every newer authenticated 5.x release mandatory before normal use, add user-invoked File Check and exact-release Repair through the trusted Updater, and make installed clients machine-bound so copied folders/direct GitHub assets cannot become usable portable clients.

**Architecture:** Preserve the existing authenticated release resolver, durable release identity, selective Launcher/Core staging, Updater IPC admission, transactional apply/rollback, and backend auth/session/permit model. Add three narrow layers: a startup compatibility gate that distinguishes newer 5.x from incompatible 6.x, a read-only integrity inspector plus explicit repair request that reuses the Updater transaction path, and an Installer-provisioned Windows machine-protected installation credential validated before login/service flow.

**Tech Stack:** Python 3.12, pytest, existing Launcher UI/application layer, Windows DPAPI/CNG-backed credential abstraction, existing signed release/trust profile infrastructure, NekoUpdater IPC/state machine.

**Spec:** `docs/superpowers/specs/2026-09-16-single-repo-unified-release-design.md`

**Execution contracts:** `docs/superpowers/plans/2026-09-16-single-repo-plan-contracts.md`

## Global Constraints

- A newer authenticated 5.x release is mandatory; there is no Skip, Later, continue-offline, or use-old-version path.
- Auto Update within 5.x may replace Launcher and Core only. `NekoUpdater.exe` never self-updates during 5.x.
- If Updater is missing/corrupt/untrusted/incompatible, fail closed and instruct uninstall/reinstall.
- 5.x -> 6.0.0 is never an in-place update; require uninstall 5.x and fresh install 6.0.0.
- File Check is user-invoked and diagnostic-only. It must not download or mutate files.
- Repair occurs only after explicit user action, uses the trusted Updater, and restores the exact installed release rather than silently upgrading.
- Directly downloaded Launcher assets and copied install folders must fail before normal login/service use unless Installer-provisioned machine binding is valid on that Windows machine.
- Reinstalling Windows/replacing disk may create a new installation binding and log in normally; manual admin approval is not required.
- Existing single-active-session, entitlement, heartbeat, replay, and launch-permit enforcement must remain authoritative and unchanged in meaning.
- TDD RED -> GREEN and independent C0/I0 review are mandatory for every task.

---

## File Structure / Responsibility Map

- `launcher/src/neko_launcher/application/software_update_policy.py` — mandatory compatible update vs major/incompatible reinstall classification.
- `launcher/src/neko_launcher/application/software_update_coordinator.py` — startup gate orchestration and no-bypass outcome.
- `launcher/src/neko_launcher/infrastructure/software_update_stage.py` — selective Launcher/Core staging; keep Updater excluded.
- `launcher/src/neko_launcher/infrastructure/github_release.py` + `github_release_binding.py` — exact canonical/historical release lookup and authenticated asset identity.
- `launcher/src/neko_launcher/updater/trust_profile.py`, `updater/enrollment.py`, `updater/main.py`, updater state/IPC modules — trusted helper integrity/admission and repair apply.
- `launcher/src/neko_launcher/bootstrap/app_factory.py`, `baseline_enrollment.py`, `pending_update_bootstrap.py`, `launcher/src/neko_launcher/main.py` — startup ordering before normal login/UI flow.
- New `launcher/src/neko_launcher/application/file_integrity.py` — read-only File Check model/service.
- New `launcher/src/neko_launcher/application/file_repair.py` — explicit exact-release repair coordinator.
- New `launcher/src/neko_launcher/infrastructure/installation_credential.py` — Installer-provisioned machine-bound proof provider.
- Existing authorization modules `application/authorized_core.py` / `production_authorization.py` — regression-first; edit only if tests prove a concrete gap.

### Task RT-SR1: Mandatory 5.x startup gate and 6.x reinstall boundary

**Files:**
- Modify: `launcher/src/neko_launcher/application/software_update_policy.py`
- Modify: `launcher/src/neko_launcher/application/software_update_coordinator.py`
- Modify: exact startup composition/bootstrap call site only if required by failing test
- Test: `launcher/tests/test_software_update_policy.py`
- Test: `launcher/tests/test_software_update_coordinator.py`
- Test: existing startup/UI one-shot tests

**Interfaces:**
- Produces: `StartupUpdateDisposition` and `classify_startup_release(...)` defined in the execution-contract companion.

- [ ] **Step 1: Add RED policy tests** for 5.1.2 -> 5.1.3 mandatory, same exact release current, newer 5.x with `mandatory=false` still mandatory, 5.x -> 6.0.0 reinstall-required, incompatible updater protocol reinstall-required, invalid/untrusted remote fail-closed.
- [ ] **Step 2: Run `launcher/.venv/Scripts/python.exe -B -m pytest launcher/tests/test_software_update_policy.py launcher/tests/test_software_update_coordinator.py -q`** and capture RED before production edits.
- [ ] **Step 3: Implement classification rules** exactly from the companion contract. Keep rollback/same-sequence conflict handling on existing fail-closed paths.
- [ ] **Step 4: Add RED coordinator/startup tests** proving login/service composition is never reached while disposition is mandatory-update or reinstall-required and Retry cannot turn into stale-use bypass.
- [ ] **Step 5: Wire the startup gate before normal login/service flow** while preserving pending-update recovery.
- [ ] **Step 6: Run focused tests GREEN**, Ruff, repository safety, `git diff --check`.
- [ ] **Step 7: Commit** `feat: enforce mandatory compatible updates at startup`.
- [ ] **Step 8: Independent C0/I0 review**.

### Task RT-SR2: Trusted Updater integrity gate and reinstall-required outcome

**Files:**
- Modify: `launcher/src/neko_launcher/infrastructure/github_release_binding.py`
- Modify: coordinator/bootstrap outcome mapping
- Modify: updater trust/enrollment validation only if existing binding lacks required expected SHA/protocol data
- Test: GitHub binding, update composition, pending-update, updater entrypoint tests

**Interfaces:**
- Produces: `InstalledUpdaterVerification` and `verify_installed_updater(...)` from the companion.

- [ ] **Step 1: Add RED tests** for missing Updater, wrong hash, wrong size, incompatible protocol, and valid updater; prove no downloader/stager/updater-session mutation occurs on failure.
- [ ] **Step 2: Use `file_find` to identify exact existing binding/composition/updater test files, then run that focused set RED** before production edits.
- [ ] **Step 3: Implement `verify_installed_updater`** by composing existing release binding + installed updater SHA/protocol checks. There is no self-download/self-replace branch.
- [ ] **Step 4: Map failure to `REINSTALL_REQUIRED`** at startup and repair call sites and add tests proving no updater session launch on failure.
- [ ] **Step 5: Run GREEN**, Ruff, repository safety, `git diff --check`.
- [ ] **Step 6: Commit** `feat: fail closed on untrusted updater helper`.
- [ ] **Step 7: Independent C0/I0 review**.

### Task RT-SR3: Persist exact installed release identity for historical File Check/Repair

**Files:**
- Modify: exact durable local release identity/state module discovered from current coordinator/updater state
- Modify: `launcher/src/neko_launcher/infrastructure/github_release.py`
- Modify: `launcher/src/neko_launcher/infrastructure/github_release_binding.py`
- Test: existing local identity, GitHub release, binding, updater-state tests

**Interfaces:**
- Produces: `InstalledReleaseSelector` and exact resolver semantics from the companion, while retaining existing committed/high-water/observed/failed release ordering.

- [ ] **Step 1: Add RED serialization tests** ensuring exact selector fields round-trip and old state migrates only when identity is deterministic; ambiguous old state fails closed rather than guessing.
- [ ] **Step 2: Add RED resolver tests** proving File Check/Repair requests exact tag/release identity and never calls GitHub `latest`.
- [ ] **Step 3: Run focused identity/resolver tests RED**.
- [ ] **Step 4: Extend durable identity minimally** with exact selector fields and canonical serialization/validation.
- [ ] **Step 5: Add exact release resolution** through canonical repo/tag plus existing signed-envelope validation.
- [ ] **Step 6: Run GREEN**, Ruff, repository safety, `git diff --check`.
- [ ] **Step 7: Commit** `feat: retain exact installed release identity`.
- [ ] **Step 8: Independent C0/I0 review**.

### Task RT-SR4: User-invoked File Check diagnostic

**Files:**
- Create: `launcher/src/neko_launcher/application/file_integrity.py`
- Modify: exact existing settings/support UI controller found by current UI tests
- Test: `launcher/tests/test_file_integrity.py`
- Test: matching existing UI test module

**Interfaces:**
- Produces: `IntegrityStatus`, `FileIntegrityItem`, `FileIntegrityReport`, and `check_installed_files(...)` from the companion.

- [ ] **Step 1: Write `launcher/tests/test_file_integrity.py` RED cases** for OK, missing, size mismatch, hash mismatch, Updater mismatch => reinstall-required, repairable components == launcher/core only, and strict read-only behavior.
- [ ] **Step 2: Run the new test file RED**; expected failure is missing module/types/function.
- [ ] **Step 3: Implement `file_integrity.py`** with streamed SHA-256 and authenticated exact-release expectations; no downloader/stager/updater dependency in the read-only service.
- [ ] **Step 4: Add UI RED tests**: explicit Check button starts check; per-file results render; Repair enabled only for repairable Launcher/Core findings with trusted Updater; check completion never starts repair automatically.
- [ ] **Step 5: Wire UI/controller to the service** without background mutation.
- [ ] **Step 6: Run GREEN**, Ruff, repository safety, `git diff --check`.
- [ ] **Step 7: Commit** `feat: add read-only installed file check`.
- [ ] **Step 8: Independent C0/I0 review**.

### Task RT-SR5: Explicit exact-release Repair through the trusted Updater

**Files:**
- Create: `launcher/src/neko_launcher/application/file_repair.py`
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_stage.py`
- Modify: exact Updater IPC/admission transaction module only if repair intent must cross IPC
- Test: `launcher/tests/test_file_repair.py`
- Test: existing stage/updater transaction tests

**Interfaces:**
- Produces: `RepairRequest` and `repair_installed_release(...)` with the nine-step algorithm in the companion.

- [ ] **Step 1: Write RED repair tests** for exact installed tag/version, Launcher-only/Core-only/both, rejected Updater component, unsigned/wrong-hash/wrong-repo/wrong-tag, no latest substitution, and no version change.
- [ ] **Step 2: Run `launcher/.venv/Scripts/python.exe -B -m pytest launcher/tests/test_file_repair.py -q`** and capture RED before production edits.
- [ ] **Step 3: Implement `file_repair.py`** to validate request, resolve exact release, revalidate Updater, download/verify only damaged Launcher/Core, stage with explicit repair intent, apply through existing Updater transaction, then re-run File Check.
- [ ] **Step 4: If IPC needs repair intent, add only a closed enum/field** accepted by Launcher+Updater; default/update behavior remains unchanged and arbitrary file paths/components remain rejected.
- [ ] **Step 5: Run repair + stage + updater transaction tests GREEN**, Ruff, repository safety, `git diff --check`.
- [ ] **Step 6: Commit** `feat: repair damaged installed release files`.
- [ ] **Step 7: Independent C0/I0 review**.

### Task RT-SR6: Installer-provisioned machine-bound installation credential

**Files:**
- Create: `launcher/src/neko_launcher/infrastructure/installation_credential.py`
- Modify: Installer/bootstrap enrollment provisioning path
- Modify: startup composition before login/service flow
- Modify: server/client enrollment proof payload only if characterization tests prove current backend does not bind installation proof
- Test: `launcher/tests/test_installation_credential.py`
- Test: baseline enrollment/composition/startup copied-install tests

**Interfaces:**
- Produces: `InstallationCredentialProvider`, public identity/proof models, and startup ordering from the companion.
- Production Windows provider: prefer CNG non-exportable machine key. If project/runtime constraints make CNG unavailable, use DPAPI machine-scope protection for generated key material behind the same non-exporting application interface. Hardware fingerprint is not the secret.

- [ ] **Step 1: Write provider RED tests** for provision/load/prove, missing/corrupt protected state, non-exporting interface, and deterministic fake provider.
- [ ] **Step 2: Run `launcher/.venv/Scripts/python.exe -B -m pytest launcher/tests/test_installation_credential.py -q`** and capture RED before production edits.
- [ ] **Step 3: Implement provider abstraction and Windows backend**; log only public id/error code, never secret bytes or protected blob content.
- [ ] **Step 4: Write RED bootstrap/enrollment tests**: Installer provisions credential; direct Launcher without it stops before login; copied public/state files on fake second machine cannot prove challenge; same-machine start succeeds; reinstall provisions a new public identity.
- [ ] **Step 5: Wire machine proof into existing enrollment/server authorization boundary**. If current backend contract already supports installation proof, reuse it; otherwise add the smallest challenge/proof fields and server validation required so modified public clients cannot bypass the local-only check.
- [ ] **Step 6: Run credential + enrollment + authorization/permit regressions GREEN**, Ruff, repository safety, `git diff --check`.
- [ ] **Step 7: Commit** `feat: bind installed client to provisioned machine credential`.
- [ ] **Step 8: Independent security review C0/I0**.

### Task RT-SR7: Preserve single-active-session behavior across reinstall/new machine identity

**Files:**
- Prefer tests only in existing auth/session/heartbeat/permit suites
- Modify production authorization/backend adapter only if a failing characterization test proves a gap

**Interfaces:**
- New installation/login may become current active authority without manual admin approval.
- Previous active session becomes inactive: future permit issuance denied and heartbeat/session authority fails closed according to existing protocol.

- [ ] **Step 1: Add characterization tests** for machine A active -> machine B reinstall/login -> B active and A inactive; historical installation identity may remain recorded but cannot remain concurrent active authority.
- [ ] **Step 2: Run focused auth/session/heartbeat/permit tests**. If characterization passes without source edits, keep tests only and do not alter production authorization.
- [ ] **Step 3: If a RED gap exists, make the smallest authority fix** that invalidates old active session while retaining entitlement/heartbeat/replay semantics.
- [ ] **Step 4: Run full relevant auth/Core permit regressions GREEN**, Ruff, repository safety, `git diff --check`.
- [ ] **Step 5: Commit** `test: preserve single active session across reinstall` when tests-only, or a narrowly scoped `fix:` message when production code changed.
- [ ] **Step 6: Independent C0/I0 review**.

### Task RT-SR8: Runtime workstream acceptance

**Files:**
- Evidence/tests only; any blocker creates a separately scoped remediation + re-review task

- [ ] **Step 1: Run full Launcher pytest suite**, all new update/integrity/repair/machine-binding/auth/UI focused suites, Ruff, repository safety, `git diff --check`.
- [ ] **Step 2: Build canonical Launcher + Updater with frozen release toolchain** and run built Updater `--self-check`.
- [ ] **Step 3: Run packaged/local scenarios**: mandatory 5.x happy path; network/update failure no-bypass; 6.x reinstall gate; File Check no mutation; exact-release Repair; corrupt Updater reinstall-required; direct Asset rejection; copied-folder rejection; reinstall/login; old session invalidation.
- [ ] **Step 4: Write durable runtime acceptance evidence** with exact commit/test counts/build hashes and no secret material.
- [ ] **Step 5: Independent runtime workstream review** must return C0/I0.

## Completion Gate

RT-SR1..RT-SR8 must be independently accepted, branch clean, and no public release/signing/tag authority mutated. Runtime work integrates only after Release Authority + Publisher workstream also reaches C0/I0.
