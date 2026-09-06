"""Precommit update abort handler preserving active family and prior rollback descriptor."""
from __future__ import annotations

from neko_launcher.updater.state_machine import validate_transition
from neko_launcher.updater.state_models import Cleanup, State


def execute_precommit_abort(current_state: State, error_code: str) -> State:
    """Execute pre-quiesce abort from PREPARING phase, preserving healthy active family and previous backup."""
    if current_state.phase != "PREPARING":
        raise ValueError(f"Precommit abort only valid from PREPARING phase, got: {current_state.phase}")

    cleanup_queue: list[Cleanup] = []
    tx = current_state.transaction
    if tx is not None:
        cleanup_queue.append(
            Cleanup(
                transaction_id=tx.id,
                request_id=tx.request_id,
                directory=tx.incoming,
                target="incoming",
                status="INTENT",
            )
        )
        if tx.staging is not None:
            cleanup_queue.append(
                Cleanup(
                    transaction_id=tx.id,
                    request_id=tx.request_id,
                    directory=tx.staging,
                    target="staging",
                    status="INTENT",
                )
            )

    next_phase = "CLEANING" if cleanup_queue else "IDLE"
    next_cleanup = cleanup_queue if cleanup_queue else None

    next_state = State(
        schema_version=1,
        revision=current_state.revision + 1,
        installation_id=current_state.installation_id,
        helper_protocol=current_state.helper_protocol,
        enrollment_complete=current_state.enrollment_complete,
        phase=next_phase,
        committed=current_state.committed,
        previous=current_state.previous,  # Preserved!
        highwater=current_state.highwater,
        observed=current_state.observed,
        failed=current_state.observed,    # Recorded!
        transaction=None,
        cleanup=next_cleanup,
        rollback=None,
        last_error=error_code,
        evidence=current_state.evidence,
    )

    validate_transition(current_state, next_state)
    return next_state
