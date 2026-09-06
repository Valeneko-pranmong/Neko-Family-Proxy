import base64
import dataclasses
import hashlib
import os
import sys
import pytest

from neko_launcher.updater.binary_frame import SLOT_FRAME_SIZE, SlotFrame, pack_slot_frame
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.slot_selector import SelectionResult, SelectionStatus
from neko_launcher.updater.state_models import (
    Binding,
    Generation,
    State,
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


@pytest.fixture
def keys():
    return {TEST_KEY_ID: TEST_PUBLIC_KEY}


@pytest.fixture
def legal_states():
    binding, payload_sha, envelope_b64, generation = _make_evidence_and_generation(1, "rel-1")
    state_rev2 = State(
        schema_version=1,
        revision=2,
        installation_id="0" * 32,
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
    return state_rev2, state_rev3


def _pack_state(state: State) -> bytes:
    body = serialize_state(state)
    return pack_slot_frame(SlotFrame(revision=state.revision, format_version=1, body_bytes=body))


def test_slot_store_rejects_missing(tmp_path, keys):
    import neko_launcher.updater.slot_store as ss
    slot_a = tmp_path / "a.bin"
    slot_b = tmp_path / "b.bin"
    slot_a.write_bytes(b"\x00" * SLOT_FRAME_SIZE)

    with pytest.raises(ss.SlotStoreError) as exc:
        ss.SlotStore(slot_a, slot_b, keys)
    assert hasattr(exc.value, "code")


def test_slot_store_rejects_invalid_size(tmp_path, keys):
    import neko_launcher.updater.slot_store as ss
    slot_a = tmp_path / "a.bin"
    slot_b = tmp_path / "b.bin"
    slot_a.write_bytes(b"\x00" * SLOT_FRAME_SIZE)
    slot_b.write_bytes(b"\x00" * (SLOT_FRAME_SIZE - 1))

    with pytest.raises(ss.SlotStoreError) as exc:
        ss.SlotStore(slot_a, slot_b, keys)
    assert hasattr(exc.value, "code")


def test_load_and_select(tmp_path, keys, legal_states):
    import neko_launcher.updater.slot_store as ss
    slot_a = tmp_path / "a.bin"
    slot_b = tmp_path / "b.bin"
    state_rev2, state_rev3 = legal_states

    slot_a.write_bytes(_pack_state(state_rev2))
    slot_b.write_bytes(_pack_state(state_rev3))

    store = ss.SlotStore(slot_a, slot_b, keys)
    result = store.load()

    assert result.status == SelectionStatus.SELECTED
    assert result.active_slot == "b"
    assert result.state == state_rev3
    store.close()


def test_write_state_revision_and_transition_validation(tmp_path, keys, legal_states):
    import neko_launcher.updater.slot_store as ss
    slot_a = tmp_path / "a.bin"
    slot_b = tmp_path / "b.bin"
    state_rev2, state_rev3 = legal_states

    slot_a.write_bytes(_pack_state(state_rev2))
    slot_b.write_bytes(b"\x00" * SLOT_FRAME_SIZE)

    store = ss.SlotStore(slot_a, slot_b, keys)
    store.load()

    with pytest.raises(ss.SlotStoreError) as exc:
        store.write_state(state_rev2)
    assert hasattr(exc.value, "code")

    state_rev4 = dataclasses.replace(state_rev2, revision=4, enrollment_complete=True)
    with pytest.raises(ss.SlotStoreError) as exc:
        store.write_state(state_rev4)
    assert hasattr(exc.value, "code")

    invalid_phase_state = dataclasses.replace(state_rev3, phase="ENROLLING")
    with pytest.raises(ss.SlotStoreError) as exc:
        store.write_state(invalid_phase_state)
    assert hasattr(exc.value, "code")

    store.close()


def test_write_state_order_and_handle(tmp_path, keys, legal_states, monkeypatch):
    import neko_launcher.updater.slot_store as ss
    slot_a = tmp_path / "a.bin"
    slot_b = tmp_path / "b.bin"
    state_rev2, state_rev3 = legal_states

    sentinel_a = 100
    sentinel_b = 200
    handle_map = {str(slot_a): sentinel_a, str(slot_b): sentinel_b}

    events = []

    def mock_open(path):
        return handle_map[str(path)]

    def mock_close(handle):
        pass

    def mock_get_size(handle):
        return SLOT_FRAME_SIZE

    def mock_read(handle, size):
        events.append(("read", handle))
        if handle == sentinel_a:
            return _pack_state(state_rev2)
        elif handle == sentinel_b:
            if ("write", sentinel_b) in events:
                return _pack_state(state_rev3)
            return b"\x00" * SLOT_FRAME_SIZE
        return b""

    def mock_write(handle, data):
        events.append(("write", handle))

    def mock_flush(handle):
        events.append(("flush", handle))

    monkeypatch.setattr(ss, "_open_existing_slot", mock_open, raising=False)
    monkeypatch.setattr(ss, "_close_handle", mock_close, raising=False)
    monkeypatch.setattr(ss, "_get_file_size", mock_get_size, raising=False)
    monkeypatch.setattr(ss, "_read_exact_at_zero", mock_read, raising=False)
    monkeypatch.setattr(ss, "_write_all_at_zero", mock_write, raising=False)
    monkeypatch.setattr(ss, "_flush_handle", mock_flush, raising=False)

    store = ss.SlotStore(slot_a, slot_b, keys)
    store.load()

    events.clear()

    result = store.write_state(state_rev3)

    assert result.status == SelectionStatus.SELECTED
    assert result.active_slot == "b"

    b_events = [e for e in events if e[1] == sentinel_b]
    assert b_events[:3] == [
        ("write", sentinel_b),
        ("flush", sentinel_b),
        ("read", sentinel_b),
    ]

    store.close()


def test_write_state_post_write_validation_failures(tmp_path, keys, legal_states, monkeypatch):
    import neko_launcher.updater.slot_store as ss
    slot_a = tmp_path / "a.bin"
    slot_b = tmp_path / "b.bin"
    state_rev2, state_rev3 = legal_states

    # Scenario 1: repair required
    slot_a.write_bytes(_pack_state(state_rev2))
    slot_b.write_bytes(b"\x00" * SLOT_FRAME_SIZE)
    store1 = ss.SlotStore(slot_a, slot_b, keys)
    store1.load()
    monkeypatch.setattr(
        ss,
        "select_active_slot",
        lambda *args, **kwargs: SelectionResult(
            status=SelectionStatus.REPAIR_REQUIRED,
            state=None,
            active_slot=None,
            reason="repair required",
        ),
    )
    with pytest.raises(ss.SlotStoreError) as exc1:
        store1.write_state(state_rev3)
    assert hasattr(exc1.value, "code")
    store1.close()
    monkeypatch.undo()

    # Scenario 2: wrong active slot
    slot_a.write_bytes(_pack_state(state_rev2))
    slot_b.write_bytes(b"\x00" * SLOT_FRAME_SIZE)
    store2 = ss.SlotStore(slot_a, slot_b, keys)
    store2.load()
    monkeypatch.setattr(
        ss,
        "select_active_slot",
        lambda *args, **kwargs: SelectionResult(
            status=SelectionStatus.SELECTED,
            state=state_rev3,
            active_slot="a",
            reason=None,
        ),
    )
    with pytest.raises(ss.SlotStoreError) as exc2:
        store2.write_state(state_rev3)
    assert hasattr(exc2.value, "code")
    store2.close()
    monkeypatch.undo()

    # Scenario 3: wrong state
    slot_a.write_bytes(_pack_state(state_rev2))
    slot_b.write_bytes(b"\x00" * SLOT_FRAME_SIZE)
    store3 = ss.SlotStore(slot_a, slot_b, keys)
    store3.load()
    state_rev3_diff = dataclasses.replace(state_rev3, installation_id="9" * 32)
    monkeypatch.setattr(
        ss,
        "select_active_slot",
        lambda *args, **kwargs: SelectionResult(
            status=SelectionStatus.SELECTED,
            state=state_rev3_diff,
            active_slot="b",
            reason=None,
        ),
    )
    with pytest.raises(ss.SlotStoreError) as exc3:
        store3.write_state(state_rev3)
    assert hasattr(exc3.value, "code")
    store3.close()
    monkeypatch.undo()


def test_write_state_fails_closed_on_flush(tmp_path, keys, legal_states, monkeypatch):
    import neko_launcher.updater.slot_store as ss
    slot_a = tmp_path / "a.bin"
    slot_b = tmp_path / "b.bin"
    state_rev2, state_rev3 = legal_states

    slot_a.write_bytes(_pack_state(state_rev2))
    slot_b.write_bytes(b"\x00" * SLOT_FRAME_SIZE)

    store = ss.SlotStore(slot_a, slot_b, keys)
    store.load()

    def fail_flush(handle):
        raise OSError("Simulated flush failure")

    monkeypatch.setattr(ss, "_flush_handle", fail_flush, raising=False)

    with pytest.raises(ss.SlotStoreError) as exc:
        store.write_state(state_rev3)

    err = str(exc.value)
    payload_sha = state_rev3.committed.binding.payload_sha256
    assert state_rev3.evidence[payload_sha] not in err
    assert hasattr(exc.value, "code")

    store.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific file identity test")
def test_windows_file_identity_preserved(tmp_path, keys, legal_states):
    import neko_launcher.updater.slot_store as ss
    slot_a = tmp_path / "a.bin"
    slot_b = tmp_path / "b.bin"
    state_rev2, state_rev3 = legal_states

    slot_a.write_bytes(_pack_state(state_rev2))
    slot_b.write_bytes(b"\x00" * SLOT_FRAME_SIZE)

    ino_a = os.stat(slot_a).st_ino
    ino_b = os.stat(slot_b).st_ino

    store = ss.SlotStore(slot_a, slot_b, keys)
    store.load()
    store.write_state(state_rev3)
    store.close()

    assert os.stat(slot_a).st_ino == ino_a
    assert os.stat(slot_b).st_ino == ino_b
    assert os.stat(slot_a).st_size == SLOT_FRAME_SIZE
    assert os.stat(slot_b).st_size == SLOT_FRAME_SIZE
