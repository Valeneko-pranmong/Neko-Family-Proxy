# Neko Family 5.1.2 Architecture

Status: APPROVED UNDER OWNER STANDING TECHNICAL DELEGATION
Date: 2026-09-12
Scope: Auto Update recovery, deferred update lifecycle, release-distribution recovery, implementation isolation, verification gates

## 1. Decision authority and execution rule

The Owner delegated technical decision authority for Neko Family 5.1.2 to the project controller on 2026-09-12. Backend/architecture choices no longer wait for Owner selection between technical alternatives. Decisions must remain evidence-based, reversible where practical, and recorded in the project ledger/Kanban.

This delegation does not weaken engineering gates. Architecture, implementation plans, TDD, independent review, C0/I0 acceptance, hosted proof, release evidence, and rollback criteria remain mandatory. The old `neko-family-5-1-stable` board remains historical evidence and is not repurposed as the 5.1.2 implementation board.

## 2. Goal

Neko Family 5.1.2 must restore a secure automatic-update path while preserving current accepted runtime behavior and legacy-client compatibility.

Required product behavior:

- Every Launcher process/open performs update discovery.
- A valid newer release may download, stage, and verify in the background while the user continues using the Launcher/proxy/game.
- Discovery, download, or transport failure must not force shutdown of an already accepted installed generation.
- Candidate signature/integrity/identity failure fails closed for that candidate.
- No update operation may forcibly terminate the game or proxy session.
- A completely staged update becomes durable `UPDATE_PENDING` state and survives Launcher restart/crash.
- The explicit Update action attempts a graceful safe transition; refusal/timeout/activity leaves the pending update intact.
- Normal safe exit may consume a pending update.
- A later safe Launcher start may consume the pending update without requiring the candidate to be downloaded again.
- Existing Updater transaction, generation, probation, rollback, anti-downgrade, and recovery mechanisms are retained rather than replaced.

## 3. Current accepted constraints

The current client discovers `Valeneko-pranmong/Neko-Family-Proxy/releases/latest` and binds signed release-v2 authority to GitHub release assets. Existing dormant clients therefore depend on the original repository identity.

Public `v5.1.0` currently exposes the human installer only. It intentionally does not expose `release-v2.json`, `NekoLauncher.exe`, `NekoUpdater.exe`, or `NekoProxyCore.zip`, so legacy machine-update discovery cannot currently succeed.

The release controller currently obtains Stable Core authority from the exact public Stable GitHub release. Because public v5.1.0 no longer contains signed machine assets, first-machine-release bootstrap needs a bounded alternate authority source.

A byte-for-byte archived v5.1.0 signed authority exists in the accepted Attempt-3 evidence. It may be used only as a bounded bootstrap input and must still pass production signature, canonical-envelope, SHA-256, size, Core identity, and Updater identity checks.

## 4. Chosen distribution architecture

### 4.1 Two-repository role inversion

The existing repository `Valeneko-pranmong/Neko-Family-Proxy` becomes the permanent machine-update channel because legacy clients already hardcode it.

After release engineering is proven, the simple human-facing installer surface moves to a separate repository such as `Valeneko-pranmong/Neko-Family-Proxy-Installer`. That repository is not a machine trust root. Creation/publication of the human repository is release-phase work, not implementation bootstrap work.

The machine channel contains the exact signed machine assets required by the accepted client contract:

- `release-v2.json`
- `NekoLauncher.exe`
- `NekoUpdater.exe`
- `NekoProxyCore.zip`

The signed manifest remains the cryptographic authority. GitHub storage/distribution is transport, not trust.

### 4.2 Bounded bootstrap authority override

For the first new machine release only, the release controller may consume the archived signed v5.1.0 Attempt-3 manifest/Core authority when the current accepted Stable tag is the known bootstrap release that lacks public machine assets.

The override must:

- be opt-in by an explicit local authoritative path/contract in controller code;
- verify the production Ed25519 signature and canonical envelope;
- verify exact expected Stable identity and tag relationship;
- verify Core SHA-256, size, canonical Core bundle identity, and installed identity;
- verify archived Updater identity against signed authority where the controller needs that evidence;
- record provenance identifying the bounded local bootstrap source;
- never mutate public v5.1.0;
- never silently fall back to arbitrary local files;
- be disabled once a newer accepted machine Stable with public machine assets exists.

After the first accepted machine release, normal exact Stable GitHub authority resumes. Reusing the bootstrap override beyond that transition is a release-blocking defect.

### 4.3 API-light discovery deferred

Refactoring newer clients to `/latest/download/release-v2.json` or another API-light discovery path is explicitly deferred. It does not solve the bootstrap problem, is unnecessary for legacy compatibility recovery, and increases first-recovery scope.

