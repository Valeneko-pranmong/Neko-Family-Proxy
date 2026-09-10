# Production One-Click Installer v5.1.3 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Include a reviewer gate after each product unit (Task 1, 2, 3) using C0/I0, request-changes loop, single-flight mutations, reuse-before-create, preserve `gh_release.json` if it exists.

**Goal:** Deliver a single, public `NekoFamilyProxy-Setup.exe` artifact for end users integrating a pinned .NET 6 bootstrapper and core components.

**Spec:** `docs/superpowers/specs/2026-09-10-production-one-click-installer-design.md` (commit 237d5e19477fb654044ea89a8fd463fcba5ce2b6)

**Global Constraints:**
- Do not rename internal source files unless a concrete test requires it.
- Fail closed on missing prerequisites (no manual download instructions).
- No mutation of v5.1.2 historical hosted state.
- Strictly YAGNI; 3 product implementation units + independent source acceptance + release chain.
- Preserve `gh_release.json`.

---

## Product Implementation Units

### Task 1: Production installer builder and Inno configuration

**Objective:** Enhance `build_beta_installer.py` with an explicit `--release-version` argument, pass it to `beta.iss` via define, enforce LaunchAllowed constraints, and extend `build-record.json`. Remove manual prerequisite text.

**Files:**
- Modify: `launcher/tests/test_build_beta_installer.py`
- Modify: `installer/scripts/build_beta_installer.py`
- Modify: `installer/beta.iss`

**Step 1: Write RED tests**
Update `launcher/tests/test_build_beta_installer.py` to:
1. Parse `installer/beta.iss` and assert `LaunchAllowed` returns `g_CoreVerifyOK and g_DotnetOK and g_DriverOK`.
2. Parse `installer/beta.iss` and assert no text referencing manual `.NET` download remains.
3. Test `build_beta_installer.py` invocation with `--release-version 5.1.3`. Assert it validates v5.1.x SemVer.
4. Test that `build-record.json` includes `release_version`, `installer_file` (set to `NekoFamilyProxy-Setup.exe`), `installer_hash`, `installer_size`, `launcher_sha256`, `updater_sha256`, `core_authority`, `core_installed_identity` (SHA256 of core-manifest.json), and `dotnet_pinned_version`/`dotnet_pinned_hash`.

**RED Command:** `python -m pytest launcher/tests/test_build_beta_installer.py -v`
**Expected Reason:** Tests will fail because `--release-version` is missing, `LaunchAllowed` does not check all components, manual prerequisite wording is still in `.iss`, and `build-record.json` lacks the new fields.

**Step 2: Minimal Code Behavior**
- Edit `installer/scripts/build_beta_installer.py` to accept `--release-version`, validating `^5\.1\.\d+$`. Pass `/DMyAppVersion={version}` to Inno Setup CLI. Set output filename to `NekoFamilyProxy-Setup.exe`. Populate the extended `build-record.json`. Preserve secret-hygiene and pinned bootstrapper gates.
- Edit `installer/beta.iss` to remove manual prerequisite download steps (fail closed). Set `LaunchAllowed := g_CoreVerifyOK and g_DotnetOK and g_DriverOK`. Ensure `AppVersion={#MyAppVersion}`. Do not create a new static-test framework (add static assertions in the existing test file).

**Step 3: GREEN Command**
Run: `python -m pytest launcher/tests/test_build_beta_installer.py -v`

**Step 4: Commit and Review Gate**
Command: `git commit -m "feat(installer): production v5.1.x setup builder, extended record, launch gates"`
Reviewer verifies C0/I0.

---

### Task 2: GitHub release hosted extra-asset compatibility proof

**Objective:** Prove that the update client ignores `NekoFamilyProxy-Setup.exe` while exact-one checks on the required 4 remain strict. Likely a tests-only commit.

**Files:**
- Modify: `launcher/tests/test_verify_github_release_assets.py`
- Modify: `launcher/tests/test_github_release.py`

**Step 1: Write RED tests**
1. In `launcher/tests/test_verify_github_release_assets.py`: Rename/strengthen `include_extra_asset` fixture to exactly `NekoFamilyProxy-Setup.exe`. Assert that the script verifies the release successfully.
2. In `launcher/tests/test_github_release.py`: Add a GitHub release parser/resolver test proving 5 unique assets parse successfully, while the updater-relevant required 4 assets remain present and valid. Preserve exact-one/duplicate-name/duplicate-id protections.

**RED Command:** `python -m pytest launcher/tests/test_verify_github_release_assets.py launcher/tests/test_github_release.py -v`
**Expected Reason:** Will fail if the extra setup asset violates strict count/name assertions in the verifier or parser.

