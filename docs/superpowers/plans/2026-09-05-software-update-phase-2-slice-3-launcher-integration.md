# Software Update Phase 2 — Slice 3 Launcher Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the verified manifest trust core into a one-shot asynchronous Launcher startup check and explicit manual application command without changing customer install behavior or existing auth/proxy startup semantics.

**Architecture:** `UpdateCheckService` owns single-flight/policy orchestration; AppWindow owns only asynchronous scheduling and safe result retention/diagnostics. Bootstrap injects HTTP gateways/verifier/local identity. No Phase-2 state blocks START, downloads files, or modifies UI layout.

**Tech Stack:** Python 3.11, existing application/port pattern, ThreadPoolExecutor/Tk `after`, pytest/Ruff/PyInstaller regression.

**Spec:** `docs/superpowers/specs/2026-09-05-software-update-phase-2-design.md`

## Global Constraints

- Worktree: `E:\Github\worktrees\Neko-Family-Proxy-5.1` on `release/5.1`; do not touch the dirty legacy `stabilize/a42-owner-verified` worktree.
- Current source version is `5.1.0a1`; do not build a materially changed Owner-test binary under that same version.
- Runtime Config v1, production Runtime Config v2, and `issue_launch_permit` v4 are separate and must not change.
- Phase 2 detects/authenticates updates and verifies artifact bytes only. No install, activation, `NekoUpdater.exe`, backup, rollback, or post-update self-test.
- Remote signed manifests use `release_sequence >= 1`; unpublished development uses local sequence `0` / `dev-unpublished`.
- Signed envelope: exact payload bytes, Ed25519, 64 KiB HTTP body, decoded payload <= 49,152 bytes, 64-byte signature, 32-byte public key.
- Key IDs: test `neko-update-test-1`; production reserved `neko-update-prod-1`. The production private key never enters the repo/client/logs.
- Manifest HTTP: HTTPS only, no redirects, 5.0 s timeout. Grant response: HTTPS only, no redirects, 5.0 s timeout, <= 16,384 bytes.
- Launcher artifact maximum 128 MiB; Core artifact maximum 1 GiB.
- Use TDD: a genuine failing assertion/missing-symbol RED before each product implementation. Collection/import errors do not count as RED.
- Launcher focused/final tests run with `PYTHONPATH` pointing at this worktree and `TCL_LIBRARY`/`TK_LIBRARY` removed process-locally. Full Launcher integration uses canonical Core artifact `E:\Github\worktrees\NekoProxyCore-live-update\TestResults\task12\a43-core`.
- Product-code implementation is delegated through Hermes; coordinator performs independent verification before every completion claim.

---

### Task 1: Update service ports and orchestration

**Files:**
- Modify: `launcher/src/neko_launcher/application/ports.py`
- Create: `launcher/src/neko_launcher/application/software_update_service.py`
- Create: `launcher/tests/test_software_update_service.py`

**Interfaces:**
- Add Protocol `UpdateManifestGateway.fetch(channel: str = "beta") -> object | None`.
- `UpdateCheckService(manifest_gateway, verifier, local_identity_provider)`
- Methods: `check_startup() -> UpdateCheckResult`, `check_manual() -> UpdateCheckResult`.
- Startup check is single-flight/once-per-process; second call returns the first completed result without another gateway fetch. Manual calls always perform a new explicit fetch and do not reset startup state.

- [ ] **Step 1: RED tests** for startup called twice -> one fetch, concurrent startup calls -> one fetch/one shared result, manual twice -> two fetches, manifest None/network -> UNAVAILABLE, verifier/policy failures -> VERIFY_FAILED safe diagnostic, success -> policy result, and an unexpected `RuntimeError("sentinel-internal-detail")` -> `VERIFY_FAILED` with diagnostic `UPDATE_CHECK_INTERNAL_FAILURE` while both concurrent callers return and the sentinel text is absent.

- [ ] **Step 2: Run focused tests and capture RED**

- [ ] **Step 3: Implement startup single-flight with `Condition` and cached result**

```python
def check_startup(self) -> UpdateCheckResult:
    with self._startup_condition:
        if self._startup_result is not None:
            return self._startup_result
        if self._startup_in_flight:
            self._startup_condition.wait_for(lambda: self._startup_result is not None)
            assert self._startup_result is not None
            return self._startup_result
        self._startup_in_flight = True

    result = self._check(UpdateInvocationReason.STARTUP)
    with self._startup_condition:
        self._startup_result = result
        self._startup_in_flight = False
        self._startup_condition.notify_all()
        return result
```

`_check` must catch all exceptions at this trust boundary. Expected transport/verification/policy failures map to their closed diagnostics; any unexpected exception maps to `VERIFY_FAILED` / `UPDATE_CHECK_INTERNAL_FAILURE` without retaining exception text. Therefore `_check` never raises, the single-flight worker always publishes a result, and waiters always wake.

- [ ] **Step 4: Run service/trust tests and Ruff**

- [ ] **Step 5: Commit** `feat: orchestrate software update checks`.

### Task 2: Launcher configuration and local identity composition

**Files:**
- Modify: `launcher/src/neko_launcher/infrastructure/defaults.py`
- Modify: `launcher/src/neko_launcher/infrastructure/config.py`
- Modify: `launcher/src/neko_launcher/bootstrap/app_factory.py`
- Modify: `launcher/tests/test_config.py`
- Create/modify: `launcher/tests/test_software_update_composition.py`

