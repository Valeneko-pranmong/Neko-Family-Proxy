You are working on this GitHub repository:

https://github.com/Valeneko-pranmong/Neko-Family-Proxy

Your task is to perform a maintainability-focused architectural refactor of the Python launcher.

IMPORTANT: This is a REFACTOR-ONLY task.

Do NOT intentionally change application behavior, business logic, security rules, authentication behavior, entitlement behavior, ProxyCore authorization behavior, UI appearance, UI layout, text displayed to users, startup behavior, game launching behavior, or Supabase behavior.

The primary goal is to make the codebase easier to understand, maintain, test, and extend.

--------------------------------------------------
1. FIRST: INSPECT THE CURRENT REPOSITORY
--------------------------------------------------

Before modifying anything:

1. Inspect the repository structure.
2. Read:
   - README.md
   - launcher/README.md
   - launcher/pyproject.toml
   - relevant documentation under docs/
   - launcher/src/neko_launcher/
   - launcher/tests/
3. Understand the existing architecture and dependency direction.

The launcher currently uses an architecture approximately divided into:

- application/
- domain/
- infrastructure/
- ui/
- main.py

Preserve this general architectural philosophy.

Do not redesign the entire system unnecessarily.

--------------------------------------------------
2. VERIFY THE DEVELOPMENT ENVIRONMENT
--------------------------------------------------

Before modifying source code, run:

gh --version
gh auth status
git status -sb
git branch --show-current
git remote -v
python --version

Also inspect the repository default branch.

If currently on main/master, create a dedicated branch:

agent/refactor-launcher-maintainability

Do NOT make this refactor directly on main.

Before editing, confirm the working tree does not contain unrelated user changes.

If unrelated changes exist, DO NOT overwrite or discard them.

--------------------------------------------------
3. CURRENT MAINTAINABILITY PROBLEMS
--------------------------------------------------

The main issue is not simply "too many files."

The repository has several responsibilities concentrated into large files and several flat namespaces.

The highest-priority issue is:

launcher/src/neko_launcher/ui/app_window.py

This file is currently very large and acts as a UI monolith.

It currently contains responsibilities such as:

- main application window
- DPI/window scaling
- native Windows title-bar styling
- rounded window handling
- window dragging
- minimize/close behavior
- system tray integration
- authentication view
- registration view
- launcher/dashboard view
- coupon-related UI
- toast notifications
- Tk variables/state binding
- background ThreadPoolExecutor handling
- event queue handling
- service callbacks
- game process polling
- proxy/game connection state presentation

These responsibilities should not remain concentrated in one class/file.

The second maintainability issue is:

launcher/src/neko_launcher/infrastructure/

This directory contains many unrelated infrastructure concerns at the same directory level, such as:

- authorized_proxy_gateway.py
- core_control_channel.py
- core_process.py
- game_process_manager.py
- process_detector.py
- process_manager.py
- installation.py
- secure_store.py
- supabase_gateway.py
- config.py
- event_bus.py

The directory should be organized by infrastructure concern.

The third issue is main.py.

main.py currently performs significant dependency construction and Windows-specific application startup responsibilities.

It should eventually become a thin application entry point.

--------------------------------------------------
4. REFACTOR PRINCIPLES
--------------------------------------------------

Follow these rules strictly:

1. Preserve observable behavior.

2. Prefer moving existing code over rewriting it.

3. Avoid changing algorithms unless required to support extraction.

4. Avoid changing public APIs unless necessary.

5. Keep backwards-compatible imports where practical.

6. Do not introduce unnecessary frameworks.

7. Do not introduce a dependency-injection framework.

8. Do not replace CustomTkinter.

9. Do not redesign the UI.

10. Do not change strings shown to users unless required to fix an existing bug.

11. Do not change Supabase schema or migrations.

12. Do not modify ProxyCore authorization/security behavior.

13. Production authorization must remain fail-closed unless the existing code explicitly allows otherwise.

14. Do not expose secrets, service-role keys, tokens, server credentials, or sensitive runtime configuration.

