# Single-Repo Release Authority + Publisher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the production 5.x machine-release trust/publisher/authority flow from the superseded dedicated Updates repository to the single canonical public repository `Valeneko-pranmong/Neko-Family-Proxy`, while safely consuming signed-but-unpublished sequence 8 and preserving all release-security invariants.

**Architecture:** Keep the existing signed `release-v2.json`, sequence authority, source-commit binding, staged-draft hosted-byte verification, and fail-closed recovery model. Replace only the repository topology and split Human/Machine publication contract with a single canonical draft/release contract that requires the Installer plus all four machine assets in one release. Treat old signed seq8 as immutable authority history; terminate it append-only before allocating/signing any replacement sequence.

**Tech Stack:** Python 3.12, pytest, Ruff, GitHub CLI integration wrappers, canonical JSON + SHA-256 + Ed25519 release envelopes, append-only production sequence ledger, Hermes Kanban.

**Spec:** `docs/superpowers/specs/2026-09-16-single-repo-unified-release-design.md`

**Execution contracts:** `docs/superpowers/plans/2026-09-16-single-repo-plan-contracts.md`

## Global Constraints

- Canonical public repository is exactly `Valeneko-pranmong/Neko-Family-Proxy`.
- `Valeneko-pranmong/Neko-Family-Proxy-Updates` is superseded and must never be created or published to.
- Every 5.x GitHub Release must contain authored assets `NekoFamilyProxy-Installer.exe`, `release-v2.json`, `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip`; GitHub-generated source archives remain automatic.
- Existing production release signature, SHA-256, sequence/replay/downgrade, exact source commit, tag, target commit, and hosted-byte checks remain fail-closed.
- The old seq8 SIGNED record and signed envelope are immutable history. Never overwrite or re-sign sequence 8.
- No production signing/publication/tag/ref mutation is authorized by implementation tasks. All implementation/tests are local-only until a later fresh exact Owner gate.
- Private signing key bytes or secret paths must never enter worker prompts/logs/source/tests.
- TDD RED -> GREEN is mandatory for every behavior change; independent C0/I0 review is mandatory per task gate.

---

## File Structure / Responsibility Map

- `scripts/production_sequence_ledger.py` — append-only authority event validation/reconciliation; add/verify architecture-supersession evidence rules without weakening terminal-state semantics.
- `scripts/release_controller.py` — controller orchestration and exact production authority/repository checks.
- `scripts/publish_atomic_release.py` — evolve machine-only draft publisher into canonical unified Release publisher, retaining source/tag/target and hosted-byte verification.
- `scripts/publish_human_release.py` — retire/redirect the old Installer-only release path; it must no longer create a second normal 5.x Release.
- `scripts/verify_github_release_assets.py` — verify canonical unified authored asset set and release-v2 machine bindings.
- `scripts/verify_human_release_assets.py` — delegate its normal 5.x validation to the unified asset contract so machine assets are not forbidden.
- `launcher/src/neko_launcher/infrastructure/update_channel_profile.py` — canonical production routing identity.
- `launcher/src/neko_launcher/updater/trust_profile.py` and enrollment/acceptance paths — verify signed profile with canonical repository and preserve immutable enrollment semantics.
- `scripts/verify_v512_k1_acceptance.py` — intentionally reopen K1 acceptance contract for the reviewed single-repo production profile; never bypass immutability checks.
- Tests: existing publish/verifier/ledger/controller/update-channel/trust/K1 suites plus new focused regression cases.

### Task RA-SR1: Define and prove terminal supersession of signed-but-unpublished seq8

**Files:**
- Modify: `scripts/production_sequence_ledger.py`
- Modify: `scripts/release_controller.py`
- Test: `launcher/tests/test_production_sequence_ledger.py`
- Test: existing release-controller tests owning signing/reconciliation behavior
- Create: `docs/superpowers/evidence/v512-single-repo-seq8-supersession.md` only after local proof succeeds

**Interfaces:**
- Consumes: current ledger event contract with statuses `RESERVED`, `SIGNED`, `PUBLISHED`, `FAILED`, `RETIRED` and accepted transition `SIGNED -> FAILED`.
- Produces: the `SupersedeSignedReleaseRequest` and dry-run preparation behavior defined in the execution-contract companion.

