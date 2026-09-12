import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from neko_launcher.application.software_update_models import LocalReleaseIdentity
from neko_launcher.updater.manifest_v2 import parse_release_v2
try:
    from tests.software_update_helpers import (
        get_test_key_registry,
        signed_envelope,
        valid_v2_release_document,
    )
except ImportError:
    try:
        from software_update_helpers import (  # type: ignore[no-redef]
            get_test_key_registry,
            signed_envelope,
            valid_v2_release_document,
        )
    except ImportError:
        from launcher.tests.software_update_helpers import (  # type: ignore[no-redef]
            get_test_key_registry,
            signed_envelope,
            valid_v2_release_document,
        )

from neko_launcher.bootstrap.pending_update_bootstrap import (
    PendingUpdateBootstrapResult,
    is_game_active_early,
    run_pending_update_bootstrap,
    try_apply_pending_on_launch,
)
from neko_launcher.infrastructure.software_update_apply import (
    SoftwareUpdateApplyError,
)
from neko_launcher.infrastructure.software_update_pending_store import (
    PendingUpdateStore,
)


def _make_fixture_payload(
    tmp_path: Path,
    *,
    sequence: int = 2,
    release_id: str = "r2-stable",
    launcher_bytes: bytes = b"MZ-test-launcher-binary-content-12345",
    core_bytes: bytes = b"PK-test-core-zip-content-67890",
    updater_bytes: bytes = b"MZ-test-updater-binary-content",
    proto_min: int = 1,
    proto_max: int = 1,
    channel: str = "stable",
):
    launcher_sha = hashlib.sha256(launcher_bytes).hexdigest()
    core_sha = hashlib.sha256(core_bytes).hexdigest()
    updater_sha = hashlib.sha256(updater_bytes).hexdigest()

    doc = valid_v2_release_document(
        sequence=sequence,
        release_id=release_id,
        channel=channel,
        proto_min=proto_min,
        proto_max=proto_max,
        launcher_sha=launcher_sha,
        launcher_size=len(launcher_bytes),
        updater_sha=updater_sha,
        updater_size=len(updater_bytes),
        core_sha=core_sha,
        core_size=len(core_bytes),
        core_installed_sha=core_sha,
    )
    envelope = signed_envelope(doc)
    envelope_bytes = json.dumps(envelope).encode("utf-8")
    parsed_release = parse_release_v2(doc)

    stage_dir = tmp_path / f"staged_source_{sequence}_{release_id}"
    stage_dir.mkdir(parents=True, exist_ok=True)
    launcher_path = stage_dir / "launcher.exe"
    launcher_path.write_bytes(launcher_bytes)
    core_path = stage_dir / "core.zip"
    core_path.write_bytes(core_bytes)

    staged_files = {
        "launcher": launcher_path,
        "core": core_path,
    }

    return parsed_release, envelope_bytes, staged_files, launcher_bytes, core_bytes


def _local_identity_seq_1():
    return LocalReleaseIdentity(
        release_sequence=1,
        release_id="r1-stable",
        launcher_version="5.1.0",
        launcher_installed_identity_sha256="0" * 64,
        core_version="1.0.0",
        core_installed_identity_sha256="0" * 64,
    )


def test_bootstrap_returns_none_when_no_pending_update(tmp_path: Path):
    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    apply_service = MagicMock()
    game_active = MagicMock(return_value=False)
    local_identity_provider = MagicMock(return_value=_local_identity_seq_1())

    result = try_apply_pending_on_launch(
        pending_store=store,
        apply_service=apply_service,
        game_active=game_active,
        local_identity_provider=local_identity_provider,
    )

    assert result == PendingUpdateBootstrapResult.NONE
    apply_service.prepare_pending.assert_not_called()


