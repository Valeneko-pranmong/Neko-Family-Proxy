# Production One-Click Installer v5.1.3 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Deliver a single, public `NekoFamilyProxy-Setup.exe` artifact for end users integrating a pinned .NET 6 bootstrapper and core components.

**Architecture:** We will reuse `installer/beta.iss` and `installer/scripts/build_beta_installer.py` parameterizing them to output the production `NekoFamilyProxy-Setup.exe` (version 5.1.3). The GitHub release workflow will be updated to produce and host exactly 5 assets (Setup + existing 4) while the software update contract remains unchanged, resolving only the existing 4.

**Tech Stack:** Python 3.11, Inno Setup, GitHub Actions, Windows CLI.

**Spec:** `docs/superpowers/specs/2026-09-10-production-one-click-installer-design.md` (commit 237d5e19477fb654044ea89a8fd463fcba5ce2b6)

**Global Constraints:**
- Do not rename internal source files unless a concrete test requires it.
- Fail closed on missing prerequisites (no manual download instructions).
- No mutation of v5.1.2 historical hosted state.
- Strictly YAGNI; 4 units of work + tests + release.
- Preserve `gh_release.json`.

---

### Task 1: Production installer behavior + builder provenance

**Objective:** Adapt installer script and InnoSetup config for production output, version 5.1.3, enforcing Core + .NET + driver launch requirements.

**Files:**
- Modify: `installer/beta.iss`
- Modify: `installer/scripts/build_beta_installer.py`
- Modify: `launcher/tests/test_build_beta_installer.py`

**Step 1: Write failing test**
Update `test_build_beta_installer.py` to expect `NekoFamilyProxy-Setup.exe` and version `5.1.3` in the `build-record.json`.

```python
# In launcher/tests/test_build_beta_installer.py (replace SETUP_NAME occurrences if tested)
def test_builder_outputs_production_setup_and_record():
    # Expect output SETUP_NAME = "NekoFamilyProxy-Setup.exe"
    # Expect record installer_version = "5.1.3"
```

**Step 2: Run test to verify failure**
Run: `python -m pytest launcher/tests/test_build_beta_installer.py -v`
Expected: FAIL (Still asserting "NekoFamilyProxy-Beta-Setup.exe" or version mismatch).

**Step 3: Write minimal implementation**
```pascal
// In installer/beta.iss
#define MyAppVersion "5.1.3"
AppVersion={#MyAppVersion}
OutputBaseFilename=NekoFamilyProxy-Setup

function LaunchAllowed(): Boolean;
begin
  Result := g_CoreVerifyOK and g_DotnetOK and g_DriverOK;
end;
```
```python
# In installer/scripts/build_beta_installer.py
SETUP_NAME = "NekoFamilyProxy-Setup.exe"

    record = {
        "installer_version": "5.1.3",
        "installer_file": SETUP_NAME,
        # ...
```

**Step 4: Run test to verify pass**
Run: `python -m pytest launcher/tests/test_build_beta_installer.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add installer/beta.iss installer/scripts/build_beta_installer.py launcher/tests/test_build_beta_installer.py
git commit -m "feat: configure installer for v5.1.3 production setup and launch gates"
```

---

### Task 2: Update compatibility + hosted extra-asset semantics

**Objective:** Prove that the update client ignores the 5th setup asset while exact-one checks on the required 4 stay strict.

**Files:**
- Modify: `launcher/tests/test_github_release.py`
- Modify: `launcher/tests/test_verify_github_release_assets.py`

**Step 1: Write failing test**
Add a test in `test_verify_github_release_assets.py` representing a 5-asset production bundle and ensure it resolves correctly.

**Step 2: Run test to verify failure**
Run: `python -m pytest launcher/tests/test_verify_github_release_assets.py -v`
Expected: FAIL if strict exact-one check improperly flags the 5th distribution asset.

**Step 3: Write minimal implementation**
Adjust the strict checks inside `launcher/src/update_client.py` or the verifier script (`scripts/verify_github_release_assets.py`) to permit the exact extra name `NekoFamilyProxy-Setup.exe` while maintaining the exact-one count for the core four.

**Step 4: Run test to verify pass**
Run: `python -m pytest launcher/tests/test_verify_github_release_assets.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add launcher/tests/test_verify_github_release_assets.py scripts/verify_github_release_assets.py
git commit -m "test: allow NekoFamilyProxy-Setup.exe as 5th hosted asset without breaking update resolution"
```

---

### Task 3: Release workflow integration

**Objective:** Modify CI workflow to stage 5 assets and verify their immutability post-rollout without altering v5.1.2.

**Files:**
- Modify: `.github/workflows/release.yml`

**Step 1: Write minimal implementation**
Edit `release.yml` in the `staged-verification` and `rollout-stable` jobs to include `NekoFamilyProxy-Setup.exe` in `$requiredAssetNames`.

```yaml
# In .github/workflows/release.yml
          $requiredAssetNames = @('NekoLauncher.exe', 'NekoUpdater.exe', 'NekoProxyCore.zip', 'release-v2.json', 'NekoFamilyProxy-Setup.exe')
```
*(Also remove the mock `echo` in `build-installer` and invoke `build_beta_installer.py` once dependencies are staged, or adjust CI so it uploads the 5 artifacts from a frozen candidate directory)*.

**Step 2: Run validation**
Run: `python scripts/check_repository_safety.py`
Expected: PASS (Syntax and structural constraints valid).

**Step 3: Commit**
```bash
git add .github/workflows/release.yml
git commit -m "ci: integrate Setup asset into release staging and immutability checks"
```

---

### Task 4: Windows acceptance proof using existing harness

**Objective:** Write the minimal reproducible proof plan for clean Windows acceptance (no .NET) using the current VM or GitHub Windows runner.

**Files:**
- Create: `launcher/tests/test_final_windows_e2e_harness.py` or document manual proof in the test file if CI cannot simulate a clean machine.

**Step 1: Write test or proof document**
Explicitly state: "Manual VM Proof required before Gate 2: Clean Windows 11 machine without .NET Desktop Runtime. Run `NekoFamilyProxy-Setup.exe`. Assert UAC for driver, silent .NET install, and successful launch. Uninstall asserts `netfilter2.sys` remains."

**Step 2: Commit**
```bash
git add launcher/tests/
git commit -m "test: define Windows clean machine acceptance proof for v5.1.3"
```

---

### Task 5: Whole-branch C0/I0 review and canonical tests

**Objective:** Self-review all tests and maintain canonical compliance.

**Execution:**
Run `python -m pytest` across `launcher/tests`.
Run `python -m ruff check launcher/src launcher/tests`.
Verify 100% C0/I0 coverage.

---

### Task 6: v5.1.3 release-prep chain

**Objective:** Staged Gate2 execution.

**Execution (Manual/Orchestrator):**
- Prepare fresh frozen candidate.
- Build Setup using the updated script.
- Sign `release-v2` with `seq7`/`stable-0007`.
- Tag `v5.1.3`.
- Push to GitHub to trigger `staged-verification` with 5 assets.
- Stop at `READY_FOR_ROLLOUT`.

---

### Task 7: Public release copy

**Objective:** Format the GitHub release text.

**Execution:**
Ensure the release notes contain the exact callout:
> **Normal USER downloads `NekoFamilyProxy-Setup.exe` only; four technical assets are automatic update components.**