- [ ] **Step 1: Write RED transition/reconciliation tests** from the companion contract. Add cases for wrong release id/source commit/component-set/envelope, already-published seq8, repeated terminalization, and `next_unused_sequence == 9` after the exact terminal event.
- [ ] **Step 2: Run focused tests** with `launcher/.venv/Scripts/python.exe -B -m pytest launcher/tests/test_production_sequence_ledger.py launcher/tests/test_release_controller_split.py -q`. Expected: new supersession-entrypoint tests FAIL before production edits. If `test_release_controller_split.py` is absent, use `file_find` to locate the existing release-controller test module and record that exact path in the task result before running.
- [ ] **Step 3: Implement the minimal preparation/controller operation** exactly as specified in `SupersedeSignedReleaseRequest`: validate current verified ledger + custody under authority lock, require exact SIGNED/unpublished identity, prepare one FAILED event, and reconcile. Production-authority read-only mode is `mutate=False`; no real append occurs in this task.
- [ ] **Step 4: Add dry-run output tests** asserting exact proposed event fields, current ledger head hash, and next sequence; prove zero writes when `mutate=False`.
- [ ] **Step 5: Run focused tests GREEN**, Ruff on changed files, `scripts/check_repository_safety.py`, and `git diff --check`.
- [ ] **Step 6: Write local evidence document** containing only public hashes/ids/commit SHAs and `PRODUCTION_LEDGER_MUTATED=false`.
- [ ] **Step 7: Commit atomically** as `feat: support terminal supersession of unpublished signed release`.
- [ ] **Step 8: Independent read-only review** must return C0/I0 before RA-SR2.

### Task RA-SR2: Reopen production trust profile and K1 acceptance for the canonical repository

**Files:**
- Modify: `launcher/src/neko_launcher/infrastructure/update_channel_profile.py`
- Modify: exact existing production profile spec/builder inputs located by tests; do not create a second profile system
- Modify: `scripts/verify_v512_k1_acceptance.py`
- Test: existing update-channel/trust-profile/K1 acceptance tests

**Interfaces:**
- Consumes: signed Profile Authority root, immutable enrollment pins, exact production release key registry.
- Produces: reviewed production trust profile whose repository identity is exactly `Valeneko-pranmong/Neko-Family-Proxy`, with all existing endpoint/key/channel/profile signature constraints unchanged.

- [ ] **Step 1: Add RED tests** that reject `Valeneko-pranmong/Neko-Family-Proxy-Updates` for the new production profile and accept only `Valeneko-pranmong/Neko-Family-Proxy`, while preserving key/profile/channel pins.
- [ ] **Step 2: Use `file_find` to identify exact trust/K1 test files under `launcher/tests/`, then run only those focused files** and record RED. Do not broaden scope until failing assertions identify the accepted profile binding that must change.
- [ ] **Step 3: Change only the accepted production routing/profile inputs** to the canonical repository; do not add runtime/user-selectable repository switches.
- [ ] **Step 4: Update K1 acceptance verification intentionally** so the reviewed acceptance record proves the new canonical profile through the same fixed authority roots/closed schemas; never weaken or skip the immutability/provenance checks.
- [ ] **Step 5: Run focused trust/K1 tests GREEN**, Ruff, repository safety, `git diff --check`, and the updated K1 verifier in read-only mode.
- [ ] **Step 6: Commit atomically** as `feat: bind production update trust to canonical repository`.
- [ ] **Step 7: Independent read-only C0/I0 review** before RA-SR3.

### Task RA-SR3: Define one canonical unified Release asset contract

**Files:**
- Modify: `scripts/verify_github_release_assets.py`
- Modify: `scripts/verify_human_release_assets.py`
- Test: existing `launcher/tests/test_verify_github_release_assets.py`
- Test: existing `launcher/tests/test_verify_human_release_assets.py`

**Interfaces:**
- Produces: `REQUIRED_UNIFIED_ASSETS` and `verify_unified_release_assets(...)` defined in the execution-contract companion.

