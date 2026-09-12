from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from neko_launcher.application.software_update_activity import (
    UpdateApplyBlocker,
    evaluate_update_apply_safety,
)
from neko_launcher.application.software_update_coordinator import (
    SoftwareUpdateCoordinator,
    UpdateLifecycleSnapshot,
)
from neko_launcher.application.software_update_models import LocalReleaseIdentity
from neko_launcher.application.software_update_pending import UpdateLifecycleState
from neko_launcher.application.software_update_service import UpdateCheckService
from neko_launcher.bootstrap.pending_update_bootstrap import (
    PendingUpdateBootstrapResult,
    try_apply_pending_on_launch,
)
from neko_launcher.domain.models import AppState, GameStatus, ProxyStatus
from neko_launcher.infrastructure.github_asset_downloader import (
    GitHubAssetDownloader,
    GitHubAssetDownloadError,
    GitHubManifestDownloader,
)
from neko_launcher.infrastructure.github_release import GitHubLatestReleaseGateway
from neko_launcher.infrastructure.github_release_binding import (
    CORE_ASSET_NAME,
    GitHubReleaseResolver,
)
from neko_launcher.infrastructure.software_update_apply import (
    SoftwareUpdateApplyService,
)
from neko_launcher.infrastructure.software_update_pending_store import (
    PendingUpdateStore,
)
from neko_launcher.infrastructure.software_update_stage import (
    SoftwareUpdateStageService,
)
from neko_launcher.updater.activation import activate_verified_generation
from neko_launcher.updater.binary_frame import SlotFrame, pack_slot_frame
from neko_launcher.updater.ipc_channel import FramedIpcChannel
from neko_launcher.updater.main import run_session
from neko_launcher.updater.probation_runner import SelfTestResult
from neko_launcher.updater.recovery_engine import RecoveryEngine
from neko_launcher.updater.state_models import deserialize_state, serialize_state
from tests.e2e.test_github_release_update_e2e import (
    FakeTransportOpener,
    ThreadHelperProcess,
    _assert_public_unauthenticated_requests,
    _build_simulation_fixtures,
    _retarget_as_launcher_only_n_plus_two,
    _SimulatedHttpResponse,
)
from tests.e2e.test_live_update_balanced_e2e import ClosableStore


class ReusableFakeTransportOpener(FakeTransportOpener):
    """Transport opener that resets simulated response streams for replayable reads."""

    def open(self, request: Any, timeout: float = 15.0) -> Any:
        res = super().open(request, timeout)
        if hasattr(res, "stream") and hasattr(res.stream, "seek"):
            res.stream.seek(0)
        return res


def _setup_coordinator_pipeline(
    root: Path,
    env: Any,
    store: Any,
    opener: FakeTransportOpener,
    local_identity: LocalReleaseIdentity,
) -> tuple[
    SoftwareUpdateCoordinator,
    SoftwareUpdateStageService,
    PendingUpdateStore,
    GitHubReleaseResolver,
]:
    gw = GitHubLatestReleaseGateway()
    gw._opener = opener
    mdl = GitHubManifestDownloader(_opener=opener)
    resolver = GitHubReleaseResolver(
        release_gateway=gw,
        manifest_downloader=mdl,
        key_registry=env.keys,
        install_root=root,
    )
    adl = GitHubAssetDownloader(_opener=opener)

    pending_store = PendingUpdateStore(
        root_dir=root,
        key_registry=env.keys,
        updater_protocol=1,
    )
    stage_service = SoftwareUpdateStageService(
        pending_store=pending_store,
        asset_downloader=adl,
    )
    check_service = UpdateCheckService(
        release_gateway=resolver,
        local_identity_provider=lambda: local_identity,
    )
    coordinator = SoftwareUpdateCoordinator(
        check_service=check_service,
        stage_service=stage_service,
        pending_store=pending_store,
        local_identity_provider=lambda: local_identity,
    )
    return coordinator, stage_service, pending_store, resolver


