# Neko Family Launcher

Desktop launcher for Supabase username/password membership, entitlement checks,
launcher-session control, and user-selected PSO2 Tweaker configuration.

> **Current status (24 August 2026):** the accepted NEKO-AUTH-LITE production
> composition is active. Core startup remains fail-closed unless Auth, the
> current Launcher session, ACTIVE entitlement, exact PSO2 identity, fresh
> challenge/permit, and typed RUNNING checks all succeed.

## Set up

```powershell
python -m pip install -e ".[dev,release]"
```

The launcher contains the Supabase project URL and publishable client key.
Publishable keys are safe for desktop clients; never place a
secret/service-role key in the launcher.

Run from source:

```powershell
python -m neko_launcher.main
```

## Debug console

After building `dist/NekoLauncher.exe`, run the live diagnostic console with:

```powershell
.\NekoLauncherDebugConsole.cmd
```

It launches the packaged executable with `--debug` and streams launcher/Core
status from `%LOCALAPPDATA%\NEKO FAMILY\logs`. See the
[debug console guide](../docs/current/debug-console.md) for stage meanings,
log files, troubleshooting, and security guidance.

## Customer flow

1. Register with a username and password.
2. Sign in with the username; the Launcher derives the deterministic,
   non-PII Supabase Auth identifier locally.
3. Contact an administrator if the password is forgotten; email reset is not
   part of the Launcher.
4. Change the password from the Launcher after signing in.
5. Check remaining entitlement time or redeem a coupon.
6. Select `Tweaker.exe`; the launcher remembers the path.
7. Request startup. The Launcher spawns the exact owned external Core host,
   then performs fresh authorized startup.

## Validation

```powershell
python -m ruff check src tests
python -m pytest -q -m "not integration"
```

Integration tests require disposable Supabase credentials:

```powershell
python -m pytest -q -m integration
```

## One-file build

The approved Core runtime is installed separately under
`%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\`. The current build specification never
embeds Core or V2Ray:

```powershell
python -m PyInstaller --clean --noconfirm NekoLauncher.spec
```

The output is `dist/NekoLauncher.exe`. Its PyInstaller archive must contain zero
`NekoProxyCore` and `v2ray-sn` entries. The publishable client configuration is
embedded and extractable by design; never embed a secret/service-role key.

See [`../docs/current/build-windows-executable.md`](../docs/current/build-windows-executable.md)
and [`../docs/README.md`](../docs/README.md) for the maintained build procedure
and documentation status.
