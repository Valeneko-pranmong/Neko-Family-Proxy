from pathlib import Path

from neko_launcher.updater.binary_frame import SlotFrame, pack_slot_frame
from neko_launcher.updater.recovery_engine import RecoveryEngine
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


def _make_dummy_gen(seq: int) -> Generation:
    return Generation(
        binding=Binding(release_sequence=seq, release_id=f"r-{seq}", payload_sha256=f"{seq:064x}"),
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )


def test_recovery_from_idle_converges_and_is_idempotent(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    gen1 = _make_dummy_gen(1)
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
        evidence={},
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
