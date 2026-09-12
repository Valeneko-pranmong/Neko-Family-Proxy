# Neko Family 5.1.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use Superpowers-style task isolation and TDD. Hermes is the execution controller for this project. Every implementation task uses `ag/gemini-3.8-flash-high`; every independent architecture/security/regression/source-acceptance review uses `ag/gemini-pro-agent`. Implementers never review their own work.

**Goal:** Restore secure automatic update for dormant and current Neko Family clients, add background verified staging plus durable `UPDATE_PENDING`, preserve active sessions, consume pending updates on safe explicit action/exit/next launch, and recover release authority without mutating public v5.1.0.

**Architecture:** Keep the original GitHub repository as the permanent machine-update channel, use a bounded signed local Stable-authority override only for the first new machine release, and add Launcher-side staging/pending orchestration around the existing Updater transaction/probation/rollback engine. All work occurs on `feature/neko-family-5.1.2` in `E:\Github\worktrees\Neko-Family-Proxy-5.1.2` and merges to `main` only after full regression plus independent C0/I0 review.

**Tech Stack:** Python >=3.11, pytest 8.3.5, Ruff 0.11.2, PyInstaller 6.21.0, tkinter/customtkinter, existing GitHub Releases transport, Ed25519 signed release-v2 envelopes, Hermes Kanban.

**Spec:** `E:\Github\Project manager\current\NEKO_FAMILY_5_1_2_ARCHITECTURE.md`

## Global Constraints

- Canonical source repository: `E:\Github\Neko-Family-Proxy`.
- Implementation branch: `feature/neko-family-5.1.2`.
- Implementation worktree: `E:\Github\worktrees\Neko-Family-Proxy-5.1.2`.
- Start from then-current clean accepted `origin/main`; record exact base SHA before any source edit.
- Never mutate public v5.1.0.
- Existing repository `Valeneko-pranmong/Neko-Family-Proxy` remains the machine-update endpoint required by dormant clients.
- Signed `release-v2.json` remains trust authority; storage/provider metadata is not trust authority.
- Do not refactor to `/latest/download` in first recovery.
- Do not replace the existing Updater transaction state machine, generation builder, probation runner, rollback controller, high-water floors, or recovery engine.
- Never forcibly terminate the game for an update.
- A failed discovery/download/stage attempt must not remove a previously verified pending update or make an accepted installed generation unrunnable.
- A pending update can apply without network only after its exact stored signed envelope and every staged artifact are reverified.
- Every code task follows assertion-level RED -> minimal GREEN -> focused regression -> Ruff -> `git diff --check` -> independent review.
- No production tag/release/public-repo creation, production signing, or hosted mutation belongs to implementation tasks. Those remain release-engineering stages after C0/I0.
- No task may claim PASS from an expected count copied from this plan. Record actual observed counts.

---

## File Structure Locked by This Plan

New focused modules:

- `launcher/src/neko_launcher/application/software_update_pending.py` — immutable pending/staged models and lifecycle state.
- `launcher/src/neko_launcher/infrastructure/software_update_pending_store.py` — durable atomic pending-generation store and re-verification.
- `launcher/src/neko_launcher/infrastructure/software_update_stage.py` — authenticated background artifact staging and supersession.
- `launcher/src/neko_launcher/application/software_update_coordinator.py` — single-flight discovery/stage/pending/apply orchestration independent of tkinter.
- `launcher/src/neko_launcher/application/software_update_activity.py` — safe/unsafe application decision from Launcher state.
- `launcher/src/neko_launcher/bootstrap/pending_update_bootstrap.py` — next-launch pending load/apply decision before ordinary online staging.
- `launcher/tests/test_software_update_pending_store.py` — persistence, tamper, crash, supersession.
- `launcher/tests/test_software_update_stage.py` — staging/download behavior.
- `launcher/tests/test_software_update_coordinator.py` — lifecycle single-flight and policy.
- `launcher/tests/test_software_update_activity.py` — session safety policy.
- `launcher/tests/test_pending_update_bootstrap.py` — next-launch/offline decisions.
- `launcher/tests/test_release_controller_bootstrap.py` — bounded release-controller authority override.
- `launcher/tests/e2e/test_deferred_pending_update_e2e.py` — staged-active -> pending -> restart/offline apply -> existing updater commit/rollback.

