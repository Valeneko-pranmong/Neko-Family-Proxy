import dataclasses
import hashlib
import json
import pytest
from pathlib import Path

from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
    LocalReleaseIdentity,
)
from neko_launcher.application.software_update_pending import (
    VerifiedPendingUpdate,
)
from neko_launcher.updater.manifest_v2 import parse_release_v2
from tests.software_update_helpers import (
    get_test_key_registry,
    signed_envelope,
    valid_v2_release_document,
)


def lazy_import():
    try:
        from neko_launcher.application.software_update_pending import (
            UpdateLifecycleState,
            VerifiedPendingUpdate,
        )
        from neko_launcher.infrastructure.software_update_pending_store import (
            PendingUpdateStore,
        )
        return True, (UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore)
    except ImportError:
        return False, None


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


def _local_identity_seq_1(
    high_water_binding: AuthenticatedReleaseBinding | None = None,
    failed_binding: AuthenticatedReleaseBinding | None = None,
) -> LocalReleaseIdentity:
    b1 = AuthenticatedReleaseBinding(1, "r1-stable", "0" * 64)
    hw = high_water_binding or b1
    return LocalReleaseIdentity(
        committed=b1,
        high_water=hw,
        observed=hw,
        failed=failed_binding,
        launcher_version="5.1.0",
        launcher_installed_identity_sha256="0" * 64,
        updater_version="5.1.0",
        updater_installed_identity_sha256="0" * 64,
        core_version="1.0.0",
        core_installed_identity_sha256="0" * 64,
    )


def _local_identity_for_pending(
    pending: VerifiedPendingUpdate,
    committed_seq: int = 1,
    failed_binding: AuthenticatedReleaseBinding | None = None,
) -> LocalReleaseIdentity:
    from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2

    doc = json.loads(pending.envelope_bytes.decode("utf-8"))
    _, payload_sha = verify_release_envelope_v2(doc, get_test_key_registry())
    hw = AuthenticatedReleaseBinding(
        release_sequence=pending.release_sequence,
        release_id=pending.release_id,
        payload_sha256=payload_sha,
    )
    c = AuthenticatedReleaseBinding(
        release_sequence=committed_seq,
        release_id=f"r{committed_seq}-stable",
        payload_sha256="0" * 64,
    )
    return LocalReleaseIdentity(
        committed=c,
        high_water=hw,
        observed=hw,
        failed=failed_binding,
        launcher_version="5.1.0",
        launcher_installed_identity_sha256="0" * 64,
        updater_version="5.1.0",
        updater_installed_identity_sha256="0" * 64,
        core_version="1.0.0",
        core_installed_identity_sha256="0" * 64,
    )


