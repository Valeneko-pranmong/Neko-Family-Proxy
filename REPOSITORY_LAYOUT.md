# Repository sharing plan

The parent GitHub repository should contain source, migrations, tests, and
documentation. It should not contain generated builds, local environment files,
dependencies, or unapproved third-party binaries.

## Safe to track

- `launcher/`
- `supabase/`
- `original-code/v1/` (legacy archive; endpoint review required before public release)
- `admin-web/` (merged as a normal folder in this repository)
- `README.md`, `CONTRIBUTING.md`, assets, and configuration templates

## Keep out of normal Git history

- `build/`, `dist/`, `__pycache__/`
- `.env` and other local secret files
- `node_modules/`, `.next/`, generated output
- `ProxyCore/` and `ProxyCore.rar` (proprietary runtime bundle)
- `*.bundle` history backups (kept locally only)

## Pre-push gate

The first shared push should happen only after:

1. The old archived launcher endpoint is rotated or removed from the public
   distribution plan.
2. No real Supabase secret/service-role key is present.
3. The team agrees where the `ProxyCore` bundle is distributed separately from
   this repository.
