# Neko Family Proxy 5.1.2 Baseline & Mandatory Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` for implementation. Steps use checkbox (`- [ ]`) syntax for tracking. Every behavior change follows `superpowers:test-driven-development`. Every completed task requires an independent review before it is accepted.

**Goal:** Turn v5.1.2 into the new cryptographically enrolled baseline, move machine updates to `Valeneko-pranmong/Neko-Family-Proxy-Updates`, prove packaged mandatory update to an isolated 5.1.3-proof candidate, retire the historical Installer repository safely, and publish the canonical Human v5.1.2 release only after all Spec Revision 3.4 gates pass.

**Architecture:** Keep `Valeneko-pranmong/Neko-Family-Proxy` as canonical source + Human Release surface; use a dedicated Production Updates repository for the four machine assets; derive local identity only from authenticated durable updater state; embed the exact production-signed baseline envelope in the final Installer for offline first enrollment; use separate append-only sequence and release-audit ledgers; treat repository deletion/tag mutation/public release operations as controller-only gated release actions, never Hermes worker actions.

**Tech Stack:** Python >=3.11, pytest, Ruff, PyInstaller, Inno Setup, PowerShell 5.1, Git/GitHub CLI, Ed25519 `release-v2` envelopes, existing updater transaction/probation/rollback/recovery engine, Hermes Kanban.

**Spec:** `docs/superpowers/specs/2026-09-13-neko-family-5-1-2-baseline-forced-update-revision-3-4.md`

## Executable Plan Pack

Superpowers scope review found three separable implementation workstreams. This master document owns authorization boundaries, cross-workstream DAG, release stop gates, and final acceptance; **Hermes implementation cards must use the checkbox tasks in these executable subplans as the task source of truth:**

- Runtime trust/enrollment: `docs/superpowers/plans/2026-09-13-v512-runtime-trust-enrollment.md` (`RT0/K1` signed trust-profile architecture gate, `RT1` packaged K1 conformance, then `RT2–RT10`).
- Release authority/build/proof: `docs/superpowers/plans/2026-09-13-v512-release-authority-proof.md` (`RA1–RA10`).
- Installer-repo retirement/Human promotion tooling: `docs/superpowers/plans/2026-09-13-v512-retirement-human-promotion.md` (`RH1–RH7` plus controller G14–G24 gates).

The coarse `Task 1–15` sections later in this master are architectural workstream summaries retained for traceability; they are **not** executable Hermes cards and do not override the detailed checkbox subplans. Task 0/K0 remains the controller execution bootstrap after future plan approval.

## Authorization Boundary For This Plan

Owner approved **writing-plan only** when this document was created. Nothing in this plan is an instruction to start implementation, open Hermes Gateway, mutate a public tag/repository/release, sign a production payload, upload an asset, or delete a repository. Execution starts only after the Owner separately approves this implementation plan.

## Current Read-Only Findings This Plan Must Correct

- Canonical source currently resolves to historical accepted SHA `f4afa51878ccea590c33f758c9da70eb3ddbd43b`; execution must re-read `HEAD`, `origin/main`, and worktree cleanliness rather than trusting this cached value.
- `github_release.py` / `github_asset_downloader.py` currently bind discovery and asset URLs to `Valeneko-pranmong/Neko-Family-Proxy`; production must move to `Neko-Family-Proxy-Updates`.
- `app_factory.py` and `pending_update_bootstrap.py` still construct production local identity as `sequence=0 / dev-unpublished`.
- `software_update_policy.py` does not yet have the full committed-vs-high-water / exact same-sequence binding semantics required by Revision 3.4.
- `installer/scripts/verify-core-install.ps1` still treats `manifest.files` as a property map while the real Core manifest uses an array; the current historical v5.1.2 payload therefore fails post-install verification.
- `release_controller.py`, `publish_atomic_release.py`, `publish_installer_release.py`, `verify_installer_release_assets.py`, `release_target.json`, current docs, and tests still encode the obsolete main-machine + separate-installer-repo topology. `kanban_release_adapter.py` also still auto-creates a Hermes release task that directly invokes `release_controller.py` after Main Source Acceptance; Revision 3.4 execution must retire that worker-driven authority path and make source acceptance only a controller-readiness signal.
- Existing publication paths contain a `gh auth token` → `curl -H Authorization: Bearer ...` pattern that must be removed; no token may appear in child-process argv/logs.
- A production-signed `stable-0007 / sequence 7` has already been cryptographically authenticated. Sequence 8 is only provisional next-unused until the production sequence ledger and fresh audit agree.
- `Valeneko-pranmong/Neko-Family-Proxy-Updates` did not exist at the last read-only audit; creating it is a later controller/public-mutation gate, not an implementation-worker task.
- The old 2026-09-12 v5.1.2 plan/spec are historical and conflict with Revision 3.4. Do not implement their obsolete machine/main + installer-repo routing.

## Global Constraints

### Source and execution isolation

- Canonical repo: `E:\Github\Neko-Family-Proxy`.
- Implementation must use a dedicated worktree/branch created only after plan approval. Suggested branch: `feature/v5.1.2-baseline-revision-3-4`; suggested worktree: `E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34`.
- No source implementation directly on canonical `main`.
- Before any task, record exact `BASE_SHA`, `origin/main`, and baseline test results.
- No partial merge to `main`; only an independently accepted exact branch HEAD may be merged.

### Hermes routing

- Normal implementation / tests / config / docs: `ag/gemini-3.8-flash-high`.
- Independent reviewer for each task and final acceptance: `ag/gemini-pro-agent`.
- `cx/gpt-5.6-sol` with reasoning effort `high` is escalation-only for genuinely difficult cross-cutting trust/concurrency/recovery/release-authority problems. The controller must record why escalation is necessary before using it.
- Implementer never reviews its own work.
- Task acceptance and final acceptance both require **Critical 0 / Important 0**.

### TDD law

For every production-code behavior change:

1. Write the smallest focused test that expresses the contract.
2. Run it and record the expected RED failure for the correct reason.
3. Implement the minimum production change.
4. Run focused GREEN tests.
5. Run affected regression tests.
6. Run Ruff and `git diff --check`.
7. Commit the task atomically.
8. Request independent review against `BASE_SHA..HEAD_SHA`.
9. Fix every Critical/Important finding, rerun tests, and re-review before downstream tasks depend on it.

Do not add production code first and backfill tests later.

### Security / release authority

- Do not read, print, copy, expose, or delegate possession of the production private signing key to Hermes workers/reviewers.
- Do not recreate credential-restoring curl shims.
- Do not pass GitHub bearer tokens in subprocess argv or logs.
- Do not add signature bypasses, trust fallbacks, hidden proof switches, or runtime environment overrides that can turn production into proof mode.
- Production signing is a controller-controlled boundary and is not executed during source implementation tasks.
- Sequence 8/stable-0008 is provisional. Implementation must never hard-code it as permanent release authority.

### Public/destructive operation boundary

The following are **controller-only release-phase actions** and are forbidden to Hermes implementers/reviewers:

- create `Neko-Family-Proxy-Updates` or any proof GitHub repository;
- production-sign the final payload;
- create/push/delete/rebind canonical `v5.1.2` tag;
- create/upload/publish production machine or Human GitHub Releases;
- capture live destructive preconditions and issue DELETE for `Neko-Family-Proxy-Installer`;
- publish `draft=false` Human v5.1.2.

Implementation tasks may create pure functions, command builders, validators, dry-run modes, fake executors, fixtures, and tests for these flows. They must not execute the real public mutation.

## Locked High-Level File/Module Direction

New focused modules are preferred over further expanding `release_controller.py`:

- `launcher/src/neko_launcher/infrastructure/update_channel_profile.py` — immutable production/proof channel profile.
- `launcher/src/neko_launcher/infrastructure/authenticated_release_identity.py` — reconstruct production local identity from signed durable updater state + exact installed component bytes.
- `launcher/src/neko_launcher/bootstrap/baseline_enrollment.py` — offline baseline enrollment orchestrator from embedded signed envelope.
- `scripts/production_sequence_ledger.py` — hash-chained append/read/verify/reserve semantics for external Production Sequence Authority Ledger.
- `scripts/project_release_audit_ledger.py` — separate hash-chained Project Release-Audit Ledger events.
- `scripts/release_dependency_audit.py` — bound snapshot + old-repo dependency audit + freshness verification.
- `scripts/capture_installer_repo_forensics.py` — canonical repository/release/asset/ref snapshot + external artifact custody preparation.
- `scripts/verify_build_equivalence.py` — proof/production extracted inventory comparison.
- `scripts/publish_human_release.py` — canonical main-repo draft/upload/validate/promote logic using injected executor; replaces the obsolete dedicated-installer-repo publisher.
- `scripts/verify_human_release_assets.py` — exact one-installer Human Release validation.

These module names and responsibility boundaries are locked by this plan revision. Any proposed rename/merge that changes ownership of trust, ledger, forensic, or public-mutation responsibilities requires a plan revision before implementation; workers do not improvise alternate homes.

---

## P0 — Reviewed Plan-Pack Custody Before K0

**Authorization:** P0 runs only after (1) the exact five-file plan pack has a valid independent `ag/gemini-pro-agent` `C0_I0_PASS` record under the handoff contract above and (2) Owner explicitly approves those reviewed hashes for execution. It is not authorized by the current writing-plan phase, controller self-review, or an unsealed reviewer response.
**Purpose:** Move the exact independently reviewed planning artifacts plus their review record out of the primary worktree's untracked state without treating unknown dirt, changed reviewed bytes, or an unbound review verdict as acceptable.

- [ ] Re-read the Owner-approved Spec Revision 3.4 **byte-for-byte** and require SHA-256 exactly `2087863bad40ae1b75c5150c5c6e678a6e584ca96c23ccfc2d39819377e52b9c`; the two approved Markdown hard-break spaces in its Status/Approval header are part of those bytes and must not be normalized by plan cleanup. Fresh-hash all four plan files and require the exact closed five-file path→SHA set equals `docs/superpowers/evidence/v512-final-plan-review.json.reviewed_files` byte-for-byte by key/value semantics. Any mismatch is `P0_REVIEWED_PLAN_BYTES_CHANGED` and invalidates the review before any worktree/commit action.
- [ ] Strictly parse canonical `docs/superpowers/evidence/v512-final-plan-review.json`; require exact schema/fields, `reviewer_model="ag/gemini-pro-agent"`, `critical_count=0`, `important_count=0`, `verdict="C0_I0_PASS"`, exact five-file reviewed map, all three recorded custody SHA-256 values, and request/invocation/response custody paths resolving to the same deterministic `E:\\Github\\artifacts\\v512-final-plan-review\\attempts\\<review_request_sha256>\\` root with exact basenames `review-request-v1.txt`, `review-invocation-v1.json`, and `review-response-v1.json`; reject path escaping or another attempt root. Fresh-read all three files; require their bytes canonical per the handoff contract, recompute each digest, require invocation `requested_model == resolved_model == "ag/gemini-pro-agent"`, non-empty connector-issued `invocation_id`, exact request hash + five-file map, and require response request hash/model/reviewed map/counts/verdict/minor count match both invocation evidence and the repo review record. Missing/malformed/mutated request/invocation/response or self-asserted-only reviewer identity is `P0_FINAL_PLAN_REVIEW_EVIDENCE_INVALID` and STOP; never reconstruct identity/verdict from remembered prose.
- [ ] Record `FINAL_PLAN_REVIEW_RECORD_SHA256`, `FINAL_PLAN_REVIEW_REQUEST_SHA256`, `FINAL_PLAN_REVIEW_INVOCATION_SHA256`, `FINAL_PLAN_REVIEW_RESPONSE_SHA256`, all five reviewed file hashes, and pre-custody canonical `BASE_SOURCE_SHA = git rev-parse HEAD`. Owner execution approval must explicitly refer to this exact reviewed hash set plus review-record/request/invocation/response digests; a generic approval of “the latest plan” is insufficient.
- [ ] Re-read primary `git status --porcelain`. The only allowed non-clean entries are exactly the four reviewed plan files, Owner-approved Spec Revision 3.4, and canonical `docs/superpowers/evidence/v512-final-plan-review.json`, with hashes equal to the accepted review bindings/record and with no tracked-file modification. Any extra/unexpected path is `P0_UNEXPECTED_WORKTREE_DELTA` and STOP; do not stash/reset/delete it.
- [ ] Use Superpowers `using-git-worktrees` to create `feature/v5.1.2-baseline-revision-3-4` at `E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34` from `BASE_SOURCE_SHA`.
- [ ] Copy exactly the five reviewed plan/spec files plus `docs/superpowers/evidence/v512-final-plan-review.json` into that worktree, verify every hash/readback, and create one docs-only branch commit `docs(plan): record reviewed v5.1.2 revision 3.4 plan pack` containing no other path. The accepted attempt's external request/invocation/response files remain immutable controller custody and are not copied into the repository; the tracked review record binds all three by deterministic path/digest.
- [ ] Verify `git diff-tree --no-commit-id --name-only -r PLAN_PACK_COMMIT_SHA` equals exactly the closed six-path set: four plans + Spec Revision 3.4 + `docs/superpowers/evidence/v512-final-plan-review.json`. Re-read the committed review-record blob and require its `reviewed_files` hashes still match the five committed plan/spec blobs exactly.
- [ ] Only after the branch commit/readback succeeds, remove the byte-identical six untracked repository copies from the primary worktree; then require primary `git status --porcelain` empty and `git rev-parse HEAD == BASE_SOURCE_SHA`. If hash/path equality fails, STOP and leave the primary copies untouched.

**Evidence:** `BASE_SOURCE_SHA`, exact five reviewed file hashes, `FINAL_PLAN_REVIEW_RECORD_SHA256`, `FINAL_PLAN_REVIEW_REQUEST_SHA256`, `FINAL_PLAN_REVIEW_INVOCATION_SHA256`, `FINAL_PLAN_REVIEW_RESPONSE_SHA256`, connector-attested reviewer identity/invocation id, `PLAN_PACK_COMMIT_SHA`, exact six-path commit set, committed review-record→five-blob revalidation, and primary-clean readback.
**Stop gate:** `P0_PLAN_PACK_CUSTODIED`. No K0 until PASS.

---

## Task 0 / K0 — Execution Bootstrap, Baseline, and Hermes DAG Materialization

**Authorization:** Execute only after `P0_PLAN_PACK_CUSTODIED` PASS and Owner approval bound to the exact independently reviewed five-file hash set recorded by P0. A generic approval of a mutable “latest plan” is not sufficient.
**Implementation model:** controller setup; no source code.
**Public mutation:** none.

