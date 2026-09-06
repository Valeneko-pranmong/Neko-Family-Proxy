# Software Update Phase 3 — Balanced Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for orchestration/review and Hermes as the ONLY repo mutation executor to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Phase 3 local engineering with the smallest practical architecture while preserving already accepted foundation at commit `8d9d8fdcbe30d97c903c275dbf450a9048991c9a`.

**Architecture:** A simplified Balanced Security implementation using a Launcher-spawned one-shot `NekoUpdater.exe` helper rather than the superseded long-lived hostile-process-family supervisor. Launcher owns network/download; helper owns signed admission, build/publish, post-Launcher-exit self-test, and commit/abort.

**Tech Stack:** Python 3.11, pytest 8.3.5, Ruff, PyInstaller, Win32 process APIs.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-balanced-security-amendment.md`.

---

## Global Constraints

- All repo mutations via Hermes.
- One logical issue/one active Hermes worker.
- TDD sequence for each task.
- One focused independent review per unit.
- Critical 0 / Important 0 only against Balanced in-scope requirements; no findings for listed hostile-local non-goals.
- No production deploy/release/signing/key mutation.
- Existing full baseline at plan creation: 1425 passed / 34 skipped / 0 failed with canonical a43 Core SHA `1b9b0ba313ac1f8c879f07f678a2f01e5b334c29fc17323533017aed2cbffcfe`.
- Each task has tests-only contract review, genuine RED, GREEN, ONE focused production review, full regression before task acceptance.
- Do not push automatically in the plan steps unless existing project authorization says the unit is accepted; normal non-force push only.
- Owner Gate 2 still blocks production publication/signing/key/active-release mutation.
- After Task 4, stop at engineering-complete/local-verified gate; release remains Owner Gate 2.

## Implementation Steps

### Task 1 — Balanced BrokerCoordinator (small library, no process/network supervision)
Files:
- Create `launcher/src/neko_launcher/updater/broker.py`
- Create `launcher/tests/updater/test_broker_balanced.py`

Prefer NO modifications to accepted Unit1/Unit2 files. Reuse `staging_handoff.handle_begin_request`, `handle_apply_request`, `GenerationPublisher.create_staging_area/publish_generation`, `build_generation`, `execute_precommit_abort`, `verify_release_envelope_v2`, `verify_canonical_core_bundle`, `SlotStore`.

Public interfaces:
- `@dataclass(frozen=True) class ApplyResult: accepted: bool; transaction_id: str|None=None; error: str|None=None`
- `class BrokerCoordinator(root_dir: Path, slot_store: SlotStore-like, public_keys: Mapping[str, bytes], published_verifier: Callable[[Path, Generation, bytes], None] | None = None)` (exact envelope bytes are canonical outer envelope JSON from state evidence)
- `begin(envelope_b64: str) -> RequestReadyResult`
- `apply(transaction_id: str, request_id: str) -> ApplyResult`

Behavior details:
- No cancel in initial Balanced scope: APPLY validation failure auto-aborts PREPARING transaction; download-side abandonment is recovered as ordinary PREPARING crash/abort on next helper start. (Deliberately avoids inventing a cancellation error code).
- BEGIN: load selected enrolled IDLE state; delegate signed/protocol/downgrade/suppression logic; persist one PREPARING/ADMITTED state via SlotStore and require returned selected state equals written state; success response only after durable write. No retained whole-lifecycle leaf/ancestor handle proof required at broker layer.
- APPLY: reload selected PREPARING matching IDs; reject/abort missing/extra/non-file inputs before staging; call existing handoff hash/size verification. Create `staging/<txid>` using GenerationPublisher, capture DirectoryIdentity, close returned handle after capture, update selected state to PREPARING with `transaction.staging=identity`, `stage='BUILDING'`, `mutation=None`; durable write. Call accepted `build_generation(root,state,public_keys)`. Publish.
- Default published verifier does practical post-publish verification: exact candidate signed envelope authenticates/payload binding matches; launcher SHA256 equals candidate identity; `verify_canonical_core_bundle` valid and canonical manifest SHA equals candidate core identity. Then persist PREPARING transaction stage VERIFIED, no new per-op mutation journal, and return success txid.
- On validation/build/publish/verifier error, call `execute_precommit_abort` from latest selected PREPARING state and persist; leave unselected published orphan inert if verifier fails rather than name-delete it. E2E need not require immediate recursive delete.
- Tests cover signature/protocol/downgrade via delegate, fixed filenames, missing/extra/corrupt hashes, metadata-only, durable BEGIN, coarse BUILDING/VERIFIED checkpoints, failures preserve old authority, and explicitly DO NOT test hostile race/ADS/hardlink/retained-handle lifetime at broker layer.

TDD sequence:
- [ ] Tests-only author -> focused independent contract review 0/0 -> tests-only commit. Keep focused, preferably <=450 lines, and reviewers cannot reject solely on line count.
- [ ] Genuine execution RED with broker missing (test module dynamically imports broker inside test body so missing production creates ordinary FAILED at execution, not collection ERROR).
- [ ] Production author -> focused GREEN -> one independent production review 0/0.
- [ ] Full Launcher regression + Ruff/diff -> narrow commit.

```python
# Sample snippet: Task 1 minimal test
class FakeSlotStore:
    def __init__(self): self._state = None
    def load(self): return SelectionResult(selected_state=self._state)
    def write_state(self, state): self._state = state; return self.load()

