# NEKO FAMILY PROXY — LAUNCHER COMPONENT STATUS & START HERE GUIDE

```text
DOCUMENT:                       docs/current/README.md
STATUS:                         PRODUCTION RELEASED
PHASE:                          PRODUCTION RELEASE/CUTOVER CLOSED
AUTHORITY:                      START bba655b3e6443ebcdf84a266e42cc918bdefe32f; CORE 862bfec463d06d57e1bee05c2bc490740eb714d4
PHASE_2_5:                      CLOSED
TECHNICAL_SECURITY_GATE:        PASS
NEXT_ACTION:                    NORMAL DEVELOPMENT
LAST_UPDATED:                  2026-08-22
CURRENT_PHASE:                  T10 COMMERCIAL LAUNCHER UI/UX
T10A:                           CLOSED
T10B1:                          CLOSED — FUNCTIONAL + OWNER VISUAL APPROVAL PASS
T10B1.2:                        CLOSED — CUSTOMER-SAFE VISUAL CLOSURE
T10B2:                          CLOSED — ENGINEERING + AUTHENTICATED PACKAGED + OWNER REVIEW PASS
T10B3:                          CLOSED — ENGINEERING + OWNER FINAL VISUAL REVIEW PASS
T10B3.1:                        CLOSED
T10B3_APPROVED_COMMIT:          1edfdb05042ed4a74128fc6826280f70f558b61d
T10B4:                          CLOSED — APPROVED AUTHORITIES PRESERVED
APPROVED_FEATURE_AUTHORITY:     e7f9530b1e9eb0536e10c04ad7b362ae7281f4d7
APPROVED_EXE_SHA256:            4ae0aa676a41822033a6b00fdae9dde7ff3b900fc30ae39ca71dea6851411609
CORE_DEPLOYED_ARTIFACT:         862bfec463d06d57e1bee05c2bc490740eb714d4
SUCCESSOR:                      NORMAL DEVELOPMENT
GLOBAL_STATUS:                  see Admin docs/current/README.md
ACTIVE_BRANCH:                  main
T10_BASE:                       8d4543553622f927d2d62dd054715a6523d82698
RUNTIME_SOURCE_BASE:            8832429a7546ab57dd8ac3a48b40b93387cb9f19
SERVER_OPERATIONS:              T1-T9 CLOSED (Production Verified on AWS Lightsail Japan)
ACTIVE_PRODUCT_BRANCH:          main
MAIN_BRANCH_STATUS:             PRODUCTION RELEASED
PHASE_2_5_TECHNICAL_SECURITY_GATE: PASS
PERMIT_CONTRACT:                LITE_V1
SESSION_POLICY:                 LATEST_CLAIM_WINS
PHASE_2_5_CLOSURE_EVIDENCE:     See phase-2-5-distinct-auth-session-future-permit-proof.md
T10B3.1_EXE_SHA256:             E4E114E138845566F7D25172CB4E8EAAC862FC43948EBEB8AF79D2F3AC9378C2
```

---

## 1. Quick Orientation: What is the Launcher Component Doing Now?

**Neko Family Launcher** is the customer desktop interface and backend edge client for *Phantasy Star Online 2 (PSO2 JP)* proxy routing.

The project infrastructure and operations milestones (**Phases T1 through T9**) are **CLOSED and verified in production**:
- **Phase T1–T3 (Closed)**: Implemented Core local telemetry engine and Launcher local telemetry consumer via Windows Named Pipe `\\.\pipe\NekoProxyCoreTelemetry`.
- **Phase T4–T6 (Closed)**: Live server metrics collection, time-series retention pruning via `pg_cron`, and historical range queries.
- **Phase T7–T8 (Closed)**: Unified AWS Lightsail Discord worker daemon, crash recovery, and production operations hardening.
- **Phase T9 (Closed)**: Weekly automated server maintenance and scheduled reboot lifecycle (Tuesdays 02:00 Asia/Bangkok).

**Phase T10A (Commercial Launcher UI/UX Design Freeze)** is **CLOSED**. The commercial UI architecture, customer status translation layer, single-instance Settings window design, and capability matrix are frozen in [`t10-commercial-ui-ux-design-freeze.md`](t10-commercial-ui-ux-design-freeze.md).

> [!IMPORTANT]
> **Production release: COMPLETE.** Phase 2.5 is `CLOSED`, the technical security
> gate is `PASS`, and the approved Launcher feature authority has been cut over to
> production `main`. The next action is normal development.

Original Edge evidence remains **A=MISSING, B=PASS, C=PASS**. Supplemental old-A
Edge evidence remains **PASS**. `PROCESS_COMPLIANCE = FAIL — HISTORICAL FORCE-PUSH
RECORDED` remains historical release evidence.