**Steps:**

1. Re-read canonical state:

```cmd
cd /d E:\Github\Neko-Family-Proxy
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git merge-base --is-ancestor HEAD origin/main
```

2. Require primary worktree clean, `HEAD == BASE_SOURCE_SHA`, and `HEAD == expected accepted origin/main`. Any mismatch after P0 is a new delta: STOP; do not silently stash/reset.
3. Reuse the P0 implementation worktree/branch and verify `git merge-base --is-ancestor BASE_SOURCE_SHA PLAN_PACK_COMMIT_SHA`; re-read the committed `v512-final-plan-review.json`, re-hash all five committed reviewed plan/spec blobs plus external `review-request-v1.txt`, `review-invocation-v1.json`, and `review-response-v1.json`, re-check connector-attested resolved-model/request/map bindings, and require exact P0-recorded digests before any implementation source change. Implementation source changes begin only after this docs-only reviewed-plan custody commit is intact.
4. In that worktree, run the existing full Launcher baseline and repository-safety checks before any production-code edit:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=short
.venv\Scripts\ruff.exe check src tests
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B scripts\check_repository_safety.py
git diff --check
```

5. If baseline is RED, record `K0_BASELINE_BLOCKED` in controller evidence and STOP before K1. Do not start Hermes Gateway or create implementation cards for an unresolved baseline.
6. On clean baseline, record `K0_BASELINE_ACCEPTED`. The approved plan has already frozen RT0/K1's signed trust-profile architecture, but **before the first RT1 production-code edit** the controller must complete K1A authority bootstrap under the same explicit execution authorization. K1A establishes/read-backs only the byte-canonical Profile Authority and Proof Release Authority public records, cross-verifies authenticated `neko-update-prod-1`, and never accesses any production private key. After K1A, materialize/dispatch **RT1 only** to implement/test the canonical profile codec, detached profile assembler, shared detached `release-v2` assembler, fixed loader, enrollment pins, and routing. Once that implementation is GREEN and committed as a clean `RT1_CODE_HEAD`, controller-only **K1B-A** seals/read-backs the exact production/proof profiles. RT1 then builds/measures the exact production/proof baseline package trees plus deterministic isolated proof N+1 fixture bytes; only after those identities exist does controller-only **K1B-B** obtain detached Proof Release Authority signatures, assemble/read-back `proof-k1-0001`/`proof-k1-0002`, and seal canonical `E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json` as `K1B_CUSTODY_SHA256`. K1A/K1B-A/K1B-B perform no production release signing, production sequence reservation, GitHub mutation, or release publication. RT2+, RA1+, and RH1+ remain blocked until exact `RT1_CODE_HEAD` conformance evidence is independently accepted `UPDATER_TRUST_FEASIBLE / C0_I0`, canonical `v512-k1-acceptance.json` is sealed in immutable `K1_ACCEPTANCE_COMMIT`, the Git-only **RT1 security-tool immutability guard** passes, **and only then** `scripts/verify_v512_k1_acceptance.py --require-git-immutability` passes for the exact accepted `K1B_CUSTODY_SHA256`. Board creation is a local process mutation, not a public GitHub mutation.

**Evidence:** K0 records `BASE_SOURCE_SHA`, `PLAN_PACK_COMMIT_SHA`, exact five reviewed plan/spec hashes, `FINAL_PLAN_REVIEW_RECORD_SHA256`, `FINAL_PLAN_REVIEW_REQUEST_SHA256`, `FINAL_PLAN_REVIEW_INVOCATION_SHA256`, `FINAL_PLAN_REVIEW_RESPONSE_SHA256`, connector-attested reviewer model/invocation id, origin/main SHA, baseline test counts/results, Ruff result, repository-safety result, worktree path, and branch name. K1A additionally records both exact public-custody file SHA-256 values plus `key_id/public_key_sha256`, authenticated `neko-update-prod-1` cross-check, and an explicit assertion that no profile/release signing, sequence reservation, or public mutation occurred. RT1/K1 later records `RT1_CODE_HEAD`, exact K1B-A profile payload/envelope/keyset SHAs, deterministic proof fixture identities, K1B-B proof payload/envelope SHAs, `K1B_CUSTODY_SHA256`, byte-identical updater evidence, and reviewer verdict; controller then seals those expectations in canonical `docs/superpowers/evidence/v512-k1-acceptance.json`, whose single immutable introduction commit is `K1_ACCEPTANCE_COMMIT`.

**Stop gate:** `K0_BASELINE_ACCEPTED`. No downstream task starts without it.

---

## Task 1 / RT1 — Signed Immutable Update Trust Profile + K1 Conformance

**Executable source of truth:** `docs/superpowers/plans/2026-09-13-v512-runtime-trust-enrollment.md`, Task RT1. This master task only owns cross-workstream gating and must not redefine a second trust interface.

**Goal:** Replace the packaged helper's direct production release-key registry with one fixed-path, Profile-Authority-signed declarative trust profile while preserving byte-identical proof/production `NekoUpdater.exe` bytes and eliminating all runtime profile/key switches.

**Controller prerequisites:** K1A exact Profile Authority + Proof Release Authority public custody must exist before RT1 production-code work. Exact signed production/proof profiles are created only at K1B-A after RT1's codec/assemblers are GREEN and committed as `RT1_CODE_HEAD`. Exact proof release envelopes are created only at K1B-B **after** package/candidate artifact identities are measured, and the resulting closed custody manifest is pinned by `K1B_CUSTODY_SHA256`. Workers receive only public authority records and sealed evidence; neither Profile Authority nor Proof Release Authority private key nor production release private key enters Hermes.

**Required contract:** RT1 produces `VerifiedUpdateTrustProfile`, a fixed loader for `<install_root>\trust\update-profile-v1.json`, immutable enrollment pins (`profile_id`, `profile_envelope_sha256`, `keyset_sha256`), `UpdateChannelProfile.from_verified(...)`, a detached-signature-only profile assembler, and one detached-signature-only `release-v2` assembler reused later by RA4 production signing. Neither assembler accepts/loads/invokes private-key material. Packaged `NekoUpdater.exe` embeds only the common Profile Authority public root; production/proof release keys come only from the verified signed profile. No CLI/env/registry/user-config/path override or fallback is permitted.

**Mechanical proof:** production/proof **baseline** package trees may differ only at exact `trust/update-profile-v1.json`; helper executable/module bytes are identical. Production profile contains production release key(s) only; proof profile `proof-v512` contains only the K1A Proof Release Authority. K1B-A seals those profiles first; exact package identities are then measured; K1B-B creates proof-only `proof-k1-0001` seq1 and mandatory `proof-k1-0002` seq2 through the one shared release assembler. Candidate N+1 keeps the exact baseline Updater bytes but uses deterministic changed proof-only Launcher/Core fixture artifacts, so the real packaged helper must authenticate/stage/handoff/apply N+1 without a proof-only helper. Neither proof envelope may verify under production trust, and a different valid signed profile after enrollment fails on marker pins before release/state evidence is trusted. The deterministic K1 candidate Launcher/Core are early architecture-feasibility fixtures only; K1 does not claim Spec §10 packaged restart/relaunch/probation coverage. Full packaged v5.1.2→v5.1.3-proof lifecycle evidence remains exclusively RA8/RA9 acceptance.

**Acceptance:** independent review must bind exact `RT1_CODE_HEAD`, exact K1A public-custody file hashes, exact `K1B_CUSTODY_SHA256`, and exact K1 evidence and return `UPDATER_TRUST_FEASIBLE / C0_I0`; controller then writes canonical `docs/superpowers/evidence/v512-k1-acceptance.json`, commits it with the reviewed evidence as `K1_ACCEPTANCE_COMMIT`, and the runtime plan's Git-only **RT1 security-tool immutability guard** must pass before `scripts/verify_v512_k1_acceptance.py --require-git-immutability`. Until that immutable record exists, the source guard passes, and the record verifies on the integration branch, **Task 2+, RA1+, and RH1+ are blocked**. Any workaround that embeds both release keysets, adds runtime profile selection, permits private-key/signer input to either detached assembler, forks release-envelope serialization, or weakens byte/signature checks is `ARCHITECTURE_FEASIBILITY_REGRESSION` and returns to Owner plan review.

---

## Task 2 — Authenticated Local Release Identity From Durable Updater State

**Goal:** Remove production `sequence=0/dev-unpublished` and reconstruct exact committed/high-water/observed/failed authority only from cryptographically authenticated durable state + installed bytes.

**Files:**

- Create: `launcher/src/neko_launcher/infrastructure/authenticated_release_identity.py`
- Modify: `launcher/src/neko_launcher/application/software_update_models.py`
- Modify: `launcher/src/neko_launcher/infrastructure/software_release_identity.py`
- Modify: `launcher/src/neko_launcher/bootstrap/app_factory.py`
- Modify: `launcher/src/neko_launcher/bootstrap/pending_update_bootstrap.py`
- Reuse without weakening: `launcher/src/neko_launcher/updater/state_models.py`, `slot_store.py`, `manifest_v2.py`, RT1 `trust_profile.py`, and the enrollment trust-binding validator
- Tests: `launcher/tests/test_software_release_identity.py`, `launcher/tests/test_software_update_composition.py`, `launcher/tests/test_pending_update_bootstrap.py`
- Add: `launcher/tests/test_authenticated_release_identity.py`

**Required local authority shape:**

```python
@dataclass(frozen=True)
class AuthenticatedReleaseBinding:
    release_sequence: int
    release_id: str
    payload_sha256: str

@dataclass(frozen=True)
class LocalReleaseIdentity:
    committed: AuthenticatedReleaseBinding
    high_water: AuthenticatedReleaseBinding
    observed: AuthenticatedReleaseBinding
    failed: AuthenticatedReleaseBinding | None
    launcher_version: str
    launcher_installed_identity_sha256: str
    updater_version: str
    updater_installed_identity_sha256: str
    core_version: str
    core_installed_identity_sha256: str

    @property
    def release_sequence(self) -> int:
        return self.committed.release_sequence
```

Keep full committed/high-water/observed/failed bindings. For enrolled production state require `observed == high_water`: `failed == high_water` means known terminal failure/no reapply; `failed != high_water` means that exact authenticated authority remains admitted/retryable even when artifacts are incomplete. After rollback the client must distinguish exact failed high-water from a conflicting payload reusing the same sequence. `dev-unpublished/0` remains legal only through the fully defined `DevelopmentReleaseIdentity`/`load_development_release_identity(...)` development contract in RT2; packaged production composition may not synthesize production authority from `__version__`.

**Reader contract:** `AuthenticatedReleaseIdentityReader(trust_profile: VerifiedUpdateTrustProfile).read(install_root: Path) -> LocalReleaseIdentity`; it must validate the fixed enrollment marker's exact `profile_id/profile_envelope_sha256/keyset_sha256` before selecting state, then use only `trust_profile.release_public_keys`. No network/raw-key/alternate-profile fallback is permitted.

It must select durable updater state through existing slot logic, require `enrollment_complete`, require committed/high-water/observed bindings with `observed == highwater`, resolve the committed payload SHA to exact signed evidence, cryptographically verify it, verify installed Launcher/Core/Updater identities, and independently verify exact high-water/observed/failed evidence. A durable state `committed=N, highwater=observed=N+1, failed!=N+1` is valid authenticated-but-incomplete authority and must survive reader reconstruction; it is not normalized to `LATEST` or failed.

**TDD steps:**

1. RED: valid committed state returns the exact committed binding + exact high-water binding.
2. RED: rollback state with committed N / high-water N+1 / failed N+1 returns all three exact bindings and cryptographically validates the N+1 evidence when present.
3. RED: same high-water sequence with changed release_id/payload evidence is rejected rather than collapsed to the same integer.
4. RED: missing/unsigned evidence, wrong payload digest, wrong release_id, wrong Launcher/Core/Updater installed hash, incomplete enrollment, corrupt slots all fail closed.
5. RED: composition no longer returns seq0/dev-unpublished for a production install fixture.
6. Run RED focused tests.
7. Implement minimal reader by reusing existing signed-envelope/state parsing; do not invent a second state file.
8. Update composition providers to use the reader.
9. GREEN + existing updater/enrollment regression:

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_authenticated_release_identity.py tests/test_software_release_identity.py tests/test_software_update_composition.py tests/test_pending_update_bootstrap.py tests/updater/test_enrollment.py tests/updater/test_slot_selector.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/infrastructure/authenticated_release_identity.py src/neko_launcher/application/software_update_models.py src/neko_launcher/infrastructure/software_release_identity.py src/neko_launcher/bootstrap/app_factory.py src/neko_launcher/bootstrap/pending_update_bootstrap.py tests
cd ..
git diff --check
```

**Review focus:** authenticated authority reconstruction, no unsigned fallback, committed/high-water/observed/failed separation.
**Escalation candidate:** `cx/gpt-5.6-sol high` only if reviewer finds unresolved state-machine/trust ambiguity.
**Acceptance:** C0/I0.

---

## Task 3 — Authenticated Ordering, Pre-Stage Authority Admission, and Discovery-Outage Semantics

**Goal:** Implement Revision 3.4 ordering semantics and persist an authenticated mandatory authority at the **real pre-stage boundary**: after authenticated discovery/policy but before `SoftwareUpdateStageService.stage()` downloads any Launcher/Core bytes. Committed sequence drives minimum-supported policy; high-water/observed provide anti-replay + resumable admission; failed marks only terminally suppressed authority.

**Executable ownership:** RT5 owns pure remote/local ordering + `payload_sha256` propagation. RT6 owns durable helper admission, coordinator ordering, narrow IDLE→IDLE state transition, and outage/retry behavior. Artifact-stage transport failure occurs before helper `BEGIN`, so Task 3 does not invent a PREPARING recovery exception for this case.

**Key files across RT5/RT6:**

- `launcher/src/neko_launcher/application/software_update_policy.py`
- `launcher/src/neko_launcher/application/software_update_models.py`
- `launcher/src/neko_launcher/infrastructure/software_update_v2.py`
- `launcher/src/neko_launcher/infrastructure/software_update_authority_admission.py` (new)
- `launcher/src/neko_launcher/application/software_update_coordinator.py`
- `launcher/src/neko_launcher/bootstrap/app_factory.py`
- `launcher/src/neko_launcher/infrastructure/software_update_apply.py` (retire direct-online `prepare()` bypass; verified pending only)
- `launcher/src/neko_launcher/infrastructure/software_update_stage.py` (honor `retry_staging=true` for exact admitted authority)
- `launcher/src/neko_launcher/infrastructure/software_update_pending_store.py` (pending envelope must bind exactly to admitted high-water/observed authority)
- `launcher/src/neko_launcher/updater/main.py`, `broker.py`, `staging_handoff.py`, `state_machine.py`
- RT5/RT6 focused policy, coordinator, authority-admission, broker/session, and state-machine tests.

