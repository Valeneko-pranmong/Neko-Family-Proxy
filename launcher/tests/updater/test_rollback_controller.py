import pytest

from neko_launcher.updater.rollback_controller import (
    complete_postcommit_rollback_selection,
    initiate_postcommit_rollback,
)
from neko_launcher.updater.state_models import Binding, Generation, Rollback, State


def _make_dummy_gen(seq: int) -> Generation:
    return Generation(
        binding=Binding(release_sequence=seq, release_id=f"r-{seq}", payload_sha256=f"{seq:064x}"),
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )


def test_postcommit_rollback_flow() -> None:
    gen0 = _make_dummy_gen(1)
    gen1 = _make_dummy_gen(2)

    # N+1 committed, N previous
    idle_state = State(
        schema_version=1,
        revision=10,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen1,
        previous=gen0,
        highwater=gen1.binding,
        observed=gen1.binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )

    # Initiate rollback
    rb_state = initiate_postcommit_rollback(idle_state, "STARTUP_FAILED")
    assert rb_state.phase == "ROLLING_BACK"
    assert rb_state.revision == 11
    assert rb_state.rollback is not None
    assert rb_state.rollback.mode == "postcommit"
    assert rb_state.rollback.target == gen0
    assert rb_state.rollback.step == "DRAIN_INTENT"
    assert rb_state.failed == gen1.binding

    # Progress to RESTORE_DONE
    rb_done = State(
        schema_version=1,
        revision=12,
        installation_id=rb_state.installation_id,
        helper_protocol=1,
        enrollment_complete=True,
        phase="ROLLING_BACK",
        committed=rb_state.committed,
        previous=rb_state.previous,
        highwater=rb_state.highwater,
        observed=rb_state.observed,
        failed=rb_state.failed,
        transaction=None,
        cleanup=None,
        rollback=Rollback(
            mode="postcommit",
            target=gen0,
            probation_id=rb_state.rollback.probation_id,
            scratch=[],
            step="RESTORE_DONE",
        ),
        last_error=rb_state.last_error,
        evidence={},
    )

    # Complete selection
    selected = complete_postcommit_rollback_selection(rb_done)
    assert selected.phase == "IDLE"
    assert selected.revision == 13
    assert selected.committed == gen0  # Restored!
    assert selected.previous is None   # Cleared!
    assert selected.highwater == gen1.binding  # Highwater preserved!
    assert selected.observed == gen1.binding   # Observed preserved!
    assert selected.failed == gen1.binding
    assert selected.rollback is None


def test_initiate_postcommit_rollback_requires_previous() -> None:
    gen1 = _make_dummy_gen(1)
    state_no_prev = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen1,
        previous=None,  # No previous!
        highwater=gen1.binding,
        observed=gen1.binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    with pytest.raises(ValueError, match="Postcommit rollback requires non-null previous"):
        initiate_postcommit_rollback(state_no_prev, "TEST")