Existing files expected to change:

- `launcher/src/neko_launcher/application/software_update_models.py`
- `launcher/src/neko_launcher/application/software_update_service.py`
- `launcher/src/neko_launcher/infrastructure/software_update_apply.py`
- `launcher/src/neko_launcher/bootstrap/app_factory.py`
- `launcher/src/neko_launcher/main.py`
- `launcher/src/neko_launcher/ui/app_window.py`
- `launcher/tests/test_software_update_apply.py`
- `launcher/tests/test_software_update_service.py`
- `launcher/tests/test_software_update_composition.py`
- `launcher/tests/ui/test_software_update_one_shot.py`
- `launcher/tests/ui/test_app_window.py`
- `scripts/release_controller.py`
- `scripts/check_repository_safety.py`
- `launcher/tests/test_repository_safety.py`
- current update/release documentation indexes as required by final repository-safety scan.

No Updater internals are changed unless an existing contract test proves a narrow adapter defect. If such a defect is found, stop that task, record the failing contract, and create a separately reviewed remediation task rather than expanding scope silently.

---

### Task 1: Durable pending models and atomic store

**Files:**
- Create: `launcher/src/neko_launcher/application/software_update_pending.py`
- Create: `launcher/src/neko_launcher/infrastructure/software_update_pending_store.py`
- Create: `launcher/tests/test_software_update_pending_store.py`
- Modify: `launcher/src/neko_launcher/application/software_update_models.py`

**Interfaces:**

```python
class UpdateLifecycleState(str, Enum):
    IDLE = "idle"
    STAGING = "staging"
    UPDATE_PENDING = "update_pending"
    APPLYING = "applying"

@dataclass(frozen=True)
class VerifiedPendingUpdate:
    release_id: str
    release_sequence: int
    changed_components: tuple[str, ...]
    envelope_bytes: bytes
    generation_dir: Path
    launcher_artifact: Path | None
    core_artifact: Path | None

class PendingUpdateStore:
    def __init__(self, root_dir: Path, key_registry: Mapping[str, bytes], updater_protocol: int) -> None: ...
    def promote(self, *, envelope_bytes: bytes, release: ReleaseSetV2, changed_components: tuple[str, ...], staged_files: Mapping[str, Path]) -> VerifiedPendingUpdate: ...
    def load_verified(self, local_identity: LocalReleaseIdentity) -> VerifiedPendingUpdate | None: ...
    def clear(self, expected_release_id: str, expected_release_sequence: int) -> None: ...
    def cleanup_incomplete(self) -> None: ...
```

Durable layout is derived entirely from `root_dir / "update-pending"`. Metadata never contains an authoritative arbitrary filesystem path.

- [ ] **Step 1: Write failing persistence and tamper tests**

Create tests that build an ephemeral signed stable exact-three release envelope, stage launcher/core fixture bytes, and assert: successful atomic promotion; process-restart reload; exact `UPDATE_PENDING`; envelope byte tamper rejection; staged size/hash tamper rejection; metadata path injection ignored/rejected; lower sequence cannot replace higher; same sequence/different identity rejected; incomplete temporary directory does not replace verified current pending.

- [ ] **Step 2: Run RED**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1.2\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_pending_store.py -q
```

Expected: assertions fail because the pending store/interfaces do not exist; zero collection errors after the test file uses guarded/dynamic imports during RED.

- [ ] **Step 3: Implement minimal models and atomic generation promotion**

Use a temporary sibling directory, exact envelope bytes, fixed filenames `release-v2.json`, `launcher.artifact`, `core.artifact.zip`, and one canonical metadata JSON. Flush/close files before `os.replace()` promotion. Verify envelope with existing production-compatible release-v2 verifier and verify staged artifact SHA-256/size before returning a `VerifiedPendingUpdate`.

- [ ] **Step 4: Run GREEN and lint**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_pending_store.py tests/test_software_update_models.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/application/software_update_pending.py src/neko_launcher/infrastructure/software_update_pending_store.py tests/test_software_update_pending_store.py
```