def _create_helper_runner(
    root: Path,
    keys: dict[str, bytes],
    store: Any,
    *,
    self_test_pass: bool = True,
) -> tuple[
    SoftwareUpdateApplyService,
    list[ThreadHelperProcess],
    list[int],
    list[FramedIpcChannel],
]:
    created_channels: list[FramedIpcChannel] = []
    helper_exit_codes: list[int] = []
    proc_refs: list[ThreadHelperProcess] = []

    def activate_fn(root_dir: Path, slot_store: Any) -> Any:
        return activate_verified_generation(
            root_dir,
            slot_store,
            self_test=lambda p: (
                SelfTestResult(passed=True)
                if self_test_pass
                else SelfTestResult(
                    passed=False,
                    code="SELFTEST_FAILED",
                    message="broken candidate self-test failed",
                )
            ),
        )

    def spawner(cmd: Any, **kwargs: Any) -> ThreadHelperProcess:
        del cmd, kwargs
        r1, w1 = os.pipe()
        r2, w2 = os.pipe()
        l_chan = FramedIpcChannel(read_handle=r2, write_handle=w1)
        u_chan = FramedIpcChannel(read_handle=r1, write_handle=w2)
        created_channels.append(l_chan)

        def run_h() -> None:
            rc = run_session(
                root,
                keys,
                channel=u_chan,
                slot_store=store,
                activate=activate_fn,
            )
            helper_exit_codes.append(rc)

        t = threading.Thread(target=run_h, daemon=True)
        t.start()
        proc = ThreadHelperProcess(t, l_chan, u_chan)
        proc_refs.append(proc)
        return proc

    service = SoftwareUpdateApplyService(
        root_dir=root,
        spawner=spawner,
        channel_factory=lambda: created_channels[-1],
    )
    return service, proc_refs, helper_exit_codes, created_channels


