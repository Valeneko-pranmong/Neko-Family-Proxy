# Contributing

## Repository layout

- `launcher/` - Launcher V2 source and tests.
- `admin-web/` - Admin dashboard source, tracked as a normal folder in this repository.
- `supabase/` - Database migrations and coupon/session documentation.
- `original-code/v1/` - Read-only archive of the first launcher release.
- `ProxyCore/` - Local runtime binary bundle. It is intentionally excluded from this repository.

## Local setup

### Launcher

```powershell
Set-Location launcher
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env.local
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q -m "not integration"
```

Do not put service-role keys, private keys, or customer data in `.env.local`.

### Admin web

Use the package manager and scripts documented in `admin-web/README.md`. Keep
`admin-web/.env` local; only `.env.example` belongs in source control.

## Before committing

- Run the launcher syntax and unit checks.
- Run the admin-web test/lint scripts.
- Run `python scripts/check_repository_safety.py` from the repository root.
- Check `git diff --check`.
- Confirm no `.env`, token, private key, build output, `node_modules`, or customer data is included.
- Do not commit `ProxyCore` binaries or archives. Distribute them separately
  only after the team confirms licensing and redistribution rights.

The former `admin-web` repository history is preserved locally in an ignored
Git bundle under `original-code/admin-web-history.bundle`; the working source
is now part of this repository.

Live Supabase integration tests run only with disposable accounts through the
manual `Supabase integration` workflow. Do not use customer accounts or reuse a
production coupon for this gate.