def test_broker_begin_success(temp_root, test_keys):
    from neko_launcher.updater.broker import BrokerCoordinator  # dynamic import for RED
    store = FakeSlotStore()
    broker = BrokerCoordinator(temp_root, store, test_keys)
    result = broker.begin(MOCK_ENVELOPE_B64)
    assert result.accepted
    assert store.load().selected_state.stage == 'ADMITTED'
```
```cmd
# Example TDD execution
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
.venv\Scripts\python.exe -B -m pytest tests/updater/test_broker_balanced.py -v
.venv\Scripts\ruff.exe check src/neko_launcher/updater/broker.py
cmd /d /c "set PYTHONDONTWRITEBYTECODE=1&& set NEKO_FINAL_CORE_ARTIFACT_PATH=E:\Github\worktrees\NekoProxyCore-live-update\TestResults\task12\a43-core&& .venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=no"
```
Commit message: `test: add Balanced BrokerCoordinator contract tests` then `feat: implement Balanced BrokerCoordinator`

### Task 2 — ActivationCoordinator / candidate self-test before selection
Files:
- Create `launcher/src/neko_launcher/updater/activation.py`
- Create `launcher/tests/updater/test_activation.py`

Interfaces:
- `@dataclass(frozen=True) class ActivationResult: committed: bool; generation: Generation | None; error: str|None=None`
- `activate_verified_generation(root_dir: Path, slot_store: SlotStore-like, self_test: Callable = run_probation_self_test) -> ActivationResult`

Behavior details:
- Require selected PREPARING tx stage VERIFIED.
- Run `run_probation_self_test` BEFORE selecting candidate.
- On self-test failure use `execute_precommit_abort` while still PREPARING, preserving old committed/highwater and journaling known incoming/staging cleanup; return committed False.
- On PASS only, map existing rich schema through lightweight durable transitions QUIESCING -> PROBATION -> CLEANING (these are schema compatibility checkpoints, not process-family security proofs), then commit candidate: committed=candidate, previous=old, highwater=candidate.binding, transaction=None, cleanup INTENT entries for known incoming/staging, last_error None. Successful activation CLEANING queue has known incoming/staging identities; existing recovery/cleanup drains them without overengineering recursive deletes.
- Validate each transition and SlotStore reread. No candidate UI process supervision, NORMAL_AUTH, family lease, or nested job proof.
- Tests: self-test fail leaves old selected; pass commits candidate+previous; SlotStore write failure fails closed; no commit occurs before PASS.

- [ ] Implement tests, review (0/0), commit tests.
- [ ] Verify RED.
- [ ] Implement production code, review (0/0), commit production code.

```python
# Sample snippet: Task 2 minimal test
def test_activation_selftest_failure_rollbacks(temp_root, store_with_verified_tx):
    result = activate_verified_generation(
        temp_root, store_with_verified_tx,
        self_test=lambda gen: SelfTestResult(passed=False, error_code='SELFTEST_FAILED')
    )
    assert not result.committed
    assert store_with_verified_tx.load().selected_state.transaction is None # aborted