15. Do not weaken validation or authorization checks.

16. Do not remove tests merely because they are difficult to update.

17. Keep Windows-specific implementation isolated from general UI/application logic where possible.

18. Prefer composition over an excessive inheritance hierarchy.

19. Avoid creating dozens of tiny one-function files.

20. Optimize for maintainability, discoverability, and clear responsibility boundaries.

--------------------------------------------------
5. PHASE 1 — REFACTOR UI
--------------------------------------------------

This is the highest priority.

Refactor:

launcher/src/neko_launcher/ui/app_window.py

The intended structure should move toward something similar to:

neko_launcher/
└── ui/
    ├── app_window.py
    ├── theme.py
    │
    ├── views/
    │   ├── __init__.py
    │   ├── auth_view.py
    │   ├── dashboard_view.py
    │   └── ...
    │
    ├── components/
    │   ├── __init__.py
    │   ├── toast.py
    │   ├── inputs.py
    │   ├── buttons.py
    │   └── ...
    │
    └── platform/
        ├── __init__.py
        ├── window_scaling.py
        ├── window_chrome.py
        └── system_tray.py

This exact structure is not mandatory if the existing code suggests a cleaner division.

Use professional judgment.

However, the responsibilities must become clearly separated.

--------------------------------------------------
6. APPWINDOW RESPONSIBILITY AFTER REFACTOR
--------------------------------------------------

AppWindow should remain the top-level UI coordinator.

It should NOT contain detailed implementation for every widget and Windows platform feature.

Ideally AppWindow should primarily handle:

- root application window ownership
- top-level view composition
- switching between major views
- binding application state/events to UI
- lifecycle
- shutdown coordination
- coordination between UI components

Conceptually it should move toward something like:

class AppWindow:
    def __init__(...):
        self._configure_window()
        self._build_views()
        self._bind_events()

    def show_auth(self):
        ...

    def show_dashboard(self):
        ...

    def close(self):
        ...

Do not force this exact code if it would make the implementation worse.

--------------------------------------------------
7. UI VIEW EXTRACTION
--------------------------------------------------

Identify large logical UI sections.

Examples include:

- login
- registration
- authenticated dashboard/program view
- entitlement/status
- coupon redemption
- game path selection
- connection/system status

Extract major UI sections into dedicated view classes or focused builders.

A view should own the widgets belonging to that logical screen/section.

Avoid passing AppWindow itself everywhere.

Prefer explicit callbacks or small interfaces.

Example:

AuthView(
    parent=...,
    on_login=...,
    on_register=...,
    on_forgot_password=...,
)

instead of:

AuthView(app_window=self)

when practical.

--------------------------------------------------
8. UI COMPONENT EXTRACTION
--------------------------------------------------

Extract reusable visual components if they have meaningful responsibility.

Potential candidates:

- ToastNotification
- status badge
- reusable card
- icon entry
- primary/secondary buttons
- common labeled field

Do NOT create components just to reduce line count.

A component should exist because it represents a reusable or independently understandable concept.

--------------------------------------------------
9. WINDOWS PLATFORM EXTRACTION
--------------------------------------------------

Move Windows-specific window manipulation out of AppWindow where practical.

Examples:

- ctypes title-bar manipulation
- DWM attributes
- rounded region handling
- window scaling calculations
- system tray management

Suggested location:

ui/platform/

Potential responsibilities:

window_chrome.py
- native title bar
- DWM styling
- rounded corners
- window dragging/native behavior where appropriate

window_scaling.py
- DPI-aware size calculations
- fixed portrait sizing
- centering calculations

system_tray.py
- pystray integration
- tray lifecycle
- thread-safe action queue

Do not break Tkinter's main-thread requirement.

All Tk operations must continue to execute on the Tk main thread.

--------------------------------------------------
10. THREADING REQUIREMENTS
--------------------------------------------------

The current launcher uses background execution and UI callbacks.

Preserve thread safety.

Do NOT access Tk widgets directly from worker threads.

