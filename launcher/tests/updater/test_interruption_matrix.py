from pathlib import Path

from neko_launcher.updater.binary_frame import SlotFrame, pack_slot_frame
from neko_launcher.updater.recovery_engine import RecoveryEngine
from neko_launcher.updater.state_models import (
    DirectoryIdentity,
    Generation,
    Mutation,
    State,
    Transaction,
    serialize_state,
)
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
)
from tests.updater.test_slot_selector import _make_signed_evidence


def _make_dummy_gen(seq: int) -> tuple[Generation, str, str]:
    binding, p_sha, env_b64 = _make_signed_evidence(seq, f"r-{seq}")
    gen = Generation(
        binding=binding,
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )
    return gen, p_sha, env_b64


def test_interruption_torn_slot_write(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    gen1, p_sha1, env_b64_1 = _make_dummy_gen(1)

    s1 = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen1,
        previous=None,
        highwater=gen1.binding,
        observed=gen1.binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={p_sha1: env_b64_1},
    )
    # Slot A is valid revision 1
    (state_dir / "slot-a.bin").write_bytes(
        pack_slot_frame(SlotFrame(revision=1, format_version=1, body_bytes=serialize_state(s1)))
    )
    # Slot B is torn (corrupt bytes simulating power cut during write)
    (state_dir / "slot-b.bin").write_bytes(b"NEKOUPD1\x00\x00partial write junk...")

    engine = RecoveryEngine(tmp_path, {TEST_KEY_ID: TEST_PUBLIC_KEY})
    res = engine.run_recovery()
    assert res.converged
    assert res.selected_generation == gen1


def test_interruption_during_building_rolls_back_idempotently(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    gen1, p_sha1, env_b64_1 = _make_dummy_gen(1)
    gen2, p_sha2, env_b64_2 = _make_dummy_gen(2)

    tx_id = "a" * 32
    req_id = "b" * 32
    stage_dir = tmp_path / "staging" / tx_id
    stage_dir.mkdir(parents=True)
    (stage_dir / "partial_file.tmp").write_text("incomplete write")

    tx = Transaction(
        id=tx_id,
        request_id=req_id,
        candidate=gen2,
        old=gen1,
        incoming=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="0" * 32, parent_file_id="0" * 32),
        staging=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="1" * 32, parent_file_id="0" * 32),
        stage="BUILDING",
        mutation=Mutation(kind="WRITE_CANDIDATE", target="stage", status="INTENT"),
    )
    s = State(
        schema_version=1,
        revision=2,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PREPARING",
        committed=gen1,
        previous=None,
        highwater=gen1.binding,
        observed=gen2.binding,
        failed=None,
        transaction=tx,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={p_sha1: env_b64_1, p_sha2: env_b64_2},
    )
    (state_dir / "slot-a.bin").write_bytes(
        pack_slot_frame(SlotFrame(revision=2, format_version=1, body_bytes=serialize_state(s)))
    )

    engine = RecoveryEngine(tmp_path, {TEST_KEY_ID: TEST_PUBLIC_KEY})
    res1 = engine.run_recovery()
    assert res1.converged
    assert res1.selected_generation == gen1

    # Second run must be completely idempotent
    res2 = engine.run_recovery()
    assert res2.converged
    assert res2.mutations_performed == 0
    assert res2.selected_generation == gen1


def test_interruption_during_probation_executes_rollback(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    gen1, p_sha1, env_b64_1 = _make_dummy_gen(1)
    gen2, p_sha2, env_b64_2 = _make_dummy_gen(2)

    tx_id = "a" * 32
    req_id = "b" * 32
    tx = Transaction(
        id=tx_id,
        request_id=req_id,
        candidate=gen2,
        old=gen1,
        incoming=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="0" * 32, parent_file_id="0" * 32),
        staging=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="1" * 32, parent_file_id="0" * 32),
        stage="PROBATION",
        mutation=Mutation(kind="START_PROBATION", target="candidate_process_family", status="INTENT"),
    )
    s = State(
        schema_version=1,
        revision=3,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PROBATION",
        committed=gen1,
        previous=None,
        highwater=gen1.binding,
        observed=gen2.binding,
        failed=None,
        transaction=tx,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={p_sha1: env_b64_1, p_sha2: env_b64_2},
    )
    (state_dir / "slot-a.bin").write_bytes(
        pack_slot_frame(SlotFrame(revision=3, format_version=1, body_bytes=serialize_state(s)))
    )

    engine = RecoveryEngine(tmp_path, {TEST_KEY_ID: TEST_PUBLIC_KEY})
    res = engine.run_recovery()
    assert res.converged
    assert res.selected_generation == gen1
    assert res.final_state is not None
    assert res.final_state.phase == "IDLE"
    assert res.final_state.failed == gen2.binding
