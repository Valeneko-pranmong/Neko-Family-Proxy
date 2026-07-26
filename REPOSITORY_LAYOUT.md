# Repository layout

## Tracked source

- `launcher/` — launcher source, tests, and one-file build specification.
- `supabase/` — schema migrations and operational documentation.
- `.github/workflows/` — CI and manual Supabase integration checks.
- `scripts/` — repository validation.
- Root assets and documentation.

## Local-only inputs and generated files

- `ProxyCore/` — approved runtime input for self-contained builds.
- `launcher/.env.local` — local publishable client configuration.
- `launcher/build/` — temporary PyInstaller output.
- `launcher/dist/` — generated deliverables.
- Python, Ruff, and pytest caches.

The customer deliverable is the one-file `launcher/dist/NekoLauncher.exe`.
