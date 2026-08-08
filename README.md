# Neko Family Proxy

Windows launcher for PSO2 NGS JP with Supabase authentication, coupon-based
entitlements, launcher-session control, and a planned authorized NekoProxyCore
integration.

> **Current status (8 August 2026):** authentication, entitlement, coupon, and
> launcher-session flows are implemented. Production Core startup remains
> **fail closed** through `AuthorizationPendingProxyGateway` until the
> `NEKO-AUTH-S0` acceptance and release gates are complete. The current source
> does not start ProxyCore in production.

## Documentation

Start at [`docs/README.md`](docs/README.md). It classifies documents as current,
blocked, historical, or removed and links to the maintained source of truth.

Common entry points:

- [Launcher development](launcher/README.md)
- [Launcher architecture](docs/current/launcher-architecture.md)
- [Windows executable build](docs/current/build-windows-executable.md)
- [Repository layout](docs/current/repository-layout.md)
- [Runtime distribution policy](docs/current/runtime-distribution.md)
- [Blocked NEKO-AUTH-S0 handoff](docs/blocked/neko-auth-s0-production-handoff.md)
- [Blocked Launcher production adapters](docs/blocked/launcher-production-adapters.md)
- [Supabase database](supabase/README.md)

## Repository structure

- `launcher/` — Python desktop launcher, tests, and PyInstaller specification.
- `supabase/` — database migrations and operational documentation.
- `docs/current/` — maintained cross-component documentation.
- `docs/blocked/` — active plans and handoffs without production approval.
- `docs/archive/` — superseded or dated evidence retained for traceability.
- `ProxyCore/` — optional, approved local build input; excluded from Git.
- `scripts/` — repository validation tools.
- Root assets — launcher icon, image, and Sarabun fonts.

## Development

```powershell
Set-Location launcher
python -m pip install -e ".[dev,release]"
python -m neko_launcher.main
```

Only the Supabase URL and publishable client key belong in the desktop client.
Never put a secret/service-role key in the launcher.

## Validation

```powershell
python scripts/check_repository_safety.py
Set-Location launcher
python -m ruff check src tests
python -m pytest -q -m "not integration"
```

## Build

```powershell
Set-Location launcher
python -m PyInstaller --clean --noconfirm NekoLauncher.spec
```

The output is `launcher/dist/NekoLauncher.exe`. Building an executable does not
constitute production approval; see the [build guide](docs/current/build-windows-executable.md)
and the current S0 release gates before distribution.
