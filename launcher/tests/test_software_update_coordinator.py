from __future__ import annotations

import hashlib
import inspect
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
import threading

from neko_launcher.application.software_update_coordinator import (
    SoftwareUpdateCoordinator,
    UpdateLifecycleSnapshot,
)
from neko_launcher.application.software_update_models import (
    LocalReleaseIdentity,
    UpdateLifecycleState,
    UpdateState,
)
from neko_launcher.application.software_update_service import UpdateCheckService
from neko_launcher.infrastructure.github_asset_downloader import (
    DownloadedArtifact,
    GitHubAssetDownloadError,
)
from neko_launcher.infrastructure.github_release import (
    GitHubRelease,
    GitHubReleaseAsset,
)
from neko_launcher.infrastructure.github_release_binding import (
    AuthenticatedReleaseGateway,
    ResolvedGitHubRelease,
)
from neko_launcher.infrastructure.software_update_pending_store import (
    PendingUpdateStore,
)
from neko_launcher.infrastructure.software_update_stage import (
    SoftwareUpdateStageService,
)
from neko_launcher.infrastructure.software_update_v2 import (
    V2ReleaseManifestVerifierAdapter,
)
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
from tests.software_update_helpers import (
    get_test_key_registry,
    signed_envelope,
    valid_v2_release_document,
)


class CodedError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


class TrackingGateway(AuthenticatedReleaseGateway):
    def __init__(
        self,
        resolved: ResolvedGitHubRelease | None = None,
        error: Exception | None = None,
        *,
        blocking: bool = False,
    ) -> None:
        self.resolved = resolved
        self.error = error
        self.calls = 0
        self.blocking = blocking
        self.entered = threading.Event()
        self.release_event = threading.Event()
        self._lock = threading.Lock()

    def resolve(self) -> ResolvedGitHubRelease | None:
        with self._lock:
            self.calls += 1
        self.entered.set()
        if self.blocking and not self.release_event.wait(timeout=5):
            raise TimeoutError("Test gateway wait timed out")
        if self.error is not None:
            raise self.error
        return self.resolved


class FakeAssetDownloader:
    def __init__(
        self,
        payloads: dict[str, bytes] | None = None,
        default_error: Exception | None = None,
    ) -> None:
        self.payloads = dict(payloads or {})
        self.default_error = default_error
        self.download_calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def download(
        self,
        *,
        initial_url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
    ) -> DownloadedArtifact:
        with self._lock:
            self.download_calls.append({
                "initial_url": initial_url,
                "destination": Path(destination),
                "expected_size": expected_size,
                "expected_sha256": expected_sha256,
            })
        if self.default_error is not None:
            raise self.default_error

        if initial_url not in self.payloads:
            raise GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE")

        data = self.payloads[initial_url]
        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        return DownloadedArtifact(size=len(data), sha256=digest)


def _make_local_identity(
    *,
    sequence: int = 1,
    release_id: str = "r1-stable",
    launcher_version: str = "5.1.0",
    core_version: str = "1.0.0",
) -> LocalReleaseIdentity:
    return LocalReleaseIdentity(
        release_sequence=sequence,
        release_id=release_id,
        launcher_version=launcher_version,
        launcher_installed_identity_sha256="0" * 64,
        core_version=core_version,
        core_installed_identity_sha256="0" * 64,
    )