- [ ] **Step 5: Commit**

```cmd
git add launcher/src/neko_launcher/application/software_update_pending.py launcher/src/neko_launcher/application/software_update_models.py launcher/src/neko_launcher/infrastructure/software_update_pending_store.py launcher/tests/test_software_update_pending_store.py
git commit -m "feat(update): add durable verified pending store"
```

**Review gate:** `ag/gemini-pro-agent` reviews path derivation, atomicity, signature/hash re-verification, supersession, and failure preservation. Required C0/I0.

---

### Task 2: Background stage service using authenticated GitHub release binding

**Dependencies:** Task 1.

**Files:**
- Create: `launcher/src/neko_launcher/infrastructure/software_update_stage.py`
- Create: `launcher/tests/test_software_update_stage.py`
- Reuse without weakening: `launcher/src/neko_launcher/infrastructure/github_release_binding.py`
- Reuse without weakening: `launcher/src/neko_launcher/infrastructure/github_asset_downloader.py`

**Interfaces:**

```python
class SoftwareUpdateStageError(Exception):
    code: str

class SoftwareUpdateStageService:
    def __init__(self, *, pending_store: PendingUpdateStore, asset_downloader: GitHubAssetDownloader) -> None: ...
    def stage(self, resolved: ResolvedGitHubRelease, local: LocalReleaseIdentity) -> VerifiedPendingUpdate | None: ...
```

`stage()` uses `evaluate_release(local, resolved.authenticated_release, STARTUP)` to derive changed Launcher/Core components. It never stages the Updater binary and never invokes the helper.

- [ ] **Step 1: Write RED tests** for changed-only downloads, no-op latest release, mandatory/non-mandatory newer release, download failure preserving older pending, hash/size failure preserving older pending, higher release supersession, lower/same-conflict rejection, and exact envelope-byte preservation.
- [ ] **Step 2: Run RED**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_stage.py -q
```

- [ ] **Step 3: Implement minimal stage service** using a store-owned temporary generation. Product bytes are accepted only through existing bounded signed-size/SHA downloader.
- [ ] **Step 4: Run GREEN/regression**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_stage.py tests/test_github_release_binding.py tests/test_github_asset_downloader.py tests/test_software_update_policy.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/infrastructure/software_update_stage.py tests/test_software_update_stage.py
```

- [ ] **Step 5: Commit**

```cmd
git add launcher/src/neko_launcher/infrastructure/software_update_stage.py launcher/tests/test_software_update_stage.py
git commit -m "feat(update): stage verified updates in background"
```

**Review gate:** C0/I0 on trust boundaries and old-pending preservation.

---

### Task 3: Pure lifecycle coordinator and single-flight semantics

**Dependencies:** Tasks 1-2.

**Files:**
- Create: `launcher/src/neko_launcher/application/software_update_coordinator.py`
- Create: `launcher/tests/test_software_update_coordinator.py`
- Modify: `launcher/src/neko_launcher/application/software_update_service.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class UpdateLifecycleSnapshot:
    state: UpdateLifecycleState
    check_result: UpdateCheckResult | None
    pending: VerifiedPendingUpdate | None
    diagnostic_code: str | None

class SoftwareUpdateCoordinator:
    def startup(self) -> UpdateLifecycleSnapshot: ...
    def manual_check(self) -> UpdateLifecycleSnapshot: ...
    def current(self) -> UpdateLifecycleSnapshot: ...
```

`startup()` loads/reverifies existing pending first, performs one process-local online check, and stages a valid newer candidate in the same worker thread. Network failure returns the verified pending snapshot if one exists. Invalid candidate never deletes valid pending.