Continue using Tk's event loop / root.after / queue mechanisms where appropriate.

Do not create additional background threads unnecessarily.

Ensure system tray callbacks cannot perform unsafe Tk work directly from the tray thread.

--------------------------------------------------
11. PHASE 2 — ORGANIZE INFRASTRUCTURE
--------------------------------------------------

After UI refactoring is stable, reorganize infrastructure.

Current flat structure should move approximately toward:

infrastructure/
├── auth/
│   ├── __init__.py
│   └── supabase_gateway.py
│
├── core/
│   ├── __init__.py
│   ├── authorized_proxy_gateway.py
│   ├── core_control_channel.py
│   └── core_process.py
│
├── process/
│   ├── __init__.py
│   ├── game_process_manager.py
│   ├── process_detector.py
│   └── process_manager.py
│
├── storage/
│   ├── __init__.py
│   ├── secure_store.py
│   └── installation.py
│
├── config.py
├── defaults.py
└── event_bus.py

Again, this is a suggested target.

Use actual dependency relationships to determine the final organization.

Do NOT create nesting merely for aesthetic reasons.

--------------------------------------------------
12. UPDATE IMPORTS SAFELY
--------------------------------------------------

After moving infrastructure files:

- update all production imports
- update test imports
- update PyInstaller-related hidden imports if necessary
- inspect NekoLauncher.spec
- inspect packaging configuration
- make sure packaged builds can still find modules

Search the entire repository for old module paths.

There must be no stale imports remaining.

--------------------------------------------------
13. PHASE 3 — THIN MAIN.PY
--------------------------------------------------

Refactor application startup so main.py becomes easier to understand.

Consider introducing:

neko_launcher/
└── bootstrap/
    ├── __init__.py
    ├── app_factory.py
    └── single_instance.py

Possible responsibilities:

app_factory.py
- construct configuration
- construct EventBus
- construct secure storage
- construct Supabase gateway
- construct process/core adapters
- construct ApplicationController
- construct LauncherService
- construct AppWindow

single_instance.py
- Windows named mutex
- duplicate-launch detection

main.py should ideally be close to:

def main() -> None:
    app = create_application()
    app.run()

However, preserve existing startup error handling and PyInstaller behavior.

Do not simplify startup code if doing so changes semantics.

--------------------------------------------------
14. IMPORTANT: REVIEW BUILD_WINDOW
--------------------------------------------------

The current build_window() dependency assembly should be reviewed carefully.

There may be a dependency ordering issue involving controller usage inside closures before controller is assigned.

Do NOT blindly rewrite this.

Analyze whether it is actually safe due to Python closure late binding.

If safe, preserve behavior while improving readability.

If unsafe, fix it and add a regression test.

Document the reasoning in the PR.

--------------------------------------------------
15. APPLICATION LAYER
--------------------------------------------------

Inspect:

application/authorized_core.py
application/controller.py
application/services.py

These files are moderately large.

Do not automatically split them.

First inspect responsibility boundaries.

Only split them if:

- a file clearly contains multiple independent use cases
- the split improves dependency clarity
- testing becomes simpler
- names remain meaningful

Avoid premature fragmentation.

Potential future grouping could include:

application/auth/
application/entitlement/
application/launch/
application/core/

but only implement this if it clearly improves the current code.

UI refactoring is more important.

--------------------------------------------------
16. DOMAIN LAYER
--------------------------------------------------

Be conservative with domain/.

Do not reorganize domain objects simply for consistency with infrastructure.

The domain layer should remain stable unless there is a clear architectural reason to change it.

--------------------------------------------------
17. TESTS
--------------------------------------------------

Tests are critical.

Existing tests include coverage for areas such as:

- AppWindow
- Authorized Core
- Config
- Controller
- EventBus
- GameProcessManager
- Installation
- LaunchPermitGateway
- Main
- ProcessDetector
- ProcessManager
- integration tests

Preserve and update them.

Where refactoring introduces extracted classes, add focused unit tests if useful.

