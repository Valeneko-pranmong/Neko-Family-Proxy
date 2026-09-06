import base64
import dataclasses
import hashlib
import pytest

from neko_launcher.updater.binary_frame import (
    MARKER_FRAME_SIZE,
    SLOT_FRAME_SIZE,
    MarkerFrame,
    SlotFrame,
    pack_marker_frame,
    pack_slot_frame,
)
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.slot_selector import SelectionStatus
from neko_launcher.updater.state_models import (
    Binding,
    EnrollmentMarker,
    Generation,
    RootIdentity,
    State,
    serialize_marker,
    serialize_state,
)
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_release_document,
)


def _make_evidence_and_generation(seq: int, rel_id: str) -> tuple[Binding, str, str, Generation]:
    doc = valid_release_document()
    doc["release_sequence"] = seq
    doc["release_id"] = rel_id
    doc["schema_version"] = 2
    doc["updater_protocol"] = {"minimum": 1, "maximum": 1}
    doc["components"]["launcher"]["artifact_format"] = "raw-pe-v1"
    doc["components"]["launcher"]["installed_identity_sha256"] = doc["components"]["launcher"]["artifact_sha256"]
    doc["components"]["core"]["artifact_format"] = "zip-core-v1"

    envelope = signed_envelope(doc)
    envelope_bytes = canonical_json_dumps(envelope)
    envelope_b64 = base64.b64encode(envelope_bytes).decode("ascii")
    payload_sha = hashlib.sha256(base64.b64decode(envelope["payload_b64"])).hexdigest()

    binding = Binding(release_sequence=seq, release_id=rel_id, payload_sha256=payload_sha)
    gen = Generation(
        binding=binding,
        launcher_identity_sha256=doc["components"]["launcher"]["installed_identity_sha256"],
        core_identity_sha256=doc["components"]["core"]["installed_identity_sha256"],
    )
    return binding, payload_sha, envelope_b64, gen


def _ready_states() -> tuple[EnrollmentMarker, State, State]:
    binding, payload_sha, envelope_b64, generation = _make_evidence_and_generation(1, "rel-1")
    marker = EnrollmentMarker(
        schema_version=1,
        installation_id="0" * 32,
        root=RootIdentity(volume_serial="1" * 16, file_id="2" * 32),
        helper_sha256="3" * 64,
        helper_protocol=1,
        keyset_sha256="4" * 64,
        bootstrap_payload_sha256=payload_sha,
        enrollment_status="PREPARED",
    )
    state_rev2 = State(
        schema_version=1,
        revision=2,
        installation_id=marker.installation_id,
        helper_protocol=1,
        enrollment_complete=False,
        phase="IDLE",
        committed=generation,
        previous=None,
        highwater=binding,
        observed=binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={payload_sha: envelope_b64},
    )
    state_rev3 = dataclasses.replace(
        state_rev2,
        revision=3,
        enrollment_complete=True,
    )
    return marker, state_rev2, state_rev3


@pytest.fixture
def keys():
    return {TEST_KEY_ID: TEST_PUBLIC_KEY}


@pytest.fixture
def marker_and_initial_state():
    binding, payload_sha, envelope_b64, _ = _make_evidence_and_generation(1, "rel-1")
    marker = EnrollmentMarker(
        schema_version=1,
        installation_id="0" * 32,
        root=RootIdentity(volume_serial="1" * 16, file_id="2" * 32),
        helper_sha256="3" * 64,
        helper_protocol=1,
        keyset_sha256="4" * 64,
        bootstrap_payload_sha256=payload_sha,
        enrollment_status="PREPARED",
    )
    initial_state = State(
        schema_version=1,
        revision=1,
        installation_id="0" * 32,
        helper_protocol=1,
        enrollment_complete=False,
        phase="ENROLLING",
        committed=None,
        previous=None,
        highwater=None,
        observed=None,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={payload_sha: envelope_b64},
    )
    return marker, initial_state