## 5. Implementation isolation

No 5.1.2 source implementation is performed on canonical `main`.

After this architecture and the implementation plan are finalized, create:

- Branch: `feature/neko-family-5.1.2`
- Worktree: `E:\Github\worktrees\Neko-Family-Proxy-5.1.2`

The branch starts from the then-current clean accepted `origin/main`. All 5.1.2 source/test/config/docs implementation commits occur in that worktree. There are no partial merges to `main`.

Merge eligibility requires full regression, repository-safety checks, independent review with Critical 0 / Important 0, and explicit source-acceptance evidence. Release execution remains downstream of merge/source acceptance.

## 6. Runtime component boundaries

### 6.1 Discovery and authenticated release binding

Existing `GitHubLatestReleaseGateway` and `GitHubReleaseResolver` remain the online discovery/binding path. They continue to enforce fixed repository, signed canonical manifest, same-release binding, artifact sizes, Updater identity, and protocol compatibility.

`UpdateCheckService` continues to own check semantics and process-local startup single-flight. Every Launcher process schedules the startup check exactly once; manual checks remain separate.

### 6.2 Background staging

Introduce a dedicated `SoftwareUpdateStageService`. It receives an already authenticated `ResolvedGitHubRelease`, determines changed Launcher/Core components using the accepted release policy, and downloads changed product artifacts into a private staging directory while the current session continues.

Staging completes only when:

- the exact canonical signed envelope is stored unchanged;
- each required changed artifact has exact signed size and SHA-256;
- the installed fixed Updater identity/protocol is compatible;
- release identity is newer and not a same-sequence conflict;
- the directory is atomically promoted from temporary staging to a durable pending generation.

A partial/failed staging attempt never replaces an already valid pending update.

### 6.3 Durable pending store

Introduce `PendingUpdateStore` under the fixed installation root. The durable record is not itself trusted. On every load, trust is reconstructed from the exact stored signed envelope and product bytes.

A pending generation contains:

- exact `release-v2.json` envelope bytes;
- staged Launcher artifact when changed;
- staged Core artifact when changed;
- a small untrusted metadata record containing schema version, release id/sequence, changed-component names, and envelope hash for consistency checks.

`PendingUpdateStore.load_verified()` must re-verify production signature/canonical bytes, stable channel, release identity, fixed artifact IDs/formats, Updater compatibility, staged artifact size/hash, local anti-downgrade/same-sequence rules, and derived paths. No absolute path from the metadata record is followed.

The externally visible lifecycle state is `UPDATE_PENDING` only after this verification passes.

### 6.4 Supersession and cleanup

A higher valid release may supersede an older pending release. It stages into a separate temporary generation first, then atomically switches the pending pointer. Same-sequence/different-identity is rejected. Lower releases never replace a higher pending release.

Crash leftovers from incomplete staging are cleaned on a later startup after the verified current pending generation has been preserved.

### 6.5 Session activity guard

A `SessionActivityGuard` provides one answer: whether applying now is safe.

Unsafe conditions include active proxy transition/session, active game process, game state not stopped, Launcher closing transition already in progress, or another update transition already in progress.

Unsafe does not invalidate pending state and never kills the game.

### 6.6 Explicit Update action

When `UPDATE_PENDING` exists, the Update action remains visible even when immediate application is unsafe.

If application is already safe, the action applies immediately through the graceful Launcher shutdown path.

If only the proxy is active, the action requests existing graceful proxy/service shutdown and waits for the bounded existing shutdown contract. On success it applies. On refusal/error/timeout it leaves `UPDATE_PENDING` intact and reports a safe user-visible message.

If the game process is active, the action never terminates the game. It tells the user the update is ready and will apply after the game is closed / on a later safe exit or start. Pending state remains intact.

### 6.7 Normal exit

Normal Launcher exit first follows the existing game-active confirmation and existing service shutdown semantics.

If a verified pending update exists and the activity guard is safe after graceful service shutdown, the close path starts the Updater handoff using the already staged candidate, then releases IPC/pipes and exits. If the guard is not safe or handoff cannot start, Launcher exits normally and preserves pending state.

### 6.8 Next-launch apply

Before normal online staging work, the Launcher checks for a verified durable pending generation.

If the game is not active and the candidate is still applicable, the Launcher may consume the pending generation without redownloading or requiring network availability. The stored signed envelope and staged bytes are reverified first.

If unsafe, the Launcher opens normally, exposes `UPDATE_PENDING`, and still performs the ordinary online startup discovery in the background. A newer valid candidate may supersede the existing pending generation.

### 6.9 Updater handoff

