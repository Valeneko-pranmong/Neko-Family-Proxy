# Launcher V2

This directory is the rebuilt desktop launcher. The legacy implementation is
preserved under `../original-code/v1/` for reference only and still requires
endpoint review before any public release.

## Set up and run from source

```powershell
Set-Location launcher
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env.local
```

Set `NEKO_SUPABASE_PUBLISHABLE_KEY` in `.env.local`. The desktop application
must use only the project's publishable key. Never place a Supabase secret or
service-role key in the launcher configuration.

Run the launcher:

```powershell
.\.venv\Scripts\python.exe -m neko_launcher.main
```

Run the validation suite:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q -m "not integration"
```

The live Supabase flow is intentionally separate because it changes disposable
test data. Configure the `NEKO_INTEGRATION_*` variables documented in
`.github/workflows/supabase-integration.yml`, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m integration
```

## Implemented customer flows

- Email/password registration and sign-in through Supabase Auth.
- Email-confirmation handling when the project requires confirmation.
- Auth-session persistence in the operating system credential vault.
- Random per-installation identity; no hardware fingerprint is collected.
- License validation and single-session claim through the `launcher` schema.
- A 30-second session heartbeat with revocation after a server rejection or
  three consecutive connection failures.
- Coupon redemption through `launcher.redeem_coupon`.
- A hard guard that prevents ProxyCore from starting without an authenticated
  user, active entitlement, and claimed launcher session.
- Launcher-session release on sign-out and application shutdown.

## Required Supabase configuration

The project must expose the `launcher` schema through the Data API and grant
the authenticated role access only to these RPCs:

- `launcher.claim_session`
- `launcher.heartbeat_session`
- `launcher.release_session`
- `launcher.redeem_coupon`

The public tables remain protected by RLS and must not grant direct customer
write access. The launcher never uses a secret/service-role key.

## Runtime dependency

Set `NEKO_PROXY_CORE_PATH` in `.env.local` when testing a nonstandard runtime
location. The default installed location is:

`%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\ProxyCore.exe`

The runtime is delivered separately under the contract in
`../RUNTIME_DISTRIBUTION.md`; it is not built into the executable or installer.

## Windows package

After installing, copy
`%LOCALAPPDATA%\NEKO FAMILY\launcher.env.example` to
`%LOCALAPPDATA%\NEKO FAMILY\launcher.env` and set the Supabase URL and
publishable key. This key is safe for a desktop client; never put a secret or
service-role key in that file.

Install the release tools and build the executable:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,release]"
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm NekoLauncher.spec
```

The `Windows release` GitHub Actions workflow runs tests, builds the executable
and Inno Setup installer, emits SHA-256 checksums, and publishes release files
only for version tags. Manual workflow runs create downloadable CI artifacts
without publishing a GitHub release.

The customer-facing UI preserves the original pink Neko Family brand palette,
logo, and Windows application icon. Shared colors live in `ui/theme.py`.
