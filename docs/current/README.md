# Current documentation

Documents in this directory describe the maintained source tree or an active
operating procedure. Update them when behavior, layout, build steps, or runtime
policy changes.

See the canonical [`../README.md`](../README.md) index for document ownership,
status, and production-blocked work.

Operational guides:

- [`build-windows-executable.md`](build-windows-executable.md) — build and smoke-test the Launcher.
- [`debug-console.md`](debug-console.md) — watch Launcher/Core startup and diagnose failures.

Implementation handoffs:

- [`backend-single-active-session-ai-prompt.md`](backend-single-active-session-ai-prompt.md) — AI-ready Backend/Admin Web prompt for multiple remembered installations with one active session.
- [`launcher-single-active-session-ai-prompt.md`](launcher-single-active-session-ai-prompt.md) — AI-ready Desktop Launcher prompt for latest-login-wins handling, forced local sign-out, and stale-heartbeat safety.
