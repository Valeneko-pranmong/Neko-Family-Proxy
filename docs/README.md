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
| **[`current/runtime-distribution.md`](current/runtime-distribution.md)** | `CURRENT_OPERATIONAL` | External Core runtime distribution policy (Two-Phase Staged-Draft GitHub Releases architecture, public Core accepted) |
| **[`current/dashboard-redesign-plan.md`](current/dashboard-redesign-plan.md)** | `CURRENT_PLAN` | Dashboard UI redesign plan (6 phases) targeting v5.0.0a10+ post-beta |
| **[`Tool.md`](Tool.md)** | `CURRENT_OPERATIONAL` | Developer tool installation and Windows environment checklist |

---

## Software Update — Two-Phase Staged-Draft Publication Architecture (Current)

Software Update operates under the Owner-approved Two-Phase Staged-Draft Publication Architecture:
- **Current Authoritative Architecture**: Software Update follows the two-phase staged-draft publication lifecycle:
  - **Phase 1 (Local Operator Environment)**: Candidate binaries (`NekoLauncher.exe`, `NekoUpdater.exe`) and Core bundle (`NekoProxyCore.zip`) are frozen in an isolated candidate staging directory, smoke-tested, freshly remeasured, and signed locally using the offline Ed25519 private key (`neko-update-prod-1`) to construct canonical `release-v2.json`. Following strict Gate #2 clearance, the operator pushes the Git tag (`v5.1.0a3`) and stages an unpublished draft release using `scripts/stage_draft_release.py` (`draft=true`, `prerelease=false`, `--clobber=false`), capturing the numeric `release_id` and four name-to-asset-ID bindings. Staging tooling never final-publishes, never signs, and never rebuilds.
  - **Phase 2 (Remote Publication Authority Gate)**: Final publication authority belongs exclusively to GitHub Actions (`.github/workflows/release.yml`). Direct local workstation publication is strictly prohibited. Publication is triggered via `workflow_dispatch` with exact inputs: `publish_release=true`, `release_id=<NUMERIC_ID>`, `release_tag=v5.1.0a3`, `expected_target=<40_CHAR_SHA>`. The workflow downloads staged assets by numeric `asset_id` as raw binary streams, enforces in-repo key binding `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`, validates cryptographic signatures and first-release invariants via `scripts/verify_github_release_assets.py`, executes a pre-publish TOCTOU lock on draft state and asset ID bindings, publishes via `PATCH /releases/:release_id` (`draft=false`), and validates public discovery on `/releases/latest`.
- [Current specification](superpowers/specs/2026-09-09-software-update-two-phase-staged-draft-design.md) — Two-Phase Staged-Draft Publication Architecture design specification.
- [Current implementation plan](superpowers/plans/2026-09-09-software-update-two-phase-staged-draft-implementation.md) — Two-Phase Staged-Draft publication architecture implementation plan. Tasks 1–4 are complete with per-task C0/I0; Task 5 documentation migration in progress; Task 6 final branch acceptance pending. Phase 1 staging tooling exists, but real staging has NOT been executed.
- **Gate #2 Normative Ordering**: Mandatory 7-step sequence: freeze exact candidate bytes -> Launcher packaged smoke + Updater self-check directly on frozen bytes -> fresh post-smoke recomputation of sizes, SHA-256 digests, and Core installed identity -> construct and sign canonical `release-v2.json` locally with offline `neko-update-prod-1` private key -> local cryptographic and descriptor binding verification -> repository safety and clean worktree checks -> formal independent review clearance (C0/I0).
- **Byte Mutation Invalidation Rule**: Any byte mutation, file touch, recompilation, or test re-run after fresh measurement invalidates Gate #2. If any candidate file is touched or re-tested after measurement, Gate #2 is void and requires restaging, remeasuring, re-signing, or creating a new candidate as applicable.
- **Supersession of Obsolete Single-Phase CI**: Old single-phase CI compilation and local filesystem workflow path inputs are obsolete and superseded. PyInstaller builds are non-byte-reproducible and hosted runners cannot access local operator storage (`E:\...`). The `build-installer` CI tag job is diagnostic-only; its compiled binaries possess zero release authority.
- **Four Trusted Client Update Assets**: Each stable release contains exactly one each of `release-v2.json` (signed envelope authority), `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip`. Local staging directories must contain strictly these four files. Permitted human-facing extras on GitHub Releases (such as checksum files or installers) are ignored by client update logic. Closed 3-component set `{launcher, updater, core}`.
- **Operator Runbook Commands**:
  - Local post-Gate #2 staging: `launcher\.venv\Scripts\python.exe scripts\stage_draft_release.py --staging-dir <dir> --tag v5.1.0a3 --target-commit <sha>`
  - Phase 2 remote publication: `gh workflow run release.yml --ref v5.1.0a3 -f publish_release=true -f release_id=<ID> -f release_tag=v5.1.0a3 -f expected_target=<SHA>`. `--ref` selects the reviewed workflow definition from the approved release tag; `expected_target` remains the exact approved checkout and authority commit.
- **Gates & Authority**: Gate #2 remains NOT PASSED. Gate #3 remains NOT PASSED. No candidate rebuild after latest implementation, no fresh post-smoke remeasurement, no production signing, no draft creation/upload, no publication.
- **Operational Discipline**: Hermes is the sole repo/project mutation executor. Mandatory dedup check before every Hermes dispatch (`--oneshot` + registry + session history).
- **Scope Boundary**: Unrelated Supabase/Admin/account/recovery/proxy services remain untouched with no update fallback. Documentation does not claim production signing, tag creation, draft release, asset upload, publication, merge, push, deployment, live auto-update completion, Gate #2, or Gate #3.

### Historical and Superseded Update Plans

- [2026-09-08 GitHub Releases specification](superpowers/specs/2026-09-08-software-update-github-releases-design.md) — **AUTHORITY FOR CLIENT DISCOVERY, TRUST, AND ROLLBACK / PARTIALLY SUPERSEDED**. Section 8 / single-phase CI publication handoff superseded by 2026-09-09 two-phase design.
- [2026-09-08 implementation plan](superpowers/plans/2026-09-08-software-update-github-releases-implementation.md) — **HISTORICAL / SUPERSEDED BY 2026-09-09 TWO-PHASE PLAN**. Tasks 1–7 accepted C0/I0 (Task 7 canonical full Launcher suite 1673 passed / 35 skipped / 0 failed; optional disposable GitHub proof NOT RUN / ACCEPTABLE) preserved as historical implementation evidence. Stale operative reviews from that cycle are superseded.

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
