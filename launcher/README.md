# Neko Family Launcher

Desktop launcher for Supabase-backed membership, entitlement checks,
launcher-session control, and user-selected PSO2 Tweaker configuration. The
legacy 5.1.6 line uses username/password login; the 5.2.0 target is Discord web
auth only.

> **Current status (25 October 2026, v5.2.0 planning):** the accepted
> NEKO-AUTH-LITE production composition is active on 5.1.6. Core startup
> remains fail-closed unless Auth, the current Launcher session, ACTIVE
> entitlement, exact PSO2 identity, fresh challenge/permit, and typed RUNNING
> checks all succeed. 5.1.6 remains public stable and usable on its legacy
> backend. 5.2.0 is a separate web-auth preview; it must not auto-update 5.1.6,
> must not be installed over or alongside it, and requires a full 5.1.6
> uninstall first. 5.3.0 is the planned cutover.

## Web auth (development)

The Discord browser flow is hidden by default and requires both variables:

```text
NEKO_WEB_AUTH_ENABLED=1
NEKO_AUTH_BRIDGE_URL=https://<proxy-backend>/auth/launcher/exchange
```

The exact loopback callback is `http://127.0.0.1:53682/auth/callback`. The
5.1.6 legacy line keeps password login; the 5.2.0 release target removes
password/recovery and uses web auth only. Do not enable or publish 5.2.0 until
the proxy bridge, identity mapping, link/claim flow, installer separation, and
staging E2E are complete. See `../docs/current/web-auth-launcher.md` and the
[separation plan](../docs/superpowers/plans/2026-10-25-web-auth-separation-and-5-3-0-cutover.md).

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
