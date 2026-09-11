"""Postcommit rollback controller executing restricted probation and floor-preserving selection."""
from __future__ import annotations

import secrets

from neko_launcher.updater.state_machine import validate_transition
from neko_launcher.updater.state_models import Rollback, State


def initiate_postcommit_rollback(current_state: State, error_code: str) -> State:
    """Initiate postcommit rollback from IDLE or CLEANING phase into ROLLING_BACK DRAIN_INTENT."""
    if current_state.phase not in ("IDLE", "CLEANING"):
        raise ValueError(f"Postcommit rollback only valid from IDLE or CLEANING phase, got: {current_state.phase}")
    if current_state.previous is None:
        raise ValueError("Postcommit rollback requires non-null previous generation")

    probation_id = secrets.token_hex(16)
    scratch = list(current_state.cleanup) if current_state.cleanup is not None else []

    rb = Rollback(
        mode="postcommit",
        target=current_state.previous,
        probation_id=probation_id,
        scratch=scratch,
        step="DRAIN_INTENT",
    )

    next_state = State(
        schema_version=1,
        revision=current_state.revision + 1,
        installation_id=current_state.installation_id,
        helper_protocol=current_state.helper_protocol,
        enrollment_complete=current_state.enrollment_complete,
        phase="ROLLING_BACK",
        committed=current_state.committed,
        previous=current_state.previous,
        highwater=current_state.highwater,
        observed=current_state.observed,
        failed=current_state.observed,
        transaction=None,
        cleanup=None,
        rollback=rb,
        last_error=error_code,
        evidence=current_state.evidence,
    )

    validate_transition(current_state, next_state)
    return next_state


def complete_postcommit_rollback_selection(current_state: State) -> State:
    """Finalize postcommit rollback selection into CLEANING or IDLE after RESTORE_DONE."""
    if current_state.phase != "ROLLING_BACK" or current_state.rollback is None:
        raise ValueError("State must be in ROLLING_BACK phase with active rollback record")
    if current_state.rollback.step != "RESTORE_DONE":
        raise ValueError(f"Rollback selection requires RESTORE_DONE step, got: {current_state.rollback.step}")

    target = current_state.rollback.target
    scratch = list(current_state.rollback.scratch)
    next_phase = "CLEANING" if scratch else "IDLE"
    next_cleanup = scratch if scratch else None

    next_state = State(
        schema_version=1,
        revision=current_state.revision + 1,
        installation_id=current_state.installation_id,
        helper_protocol=current_state.helper_protocol,
        enrollment_complete=current_state.enrollment_complete,
        phase=next_phase,
        committed=target,
        previous=None,  # Cleared on postcommit rollback
        highwater=current_state.highwater,  # Preserved!
        observed=current_state.observed,    # Preserved!
        failed=current_state.failed,
        transaction=None,
        cleanup=next_cleanup,
        rollback=None,
        last_error=current_state.last_error,
        evidence=current_state.evidence,
    )

    validate_transition(current_state, next_state)
    return next_state
