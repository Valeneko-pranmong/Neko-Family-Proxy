from pathlib import Path

from neko_launcher.updater.binary_frame import SlotFrame, pack_slot_frame
from neko_launcher.updater.recovery_engine import RecoveryEngine
from neko_launcher.updater.state_models import (
    DirectoryIdentity,
    Generation,
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
        launcher_identity_sha256="3" * 64,
        core_identity_sha256="2" * 64,
    )
    return gen, p_sha, env_b64


def test_recovery_from_idle_converges_and_is_idempotent(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    gen1, p_sha, env_b64 = _make_dummy_gen(1)
    releases_dir = tmp_path / "releases" / f"g-{gen1.binding.release_sequence:020d}-{gen1.binding.payload_sha256}"
    releases_dir.mkdir(parents=True)
    s = State(
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
        evidence={p_sha: env_b64},
    )
    frame = pack_slot_frame(SlotFrame(revision=1, format_version=1, body_bytes=serialize_state(s)))
    (state_dir / "slot-a.bin").write_bytes(frame)

    engine = RecoveryEngine(tmp_path, {TEST_KEY_ID: TEST_PUBLIC_KEY})
    res1 = engine.run_recovery()
    assert res1.converged
    assert res1.selected_generation == gen1

    # Idempotence: second recovery performs 0 mutations
    res2 = engine.run_recovery()
    assert res2.converged
    assert res2.mutations_performed == 0
    assert res2.selected_generation == gen1


def test_recovery_from_preparing_aborts_candidate(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    gen1, p_sha1, env_b64_1 = _make_dummy_gen(1)
    releases_dir = tmp_path / "releases" / f"g-{gen1.binding.release_sequence:020d}-{gen1.binding.payload_sha256}"
    releases_dir.mkdir(parents=True)
    gen2, p_sha2, env_b64_2 = _make_dummy_gen(2)

    inc_dir = tmp_path / "incoming" / ("b" * 32)
    inc_dir.mkdir(parents=True)
    (inc_dir / "partial.tmp").write_text("junk")

    tx = Transaction(
        id="a" * 32,
        request_id="b" * 32,
        candidate=gen2,
        old=gen1,
        incoming=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="0" * 32, parent_file_id="0" * 32),
        staging=None,
        stage="ADMITTED",
        mutation=None,
    )
    s = State(
        schema_version=1,
        revision=1,
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
    frame = pack_slot_frame(SlotFrame(revision=1, format_version=1, body_bytes=serialize_state(s)))
    (state_dir / "slot-a.bin").write_bytes(frame)

    engine = RecoveryEngine(tmp_path, {TEST_KEY_ID: TEST_PUBLIC_KEY})
    res = engine.run_recovery()
    assert res.converged
    assert res.selected_generation == gen1
    assert res.final_state is not None
    assert res.final_state.phase == "IDLE"
    assert res.final_state.failed == gen2.binding
