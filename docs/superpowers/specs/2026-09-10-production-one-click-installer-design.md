# Architectural Design: Production One-Click Installer (v5.1.3)

## 1. Goals and Non-Goals
### Goals
- Deliver a single, public `NekoFamilyProxy-Setup.exe` artifact for end users.
- Provide a zero-manual-prerequisite installation experience (silently install .NET 6 Desktop Runtime x64 if missing).
- Reuse existing installer source (`installer/beta.iss` and `installer/scripts/build_beta_installer.py`); do not require renaming internal source files as a prerequisite.
- Maintain the current 4-asset auto-updater contract and network behaviors untouched.

### Non-Goals
- Modifying the existing v5.1.2 immutable assets or tags (historical v5.1.2 seq6 remains immutable).
- Repacking NekoProxyCore into a .NET self-contained deployment.
- Changing the existing auto-update mechanisms, JSON manifest, or component topologies.
- Implementing automatic updates for the Setup artifact itself; the setup is a distribution mechanism for initial installs.

## 2. Existing Reusable Assets
- **Inno Setup Tooling**: We will adapt `installer/beta.iss` and `build_beta_installer.py`.
- **netfilter2 Helper**: Existing helper to handle driver elevation and registration.
- **Update Protocol**: The 4-asset update mechanism (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, `release-v2.json`).

## 3. User Experience
- The user downloads only one file from GitHub Releases: `NekoFamilyProxy-Setup.exe`.
- The user runs the executable. UAC is triggered only when Windows elevation is genuinely required (e.g., driver registration, prerequisite installation).
- No manual network download of prerequisites; if missing, they are installed silently from the bundled bootstrapper.
- After completion, standard shortcuts are available, and the application is ready.

## 4. Install Layout and Flow
- **Target Path**: Per-user directory at `%LOCALAPPDATA%\NEKO FAMILY`.
- **Contents**:
  - Launcher, Updater, and uncompressed external Core bundle.
  - Standard shortcuts and uninstaller.
- **Flow**:
  1. Check for .NET 6 Desktop Runtime x64.
  2. If missing, run bundled bootstrapper silently.
  3. Extract core application files.
  4. Verify and invoke `netfilter2` helper (elevating if necessary).
  5. Create shortcuts.
- **Install Success Definition**: Only report ready and offer launch when Core verification + .NET runtime detection + required driver readiness ALL pass. (The design explicitly requires all three for production).
- **Uninstall**: Remove app files, shortcuts, and uninstall entry but intentionally preserve the shared netfilter2 machine driver, matching existing policy.

## 5. Prerequisite Policy
- **Microsoft .NET Desktop Runtime 6 x64**: Pinned bootstrapper bundled *inside* `NekoFamilyProxy-Setup.exe`.
- It installs silently if not detected. No install-time prerequisite network download.
- The user is never instructed to download/install .NET manually.

## 6. Update and Release Contract
- **Setup Asset**: `NekoFamilyProxy-Setup.exe` is exactly one additional distribution-only hosted asset; `release-v2` remains exactly the four existing update components (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, and `release-v2.json`).
- **GitHub Release Body**: Public copy after v5.1.3 is published must say USERS download only `NekoFamilyProxy-Setup.exe`; the 4 update assets are automatic-update components and not user installation steps.

## 7. Build Identity and Provenance
- **Exact v5.1.3 release authority**: version 5.1.3, Git tag v5.1.3, release_sequence 7, release_id stable-0007, minimum_supported_sequence 1, channel stable, mandatory false, updater protocol min=1 max=1, key id neko-update-prod-1.
- Specify Inno Setup application/display version 5.1.3 for this successor and public filename exactly `NekoFamilyProxy-Setup.exe`.
- Build scripts will bind `NekoFamilyProxy-Setup.exe` to the exact frozen candidate bytes (Launcher/Updater/Core) used for that release.
- **Manifest**: Use/extend existing `build-record.json` specifically. Record release version, installer filename, installer SHA256/size, exact Launcher SHA256, Updater SHA256, Core authority/installed identity as already available, and pinned .NET bootstrapper version/SHA256. No second manifest.

## 8. Failure Handling
- **Prerequisite Failure Behavior**: No manual download/install instructions. If .NET install is declined/fails or fresh detection still fails, the installer must fail closed for launch: suppress launch, clearly report setup could not complete readiness, and user may rerun the same Setup after allowing required UAC.
- Do not claim transactional rollback unless implementation proves one.
- **Driver**: Same principle for driver readiness/incompatible driver. If driver registration fails or is incompatible, fail closed for launch (suppress launch and report readiness failure).

## 9. Security
- Preserve secret hygiene checks; never package plaintext `runtime-settings.key`, `service-role`, or private keys.
- Pinned Microsoft bootstrapper must be verified before compilation.
- No install-time prerequisite network download.
- UAC elevation is delayed and invoked only when required (driver registration or system-wide prerequisite installation).
- Core remains external and verified against `core-manifest.json`.

## 10. CI and Test Acceptance
- **Acceptance Test Requirement**: Prove GitHubReleaseResolver/update verifier still accepts a stable release that has the required 4 assets PLUS `NekoFamilyProxy-Setup.exe` and ignores the extra distribution asset for update resolution. Do not weaken exact-one checks for the required four.
- **Clean Machine Proof**: Without preinstalled runtime, must verify no manual prerequisite download step and only expected UAC.
- **Runtime-Present Path**: Must prove no unnecessary .NET bootstrapper execution/elevation.
- **Driver-Ready Path**: Must prove no driver elevation.
- **Missing-Driver Path**: Must prove expected elevation.
- **Failure Paths**: Suppress launch.
- **Clean Uninstall**: Preserves shared driver.
- Utilize existing test harness and clean Windows CI/VM environments; no new infrastructure unless absolutely necessary.

## 11. Staged Publication and Rollout
- **Verification**: Hosted verification for v5.1.3 must verify the Setup asset identity alongside the 4 update assets.
- **Lifecycle**: PRERELEASE hosted verification -> READY_FOR_ROLLOUT -> explicit owner rollout. No automatic USER rollout until Owner approval.

## 12. Migration from Current v5.1.2
- v5.1.2 is an immutable accepted latest release and will never be modified. (Historical v5.1.2 seq6 remains immutable).
- The new design takes effect strictly from v5.1.3.

## 13. Future Release Template Impact (v5.1.4+)
- Future 5.1.4+ same pattern; Setup built from each frozen candidate and verified as hosted distribution asset.

## 14. Anti-Duplication and YAGNI
- Avoid duplicate installer subsystems. Modify existing `installer/beta.iss` instead of creating a secondary framework.
- No self-contained .NET packaging; rely on the bundled installer method which is simpler and reuses our verified components.
- Do not implement custom UI for the installer beyond the standard Inno Setup wizard. Keep it strictly functional.