- [ ] **Step 1: Write RED tests** for exactly Installer + four machine assets, each missing asset, duplicate asset, unexpected authored asset, wrong tag, wrong target, wrong draft state, and old Human-verifier behavior that forbids machine assets.
- [ ] **Step 2: Run `launcher/.venv/Scripts/python.exe -B -m pytest launcher/tests/test_verify_github_release_assets.py launcher/tests/test_verify_human_release_assets.py -q`** and capture RED before production edits.
- [ ] **Step 3: Implement `REQUIRED_UNIFIED_ASSETS` and `verify_unified_release_assets`** with the exact contract/algorithm in the companion. Preserve existing machine manifest/component identity validation and add Installer hosted-byte identity validation at the composed release layer.
- [ ] **Step 4: Make legacy normal 5.x verifier entrypoints delegate to the unified verifier**. Historical/audit-only helpers may remain, but no normal path may define Installer-only or machine-only canonical releases.
- [ ] **Step 5: Run verifier tests GREEN**, Ruff on changed scripts/tests, repository safety, `git diff --check`.
- [ ] **Step 6: Commit** `feat: verify unified canonical release assets`.
- [ ] **Step 7: Independent C0/I0 review** before RA-SR4.

### Task RA-SR4: Unify draft publication without losing atomic/idempotent safety

**Files:**
- Modify: `scripts/publish_atomic_release.py`
- Modify: `scripts/publish_human_release.py`
- Modify: `scripts/release_controller.py`
- Test: existing atomic/human publisher tests and release-controller publication tests

**Interfaces:**
- Consumes: one frozen staging directory containing the five authored assets; exact target commit; tag; signed release authority binding; command executor.
- Produces: `publish_unified_release(...) -> UnifiedPublishResult` with the nine-step algorithm in the execution-contract companion.

- [ ] **Step 1: Add RED tests** for canonical repo, exact five-asset upload, Installer inclusion, hosted readback of all assets, `source_commit == target_commit` check before any public call, crash/retry idempotence, divergent pre-existing draft rejection, and zero calls to the superseded Updates repository.
- [ ] **Step 2: Use `file_find` to resolve the existing publisher/controller test files, then run that focused set RED** before production edits.
- [ ] **Step 3: Implement `publish_unified_release`** inside the existing atomic publisher responsibility boundary: canonical main repo only, exact five authored assets, source-commit check inside authority lock, staged draft/reconcile, hosted download/hash readback, unified verifier, single promotion.
- [ ] **Step 4: Reconcile `publish_human_release.py`** so its normal 5.x path delegates to or is superseded by the unified publisher and can no longer create a second Installer-only release. Keep historical deletion/audit validation functions only for historical operations that still explicitly call them.
- [ ] **Step 5: Run focused GREEN tests**, Ruff, repository safety, `git diff --check`.
- [ ] **Step 6: Commit** `feat: publish unified canonical releases`.
- [ ] **Step 7: Independent C0/I0 review** before RA-SR5.

### Task RA-SR5: Local end-to-end publication proof and authority acceptance

**Files:**
- Modify/Create only existing proof-harness/evidence paths identified by `scripts/` and `launcher/tests/`; no production custody/private-key paths
- Test: full publisher/verifier/controller/ledger/trust suites

**Interfaces:**
- Produces: mutation-free local/emulated evidence that a fresh sequence after terminal seq8 supersession can build a proof-signed candidate bound to the main repo, stage a unified draft shape, verify hosted-equivalent bytes, and recover idempotently from crashes.

- [ ] **Step 1: Build deterministic proof fixtures** for Installer + release-v2 + Launcher + Updater + Core using the existing Proof Release Authority only.
- [ ] **Step 2: Run happy path and negative proof cases** for wrong repo/tag/target, missing/duplicate/extra authored assets, bad signature/hash, stale source commit, same-sequence conflict, replay, rollback, and crash boundaries around draft/upload/readback/promotion.
- [ ] **Step 3: Run full relevant release-authority/publisher/trust regression suites**, Ruff, repository safety, `git diff --check`.
- [ ] **Step 4: Write durable local evidence** with exact commits/hashes/test counts and these literals: `NO_PUBLIC_MUTATION=true`, `NO_PRODUCTION_SIGNING=true`, `NO_PRODUCTION_LEDGER_MUTATION=true`.
- [ ] **Step 5: Commit proof-only tracked additions** with `test: prove unified release authority and publication flow`.
- [ ] **Step 6: Independent workstream acceptance C0/I0**. Only then may this workstream integrate with runtime work.

## Completion Gate

This plan is complete only when RA-SR1..RA-SR5 each have GREEN TDD evidence and independent C0/I0, the branch is clean, and no production/public state has been mutated. Actual seq8 terminal mutation, production signing, GitHub draft/release/tag mutation, or release promotion remains a separate fresh Owner-authorized controller gate.