- [ ] **Step 1: Write RED tests** for every-process startup call, startup single-flight, manual check independence, pending-first load, offline-with-pending, online newer supersession, invalid remote preservation, and concurrent callback coalescing.
- [ ] **Step 2: Run RED**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_coordinator.py tests/test_software_update_service.py -q
```

- [ ] **Step 3: Implement coordinator** with a `Condition` or equivalent bounded process-local single-flight. Do not add a second cross-process lock; existing Launcher named mutex remains authoritative.
- [ ] **Step 4: GREEN/lint**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_coordinator.py tests/test_software_update_service.py tests/test_software_update_policy.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/application/software_update_coordinator.py src/neko_launcher/application/software_update_service.py tests/test_software_update_coordinator.py tests/test_software_update_service.py
```

- [ ] **Step 5: Commit**

```cmd
git add launcher/src/neko_launcher/application/software_update_coordinator.py launcher/src/neko_launcher/application/software_update_service.py launcher/tests/test_software_update_coordinator.py launcher/tests/test_software_update_service.py
git commit -m "feat(update): coordinate check stage and durable pending"
```

**Review gate:** C0/I0 on race/single-flight/error-state semantics.

---

### Task 4: Session activity guard and explicit apply policy

**Dependencies:** Task 3.

**Files:**
- Create: `launcher/src/neko_launcher/application/software_update_activity.py`
- Create: `launcher/tests/test_software_update_activity.py`
- Modify later in Task 6: `launcher/src/neko_launcher/ui/app_window.py`

**Interfaces:**

```python
class UpdateApplyBlocker(str, Enum):
    GAME_ACTIVE = "game_active"
    PROXY_ACTIVE = "proxy_active"
    GAME_TRANSITION = "game_transition"
    UPDATE_BUSY = "update_busy"

@dataclass(frozen=True)
class UpdateApplySafety:
    safe: bool
    blocker: UpdateApplyBlocker | None

def evaluate_update_apply_safety(state: AppState, *, update_busy: bool) -> UpdateApplySafety: ...
```

- [ ] **Step 1: Write tests** proving stopped/stopped is safe, proxy active blocks with `PROXY_ACTIVE`, game process active blocks with `GAME_ACTIVE`, non-stopped game state blocks, and update transition blocks.
- [ ] **Step 2: Run RED**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_activity.py -q
```

- [ ] **Step 3: Implement pure policy** with no tkinter/service side effects.
- [ ] **Step 4: GREEN/lint and commit**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_activity.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/application/software_update_activity.py tests/test_software_update_activity.py
git add launcher/src/neko_launcher/application/software_update_activity.py launcher/tests/test_software_update_activity.py
git commit -m "feat(update): define safe deferred apply policy"
```

**Review gate:** C0/I0; specifically prove no forced-game termination path is introduced.

---

### Task 5: Apply verified staged bytes through existing Updater transaction

**Dependencies:** Tasks 1 and 4.

**Files:**
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_apply.py`
- Modify: `launcher/tests/test_software_update_apply.py`
- Regression only unless defect proven: `launcher/src/neko_launcher/updater/staging_handoff.py`
- Regression: `launcher/tests/updater/test_staging_handoff.py`

**Interfaces:**

```python
class SoftwareUpdateApplyService:
    def prepare_pending(self, pending: VerifiedPendingUpdate) -> PreparedUpdate: ...
```

The existing network-refetch `prepare()` path may remain only if still used by non-5.1.2 tests; production 5.1.2 composition uses `prepare_pending()`.

- [ ] **Step 1: Write RED tests** proving `prepare_pending()` sends byte-identical stored envelope to BEGIN, requires helper changed map equal staged changed components, copies only fixed staged Launcher/Core files to helper-created incoming paths, rehashes/rechecks size after copy, sends APPLY only after checks, starts with no network resolver/downloader dependency, aborts helper on mismatch/failure, and returns a releasable `PreparedUpdate` on acceptance.
- [ ] **Step 2: Add offline assertion**: a verified pending update applies with a fake release gateway that would raise if called.
- [ ] **Step 3: Run RED**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_apply.py tests/updater/test_staging_handoff.py -q
```