def test_enroll_state_directory_success(tmp_path, keys, marker_and_initial_state):
    import neko_launcher.updater.enrollment as enr
    marker, initial_state = marker_and_initial_state
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    result = enr.enroll_state_directory(state_dir, marker, initial_state, keys)

    assert result.status == SelectionStatus.SELECTED
    assert result.state == initial_state
    assert result.state.revision == 1
    assert result.state.phase == "ENROLLING"
    assert result.state.enrollment_complete is False

    marker_file = state_dir / "enrollment.bin"
    slot_a = state_dir / "slot-a.bin"
    slot_b = state_dir / "slot-b.bin"

    assert marker_file.stat().st_size == MARKER_FRAME_SIZE
    assert slot_a.stat().st_size == SLOT_FRAME_SIZE
    assert slot_b.stat().st_size == SLOT_FRAME_SIZE
    assert slot_a.read_bytes() == slot_b.read_bytes()


def test_enroll_state_directory_fails_closed_on_flush(tmp_path, keys, marker_and_initial_state, monkeypatch):
    import neko_launcher.updater.enrollment as enr
    marker, initial_state = marker_and_initial_state
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    def mock_flush(handle):
        raise OSError("Simulated flush failure")

    monkeypatch.setattr(enr, "_flush_handle", mock_flush, raising=False)

    with pytest.raises(enr.EnrollmentError) as exc:
        enr.enroll_state_directory(state_dir, marker, initial_state, keys)

    err = str(exc.value)
    payload_sha = marker.bootstrap_payload_sha256
    assert initial_state.evidence[payload_sha] not in err
    assert hasattr(exc.value, "code")


def test_enroll_state_directory_fails_closed_on_reread(tmp_path, keys, marker_and_initial_state, monkeypatch):
    import neko_launcher.updater.enrollment as enr
    marker, initial_state = marker_and_initial_state
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    def mock_read(handle, size):
        raise OSError("Simulated reread failure")

    monkeypatch.setattr(enr, "_read_exact_at_zero", mock_read, raising=False)

    with pytest.raises(enr.EnrollmentError) as exc:
        enr.enroll_state_directory(state_dir, marker, initial_state, keys)
    assert hasattr(exc.value, "code")


def test_enroll_state_directory_evidence_validation(tmp_path, keys, marker_and_initial_state):
    import neko_launcher.updater.enrollment as enr
    marker, initial_state = marker_and_initial_state

    # 1. Empty evidence
    state_dir_1 = tmp_path / "state1"
    state_dir_1.mkdir()
    state_empty = dataclasses.replace(initial_state, evidence={})
    with pytest.raises(enr.EnrollmentError):
        enr.enroll_state_directory(state_dir_1, marker, state_empty, keys)
    assert not (state_dir_1 / "enrollment.bin").exists()
    assert not (state_dir_1 / "slot-a.bin").exists()
    assert not (state_dir_1 / "slot-b.bin").exists()

    # 2. Extra evidence: hex64 key, string value
    state_dir_2 = tmp_path / "state2"
    state_dir_2.mkdir()
    extra_key = "e" * 64 if marker.bootstrap_payload_sha256 == "f" * 64 else "f" * 64
    state_extra = dataclasses.replace(initial_state, evidence={**initial_state.evidence, extra_key: "data"})
    with pytest.raises(enr.EnrollmentError):
        enr.enroll_state_directory(state_dir_2, marker, state_extra, keys)
    assert not (state_dir_2 / "enrollment.bin").exists()
    assert not (state_dir_2 / "slot-a.bin").exists()
    assert not (state_dir_2 / "slot-b.bin").exists()

    # 3. Bootstrap mismatch: valid unequal hex64, not words
    state_dir_3 = tmp_path / "state3"
    state_dir_3.mkdir()
    mismatch_sha = "1" * 64 if marker.bootstrap_payload_sha256 != "1" * 64 else "2" * 64
    marker_mismatch = dataclasses.replace(marker, bootstrap_payload_sha256=mismatch_sha)
    with pytest.raises(enr.EnrollmentError):
        enr.enroll_state_directory(state_dir_3, marker_mismatch, initial_state, keys)
    assert not (state_dir_3 / "enrollment.bin").exists()
    assert not (state_dir_3 / "slot-a.bin").exists()
    assert not (state_dir_3 / "slot-b.bin").exists()

    # 4. Tampered envelope: string value, valid hex key
    state_dir_4 = tmp_path / "state4"
    state_dir_4.mkdir()
    bad_evidence = {marker.bootstrap_payload_sha256: "invalidb64"}
    state_tampered = dataclasses.replace(initial_state, evidence=bad_evidence)
    with pytest.raises(enr.EnrollmentError):
        enr.enroll_state_directory(state_dir_4, marker, state_tampered, keys)
    assert not (state_dir_4 / "enrollment.bin").exists()
    assert not (state_dir_4 / "slot-a.bin").exists()
    assert not (state_dir_4 / "slot-b.bin").exists()