**Policy contract:**

```python
mandatory_update = (
    authenticated_remote.mandatory
    or local.committed.release_sequence
        < authenticated_remote.minimum_supported_sequence
)
```

Ordering contract:

```text
remote.sequence > local.high_water.release_sequence
    => AVAILABLE or MANDATORY from committed-sequence formula

remote == committed == high_water == observed
    => LATEST / NO UPDATE

remote == high_water == observed > committed AND failed == high_water
    => LATEST / known failed / do not reapply

remote == high_water == observed > committed AND failed != high_water
    => LATEST / no new authority; preserve mandatory formula; retry_staging=true;
       retain committed-vs-remote changed_components for staging resumption

same numeric high-water sequence with different release_id/payload
    => SAME_SEQUENCE_IDENTITY_CONFLICT

remote.sequence < local.high_water.release_sequence
    => DOWNGRADE_OR_REPLAY_REJECTED
```

**Real pipeline contract:**

```text
resolver authenticates signed N+1
    -> RT5 policy says AVAILABLE/MANDATORY
    -> RT6 `ADMIT_AUTHORITY` one-shot helper session re-verifies exact envelope
    -> admission-only helper session returns success without activation/probation
    -> durable updater state remains IDLE with:
         committed=N
         highwater=observed=N+1
         failed unchanged
         exact envelope evidence stored
         transaction=null
    -> fresh local identity read + policy re-evaluation
    -> exact admitted authority now resolves `LATEST + retry_staging=true`
    -> lifecycle retry flag (or first-seen AVAILABLE/MANDATORY) authorizes `SoftwareUpdateStageService.stage()`
    -> retry result retains changed_components relative to committed runtime
    -> stage must honor retry_staging and may promote pending only from exact admitted binding
```

If staging network/download fails before `PendingUpdateStore.promote`, no updater transaction has begun: committed N remains runnable, high-water/observed N+1 remain durable, failed is unchanged, no fake pending exists, and exact N+1 is retryable when discovery/network returns. If discovery is unavailable in the meantime, the committed runtime remains non-bricking. `PendingUpdateStore.load_verified(...)` must reject any pending whose verified `(sequence, release_id, payload_sha256)` does not equal the admitted `high_water == observed` binding or equals `failed`. Later helper `BEGIN` occurs only after durable pending exists and retains the existing apply/recovery semantics. The legacy direct-online `SoftwareUpdateApplyService.prepare()` path is no longer production-capable after RT6; production apply is only `prepare_pending(...)`, so no resolver/download path can bypass durable authority admission + pending promotion.

**TDD summary:**

1. RT5 RED matrix covers newer optional/mandatory, committed minimum-supported formula, exact committed baseline, exact failed high-water, exact observed-unfailed `LATEST + retry_staging=true`, conflict, replay, and semantic-version irrelevance.
2. RT6 RED state tests prove one-shot `ADMIT_AUTHORITY` writes only exact IDLE authority/evidence state and creates no transaction/incoming directory.
3. RT6 RED coordinator/stage/pending tests prove admission is durably accepted before the first `stage()` call, local identity is refreshed afterward, fresh policy resolves exact admitted authority as `LATEST + retry_staging=true` with committed-vs-remote changed components intact, stage continues rather than early-returning, and pending verification requires exact admitted payload binding.
4. RT6 RED stage-failure/restart scenario proves committed N + `highwater=observed=N+1` survive with `failed!=N+1`, no pending, non-bricking discovery outage, then exact N+1 retry succeeds after network return.
5. RT6 RED session tests prove admission-only completion never calls activation; direct-online `prepare()` fails closed before resolver/spawner/downloader/state mutation; production-style E2E uses durable pending + `prepare_pending(...)` only.
6. Existing BEGIN/APPLY and candidate-specific package/hash/self-test failure behavior remains regression-tested; RT6 does not repurpose PREPARING abort semantics.
7. Each owning RT task runs complete RED before implementation, exact GREEN/regressions/Ruff/diff-check, atomic commit, and independent C0/I0 review.

**Review focus:** authority is durable before artifact transfer; admission-only helper completion cannot activate; direct-online apply cannot bypass durable pending; mandatory formula uses committed not high-water; no replay hole; no fake pending; no stage-failure path enters PREPARING.
**Acceptance:** C0/I0.

---

## Task 4 — Offline Baseline Enrollment From Exact Embedded Signed Envelope

**Goal:** Make fresh v5.1.2 establish trusted committed baseline offline from the exact production-signed envelope and exact installed component identities.

**Files:**

- Create: `launcher/src/neko_launcher/bootstrap/baseline_enrollment.py`
- Modify: `launcher/src/neko_launcher/updater/enrollment.py` only to expose/reuse the existing enrollment primitive required by the orchestrator; do not change transition semantics.
- **Do not modify:** `launcher/src/neko_launcher/updater/state_machine.py`. If RED tests prove the existing enrollment transition cannot represent the approved signed-baseline enrollment contract, STOP with `BASELINE_ENROLLMENT_CONTRACT_BLOCKED` and revise the plan before any state-machine contract change.
- Modify: `launcher/src/neko_launcher/main.py` to add the fixed internal `--enroll-baseline` mode defined by RT8; it accepts no sequence/release/key/channel/path trust arguments.
- Modify: `installer/beta.iss` to install the fixed baseline envelope **and exact signed trust profile** at their fixed paths, then invoke `{app}\NekoLauncher.exe --enroll-baseline` before optional normal launch.
- Modify: `installer/scripts/build_beta_installer.py`
- Tests: create `launcher/tests/test_baseline_enrollment.py`; modify `launcher/tests/updater/test_enrollment.py`, `launcher/tests/test_build_beta_installer.py`, and `launcher/tests/test_main.py`.

**Target orchestrator:** `enroll_baseline_from_signed_envelope(*, install_root: Path, envelope_path: Path, trust_profile: VerifiedUpdateTrustProfile) -> BaselineEnrollmentResult`, where the result contains `enrolled: bool`, exact `binding: AuthenticatedReleaseBinding | None`, and `error: str | None`. No raw key mapping is accepted; sequence/release_id are never independent unsigned inputs. Enrollment writes exact `profile_id/profile_envelope_sha256/keyset_sha256` pins from the same verified profile.

The orchestrator must verify envelope signature/channel/protocol, hash installed Launcher and Updater, verify canonical Core installed identity, construct committed/high-water/observed binding from the signed payload, and complete enrollment through existing durable enrollment/state primitives. It must be idempotent when the exact baseline is already enrolled and fail closed on any conflicting state/binding.

**Installer contract:** the builder requires build-time inputs `--baseline-envelope <path>` and `--trust-profile <path>`, verifies the trust profile under the approved Profile Authority public root, copies exact bytes to staging paths `baseline\release-v2.json` and `trust\update-profile-v1.json`, and records both SHAs + profile/keyset binding. Inno installs them as `{app}\baseline\release-v2.json` and `{app}\trust\update-profile-v1.json`, then invokes exactly `{app}\NekoLauncher.exe --enroll-baseline`. That internal launcher mode accepts no arbitrary envelope/profile/trust/sequence/release/path arguments and reads only the two fixed installed paths. The embedded baseline envelope must equal machine-channel evidence; the embedded production profile must equal canonical profile custody.

**TDD steps:**

1. RED: valid signed envelope + exact installed component fixtures enroll offline with no network object available.
2. RED: altered envelope signature, wrong launcher/updater/core identity, wrong channel/protocol, same-sequence conflicting preexisting state, malformed envelope all fail closed.
3. RED: exact rerun is idempotent.
4. RED: no unsigned sequence/release_id input is accepted by the enrollment API.
5. RED installer-build test proves **both** the baseline envelope and signed trust profile are mandatory build inputs; both exact SHAs plus profile/keyset binding enter the build record, and one-byte drift in either input fails closed.
6. Implement minimal orchestrator using existing enrollment/state models; preserve state-machine monotonicity.
7. Wire installer bootstrap without adding a network prerequisite.
8. GREEN + enrollment/state-machine regression.

**Review focus:** first trust establishment, idempotence, durable state correctness, no unsigned bootstrap.
**Escalation candidate:** Sol high only for unresolved enrollment state-transition correctness.
**Acceptance:** C0/I0.

---

## Task 5 — Fix Core Post-Install Verifier Against the Real Manifest Schema

**Goal:** Remove the proven exit-code-6 release blocker.

**Files:**

- Modify: `installer/scripts/verify-core-install.ps1`
- Create: `launcher/tests/test_verify_core_install_script.py`; generate the Core tree and array-schema manifest under pytest `tmp_path`.
- Modify: `launcher/tests/test_build_beta_installer.py` so Core-verifier success is a required installer qualification assertion.

**Real schema:**

```json
{
  "source_commit": "...",
  "files": [
    {"path": "...", "size": 123, "sha256": "..."}
  ]
}
```

**TDD steps:**

1. RED functional test invokes Windows PowerShell on a temporary Core tree using the real array schema and proves current script exits 6.
2. Add RED cases for wrong source authority, missing file, wrong size, wrong hash, duplicate/unsafe path, zero files, v2ray mismatch, missing nkps, plaintext key/settings.
3. Modify PowerShell to require array entries with exact allowed fields/types, normalize only safe relative paths, verify both size and SHA-256, and find the v2ray declaration by `path` rather than `.PSObject.Properties`.
4. GREEN:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_verify_core_install_script.py -q
```

5. Run the fixed script against the known local historical v5.1.2 payload path recorded by the audit; expected outcome is exit 0 for those valid Core bytes. If that local evidence path is absent at execution, STOP the regression-evidence step and record `HISTORICAL_PAYLOAD_EVIDENCE_MISSING` rather than silently skipping it.
6. Commit/review.

**Review focus:** PowerShell schema strictness/path safety, exact real-schema compatibility.
**Acceptance:** C0/I0.

---

## Task 6 — Production Sequence Authority Ledger Tooling

**Goal:** Make production sequence allocation durable and non-reusable; never derive release sequence solely from semantic version.

**Files:**

- Create: `scripts/production_sequence_ledger.py`
- Create: `scripts/authenticated_production_history.py`
- Modify: `scripts/derive_version.py`
- Modify: `scripts/release_controller.py`
- Modify: `release_target.json` to the exact semantic-intent-only schema `{source_base, target, intent}`; remove `seq`, `stable_id`, `installer_repo`, and the ambiguous legacy field name `stable`. `source_base` means only the accepted Launcher/Updater source-build compatibility base (currently `v5.1.1`); it is neither the Human/public stable version (`v5.1.0`) nor a Core-authority selector. Core authority is resolved exclusively from explicit verified Core-authority custody.
- Modify: `scripts/kanban_release_adapter.py` so successful Main Source Acceptance can report `CONTROLLER_RELEASE_REQUIRED` but cannot create a Hermes release worker/task or embed/invoke `release_controller.py` for authority-changing work.
- Add: `launcher/tests/test_production_sequence_ledger.py`
- Modify existing: `tests/test_release_controller_split.py`, `tests/test_derive_version.py`, and `tests/test_release_intent.py`; do not create duplicate derive-version/controller test files under `launcher/tests`.

**Important:** Source code must accept an explicit external ledger path. Do not hard-code the authoritative ledger inside the canonical repo or retiring repo. Tests use `tmp_path`.

**Record shape:** production ledger record 1 is one immutable historical genesis; all later records are lifecycle events.

```python
@dataclass(frozen=True)
class SequenceLedgerGenesis:
    record_type: Literal["GENESIS"]
    floor_binding: AuthenticatedProductionBinding
    floor_provenance_source_commit: str | None
    timestamp: str
    previous_entry_sha256: None

@dataclass(frozen=True)
class SequenceLedgerEvent:
    record_type: Literal["EVENT"]
    sequence: int
    release_id: str
    status: str                 # RESERVED, SIGNED, PUBLISHED, RETIRED, FAILED
    version: str
    channel: str
    source_commit: str
    component_set_sha256: str
    payload_sha256: str | None
    envelope_sha256: str | None
    key_id: str | None
    timestamp: str
    previous_entry_sha256: str
```

**Authenticated-history authority model:**

```python
@dataclass(frozen=True)
class AuthenticatedProductionBinding:
    sequence: int
    release_id: str
    payload_sha256: str
    envelope_sha256: str
    key_id: str

@dataclass(frozen=True)
class AuthenticatedHistorySnapshot:
    bindings_by_sequence: Mapping[int, AuthenticatedProductionBinding]
    provenance_source_commit_by_sequence: Mapping[int, str]
    live_updates_sequences: frozenset[int]
    highest_authenticated_sequence: int
    authenticated_bindings_sha256: str
    snapshot_sha256: str

@dataclass(frozen=True)
class ReconciledSequenceAuthority:
    authenticated_bindings_sha256: str
    history_snapshot_sha256: str
    genesis_floor_sequence: int
    latest_ledger_entry_sha256: str
    highest_authenticated_sequence: int
    highest_consumed_sequence: int
    next_unused_sequence: int