- [ ] **Step 4: Implement minimal staged apply path**. Use derived fixed destinations under helper request ID; never trust path strings from pending metadata.
- [ ] **Step 5: GREEN/regression/lint**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_apply.py tests/updater/test_staging_handoff.py tests/updater/test_state_machine.py tests/updater/test_recovery_engine.py tests/updater/test_probation_runner.py tests/updater/test_rollback_controller.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/infrastructure/software_update_apply.py tests/test_software_update_apply.py
```

- [ ] **Step 6: Commit**

```cmd
git add launcher/src/neko_launcher/infrastructure/software_update_apply.py launcher/tests/test_software_update_apply.py
git commit -m "feat(update): apply verified pending bytes offline"
```

**Review gate:** C0/I0 on exact envelope handoff, path safety, helper lifecycle, and no Updater trust weakening.

---

### Task 6: Composition, UI pending state, explicit Update, and normal-exit handoff

**Dependencies:** Tasks 3-5.

**Files:**
- Modify: `launcher/src/neko_launcher/bootstrap/app_factory.py`
- Modify: `launcher/src/neko_launcher/ui/app_window.py`
- Modify: `launcher/tests/test_software_update_composition.py`
- Modify: `launcher/tests/ui/test_software_update_one_shot.py`
- Modify: `launcher/tests/ui/test_app_window.py`

**Behavior contract:**

- Startup still schedules update work for every Launcher process/open.
- Online check/stage is asynchronous and does not block normal UI use.
- `UPDATE_PENDING` is represented separately from raw check availability.
- Update button is enabled when a verified pending candidate exists, not only when proxy/game are already idle.
- Clicking Update while game active never kills the game and leaves pending intact with an explanatory notice.
- Clicking Update while only proxy is active uses the existing graceful service/controller stop path; bounded failure leaves pending intact.
- Safe Update starts `prepare_pending()`, then runs the existing close/shutdown path and `PreparedUpdate.release()`.
- Normal safe close with verified pending may apply automatically after graceful service shutdown; unsafe close preserves pending.

- [ ] **Step 1: Write UI/application RED tests** for background stage completion, pending button visibility, safe apply, game-active preservation, proxy graceful-stop success, proxy stop failure/timeout preservation, close-with-pending safe apply, close-with-game pending retention, and internal failure diagnostics that do not clear pending.
- [ ] **Step 2: Run RED**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_composition.py tests/ui/test_software_update_one_shot.py tests/ui/test_app_window.py -q
```

- [ ] **Step 3: Update composition** so one resolver, downloader, pending store, stage service, coordinator, and staged apply service are shared by the window.
- [ ] **Step 4: Refactor update UI callbacks** to consume `UpdateLifecycleSnapshot`; preserve existing Thai UX style and existing close/game confirmation semantics.
- [ ] **Step 5: GREEN/lint**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_composition.py tests/ui/test_software_update_one_shot.py tests/ui/test_app_window.py tests/test_software_update_coordinator.py tests/test_software_update_activity.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/bootstrap/app_factory.py src/neko_launcher/ui/app_window.py tests/test_software_update_composition.py tests/ui/test_software_update_one_shot.py tests/ui/test_app_window.py
```

- [ ] **Step 6: Commit**

```cmd
git add launcher/src/neko_launcher/bootstrap/app_factory.py launcher/src/neko_launcher/ui/app_window.py launcher/tests/test_software_update_composition.py launcher/tests/ui/test_software_update_one_shot.py launcher/tests/ui/test_app_window.py
git commit -m "feat(update): expose pending update without forcing sessions"
```

**Review gate:** C0/I0 on user-session safety, shutdown ordering, executor races, and preservation of pending state.

---

### Task 7: Next-launch verified pending apply

**Dependencies:** Tasks 1, 4, 5, 6.

**Files:**
- Create: `launcher/src/neko_launcher/bootstrap/pending_update_bootstrap.py`
- Create: `launcher/tests/test_pending_update_bootstrap.py`
- Modify: `launcher/src/neko_launcher/main.py`
- Modify: `launcher/tests/test_main.py` if present; otherwise create focused bootstrap tests only.

**Interfaces:**

```python
class PendingUpdateBootstrapResult(str, Enum):
    NONE = "none"
    DEFERRED = "deferred"
    HANDOFF_STARTED = "handoff_started"