Refactor `SoftwareUpdateApplyService` so apply can consume a verified staged candidate instead of always refetching/downloading.

Apply sequence:

1. Reverify/load pending candidate.
2. Spawn the fixed installed `NekoUpdater.exe --session`.
3. Send `BEGIN` with the exact stored canonical envelope bytes.
4. Receive helper request/transaction IDs and helper-derived changed-component map.
5. Require helper changed-component set to match the verified staged candidate.
6. Copy verified staged Launcher/Core bytes only into the helper-created fixed incoming paths.
7. Rehash/resize the copied bytes before `APPLY`.
8. Send `APPLY`.
9. After acceptance, close Launcher cleanly and `release()` the helper rather than terminating it.
10. Existing helper transaction/generation/probation/rollback machinery owns the remainder.

The Updater state machine, generation builder, probation runner, rollback controller, high-water floors, and recovery engine are not redesigned.

## 7. Failure semantics

Transport/network unavailable: keep installed accepted generation running; keep a previously verified pending generation.

Manifest signature/canonical/schema failure: reject candidate; never stage/apply it.

Artifact size/hash failure: reject that staging attempt; preserve prior valid pending generation.

Updater identity/protocol mismatch: reject candidate before apply.

Same-sequence identity conflict/downgrade: fail closed and record a safe diagnostic.

Crash during staging: temporary generation may remain; current verified pending remains authoritative.

Crash after Updater transaction starts: existing Updater recovery state machine is authoritative.

Probation failure: existing rollback path restores previous accepted generation while preserving anti-downgrade/high-water evidence.

## 8. Concurrency

The existing Windows named mutex `Local\\NekoFamilyProxyLauncher` remains the cross-process Launcher single-instance boundary. 5.1.2 does not add a second competing Launcher process lock.

Within one Launcher process, discovery, staging, and apply use explicit single-flight state so duplicate startup/manual callbacks cannot concurrently mutate the pending store.

## 9. Diagnostics and privacy

Diagnostics record only safe status fields such as lifecycle state, release sequence, changed component names, and stable diagnostic codes. They must not record signed envelope contents, CDN query strings, response headers/cookies, local secret material, or production signing keys.

## 10. Testing strategy

Required layers:

- unit tests for pending record parsing, atomic promotion, verification, supersession, cleanup, and anti-downgrade;
- stage-service tests for valid changed-only downloads, offline/failure preservation, corruption rejection, and duplicate/single-flight behavior;
- UI/application tests for every-open check, visible pending state, explicit Update behavior, active game/proxy behavior, normal exit, timeout/refusal preservation;
- apply tests proving exact stored envelope bytes reach helper BEGIN, staged bytes are copied/reverified, helper changed-set mismatch fails closed, and no network refetch is required for a verified pending candidate;
- updater regression tests proving existing BEGIN/APPLY/probation/rollback/recovery behavior remains unchanged;
- release-controller tests for bounded local bootstrap authority and automatic disablement after a newer public machine Stable exists;
- deterministic E2E for stage while active -> pending -> restart/offline apply -> probation/commit, plus candidate failure -> rollback;
- full Launcher pytest, Ruff, repository safety, workflow tests, and `git diff --check` before merge eligibility.

## 11. Release engineering gates

Implementation does not itself create a public repository, tag, release, or production manifest.

After implementation C0/I0:

1. Prepare exact machine release candidate and provenance.
2. Verify first-release bootstrap authority path against archived v5.1.0 evidence.
3. Prove machine release assets with production resolver/verifier on hosted infrastructure.
4. Prove real upgrade from a supported legacy generation to the first new machine release.
5. Prove the next machine release uses normal public Stable authority with bootstrap override disabled.
6. Only then migrate/establish the separate human installer repository/surface and final publication policy.

## 12. Rejected alternatives

- Mutating public v5.1.0 to restore machine assets: rejected because it breaks the accepted immutability/current release-surface policy.
- Moving the machine channel away from the original repository immediately: rejected because dormant clients cannot discover the migration.
- Replacing signed release-v2 authority with storage/provider trust: rejected because transport must not become trust root.
- Rewriting the existing Updater transaction engine: rejected because it already contains the required transactional, probation, recovery, and rollback semantics.
- API-light discovery refactor in first recovery: deferred as unnecessary scope.

## 13. Architecture acceptance

Architecture decision: ACCEPTED.

Selected approach: Two-Repo Role Inversion + bounded local bootstrap authority override + durable Launcher-side staging/pending orchestration around the existing Updater transaction engine.

Implementation may proceed only from the detailed 5.1.2 implementation plan in an isolated feature worktree and under Hermes Kanban dependency/review gates.
