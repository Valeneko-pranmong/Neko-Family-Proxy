# Closed Beta single-EXE installer source

Builds `NekoFamilyProxy-Beta-Setup.exe`: a per-user installer that deploys the
approved `NekoLauncher.exe` plus the complete external ProxyCore bundle into
`%LOCALAPPDATA%\NEKO FAMILY\`, verifies the installed Core against
`core-manifest.json`, and prepares the netfilter2 driver through the existing
supported registration path when needed.

Layout:

- `beta.iss` - Inno Setup script (PrivilegesRequired=lowest; elevation only
  for optional driver registration or the .NET Desktop Runtime silent
  install; x64-only hard block per PM decision D2).
- `scripts/build_beta_installer.py` - fail-closed orchestrator: verifies the
  staged payload against the approved authorities (including the pinned .NET
  Desktop Runtime 6 x64 bootstrapper version + SHA-256), compiles with ISCC,
  records size + SHA-256.
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
   - `Prereqs\windowsdesktop-runtime-*-win-x64.exe` (.NET Desktop Runtime 6.x
     x64 bootstrapper; its version and official SHA-256 must be pinned in
     `scripts/build_beta_installer.py` before a release build can pass)

2. Run:

   ```text
   python installer\scripts\build_beta_installer.py
   ```

   The build aborts before compiling if any approved hash/manifest/secret gate
   fails — including gate 4, which fails closed with a clear Thai/English
   error while the approved .NET bootstrapper is absent or unpinned, so an
   unverified prerequisite binary can never be packaged. Output lands in
   `D:\Build\NekoBetaInstaller\out\` together with `build-record.json`.

3. Never commit the generated Setup EXE (`installer/.gitignore` blocks `out/`).

## 5.1.6/5.2.0 separation guard

`beta.iss` now fails closed before installation when any of these is true:

- `NekoLauncher`, `NekoProxyCore`, or `NekoUpdater` is still running.
- An existing `NekoLauncher.exe` has no verifiable uninstall `DisplayVersion`.
- The installed version is not exactly the installer's `MyAppVersion` (5.2.0).

A 5.1.6 installation is therefore blocked until it is uninstalled through
Windows Settings > Apps. A 5.2.0 reinstall is allowed. Local state is a clean
start; no settings, auth, trust, or session state is carried across the line.
The source guard has static tests, but ISCC and the full install/uninstall
matrix are still required before publication.

## Installer runtime behavior (.NET Desktop Runtime)

- Detection: the post-install step probes
  `%ProgramFiles%\dotnet\shared\Microsoft.WindowsDesktop.App\*` for any 6.x+
  shared Desktop Runtime (authoritative for x64 because `ArchitecturesAllowed=x64`
  hard-blocks non-x64 hosts).
- If missing, setup requests ONE elevation and runs the staged bootstrapper
  silently (`/install /quiet /norestart`), then re-runs the unelevated
  detection; that fresh re-check — not the installer exit code — decides the
  outcome (same fail-closed pattern as the netfilter2 driver step).
- If the runtime is still missing after setup, a clear error is shown and the
  optional launch action stays suppressed (`LaunchAllowed` requires Core
  verification AND runtime presence).

## Driver registration hardening

The installer build pins the SHA-256 of `core-manifest.json`,
`bin\Redirector.bin`, and `bin\nfdriver.sys` and passes those values to the
elevated helper. The helper verifies the manifest and every declared driver
file before touching machine state, then copies the verified driver, redirector,
and declared DLLs into an admin-only staging directory under
`%ProgramData%\NekoFamily\driver-stage`. `Redirector.bin` is loaded from that
staging directory, not from the user-writable `%LOCALAPPDATA%` Core folder, and
the staging directory is removed afterwards.

Residual risk: `ensure-netfilter2.ps1` itself still runs from the per-user app
directory. Full protection against a same-user script swap requires a signed
helper installed in an admin-only location.

## Test evidence policy

Installer changes require: silent install exit 0, Launcher SHA-256 at the
install target unchanged from approved, installed Core manifest PASS,
netfilter2 RUNNING, Launcher startup smoke, clean uninstall that preserves the
shared netfilter2 driver, and byte-identical restore proof against the
pre-test baseline.

.NET bootstrap evidence additionally requires:

1. Prebuild: with no `Prereqs\windowsdesktop-runtime-*-win-x64.exe` staged,
   `build_beta_installer.py` aborts at gate 4 with the Thai/English fail-
   closed message (negative-proof log kept with the build record).
2. On a machine WITHOUT Desktop Runtime 6 x64: exactly one UAC prompt, the
   silent install completes, the fresh re-detection logs the found 6.x
   version, and the launch action runs.
3. On a machine WITH Desktop Runtime 6 x64 already present: NO elevation
   prompt and no bootstrapper execution (probe-only path proven via setup log).
4. Failure path: with runtime still absent after setup (e.g. elevated install
   declined), the error dialog appears and the post-install summary logs
   `dotnet_ok=0`; the launcher shortcut's optional launch is suppressed.
