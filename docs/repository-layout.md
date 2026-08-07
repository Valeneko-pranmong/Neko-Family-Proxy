# Repository layout

**Status:** Current — reviewed 7 August 2026.

## Tracked source

- `launcher/` — launcher source, tests, and one-file build specification.
  - `application/` — business logic, services, and ports.
  - `domain/` — core models and events.
  - `infrastructure/` — external integrations, grouped by `auth`, `core`, `process`, and `storage`.
  - `ui/` — views, components, and platform-specific window handling.
  - `bootstrap/` — dependency assembly and application startup.
- `supabase/` — schema migrations and operational documentation.
- `.github/workflows/` — CI and manual Supabase integration checks.
- `scripts/` — repository validation.
- `docs/` — maintained documentation and historical records under
  `docs/archive/`.
- Root assets, project overview, and contribution guide.

## Local-only inputs and generated files

- `ProxyCore/` — optional approved runtime input for controlled builds.
- `launcher/.env.local` — local publishable client configuration.
- `launcher/build/` — temporary PyInstaller output.
- `launcher/dist/` — generated deliverables.
- Python, Ruff, and pytest caches.

The generated executable is `launcher/dist/NekoLauncher.exe`. It is not a
customer release until the current S0 acceptance, security, and release gates
also pass.