Do NOT heavily mock implementation details.

Prefer testing behavior and public interfaces.

--------------------------------------------------
18. VALIDATION AFTER EACH PHASE
--------------------------------------------------

Do not perform the entire refactor and only test at the end.

Use incremental validation.

After each meaningful extraction:

Run:

python -m ruff check src tests

and:

python -m pytest -q -m "not integration"

Also run:

python scripts/check_repository_safety.py

from the repository root where applicable.

If dependencies are not installed:

cd launcher
python -m pip install -e ".[dev,release]"

Then rerun tests.

--------------------------------------------------
19. TEST WINDOWS-SPECIFIC CODE CAREFULLY
--------------------------------------------------

The execution environment may not be Windows.

Do not remove Windows behavior simply because Linux CI cannot exercise it.

Windows-only code should remain guarded by:

sys.platform == "win32"

or equivalent existing guards.

Where possible, unit test pure calculations separately from Windows API calls.

Do not execute unsafe ctypes Windows APIs on non-Windows environments.

--------------------------------------------------
20. PYINSTALLER VALIDATION
--------------------------------------------------

Inspect:

launcher/NekoLauncher.spec

After module moves, verify that packaging still includes required modules and assets.

If running on Windows and build dependencies are available, run:

cd launcher
python -m PyInstaller --clean --noconfirm NekoLauncher.spec

Verify expected output:

launcher/dist/NekoLauncher.exe

Do not claim a successful Windows build if the environment cannot actually perform it.

If unavailable, explicitly document that limitation.

--------------------------------------------------
21. CODE QUALITY TARGETS
--------------------------------------------------

These are guidelines, NOT strict line-count rules.

Prefer approximately:

- reusable UI component: 50–250 lines
- individual view: 150–500 lines
- service: 150–400 lines
- adapter: 100–350 lines

Files above ~800–1000 lines should trigger a responsibility review.

Do not artificially split cohesive files to satisfy a number.

The goal is cohesion, not arbitrary file size.

--------------------------------------------------
22. NAMING
--------------------------------------------------

Use names that explain responsibility.

Avoid generic names like:

helpers.py
utils.py
common.py
misc.py

unless the contents are genuinely cohesive.

Prefer:

window_scaling.py
system_tray.py
toast.py
auth_view.py
dashboard_view.py
app_factory.py

--------------------------------------------------
23. CIRCULAR IMPORTS
--------------------------------------------------

Pay close attention to circular imports.

Desired dependency direction should remain broadly:

domain
↑
application
↑
infrastructure / UI composition

UI and infrastructure may implement application ports/adapters.

Do not make domain import UI or infrastructure.

Do not make application depend directly on concrete UI classes.

--------------------------------------------------
24. SECURITY / PROXYCORE CONSTRAINTS
--------------------------------------------------

This repository contains authorization and ProxyCore integration code.

Do not weaken or bypass authorization controls during refactoring.

Specifically:

- production fail-closed behavior must remain intact
- CURRENT_PRODUCTION_AUTHORIZATION behavior must remain intact
- access-context checks must remain intact
- entitlement checks must remain intact
- session validation must remain intact
- installation identity behavior must remain intact
- launch permits must remain intact
- authenticated transport requirements must remain intact

This refactor is not authorization work.

Do not change these flows except where module moves require import updates.

--------------------------------------------------
25. SUPABASE CONSTRAINTS
--------------------------------------------------

Do not put service-role secrets into the desktop launcher.

The desktop launcher must continue using only client-safe/publishable configuration.

Do not modify Supabase database migrations as part of this refactor unless absolutely necessary.

It should not be necessary.

--------------------------------------------------
26. DOCUMENTATION
--------------------------------------------------

After finishing the refactor:

Update documentation only where paths or architecture descriptions are now outdated.

At minimum inspect:

README.md
launcher/README.md
docs/repository-layout.md

Do not rewrite unrelated documentation.

Add a concise explanation of the new launcher module organization.

--------------------------------------------------
27. GIT WORKFLOW
--------------------------------------------------

