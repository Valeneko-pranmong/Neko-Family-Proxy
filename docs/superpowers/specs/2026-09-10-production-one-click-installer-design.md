# Architectural Design: Production One-Click Installer (v5.1.3)

## 1. Goals and Non-Goals
### Goals
- Deliver a single, public `NekoFamilyProxy-Setup.exe` artifact for end users.
- Provide a zero-manual-prerequisite installation experience (silently install .NET 6 Desktop Runtime x64 if missing).
- Reuse existing `installer/beta.iss` and `installer/scripts/build_beta_installer.py` tooling, removing beta labels.
- Maintain the current 4-asset auto-updater contract and network behaviors untouched.

### Non-Goals
- Modifying the existing v5.1.2 immutable assets or tags.
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
  4. Verify and invoke `netfilter2` helper (elevating if necessary; fails closed on incompatible running drivers).
  5. Create shortcuts.

## 5. Prerequisite Policy
- **Microsoft .NET Desktop Runtime 6 x64**: Pinned bootstrapper bundled *inside* `NekoFamilyProxy-Setup.exe`.
- It installs silently if not detected. No external network requests during the installation phase for prerequisites.
- The user is never instructed to download/install .NET manually.

## 6. Update and Release Contract
- **Existing Components**: `NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, and `release-v2.json` remain the exclusive payloads of the auto-update mechanism.
- **Setup Asset**: `NekoFamilyProxy-Setup.exe` acts as a 5th distribution-only GitHub Release asset. It is *not* added to the `release-v2` component set. Existing resolver/updater behavior must remain unchanged.
- **GitHub Release Body**: Public instructions will feature a prominent "For users: download NekoFamilyProxy-Setup.exe" section at the top. The 4 technical assets and source codes will be explicitly labeled as internal/automatic components, not for manual download. (Source code zip/tar.gz are GitHub-generated and not removable.)

## 7. Build Identity and Provenance
- Build scripts will bind `NekoFamilyProxy-Setup.exe` to the exact frozen candidate bytes (Launcher/Updater/Core) used for that release.
- Installer SHA256 and size, along with component authorities, will be recorded in the existing build-record/ledger mechanism (or minimal extension) to guarantee traceability.
- Version targeted is **v5.1.3**. Beta product/output labels inside the installer code will be scrubbed to reflect the production status without creating a duplicate installer subsystem.

## 8. Failure Handling
- **netfilter2**: Fails closed if the driver registration fails or if there is an incompatible running driver.
- **Prerequisites**: If the bundled .NET bootstrapper fails, the installer aborts safely, providing an error log.

## 9. Security
- UAC elevation is delayed and invoked only when required (driver registration or system-wide prerequisite installation).
- Core remains external and verified against `core-manifest.json`.

## 10. CI and Test Acceptance
- **Builder TDD**: Validate script modifications for packaging.
- **Installer-Source/Static Contract Tests**: Validate Inno Setup definitions.
- **Clean Windows Install**: Test installation without preinstalled .NET 6 Desktop Runtime.
- **Install with Runtime Present**: Ensure idempotency and speed.
- **netfilter2 Verification**: Test scenarios with ready and missing driver paths.
- **Smoke Tests**: Launcher startup smoke, updater self-check, Core manifest pass.
- **Uninstall Behavior**: Clean removal of artifacts.
- **Manual Step Proof**: Automated verification that the user is not prompted for any manual prerequisite step.
- Utilize existing test harness and clean Windows CI/VM environments; no new infrastructure unless absolutely necessary.

## 11. Staged Publication and Rollout
- **Verification**: Hosted verification for v5.1.3 must verify the Setup asset identity alongside the 4 update assets, keeping the `release-v2` verifier semantics unchanged.
- **Lifecycle**: PRERELEASE hosted verification -> READY_FOR_ROLLOUT -> explicit owner rollout. No automatic USER rollout until Owner approval.

## 12. Migration from Current v5.1.2
- v5.1.2 is an immutable accepted latest release and will never be modified.
- The new design takes effect strictly from v5.1.3.
- Upon successful rollout of v5.1.3, the public copy for v5.1.2 may optionally clarify that it is superseded, but no v5.1.2 assets will be replaced.

## 13. Future Release Template Impact (v5.1.4+)
- The v5.1.3 deployment serves as the template. Future releases will generate and update the identical `NekoFamilyProxy-Setup.exe` artifact from each accepted frozen candidate via the established release chain.

## 14. Anti-Duplication and YAGNI
- Avoid duplicate installer subsystems. Modify existing `installer/beta.iss` instead of creating a secondary framework.
- No self-contained .NET packaging; rely on the bundled installer method which is simpler and reuses our verified components.
- Do not implement custom UI for the installer beyond the standard Inno Setup wizard. Keep it strictly functional.