def test_bootstrap_hands_off_when_valid_pending_and_no_game(tmp_path: Path):
    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    release, env_bytes, staged_files, _, _ = _make_fixture_payload(
        tmp_path, sequence=2, release_id="r2-stable"
    )
    pending = store.promote(
        envelope_bytes=env_bytes,
        release=release,
        changed_components=("launcher", "core"),
        staged_files=staged_files,
    )

    mock_prepared = MagicMock()
    apply_service = MagicMock()
    apply_service.prepare_pending.return_value = mock_prepared

    game_active = MagicMock(return_value=False)
    local_identity_provider = MagicMock(return_value=_local_identity_seq_1())

    result = try_apply_pending_on_launch(
        pending_store=store,
        apply_service=apply_service,
        game_active=game_active,
        local_identity_provider=local_identity_provider,
    )

    assert result == PendingUpdateBootstrapResult.HANDOFF_STARTED
    apply_service.prepare_pending.assert_called_once_with(pending)
    mock_prepared.release.assert_called_once()


def test_bootstrap_defers_when_game_active(tmp_path: Path):
    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    release, env_bytes, staged_files, _, _ = _make_fixture_payload(
        tmp_path, sequence=2, release_id="r2-stable"
    )
    store.promote(
        envelope_bytes=env_bytes,
        release=release,
        changed_components=("launcher", "core"),
        staged_files=staged_files,
    )

    apply_service = MagicMock()
    game_active = MagicMock(return_value=True)
    local_identity_provider = MagicMock(return_value=_local_identity_seq_1())

    result = try_apply_pending_on_launch(
        pending_store=store,
        apply_service=apply_service,
        game_active=game_active,
        local_identity_provider=local_identity_provider,
    )

    assert result == PendingUpdateBootstrapResult.DEFERRED
    apply_service.prepare_pending.assert_not_called()
    # Pending update must be preserved in store
    assert store.load_verified(_local_identity_seq_1()) is not None


def test_bootstrap_rejects_tampered_pending_and_opens_normally(tmp_path: Path):
    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    release, env_bytes, staged_files, _, _ = _make_fixture_payload(
        tmp_path, sequence=2, release_id="r2-stable"
    )
    pending = store.promote(
        envelope_bytes=env_bytes,
        release=release,
        changed_components=("launcher", "core"),
        staged_files=staged_files,
    )

    # Tamper with core artifact
    assert pending.core_artifact is not None
    pending.core_artifact.write_bytes(b"tampered-bytes")

    apply_service = MagicMock()
    game_active = MagicMock(return_value=False)
    local_identity_provider = MagicMock(return_value=_local_identity_seq_1())

    result = try_apply_pending_on_launch(
        pending_store=store,
        apply_service=apply_service,
        game_active=game_active,
        local_identity_provider=local_identity_provider,
    )

    assert result == PendingUpdateBootstrapResult.NONE
    apply_service.prepare_pending.assert_not_called()


def test_bootstrap_clears_already_current_stale_record(tmp_path: Path):
    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    release, env_bytes, staged_files, _, _ = _make_fixture_payload(
        tmp_path, sequence=2, release_id="r2-stable"
    )
    store.promote(
        envelope_bytes=env_bytes,
        release=release,
        changed_components=("launcher", "core"),
        staged_files=staged_files,
    )

    # Local installation is already sequence 2 (update already applied)
    already_updated_identity = LocalReleaseIdentity(
        release_sequence=2,
        release_id="r2-stable",
        launcher_version="5.1.2",
        launcher_installed_identity_sha256="0" * 64,
        core_version="1.0.0",
        core_installed_identity_sha256="0" * 64,
    )

    apply_service = MagicMock()
    game_active = MagicMock(return_value=False)
    local_identity_provider = MagicMock(return_value=already_updated_identity)

    result = try_apply_pending_on_launch(
        pending_store=store,
        apply_service=apply_service,
        game_active=game_active,
        local_identity_provider=local_identity_provider,
    )

    assert result == PendingUpdateBootstrapResult.NONE
    apply_service.prepare_pending.assert_not_called()
    # Pointer and generation must be safely cleared
    assert not store.pointer_file.exists()


