# Repository layout

**Status:** Current — reviewed 8 August 2026.

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
- `docs/current/` — maintained cross-component documentation.
- `docs/blocked/` — active plans and handoffs without production approval.
- `docs/archive/` — superseded and dated evidence retained for traceability.
- Root assets, project overview, and contribution guide.

## Local-only inputs and generated files

- `ProxyCore/` — local stale input only; never packaged into Launcher EXE.
- `launcher/.env.local` — local publishable client configuration.
- `launcher/build/` — temporary PyInstaller output.
- `launcher/dist/` — generated deliverables.
- Python, Ruff, and pytest caches.

The generated executable is `launcher/dist/NekoLauncher.exe`. It is not a
customer release until the current S0 acceptance, security, and release gates
also pass.
