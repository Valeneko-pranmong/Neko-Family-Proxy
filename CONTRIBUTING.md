# Contributing

## Repository layout

- `launcher/` - Launcher V2 source and tests.
- `admin-web/` - Admin dashboard source, tracked as a normal folder in this repository.
- `supabase/` - Database migrations and coupon/session documentation.
- `v1` branch - Sanitized, read-only archive of the first launcher release.
- `ProxyCore/` - Local runtime binary bundle. It is intentionally excluded from this repository.

## Local setup

### Launcher

```powershell
Set-Location launcher
Copy-Item .env.example .env.local
$env:PYTHONPATH = "src"
python -m neko_launcher.main
```

Do not put service-role keys, private keys, or customer data in `.env.local`.

### Admin web

Use the package manager and scripts documented in `admin-web/README.md`. Keep
`admin-web/.env` local; only `.env.example` belongs in source control.

## Before committing

- Run the launcher syntax and unit checks.
- Run the admin-web test/lint scripts.
- Check `git diff --check`.
- Confirm no `.env`, token, private key, build output, `node_modules`, or customer data is included.
- Do not commit `ProxyCore` binaries or archives. Distribute them separately
  only after the team confirms licensing and redistribution rights.

The former `admin-web` repository history is preserved locally in an ignored
Git bundle under `original-code/admin-web-history.bundle`; the working source
is now part of this repository.