**Step 2: Minimal Code Behavior**
Do NOT change production verifier/parser unless RED evidence exposes a real defect. If it fails, relax the unlisted asset failure condition specifically for `NekoFamilyProxy-Setup.exe` while preserving the exact-one requirement for `NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, `release-v2.json`.

**Step 3: GREEN Command**
Run: `python -m pytest launcher/tests/test_verify_github_release_assets.py launcher/tests/test_github_release.py -v`

**Step 4: Commit and Review Gate**
Command: `git commit -m "test(release): prove 5-asset compatibility with NekoFamilyProxy-Setup.exe"`
Reviewer verifies C0/I0.

---

### Task 3: Release workflow integration

**Objective:** Stage the 5 assets, update workflow source-acceptance constants, and verify immutability without altering v5.1.2.

**Files:**
- Modify: `launcher/tests/test_release_workflow_github_assets.py`
- Modify: `launcher/tests/test_release_workflow_publication_gate.py`
- Modify: `.github/workflows/release.yml`

**Step 1: Write RED tests**
In `launcher/tests/test_release_workflow_github_assets.py` and `launcher/tests/test_release_workflow_publication_gate.py`: Add `NekoFamilyProxy-Setup.exe` to staged hosted binding and rollout immutability sets. Validate that the verifier invocation still validates only the signed update four. Update release authority from `v5.1.2` to `v5.1.3` wherever workflow source-acceptance constants are intentionally release-specific.

**RED Command:** `python -m pytest launcher/tests/test_release_workflow_github_assets.py launcher/tests/test_release_workflow_publication_gate.py -v`
**Expected Reason:** Tests will fail because `NekoFamilyProxy-Setup.exe` is missing from the workflow's allowed asset arrays and the release version is still `v5.1.2`.

**Step 2: Minimal Code Behavior**
In `.github/workflows/release.yml`: Add `NekoFamilyProxy-Setup.exe` to the expected assets list where appropriate for the 5th immutable asset. Update any hardcoded `v5.1.2` constants to `v5.1.3`.
**IMPORTANT RULING:** Do NOT force GitHub tag CI to build the final Setup from external Core/prerequisite payload; current exact Setup will be built once from frozen local candidate before tag using existing builder, then hosted as immutable fifth asset. Exact-tag CI validates source/tests/workflow and existing Launcher/Updater package path. This avoids inventing secret/external payload transport into CI.

**Step 3: GREEN Command**
Run: `python -m pytest launcher/tests/test_release_workflow_github_assets.py launcher/tests/test_release_workflow_publication_gate.py -v`

**Step 4: Commit and Review Gate**
Command: `git commit -m "ci(workflow): integrate NekoFamilyProxy-Setup.exe asset and update v5.1.3 authority"`
Reviewer verifies C0/I0.

---

## Independent Source Acceptance

### Task 4: Whole-branch Source Acceptance

**Objective:** Independent reviewer C0/I0 verification of the branch before freezing candidates.

**Execution:**
Reviewer executes the canonical repository commands (do not invent coverage percentages):
- `python -m pytest launcher/tests/test_build_beta_installer.py launcher/tests/test_verify_github_release_assets.py launcher/tests/test_github_release.py launcher/tests/test_release_workflow_github_assets.py launcher/tests/test_release_workflow_publication_gate.py -v`
- `python -m ruff check launcher/src launcher/tests`
- `python scripts/check_repository_safety.py`

Independent reviewer verifies passing output (C0) and approves branch integrity (I0).

---

## Release Preparation and Proof Chain

### Task 5: Release-prep and Validation

**Objective:** Fully ordered and exact staging, building, proving, tagging, and publishing sequence.

**Execution (Strict Ordering):**
1. **Source C0/I0:** Complete Task 4.
2. **Fresh Frozen Candidate:** Prepare fresh frozen Launcher/Updater/Core candidate.
3. **Stage .NET Bootstrapper:** Stage pinned `.NET Desktop Runtime 6.0.36` bootstrapper utilizing existing approved SHA256 `0d20debb26fc8b2bc84f25fbd9d4596a6364af8517ebf012e8b871127b798941`.
4. **Build Setup:** Execute builder to output exactly one `NekoFamilyProxy-Setup.exe` from those candidate bytes.
5. **Build-record Binding:** Verify the extended `build-record.json`.
6. **Development-Machine Proof:** Exact-artifact development-machine install/uninstall smoke if safe and already harnessed (e.g. verify runtime-present path where no bootstrapper execution/elevation for .NET is required).
7. **REQUIRED Fresh-Machine Exact-Artifact Proof:**
   - **Environment:** Reuse an already available clean external Windows machine/VM if one becomes available; **otherwise HOLD at FRESH_MACHINE_PROOF_REQUIRED before tag/publication**. Do not install Hyper-V/Sandbox or create infrastructure automatically.
   - **Acceptance Criteria:**
     - No preinstalled .NET6 Desktop Runtime.
     - Run exact Setup.
     - Bundled bootstrapper installs silently after expected UAC.
     - Core verify PASS.
     - netfilter2 ready after expected UAC if missing.
     - Launcher starts.
     - Updater `--self-check` PASS.
     - No manual prerequisite download/install step.
     - Uninstall removes app/shortcuts but preserves shared netfilter2.
8. **Gate2 / Sign Release-v2:** Sign `release-v2.json` `seq7`/`stable-0007` with exactly 3 components + manifest (`Setup` is NOT a signed component).
9. **Immutable Tag:** Tag `v5.1.3`.
10. **Exact-tag CI:** Verify Windows CI is GREEN.
11. **Hosted Publication:** Publish prerelease with exactly FIVE project assets (`NekoFamilyProxy-Setup.exe` + `NekoLauncher.exe` + `NekoUpdater.exe` + `NekoProxyCore.zip` + `release-v2.json`).
    - **Public Copy:** Use `E:/Github/Project manager/current/PUBLIC_RELEASE_TEMPLATE.md` with a prominent first callout: "Normal users download `NekoFamilyProxy-Setup.exe` only; four technical assets are automatic-update components."
12. **Hosted Verifier:** Validate the signed four and separate Setup ID/size/SHA binding against `build-record.json`.
13. **READY_FOR_ROLLOUT -> STOP.** (Never modify `v5.1.2`).