def test_enroll_state_directory_partial_or_existing_fails(tmp_path, keys, marker_and_initial_state):
    import neko_launcher.updater.enrollment as enr
    marker, initial_state = marker_and_initial_state

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    marker_file = state_dir / "enrollment.bin"
    marker_file.write_bytes(b"existing_marker_bytes")

    with pytest.raises(enr.EnrollmentError) as exc:
        enr.enroll_state_directory(state_dir, marker, initial_state, keys)
    assert hasattr(exc.value, "code")

    assert marker_file.read_bytes() == b"existing_marker_bytes"
    assert not (state_dir / "slot-a.bin").exists()
    assert not (state_dir / "slot-b.bin").exists()

    state_dir2 = tmp_path / "state2"
    state_dir2.mkdir()
    slot_a2 = state_dir2 / "slot-a.bin"
    slot_a2.write_bytes(b"existing_slot_a")

    with pytest.raises(enr.EnrollmentError):
        enr.enroll_state_directory(state_dir2, marker, initial_state, keys)

    assert slot_a2.read_bytes() == b"existing_slot_a"
    assert not (state_dir2 / "enrollment.bin").exists()
    assert not (state_dir2 / "slot-b.bin").exists()


def test_load_enrollment_success(tmp_path, keys):
    import neko_launcher.updater.enrollment as enr
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    marker, state_rev2, state_rev3 = _ready_states()

    marker_bytes = pack_marker_frame(MarkerFrame(format_version=1, body_bytes=serialize_marker(marker)))
    slot_a_bytes = pack_slot_frame(SlotFrame(revision=state_rev2.revision, format_version=1, body_bytes=serialize_state(state_rev2)))
    slot_b_bytes = pack_slot_frame(SlotFrame(revision=state_rev3.revision, format_version=1, body_bytes=serialize_state(state_rev3)))

    (state_dir / "enrollment.bin").write_bytes(marker_bytes)
    (state_dir / "slot-a.bin").write_bytes(slot_a_bytes)
    (state_dir / "slot-b.bin").write_bytes(slot_b_bytes)

    loaded_marker, result = enr.load_enrollment(
        state_dir,
        expected_root=marker.root,
        expected_helper_sha256=marker.helper_sha256,
        expected_keyset_sha256=marker.keyset_sha256,
        expected_bootstrap_payload_sha256=marker.bootstrap_payload_sha256,
        public_keys=keys,
    )

    assert loaded_marker == marker
    assert result.status == SelectionStatus.SELECTED
    assert result.active_slot == "b"
    assert result.state == state_rev3
    assert result.state.enrollment_complete is True
    assert result.state.installation_id == marker.installation_id