```

RA1 exposes a Windows-locked `SequenceAuthoritySession` as the serialization authority. Because signed seq7 predates this ledger, RA2 first bootstraps exactly one immutable genesis from fresh canonical seq7 custody under that same lock; it never fabricates historical lifecycle events. RA2 defines `AuthenticatedHistoryProvider.load() -> AuthenticatedHistorySnapshot`, whose load performs a fresh cryptographic enumeration each call and distinguishes canonical custody records from exact live Updates records. Cryptographic binding is limited to fields actually carried by verified release-v2: sequence/release_id/payload/envelope/key plus signed payload/component content. `source_commit` remains controller/build provenance and is never invented from a public envelope; corroborated custody provenance is stored separately. `authenticated_bindings_sha256` hashes only verified signed bindings, while snapshot digest also binds source/provenance claims. `live_updates_sequences` can be set only by verified live production Updates enumeration; custody alone never proves publication. No authority-changing API accepts a prebuilt snapshot. `RESERVED` requires genesis and fresh reconciliation inside the lock. RA4 signs, atomically custodies the exact envelope, fresh-reconciles, and appends `SIGNED` under the same lock; crash-after-custody recovery completes only the missing `SIGNED` append without re-signing. RA5 fresh-reconciles before publication and supports exact live-public crash recovery by read-only verification plus missing `PUBLISHED` append, never duplicate promotion. Newer/conflicting authority or provenance disagreement hard-stops; there is no silent retry.

**Required semantics:**

- verify exactly one immutable genesis plus the full hash chain before reading latest consumption;
- the genesis floor must remain present/cryptographically identical in every fresh authenticated-history load; missing/rebound floor fails closed;
- signed authorities at/below the genesis floor are pre-ledger history and do not receive fabricated lifecycle events; every authenticated authority above the floor requires a ledger allocation or an exact bounded recovery state;
- append-only **event lifecycle** per post-genesis sequence; never edit an earlier event;
- the first event for sequence N is the allocation event `RESERVED`; that event consumes N permanently;
- legal same-sequence lifecycle is exact: `START -> RESERVED`; `RESERVED -> SIGNED | FAILED`; `SIGNED -> PUBLISHED | FAILED`; `PUBLISHED -> RETIRED`; `FAILED` and `RETIRED` are terminal; no other transition is valid;
- every event for sequence N must preserve immutable allocation fields `sequence`, `release_id`, `version`, `channel`, `source_commit`, and `component_set_sha256` from the first `RESERVED` event;
- once `SIGNED` exists, `payload_sha256`, `envelope_sha256`, and `key_id` become immutable for all later events for that sequence;
- reject a second allocation of an already consumed sequence, any illegal status transition, transition back to `RESERVED`, changed allocation binding, or payload/envelope/key rebinding;
- next-unused = `max(reconciled.genesis_floor_sequence, reconciled.highest_authenticated_sequence, reconciled.highest_consumed_sequence)+1`; no allocator accepts a bare highest-authenticated integer;
- a reserved sequence remains consumed if build/signing/publishing later fails; it is never made available again;
- ledger/history disagreement returns explicit reconciliation-required failure;
- `release_target.json` cannot override ledger allocation/binding truth.

**TDD steps:** RED one-time exact seq7 genesis, mutated/second/missing genesis, valid `RESERVED -> SIGNED -> PUBLISHED`, signed-before-ledger-append recovery, published-before-ledger-append recovery, authenticated above-floor authority without allocation, reserved-then-failed consumption, tampered chain, second allocation, illegal transition, changed ledger release_id/version/channel/source_commit, payload/envelope/key rebinding after `SIGNED`, transition back to `RESERVED`, authenticated-history higher/lower cases, cryptographic divergence, separate custody-provenance mismatch, custody-vs-live source-kind enforcement, concurrent/stale append guard. Implement minimal atomic genesis/event append + custody index update with Windows locking/fsync/readback. Run focused tests + release controller tests + Ruff. Commit/review.

**Review focus:** append-only guarantees, race/stale write handling, no semantic-version reuse.
**Escalation candidate:** Sol high if concurrency/custody semantics remain disputed after normal review.
**Acceptance:** C0/I0.

---

## Task 7 — Release Build/Signing Boundary and Correct Build Order

**Goal:** Refactor release tooling so components + signed production trust profile are frozen first, sequence is reserved, canonical metadata is generated, controller signing returns one detached production signature, the accepted RT1 shared `release-v2` assembler constructs/re-verifies one exact envelope, then the final Installer embeds that envelope plus the frozen trust profile. Remove obsolete split-publish coupling and secret-unsafe verification.

**Files:**

- Modify: `scripts/release_controller.py`
- Modify: `scripts/build_software_release_v2.py`
- Modify: `scripts/sign_software_release.py`
- Reuse unchanged from accepted RT1/K1: `scripts/assemble_release_v2_envelope.py`; production and proof envelope construction share this one canonical path.
- Modify: `scripts/publish_atomic_release.py` (becomes machine-channel publisher for `Neko-Family-Proxy-Updates`)
- Rename/rework later Human publisher in Task 13; remove coupling here.
- Modify: `installer/scripts/build_beta_installer.py`
- Modify: `release_target.json`
- Tests: existing `tests/test_release_controller_split.py`, `launcher/tests/test_build_software_release_v2.py`, `launcher/tests/test_sign_software_release.py`, `launcher/tests/test_assemble_release_v2_envelope.py`, `launcher/tests/test_publish_atomic_release.py`, and `launcher/tests/test_build_beta_installer.py`.

**Pipeline API direction:** executable RA3 is the sole producer of `ArtifactIdentity`, `FinalComponentSet`, and `UnsignedBaselineEvidence`; executable RA4 is the sole producer of `SignedBaselineEvidence`. RA6/RT8 consume `SignedBaselineEvidence` for exact Installer embedding/provenance, and the later controller CR3/R4 gates use the same accepted interface.

```python
@dataclass(frozen=True)
class CoreAuthorityBinding:
    authority_version_tag: str
    authority_release_sequence: int
    authority_release_id: str
    authority_payload_sha256: str
    authority_envelope_sha256: str
    authority_key_id: str
    core_source_commit: str
    provenance_sha256: str

@dataclass(frozen=True)
class TrustProfileBinding:
    profile_id: str
    channel: str
    owner: str
    repository: str
    profile_authority_key_id: str
    profile_authority_public_key_sha256: str
    profile_envelope_sha256: str
    keyset_sha256: str

@dataclass(frozen=True)
class FinalComponentSet:
    source_commit: str
    launcher: ArtifactIdentity
    updater: ArtifactIdentity
    core: ArtifactIdentity
    core_authority: CoreAuthorityBinding
    trust_profile: TrustProfileBinding
    component_set_sha256: str

@dataclass(frozen=True)
class SignedBaselineEvidence:
    sequence: int
    release_id: str
    component_set_sha256: str
    payload_sha256: str
    envelope_sha256: str
    key_id: str
    envelope_path: Path
```

Build controller must stop at a `SIGNING_REQUIRED` boundary when running under Hermes/test implementation. Actual production signing is a later controller release operation. The production signer returns only `DetachedReleaseSignature(key_id, signature)`; `release_controller.py` passes that detached signature + exact canonical payload + accepted production public registry to the unchanged RT1 `assemble_verified_release_v2_envelope(...)`, then trusts only the re-verified envelope result. A production signer or helper that serializes an envelope itself is out of contract.

**Signing security requirements:**

- production private key content is never returned/logged;
- remove traceback/environment-key dumping from `sign_software_release.py`;
- do not accept inline private key material;
- implementation tests use generated test keys/injected signer, never production private key;
- actual production signer is controller-only and returns detached signature only; it never owns envelope serialization;
- production controller public-key composition is the exact accepted production registry only (`neko-update-prod-1` currently); mixed prod+proof registry or Proof Release Authority key fails before signer invocation;
- `assemble_release_v2_envelope.py` remains the sole proof/production envelope serializer/verifier path.

**Hosted asset verification security:** use one exact mechanism: parent Python runs `gh api repos/{owner}/{repo}/releases/assets/{asset_id} -H "Accept: application/octet-stream"` as an argv array with stdout connected directly to a parent-opened temporary file. No `gh auth token`, curl, bearer argv, shell redirection, or credential-bearing environment dump is permitted. Parent flushes/fsyncs/closes, computes exact size/SHA-256, validates identity, records evidence, then removes the temp file unless another custody contract owns it. Tests capture argv and enforce this exact path.

**TDD steps:**

1. RED pipeline-order tests prove Installer cannot build before exact signed envelope is supplied and the machine envelope is the same bytes embedded in Installer.
2. RED metadata tests prove `minimum_supported_sequence == baseline sequence`, sequence/release_id come from ledger reservation, and no `seq=6` target config can override it.
3. RED security tests reject token-bearing child argv and environment-key/traceback secret leakage.
4. RED tests prove machine publisher targets `Neko-Family-Proxy-Updates`, not main Human repo.
5. Implement refactor with injected command executor + detached-signer boundary while reusing the accepted shared release assembler unchanged.
6. GREEN + release tooling regression; no real signing/public commands executed.
7. Commit/review.

**Review focus:** key custody, detached-signature-only production signer, exact production registry, single shared proof/production envelope assembler, deterministic ordering, exact envelope reuse, no hidden public mutation, no token argv.
**Acceptance:** C0/I0.

---

## Task 8 — Final Installer Embeds Exact Signed Envelope and Records Provenance

**Goal:** Make final Installer contain exact component set + exact signed baseline authority, with verifiable 5.1.2 metadata/title/package identity.

**Dependencies:** Tasks 4, 5, 7.

**Files:**

- Modify: `installer/beta.iss`
- Modify: `installer/scripts/build_beta_installer.py`
- Modify Installer build tests.
- Modify release build-record generation in `scripts/release_controller.py` only through interfaces established in Task 7.

**Build record must include:** source SHA; injected version files/values; Launcher/Updater/Core hashes/sizes/installed identities; complete frozen `TrustProfileBinding` (profile id/channel/repo, Profile Authority key/root SHA, profile-envelope SHA, keyset SHA); sequence/release_id/key_id; signed payload SHA; exact envelope SHA; exact embedded envelope SHA; exact embedded trust-profile SHA; installer SHA/size; Core authority. Any mismatch between embedded profile and frozen `FinalComponentSet.trust_profile` fails before ISCC.

**TDD steps:**

1. RED: build gate refuses a missing baseline envelope **or** missing signed trust profile.
2. RED: envelope signature/component identities and verified trust-profile binding must match the exact staged Launcher/Updater/Core + frozen `FinalComponentSet.trust_profile` before ISCC starts.
3. RED: a one-byte-different embedded envelope **or trust profile** fails provenance/binding checks.
4. RED: package/version/title build inputs resolve to `5.1.2` and no `5.1.1` package identity remains in built metadata inputs.
5. Implement exact envelope **and frozen signed trust-profile** copy into payload + installer file list; pass no unsigned sequence/release_id or runtime trust/profile selector to installer.
6. Build a test candidate with test-signed envelope + test-signed profile; inspect staged installer payload/provenance and require exact recorded/embedded SHAs and profile binding.
7. Run PowerShell verifier tests from Task 5.
8. Commit/review.

**Acceptance:** C0/I0.

---

## Task 9 — Proof/Production Mechanical Equivalence Verifier

**Goal:** Mechanically prove proof and production binaries differ only in the explicit profile allowlist, with first-generation `NekoUpdater.exe` byte-identical.

**Files:**

- Create: `scripts/verify_build_equivalence.py`
- Add: `launcher/tests/test_verify_build_equivalence.py`
- Modify: `scripts/release_controller.py` build-record/profile evidence generation through Task 7 interfaces so it emits deterministic production/proof inventory inputs and the explicit profile-difference allowlist digest consumed by `verify_build_equivalence.py`.

**Evidence model:**

```python
@dataclass(frozen=True)
class ContentInventoryEntry:
    logical_path: str
    sha256: str
    size: int
    classification: str
```

The verifier must inspect packaged/extracted contents with one deterministic method, compare both builds, and permit differences only for explicit generated profile resources (endpoint/channel/trust-profile/profile-id). Any code/module/resource outside the allowlist must have identical hash.

Hard invariant:

```text
sha256(proof_baseline/NekoUpdater.exe)
==
sha256(production_candidate/NekoUpdater.exe)
```

**TDD steps:** RED identical builds pass, allowed profile file diff passes, code/module diff fails, extra/missing file fails, changed updater byte fails, unlisted trust resource fails. Implement deterministic inventory/canonical evidence JSON. Run tests/Ruff/diff-check. Commit/review.

**Review focus:** allowlist minimality; ensure test/proof behavior cannot diverge invisibly.
**Acceptance:** C0/I0.

---

## Task 10 — Packaged 5.1.2 → Isolated 5.1.3-Proof E2E Harness

**Goal:** Prove the actual final accepted baseline updater logic and exact same-source/same-toolchain baseline Updater helper can perform the mandatory update lifecycle and recovery. K1 Step 10/11 synthetic component fixtures are feasibility-only and cannot satisfy this task.

**Files:**

- Create/extend: `launcher/tests/e2e/test_v512_to_v513_proof_e2e.py`
- Reuse/extend: `launcher/tests/e2e/test_deferred_pending_update_e2e.py`, `test_github_release_update_e2e.py`
- Reuse updater transaction/recovery test modules.
- Add proof-profile fixtures under tests only; do not add user-selectable proof switch to production runtime.

**Required packaged scenarios:**

1. fresh baseline offline enrollment from embedded proof-signed equivalent envelope;
2. baseline self-resolution as `LATEST / NO UPDATE`;
3. detect authenticated seq N+1 proof candidate;
4. mandatory because `remote.mandatory` and separate case because committed < minimum-supported;
5. authenticated-but-incomplete mandatory authority: RT6 one-shot helper `ADMIT_AUTHORITY` re-verifies and persists `highwater=observed=N+1` while state remains IDLE before `SoftwareUpdateStageService.stage()` downloads anything; network fails before pending, restart preserves exact retryable authority with `failed!=N+1` and no PREPARING transaction, discovery outage is non-bricking, network return retries exact N+1;
6. successful retry completes download/stage/signature/size/hash identity verification and durable pending survives process restart;
7. active game defers apply and is never force-terminated;
8. safe apply through exact baseline `NekoUpdater.exe`;
9. relaunch/probation/self-test/commit;
10. broken candidate rollback with committed N and high-water N+1 retained;
11. same-sequence exact binding no-op;
12. same-sequence conflicting binding fail-closed;
13. lower-than-high-water reject;
14. crash injection around PREPARING/QUIESCING/PROBATION/CLEANING/ROLLING_BACK boundaries;
15. verified pending applies with discovery network disabled;
16. discovery outage without authenticated mandatory pending leaves committed app runnable.

**TDD/evidence steps:** after `RUNTIME_TRUST_C0_I0` and RA7, record the exact package-source SHA, freshly rebuild production-equivalent and proof-equivalent 5.1.2 baseline trees from that same source/toolchain using the accepted K1B-A profiles, mechanically require only `trust/update-profile-v1.json` to differ and baseline `NekoUpdater.exe` to be byte-identical, then sign proof baseline/candidate payloads from those freshly measured component identities using the K1A Proof Release Authority + immutable RT1 assembler. Add one scenario at a time, first make the harness assertion RED against current behavior, then implement only missing adapter behavior in the relevant already-reviewed task module. If a scenario exposes a defect in an accepted prior task, reopen that task and re-review it; do not patch the E2E test to hide the defect.

Run focused E2E then full updater suite:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/e2e/test_v512_to_v513_proof_e2e.py tests/e2e/test_deferred_pending_update_e2e.py tests/e2e/test_github_release_update_e2e.py -q
.venv\Scripts\python.exe -B -m pytest tests/updater -q
```