---

## 2. Active Launcher Documentation (`docs/current/`)

| Document | Role / Content | Authority Level |
| :--- | :--- | :--- |
| **[`README.md`](README.md)** | Component status, branch authority, and start here orientation | `CURRENT_STATUS` |
| **[`t10-commercial-ui-ux-design-freeze.md`](t10-commercial-ui-ux-design-freeze.md)** | T10 commercial UI/UX architecture, Settings window design & capability matrix | `CURRENT_CONTRACT` |
| **[`launcher-architecture.md`](launcher-architecture.md)** | Desktop application layered architecture, IPC, and controllers | `CURRENT_CONTRACT` |
| **[`neko-auth-lite.md`](neko-auth-lite.md)** | NEKO-AUTH-LITE authentication, challenge-response, and permit flow | `CURRENT_CONTRACT` |
| **[`final-windows-e2e-harness.md`](final-windows-e2e-harness.md)** | Windows E2E integration test harness and binary admission gates | `CURRENT_CONTRACT` |
| **[`phase-2-5-distinct-auth-session-future-permit-proof.md`](phase-2-5-distinct-auth-session-future-permit-proof.md)** | Closed distinct auth session future permit security proof and evidence | `CURRENT_RELEASE_EVIDENCE` |
| **[`build-windows-executable.md`](build-windows-executable.md)** | PyInstaller standalone packaging and secret-hygiene build instructions | `CURRENT_OPERATIONAL` |
| **[`debug-console.md`](debug-console.md)** | Windows debug console, runtime logging, and IPC troubleshooting | `CURRENT_OPERATIONAL` |
| **[`repository-layout.md`](repository-layout.md)** | File organization and component dependency layout | `CURRENT_OPERATIONAL` |
| **[`runtime-distribution.md`](runtime-distribution.md)** | External Core runtime distribution policy | `CURRENT_OPERATIONAL` |
| **[`closed-beta-runbook.md`](closed-beta-runbook.md)** | Approved closed-beta distribution, tester, rollback, and monitoring checklist | `CURRENT_OPERATIONAL` |

---

## 3. Global Cross-Repository Authority

For complete cross-component governance and global project phases, refer to the **Global Doc Authority**:
- **Global Project Status:** `D:\Github\Neko-Family-Proxy-admin-tool\docs\current\README.md`
- **Core Engine Source Authority:** `D:\Github\NekoProxyCore` (`feature/neko-auth-lite-v1-core`)

---

## 4. Historical Archive Index

Historical phase proposals, superseded AI prompts, and completed milestone evidence are preserved in `docs/archive/`:

- **[Telemetry Archive](../archive/telemetry/)**: [`launcher-telemetry-consumer-handoff.md`](../archive/telemetry/launcher-telemetry-consumer-handoff.md)
- **[Prompts Archive](../archive/prompts/)**: [`backend-single-active-session-ai-prompt.md`](../archive/prompts/backend-single-active-session-ai-prompt.md), [`launcher-single-active-session-ai-prompt.md`](../archive/prompts/launcher-single-active-session-ai-prompt.md), [`backend-single-active-session-ai-prompt-root-duplicate.md`](../archive/prompts/backend-single-active-session-ai-prompt-root-duplicate.md)
- **[Phase 2.5 Archive](../archive/phase-2-5/)**: [`phase-2-production-deployment-plan.md`](../archive/phase-2-5/phase-2-production-deployment-plan.md), [`phase-2-5-migration-history-reconciliation.md`](../archive/phase-2-5/phase-2-5-migration-history-reconciliation.md), [`phase-2-5-linked-parity.json`](../archive/phase-2-5/phase-2-5-linked-parity.json)
- **[Historical Blocked Archive](../archive/blocked/)**: Resolved historical blocker proposals and handoffs.
- **[Scratch Archive](../archive/scratch/)**: [`historical-phase25-work-progress-notes.md`](../archive/scratch/historical-phase25-work-progress-notes.md)
- **[Backend Supabase Archive](../archive/backend-supabase/)**: [`issue-launch-permit-phase-1.md`](../archive/backend-supabase/issue-launch-permit-phase-1.md)
- **[Historical S0 Archive](../archive/)**: [`launcher-s0-contract-proposal.md`](../archive/launcher-s0-contract-proposal.md), [`launcher-s0-connector-handoff.md`](../archive/launcher-s0-connector-handoff.md), [`s0-security-contract-freeze-request.md`](../archive/s0-security-contract-freeze-request.md)
