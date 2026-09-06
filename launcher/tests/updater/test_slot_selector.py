import base64
import hashlib

from neko_launcher.updater.binary_frame import SlotFrame, pack_slot_frame
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.slot_selector import SelectionStatus, select_active_slot
from neko_launcher.updater.state_models import (
    Binding,
    DirectoryIdentity,
    Generation,
    State,
    Transaction,
    serialize_state,
)
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_release_document,
)


def _make_signed_evidence(seq: int, rel_id: str) -> tuple[Binding, str, str]:
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
    return binding, payload_sha, envelope_b64


def _make_state(rev: int, seq: int) -> State:
    binding, p_sha, env_b64 = _make_signed_evidence(seq, f"rel-{seq}")
    gen = Generation(
        binding=binding,
        launcher_identity_sha256="3" * 64,
        core_identity_sha256="2" * 64,
    )
    return State(
        schema_version=1,
        revision=rev,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen,
        previous=None,
        highwater=binding,
        observed=binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={p_sha: env_b64},
    )


def _pack_state(state: State) -> bytes:
    body = serialize_state(state)
    frame = SlotFrame(revision=state.revision, format_version=1, body_bytes=body)
    return pack_slot_frame(frame)


def test_select_highest_consecutive_valid_revision() -> None:
    s1 = _make_state(rev=10, seq=1)
    b2, p2, e2 = _make_signed_evidence(2, "rel-2")
    cand2 = Generation(binding=b2, launcher_identity_sha256="3" * 64, core_identity_sha256="2" * 64)
    tx2 = Transaction(
        id="a" * 32,
        request_id="b" * 32,
        candidate=cand2,
        old=s1.committed,
        incoming=DirectoryIdentity("12345678abcdef01", "0" * 32, "0" * 32),
        staging=None,
        stage="ADMITTED",
        mutation=None,
    )
    s2 = State(
        schema_version=1,
        revision=11,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PREPARING",
        committed=s1.committed,
        previous=None,
        highwater=s1.highwater,
        observed=b2,
        failed=None,
        transaction=tx2,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={**s1.evidence, p2: e2},
    )
    slot_a = _pack_state(s1)
    slot_b = _pack_state(s2)
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}

    res = select_active_slot(slot_a, slot_b, keys)
    assert res.status == SelectionStatus.SELECTED
    assert res.state is not None
    assert res.state.revision == 11
    assert res.active_slot == "b"


def test_select_valid_when_other_slot_torn() -> None:
    s1 = _make_state(rev=5, seq=1)
    slot_a = _pack_state(s1)
    slot_b = b"corrupted bytes..."
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}

    res = select_active_slot(slot_a, slot_b, keys)
    assert res.status == SelectionStatus.SELECTED
    assert res.state is not None
    assert res.state.revision == 5
    assert res.active_slot == "a"


def test_repair_required_when_higher_slot_malformed() -> None:
    s1 = _make_state(rev=5, seq=1)
    slot_a = _pack_state(s1)
    # Frame is valid format, but JSON body is invalid schema (missing required fields)
    bad_frame = SlotFrame(revision=6, format_version=1, body_bytes=b'{"bad":1}')
    slot_b = pack_slot_frame(bad_frame)
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}

    res = select_active_slot(slot_a, slot_b, keys)
    assert res.status == SelectionStatus.REPAIR_REQUIRED
    assert res.reason is not None and "malformed" in res.reason.lower()


def test_repair_required_when_stale_lower_slot_malformed() -> None:
    bad_frame = SlotFrame(revision=4, format_version=1, body_bytes=b'{"bad":1}')
    slot_a = pack_slot_frame(bad_frame)
    s2 = _make_state(rev=5, seq=1)
    slot_b = _pack_state(s2)
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}

    res = select_active_slot(slot_a, slot_b, keys)
    assert res.status == SelectionStatus.REPAIR_REQUIRED
    assert res.reason is not None and "stale" in res.reason.lower()


def test_repair_required_when_nonadjacent_revisions() -> None:
    s1 = _make_state(rev=3, seq=1)
    s2 = _make_state(rev=5, seq=2)  # Gap!
    slot_a = _pack_state(s1)
    slot_b = _pack_state(s2)
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}

    res = select_active_slot(slot_a, slot_b, keys)
    assert res.status == SelectionStatus.REPAIR_REQUIRED
    assert res.reason is not None and "nonadjacent" in res.reason.lower()


def test_repair_required_when_evidence_unauthenticated() -> None:
    s1 = _make_state(rev=1, seq=1)
    # Tamper with evidence envelope base64
    from dataclasses import asdict
    s1_dict = asdict(s1)
    s1_dict["evidence"] = {list(s1.evidence.keys())[0]: "dGFtcGVyZWQtZW52ZWxvcGU="}
    # Serialize manually with canonical json dumps
    body = canonical_json_dumps(s1_dict)
    slot_a = pack_slot_frame(SlotFrame(revision=1, format_version=1, body_bytes=body))
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}

    res = select_active_slot(slot_a, None, keys)
    assert res.status == SelectionStatus.REPAIR_REQUIRED
    assert res.reason is not None and "evidence" in res.reason.lower()


def test_enrollment_incomplete_when_both_slots_none() -> None:
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}
    res = select_active_slot(None, None, keys)
    assert res.status == SelectionStatus.ENROLLMENT_INCOMPLETE