def test_bootstrap_preserves_pending_when_apply_preparation_fails(tmp_path: Path):
    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    release, env_bytes, staged_files, _, _ = _make_fixture_payload(
        tmp_path, sequence=2, release_id="r2-stable"
    )
    store.promote(
        envelope_bytes=env_bytes,
        release=release,
        changed_components=("launcher", "core"),
        staged_files=staged_files,
    )

    apply_service = MagicMock()
    apply_service.prepare_pending.side_effect = SoftwareUpdateApplyError("APPLY_REJECTED")

    game_active = MagicMock(return_value=False)
    local_identity_provider = MagicMock(return_value=_local_identity_seq_1())

    result = try_apply_pending_on_launch(
        pending_store=store,
        apply_service=apply_service,
        game_active=game_active,
        local_identity_provider=local_identity_provider,
    )

    # Fails closed, opens normally with pending preserved (deferred)
    assert result == PendingUpdateBootstrapResult.DEFERRED
    apply_service.prepare_pending.assert_called_once()
    # Pending update must still be intact and valid in store
    assert store.load_verified(_local_identity_seq_1()) is not None


def test_bootstrap_defers_when_game_observation_raises(tmp_path: Path):
    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    release, env_bytes, staged_files, _, _ = _make_fixture_payload(
        tmp_path, sequence=2, release_id="r2-stable"
    )
    store.promote(
        envelope_bytes=env_bytes,
        release=release,
        changed_components=("launcher", "core"),
        staged_files=staged_files,
    )

    apply_service = MagicMock()
    game_active = MagicMock(side_effect=RuntimeError("Process check failed"))
    local_identity_provider = MagicMock(return_value=_local_identity_seq_1())

    result = try_apply_pending_on_launch(
        pending_store=store,
        apply_service=apply_service,
        game_active=game_active,
        local_identity_provider=local_identity_provider,
    )

    # Must fail closed: defer rather than risk mutating during active game
    assert result == PendingUpdateBootstrapResult.DEFERRED
    apply_service.prepare_pending.assert_not_called()
    assert store.load_verified(_local_identity_seq_1()) is not None


def test_run_pending_update_bootstrap_safe_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # 1. When try_apply_pending_on_launch returns HANDOFF_STARTED
    monkeypatch.setattr(
        "neko_launcher.bootstrap.pending_update_bootstrap.try_apply_pending_on_launch",
        lambda **kwargs: PendingUpdateBootstrapResult.HANDOFF_STARTED,
    )
    res = run_pending_update_bootstrap(tmp_path, game_active=lambda: False)
    assert res == PendingUpdateBootstrapResult.HANDOFF_STARTED

    # 2. When try_apply_pending_on_launch returns DEFERRED
    monkeypatch.setattr(
        "neko_launcher.bootstrap.pending_update_bootstrap.try_apply_pending_on_launch",
        lambda **kwargs: PendingUpdateBootstrapResult.DEFERRED,
    )
    res = run_pending_update_bootstrap(tmp_path, game_active=lambda: True)
    assert res == PendingUpdateBootstrapResult.DEFERRED

    # 3. When unexpected exception occurs during composition
    monkeypatch.setattr(
        "neko_launcher.bootstrap.pending_update_bootstrap.try_apply_pending_on_launch",
        MagicMock(side_effect=RuntimeError("Unexpected startup crash")),
    )
    res = run_pending_update_bootstrap(tmp_path)
    assert res == PendingUpdateBootstrapResult.NONE


def test_is_game_active_early_probes_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Target detector observes pso2.exe
    monkeypatch.setattr(
        "neko_launcher.infrastructure.process.process_detector.ExactPso2TargetDetector.observe_exact_pso2",
        lambda self: MagicMock(),
    )
    assert is_game_active_early() is True

    # No exact target, but is_any_process_running finds it
    monkeypatch.setattr(
        "neko_launcher.infrastructure.process.process_detector.ExactPso2TargetDetector.observe_exact_pso2",
        lambda self: None,
    )
    monkeypatch.setattr(
        "neko_launcher.infrastructure.process.process_detector.is_any_process_running",
        lambda: True,
    )
    assert is_game_active_early() is True

    # Neither finds it
    monkeypatch.setattr(
        "neko_launcher.infrastructure.process.process_detector.is_any_process_running",
        lambda: False,
    )
    assert is_game_active_early() is False

    # Exception during detection fails safe (returns False)
    monkeypatch.setattr(
        "neko_launcher.infrastructure.process.process_detector.is_any_process_running",
        MagicMock(side_effect=OSError("Access denied")),
    )
    assert is_game_active_early() is False