def _make_resolved_release(
    *,
    sequence: int = 2,
    release_id: str = "r2-stable",
    channel: str = "stable",
    mandatory: bool = False,
    minimum_supported_sequence: int = 1,
    launcher_version: str = "5.1.1",
    launcher_bytes: bytes = b"MZ-launcher-binary-v2",
    core_version: str = "1.0.1",
    core_bytes: bytes = b"PK-core-zip-v2",
    updater_version: str = "5.1.0",
    updater_bytes: bytes = b"MZ-updater-helper-binary",
) -> tuple[ResolvedGitHubRelease, dict[str, bytes]]:
    keys = get_test_key_registry()
    l_sha = hashlib.sha256(launcher_bytes).hexdigest()
    c_sha = hashlib.sha256(core_bytes).hexdigest()
    u_sha = hashlib.sha256(updater_bytes).hexdigest()

    doc = valid_v2_release_document(
        sequence=sequence,
        release_id=release_id,
        channel=channel,
        mandatory=mandatory,
        minimum_supported_sequence=minimum_supported_sequence,
        launcher_version=launcher_version,
        launcher_sha=l_sha,
        launcher_size=len(launcher_bytes),
        updater_version=updater_version,
        updater_sha=u_sha,
        updater_size=len(updater_bytes),
        core_version=core_version,
        core_sha=c_sha,
        core_size=len(core_bytes),
        core_installed_sha=c_sha,
    )

    env = signed_envelope(doc)
    env_bytes = canonical_json_dumps(env)

    adapter = V2ReleaseManifestVerifierAdapter(keys, updater_protocol=1)
    authenticated_release = adapter.verify(env)
    release_v2, _ = verify_release_envelope_v2(env, keys)

    launcher_url = f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/NekoLauncher.exe"
    updater_url = f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/NekoUpdater.exe"
    core_url = f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/NekoProxyCore.zip"
    manifest_url = f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/release-v2.json"

    launcher_asset = GitHubReleaseAsset(id=1, name="NekoLauncher.exe", size=len(launcher_bytes), browser_download_url=launcher_url)
    updater_asset = GitHubReleaseAsset(id=2, name="NekoUpdater.exe", size=len(updater_bytes), browser_download_url=updater_url)
    core_asset = GitHubReleaseAsset(id=3, name="NekoProxyCore.zip", size=len(core_bytes), browser_download_url=core_url)
    manifest_asset = GitHubReleaseAsset(id=4, name="release-v2.json", size=len(env_bytes), browser_download_url=manifest_url)

    gh_release = GitHubRelease(
        id=10,
        tag_name=f"v{launcher_version}",
        draft=False,
        prerelease=False,
        assets=(manifest_asset, launcher_asset, updater_asset, core_asset),
    )

    resolved = ResolvedGitHubRelease(
        authenticated_release=authenticated_release,
        authenticated_release_v2=release_v2,
        github_release=gh_release,
        manifest_asset=manifest_asset,
        launcher_asset=launcher_asset,
        updater_asset=updater_asset,
        core_asset=core_asset,
        envelope_bytes=env_bytes,
        envelope_document=env,
    )
    payloads = {
        launcher_url: launcher_bytes,
        core_url: core_bytes,
    }
    return resolved, payloads


def _setup_coordinator(
    tmp_path: Path,
    gateway: AuthenticatedReleaseGateway,
    downloader: FakeAssetDownloader,
    local_id: LocalReleaseIdentity | None = None,
) -> tuple[SoftwareUpdateCoordinator, PendingUpdateStore, SoftwareUpdateStageService]:
    keys = get_test_key_registry()
    local = local_id or _make_local_identity()
    store = PendingUpdateStore(tmp_path, keys, updater_protocol=1)
    stage_service = SoftwareUpdateStageService(
        pending_store=store,
        asset_downloader=downloader,
    )
    check_service = UpdateCheckService(gateway, lambda: local)
    coordinator = SoftwareUpdateCoordinator(
        check_service=check_service,
        stage_service=stage_service,
        pending_store=store,
        local_identity_provider=lambda: local,
    )
    return coordinator, store, stage_service


def test_coordinator_public_interfaces() -> None:
    # Verify UpdateLifecycleSnapshot signature
    snap_fields = {f.name for f in inspect.signature(UpdateLifecycleSnapshot).parameters.values()}
    assert snap_fields == {"state", "check_result", "pending", "diagnostic_code"}

    # Verify SoftwareUpdateCoordinator methods
    assert hasattr(SoftwareUpdateCoordinator, "startup")
    assert hasattr(SoftwareUpdateCoordinator, "manual_check")
    assert hasattr(SoftwareUpdateCoordinator, "current")


def test_current_idle_when_store_has_no_pending(tmp_path: Path) -> None:
    gateway = TrackingGateway(resolved=None)
    downloader = FakeAssetDownloader()
    coordinator, _, _ = _setup_coordinator(tmp_path, gateway, downloader)

    snapshot = coordinator.current()
    assert snapshot.state == UpdateLifecycleState.IDLE
    assert snapshot.pending is None
    assert snapshot.check_result is None
    assert snapshot.diagnostic_code is None
    assert gateway.calls == 0