def test_load_enrollment_accepts_later_committed_state_without_bootstrap_evidence(tmp_path, keys):
    import neko_launcher.updater.enrollment as enr
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    binding_seq1, payload_sha1, envelope_b64_1, _ = _make_evidence_and_generation(1, "rel-1")
    marker = EnrollmentMarker(
        schema_version=1,
        installation_id="0" * 32,
        root=RootIdentity(volume_serial="1" * 16, file_id="2" * 32),
        helper_sha256="3" * 64,
        helper_protocol=1,
        keyset_sha256="4" * 64,
        bootstrap_payload_sha256=payload_sha1,
        enrollment_status="PREPARED",
    )

    binding_seq2, payload_sha2, envelope_b64_2, gen2 = _make_evidence_and_generation(2, "rel-2")
    state_later = State(
        schema_version=1,
        revision=4,
        installation_id=marker.installation_id,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen2,
        previous=None,
        highwater=binding_seq2,
        observed=binding_seq2,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={payload_sha2: envelope_b64_2},
    )

    assert payload_sha1 not in state_later.evidence

    marker_bytes = pack_marker_frame(MarkerFrame(format_version=1, body_bytes=serialize_marker(marker)))
    slot_a_bytes = pack_slot_frame(SlotFrame(revision=4, format_version=1, body_bytes=serialize_state(state_later)))

    (state_dir / "enrollment.bin").write_bytes(marker_bytes)
    (state_dir / "slot-a.bin").write_bytes(slot_a_bytes)
    (state_dir / "slot-b.bin").write_bytes(b"\x00" * SLOT_FRAME_SIZE)

    loaded_marker, result = enr.load_enrollment(
        state_dir,
        expected_root=marker.root,
        expected_helper_sha256=marker.helper_sha256,
        expected_keyset_sha256=marker.keyset_sha256,
        expected_bootstrap_payload_sha256=marker.bootstrap_payload_sha256,
        public_keys=keys,
    )

    assert loaded_marker == marker
    assert result.status == SelectionStatus.SELECTED
    assert result.active_slot == "a"
    assert result.state == state_later
    assert result.state.enrollment_complete is True
    assert marker.bootstrap_payload_sha256 not in result.state.evidence


def test_load_enrollment_negative_matrix(tmp_path, keys):
    import neko_launcher.updater.enrollment as enr
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    marker, state_rev2, state_rev3 = _ready_states()

    marker_bytes = pack_marker_frame(MarkerFrame(format_version=1, body_bytes=serialize_marker(marker)))
    slot_a_bytes = pack_slot_frame(SlotFrame(revision=2, format_version=1, body_bytes=serialize_state(state_rev2)))
    slot_b_bytes = pack_slot_frame(SlotFrame(revision=3, format_version=1, body_bytes=serialize_state(state_rev3)))

    enrollment_file = state_dir / "enrollment.bin"
    slot_a_file = state_dir / "slot-a.bin"
    slot_b_file = state_dir / "slot-b.bin"

    def restore_valid_state():
        enrollment_file.write_bytes(marker_bytes)
        slot_a_file.write_bytes(slot_a_bytes)
        slot_b_file.write_bytes(slot_b_bytes)

    restore_valid_state()

    # 1. Missing slot
    slot_a_file.unlink()
    with pytest.raises(enr.EnrollmentError) as exc:
        enr.load_enrollment(state_dir, marker.root, marker.helper_sha256, marker.keyset_sha256, marker.bootstrap_payload_sha256, keys)
    assert hasattr(exc.value, "code")
    restore_valid_state()

    # 2. Corrupt marker
    enrollment_file.write_bytes(b"corrupt_marker_bytes")
    with pytest.raises(enr.EnrollmentError) as exc:
        enr.load_enrollment(state_dir, marker.root, marker.helper_sha256, marker.keyset_sha256, marker.bootstrap_payload_sha256, keys)
    assert hasattr(exc.value, "code")
    restore_valid_state()

    # 3. Marker/state installation mismatch
    marker_mismatch = dataclasses.replace(marker, installation_id="1" * 32)
    enrollment_file.write_bytes(pack_marker_frame(MarkerFrame(format_version=1, body_bytes=serialize_marker(marker_mismatch))))
    with pytest.raises(enr.EnrollmentError) as exc:
        enr.load_enrollment(state_dir, marker_mismatch.root, marker_mismatch.helper_sha256, marker_mismatch.keyset_sha256, marker_mismatch.bootstrap_payload_sha256, keys)
    assert hasattr(exc.value, "code")
    restore_valid_state()

    # 4. Selected false-complete: rev2 IDLE(false) sole selected valid frame by making other slot torn
    slot_b_file.write_bytes(b"\x00" * SLOT_FRAME_SIZE)
    with pytest.raises(enr.EnrollmentError) as exc:
        enr.load_enrollment(state_dir, marker.root, marker.helper_sha256, marker.keyset_sha256, marker.bootstrap_payload_sha256, keys)
    assert hasattr(exc.value, "code")
    restore_valid_state()

    # 5. Expected root mismatch
    wrong_root = RootIdentity(volume_serial="9" * 16, file_id="9" * 32)
    with pytest.raises(enr.EnrollmentError) as exc:
        enr.load_enrollment(state_dir, wrong_root, marker.helper_sha256, marker.keyset_sha256, marker.bootstrap_payload_sha256, keys)
    assert hasattr(exc.value, "code")

    # 6. Expected helper mismatch
    wrong_helper = "e" * 64 if marker.helper_sha256 == "f" * 64 else "f" * 64
    with pytest.raises(enr.EnrollmentError) as exc:
        enr.load_enrollment(state_dir, marker.root, wrong_helper, marker.keyset_sha256, marker.bootstrap_payload_sha256, keys)
    assert hasattr(exc.value, "code")

    # 7. Expected keyset mismatch
    wrong_keyset = "e" * 64 if marker.keyset_sha256 == "f" * 64 else "f" * 64
    with pytest.raises(enr.EnrollmentError) as exc:
        enr.load_enrollment(state_dir, marker.root, marker.helper_sha256, wrong_keyset, marker.bootstrap_payload_sha256, keys)
    assert hasattr(exc.value, "code")

    # 8. Expected bootstrap mismatch
    wrong_bootstrap = "e" * 64 if marker.bootstrap_payload_sha256 == "f" * 64 else "f" * 64
    with pytest.raises(enr.EnrollmentError) as exc:
        enr.load_enrollment(state_dir, marker.root, marker.helper_sha256, marker.keyset_sha256, wrong_bootstrap, keys)
    assert hasattr(exc.value, "code")


