import pytest

from neko_launcher.updater.state_machine import StateTransitionError, validate_transition
from neko_launcher.updater.state_models import (
    Binding,
    Cleanup,
    DirectoryIdentity,
    Generation,
    State,
    Transaction,
)


def _make_dummy_gen(seq: int) -> Generation:
    return Generation(
        binding=Binding(release_sequence=seq, release_id=f"r-{seq}", payload_sha256=f"{seq:064x}"),
        launcher_identity_sha256="1" * 64,
        core_identity_sha256="2" * 64,
    )


def _make_dir_id(name: int) -> DirectoryIdentity:
    return DirectoryIdentity(
        volume_serial="12345678abcdef01",
        file_id=f"{name:032x}",
        parent_file_id="0" * 32,
    )


def test_transition_enforces_revision_increment() -> None:
    gen = _make_dummy_gen(1)
    s1 = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen,
        previous=None,
        highwater=gen.binding,
        observed=gen.binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    s2 = State(
        schema_version=1,
        revision=1,  # Same revision!
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen,
        previous=None,
        highwater=gen.binding,
        observed=gen.binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    with pytest.raises(StateTransitionError, match="Revision must increment by exactly 1"):
        validate_transition(s1, s2)


def test_idle_to_preparing_admitted_transition() -> None:
    gen1 = _make_dummy_gen(1)
    gen2 = _make_dummy_gen(2)
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
        evidence={},
    )
    tx = Transaction(
        id="a" * 32,
        request_id="b" * 32,
        candidate=gen2,
        old=gen1,
        incoming=_make_dir_id(1),
        staging=None,
        stage="ADMITTED",
        mutation=None,
    )
    s2 = State(
        schema_version=1,
        revision=2,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PREPARING",
        committed=gen1,
        previous=None,
        highwater=gen1.binding,
        observed=gen2.binding,  # Advanced
        failed=None,
        transaction=tx,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    validate_transition(s1, s2)


def test_pre_quiesce_abort_preserves_previous() -> None:
    gen0 = _make_dummy_gen(1)
    gen1 = _make_dummy_gen(2)
    gen2 = _make_dummy_gen(3)
    tx = Transaction(
        id="a" * 32,
        request_id="b" * 32,
        candidate=gen2,
        old=gen1,
        incoming=_make_dir_id(1),
        staging=None,
        stage="ADMITTED",
        mutation=None,
    )
    s_preparing = State(
        schema_version=1,
        revision=5,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PREPARING",
        committed=gen1,
        previous=gen0,  # Valid previous exists!
        highwater=gen1.binding,
        observed=gen2.binding,
        failed=None,
        transaction=tx,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    cleanup_item = Cleanup(
        transaction_id=tx.id,
        request_id=tx.request_id,
        directory=tx.incoming,
        target="incoming",
        status="INTENT",
    )
    s_abort = State(
        schema_version=1,
        revision=6,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="CLEANING",
        committed=gen1,
        previous=gen0,  # Must be preserved!
        highwater=gen1.binding,
        observed=gen2.binding,
        failed=gen2.binding,
        transaction=None,
        cleanup=[cleanup_item],
        rollback=None,
        last_error="CANCELLED",
        evidence={},
    )
    validate_transition(s_preparing, s_abort)


def test_illegal_highwater_decrease_rejected() -> None:
    gen1 = _make_dummy_gen(1)
    gen2 = _make_dummy_gen(2)
    s1 = State(
        schema_version=1,
        revision=10,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen2,
        previous=gen1,
        highwater=gen2.binding,
        observed=gen2.binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    s2 = State(
        schema_version=1,
        revision=11,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen1,
        previous=None,
        highwater=gen1.binding,  # Decreased highwater floor!
        observed=gen2.binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    with pytest.raises(StateTransitionError, match="Highwater floor cannot decrease"):
        validate_transition(s1, s2)
