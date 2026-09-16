# Single-Repo Integration + Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the independently accepted release-authority/publisher and runtime workstreams, prove the full product/release matrix, and stop at fresh Owner gates before any production authority/public GitHub mutation.

**Architecture:** No worker resolves cross-workstream conflicts ad hoc. The controller integrates only reviewed commits in task order, reruns the full acceptance matrix on the combined tree, and creates separate gates for (1) real seq8 terminal authority mutation, (2) production replacement signing, and (3) canonical GitHub release/tag publication. Public and destructive actions remain outside this implementation plan.

**Tech Stack:** Git worktrees/cherry-pick integration, Python 3.12/pytest/Ruff, PyInstaller frozen release toolchain, release proof harness, Hermes Kanban, independent reviewer profile.

**Spec:** `docs/superpowers/specs/2026-09-16-single-repo-unified-release-design.md`

**Execution contracts:** `docs/superpowers/plans/2026-09-16-single-repo-plan-contracts.md`

## Global Constraints

- Integrate only exact commits that independently passed C0/I0; conflicts abort and block rather than being manually resolved inside an integration task.
- Accepted baseline branch/history must not be reset/rebased/re-written.
- Full authored Release set is Installer + release-v2 + Launcher + Updater + Core in the single canonical repo.
- Mandatory 5.x/no-skip, stable 5.x Updater, exact-release Repair, machine binding, single-active-session, and 6.x reinstall boundary must all survive integration.
- Actual seq8 FAILED append, production signing, tag/ref mutation, GitHub draft/release creation/promotion, and retirement/destructive operations require fresh exact Owner gates and are not implied by this plan.
- No private key material in Hermes workers/logs/repo/evidence.

---

### Task INT-SR1: Integrate Release Authority + Publisher accepted commits

**Files:** Git history + integration evidence only.

- [ ] **Step 1: Fresh prerequisite check.** Read Kanban states/results for RA-SR1..RA-SR5 and their review children; require explicit C0/I0 and capture exact reviewed commit SHAs.
- [ ] **Step 2: Verify integration base.** Run `git status --short --branch`, `git rev-parse HEAD`, and ancestry checks against the accepted implementation base. Unexpected tracked drift blocks integration.
- [ ] **Step 3: Cherry-pick reviewed RA commits in task order.** For each exact SHA run `git cherry-pick <sha>`. On conflict run `git cherry-pick --abort`, block INT-SR1, and create a remediation + fresh re-review task. No manual conflict resolution.
- [ ] **Step 4: Run the RA acceptance matrix.** Full relevant ledger/controller/trust/verifier/publisher tests, Ruff, repository safety, `git diff --check`, and local mutation-free proof harness must all be green.
- [ ] **Step 5: Record integration evidence** with base SHA, ordered reviewed commit list, resulting SHA/tree, test counts, and clean tracked status.
- [ ] **Step 6: Independent integration review C0/I0.** Reviewer is read-only and reruns the critical matrix.

### Task INT-SR2: Integrate Runtime accepted commits

**Files:** Git history + integration evidence only.

- [ ] **Step 1: Fresh prerequisite check.** Require RT-SR1..RT-SR8 plus all review/remediation children explicit C0/I0; capture exact accepted SHAs.
- [ ] **Step 2: Cherry-pick reviewed RT commits in task order** onto INT-SR1 accepted head. Conflict handling is exactly the companion integration contract: abort, block, remediate, re-review.
- [ ] **Step 3: Run Runtime acceptance matrix**: full Launcher tests, new integrity/repair/machine-binding/auth/UI suites, canonical Launcher/Updater builds, built Updater `--self-check`, Ruff, repository safety, `git diff --check`.
- [ ] **Step 4: Run combined packaged scenarios** for mandatory update, failed-update no bypass, 6.x reinstall, File Check read-only, exact-release Repair, corrupt Updater reinstall, direct/copy rejection, reinstall/login and old-session invalidation.
- [ ] **Step 5: Record integration SHA/tree and evidence**; tracked worktree must be clean after evidence commit.
- [ ] **Step 6: Independent integration review C0/I0.**

### Task INT-SR3: Full combined release/runtime acceptance matrix

**Files:**
- Create: `docs/superpowers/evidence/v512-single-repo-full-acceptance.md`
- Tests/evidence only unless a failure creates a separately scoped remediation + review task

- [ ] **Step 1: Verify exact ancestry and scope.** Record spec commit, plan commits, RA/RT review commits, integration head/tree, and `git status --short`.
- [ ] **Step 2: Run full automated verification.** Require full Launcher pytest suite zero failures; full root/release-authority suites; all new single-repo tests; Ruff; repository safety; `git diff --check`; updated K1/trust/authority provenance checks.
- [ ] **Step 3: Build full five-asset staging set.** Using the frozen release toolchain build `NekoFamilyProxy-Installer.exe`, `NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`; generate proof `release-v2.json`; run built Updater self-check; record exact size/SHA-256 of all five assets.
- [ ] **Step 4: Verify unified Release shape locally/emulated** with proof authority only. Require canonical repo/tag/target and the exact five authored assets.
- [ ] **Step 5: Execute negative matrix**: old Updates repo; wrong source commit/tag/target; missing/duplicate/extra authored asset; bad signature/hash; replay/downgrade/same-sequence conflict; failed update bypass attempt; File Check mutation attempt; Updater self-update attempt; direct Asset; copied install; concurrent stale session; 5.x->6.x in-place attempt.
- [ ] **Step 6: Write durable evidence** with exact SHAs/counts/build identities and the four literals from the execution-contract companion: no production ledger mutation/signing/public GitHub mutation/destructive action.
- [ ] **Step 7: Commit evidence** as `test: accept single-repo release and runtime architecture`.
- [ ] **Step 8: Independent FINAL review C0/I0.** Any C/I finding creates remediation and fresh full re-review.

### Task INT-SR4: Create exact post-acceptance Owner gates

**Files:** Kanban/controller state only; no source changes.

- [ ] **Step 1: Create `OWNER GATE — terminate superseded seq8`.** Bind exact accepted source HEAD/tree, seq8 release id/source/component/payload/envelope hashes, latest ledger head, reviewed supersession-operation commit, and action scope limited to append/read-back terminal FAILED + reconciliation. Explicitly exclude signing/publication/tag/ref mutation.
- [ ] **Step 2: Create `OWNER GATE — production replacement signing`.** Depend on successful seq8 terminal reconciliation and bind newly reserved sequence/release id/component-set/source commit plus signing/custody-only scope. Explicitly exclude publication/tag/ref mutation.
- [ ] **Step 3: Create `OWNER GATE — canonical unified public release`.** Depend on successful replacement signing and final hosted preflight. Bind canonical repo, exact tag, target/source commit, all five asset sizes/hashes, signed payload/envelope hashes, publisher commit, and explicitly enumerated draft/upload/readback/promotion/tag/ref mutations.
- [ ] **Step 4: Keep old dedicated-repo CR7/CR8 cards permanently superseded/parked.** They can never satisfy these new gates.
- [ ] **Step 5: Keep retirement/destructive cards blocked** until a future separate reviewed plan and exact Owner authorization.

## Completion Gate

Implementation orchestration stops at the Owner gates unless the Owner separately approves their exact bound actions. A green C0/I0 combined tree is release-ready evidence, not production/public authority.
