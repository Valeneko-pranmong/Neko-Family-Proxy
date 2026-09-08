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
| **[`current/runtime-distribution.md`](current/runtime-distribution.md)** | `CURRENT_OPERATIONAL` | External Core runtime distribution policy (GitHub Releases architecture, public Core accepted) |
| **[`current/dashboard-redesign-plan.md`](current/dashboard-redesign-plan.md)** | `CURRENT_PLAN` | Dashboard UI redesign plan (6 phases) targeting v5.0.0a10+ post-beta |
| **[`Tool.md`](Tool.md)** | `CURRENT_OPERATIONAL` | Developer tool installation and Windows environment checklist |

---

## Software Update — GitHub Releases Architecture (Current)

Software Update operates under the Owner-approved GitHub-only architecture:
- **Current Architecture**: Fixed GitHub Releases only, latest published stable release discovery, signed `release-v2.json` authority, exact fixed product assets (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`), public Core accepted, no Supabase/Admin update fallback, and publish-last draft verification process.
- [Current specification](superpowers/specs/2026-09-08-software-update-github-releases-design.md) — Fixed GitHub Releases-only Software Update architecture design.
- [Current implementation plan](superpowers/plans/2026-09-08-software-update-github-releases-implementation.md) — 8-task implementation plan. Tasks 1–7 accepted C0/I0 (Task 7 canonical full Launcher suite 1673 passed / 35 skipped / 0 failed; optional disposable GitHub proof NOT RUN / ACCEPTABLE). Task 8 documentation migration completed; independent Astra medium review returned C0/I3; correction applied; RE-REVIEW PENDING. Release execution remains separately controlled.
- **Gates & Authority**: Gate #2 remains NOT PASSED until replacement GitHub package/release execution criteria are performed under separate authority. Gate #3 NOT PASSED.
- **Operational Discipline**: Active implementation and review routing is `cx/gpt-6-astra` with reasoning `medium` via Hermes. Gemini 3.8 Flash High and Sol High are PAUSED until Owner changes routing. ChatGPT PM writes no product code; Hermes is the sole repo/project mutation executor. Mandatory dedup check before every Hermes dispatch (`--oneshot` + registry + session history).
- **Scope Boundary**: Unrelated Supabase/Admin/account/recovery/proxy services remain untouched. Documentation does not claim production signing, tag creation, draft release, asset upload, publication, merge, push, deployment, live auto-update completion, Gate #2, or Gate #3.

### Historical and Superseded Update Plans

- [Phase-2 design](superpowers/specs/2026-09-05-software-update-phase-2-design.md) — **HISTORICAL / SUPERSEDED BY OWNER GITHUB-ONLY ARCHITECTURE DECISION, NOT PASS**. Signed update discovery prototype; does not install software.
- [Phase-3 transactional update architecture](superpowers/specs/2026-09-06-software-update-phase-3-design.md) — **HISTORICAL / SUPERSEDED BY OWNER GITHUB-ONLY ARCHITECTURE DECISION, NOT PASS**. Historical Supabase private Storage / Admin grant / capability / Vercel Software Update E3 requirements preserved as evidence.
- [Phase-3 independent review record](superpowers/specs/2026-09-06-software-update-phase-3-review.md) — historical architecture review record.
- [Phase-3 master implementation plan](superpowers/plans/2026-09-06-software-update-phase-3-master-plan.md) — **HISTORICAL / SUPERSEDED BY OWNER GITHUB-ONLY ARCHITECTURE DECISION, NOT PASS**.
- Phase-2 `5.1.0a2` remains historical packaged candidate evidence; this documentation checkpoint does not change product behavior or its version.

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