def test_pending_first_load_without_online_check(tmp_path: Path) -> None:
    keys = get_test_key_registry()
    local = _make_local_identity(sequence=1)
    store = PendingUpdateStore(tmp_path, keys, updater_protocol=1)

    # Pre-stage verified pending update for sequence 2
    resolved, payloads = _make_resolved_release(sequence=2)
    downloader = FakeAssetDownloader(payloads)
    stage_service = SoftwareUpdateStageService(pending_store=store, asset_downloader=downloader)
    pre_staged = stage_service.stage(resolved, local)
    assert pre_staged is not None

    # Now create coordinator
    gateway = TrackingGateway(resolved=None)
    check_service = UpdateCheckService(gateway, lambda: local)
    coordinator = SoftwareUpdateCoordinator(
        check_service=check_service,
        stage_service=stage_service,
        pending_store=store,
        local_identity_provider=lambda: local,
    )

    # Calling current() before startup() loads verified pending from disk
    snapshot = coordinator.current()
    assert snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot.pending is not None
    assert snapshot.pending.release_sequence == 2
    assert snapshot.check_result is None
    assert snapshot.diagnostic_code is None
    assert gateway.calls == 0


def test_every_process_startup_performs_check_and_stages_valid_newer(tmp_path: Path) -> None:
    resolved, payloads = _make_resolved_release(sequence=2)
    gateway = TrackingGateway(resolved=resolved)
    downloader = FakeAssetDownloader(payloads)
    coordinator, store, _ = _setup_coordinator(tmp_path, gateway, downloader)

    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot.pending is not None
    assert snapshot.pending.release_sequence == 2
    assert snapshot.check_result is not None
    assert snapshot.check_result.state == UpdateState.AVAILABLE
    assert snapshot.diagnostic_code is None
    assert gateway.calls == 1

    # Verify store has the pending update
    loaded = store.load_verified(_make_local_identity())
    assert loaded is not None
    assert loaded.release_sequence == 2


def test_startup_single_flight_sequential(tmp_path: Path) -> None:
    resolved, payloads = _make_resolved_release(sequence=2)
    gateway = TrackingGateway(resolved=resolved)
    downloader = FakeAssetDownloader(payloads)
    coordinator, _, _ = _setup_coordinator(tmp_path, gateway, downloader)

    first = coordinator.startup()
    second = coordinator.startup()

    assert gateway.calls == 1
    assert first is second


def test_startup_single_flight_concurrent(tmp_path: Path) -> None:
    resolved, payloads = _make_resolved_release(sequence=2)
    gateway = TrackingGateway(resolved=resolved, blocking=True)
    downloader = FakeAssetDownloader(payloads)
    coordinator, _, _ = _setup_coordinator(tmp_path, gateway, downloader)

    results: list[UpdateLifecycleSnapshot] = []

    def worker() -> UpdateLifecycleSnapshot:
        return coordinator.startup()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker) for _ in range(8)]
        assert gateway.entered.wait(timeout=2)
        gateway.release_event.set()
        for f in futures:
            results.append(f.result(timeout=5))

    assert gateway.calls == 1
    assert len(results) == 8
    assert all(r is results[0] for r in results)


def test_concurrent_startup_callbacks_coalesced(tmp_path: Path) -> None:
    resolved, payloads = _make_resolved_release(sequence=2)
    gateway = TrackingGateway(resolved=resolved, blocking=True)
    downloader = FakeAssetDownloader(payloads)
    coordinator, _, _ = _setup_coordinator(tmp_path, gateway, downloader)

    cb_results: list[UpdateLifecycleSnapshot] = []
    cb_lock = threading.Lock()

    def make_cb():
        def cb(snap: UpdateLifecycleSnapshot) -> None:
            with cb_lock:
                cb_results.append(snap)
        return cb

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(coordinator.startup, make_cb()) for _ in range(5)]
        assert gateway.entered.wait(timeout=2)
        gateway.release_event.set()
        for f in futures:
            f.result(timeout=5)

    assert gateway.calls == 1
    assert len(cb_results) == 5
    assert all(r is cb_results[0] for r in cb_results)


def test_manual_check_independence_does_not_mutate_startup_result(tmp_path: Path) -> None:
    resolved_r2, payloads_r2 = _make_resolved_release(sequence=2, release_id="r2-beta")
    resolved_r3, payloads_r3 = _make_resolved_release(sequence=3, release_id="r3-beta")

    gateway = TrackingGateway(resolved=resolved_r2)
    downloader = FakeAssetDownloader({**payloads_r2, **payloads_r3})
    coordinator, _, _ = _setup_coordinator(tmp_path, gateway, downloader)

    # Startup finishes with sequence 2
    startup_snap = coordinator.startup()
    assert startup_snap.pending is not None
    assert startup_snap.pending.release_sequence == 2
    assert gateway.calls == 1

    # Remote updates to sequence 3
    gateway.resolved = resolved_r3
    manual_snap = coordinator.manual_check()
    assert manual_snap.pending is not None
    assert manual_snap.pending.release_sequence == 3
    assert gateway.calls == 2

    # Subsequent startup() returns cached sequence 2 snapshot
    cached_startup = coordinator.startup()
    assert cached_startup is startup_snap
    assert cached_startup.pending.release_sequence == 2

    # current() reflects the latest manual_check result
    current_snap = coordinator.current()
    assert current_snap.pending.release_sequence == 3