Work on:

agent/refactor-launcher-maintainability

Use logical commits.

Prefer several understandable commits rather than one enormous commit.

Example:

1. refactor UI platform helpers
2. extract launcher UI views
3. organize infrastructure modules
4. extract bootstrap wiring
5. update tests and architecture docs

Before committing each phase:

git status
git diff --check

Run relevant tests.

Do not include unrelated files.

--------------------------------------------------
28. FINAL FULL VALIDATION
--------------------------------------------------

Before creating the PR, run:

python scripts/check_repository_safety.py

cd launcher

python -m ruff check src tests

python -m pytest -q -m "not integration"

If integration prerequisites are available, run relevant integration tests.

If on Windows and practical:

python -m PyInstaller --clean --noconfirm NekoLauncher.spec

Also run:

git diff --check

Search for stale imports and obsolete paths.

--------------------------------------------------
29. REVIEW THE FINAL DIFF
--------------------------------------------------

Before publishing:

Review:

git diff main...HEAD --stat

and the full diff.

Specifically check for accidental changes to:

- Thai UI text
- colors
- spacing
- dimensions
- authentication flow
- Supabase requests
- entitlement logic
- ProxyCore startup logic
- process detection
- executable paths
- startup timing
- ThreadPoolExecutor behavior
- Tk root.after timing
- shutdown behavior

Any such change must be justified.

Prefer reverting accidental behavioral changes.

--------------------------------------------------
30. CREATE A DRAFT PULL REQUEST
--------------------------------------------------

After all validation succeeds:

Push the branch.

Create a DRAFT pull request targeting main.

Suggested title:

Refactor launcher architecture for maintainability

The PR description should clearly contain:

## Summary

Explain that this is a structural refactor intended to improve maintainability without intentionally changing application behavior.

## Changes

Describe:

- UI decomposition
- platform helper extraction
- infrastructure grouping
- bootstrap extraction
- import updates
- test updates
- documentation updates

## Behavior

Explicitly state:

"No intentional user-facing or business-logic behavior changes."

## Validation

List exactly what was actually run.

Example:

- repository safety check
- ruff
- pytest non-integration suite
- PyInstaller build if performed

Do not claim checks that were not actually run.

## Risks

Mention:

- Windows-native UI/window behavior
- PyInstaller module discovery
- module path changes

and explain what tests/checks mitigate them.

--------------------------------------------------
31. ACCEPTANCE CRITERIA
--------------------------------------------------

The task is complete only when all of the following are true:

[ ] app_window.py is substantially smaller and focused on top-level coordination.

[ ] Major UI sections are separated into understandable modules.

[ ] Windows-specific UI platform code is isolated where practical.

[ ] Infrastructure modules are organized by responsibility.

[ ] main.py is significantly easier to read.

[ ] There are no unnecessary circular dependencies.

[ ] Existing behavior is preserved.

[ ] Existing UI appearance is intentionally preserved.

[ ] Supabase behavior is preserved.

[ ] ProxyCore authorization behavior is preserved.

[ ] Production fail-closed behavior is preserved.

[ ] Existing tests pass or failures are clearly explained.

[ ] Ruff passes.

[ ] Repository safety check passes.

[ ] PyInstaller configuration has been reviewed for moved modules.

[ ] Documentation reflects the new architecture.

[ ] No unrelated code is changed.

[ ] No credentials or secrets are introduced.

--------------------------------------------------
32. IMPORTANT WORKING STYLE
--------------------------------------------------

Do not perform a massive blind rewrite.

Work incrementally.

For each major phase:

1. inspect
2. identify responsibility boundaries
3. move/extract code
4. update imports
5. update tests
6. run validation
7. inspect diff
8. continue

When uncertain, preserve existing behavior rather than redesigning it.

The main objective is:

"Make the repository easier to maintain while keeping the launcher working exactly as it does now."

Start by inspecting the repository and report the current architecture and proposed refactoring plan before making the first code change. Then proceed with the implementation.