def test_deferred_update_e2e_session_active_staging_offline_apply_commit(
    tmp_path: Path,
) -> None:
    """Step 1: Deterministic E2E proving online stage while session active -> durable

    pending -> restart/offline apply -> existing Updater probation/commit.
    """
    env, store, updater_bytes, routes = _build_simulation_fixtures(
        tmp_path,
        launcher_changed=True,
        core_changed=True,
    )
    opener = ReusableFakeTransportOpener(routes)

    local_identity_v1 = LocalReleaseIdentity(
        release_sequence=1,
        release_id="rel-1",
        launcher_version="1.0.0",
        launcher_installed_identity_sha256=env.old_launcher_sha,
        core_version="1.0.0",
        core_installed_identity_sha256=env.old_core_id,
    )

    coordinator, stage_service, pending_store, resolver = (
        _setup_coordinator_pipeline(
            tmp_path,
            env,
            store,
            opener,
            local_identity_v1,
        )
    )

    # 1. Simulate active proxy and game sessions
    active_state = AppState(
        game_status=GameStatus.RUNNING,
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    safety = evaluate_update_apply_safety(active_state)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.GAME_ACTIVE

    # Attempting launch apply while game is active must defer
    dummy_apply = SoftwareUpdateApplyService(root_dir=tmp_path)
    deferred_res = try_apply_pending_on_launch(
        pending_store=pending_store,
        apply_service=dummy_apply,
        game_active=lambda: True,
        local_identity_provider=lambda: local_identity_v1,
    )
    assert deferred_res in (
        PendingUpdateBootstrapResult.NONE,
        PendingUpdateBootstrapResult.DEFERRED,
    )

    # 2. Online stage N+1 candidate while session remains active
    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot.pending is not None
    assert snapshot.pending.release_sequence == 2
    assert snapshot.pending.release_id == "rel-2"

    # Verify no forced termination occurred while game/proxy were active
    assert evaluate_update_apply_safety(active_state).safe is False
    assert (
        try_apply_pending_on_launch(
            pending_store=pending_store,
            apply_service=dummy_apply,
            game_active=lambda: True,
            local_identity_provider=lambda: local_identity_v1,
        )
        == PendingUpdateBootstrapResult.DEFERRED
    )

    # Verify durable pending record and artifacts written to disk
    pointer = pending_store._read_active_pointer()
    assert pointer is not None
    assert pointer["release_sequence"] == 2
    assert pointer["release_id"] == "rel-2"
    assert snapshot.pending.generation_dir.is_dir()
    assert (snapshot.pending.generation_dir / "release-v2.json").is_file()
    assert (snapshot.pending.generation_dir / "launcher.artifact").is_file()
    assert (snapshot.pending.generation_dir / "core.artifact.zip").is_file()

    # 3. Simulate Launcher shutdown, restart, and offline apply
    # Network transport is completely disabled
    routes.clear()

    apply_service, proc_refs, exit_codes, channels = _create_helper_runner(
        tmp_path,
        env.keys,
        store,
        self_test_pass=True,
    )

    # Game has terminated before restart
    apply_result = try_apply_pending_on_launch(
        pending_store=pending_store,
        apply_service=apply_service,
        game_active=lambda: False,
        local_identity_provider=lambda: local_identity_v1,
    )
    assert apply_result == PendingUpdateBootstrapResult.HANDOFF_STARTED

    assert proc_refs
    proc_refs[0].thread.join(timeout=10.0)
    assert not proc_refs[0].thread.is_alive()
    assert exit_codes[0] == 0

    # 4. Verify committed N+1 in Updater state and file structure
    state = store.state
    assert state is not None
    assert state.phase in ("CLEANING", "IDLE")
    assert state.committed == env.candidate
    assert state.previous == env.old
    assert state.highwater == env.candidate.binding
    assert state.failed is None
    assert state.transaction is None

    published_dir = (
        tmp_path
        / "releases"
        / f"g-{env.candidate.binding.release_sequence:020d}-{env.candidate.binding.payload_sha256}"
    )
    assert published_dir.is_dir()
    assert (published_dir / "NekoLauncher.exe").is_file()
    assert (published_dir / "ProxyCore").is_dir()

    # Local identity advances to N+1; stale pending update is cleared safely
    local_identity_v2 = LocalReleaseIdentity(
        release_sequence=2,
        release_id="rel-2",
        launcher_version="1.0.0",
        launcher_installed_identity_sha256=env.new_launcher_sha,
        core_version="1.0.0",
        core_installed_identity_sha256=env.new_core_id,
    )
    pending_store.clear("rel-2", 2)
    assert pending_store.load_verified(local_identity_v2) is None

    _assert_public_unauthenticated_requests(opener)


def test_deferred_update_e2e_signed_n_plus_two_broken_candidate_rollback(
    tmp_path: Path,
) -> None:
    """Step 2: Failure E2E for signed N+2 with broken candidate behavior causing

    existing probation/rollback path to restore runnable N+1 while preserving
    failure/high-water evidence.
    """
    env, store, updater_bytes, routes = _build_simulation_fixtures(
        tmp_path,
        launcher_changed=True,
        core_changed=True,
    )
    opener = ReusableFakeTransportOpener(routes)

    local_v1 = LocalReleaseIdentity(
        release_sequence=1,
        release_id="rel-1",
        launcher_version="1.0.0",
        launcher_installed_identity_sha256=env.old_launcher_sha,
        core_version="1.0.0",
        core_installed_identity_sha256=env.old_core_id,
    )

    coordinator, stage_service, pending_store, resolver = (
        _setup_coordinator_pipeline(
            tmp_path,
            env,
            store,
            opener,
            local_v1,
        )
    )

    # 1. Complete initial update to N+1
    coordinator.startup()
    apply_v1, proc_v1, exit_v1, _ = _create_helper_runner(
        tmp_path,
        env.keys,
        store,
        self_test_pass=True,
    )
    routes.clear()
    res1 = try_apply_pending_on_launch(
        pending_store=pending_store,
        apply_service=apply_v1,
        game_active=lambda: False,
        local_identity_provider=lambda: local_v1,
    )
    assert res1 == PendingUpdateBootstrapResult.HANDOFF_STARTED
    proc_v1[0].thread.join(timeout=10.0)
    assert exit_v1[0] == 0
    n_plus_one = env.candidate
    assert store.state.committed == n_plus_one

    # 2. Process restart and clean recovery to IDLE
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_bytes = serialize_state(store.state)
    (state_dir / "slot-a.bin").write_bytes(
        pack_slot_frame(
            SlotFrame(
                revision=store.state.revision,
                format_version=1,
                body_bytes=state_bytes,
            )
        )
    )
    restarted = RecoveryEngine(tmp_path, env.keys).run_recovery()
    assert restarted.converged is True
    assert restarted.selected_generation == n_plus_one
    assert restarted.final_state is not None
    store = ClosableStore(deserialize_state(serialize_state(restarted.final_state)))
    env.store = store

    # 3. Create signed N+2 authority and stage it
    local_v2 = LocalReleaseIdentity(
        release_sequence=2,
        release_id="rel-2",
        launcher_version="1.0.0",
        launcher_installed_identity_sha256=env.new_launcher_sha,
        core_version="1.0.0",
        core_installed_identity_sha256=env.new_core_id,
    )
    n_plus_two = _retarget_as_launcher_only_n_plus_two(env, routes)
    opener = ReusableFakeTransportOpener(routes)
    coordinator2, stage_service2, pending_store2, resolver2 = (
        _setup_coordinator_pipeline(
            tmp_path,
            env,
            store,
            opener,
            local_v2,
        )
    )

    snapshot2 = coordinator2.startup()
    assert snapshot2.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot2.pending is not None
    assert snapshot2.pending.release_sequence == 3
    assert snapshot2.pending.release_id == "rel-3"

    # 4. Offline apply with broken candidate behavior triggering probation failure
    routes.clear()
    apply_v2, proc_v2, exit_v2, _ = _create_helper_runner(
        tmp_path,
        env.keys,
        store,
        self_test_pass=False,
    )

    res2 = try_apply_pending_on_launch(
        pending_store=pending_store2,
        apply_service=apply_v2,
        game_active=lambda: False,
        local_identity_provider=lambda: local_v2,
    )
    assert res2 == PendingUpdateBootstrapResult.HANDOFF_STARTED
    proc_v2[0].thread.join(timeout=10.0)
    assert exit_v2[0] != 0

    # 5. Verify existing rollback restored runnable N+1 with failure/high-water evidence intact
    state = store.state
    assert state is not None
    assert state.committed == n_plus_one
    assert state.previous == env.old
    assert state.highwater == n_plus_one.binding
    assert state.observed == n_plus_two.binding
    assert state.failed == n_plus_two.binding
    assert state.transaction is None
    assert state.last_error == "SELFTEST_FAILED"

    # N+1 runnable directory is fully preserved
    n_plus_one_dir = (
        tmp_path
        / "releases"
        / f"g-{n_plus_one.binding.release_sequence:020d}-{n_plus_one.binding.payload_sha256}"
    )
    assert n_plus_one_dir.is_dir()
    assert (n_plus_one_dir / "NekoLauncher.exe").is_file()
    assert (n_plus_one_dir / "ProxyCore").is_dir()

    # Recovery converges to N+1 cleanly with zero mutations
    state_dir = tmp_path / "state"
    for slot in (state_dir / "slot-a.bin", state_dir / "slot-b.bin"):
        slot.unlink(missing_ok=True)
    state_bytes = serialize_state(state)
    (state_dir / "slot-a.bin").write_bytes(
        pack_slot_frame(
            SlotFrame(
                revision=state.revision,
                format_version=1,
                body_bytes=state_bytes,
            )
        )
    )
    recovery = RecoveryEngine(tmp_path, env.keys)
    recovered1 = recovery.run_recovery()
    assert recovered1.converged is True
    assert recovered1.selected_generation == n_plus_one
    recovered2 = recovery.run_recovery()
    assert recovered2.converged is True
    assert recovered2.mutations_performed == 0
    assert recovered2.selected_generation == n_plus_one
    assert recovered2.final_state == recovered1.final_state


def test_deferred_update_partial_staging_crash_recovery(tmp_path: Path) -> None:
    """Step 3a: Crash/retry - partial staging crash is rejected, cleaned up, and

    subsequent staging retry succeeds cleanly.
    """
    env, store, updater_bytes, routes = _build_simulation_fixtures(tmp_path)
    opener = ReusableFakeTransportOpener(routes)

    local_v1 = LocalReleaseIdentity(
        release_sequence=1,
        release_id="rel-1",
        launcher_version="1.0.0",
        launcher_installed_identity_sha256=env.old_launcher_sha,
        core_version="1.0.0",
        core_installed_identity_sha256=env.old_core_id,
    )

    coordinator, stage_service, pending_store, _ = _setup_coordinator_pipeline(
        tmp_path,
        env,
        store,
        opener,
        local_v1,
    )

    # 1. Simulate orphaned / partial staging folder from crashed download
    orphaned_stage = pending_store.base_dir / "tmp_stage_crashed_123"
    orphaned_stage.mkdir(parents=True, exist_ok=True)
    (orphaned_stage / "launcher.artifact").write_bytes(b"corrupted-partial-data")

    # Pending store must reject partial staging and return None
    assert pending_store.load_verified(local_v1) is None
    dummy_apply = SoftwareUpdateApplyService(root_dir=tmp_path)
    assert (
        try_apply_pending_on_launch(
            pending_store=pending_store,
            apply_service=dummy_apply,
            game_active=lambda: False,
            local_identity_provider=lambda: local_v1,
        )
        == PendingUpdateBootstrapResult.NONE
    )

    # 2. Simulate download network failure midway during coordinator startup
    adl = stage_service._asset_downloader
    original_download = adl.download

    def failing_download(*args: Any, **kwargs: Any) -> Any:
        raise GitHubAssetDownloadError("CONNECTION_RESET")

    adl.download = failing_download  # type: ignore[assignment]

    fail_snapshot = coordinator.startup()
    assert fail_snapshot.state == UpdateLifecycleState.IDLE
    assert fail_snapshot.pending is None
    assert pending_store.load_verified(local_v1) is None

    # 3. Restore network; coordinator cleans incomplete staging and succeeds on retry
    adl.download = original_download  # type: ignore[assignment]
    retry_coordinator, retry_stage, retry_store, _ = _setup_coordinator_pipeline(
        tmp_path,
        env,
        store,
        opener,
        local_v1,
    )

    recovered_snapshot = retry_coordinator.startup()
    assert recovered_snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert recovered_snapshot.pending is not None
    assert recovered_snapshot.pending.release_sequence == 2

    # Verify orphaned directory was cleaned up
    assert not orphaned_stage.exists()


def test_deferred_update_completed_pending_restart(tmp_path: Path) -> None:
    """Step 3b: Crash/retry - completed pending update survives restart and is

    discoverable offline without any network calls.
    """
    env, store, updater_bytes, routes = _build_simulation_fixtures(tmp_path)
    opener = ReusableFakeTransportOpener(routes)

    local_v1 = LocalReleaseIdentity(
        release_sequence=1,
        release_id="rel-1",
        launcher_version="1.0.0",
        launcher_installed_identity_sha256=env.old_launcher_sha,
        core_version="1.0.0",
        core_installed_identity_sha256=env.old_core_id,
    )

    coordinator, stage_service, pending_store, _ = _setup_coordinator_pipeline(
        tmp_path,
        env,
        store,
        opener,
        local_v1,
    )

    # Stage pending update
    staged_snapshot = coordinator.startup()
    assert staged_snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert staged_snapshot.pending is not None
    assert staged_snapshot.pending.release_sequence == 2

    # Simulate Launcher process restart in complete offline mode
    routes.clear()
    offline_opener = ReusableFakeTransportOpener({})
    restart_coordinator, _, restart_store, _ = _setup_coordinator_pipeline(
        tmp_path,
        env,
        store,
        offline_opener,
        local_v1,
    )

    # current() discovers verified pending from disk immediately with ZERO network requests
    curr_snapshot = restart_coordinator.current()
    assert curr_snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert curr_snapshot.pending is not None
    assert curr_snapshot.pending.release_sequence == 2
    assert len(offline_opener.captured_requests) == 0

    # startup() offline preserves the verified pending update
    startup_snapshot = restart_coordinator.startup()
    assert startup_snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert startup_snapshot.pending is not None
    assert startup_snapshot.pending.release_sequence == 2


def test_deferred_update_duplicate_startup_callback(tmp_path: Path) -> None:
    """Step 3c: Crash/retry - concurrent and duplicate startup callbacks are

    coalesced to a single staging pipeline and invoked exactly once.
    """
    env, store, updater_bytes, routes = _build_simulation_fixtures(tmp_path)
    opener = ReusableFakeTransportOpener(routes)

    local_v1 = LocalReleaseIdentity(
        release_sequence=1,
        release_id="rel-1",
        launcher_version="1.0.0",
        launcher_installed_identity_sha256=env.old_launcher_sha,
        core_version="1.0.0",
        core_installed_identity_sha256=env.old_core_id,
    )

    coordinator, stage_service, pending_store, _ = _setup_coordinator_pipeline(
        tmp_path,
        env,
        store,
        opener,
        local_v1,
    )

    received_snapshots: list[UpdateLifecycleSnapshot] = []
    cb_lock = threading.Lock()

    def cb(snap: UpdateLifecycleSnapshot) -> None:
        with cb_lock:
            received_snapshots.append(snap)

    # Spawn 5 concurrent startup requests
    threads = [
        threading.Thread(target=coordinator.startup, kwargs={"callback": cb})
        for _ in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    # All 5 callbacks received the identical snapshot
    assert len(received_snapshots) == 5
    for snap in received_snapshots:
        assert snap.state == UpdateLifecycleState.UPDATE_PENDING
        assert snap.pending is not None
        assert snap.pending.release_sequence == 2

    # Subsequent callback registered after completion executes immediately without deadlocking
    post_completion_snapshots: list[UpdateLifecycleSnapshot] = []
    coordinator.startup(callback=lambda s: post_completion_snapshots.append(s))
    assert len(post_completion_snapshots) == 1
    assert (
        post_completion_snapshots[0].state
        == UpdateLifecycleState.UPDATE_PENDING
    )


def test_deferred_update_higher_pending_supersession(tmp_path: Path) -> None:
    """Step 3d: Crash/retry - newer N+2 candidate atomically supersedes N+1 pending

    update prior to apply, and offline apply commits N+2 directly.
    """
    env, store, updater_bytes, routes = _build_simulation_fixtures(tmp_path)
    opener = ReusableFakeTransportOpener(routes)

    local_v1 = LocalReleaseIdentity(
        release_sequence=1,
        release_id="rel-1",
        launcher_version="1.0.0",
        launcher_installed_identity_sha256=env.old_launcher_sha,
        core_version="1.0.0",
        core_installed_identity_sha256=env.old_core_id,
    )

    coordinator, stage_service, pending_store, resolver = (
        _setup_coordinator_pipeline(
            tmp_path,
            env,
            store,
            opener,
            local_v1,
        )
    )

    # 1. Stage N+1
    snap1 = coordinator.startup()
    assert snap1.pending is not None
    assert snap1.pending.release_sequence == 2
    gen_2_dir = snap1.pending.generation_dir
    assert gen_2_dir.is_dir()

    # 2. Before applying N+1, N+2 becomes available online
    n_plus_two = _retarget_as_launcher_only_n_plus_two(env, routes)
    tag = "v1.0.1"
    release_base = f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/"
    cdn_base = "https://objects.githubusercontent.com/test-assets-n-plus-two/"
    routes.update({
        release_base + CORE_ASSET_NAME: _SimulatedHttpResponse(
            status=302, headers={"Location": cdn_base + CORE_ASSET_NAME}
        ),
        cdn_base + CORE_ASSET_NAME: _SimulatedHttpResponse(env.new_core_zip_bytes),
    })

    opener2 = ReusableFakeTransportOpener(routes)
    coordinator2, stage_service2, pending_store2, resolver2 = (
        _setup_coordinator_pipeline(
            tmp_path,
            env,
            store,
            opener2,
            local_v1,
        )
    )

    snap2 = coordinator2.startup()
    assert snap2.pending is not None
    assert snap2.pending.release_sequence == 3
    assert snap2.pending.release_id == "rel-3"

    # Verify N+1 pending artifacts were superseded / cleaned up
    assert not gen_2_dir.exists()
    assert snap2.pending.generation_dir.is_dir()

    # 3. Offline apply consumes N+2 directly
    routes.clear()
    apply_service, proc_refs, exit_codes, _ = _create_helper_runner(
        tmp_path,
        env.keys,
        store,
        self_test_pass=True,
    )

    res = try_apply_pending_on_launch(
        pending_store=pending_store2,
        apply_service=apply_service,
        game_active=lambda: False,
        local_identity_provider=lambda: local_v1,
    )
    assert res == PendingUpdateBootstrapResult.HANDOFF_STARTED
    proc_refs[0].thread.join(timeout=10.0)
    assert exit_codes[0] == 0

    # 4. Verify SlotStore committed N+2 directly
    state = store.state
    assert state is not None
    assert state.committed == n_plus_two
    assert state.previous == env.old
    assert state.highwater == n_plus_two.binding
    assert state.failed is None


def test_deferred_update_no_production_network_mutation(tmp_path: Path) -> None:
    """Security verification: ensures no production network endpoints or secrets

    are touched throughout discovery and staging.
    """
    env, store, updater_bytes, routes = _build_simulation_fixtures(tmp_path)
    opener = ReusableFakeTransportOpener(routes)

    local_v1 = LocalReleaseIdentity(
        release_sequence=1,
        release_id="rel-1",
        launcher_version="1.0.0",
        launcher_installed_identity_sha256=env.old_launcher_sha,
        core_version="1.0.0",
        core_installed_identity_sha256=env.old_core_id,
    )

    coordinator, _, _, _ = _setup_coordinator_pipeline(
        tmp_path,
        env,
        store,
        opener,
        local_v1,
    )
    coordinator.startup()

    _assert_public_unauthenticated_requests(opener)