def test_offline_with_existing_pending_preserves_verified_pending(tmp_path: Path) -> None:
    keys = get_test_key_registry()
    local = _make_local_identity(sequence=1)
    store = PendingUpdateStore(tmp_path, keys, updater_protocol=1)

    # Pre-stage sequence 2
    resolved, payloads = _make_resolved_release(sequence=2)
    downloader = FakeAssetDownloader(payloads)
    stage_service = SoftwareUpdateStageService(pending_store=store, asset_downloader=downloader)
    pre_staged = stage_service.stage(resolved, local)
    assert pre_staged is not None

    # Gateway simulates offline network error
    gateway = TrackingGateway(error=CodedError("MANIFEST_UNAVAILABLE", "network is unreachable"))
    check_service = UpdateCheckService(gateway, lambda: local)
    coordinator = SoftwareUpdateCoordinator(
        check_service=check_service,
        stage_service=stage_service,
        pending_store=store,
        local_identity_provider=lambda: local,
    )

    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot.pending is not None
    assert snapshot.pending.release_sequence == 2
    assert snapshot.check_result is not None
    assert snapshot.check_result.state == UpdateState.UNAVAILABLE
    assert snapshot.diagnostic_code == "MANIFEST_UNAVAILABLE"

    # Store still has valid pending update
    assert store.load_verified(local) is not None


def test_invalid_remote_preserves_verified_pending(tmp_path: Path) -> None:
    keys = get_test_key_registry()
    local = _make_local_identity(sequence=1)
    store = PendingUpdateStore(tmp_path, keys, updater_protocol=1)

    # Pre-stage sequence 2
    resolved, payloads = _make_resolved_release(sequence=2)
    downloader = FakeAssetDownloader(payloads)
    stage_service = SoftwareUpdateStageService(pending_store=store, asset_downloader=downloader)
    pre_staged = stage_service.stage(resolved, local)
    assert pre_staged is not None

    # Gateway simulates invalid manifest signature
    gateway = TrackingGateway(error=CodedError("SIGNATURE_INVALID", "signature check failed"))
    check_service = UpdateCheckService(gateway, lambda: local)
    coordinator = SoftwareUpdateCoordinator(
        check_service=check_service,
        stage_service=stage_service,
        pending_store=store,
        local_identity_provider=lambda: local,
    )

    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot.pending is not None
    assert snapshot.pending.release_sequence == 2
    assert snapshot.check_result is not None
    assert snapshot.check_result.state == UpdateState.VERIFY_FAILED
    assert snapshot.diagnostic_code == "MANIFEST_REJECTED"

    # Store still has valid pending update
    assert store.load_verified(local) is not None


def test_online_newer_supersedes_existing_pending(tmp_path: Path) -> None:
    keys = get_test_key_registry()
    local = _make_local_identity(sequence=1)
    store = PendingUpdateStore(tmp_path, keys, updater_protocol=1)

    # Pre-stage sequence 2
    resolved_r2, payloads_r2 = _make_resolved_release(sequence=2, release_id="r2-beta")
    resolved_r3, payloads_r3 = _make_resolved_release(sequence=3, release_id="r3-beta")

    downloader = FakeAssetDownloader({**payloads_r2, **payloads_r3})
    stage_service = SoftwareUpdateStageService(pending_store=store, asset_downloader=downloader)
    pre_staged = stage_service.stage(resolved_r2, local)
    assert pre_staged is not None
    assert store.load_verified(local).release_sequence == 2

    # Now startup with remote having sequence 3
    gateway = TrackingGateway(resolved=resolved_r3)
    check_service = UpdateCheckService(gateway, lambda: local)
    coordinator = SoftwareUpdateCoordinator(
        check_service=check_service,
        stage_service=stage_service,
        pending_store=store,
        local_identity_provider=lambda: local,
    )

    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot.pending is not None
    assert snapshot.pending.release_sequence == 3
    assert snapshot.diagnostic_code is None

    # Store active pointer is now sequence 3
    active = store.load_verified(local)
    assert active is not None
    assert active.release_sequence == 3


