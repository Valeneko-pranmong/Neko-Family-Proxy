# Neko Family Launcher Documentation Index

Last reviewed: **28 August 2026** (Post-Beta Dashboard Redesign plan added)

This is the canonical index for repository documentation. Documentation is organized by lifecycle so that active instructions are not mixed with historical evidence or superseded plans.

## Directory Structure Rules

- `current/` — Maintained contracts, operational guides, and active release blockers.
- `archive/` — Historical milestone evidence, superseded AI prompts, and completed test records.
- Component documentation stays beside its component (`launcher/`, `supabase/`, `agent/`).

---

## Active Documentation (`docs/current/`)

| Document | Classification | Purpose |
| :--- | :--- | :--- |
| **[`current/README.md`](current/README.md)** | `CURRENT_STATUS` | Component status, branch authority, and start here guide |
| **[`current/launcher-architecture.md`](current/launcher-architecture.md)** | `CURRENT_CONTRACT` | Launcher desktop layered architecture, IPC, and controllers |
| **[`current/neko-auth-lite.md`](current/neko-auth-lite.md)** | `CURRENT_CONTRACT` | NEKO-AUTH-LITE authentication, challenge-response, and permit flow |
| **[`current/final-windows-e2e-harness.md`](current/final-windows-e2e-harness.md)** | `CURRENT_CONTRACT` | Windows E2E integration test harness and binary admission gates |
| **[`current/phase-2-5-distinct-auth-session-future-permit-proof.md`](current/phase-2-5-distinct-auth-session-future-permit-proof.md)** | `CURRENT_RELEASE_BLOCKER` | Prepared distinct Auth-session future permit proof (Unresolved client gate) |
| **[`current/build-windows-executable.md`](current/build-windows-executable.md)** | `CURRENT_OPERATIONAL` | PyInstaller standalone packaging and secret-hygiene build instructions |
| **[`current/debug-console.md`](current/debug-console.md)** | `CURRENT_OPERATIONAL` | Windows debug console, runtime logging, and IPC troubleshooting |
| **[`current/repository-layout.md`](current/repository-layout.md)** | `CURRENT_OPERATIONAL` | Tracked source, local inputs, and component layout |
| **[`current/runtime-distribution.md`](current/runtime-distribution.md)** | `CURRENT_OPERATIONAL` | Controlled Core runtime delivery and packaging policy |
| **[`current/dashboard-redesign-plan.md`](current/dashboard-redesign-plan.md)** | `CURRENT_PLAN` | Dashboard UI redesign plan (6 phases) targeting v5.0.0a10+ post-beta |
| **[`Tool.md`](Tool.md)** | `CURRENT_OPERATIONAL` | Developer tool installation and Windows environment checklist |

---

## Component Documentation

| Document | Purpose |
| :--- | :--- |
| **[`../launcher/README.md`](../launcher/README.md)** | Launcher Python setup, Qt environment, and pytest execution |
| **[`../supabase/README.md`](../supabase/README.md)** | Supabase database schema, migrations, and RPCs |
| **[`../supabase/coupon-workflow.md`](../supabase/coupon-workflow.md)** | Coupon roles, redemption flows, and security behavior |
| **[`../supabase/security-test-plan.md`](../supabase/security-test-plan.md)** | Database RLS, privilege separation, and concurrency tests |

---

## Historical Archive (`docs/archive/`)

| Archive Topic | Path | Contents |
| :--- | :--- | :--- |
| **Telemetry** | [`archive/telemetry/`](archive/telemetry/) | [`launcher-telemetry-consumer-handoff.md`](archive/telemetry/launcher-telemetry-consumer-handoff.md) |
| **Prompts** | [`archive/prompts/`](archive/prompts/) | Historical AI implementation prompts for single active session policy |
| **Phase 2.5** | [`archive/phase-2-5/`](archive/phase-2-5/) | Closed Phase 2.5 migration reconciliation, parity data, and deployment plan |
| **Historical Blocked** | [`archive/blocked/`](archive/blocked/) | Historical S0 / Phase 2 blocked proposals and reports |
| **Scratch / Notes** | [`archive/scratch/`](archive/scratch/) | Historical forensic scratch notes |
| **Historical S0** | [`archive/`](archive/) | S0 connectors, contract proposals, and changelogs |