def test_load_enrollment_mismatch_fails(tmp_path, keys):
    import neko_launcher.updater.enrollment as enr
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    marker, state_rev2, state_rev3 = _ready_states()

    (state_dir / "enrollment.bin").write_bytes(pack_marker_frame(MarkerFrame(format_version=1, body_bytes=serialize_marker(marker))))
    (state_dir / "slot-a.bin").write_bytes(b"\x00" * SLOT_FRAME_SIZE)
    (state_dir / "slot-b.bin").write_bytes(pack_slot_frame(SlotFrame(revision=3, format_version=1, body_bytes=serialize_state(state_rev3))))

    wrong_helper = "e" * 64 if marker.helper_sha256 == "f" * 64 else "f" * 64
    wrong_keyset = "e" * 64 if marker.keyset_sha256 == "f" * 64 else "f" * 64
    wrong_bootstrap = "e" * 64 if marker.bootstrap_payload_sha256 == "f" * 64 else "f" * 64

    with pytest.raises(enr.EnrollmentError):
        enr.load_enrollment(state_dir, RootIdentity(volume_serial="9" * 16, file_id="9" * 32), marker.helper_sha256, marker.keyset_sha256, marker.bootstrap_payload_sha256, keys)

    with pytest.raises(enr.EnrollmentError):
        enr.load_enrollment(state_dir, marker.root, wrong_helper, marker.keyset_sha256, marker.bootstrap_payload_sha256, keys)

    with pytest.raises(enr.EnrollmentError):
        enr.load_enrollment(state_dir, marker.root, marker.helper_sha256, wrong_keyset, marker.bootstrap_payload_sha256, keys)

    with pytest.raises(enr.EnrollmentError):
        enr.load_enrollment(state_dir, marker.root, marker.helper_sha256, marker.keyset_sha256, wrong_bootstrap, keys)


def test_load_enrollment_never_creates(tmp_path, keys):
    import neko_launcher.updater.enrollment as enr
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    with pytest.raises(enr.EnrollmentError):
        enr.load_enrollment(
            state_dir,
            expected_root=RootIdentity(volume_serial="1" * 16, file_id="2" * 32),
            expected_helper_sha256="3" * 64,
            expected_keyset_sha256="4" * 64,
            expected_bootstrap_payload_sha256="a" * 64,
            public_keys=keys,
        )

    assert not (state_dir / "enrollment.bin").exists()
    assert not (state_dir / "slot-a.bin").exists()
    assert not (state_dir / "slot-b.bin").exists()
