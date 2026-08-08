# Documentation index

Last reviewed: **8 August 2026**

This is the canonical index for repository documentation. Documentation is
organized by lifecycle so that active instructions are not mixed with blocked
plans or historical evidence.

## Directory rules

- `current/` — maintained architecture, build, layout, and operating guidance.
- `blocked/` — active proposals or handoffs that must not be treated as
  production approval.
- `archive/` — superseded or dated evidence retained only for traceability.
- Component documentation stays beside its component, such as `launcher/` and
  `supabase/`.
- File names use lowercase kebab-case, except conventional `README.md` files.

## Start here

| Document | Status | Purpose |
| --- | --- | --- |
| [`../README.md`](../README.md) | Current | Project overview and current production state |
| [`../launcher/README.md`](../launcher/README.md) | Current | Launcher setup, behavior, and validation |
| [`current/launcher-architecture.md`](current/launcher-architecture.md) | Current; validation pending | Launcher architecture after the maintainability refactor |
| [`current/build-windows-executable.md`](current/build-windows-executable.md) | Current | Build and smoke-test `NekoLauncher.exe` |
| [`current/repository-layout.md`](current/repository-layout.md) | Current | Tracked source, local inputs, and generated output |
| [`current/runtime-distribution.md`](current/runtime-distribution.md) | Current policy | Controlled NekoProxyCore runtime delivery policy |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Current | Contribution and local validation rules |

## Component documentation

| Document | Status | Purpose |
| --- | --- | --- |
| [`../supabase/README.md`](../supabase/README.md) | Current | Database architecture and migration status |
| [`../supabase/coupon-workflow.md`](../supabase/coupon-workflow.md) | Current | Coupon roles, flows, and security behavior |
| [`../supabase/security-test-plan.md`](../supabase/security-test-plan.md) | Current | Disposable-environment security and concurrency checks |
| [`../supabase/blocked_migrations/README.md`](../supabase/blocked_migrations/README.md) | Current warning | Files that must never enter the active migration path |
| [`../supabase/functions/issue_launch_permit/README.md`](../supabase/functions/issue_launch_permit/README.md) | Experimental; production-blocked | Prototype Edge Function notes and explicit security limitations |

## Production-blocked authorization work

These documents are still useful for design and implementation work, but none
of them authorizes production Core startup.

| Document | Status | Purpose |
| --- | --- | --- |
| [`blocked/neko-auth-s0-production-handoff.md`](blocked/neko-auth-s0-production-handoff.md) | Blocked | Central `NEKO-AUTH-S0` baseline and release gates |
| [`blocked/launcher-production-adapters.md`](blocked/launcher-production-adapters.md) | Blocked | Launcher responsibilities pinned to the S0 baseline |
| [`blocked/launcher-minimal-launch-authorization-plan.md`](blocked/launcher-minimal-launch-authorization-plan.md) | Draft; approval required | Reduced-scope Launcher execution plan |
| [`blocked/core-minimal-launch-authorization-plan.md`](blocked/core-minimal-launch-authorization-plan.md) | Draft; approval required | Matching NekoProxyCore execution plan |

## Historical and unused material

Files under [`archive/`](archive/) are not current instructions. The archive
index records why each file is retained and identifies its current replacement.

The accidental Windows process capture formerly stored as `tasks.csv` was
removed because it was neither project documentation nor a task list.

## Maintenance rules

1. Add every maintained document to this index.
2. Put active cross-component guidance in `current/`.
3. Put unapproved plans, release gates, and incomplete production handoffs in
   `blocked/`.
4. Move superseded or date-specific evidence to `archive/`; do not silently
   rewrite historical claims.
5. Give every blocked or archived document a status banner and a current
   replacement where one exists.
6. Do not describe a prototype as production-ready unless production
   composition, security review, and tests demonstrate it.
7. Never store secrets, tokens, customer identifiers, private keys, raw
   production configuration, or machine-specific absolute links in docs.