def test_atomic_promotion_and_exact_update_pending(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    assert UpdateLifecycleState.IDLE == "idle"
    assert UpdateLifecycleState.STAGING == "staging"
    assert UpdateLifecycleState.UPDATE_PENDING == "update_pending"
    assert UpdateLifecycleState.APPLYING == "applying"

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _local_identity_seq_1()

    # Initial state is IDLE / None
    assert store.load_verified(local) is None
    assert store.state(local) == UpdateLifecycleState.IDLE

    release, env_bytes, staged_files, l_bytes, c_bytes = _make_fixture_payload(tmp_path, sequence=2, release_id="r2-stable")
    pending = store.promote(
        envelope_bytes=env_bytes,
        release=release,
        changed_components=("launcher", "core"),
        staged_files=staged_files,
    )

    assert isinstance(pending, VerifiedPendingUpdate)
    assert pending.release_id == "r2-stable"
    assert pending.release_sequence == 2
    assert pending.changed_components == ("launcher", "core")
    assert pending.envelope_bytes == env_bytes
    assert pending.generation_dir.is_dir()
    assert pending.launcher_artifact is not None and pending.launcher_artifact.read_bytes() == l_bytes
    assert pending.core_artifact is not None and pending.core_artifact.read_bytes() == c_bytes

    # load_verified returns identical pending update with admitted identity
    admitted = _local_identity_for_pending(pending)
    loaded = store.load_verified(admitted)
    assert loaded == pending
    assert store.state(admitted) == UpdateLifecycleState.UPDATE_PENDING
    assert store.load_verified(local) is None
    assert store.state(local) == UpdateLifecycleState.IDLE


def test_process_restart_reload(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    store1 = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    release, env_bytes, staged_files, l_bytes, c_bytes = _make_fixture_payload(tmp_path, sequence=2, release_id="r2-stable")
    promoted = store1.promote(
        envelope_bytes=env_bytes,
        release=release,
        changed_components=("launcher", "core"),
        staged_files=staged_files,
    )

    # Re-instantiate store representing new process
    store2 = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _local_identity_for_pending(promoted)
    loaded = store2.load_verified(local)
    assert loaded is not None
    assert loaded.release_id == promoted.release_id
    assert loaded.release_sequence == promoted.release_sequence
    assert loaded.changed_components == promoted.changed_components
    assert loaded.envelope_bytes == promoted.envelope_bytes
    assert loaded.launcher_artifact is not None and loaded.launcher_artifact.read_bytes() == l_bytes
    assert loaded.core_artifact is not None and loaded.core_artifact.read_bytes() == c_bytes
    assert store2.state(local) == UpdateLifecycleState.UPDATE_PENDING


def test_envelope_byte_tamper_rejection(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    release, env_bytes, staged_files, _, _ = _make_fixture_payload(tmp_path, sequence=2, release_id="r2-stable")
    pending = store.promote(
        envelope_bytes=env_bytes,
        release=release,
        changed_components=("launcher", "core"),
        staged_files=staged_files,
    )

    # Tamper envelope bytes
    envelope_file = pending.generation_dir / "release-v2.json"
    tampered = bytearray(envelope_file.read_bytes())
    tampered[-5] ^= 0xFF
    envelope_file.write_bytes(bytes(tampered))

    local = _local_identity_for_pending(pending)
    assert store.load_verified(local) is None
    assert store.state(local) == UpdateLifecycleState.IDLE


def test_staged_artifact_tamper_rejection(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    # Case 1: launcher tampered
    store1 = PendingUpdateStore(tmp_path / "case1", get_test_key_registry(), updater_protocol=1)
    release1, env_bytes1, staged1, l_bytes, _ = _make_fixture_payload(tmp_path / "case1", sequence=2, release_id="r2-stable")
    p1 = store1.promote(envelope_bytes=env_bytes1, release=release1, changed_components=("launcher", "core"), staged_files=staged1)
    assert p1.launcher_artifact is not None
    p1.launcher_artifact.write_bytes(b"tampered-launcher-bytes")
    local1 = _local_identity_for_pending(p1)
    assert store1.load_verified(local1) is None

    # Case 2: core tampered
    store2 = PendingUpdateStore(tmp_path / "case2", get_test_key_registry(), updater_protocol=1)
    release2, env_bytes2, staged2, _, _ = _make_fixture_payload(tmp_path / "case2", sequence=2, release_id="r2-stable")
    p2 = store2.promote(envelope_bytes=env_bytes2, release=release2, changed_components=("launcher", "core"), staged_files=staged2)
    assert p2.core_artifact is not None
    p2.core_artifact.write_bytes(b"tampered-core-bytes")
    local2 = _local_identity_for_pending(p2)
    assert store2.load_verified(local2) is None

    # Case 3: artifact missing
    store3 = PendingUpdateStore(tmp_path / "case3", get_test_key_registry(), updater_protocol=1)
    release3, env_bytes3, staged3, _, _ = _make_fixture_payload(tmp_path / "case3", sequence=2, release_id="r2-stable")
    p3 = store3.promote(envelope_bytes=env_bytes3, release=release3, changed_components=("launcher", "core"), staged_files=staged3)
    assert p3.launcher_artifact is not None
    p3.launcher_artifact.unlink()
    local3 = _local_identity_for_pending(p3)
    assert store3.load_verified(local3) is None


def test_metadata_path_injection_ignored_or_rejected(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    release, env_bytes, staged_files, _, _ = _make_fixture_payload(tmp_path, sequence=2, release_id="r2-stable")
    pending = store.promote(
        envelope_bytes=env_bytes,
        release=release,
        changed_components=("launcher", "core"),
        staged_files=staged_files,
    )

    local = _local_identity_for_pending(pending)

    # Tamper pointer file with directory traversal injection
    pointer_path = tmp_path / "update-pending" / "current.json"
    pointer_data = json.loads(pointer_path.read_text("utf-8"))
    pointer_data["generation_name"] = "../../evil_dir"
    pointer_path.write_text(json.dumps(pointer_data), "utf-8")

    # Injected relative traversal must be rejected
    assert store.load_verified(local) is None

    # Tamper pointer file with absolute path injection
    pointer_data["generation_name"] = "C:\\Windows\\System32"
    pointer_path.write_text(json.dumps(pointer_data), "utf-8")
    assert store.load_verified(local) is None

    # Restore pointer, tamper metadata.json to inject arbitrary file paths
    pointer_data["generation_name"] = pending.generation_dir.name
    pointer_path.write_text(json.dumps(pointer_data), "utf-8")

    meta_path = pending.generation_dir / "metadata.json"
    meta_data = json.loads(meta_path.read_text("utf-8"))
    meta_data["launcher_artifact"] = "C:\\malicious\\fake.exe"
    meta_data["path"] = "/evil"
    meta_path.write_text(json.dumps(meta_data), "utf-8")

    # The store must never follow arbitrary paths: either rejects or derives only from generation_dir
    loaded = store.load_verified(local)
    if loaded is not None:
        assert loaded.launcher_artifact == pending.generation_dir / "launcher.artifact"
        assert not str(loaded.launcher_artifact).startswith("C:\\malicious")


def test_lower_sequence_cannot_replace_higher(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)

    # Promote sequence 3
    rel3, env3, staged3, l3, c3 = _make_fixture_payload(tmp_path, sequence=3, release_id="r3-stable")
    p3 = store.promote(envelope_bytes=env3, release=rel3, changed_components=("launcher", "core"), staged_files=staged3)
    assert p3.release_sequence == 3

    # Attempt to promote sequence 2
    rel2, env2, staged2, _, _ = _make_fixture_payload(tmp_path, sequence=2, release_id="r2-stable")
    with pytest.raises(ValueError, match="[Dd]owngrade"):
        store.promote(envelope_bytes=env2, release=rel2, changed_components=("launcher", "core"), staged_files=staged2)

    # Sequence 3 remains current pending
    local3 = _local_identity_for_pending(p3)
    loaded = store.load_verified(local3)
    assert loaded is not None
    assert loaded.release_sequence == 3
    assert loaded.release_id == "r3-stable"

    # Anti-downgrade against local identity: local committed sequence 4 rejects pending sequence 3
    b4 = AuthenticatedReleaseBinding(4, "r4-stable", "0" * 64)
    local_seq_4 = LocalReleaseIdentity(
        committed=b4,
        high_water=b4,
        observed=b4,
        failed=None,
        launcher_version="5.1.0",
        launcher_installed_identity_sha256="0" * 64,
        updater_version="5.1.0",
        updater_installed_identity_sha256="0" * 64,
        core_version="1.0.0",
        core_installed_identity_sha256="0" * 64,
    )
    assert store.load_verified(local_seq_4) is None


def test_same_sequence_different_identity_rejected(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)

    # Promote sequence 3 with identity "r3-stable-a"
    rel3a, env3a, staged3a, _, _ = _make_fixture_payload(tmp_path, sequence=3, release_id="r3-stable-a")
    p3a = store.promote(envelope_bytes=env3a, release=rel3a, changed_components=("launcher", "core"), staged_files=staged3a)

    # Attempt to promote sequence 3 with conflicting identity "r3-stable-b"
    rel3b, env3b, staged3b, _, _ = _make_fixture_payload(tmp_path, sequence=3, release_id="r3-stable-b")
    with pytest.raises(ValueError, match="[Ss]ame[- ]sequence"):
        store.promote(envelope_bytes=env3b, release=rel3b, changed_components=("launcher", "core"), staged_files=staged3b)

    # Sequence 3 identity "r3-stable-a" remains intact
    local3a = _local_identity_for_pending(p3a)
    loaded = store.load_verified(local3a)
    assert loaded is not None
    assert loaded.release_id == "r3-stable-a"

    # Same sequence as local committed identity is not an update (rejected by load_verified)
    local_same_seq = LocalReleaseIdentity(
        committed=local3a.high_water,
        high_water=local3a.high_water,
        observed=local3a.high_water,
        failed=None,
        launcher_version="5.1.0",
        launcher_installed_identity_sha256="0" * 64,
        updater_version="5.1.0",
        updater_installed_identity_sha256="0" * 64,
        core_version="1.0.0",
        core_installed_identity_sha256="0" * 64,
    )
    assert store.load_verified(local_same_seq) is None


def test_incomplete_temporary_directory_does_not_replace_verified_pending(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)

    # Promote valid sequence 2
    rel2, env2, staged2, _, _ = _make_fixture_payload(tmp_path, sequence=2, release_id="r2-stable")
    p2 = store.promote(envelope_bytes=env2, release=rel2, changed_components=("launcher", "core"), staged_files=staged2)

    # Simulate incomplete crash leftovers in update-pending
    base_dir = tmp_path / "update-pending"
    tmp_crash_dir = base_dir / "tmp_crash_leftover_abc"
    tmp_crash_dir.mkdir(parents=True, exist_ok=True)
    (tmp_crash_dir / "corrupt.file").write_bytes(b"garbage")

    # load_verified ignores incomplete temporary directories
    local2 = _local_identity_for_pending(p2)
    loaded = store.load_verified(local2)
    assert loaded is not None
    assert loaded.release_sequence == 2
    assert loaded.release_id == "r2-stable"

    # cleanup_incomplete cleans temporary leftovers and preserves valid pending
    store.cleanup_incomplete()
    assert not tmp_crash_dir.exists()
    assert store.load_verified(local2) is not None


def test_failed_promotion_preserves_prior_valid_pending(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)

    # Promote valid sequence 2
    rel2, env2, staged2, _, _ = _make_fixture_payload(tmp_path, sequence=2, release_id="r2-stable")
    p2 = store.promote(envelope_bytes=env2, release=rel2, changed_components=("launcher", "core"), staged_files=staged2)

    # Create sequence 3 with corrupt staged file (bad hash)
    rel3, env3, staged3, _, _ = _make_fixture_payload(tmp_path, sequence=3, release_id="r3-stable")
    staged3["launcher"].write_bytes(b"corrupted-launcher-payload")

    with pytest.raises(ValueError):
        store.promote(envelope_bytes=env3, release=rel3, changed_components=("launcher", "core"), staged_files=staged3)

    # Sequence 2 must still be the authoritative pending update
    local2 = _local_identity_for_pending(p2)
    loaded = store.load_verified(local2)
    assert loaded is not None
    assert loaded.release_sequence == 2
    assert loaded.release_id == "r2-stable"

    # No leftover temporary directories in update-pending
    base_dir = tmp_path / "update-pending"
    tmp_leftovers = [p for p in base_dir.iterdir() if p.name.startswith("tmp_")]
    assert len(tmp_leftovers) == 0


def test_clear_and_supersession(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)

    # Promote sequence 2
    rel2, env2, staged2, _, _ = _make_fixture_payload(tmp_path, sequence=2, release_id="r2-stable")
    p2 = store.promote(envelope_bytes=env2, release=rel2, changed_components=("launcher", "core"), staged_files=staged2)
    local2 = _local_identity_for_pending(p2)
    assert store.load_verified(local2) is not None

    # Supersede with sequence 3
    rel3, env3, staged3, _, _ = _make_fixture_payload(tmp_path, sequence=3, release_id="r3-stable")
    p3 = store.promote(envelope_bytes=env3, release=rel3, changed_components=("launcher", "core"), staged_files=staged3)
    local3 = _local_identity_for_pending(p3)

    loaded = store.load_verified(local3)
    assert loaded is not None
    assert loaded.release_sequence == 3
    assert loaded.release_id == "r3-stable"

    # Clear with mismatched expected sequence/id does nothing
    store.clear(expected_release_id="r2-stable", expected_release_sequence=2)
    assert store.load_verified(local3) is not None

    # Clear with matching expected sequence and id clears pending update
    store.clear(expected_release_id="r3-stable", expected_release_sequence=3)
    assert store.load_verified(local3) is None
    assert store.state(local3) == UpdateLifecycleState.IDLE


def test_updater_protocol_incompatibility_rejected(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    # Store supports protocol 1
    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _local_identity_seq_1()

    # Release requires protocol minimum 2
    rel, env, staged, _, _ = _make_fixture_payload(tmp_path, sequence=2, proto_min=2, proto_max=2)
    with pytest.raises(ValueError, match="[Pp]rotocol"):
        store.promote(envelope_bytes=env, release=rel, changed_components=("launcher", "core"), staged_files=staged)

    assert store.load_verified(local) is None


def test_channel_must_be_stable(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    _, _, PendingUpdateStore = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    # Channel beta rejected by parse_release_v2
    with pytest.raises(ValueError, match="channel"):
        _make_fixture_payload(tmp_path, sequence=2, channel="beta")

    # Also test promote directly rejects if release object has non-stable channel
    rel, env, staged, _, _ = _make_fixture_payload(tmp_path, sequence=2, channel="stable")
    rel_beta = dataclasses.replace(rel, channel="beta")
    with pytest.raises(ValueError, match="[Cc]hannel"):
        store.promote(
            envelope_bytes=env,
            release=rel_beta,
            changed_components=("launcher", "core"),
            staged_files=staged,
        )


def test_partial_component_change(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    UpdateLifecycleState, VerifiedPendingUpdate, PendingUpdateStore = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)

    # Only launcher changed
    rel, env, staged, l_bytes, _ = _make_fixture_payload(tmp_path, sequence=2, release_id="r2-stable")
    p_launcher = store.promote(
        envelope_bytes=env,
        release=rel,
        changed_components=("launcher",),
        staged_files={"launcher": staged["launcher"]},
    )
    assert p_launcher.launcher_artifact is not None and p_launcher.launcher_artifact.read_bytes() == l_bytes
    assert p_launcher.core_artifact is None

    local = _local_identity_for_pending(p_launcher)
    loaded = store.load_verified(local)
    assert loaded is not None
    assert loaded.launcher_artifact is not None
    assert loaded.core_artifact is None


def test_pending_store_load_verified_exact_binding_contract(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "Pending update symbols must be implemented"
    _, _, PendingUpdateStore = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    rel, env, staged, _, _ = _make_fixture_payload(tmp_path, sequence=2, release_id="r2-stable")
    pending = store.promote(
        envelope_bytes=env,
        release=rel,
        changed_components=("launcher", "core"),
        staged_files=staged,
    )

    # 1. Unadmitted local (high_water seq 1) cannot load pending seq 2
    unadmitted = _local_identity_seq_1()
    assert store.load_verified(unadmitted) is None

    # 2. Admitted local loads pending
    admitted = _local_identity_for_pending(pending)
    assert store.load_verified(admitted) == pending

    # 3. Local with failed matching pending cannot load pending
    failed_local = _local_identity_for_pending(pending, failed_binding=admitted.high_water)
    assert store.load_verified(failed_local) is None

    # 4. Conflicting same-sequence payload cannot load pending
    conflict_binding = AuthenticatedReleaseBinding(2, "r2-stable", "f" * 64)
    conflict_local = _local_identity_seq_1(high_water_binding=conflict_binding)
    assert store.load_verified(conflict_local) is None

    # 5. Local committed at or higher than pending cannot load pending
    higher_binding = AuthenticatedReleaseBinding(2, pending.release_id, admitted.high_water.payload_sha256)
    higher_committed = LocalReleaseIdentity(
        committed=higher_binding,
        high_water=higher_binding,
        observed=higher_binding,
        failed=None,
        launcher_version="5.1.0",
        launcher_installed_identity_sha256="0" * 64,
        updater_version="5.1.0",
        updater_installed_identity_sha256="0" * 64,
        core_version="1.0.0",
        core_installed_identity_sha256="0" * 64,
    )
    assert store.load_verified(higher_committed) is None
