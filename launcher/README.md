# Neko Family Launcher

Desktop launcher for Supabase username/password membership, entitlement checks,
launcher-session control, and user-selected PSO2 Tweaker configuration.

> **Current status (8 August 2026):** production Core startup is intentionally
> fail closed through `AuthorizationPendingProxyGateway`. The S0 authorization
> contract is not fully accepted or released, so the current production
> composition does not start NekoProxyCore or Tweaker.

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
7. Request startup. The current fail-closed gateway rejects the request until
   the production authorization adapters and Core contract pass all release
   gates.

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

An approved `../ProxyCore/` directory may be present as a controlled local build
input. The current build specification embeds the directory when it exists:

```powershell
python -m PyInstaller --clean --noconfirm NekoLauncher.spec
```

The output is `dist/NekoLauncher.exe`. If `../ProxyCore/` exists, its contents
are embedded; that does not enable production startup or constitute release
approval. The publishable client configuration is embedded and extractable by
design; never embed a secret/service-role key.

See [`../docs/current/build-windows-executable.md`](../docs/current/build-windows-executable.md)
and [`../docs/README.md`](../docs/README.md) for the maintained build procedure
and documentation status.