def try_apply_pending_on_launch(*, pending_store: PendingUpdateStore, apply_service: SoftwareUpdateApplyService, game_active: Callable[[], bool], local_identity_provider: Callable[[], LocalReleaseIdentity]) -> PendingUpdateBootstrapResult: ...
```

`HANDOFF_STARTED` means the caller releases the helper and exits before constructing the ordinary Launcher window. `DEFERRED` means open normally and expose pending state.

- [ ] **Step 1: Write RED tests** for no pending, valid offline pending + no game -> handoff, active game -> deferred/no helper spawn, tampered pending -> rejected/open normally, already-current pending -> clear stale record safely, apply preparation failure -> preserve pending/open normally.
- [ ] **Step 2: Run RED**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_pending_update_bootstrap.py -q
```

- [ ] **Step 3: Implement bootstrap with dependency injection**. Do not introduce network discovery in this function.
- [ ] **Step 4: Wire into `main.py` after single-instance acquisition and root/config construction prerequisites but before normal UI construction.** Existing named mutex remains held through decision/handoff.
- [ ] **Step 5: GREEN/lint and commit**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_pending_update_bootstrap.py tests/test_single_instance.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/bootstrap/pending_update_bootstrap.py src/neko_launcher/main.py tests/test_pending_update_bootstrap.py
git add launcher/src/neko_launcher/bootstrap/pending_update_bootstrap.py launcher/src/neko_launcher/main.py launcher/tests/test_pending_update_bootstrap.py
git commit -m "feat(update): apply verified pending update on safe launch"
```

**Review gate:** C0/I0 on early-startup ordering and offline trust reconstruction.

---

### Task 8: Bounded first-machine-release controller authority override

**Dependencies:** Architecture only; may execute in parallel with Tasks 1-4 but must not run release side effects.

**Files:**
- Modify: `scripts/release_controller.py`
- Create: `launcher/tests/test_release_controller_bootstrap.py`
- Modify: `scripts/check_repository_safety.py`
- Modify: `launcher/tests/test_repository_safety.py`

**Interface:**

```python
@dataclass(frozen=True)
class CoreAuthoritySource:
    manifest_path: Path
    core_zip_path: Path
    provenance: dict[str, object]

def resolve_core_authority(stable_tag: str, staging_dir: Path, *, bootstrap_authority_dir: Path | None = None) -> CoreAuthoritySource: ...
```

Rules:

- Normal path remains exact GitHub Stable release authority.
- Local override is accepted only for the explicitly recognized first bootstrap Stable lacking public machine assets and only when the caller supplies `bootstrap_authority_dir`.
- Directory must contain exact `release-v2.json` and `NekoProxyCore.zip`; optionally inspect exact `NekoUpdater.exe` when signed helper identity evidence is required.
- The same signature/channel/Core artifact/hash/size/canonical Core installed-identity verification used by normal authority applies to local bytes.
- No arbitrary fallback when GitHub query fails for any other tag/release.
- Once the current Stable is newer than bootstrap Stable and has normal public machine authority, local override must be ignored/rejected.

- [ ] **Step 1: Write RED tests** for valid archived bootstrap authority, forged signature, changed Core byte, wrong tag, wrong channel, missing asset, arbitrary directory, no-override normal failure, and newer Stable refusing local override.
- [ ] **Step 2: Run RED**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_release_controller_bootstrap.py tests/test_repository_safety.py -q
```

