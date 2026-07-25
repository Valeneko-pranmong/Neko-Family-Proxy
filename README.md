# Neko Family Proxy

Neko Family Proxy is being rebuilt as a shareable product for the Neko Family
team. The repository contains the launcher application, admin dashboard, and
Supabase database migrations for account, session, entitlement, and coupon
management.

The runtime proxy bundle is intentionally not part of this repository. It is
distributed through a separate, controlled channel and is supplied locally
when the launcher is run.

## Repository structure

- `launcher/` - Modular desktop launcher (Python) and tests.
- `admin-web/` - Admin dashboard, included as a normal folder in this repository.
- `supabase/` - Supabase migrations and coupon/session documentation.
- `original-code/v1/` - Read-only archive of the first launcher release.
- `icon_app.ico`, `image_11.png` - Shared application icon and pink-theme logo.

## Local development

### Launcher

```powershell
Set-Location launcher
Copy-Item .env.example .env.local
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = "src"
python -m neko_launcher.main
```

Set `NEKO_PROXY_CORE_PATH` in `launcher/.env.local` to the separately supplied
runtime executable when testing a real proxy connection. Never commit that
runtime, local environment files, or service-role credentials.

### Admin dashboard

See `admin-web/README.md` for the web development commands. Keep admin secrets
in local environment files; commit only the provided `.env.example` template.

### Database

The `supabase/` directory contains versioned migrations and documentation for
the Supabase project. Apply migrations through the team's approved Supabase
workflow and never place a service-role key in source control.

## Sharing with the team

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[REPOSITORY_LAYOUT.md](REPOSITORY_LAYOUT.md) for the source-control rules,
validation gates, and the list of files intentionally excluded from GitHub.
For the current implementation status and ordered handoff plan, see
[PROJECT_STATUS.md](PROJECT_STATUS.md).

Before the first public push, review the archived V1 code for any legacy
endpoints or deployment-specific values and rotate or remove them as needed.