Generate machine-readable evidence with the exact fresh package-source SHA, full signed component objects, source/build/profile hashes, embedded signed proof-envelope bytes/bindings, and exact same-run production/proof Updater equality result; durable RA9 evidence must cryptographically cross-bind scenario authority state to those signed releases.

**Review focus:** packaged reality vs mocks; session safety; rollback/high-water; proof/production equivalence.
**Acceptance:** C0/I0.

---

## Task 11 — Dependency Audit Bound to Exact Source/Config/Tooling/Docs Snapshot

**Goal:** Implement deterministic audit/freshness tooling for retirement, with zero operational dependency on the old Installer repo.

**Files:**

- Create: `scripts/release_dependency_audit.py`
- Add: `launcher/tests/test_release_dependency_audit.py`
- Modify: `scripts/check_repository_safety.py`
- Modify: `launcher/tests/test_repository_safety.py`
- Later Task 14 updates current docs/source references so this audit passes.

**Audit output:**

```python
@dataclass(frozen=True)
class DependencyAuditEvidence:
    input_snapshot_sha256: str
    result_sha256: str
    approved_source_commit: str
    tracked_tree_sha256: str
    operational_matches: tuple[Finding, ...]
    historical_allowed_matches: tuple[Finding, ...]
```

The snapshot must bind the exact approved source tree plus production config, workflows, build/release tooling, installer scripts, normal-user docs, and any explicit external/generated inputs that can affect operational dependency detection.

Search direct and constructed references for:

- `Neko-Family-Proxy-Installer`;
- full owner/repo URL/API paths;
- split owner/repository constants that compose the old repo;
- release/upload/download configuration and documentation.

Historical superseded Superpowers docs may remain only under an explicit non-operational historical classification. Current docs/runtime/tooling references are blockers.

**TDD steps:** RED direct runtime ref, split constant ref, current-doc ref, generated config ref, clean snapshot, allowed historical-only ref, snapshot changed → `DEPENDENCY_AUDIT_STALE`. Implement canonical snapshot/result JSON and compare function. Run tests/repository-safety/Ruff. Commit/review.

**Acceptance:** C0/I0.

---

## Task 12 — Complete Installer-Repo Forensics, External Byte Custody, and Project Release-Audit Ledger Tooling

**Goal:** Build read-only capture/validation tooling and a separate append-only release-audit ledger. Do not execute live deletion.

**Files:**

- Create: `scripts/project_release_audit_ledger.py`
- Create: `scripts/capture_installer_repo_forensics.py`
- Add: `launcher/tests/test_project_release_audit_ledger.py`
- Add: `launcher/tests/test_installer_repo_forensics.py`

**Forensic capture contract:** deterministically capture repository numeric ID/node_id/owner/name/default branch/default-head/visibility/state plus ALL releases, ALL custom assets, ALL tags/peeled commits, and branch-head refs in scope. Produce repository/release/asset/ref digests and complete inventory digest.

**Custody contract:** RH3 implementation/tests accept an injected custody root and use only `tmp_path`; they must not write the real retirement-custody location. `ArtifactCustodyEvidence` records repository/release/asset identity, exact broken Installer bytes/hash, and a `known_broken_evidence_ref`/digest/status. The known-broken evidence binds **historical verifier bytes from the exact broken Installer source/build**, historical exit-6 output digest, exact historical Core payload digest, and source/build provenance—not the RT9-fixed current verifier. The real `E:\Github\artifacts\v512-retirement-custody` record is created only by controller G14 live forensics.

**Expected historical cross-check only:** size `212293271`, SHA-256 `e069aa2b268d134ca16d038bef58c176d237e01201e638c63e07f5832803e3f7`. The tool recomputes actual bytes and blocks on unexplained mismatch.

**Release-audit ledger events:**

- `RETIREMENT_EVIDENCE_READY` / `RETIREMENT_PRECONDITIONS_RECORDED` — evidence only, never DELETE authorization;
- `INSTALLER_REPOSITORY_DELETED` with `result=VERIFIED_DELETED` — actual destructive result, only controller appends after live post-delete verification.

**TDD steps:** RED pagination/completeness, missing page, mutable ordering canonicalization, duplicate asset/tag IDs, annotated/lightweight tags, immutable repo ID mismatch, custody hash mismatch, ledger tamper, append-only chain, event-schema distinction, and explicit test proving `RETIREMENT_EVIDENCE_READY` cannot be interpreted as executable deletion authorization. Implement with injected GitHub API executor; tests use fakes only. Commit/review.

**Acceptance:** C0/I0.

---

## Task 13 — Canonical Human Draft Publisher and Controller-Safety Validators

**Goal:** Replace obsolete separate-installer-repo publisher with canonical main-repo Human draft → validate → publish logic, while keeping actual tag mutation/delete/public promotion controller-only.

**Files:**

- Rename/rewrite: `scripts/publish_installer_release.py` → `scripts/publish_human_release.py`
- Rename/rewrite: `scripts/verify_installer_release_assets.py` → `scripts/verify_human_release_assets.py`
- Rename/rewrite: `launcher/tests/test_publish_installer_release.py` → `launcher/tests/test_publish_human_release.py`
- Rename/rewrite: `launcher/tests/test_verify_installer_release_assets.py` → `launcher/tests/test_verify_human_release_assets.py`
- Create: `scripts/retirement_predelete_check.py`
- Create: `launcher/tests/test_retirement_predelete_check.py`

**Human repository constants:**

```python
CANONICAL_HUMAN_REPO = "Valeneko-pranmong/Neko-Family-Proxy"
CANONICAL_MACHINE_REPO = "Valeneko-pranmong/Neko-Family-Proxy-Updates"
RETIRED_INSTALLER_REPO = "Valeneko-pranmong/Neko-Family-Proxy-Installer"
REQUIRED_HUMAN_ASSETS = ("NekoFamilyProxy-Installer.exe",)
```

**G23 API contract (tested with fake executor only):**

```text
G22 deletion-result ledger readback PASS
→ create v5.1.2 release with draft=true, prerelease=false
→ upload exact Installer
→ read back while draft
→ download/read remote asset through credential-hidden mechanism
→ verify remote SHA-256 + size + exact single asset set + body/tag/source
→ validation fail => STOP; never issue draft=false
→ validation PASS => issue draft=false
→ fresh public live-readback
```

No production command may call `gh auth token` or put bearer token in argv.

**Pre-delete validator contract:** current-session function consumes the latest forensic evidence + latest dependency audit + live freshly captured state and returns a structured PASS or exact blocker (`TARGET_IDENTITY_MISMATCH`, `FORENSIC_STATE_CHANGED`, `DEPENDENCY_AUDIT_STALE`, `TAG_AUTHORITY_BLOCKED`, etc.). It must not contain a DELETE command. The controller owns DELETE.

**TDD steps:** RED draft creation target, one-asset rule, wrong body, wrong tag/source, wrong remote size/hash, extra machine asset, failure path proves no `draft=false` command, success path permits promotion, post-publish readback, no-token argv. RED pre-delete mismatch/freshness cases. Implement pure/injected-executor tooling. Commit/review.

**Review focus:** invalid draft can never publish; public/destructive boundary not delegated; no secret exposure.
**Acceptance:** C0/I0.

---

## Task 14 — Remove Operational Old-Installer-Repo Dependencies and Update Current Documentation

**Goal:** Make the bound dependency audit pass while preserving historical evidence as explicitly historical.

**Files expected to change:**

- `release_target.json`
- `scripts/release_controller.py`
- `scripts/publish_atomic_release.py`
- new Human publisher/verifier from Task 13
- `.github/workflows/release.yml` and related release workflows if they encode old topology
- `docs/current/runtime-distribution.md`
- `docs/current/README.md`
- `docs/README.md`
- `docs/HANDOFF.md`, `docs/PROJECT_CONTEXT.md`; root `README.md` and `SECURITY.md` are absent from the current tracked tree and are not baseline task paths
- repository safety tests/allowlist configuration.

Historical `docs/superpowers/specs/**` and `docs/superpowers/plans/**` may mention the old repo as historical context but must not be treated as current operational instructions. Add explicit superseded markers where ambiguity could cause an operator/tool to follow them.

**TDD steps:**

1. Run dependency audit RED and capture all operational findings.
2. Fix one category at a time: runtime/config → workflows/tooling → current docs → normal-user docs.
3. Re-run audit after each category; do not blanket-ignore paths.
4. Add tests proving old repo references in current operational surfaces fail the audit while explicitly historical Superpowers docs are classified, not silently ignored.
5. GREEN repository-safety + dependency audit + docs checks.
6. Commit/review.

**Acceptance:** zero operational dependency findings, reviewer C0/I0.

---

## Task 15 — Full Source/Build Acceptance and Final Independent Review

**Dependencies:** Tasks 1–14.

**Goal:** Produce one exact implementation HEAD with complete source/test/evidence acceptance. This is still not a release.

**Steps:**

1. Run full Launcher tests:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=short
.venv\Scripts\ruff.exe check src tests
```

2. Run repository/release tooling tests and safety checks:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B scripts\check_repository_safety.py
git diff --check
```

