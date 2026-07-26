# Neko Family Proxy

Windows launcher for PSO2 NGS JP with Supabase membership, coupon-based
entitlements, an embedded ProxyCore runtime, and user-selected `Tweaker.exe`
launching.

## Repository structure

- `launcher/` — Python desktop launcher, tests, and PyInstaller specification.
- `supabase/` — Database migrations and security documentation.
- `ProxyCore/` — Local approved runtime used only for self-contained builds;
  excluded from Git.
- `icon_app.ico` and `image_11.png` — Launcher assets.
- `scripts/` — Repository safety validation.

## Development

```powershell
Set-Location launcher
python -m pip install -e ".[dev,release]"
Copy-Item .env.example .env.local
python -m neko_launcher.main
```

Use only the Supabase publishable key in `.env.local`. Never use a secret or
service-role key in the desktop application.

## Validation

```powershell
python scripts/check_repository_safety.py
Set-Location launcher
python -m ruff check src tests
python -m pytest -q -m "not integration"
```

## One-file build

Place the approved `ProxyCore/` directory at the repository root and configure
`launcher/.env.local`, then run:

```powershell
Set-Location launcher
python -m PyInstaller --clean --noconfirm NekoLauncher.spec
```

The deliverable is `launcher/dist/NekoLauncher.exe`. The build embeds
ProxyCore and the publishable client configuration. Users select their own
`Tweaker.exe` location after signing in.