- [ ] **Step 3: Factor common byte-verification from `verify_and_fetch_core()`** so GitHub and bounded local sources feed one verification routine. Do not duplicate or weaken trust checks.
- [ ] **Step 4: GREEN/lint/safety**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_release_controller_bootstrap.py tests/test_repository_safety.py -q
.venv\Scripts\ruff.exe check ../scripts/release_controller.py ../scripts/check_repository_safety.py tests/test_release_controller_bootstrap.py tests/test_repository_safety.py
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1.2
launcher\.venv\Scripts\python.exe -B scripts\check_repository_safety.py
```

- [ ] **Step 5: Commit**

```cmd
git add scripts/release_controller.py scripts/check_repository_safety.py launcher/tests/test_release_controller_bootstrap.py launcher/tests/test_repository_safety.py
git commit -m "feat(release): add bounded signed bootstrap authority"
```

**Review gate:** `ag/gemini-pro-agent`, C0/I0. Any route that permits arbitrary local unsigned Core is Critical.

---

### Task 9: Deterministic deferred-update E2E and regression matrix

**Dependencies:** Tasks 1-8.

**Files:**
- Create: `launcher/tests/e2e/test_deferred_pending_update_e2e.py`
- Modify as needed for shared fixtures only: `launcher/tests/software_update_helpers.py`
- Reuse: `launcher/tests/e2e/test_github_release_update_e2e.py`
- Reuse: existing Updater transaction/recovery test modules.

- [ ] **Step 1: Add deterministic E2E** that creates ephemeral signed N+1 authority, simulates active proxy/game while online discovery downloads/stages N+1, verifies no forced termination, closes/restarts Launcher, disables network transport, consumes verified pending bytes, passes existing Updater probation, and reaches committed N+1.
- [ ] **Step 2: Add failure E2E** for signed N+2 with broken candidate behavior causing existing probation/rollback path to restore runnable N+1 while preserving failure/high-water evidence.
- [ ] **Step 3: Add crash/retry cases** for partial staging, restart with completed pending, duplicate startup callback, and newer N+2 superseding N+1 pending before apply.
- [ ] **Step 4: Run focused E2E**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/e2e/test_deferred_pending_update_e2e.py tests/e2e/test_github_release_update_e2e.py -q
```

- [ ] **Step 5: Run full updater regression**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/updater -q
```

- [ ] **Step 6: Commit**

```cmd
git add launcher/tests/e2e/test_deferred_pending_update_e2e.py launcher/tests/software_update_helpers.py
git commit -m "test(update): prove deferred pending update lifecycle"
```

**Review gate:** independent regression/security review C0/I0.

---

### Task 10: Documentation, repository safety, full branch acceptance

**Dependencies:** Tasks 1-9.

**Files:**
- Create in branch: `docs/superpowers/specs/2026-09-12-neko-family-5-1-2-update-architecture.md` copied from the accepted architecture authority.
- Create in branch: `docs/superpowers/plans/2026-09-12-neko-family-5-1-2-implementation.md` copied from this plan.
- Modify: `docs/current/runtime-distribution.md`
- Modify: `docs/current/README.md`
- Modify: `docs/README.md`
- Modify only where current claims require it: `README.md`, `SECURITY.md`, `docs/HANDOFF.md`, `docs/PROJECT_CONTEXT.md`.
- Update external authority ledger under `E:\Github\Project manager\current\` with branch SHA, test evidence, review verdicts, and remaining release gates.

- [ ] **Step 1: Update current documentation** to distinguish machine-update channel from human installer surface, describe durable pending behavior, and document bounded bootstrap override as first-release-only.
- [ ] **Step 2: Run repository safety** and remove only current-doc/source contradictions; preserve historical specs/plans as historical evidence.
- [ ] **Step 3: Run complete Launcher tests**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1.2\launcher
.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=short
.venv\Scripts\ruff.exe check src tests
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1.2
launcher\.venv\Scripts\python.exe -B scripts\check_repository_safety.py
git diff --check
```

- [ ] **Step 4: Run build/static release-controller tests without release mutation** using existing repository build/test commands required by CI; do not create/tag/upload/publish a release.
- [ ] **Step 5: Independent final review** by `ag/gemini-pro-agent` against architecture + plan + full diff. Required verdict: Critical 0 / Important 0.
- [ ] **Step 6: Commit documentation/acceptance changes**

```cmd
git add docs README.md SECURITY.md
git commit -m "docs(update): record 5.1.2 deferred update architecture"
```