3. Re-verify immutable K1 + packaged proof acceptance from their tracked expected digests before any final E2E/review. External custody is mutable storage and current-path verifier code could drift after its owning acceptance, so prior RT10/RA10 PASS alone is not fresh authority. Run the Git-only RT1 and RA9 source immutability guards **before** invoking either verifier:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-k1-acceptance.json'; paths=[r'scripts/build_update_trust_profile.py',r'scripts/assemble_release_v2_envelope.py',r'scripts/verify_v512_k1_acceptance.py',r'launcher/src/neko_launcher/updater/trust.py',r'launcher/src/neko_launcher/updater/trust_profile.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('K1 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['rt1_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RT1 security paths changed after accepted RT1_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RT1_SECURITY_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B scripts\verify_v512_k1_acceptance.py --repo-root . --acceptance-record docs\superpowers\evidence\v512-k1-acceptance.json --evidence docs\superpowers\evidence\v512-updater-trust-feasibility.md --k1b-custody E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json --require-git-immutability
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-ra9-proof-acceptance.json'; paths=[r'scripts/verify_v512_proof_evidence.py',r'launcher/tests/e2e/test_v512_to_v513_proof_e2e.py',r'launcher/tests/test_verify_v512_proof_evidence.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('RA9 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['ra9_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RA9 evidence paths changed after accepted RA9_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RA9_EVIDENCE_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B scripts\verify_v512_proof_evidence.py --repo-root . --acceptance-record docs\superpowers\evidence\v512-ra9-proof-acceptance.json --evidence E:\Github\artifacts\v512-release-proof-evidence\v512-v513-proof-evidence.json --k1-acceptance-record docs\superpowers\evidence\v512-k1-acceptance.json --k1b-custody E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json
```

Any K1/RA9 record-history, digest, authority/public-key/keyset, profile, artifact, embedded proof-envelope signature, scenario-evidence digest, envelope-reference coverage, or custody mismatch blocks Task 15; do not reconstruct expected digests or trust registries from current files.
4. Run proof/production equivalence tests and full deterministic packaged E2E in a disposable environment. Record actual counts and hashes; never copy expected counts from this plan.
5. Run a test-signed final Installer build through Core verifier and offline baseline enrollment. No production signing/public mutation.
6. Capture exact `BASE_SHA`, `HEAD_SHA`, tree hash, test commands/results, build/profile/equivalence evidence, `RT1_CODE_HEAD`, `K1_ACCEPTANCE_COMMIT`, `K1B_CUSTODY_SHA256`, `RA9_CODE_HEAD`, immutable RA9 acceptance-record introduction commit, and accepted `proof_evidence_sha256`.
7. Independent final review by `ag/gemini-pro-agent` against the approved Revision 3.4 spec, this plan, `BASE_SHA..HEAD_SHA`, immutable K1/RA9 acceptance records, and the freshly verified external-custody digests.
8. Critical >0 or Important >0 returns the branch to remediation and re-review; no merge while findings remain.
9. Only after C0/I0, mark source state `IMPLEMENTATION_C0_I0 / READY_FOR_OWNER_SOURCE_ACCEPTANCE`.

**Stop gate:** implementation completion does **not** authorize merge/public release. Owner/controller decides the next execution step.

---

# Independent Final Plan Review Handoff Contract

This gate reviews the **plan pack itself before P0**. It is separate from later implementation/task reviews and cannot be replaced by controller self-review. The required reviewer is exactly `ag/gemini-pro-agent`; Codex, Claude, Sol, controller self-review, or another model may provide supplemental findings but **cannot satisfy this gate**. Reviewer identity is trusted only from connector/tool invocation metadata that independently reports the **resolved model**; `reviewer_model` text inside the reviewer's own response is a cross-check, never the identity trust root. If the connector cannot attest `resolved_model == "ag/gemini-pro-agent"` independently of response content, this gate cannot PASS.

**Review target set:** exactly these five repository files, plus read-only source inspection only when needed to validate a concrete plan/source/API claim:

1. `docs/superpowers/specs/2026-09-13-neko-family-5-1-2-baseline-forced-update-revision-3-4.md`
2. `docs/superpowers/plans/2026-09-13-neko-family-5-1-2-baseline-release-implementation.md`
3. `docs/superpowers/plans/2026-09-13-v512-runtime-trust-enrollment.md`
4. `docs/superpowers/plans/2026-09-13-v512-release-authority-proof.md`
5. `docs/superpowers/plans/2026-09-13-v512-retirement-human-promotion.md`

Before dispatch, controller must fresh-compute SHA-256 for all five bytes, require Spec SHA exactly `2087863bad40ae1b75c5150c5c6e678a6e584ca96c23ccfc2d39819377e52b9c`, require Master status exactly `PLAN_REVISION_COMPLETE / READY_FOR_FINAL_PLAN_REVIEW`, require plan trailing-whitespace scan clean, run `git diff --check`, and require `git status --short` contains only the intentional plan/spec artifacts and no tracked source mutation. Controller renders the exact reviewer request—including the five path→SHA bindings, this review scope/focus, forbidden actions, and required `ReviewResponseV1` schema—as UTF-8 text with LF line endings and exactly one terminal LF, computes `review_request_sha256` **before writing**, creates deterministic immutable attempt root `E:\Github\artifacts\v512-final-plan-review\attempts\<review_request_sha256>`, and atomically writes/fsyncs/read-backs exact request bytes at `<attempt_root>\review-request-v1.txt`. A pre-existing attempt root is accepted only when every existing expected file is byte-identical to the same attempt; any mismatch is `FINAL_PLAN_REVIEW_ATTEMPT_COLLISION` and STOP. Symbolic labels such as “current plan” are insufficient.

Dispatch must use only a connector invocation that returns independent invocation metadata. Controller canonicalizes that metadata into sorted-key compact UTF-8 JSON + exactly one LF at `<attempt_root>\review-invocation-v1.json` with exact fields `schema_version=1`, `connector` (non-empty connector/tool identity), `requested_model="ag/gemini-pro-agent"`, `resolved_model="ag/gemini-pro-agent"`, `invocation_id` (non-empty connector-issued run/session identifier), `review_request_sha256`, and `reviewed_files` (the exact five-file map). Every value except `requested_model` and the reviewed/request hashes must come from connector-returned invocation metadata, not reviewer-authored response text. Missing/mutable/ambiguous invocation metadata or a resolved-model mismatch is `FINAL_PLAN_REVIEW_IDENTITY_UNATTESTED` and STOP; no verdict may be sealed. A completed attempt directory is immutable and never overwritten by a later review; remediation creates a new request hash/attempt root.

Reviewer receives the exact documents and a concise contract, **not this conversation history**. Review must adversarially trace Spec §§1–19 through the plans and inspect source read-only where a plan claims an existing API/schema/path. Required focus includes at least: release topology and machine/Human separation; sequence-ledger authority/crash recovery; Profile Authority/proof/production trust separation and exact profile byte contract; K1 feasibility vs final RA8/RA9 proof separation; immutable shared detached-envelope assembler; CoreAuthorityBinding and no Core/source-base conflation; final signed production reference vs proof equivalence; RA9 durable cryptographic evidence/state cross-binding; no secret/private-key leakage; controller/worker/Hermes boundaries; retirement G14–G24 ordering/current-session DELETE authority; executable command/ref semantics; and cross-pack DAG/prerequisite consistency.

Reviewer output must be exactly one `ReviewResponseV1` JSON object, not free-form prose. `ReviewFindingV1` has exact fields `severity` (`Critical` | `Important` | `Minor`), `file`, `section`, `failure_mode`, `violated_invariant`, and `recommendation`, all non-empty strings except the closed enum. `ReviewResponseV1` has exact fields `schema_version=1`, `reviewer_model="ag/gemini-pro-agent"`, `review_request_sha256`, `reviewed_files` (closed path→sha256 map for all five files), `findings` (list of `ReviewFindingV1`), `critical_count`, `important_count`, `minor_count`, and `verdict`. Counts must equal the findings list exactly; response `review_request_sha256` and `reviewed_files` must equal controller custody, and response `reviewer_model` must equal the connector-attested resolved model. `verdict="C0_I0_PASS"` only when Critical=0 and Important=0, otherwise `verdict="REMEDIATION_REQUIRED"`. Unknown/missing fields, request/hash-set mismatch, ambiguous counts, non-JSON output, or a prose-only “looks good” is not acceptance.

Controller validates the returned object against the independently attested invocation evidence, then serializes the accepted reviewer result as sorted-key compact UTF-8 JSON (`separators=(',', ':')`, `ensure_ascii=False`) plus exactly one terminal LF, with no BOM/CRLF/extra whitespace, and atomically writes/fsyncs/read-backs exact bytes at `<attempt_root>\review-response-v1.json`. Its SHA-256 is `review_response_sha256`; controller must reject a response whose embedded request hash, reviewed-files map, or model differs from the custodied request/invocation evidence. The request/invocation/response files for both PASS and REMEDIATION_REQUIRED attempts remain immutable audit evidence.

**Verdict custody:** after a genuine connector-attested `C0_I0_PASS`, controller creates **without editing any of the five reviewed files** canonical `docs/superpowers/evidence/v512-final-plan-review.json` as sorted-key compact UTF-8 JSON + exactly one LF with exact fields `schema_version=1`, `reviewer_model="ag/gemini-pro-agent"`, `reviewed_files` (the same closed five-file path→sha256 map), `critical_count=0`, `important_count=0`, `minor_count`, `verdict="C0_I0_PASS"`, `review_request_custody_path`, `review_request_sha256`, `review_invocation_custody_path`, `review_invocation_sha256`, `review_response_custody_path`, `review_response_sha256`, and `reviewed_at`. All three custody paths must resolve under exact deterministic `E:\Github\artifacts\v512-final-plan-review\attempts\<review_request_sha256>\` to `review-request-v1.txt`, `review-invocation-v1.json`, and `review-response-v1.json` respectively; path escaping or another attempt root fails. Re-read/hash all three external custody files before writing this record and require request→invocation→response bindings plus connector-attested resolved model exact. Fresh-read all five plan/spec files after writing the record and require their SHA values still equal the reviewed bindings. The external record—not a post-review edit to Master—is the durable proof that the exact READY plan bytes received C0/I0. P0/Owner execution approval must consume those reviewed hashes and all three custody digests; any later byte change to any reviewed file or accepted review custody file invalidates this record and requires a new independent review.

If reviewer returns any Critical/Important finding, do **not** create/pass the review record. Controller first changes Master status back to `PLAN_REVISION_IN_PROGRESS / FINAL_CROSS_PACK_REVIEW_ACTIVE`, remediates plan-only, reruns all integrity/stale/gate checks, returns to `READY_FOR_FINAL_PLAN_REVIEW`, computes a new five-file hash set, and requests a fresh independent review. Minor findings may remain recorded without byte edits; if any Minor is fixed by changing a reviewed file, the prior verdict/hash set is invalid and review must repeat.

This review gate performs **no P0 custody commit, no source implementation, no Hermes/Gateway action, no signing, no production sequence reservation, no public mutation, no repository deletion, and no Human Release**.

---

# Hermes Kanban DAG

After execution approval + P0 + K0, the controller performs K1A without Hermes. Materialize/dispatch **RT1 only** after K1A. Inside RT1, K1B-A seals profiles after the clean `RT1_CODE_HEAD`; package/candidate bytes are measured next; K1B-B then seals proof envelopes + `K1B_CUSTODY_SHA256`; materialize/unlock remaining RT/RA/RH cards only after reviewed packaged conformance **and** immutable `K1_ACCEPTANCE_COMMIT`:

```text
P0 Approved plan-pack + independent-review custody / docs-only branch commit
  → K0 Baseline / isolated worktree / baseline evidence
      → K1A Controller-only non-production authority bootstrap
           Profile Authority public/root custody
           + Proof Release Authority public custody
           NO profile sealing / production release signing / sequence allocation / GitHub mutation
          → RT1-A Signed-profile codec + both detached assemblers + runtime implementation + unit GREEN + commit `RT1_CODE_HEAD`
              → K1B-A Controller-only exact production/proof profile sealing
                   → RT1-B Build/measure baseline package trees + deterministic proof N+1 fixture
                       → K1B-B Controller-only proof-envelope sealing + `K1B_CUSTODY_SHA256`
                           detached signatures only; private keys remain controller-only
                           → RT1-C Packaged K1 conformance
                               ├─ FAIL = ARCHITECTURE_FEASIBILITY_REGRESSION → Owner architecture review; STOP RT2+/RA/RH
                               └─ PASS candidate = UPDATER_TRUST_FEASIBLE / C0_I0
                                    → controller seals + verifies immutable `v512-k1-acceptance.json` in `K1_ACCEPTANCE_COMMIT`
                                        ├─ Runtime workstream
                                        │    RT2 Exact binding model
                                        │      → RT3 Authenticated local identity reader
                                        │      → RT4 Production composition
                                        │      → RT5 Ordering + mandatory formula
                                        │      → RT6 Pre-stage durable authority admission + retry/outage semantics
                                        │      → RT7 Offline baseline enrollment
                                        │      → RT8 Installer envelope + trust-profile wiring
                                        │      → RT9 Core verifier
                                        │      → RT10 Runtime C0/I0 acceptance
                                        │
                                        ├─ Release authority workstream
                                        │    RA1 Sequence Authority Ledger + authenticated-history reconciliation
                                        │      → RA2 Reconciled ledger-backed release allocation
                                        │      → RA3 Exact component/trust-profile freeze + canonical baseline metadata producer
                                        │      → RA4 Controller-only detached-signing boundary + shared release assembler
                                        │      → RA5 Machine publisher / secret-safe hosted verification
                                        │
                                        └─ Retirement tooling workstream
                                             RH1 Dependency audit
                                             RH2 Project Release-Audit Ledger
                                             RH3 Complete forensics + external asset custody

RT10 + RA1..RA5
  → RA6 Final Installer signed-envelope provenance
  → RA7 Mechanical proof/production equivalence
  → RA8 Packaged mandatory-update happy path/session/offline pending
  → RA9 Rollback/replay/crash recovery proof
  → RA10 Release-authority/proof C0/I0 acceptance

RH1 + RH2 + RH3 + RA10
  → RH4 Current-session pre-delete validator
  → RH5 Canonical Human draft publisher
  → RH6 Remove operational old-repo dependencies/current-doc cleanup
  → RH7 Retirement/Human tooling C0/I0 acceptance

RT10 + RA10 + RH7
  → FINAL full-branch test/evidence review (master acceptance)
  → Owner source/merge decision
  → controller release stop gates only after separate authorization
```

Parallelism is allowed only for tasks with no shared mutable files and no dependency on an unaccepted contract. The controller integrates task commits in deterministic order. Hermes workers must not maintain competing long-lived integration branches.

# Per-Task Hermes Implementer/Reviewer Boundary

For every executable implementation task `RT1–RT9`, `RA1–RA9`, and `RH1–RH6` (workstream acceptance tasks are controller/reviewer checkpoints). `RT0/K1` is the approved plan-level architecture contract; `K1A` is controller-only public-authority bootstrap before RT1; `K1B-A` is controller-only profile sealing after clean `RT1_CODE_HEAD`; `K1B-B` is controller-only proof-envelope/custody-manifest sealing only after exact artifact identities are measured. **RT1 is the first and only implementation task allowed before K1 conformance acceptance**. RT2+, RA1+, and RH1+ require reviewed RT1 `UPDATER_TRUST_FEASIBLE / C0_I0`, exact `K1B_CUSTODY_SHA256`, immutable canonical `v512-k1-acceptance.json` in `K1_ACCEPTANCE_COMMIT`, the Git-only **RT1 security-tool immutability guard**, **and a fresh `scripts/verify_v512_k1_acceptance.py --require-git-immutability` PASS on the integration branch**:

- [ ] Controller records `TASK_BASE_SHA`.
- [ ] Dispatch implementer `ag/gemini-3.8-flash-high` with only the task scope, approved spec path, exact subplan task, required tests, forbidden operations, and expected evidence.
- [ ] Implementer follows RED→GREEN, commits one atomic task result, and returns test evidence + `TASK_HEAD_SHA`.
- [ ] Controller verifies working tree/state and runs the task’s required tests independently where practical.
- [ ] Dispatch a **different** `ag/gemini-pro-agent` reviewer with:

```text
Spec: docs/superpowers/specs/2026-09-13-neko-family-5-1-2-baseline-forced-update-revision-3-4.md
Plan task: <RTn | RAn | RHn>
BASE_SHA: <TASK_BASE_SHA>
HEAD_SHA: <TASK_HEAD_SHA>
Review for correctness, trust/security, regressions, scope compliance.
Required verdict: Critical count / Important count / Minor count.
```

- [ ] Critical/Important findings reopen the same task for remediation; implementer cannot self-approve.
- [ ] Only C0/I0 marks the Kanban task Done and unlocks dependents.

# Evidence Requirements By Class

## Source task evidence

- RED command + failure reason;
- GREEN focused tests;
- affected regression tests;
- Ruff result;
- `git diff --check`;
- commit SHA;
- independent C0/I0 review.

## Build/proof evidence

- source SHA/tree;
- build profile id and allowlisted profile differences;
- exact component hashes/sizes;
- signed-envelope/payload hashes (test/proof during implementation; production only in release phase);
- Installer hash/size;
- extracted equivalence inventory/diff report;
- exact `NekoUpdater.exe` equality result;
- packaged E2E scenario matrix/results;
- RA9 proof schema v1 has exact nested component/scenario/binding schemas; working bytes at `artifacts/evidence/v512-v513-proof-evidence.json` are copied byte-identically to `E:\Github\artifacts\v512-release-proof-evidence\v512-v513-proof-evidence.json`; after independent C0/I0 the controller seals the expected digest in immutable tracked `docs/superpowers/evidence/v512-ra9-proof-acceptance.json`, and RA10 validates custody against that pre-accepted digest rather than trusting a newly computed digest.

## Release/retirement evidence

Generated later by controller execution, never fabricated by implementation workers:

- production sequence ledger readback;
- production signed baseline evidence;
- production machine draft/public readbacks and exact asset hashes;
- production candidate live self-resolution;
- complete old-repo forensic snapshot/digests;
- exact broken Installer external custody bytes/hash/IDs;
- dependency-audit snapshot/result/freshness;
- `RETIREMENT_EVIDENCE_READY` release-audit entry;
- current-session G18/G19 fresh checks;
- actual DELETE result + post-delete verification;
- `INSTALLER_REPOSITORY_DELETED / VERIFIED_DELETED` ledger entry;
- Human draft validation evidence and final public readback.

# Release Stop Gates After Source Acceptance

These are **not implementation tasks**. They are controller-run gates after a separately approved implementation/merge/release phase.

## R0 — Owner source/merge authorization

No merge/public action until Owner accepts the implementation plan execution result and exact C0/I0 branch HEAD.

## R1 — Post-merge CI/source acceptance

Merge only accepted HEAD (or mechanically equivalent merge commit), rerun CI/tests/safety on main, bind final approved source SHA.

## R1A — Canonical production authority-history custody + ledger genesis bootstrap

Before any component freeze/reservation, controller re-reads and production-verifies the already-audited seq7 envelope at `E:\Github\artifacts\main-auto-release\34601286641-fb0d2e734ee611d75933ccd90cb82347c0b578bd\5.1.3\publish\release-v2.json`. Require exact `sequence=7`, `release_id=stable-0007`, `key_id=neko-update-prod-1`, payload SHA-256 `d62602d3b90ee0d6b251b6eee7d1aa3e1b5db591f1cd280f723bc011c12fed98`, envelope SHA-256 `a806be8e9f1308df1d4ab63e08b319112723a49b768bbb1a2af6189d5ee625c9`, size 1632, and provenance commit `fb0d2e734ee611d75933ccd90cb82347c0b578bd` present. Persist/read-back the exact envelope through canonical external custody `E:\Github\artifacts\v512-production-authority-custody` using the tested atomic/idempotent custody-index API. Then construct the production history provider, acquire the external Production Sequence Authority Ledger lock, fresh-load history, require the highest authenticated authority is still exactly seq7, and create/read-back exactly one immutable genesis anchored to that seq7 binding/provenance. If a ledger already exists, require exact genesis equality and never regenerate it. Hard-stop if historical evidence is absent/changed or a newer pre-ledger authority appears; never replace cryptographic history with a remembered `highest=7` scalar or fabricate historical lifecycle events. Future provider loads canonical custody plus fresh live Updates-channel authority.

## R2 — Freeze exact final production component set

First require the runtime plan's Git-only **RT1 security-tool immutability guard** to PASS, then require `scripts/verify_v512_k1_acceptance.py --require-git-immutability` to pass for canonical `v512-k1-acceptance.json` and exact `K1B_CUSTODY_SHA256`. Build exact Launcher/Updater from the approved final source SHA, using semantic `source_base` only for Launcher/Updater source-build compatibility; load the exact Core once from explicit controller-owned canonical Core-authority custody; and load/re-verify the exact **K1B-A production** `update-profile-v1.json` referenced by immutable K1 acceptance, all **before sequence allocation**. For Core, require historical `sequence=6 / release_id=stable-0006 / version=v5.1.2` RA3 custody expectations and never select/fetch Core through `source_base` or Human Release. For trust, require `profile_id=production`, `channel=stable`, owner/repository `Valeneko-pranmong/Neko-Family-Proxy-Updates`, exact Profile Authority key/root identity and profile/keyset SHAs pinned by accepted K1 record/manifest, and the approved production release keyset only. Record source SHA/tree, toolchain, all component identities, complete frozen `CoreAuthorityBinding`, and complete frozen `TrustProfileBinding`. Compute `component_set_sha256` over the entire typed set including both bindings. Do not re-resolve Core or replace/re-sign/select another production trust profile after this freeze. Any source/component/Core-authority/trust-profile change after `RESERVED` consumes that sequence and requires a new freeze/reservation. No Human Release yet.

## R3 — Fresh production sequence reconciliation and reservation

- Construct the production `AuthenticatedHistoryProvider` from canonical R1A custody records plus fresh live Updates-channel records; do not create/pass a prebuilt history snapshot as reservation authority and do not scan arbitrary artifact trees during reservation.
- Acquire the Production Sequence Authority Ledger serialization session first.
- **Inside that lock**, call `history_provider.load()` afresh, re-read/verify the exact R1A genesis + ledger, require the genesis floor binding remains present and identical, reconcile all cryptographically authenticated per-sequence `release_id/payload/envelope/key` bindings, and separately reconcile any available controller/custody `source_commit` provenance against post-genesis `RESERVED` provenance. A live public envelope with no source-commit provenance is valid and must not cause source provenance to be inferred. Then derive next-unused from genesis floor + authenticated history + consumed events, append/fsync/read-back `RESERVED` bound to the frozen R2 component set, and release.
- Newer/conflicting authenticated authority or lifecycle divergence hard-stops; there is no silent retry. Provisional seq8 is used only if still next-unused.
- If any component/source/component-set byte changes after `RESERVED`, that sequence remains permanently consumed; never reuse it.

## R4 — Fresh authority guard + controller production signing + `SIGNED`

Generate canonical metadata only from frozen R2 + R3 allocation without signing. Acquire the same ledger serialization session; inside it call `history_provider.load()` afresh and reconcile exact `RESERVED`. If exact canonical custody already contains the matching signed envelope from a prior crash and reconciliation returns `SIGNED_APPEND_REQUIRED`, verify it and append only the missing `SIGNED` record with zero signer invocation. Otherwise any newer/conflicting authority stops **before signer invocation**. For a new signature, while the session remains held first re-run the Git-only **RT1 security-tool immutability guard**; only on PASS may the controller production signer return `DetachedReleaseSignature`, after which pass exact canonical payload + detached signature + exact production public registry to immutable RT1 `assemble_verified_release_v2_envelope(...)`, trust only the re-verified envelope/key_id, atomically persist/read-back that exact envelope in canonical authority custody, fresh-load history again, require exact `SIGNED_APPEND_REQUIRED`, append/fsync/read-back `SIGNED`, then release. Hermes workers never receive private key material and no second envelope serializer is permitted.

## R5 — Final Installer build/qualification

Build final Installer containing the exact production-signed baseline envelope + exact components + the exact frozen **K1B-A production trust-profile bytes referenced by immutable K1 acceptance** from R2. Before ISCC, require embedded trust-profile SHA/profile id/keyset/Profile Authority binding to equal `FinalComponentSet.trust_profile`; one-byte profile drift, profile substitution, or a different validly signed profile fails qualification. Prove envelope hash equality, trust-profile hash equality, marker pin creation, version/title/package metadata 5.1.2, Core verifier exit 0, clean install, offline enrollment, uninstall/reinstall, and v5.1.0 uninstall→5.1.2 manual migration path. A transient qualification-infrastructure failure may retry only the exact signed candidate + exact frozen profile; if qualification proves the candidate requires any payload/component/Core-authority/trust-profile change, append/read-back same-sequence `FAILED`, keep the sequence consumed, and restart from R2 with a newly frozen set/new sequence.

## R6 — Proof/production equivalence and forced-update proof

Run the Git-only **RT1 security-tool immutability guard** and **RA9 proof-evidence immutability guard**, then fresh-reverify immutable K1/RA9 acceptance with the exact K1B custody chain. Those records are qualification/authority anchors only, not release-phase component sources. Use the exact R2/R4 frozen-and-production-signed Launcher/Updater/Core bytes as the production baseline reference; do not rebuild a substitute production reference after signing. Build the proof-equivalent 5.1.2 Launcher/Updater from the exact Owner-approved final source SHA with the identical dependency lock/PyInstaller specs/packaging code/toolchain recipe used by the signed production candidate, stage the exact same frozen Core bytes/CoreAuthorityBinding from R2 (Core is not rebuilt from the Launcher/Updater source commit), and use the exact **K1B-A proof profile referenced by K1 acceptance**. Mechanical equivalence permits exactly one trust/routing resource difference: `trust/update-profile-v1.json`; verify both profiles under the same accepted Profile Authority root, require production profile has no proof release key/fallback, proof profile has no production fallback, require the freshly measured proof Launcher/Updater/Core identities to equal the signed production component identities exactly, and require byte-identical baseline `NekoUpdater.exe` plus identical non-allowlisted code/module/resources. Build/measure the isolated 5.1.3-proof candidate against that proof baseline. Accepted proof baseline/candidate/auxiliary envelopes must sign only those fresh proof identities using detached K1A Proof Release Authority signatures + immutable RT1 shared assembler; K1 synthetic component fixtures and worker/fixture keys cannot become accepted release-phase evidence. Record fresh proof evidence with final source SHA, signed-production reference component objects, fresh proof component objects, exact signed proof-envelope bytes/bindings, CoreAuthorityBinding equality, scenario authority-state bindings, and exact Updater equality, then complete the packaged 5.1.2→5.1.3-proof matrix with proof enrollment pins bound to the proof profile. Any source/toolchain mismatch, production-reference rebuild/substitution, Core authority/byte drift, unexpected binary/module/resource difference, trust-domain crossover, stale K1/RA9 evidence, or proof-envelope/state-binding mismatch blocks release. If the production-signed baseline/frozen production profile itself requires a byte/authority/trust-profile change to resolve proof failure, append/read-back same-sequence `FAILED`; never reuse that signed sequence for corrected content.

## R7 — Independent release-candidate review

`ag/gemini-pro-agent` reviews exact production candidate evidence. Required C0/I0. Sol high may be used only if the controller explicitly escalates a genuinely complex unresolved issue.

## R8 — Production Updates repository readiness

If `Valeneko-pranmong/Neko-Family-Proxy-Updates` still does not exist, STOP for the separately authorized controller public-repository creation step. No worker creates it.

## R9 — Fresh authority guard + production machine publication + `PUBLISHED`

Acquire the same ledger serialization session **before any public promotion**, fresh-load authenticated history inside it, and reconcile exact `SIGNED`; newer/conflicting authority means zero publication. If the exact candidate is already verified specifically from the live Updates source while ledger remains `SIGNED`, treat it as `PUBLISHED_APPEND_REQUIRED`: perform read-only hosted asset/tag/target + production self-resolution verification and append only the missing `PUBLISHED` record with zero create/upload/promote commands. Otherwise keep the session held while promoting the exact four machine assets once and performing hosted/public byte verification + production self-resolution. Then fresh-load history again while still locked, require the exact binding in `live_updates_sequences` and no newer/conflicting authority, append/fsync/read-back `PUBLISHED`, then release. A transient retry requires a new fresh-guarded session and byte-identical candidate; crash-after-promotion recovery never repeats public mutation. Failure blocks all retirement/Human gates.

## R10 — G14a Complete old-repo forensic capture

Controller captures immutable repository ID/node_id/owner/name/default HEAD plus ALL releases/assets/tags/ref scope and canonical digests.

## R11 — G14b Exact broken Installer + historical-failure custody

Controller alone creates the real retirement custody. Custody exact old Installer bytes, materialize/hash the **historical** `verify-core-install.ps1` from the exact broken source/build (never the RT9-fixed current script), reproduce/validate historical exit 6 against exact historical Core payload evidence, hash normalized failure output, and bind those values in `KnownBrokenEvidenceV1`. Any Installer/verifier/failure/payload/provenance mismatch blocks.

## R12 — G14c/G14d Dependency + replacement audits

Run exact bound dependency audit and replacement-readiness check against final approved source/config/tooling/docs and live machine readiness. Any operational old-repo dependency blocks.

## R13 — G14e/G14f Retirement evidence ledger

Construct evidence package; append/read-back `RETIREMENT_EVIDENCE_READY`. This is evidence only and never DELETE authorization.

## R14 — G15 Mutation-free Human preflight

Prepare final bilingual body, exact Installer hash/size, expected one-asset set, permissions/API payload locally. Capture current canonical tag and validate exact intended mutation. **Do not create a draft Human Release and do not upload asset.**

## R15 — G16 Explicit Owner canonical tag mutation approval

Present exact current tag target, approved final SHA, and required mutation. Wait for explicit Owner approval for that exact tag action. The prior spec approval is not blanket tag-mutation permission.

## R16 — G17 Canonical tag action + live readback

Controller performs only the approved mutation and proves `refs/tags/v5.1.2^{commit} == approved final SHA`. Failure blocks DELETE.

## R17 — G18/G19 Current-session fresh DELETE authorization

In one controller-controlled execution session:

- fresh-capture complete old-repo immutable identity + release/asset/ref inventory;
- recompute inventory digests and require exact equality with latest forensic evidence;
- fresh-capture dependency-audit input snapshot and require equality with latest PASS snapshot;
- reverify replacement readiness, tag authority, ledger readback, and exact artifact custody.

Blockers include at least:

```text
TARGET_IDENTITY_MISMATCH
FORENSIC_STATE_CHANGED
DEPENDENCY_AUDIT_STALE
FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE
TAG_AUTHORITY_BLOCKED
RETIREMENT_BLOCKED
```

A stale/interrupted session invalidates G19 and requires fresh G18/G19.

## R18 — G20 Controller-only DELETE

Only the Project Controller issues deletion of `Valeneko-pranmong/Neko-Family-Proxy-Installer`, and only immediately after current-session G19 PASS. No Hermes worker/reviewer/AI coding worker receives this action.

## R19 — G21 Post-delete verification

Fresh-query GitHub and prove old repository/release/tag/asset namespace no longer acts as public authority. Rerun zero-operational-dependency verification. If live verification is unavailable, Human Release remains blocked.

## R20 — G22 Durable deletion-result custody

Append/read-back `INSTALLER_REPOSITORY_DELETED` / `VERIFIED_DELETED` to Project Release-Audit Ledger with pre-delete evidence, actual delete outcome, post-delete live verification digest, and dependency verification digest. Ledger failure blocks Human Release even if deletion succeeded.

## R21 — G23-A/B/C Human draft, upload, validate

Only after R20 PASS:

1. create canonical main-repo v5.1.2 as `draft=true`, `prerelease=false`;
2. upload exact qualified `NekoFamilyProxy-Installer.exe`;
3. while still draft, live-verify tag/source, approved bilingual body, exact one-asset set, remote size and SHA-256, and absence of machine assets.

Any validation failure STOPs; do not publish.

## R22 — G23-D/E Publish and public readback

Only on draft validation PASS set `draft=false`, then fresh-read public release and reverify complete Human contract plus old-repo unavailability.

## R23 — Production v5.1.3 remains blocked

No production v5.1.3 release without a new explicit Owner authorization, even after v5.1.2 succeeds.

# Controller-Only Operation Matrix

| Operation | Hermes implementer | Hermes reviewer | Project Controller |
|---|---:|---:|---:|
| Edit/test source | Yes, scoped | Review only | Orchestrates |
| Build test/proof artifact | Yes, scoped | Review evidence | Orchestrates |
| Read public GitHub state | Yes if task needs read-only fixture/evidence | Yes | Yes |
| Production private signing key access | **No** | **No** | Controlled boundary only |
| Create Updates/proof GitHub repo | **No** | **No** | Only at authorized release gate |
| Move/delete/recreate canonical v5.1.2 tag | **No** | **No** | Exact Owner-approved action only |
| Publish production machine release | **No** | **No** | Release gate only |
| Delete historical Installer repository | **No** | **No** | **Controller-only G20** |
| Create/upload Human v5.1.2 draft | **No** | **No** | After G22 only |
| Set Human draft=false | **No** | **No** | After draft validation PASS only |

# Plan Self-Review

## Spec coverage

Covered explicitly:

- Human/main vs machine/Updates topology;
- authenticated sequence custody and non-reuse;
- signed-envelope offline baseline enrollment;
- local committed/high-water/observed/failed identity reconstruction;
- exact ordering/mandatory/offline semantics;
- real Core manifest verifier fix;
- proof/production mechanical equivalence + byte-identical baseline Updater;
- full packaged mandatory-update proof/recovery;
- token/private-key safety;
- complete dependency-audit snapshot/freshness;
- complete repository/release/asset/ref forensics + exact broken Installer byte custody;
- separate Sequence vs Release-Audit ledgers;
- canonical tag Owner gate;
- current-session G19 freshness authority;
- controller-only repository deletion;
- durable deletion-result ledger before Human mutation;
- draft-first Human release validation before public promotion;
- bilingual one-installer Human presentation contract;
- production v5.1.3 remains separately blocked.

## Placeholder scan

No mandatory requirement is deferred behind an unspecified placeholder. GitHub repository creation, production signing, tag mutation, repository deletion, and public release publication are intentionally represented as explicit later controller stop gates because the current Owner authorization covers writing-plan only and the approved spec makes those controller/public actions distinct from source implementation.

## Interface consistency

- Runtime subplan defines one authenticated `LocalReleaseIdentity` carrying exact `committed`, `high_water`, `observed`, and optional `failed` bindings; `observed==high_water` plus failed equality distinguishes retryable authenticated-incomplete authority from known terminal failure.
- Release semantic intent separates `source_base` (current accepted Launcher/Updater source-build compatibility base `v5.1.1`) from the Human/manual-migration stable version `v5.1.0`; `source_base` never selects Core authority, which comes only from explicit verified Core-authority custody, and semantic version never allocates sequence authority.
- Main Source Acceptance cannot auto-dispatch a Hermes release worker into `release_controller.py`; it is only a readiness signal for later controller-owned authority gates.
- Final component freeze distinguishes Launcher/Updater source provenance from authenticated Core authority provenance **and** the separately signed production `TrustProfileBinding`; all three are bound into `component_set_sha256` before production sequence reservation.
- Baseline enrollment and local identity reader share one fixed Profile-Authority-verified trust profile, its immutable enrollment pins, and the same signed-envelope/updater-state authority rather than parallel key/config paths.
- Production/proof channel differences flow only through exact Profile-Authority-signed `trust/update-profile-v1.json` resources. Packaged helper code embeds the same Profile Authority public root and no production/proof release-key registry; `UpdateChannelProfile` is derived only from `VerifiedUpdateTrustProfile`.
- Production Sequence Authority Ledger and Project Release-Audit Ledger are separate modules, custody locations, and semantics by design.
- Machine publisher targets Updates repo; Human draft publisher targets canonical main repo and requires G22 deletion-result evidence before creation.
- G14f durable evidence, G19 ephemeral/current-session DELETE authorization, and G22 durable destructive-result evidence remain distinct.

## Risk review

Highest-risk executable tasks are RT1/RT3/RT7 (signed trust-profile bootstrap/conformance, authenticated local identity, and first enrollment), RA1/RA3/RA4 (sequence reconciliation/custody, complete component+trust freeze, and signing authority), RA8/RA9 (packaged update/rollback/crash proof), and RH3/RH4/RH5 (forensic custody, current-session retirement checks, and Human draft promotion). They require independent pro-agent review; Sol-high escalation is allowed only if a specific unresolved cross-cutting issue justifies the quota.

The proof-key/byte-identical-Updater architecture is now frozen by the **RT0/K1 plan gate**: one common Profile Authority root + exact signed external trust profile + enrollment pins, with a separate controller-custodied Proof Release Authority for proof `release-v2` signatures. After execution approval/K0, K1A establishes byte-canonical public custody only; RT1 implements/tests the profile codec, both detached assemblers, runtime trust, and K1 acceptance verifier and commits `RT1_CODE_HEAD`; K1B-A seals profiles; exact package/candidate bytes are measured; K1B-B seals proof envelopes + canonical `k1b-custody-v1.json`; packaged conformance/review binds exact `K1B_CUSTODY_SHA256`; controller then seals canonical `v512-k1-acceptance.json` in `K1_ACCEPTANCE_COMMIT` and verifies immutable Git history. Only after that may RT2+/RA1+/RH1+ proceed. RA7–RA9 re-verify that record and may not invent another trust carrier, proof fixture, serializer, or worker-held signer. Any contradiction is `ARCHITECTURE_FEASIBILITY_REGRESSION` and returns to Owner architecture review.

## Revision closeout after external plan review

The prior plan-review verdict was `PLAN_REVISION_REQUIRED` with Critical 2 / Important 3. This revision closes those five blocking findings as follows:

- **Sequence lifecycle:** master Task 6 and RA1 now use one append-only per-sequence event lifecycle. The first `RESERVED` consumes the sequence; legal same-sequence transitions are `RESERVED -> SIGNED|FAILED`, `SIGNED -> PUBLISHED|FAILED`, and `PUBLISHED -> RETIRED`. Second allocation, rebinding, illegal transition, or payload/envelope/key rebinding is rejected.
- **Release order:** master R2/R3 and RA controller gates freeze exact Launcher/Updater/Core **plus exact signed production `TrustProfileBinding`** first, then perform fresh sequence reconciliation/reservation, then metadata/signing. Any component/source/Core-authority/trust-profile/component-set change after reservation consumes the reservation and restarts with a new sequence.
- **Real source mapping:** RA2 modifies the existing root `tests/test_derive_version.py` and `tests/test_release_intent.py`, updates all current tuple/caller surfaces identified by source mapping, and removes semantic `get_release_sequence(version)` from production/release authority paths including `publish_atomic_release.py` and `verify_github_release_assets.py`.
- **Executable RT contracts:** RT4 has an explicit already-verified-profile/identity-reader test seam while packaged production loads one fixed signed profile and exposes no raw key/profile selector; RT7 forbids `state_machine.py` modification and requires STOP/plan revision if existing enrollment transitions cannot satisfy the signed-baseline contract. Development seq0 remains a separate explicit development identity type.
- **Early proof feasibility architecture:** RT0/K1 is resolved at plan level by the signed-profile architecture. K1A creates/reads back only byte-canonical Profile Authority + Proof Release Authority public custody; RT1 implements/tests the profile codec, detached profile/release assemblers, runtime trust and acceptance verifier, then commits `RT1_CODE_HEAD`; K1B-A seals profiles, exact baseline/candidate bytes are measured, and K1B-B seals proof envelopes + `K1B_CUSTODY_SHA256`. Independent review binds those exact bytes and controller seals canonical `v512-k1-acceptance.json` in `K1_ACCEPTANCE_COMMIT`; its immutable Git/history verifier must pass before RT2+/RA1+/RH1+ unlock.

A final cross-pack placeholder/interface/gate-order sweep also locked `UpdateState.LATEST` as the no-new-admissible-authority result for exact failed high-water rediscovery, aligned `SequenceLedgerEvent` terminology across master/RA, and made missing historical Core payload evidence an explicit RT9 blocker instead of a silent skip.

## Previous final-plan-review revision closeout

The latest independent plan review returned Critical 1 / Important 8 / Minor 3. This writing-plan-only revision closes those findings without changing Spec Revision 3.4 or starting execution:

- **Authenticated production history:** RA1/RA2 now use full typed authenticated bindings and `AuthenticatedHistorySnapshot`/`ReconciledSequenceAuthority`; reservation rechecks snapshot + ledger digests under the append lock and never allocates from a bare highest-sequence integer or silently retries stale authority.
- **RT1 real transport:** the plan names the real `GitHubLatestReleaseGateway`, separates `latest_release_api` from `browser_download_prefix`, and tests observable fetch/download behavior rather than invented inspection APIs.
- **RT2 ownership:** RT2 solely owns authenticated/development identity model migration, `software_release_identity.py`, tests, GREEN/Ruff/commit scope; RT3 only consumes that contract.
- **RT5 payload binding:** `software_update_v2.py` and its adapter test are in RED/GREEN/Ruff/atomic commit scope so authenticated `payload_sha256` reaches policy exactly.
- **RA DAG:** RA3 now produces exact `ArtifactIdentity`/`FinalComponentSet`/unsigned metadata before RA4 consumes them at the controller-only signing boundary; master DAG matches that order.
- **Hosted verification:** RA5 and RH5 lock one `gh api releases/assets/{asset_id}` stdout-to-parent-file mechanism with no token extraction, bearer argv, curl, or shell redirection.
- **Proof evidence (superseded by the next review closeout):** RA9 introduced generated worktree + external custody evidence; the next revision adds an immutable accepted-digest anchor and full nested schema.
- **Known-broken custody (superseded by the next review closeout):** RH2/RH3 introduced known-broken evidence binding; the next revision separates test custody from controller-only live forensic custody and binds historical verifier bytes rather than the fixed current verifier.
- **TDD executability:** RT/RA/RH behavior-changing tasks, including RT1 signed-profile/assembler/verifier implementation, carry explicit RED execution/evidence before implementation, GREEN/regression commands, lint/diff checks, exact commit scopes, and C0/I0 review; RT0/K1 plan architecture, K1A public-authority bootstrap, K1B-A controller profile sealing, K1B-B controller proof-envelope/custody sealing, acceptance checkpoints, and controller-only live release gates remain exempt from artificial RED.
- **Minor ambiguity cleanup:** `SignedBaselineEvidence` has an executable RA4 producer and RA6/RT8 consumers; RT8 locks build-time `--baseline-envelope` + `--trust-profile`, fixed `{app}\baseline\release-v2.json` + `{app}\trust\update-profile-v1.json`, and runtime `--enroll-baseline` with no authority/path arguments; RH6 uses RH1 audit output as authoritative file scope.
- **Placeholder sweep:** the executable pack contains none of the prohibited placeholder phrases from that review checklist.

## Current FINAL PLAN REVIEW revision closeout

The Owner's current FINAL PLAN REVIEW reported Critical 2 / Important 8 / Minor 3 and identified an additional acceptance-checkpoint row in the detailed table. This plan-only revision addresses every concrete row without changing Spec Revision 3.4 or starting execution:

- **Fresh authenticated-history authority:** `SequenceAuthoritySession` is now the serialization boundary; `AuthenticatedHistoryProvider.load()` is invoked inside the lock for `RESERVED`, again immediately before production signing/`SIGNED`, and before + after machine promotion prior to `PUBLISHED`. No authority-changing API accepts a prebuilt history snapshot. Newer/conflicting external authority hard-stops before sign/publish.
- **Authenticated-but-incomplete mandatory authority:** runtime identity preserves exact `observed`; RT6 now uses a dedicated one-shot helper `ADMIT_AUTHORITY` operation that re-verifies the signed envelope and durably advances `highwater=observed` while updater state remains IDLE **before** `SoftwareUpdateStageService.stage()` performs artifact transfer. Stage/network failure therefore needs no PREPARING recovery exception: committed stays runnable, failed is unchanged, no pending is fabricated, and exact observed high-water remains retryable. RA8 packages this real pre-stage network-loss scenario.
- **RA1 TDD order:** all RA1 tests are authored first, then one complete RED, then implementation, then complete GREEN; no implementation step precedes the full RED.
- **Signed baseline key identity:** `SignedBaselineEvidence.key_id` is derived only from the verified signed envelope and is the single RA6/build-record/controller key identifier.
- **Development identity:** RT2 now defines the complete `DevelopmentReleaseIdentity` shape and exact `load_development_release_identity(...)` signature/consumer boundary.
- **RT8 TDD order:** builder/tamper RED precedes builder changes; command-mode RED precedes `main.py`; ISS integration RED precedes `beta.iss`.
- **Acceptance execution:** RT10, RA10, and RH7 contain exact pytest/Ruff/repository-safety/diff/evidence-verification commands and explicit touched-test matrices.
- **Historical broken custody:** RH3 implementation uses injected `tmp_path` custody only. Real retirement custody is controller G14-only and binds the exact historical verifier bytes/source commit, historical exit-6 output, historical Core payload, exact broken Installer bytes, and build provenance—not the RT9-fixed verifier.
- **Proof evidence immutability:** RA9 defines a complete nested schema v1 with exact embedded proof-envelope bytes, accepted authority public-key/K1 bindings, full component objects, baseline/candidate/auxiliary release roles, scenario→envelope references, recomputable scenario digests, and authority-state→signed-release cross-binding. External custody is pinned by a controller-created tracked C0/I0 acceptance record; RA10/Task15 first guard the accepted RA9 verifier/harness source, then compare custody bytes to the immutable expected digest and independently re-verify K1 authority/profile/keyset + proof signatures rather than rehash-and-trust.
- **Signed immutable trust profile + proof signer custody (supersedes the earlier in-memory-only profile contract):** RT0/K1 selects a dedicated Profile Authority and separate Proof Release Authority; K1A custodies only byte-canonical public identities while both non-production private keys stay controller-only. RT1 implements/tests canonical profile payload/envelope verification, detached profile/release assemblers, runtime trust and `verify_v512_k1_acceptance.py`, then commits `RT1_CODE_HEAD`. K1B-A seals profiles; exact package/candidate identities are measured; K1B-B seals proof envelopes + canonical custody manifest. Independent review binds `K1B_CUSTODY_SHA256`; controller seals canonical `v512-k1-acceptance.json` and verifies its immutable `K1_ACCEPTANCE_COMMIT`. Packaged runtime verifies the fixed installed profile, pins profile-envelope/keyset identity, removes raw trust switches, and proves byte-identical proof/production baseline `NekoUpdater.exe`; RA3 later freezes the accepted K1B-A production `TrustProfileBinding` into `component_set_sha256` before reservation.
- **Traceability cleanup:** Master uses runtime `browser_download_prefix`, points Human publisher work to Task 13 and docs cleanup to Task 14, and reflects observed/retryable authority semantics and fresh signing/publication guards.
- **Independent final-review custody:** review dispatch is now hash-bound to the exact five-file plan pack; reviewer output has a closed canonical JSON schema and external custody digest; a passing verdict is sealed in `v512-final-plan-review.json` without mutating reviewed files; P0 requires that record + response custody + explicit Owner approval of the exact reviewed hashes and commits the closed six-path docs/evidence set before K0.

## Plan status

`PLAN_REVISION_COMPLETE / READY_FOR_FINAL_PLAN_REVIEW`

Controller pre-review has no open Critical/Important candidate after the fresh Spec-to-plan/source/API trace plus the independent-review governance hardening: review dispatch is bound to exact five-file hashes; reviewer identity must be connector-attested rather than self-asserted; request/invocation/response custody is immutable per `review_request_sha256` attempt; a PASS is sealed externally without mutating reviewed plan bytes; and P0/K0 revalidate that full chain plus explicit Owner approval of the exact reviewed hashes before any source edit. Fresh plan-byte assertions, stale-contract/canonical-JSON checks, exact approved-Spec SHA, plan trailing-whitespace scan, `git diff --check`, and worktree-status verification all pass. This status means **ready for the required independent final plan review only**: it is not independent C0/I0, not Owner execution approval, and not authority to start P0, Task 0/K0, Hermes Gateway, implementation dispatch, production signing, sequence reservation, public mutation, repository deletion, or Human Release. The required `ag/gemini-pro-agent` reviewer connector is still unavailable, so no independent verdict or review custody files are claimed/created.
