# Neko Launcher Architecture Refactor

> **Status:** Implementation complete; final validation pending (7 August 2026).

## Purpose
Perform a maintainability-focused architectural refactor of the Python launcher, resolving a monolithic 1700-line UI script and an unorganized infrastructure layer.

## Previous Architecture
- Monolithic `main.py` entrypoint and dependency assembly.
- Monolithic `app_window.py` containing platform specifics, views, and orchestration.
- Flat `infrastructure/` directory with unclear module responsibilities.

## New Architecture
- **`bootstrap/`**: Application dependency assembly (`app_factory.py`) and single instance enforcement.
- **`ui/`**: Decomposed into `platform/` (window chrome, scaling, tray), `views/` (encapsulated UI state presentation), and `components/`. `app_window.py` is now a thin coordinator.
- **`infrastructure/`**: Logically grouped by external integrations:
  - `auth/`: Supabase integration.
  - `core/`: Authorized Core orchestrator and permits.
  - `process/`: Game and generic process management.
  - `storage/`: Local credential storage and installation identity.

## Major Decisions
- **Fail-Closed Authorization:** `unavailable_gateway.py` remains at the root of `infrastructure/` to strictly enforce fail-closed authorization behaviors.
- **View Encapsulation:** Views expose presentation methods (e.g. `set_actions_enabled()`) rather than leaking widget properties to `AppWindow`.
- **Scaling Extraction:** Scaling calculations are pure and adapters are tested without requiring a full GUI root.

## Behavior-Preservation Constraints
- **NO INTENTIONAL BEHAVIORAL CHANGES.**
- Fail-closed production authorization rules must remain untouched.
- Startup-error privacy (hiding raw exceptions) must be preserved.
- UI text, fonts, colors, layouts, DPI scaling, and dimensions must remain identical.

## Validation Performed
- Repository safety checks (baseline).
- Ruff linter passes with 0 violations.
- All non-integration tests pass.
- Verified Windows 100%, 125%, 150%, and short-notebook DPI scaling behavior.
- Manual UI regression validation (Pending).
- GitHub Actions CI / release workflows (Pending).

## Known Limitations
- The old architecture instructions were moved to `docs/archive/refactor-instructions.md` for historical preservation.