- [ ] **Step 7: Record exact branch HEAD and all actual test/review evidence** in the 5.1.2 project ledger.

**Branch acceptance state:** `IMPLEMENTATION_C0_I0 / READY_FOR_MAIN_SOURCE_ACCEPTANCE`. This state does not mean released.

---

## Hermes Kanban DAG

Create board display name exactly `Neko Family 5.1.2` after branch/worktree baseline is clean.

Logical dependency graph:

```text
K0 Bootstrap/authority ledger
  -> T1 Pending Store
      -> T2 Stage Service
          -> T3 Coordinator
              -> T4 Activity Guard
                  -> T6 UI/Normal Exit
      -> T5 Staged Apply -----------^
      -> T7 Next-Launch Apply ------^
  -> T8 Controller Bootstrap Authority

T1,T2,T3,T4,T5,T6,T7,T8
  -> T9 Deferred E2E/Regression
      -> T10 Docs + Full Branch Acceptance
          -> R1 Independent Final Review
              -> G2 C0/I0 Gate
                  -> Main Source Acceptance
                      -> Merge to main
                          -> Post-merge CI/source acceptance
                              -> Release engineering gates
```

Tasks that do not share mutable files may run in parallel. T8 may run beside early Launcher work, but shared repository commits must be rebased/cherry-picked into the single integration branch in controlled order by the project controller; Hermes workers must not create competing long-lived integration branches.

## Hermes Model Routing

- Implementation/source/test/config/doc remediation: `ag/gemini-3.8-flash-high`.
- Architecture/security/regression/release/source-acceptance review: `ag/gemini-pro-agent`.
- Reviewer profile must be distinct from implementer attempt.
- A task does not become done merely because tests pass; it requires its specified independent review gate where one is listed.
- Any review verdict with Critical > 0 or Important > 0 returns the implementation task for remediation and re-review.

## Baseline and Merge Rules

Before Task 1 dispatch:

```cmd
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git merge-base --is-ancestor HEAD origin/main
```

Run the existing canonical Launcher baseline suite in the new worktree. If baseline is red, create a dedicated Kanban diagnostic task and distinguish pre-existing failure from 5.1.2 changes before implementation continues.

No partial merge to `main`. After branch C0/I0, perform independent Main Source Acceptance against exact branch HEAD. Merge only that accepted HEAD (or a mechanically equivalent merge commit), then rerun post-merge CI/source acceptance before any release action.

## Release-Phase Success Criteria After Merge

Implementation completion is not production completion. Release engineering later must prove all of the following with exact evidence:

1. First new machine Stable in the original repository exposes the four required machine assets and passes production resolver/verifier checks.
2. The first machine release's Core authority was derived through the bounded archived signed bootstrap path without modifying public v5.1.0.
3. A supported legacy client can upgrade to the first machine Stable.
4. A subsequent machine Stable derives authority from normal public Stable machine assets and proves the bootstrap override is disabled.
5. Human installer surface can be moved to the separate installer repository without changing the machine trust root.
6. Real release acceptance review returns C0/I0 before final production acceptance.

## Plan Self-Review Result

Spec coverage: complete for every-open discovery, background staging, durable pending, active-session preservation, explicit Update, normal exit, next-launch offline apply, existing Updater reuse, bootstrap authority, legacy repository compatibility, test/review/merge gates, and release proof.

Placeholder scan: no implementation placeholder or deferred mandatory step remains. API-light discovery and human-repository creation are explicit later-scope decisions, not missing implementation steps.

Type/interface consistency: `VerifiedPendingUpdate`, `PendingUpdateStore`, `SoftwareUpdateStageService`, `SoftwareUpdateCoordinator`, `UpdateLifecycleSnapshot`, activity policy, `prepare_pending()`, and next-launch bootstrap are defined once and consumed consistently by dependent tasks.

Plan decision: APPROVED UNDER OWNER STANDING TECHNICAL DELEGATION. Proceed to isolated worktree creation, clean baseline verification, then Hermes board/DAG materialization. Do not start source implementation if baseline verification is unresolved.