def test_same_sequence_already_pending_does_not_redownload(tmp_path: Path) -> None:
    keys = get_test_key_registry()
    local = _make_local_identity(sequence=1)
    store = PendingUpdateStore(tmp_path, keys, updater_protocol=1)

    resolved, payloads = _make_resolved_release(sequence=2, release_id="r2-beta")
    downloader = FakeAssetDownloader(payloads)
    stage_service = SoftwareUpdateStageService(pending_store=store, asset_downloader=downloader)
    pre_staged = stage_service.stage(resolved, local)
    assert pre_staged is not None
    initial_download_calls = len(downloader.download_calls)

    gateway = TrackingGateway(resolved=resolved)
    check_service = UpdateCheckService(gateway, lambda: local)
    coordinator = SoftwareUpdateCoordinator(
        check_service=check_service,
        stage_service=stage_service,
        pending_store=store,
        local_identity_provider=lambda: local,
    )

    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot.pending is not None
    assert snapshot.pending.release_sequence == 2
    # No additional downloads occurred
    assert len(downloader.download_calls) == initial_download_calls


def test_staging_download_failure_preserves_prior_pending(tmp_path: Path) -> None:
    keys = get_test_key_registry()
    local = _make_local_identity(sequence=1)
    store = PendingUpdateStore(tmp_path, keys, updater_protocol=1)

    resolved_r2, payloads_r2 = _make_resolved_release(sequence=2, release_id="r2-beta")
    resolved_r3, _ = _make_resolved_release(sequence=3, release_id="r3-beta")

    downloader = FakeAssetDownloader(payloads_r2)
    stage_service = SoftwareUpdateStageService(pending_store=store, asset_downloader=downloader)
    pre_staged = stage_service.stage(resolved_r2, local)
    assert pre_staged is not None

    # Now make downloader fail for sequence 3
    downloader.default_error = GitHubAssetDownloadError("DOWNLOAD_FAILED")

    gateway = TrackingGateway(resolved=resolved_r3)
    check_service = UpdateCheckService(gateway, lambda: local)
    coordinator = SoftwareUpdateCoordinator(
        check_service=check_service,
        stage_service=stage_service,
        pending_store=store,
        local_identity_provider=lambda: local,
    )

    snapshot = coordinator.startup()
    # Prior pending sequence 2 is preserved
    assert snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot.pending is not None
    assert snapshot.pending.release_sequence == 2
    assert snapshot.diagnostic_code == "DOWNLOAD_FAILED"
    assert store.load_verified(local).release_sequence == 2


def test_startup_cleans_incomplete_staging_after_preserving_pending(tmp_path: Path) -> None:
    keys = get_test_key_registry()
    local = _make_local_identity(sequence=1)
    store = PendingUpdateStore(tmp_path, keys, updater_protocol=1)

    resolved, payloads = _make_resolved_release(sequence=2, release_id="r2-beta")
    downloader = FakeAssetDownloader(payloads)
    stage_service = SoftwareUpdateStageService(pending_store=store, asset_downloader=downloader)
    pre_staged = stage_service.stage(resolved, local)
    assert pre_staged is not None

    # Create orphan temporary staging directory simulating a crash
    crash_dir = store.base_dir / "tmp_stage_crash123"
    crash_dir.mkdir(parents=True, exist_ok=True)
    (crash_dir / "partial.tmp").write_bytes(b"corrupt")
    assert crash_dir.exists()

    gateway = TrackingGateway(resolved=resolved)
    check_service = UpdateCheckService(gateway, lambda: local)
    coordinator = SoftwareUpdateCoordinator(
        check_service=check_service,
        stage_service=stage_service,
        pending_store=store,
        local_identity_provider=lambda: local,
    )

    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot.pending.release_sequence == 2
    # Incomplete dir was cleaned up
    assert not crash_dir.exists()


def test_diagnostics_privacy_sanitizes_errors(tmp_path: Path) -> None:
    sensitive_msg = "https://secret.token@example.com/asset?key=SECRET123"
    gateway = TrackingGateway(error=RuntimeError(sensitive_msg))
    downloader = FakeAssetDownloader()
    coordinator, _, _ = _setup_coordinator(tmp_path, gateway, downloader)

    snapshot = coordinator.startup()
    assert snapshot.diagnostic_code == "UPDATE_CHECK_INTERNAL_FAILURE"
    assert "secret.token" not in repr(snapshot)
    assert "SECRET123" not in repr(snapshot)
    assert "secret.token" not in str(snapshot)
    assert "SECRET123" not in str(snapshot)