```
Commit message: `test: add ActivationCoordinator rollback tests` then `feat: implement ActivationCoordinator`

### Task 3 — Thin one-shot updater process + local onefile package smoke
Files:
- Create `launcher/src/neko_launcher/updater/main.py`
- Create `launcher/tests/updater/test_updater_main.py`
- Create `launcher/NekoUpdater.spec`
- Modify `launcher/pyproject.toml` ONLY if strictly needed for packaging metadata (avoid lockfile churn).

Topology:
- Launcher spawns `NekoUpdater.exe --session` with stdin/stdout pipes; Launcher owns network/download.
- `main.py` uses existing `FramedIpcChannel`, fixed production root `get_expected_install_root()`, root validation, existing enrollment/SlotStore, one broker session.
- Session accepts BEGIN and APPLY messages, echoes message_id, emits REQUEST_READY/APPLY_RESULT.
- After successful APPLY it finishes IPC; actual activation is called only after caller/Launcher has closed session/exited.
- Keep process waiting logic simple and bounded; do not use family lease/job supervisor.

Functions:
- Provide dependency-injected pure functions `serve_session(channel, coordinator) -> bool` and `run_session(root_dir, public_keys, *, channel=None, slot_store=None, activate=activate_verified_generation) -> int` so tests use tmp sandbox without adding a production arbitrary-root CLI.
- Production `main()` has no `--root`; test keys/root are injected only through Python tests, never env/CLI backdoor.
- Production main: packaging/local `--self-check` is allowed now; production `--session` must fail closed without production key registry. Do not imply we will mutate keys in Task 3; local engineering does not embed test keys.

Packaging:
- `NekoUpdater.spec`: PyInstaller onefile named NekoUpdater, entry `src/neko_launcher/updater/main.py`, no app assets unless required, console behavior compatible with inherited stdio.
- Packaging test builds real NekoUpdater.exe and verifies `--self-check` exits 0 without network/credentials and imports required updater modules; `--session` production without authorized key registry fails closed, not open. Do not sign/publish.

- [ ] Implement tests, review (0/0), commit tests.
- [ ] Verify RED.
- [ ] Implement production code, review (0/0), commit production code.
- [ ] Create spec, build `NekoUpdater.exe`, execute package smoke tests.

```python
# Sample snippet: Task 3 minimal test
def test_run_session_injects_keys_and_root(temp_root, test_keys):
    assert run_session(temp_root, test_keys, channel=MockChannel()) == 0
```
Commit message: `test: add one-shot updater main tests` then `feat: implement NekoUpdater main and PyInstaller spec`

### Task 4 — Balanced local E2E matrix + rollback proof
Files:
- Create `launcher/tests/e2e/test_live_update_balanced_e2e.py`
- Create test helpers only if needed under `launcher/tests/e2e/`. (Do not restore superseded old E2E plan requirements).

Details:
- Use local temp/sandbox and injected ephemeral Ed25519 keys through Python `run_session`, plus real accepted a43 Core artifact authority (`1b9b0ba313ac1f8c879f07f678a2f01e5b334c29fc17323533017aed2cbffcfe`) when needed.
- Exact canonical Core env var: `set NEKO_FINAL_CORE_ARTIFACT_PATH=E:\Github\worktrees\NekoProxyCore-live-update\TestResults\task12\a43-core` (canonical exe SHA is `1b9b0ba313ac1f8c879f07f678a2f01e5b334c29fc17323533017aed2cbffcfe`)
- Matrix: bootstrap N -> Launcher-only N+1 -> Core-only N+2 -> both N+3 -> metadata-only N+4. For each, BEGIN, write only changed fixed artifacts, APPLY, activation PASS, verify committed generation identities/highwater and old previous.
- Failure path: valid published broken candidate self-test returns FAIL -> old committed remains selected, failed=observed, no candidate commit.
- Crash/restart cases only at coarse checkpoints: after ADMITTED and after VERIFIED; recovery converges safely.
- Separate package smoke executes built `NekoUpdater.exe --self-check`. No exhaustive Win32 malicious races.
- Full gate: focused E2E + full Launcher regression with canonical a43 Core, Ruff, diff/scope, independent Balanced review 0/0, narrow commit. No release/deploy/signing.

- [ ] Implement E2E tests, review (0/0), commit tests.
- [ ] Verify RED.
- [ ] Ensure all units pass (GREEN) in the full integrated matrix.
- [ ] Final regression and final narrow commit.

```python
# Sample snippet: Task 4 minimal test
class BalancedSandbox:
    def __init__(self, root, keys):
        from neko_launcher.updater.broker import BrokerCoordinator
        self.store = FakeSlotStore()
        self.broker = BrokerCoordinator(root, self.store, keys)
    def apply_update(self):
        self.broker.begin("b64")
        self.broker.apply("tx1", "req1")
        return activate_verified_generation(self.broker.root_dir, self.store, lambda g: SelfTestResult(passed=True))

def test_e2e_matrix_launcher_only(temp_root, test_keys):
    sandbox = BalancedSandbox(temp_root, test_keys)
    result = sandbox.apply_update()
    assert result.committed
```
Commit message: `test: implement Balanced live update E2E matrix`

## Deliberately Not Building
To strictly bound the scope to the Balanced threat model, the following will NOT be implemented:
- Family process lease and hostile process-tree survival guarantees.
- Exhaustive retained handle lifetime proofs and directory identity checks against malicious local administrators.
- Hostile Win32 ADS / hardlink / reparse racing mitigation beyond already authenticated OS semantics.
- A secondary security framework inside the orchestration logic.
- Arbitrary root directory backdoors via CLI in production builds.
- Embedding of test keys in the production binary.
- Elaborate mutation journals for every filesystem sub-operation (using coarse checkpoints instead).
