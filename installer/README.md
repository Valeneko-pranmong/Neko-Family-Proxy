# Closed Beta single-EXE installer source

Builds `NekoFamilyProxy-Beta-Setup.exe`: a per-user installer that deploys the
approved `NekoLauncher.exe` plus the complete external ProxyCore bundle into
`%LOCALAPPDATA%\NEKO FAMILY\`, verifies the installed Core against
`core-manifest.json`, and prepares the netfilter2 driver through the existing
supported registration path when needed.

Layout:

- `beta.iss` - Inno Setup script (PrivilegesRequired=lowest; elevation only
  for optional driver registration).
- `scripts/build_beta_installer.py` - fail-closed orchestrator: verifies the
  staged payload against the approved authorities, compiles with ISCC, records
  size + SHA-256.
- `scripts/verify-core-install.ps1` - post-install Core manifest verification
  (runs during install).
- `scripts/ensure-netfilter2.ps1` - netfilter2 readiness/registration helper
  reusing the proven `Redirector.bin!aio_register("netfilter2")` path.

## Build

1. Stage the approved payload OUTSIDE the repository at
   `D:\Build\NekoBetaInstaller\payload\`:

   - `NekoLauncher.exe` (approved SHA-256)
   - `CoreBundle\` (complete Core bundle including `core-manifest.json` and
     `runtime-settings.nkps`; never any plaintext settings or key)

2. Run:

   ```text
   python installer\scripts\build_beta_installer.py
   ```

   The build aborts before compiling if any approved hash/manifest/secret gate
   fails. Output lands in `D:\Build\NekoBetaInstaller\out\` together with
   `build-record.json`.

3. Never commit the generated Setup EXE (`installer/.gitignore` blocks `out/`).

## Test evidence policy

Installer changes require: silent install exit 0, Launcher SHA-256 at the
install target unchanged from approved, installed Core manifest PASS,
netfilter2 RUNNING, Launcher startup smoke, clean uninstall that preserves the
shared netfilter2 driver, and byte-identical restore proof against the
pre-test baseline.