def test_no_duplicate_cross_process_mutex() -> None:
    import neko_launcher.application.software_update_coordinator as coord_mod
    src = inspect.getsource(coord_mod)
    forbidden_tokens = ["CreateMutex", "OpenMutex", "win32event", "named_mutex", "ipc"]
    for token in forbidden_tokens:
        assert token not in src, f"Forbidden cross-process sync token '{token}' in coordinator"


def test_exception_in_startup_does_not_strand_waiters(tmp_path: Path) -> None:
    gateway = TrackingGateway(error=RuntimeError("unexpected gateway crash"), blocking=True)
    downloader = FakeAssetDownloader()
    coordinator, _, _ = _setup_coordinator(tmp_path, gateway, downloader)

    results: list[UpdateLifecycleSnapshot] = []

    def worker() -> UpdateLifecycleSnapshot:
        return coordinator.startup()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker) for _ in range(4)]
        assert gateway.entered.wait(timeout=2)
        gateway.release_event.set()
        for f in futures:
            results.append(f.result(timeout=5))

    assert len(results) == 4
    for r in results:
        assert r.state == UpdateLifecycleState.IDLE
        assert r.diagnostic_code == "UPDATE_CHECK_INTERNAL_FAILURE"


def test_startup_callback_after_completion_invokes_outside_lock_without_deadlock(
    tmp_path: Path,
) -> None:
    resolved, payloads = _make_resolved_release(sequence=2)
    gateway = TrackingGateway(resolved=resolved)
    downloader = FakeAssetDownloader(payloads)
    coordinator, _, _ = _setup_coordinator(tmp_path, gateway, downloader)

    initial_snap = coordinator.startup()
    assert initial_snap is not None

    callback_called = False
    current_inside_cb: UpdateLifecycleSnapshot | None = None
    call_result: list[UpdateLifecycleSnapshot] = []

    def reentrant_callback(snap: UpdateLifecycleSnapshot) -> None:
        nonlocal callback_called, current_inside_cb
        callback_called = True
        # Must be able to call current() without deadlocking on coordinator._lock
        current_inside_cb = coordinator.current()

    def runner() -> None:
        call_result.append(coordinator.startup(reentrant_callback))

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout=1.0)

    assert not thread.is_alive(), "startup(reentrant_callback) deadlocked when calling current()"
    assert callback_called is True
    assert len(call_result) == 1
    assert call_result[0] is initial_snap
    assert current_inside_cb is initial_snap


def test_post_startup_callbacks_not_retained_and_do_not_grow_state(
    tmp_path: Path,
) -> None:
    resolved, payloads = _make_resolved_release(sequence=2)
    gateway = TrackingGateway(resolved=resolved)
    downloader = FakeAssetDownloader(payloads)
    coordinator, _, _ = _setup_coordinator(tmp_path, gateway, downloader)

    coordinator.startup()
    assert len(coordinator._startup_callbacks) == 0

    def dummy_cb(snap: UpdateLifecycleSnapshot) -> None:
        pass

    for _ in range(10):
        coordinator.startup(dummy_cb)

    assert len(coordinator._startup_callbacks) == 0


def test_concurrent_startup_callbacks_invoked_exactly_once_with_current_access(
    tmp_path: Path,
) -> None:
    resolved, payloads = _make_resolved_release(sequence=2)
    gateway = TrackingGateway(resolved=resolved, blocking=True)
    downloader = FakeAssetDownloader(payloads)
    coordinator, _, _ = _setup_coordinator(tmp_path, gateway, downloader)

    call_counts: dict[int, int] = {}
    current_results: dict[int, UpdateLifecycleSnapshot] = {}
    lock = threading.Lock()

    def make_cb(idx: int):
        def cb(snap: UpdateLifecycleSnapshot) -> None:
            with lock:
                call_counts[idx] = call_counts.get(idx, 0) + 1
                current_results[idx] = coordinator.current()
        return cb

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(coordinator.startup, make_cb(i)) for i in range(6)]
        assert gateway.entered.wait(timeout=2)
        gateway.release_event.set()
        for f in futures:
            f.result(timeout=5)

    assert gateway.calls == 1
    assert len(call_counts) == 6
    for i in range(6):
        assert call_counts[i] == 1
        assert current_results[i] is not None
    assert len(coordinator._startup_callbacks) == 0