**Interfaces:**
- Default update API base URL exactly `https://neko-control-room.vercel.app`.
- Add `LauncherConfig.software_update_api_url`.
- Bootstrap update constants for this development line: `release_sequence=0`, `release_id="dev-unpublished"`; production sequence 1 is assigned only by later Owner release preparation.
- Production public-key registry remains empty/fail-closed until Owner-approved `neko-update-prod-1` public key is provisioned; tests inject the test public key.

- [ ] **Step 1: RED config/composition tests** assert the base URL, no production private key string exists, source/dev identity is sequence 0, and a missing Core canonical manifest yields an update result failure without stopping normal Launcher composition.

- [ ] **Step 2: Run focused tests and capture RED**

- [ ] **Step 3: Wire `HttpUpdateManifestGateway`, `ReleaseManifestVerifier`, identity provider, and `UpdateCheckService` in `build_window`**

In the existing final `AppWindow` constructor call in `build_window`, add the keyword argument `update_check_service=update_check_service`. Do not invoke the network in `build_window`; AppWindow schedules it asynchronously later.

- [ ] **Step 4: Run config/composition tests and Ruff**

- [ ] **Step 5: Commit** `feat: compose software update checker`.

### Task 3: One-shot asynchronous startup + explicit manual command

**Files:**
- Modify: `launcher/src/neko_launcher/ui/app_window.py`
- Create: `launcher/tests/ui/test_software_update_one_shot.py`

**Interfaces:**
- New optional constructor arg `update_check_service: Any = None`.
- Dedicated executor `ThreadPoolExecutor(max_workers=1, thread_name_prefix="neko-software-update")`.
- Schedule once: `root.after(2_000, self._check_software_update_startup)`.
- Expose method `_check_software_update_manual()` for later Phase-4 button wiring; no button/layout change now.
- Store only `_last_update_result: UpdateCheckResult | None`; diagnostics emit safe fields only.

- [ ] **Step 1: RED UI-threading tests** patterned after `test_public_proxy_status_one_shot.py`: startup schedules exactly once, second callback does not trigger another gateway fetch due service single-flight, update Future does not occupy `_executor` used for login/session restore, failure leaves auth/proxy state untouched, manual command is separately invokable.

- [ ] **Step 2: Run focused UI test and capture RED** with `TCL_LIBRARY`/`TK_LIBRARY` removed.

- [ ] **Step 3: Implement scheduling and callbacks**

```python
self._update_check_service = update_check_service
self._update_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="neko-software-update",
)
self._last_update_result: UpdateCheckResult | None = None
self.root.after(2_000, self._check_software_update_startup)
```

On completion call only a safe diagnostic such as `SOFTWARE_UPDATE_CHECK` with `state`, `release_sequence`, comma-joined changed component names, and diagnostic code. Do not place raw envelope/signature/grant URL in AppWindow fields.

- [ ] **Step 4: Run focused UI + existing startup/public-status/auth tests and Ruff**

- [ ] **Step 5: Commit** `feat: check software updates once at startup`.

### Task 4: Phase-2 privacy/security regression gate

**Files:**
- Create: `launcher/tests/test_software_update_privacy.py` if Slice 2 did not already create it; otherwise extend that file.
- Test only: leave `scripts/check_repository_safety.py` unchanged in Phase 2; repository scanning is implemented in the new privacy test.

- [ ] **Step 1: RED/guard tests** assert: production private Ed25519 key patterns absent from distributable source; `neko-update-test-1` test private key cannot be imported from production package; update results/logs omit raw payload/signature/grant URL/JWT/permit/Runtime Config/proxy credential sentinels; updater rejects unknown key and downgrade.
- [ ] **Step 2: Run the new privacy test plus existing `tests/test_repository_safety.py`; both must pass without modifying the safety script.**
- [ ] **Step 3: Run full Launcher Ruff and full pytest with canonical Core artifact.**

Expected: all prior 878 tests plus Phase-2 additions pass; 3 existing expected skips remain unless test inventory intentionally changes.

### Task 5: Phase-2 engineering candidate identity and build verification

**Files:**
- Modify only after all source tests are green: `launcher/pyproject.toml` and `launcher/src/neko_launcher/__init__.py` from `5.1.0a1` to `5.1.0a2`.
- Tests: existing version/build/smoke tests plus Phase-2 suites.

- [ ] **Step 1: RED version-identity assertion** proving current product-affecting Phase-2 tree may not be built/presented as `5.1.0a1`.
- [ ] **Step 2: Hermes bumps exactly both version files to `5.1.0a2`.**
- [ ] **Step 3: Re-run full Ruff + full Launcher suite on the final tree.**
- [ ] **Step 4: Build a fresh a2 candidate without overwriting v5.0.0/a43/a44 evidence.** Archive under `E:\Github\artifacts\phase2\5.1.0a2-candidate` with SHA-256 and metadata.
- [ ] **Step 5: Smoke-run in an `E:\Github` sandbox.** With Control Room production still unconfigured for software update, expected behavior is normal Launcher startup unaffected by update unavailability; no install is attempted. Verify packaged support diagnostics identify `5.1.0a2` and no secret residue.
- [ ] **Step 6: Commit** `release: prepare 5.1.0a2 phase2 candidate` and push `release/5.1`; keep Draft PR #5 draft.

### Task 6: Phase-2 cross-repo checkpoint

**Files:** Project Manager only after verification.

- [ ] Record Launcher commit/hash/test totals, Admin feature commit/test totals, Draft PR states, and explicitly `PRODUCTION_SOFTWARE_UPDATE_ROUTE = NOT DEPLOYED` / `ACTIVE_RELEASE = NONE`.
- [ ] Mark Phase 2 `ENGINEERING_PASS` only when Slice 1-3 tests/build/smoke pass.
- [ ] Do not begin Phase 3 until Phase 2 checkpoint is accepted.
