# Documentation index

Last reviewed: **4 August 2026**

This index is the entry point for repository documentation. File names use
lowercase kebab-case, except conventional `README.md` files and license files.

## Status definitions

- **Current** — describes the source tree or an active operating procedure.
- **Blocked** — current design/handoff, but not approved for production use.
- **Historical** — retained for traceability; do not use as current instructions.
- **Removed** — generated, duplicated, or misleading material deleted from Git.

## Current

| Document | Purpose |
| --- | --- |
| [`../README.md`](../README.md) | Project overview and current system status |
| [`../launcher/README.md`](../launcher/README.md) | Launcher setup, behavior, and validation |
| [`build-windows-executable.md`](build-windows-executable.md) | Build and smoke-test the Windows executable |
| [`repository-layout.md`](repository-layout.md) | Tracked source, local inputs, and generated output |
| [`runtime-distribution.md`](runtime-distribution.md) | Controlled NekoProxyCore delivery policy |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Local checks and contribution safety rules |
| [`../supabase/README.md`](../supabase/README.md) | Database architecture and migration status |
| [`../supabase/coupon-workflow.md`](../supabase/coupon-workflow.md) | Coupon roles, flows, and security behavior |
| [`../supabase/security-test-plan.md`](../supabase/security-test-plan.md) | Supabase security and concurrency test plan |

## Current but production-blocked

| Document | Status |
| --- | --- |
| [`neko-auth-s0-production-handoff.md`](neko-auth-s0-production-handoff.md) | Central `NEKO-AUTH-S0` technical baseline; owner acceptance and release gates remain pending |
| [`launcher-production-adapters.md`](launcher-production-adapters.md) | Launcher implementation specification pinned to the same baseline; production composition must remain fail closed |

The central handoff is the repository-level overview. The Launcher adapter
document narrows that contract to Launcher responsibilities. If either conflicts
with the external signed contract package, the package is authoritative and
production wiring must stop.

## Historical records

Files under [`archive/`](archive/) preserve dated release evidence, superseded
proposals, and pre-baseline handoffs. They are not implementation instructions.
See [`archive/README.md`](archive/README.md) for the classification and replacement
for each file.

## Removed

- `tasks.txt` — an accidental UTF-16 Windows process-list capture, not a project
  task list or documentation file.

## Maintenance rules

1. Update this index whenever a document is added, archived, renamed, or removed.
2. Put active procedures in `docs/` or the relevant component directory.
3. Put superseded or date-specific evidence in `docs/archive/` and add a
   historical-status banner.
4. Do not create file names with spaces; use lowercase kebab-case.
5. Do not describe a design as implemented unless the production composition
   and tests demonstrate it.
6. Keep secrets, tokens, customer identifiers, private keys, and raw production
   configuration out of documentation.
