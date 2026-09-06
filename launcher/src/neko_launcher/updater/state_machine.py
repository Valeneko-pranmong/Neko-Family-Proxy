"""Exhaustive state transition automaton and transition validator."""
from __future__ import annotations

from neko_launcher.updater.state_models import State


class StateTransitionError(ValueError):
    """Raised when an illegal or non-adjacent state transition is attempted."""


def validate_transition(current: State, next_state: State) -> None:
    """Validate that transitioning from current to next_state conforms to Section 8.1."""
    # 1. Revision must increment by exactly 1, except initial identical ENROLLING
    is_initial_enrolling = (
        current.phase == "ENROLLING"
        and next_state.phase == "ENROLLING"
        and current.revision == 1
        and next_state.revision == 1
        and current == next_state
    )
    if not is_initial_enrolling:
        if next_state.revision != current.revision + 1:
            raise StateTransitionError(
                f"Revision must increment by exactly 1: current {current.revision}, next {next_state.revision}"
            )

    # 2. Immutable installation ID and protocol
    if next_state.installation_id != current.installation_id:
        raise StateTransitionError("Installation ID is immutable")
    if next_state.helper_protocol != current.helper_protocol:
        raise StateTransitionError("Helper protocol is immutable")

    # 3. Monotonic floors
    if current.highwater is not None:
        if next_state.highwater is None:
            raise StateTransitionError("Highwater floor cannot be cleared")
        if next_state.highwater.release_sequence < current.highwater.release_sequence:
            raise StateTransitionError(
                f"Highwater floor cannot decrease: current {current.highwater.release_sequence}, "
                f"next {next_state.highwater.release_sequence}"
            )

    if current.observed is not None:
        if next_state.observed is None:
            raise StateTransitionError("Observed floor cannot be cleared")
        if next_state.observed.release_sequence < current.observed.release_sequence:
            raise StateTransitionError(
                f"Observed floor cannot decrease: current {current.observed.release_sequence}, "
                f"next {next_state.observed.release_sequence}"
            )

    # 4. Same-sequence binding immutability
    if current.observed is not None and next_state.observed is not None:
        if current.observed.release_sequence == next_state.observed.release_sequence:
            if (
                current.observed.payload_sha256 != next_state.observed.payload_sha256
                or current.observed.release_id != next_state.observed.release_id
            ):
                raise StateTransitionError("Same-sequence observed binding cannot change payload or release_id")

    # 5. Phase-specific transition matrix
    cp = current.phase
    np = next_state.phase

    if np == "REPAIR_REQUIRED":
        return

    if cp == "ENROLLING":
        if np == "ENROLLING":
            return
        elif np == "IDLE":
            if next_state.committed is None or next_state.highwater is None:
                raise StateTransitionError("IDLE after enrollment requires committed and highwater")
            return
        raise StateTransitionError(f"Illegal transition from ENROLLING to {np}")

    elif cp == "IDLE":
        if np == "IDLE":
            # Allowed for enrollment final mirror IDLE(false) -> IDLE(true)
            if not current.enrollment_complete and next_state.enrollment_complete:
                return
            raise StateTransitionError("Illegal IDLE -> IDLE transition without enrollment completion")
        elif np == "PREPARING":
            if next_state.transaction is None or next_state.transaction.stage != "ADMITTED":
                raise StateTransitionError("IDLE -> PREPARING requires transaction in ADMITTED stage")
            if next_state.transaction.old != current.committed:
                raise StateTransitionError("Transaction old generation must match current committed")
            return
        elif np == "ROLLING_BACK":
            if current.previous is None:
                raise StateTransitionError("Postcommit rollback from IDLE requires non-null previous generation")
            if next_state.rollback is None or next_state.rollback.mode != "postcommit":
                raise StateTransitionError("Rollback from IDLE must be postcommit")
            return
        raise StateTransitionError(f"Illegal transition from IDLE to {np}")

    elif cp == "PREPARING":
        if np == "PREPARING":
            return
        elif np == "QUIESCING":
            if current.transaction is None or current.transaction.stage != "VERIFIED":
                raise StateTransitionError("PREPARING -> QUIESCING requires transaction in VERIFIED stage")
            return
        elif np in ("CLEANING", "IDLE"):
            # Pre-quiesce abort!
            if next_state.committed != current.committed:
                raise StateTransitionError("Pre-quiesce abort must preserve committed generation")
            if next_state.previous != current.previous:
                raise StateTransitionError("Pre-quiesce abort must preserve previous generation")
            if next_state.transaction is not None:
                raise StateTransitionError("Pre-quiesce abort must clear transaction")
            if next_state.failed != current.observed:
                raise StateTransitionError("Pre-quiesce abort must record failed=observed")
            return
        elif np == "ROLLING_BACK":
            raise StateTransitionError("PREPARING before QUIESCING should use pre-quiesce abort to CLEANING/IDLE")
        raise StateTransitionError(f"Illegal transition from PREPARING to {np}")

    elif cp == "QUIESCING":
        if np == "PROBATION":
            return
        elif np == "ROLLING_BACK":
            if next_state.rollback is None or next_state.rollback.mode != "precommit":
                raise StateTransitionError("Rollback from QUIESCING must be precommit")
            return
        raise StateTransitionError(f"Illegal transition from QUIESCING to {np}")

    elif cp == "PROBATION":
        if np == "CLEANING":
            # Commit transition
            if current.transaction is None:
                raise StateTransitionError("Commit from PROBATION requires active transaction")
            if next_state.committed != current.transaction.candidate:
                raise StateTransitionError("Commit must set committed = candidate")
            if next_state.previous != current.committed:
                raise StateTransitionError("Commit must set previous = old committed")
            if next_state.transaction is not None:
                raise StateTransitionError("Commit must clear transaction")
            return
        elif np == "ROLLING_BACK":
            if next_state.rollback is None:
                raise StateTransitionError("Rollback from PROBATION requires rollback descriptor")
            return
        raise StateTransitionError(f"Illegal transition from PROBATION to {np}")

    elif cp == "ROLLING_BACK":
        if np == "ROLLING_BACK":
            return
        elif np in ("CLEANING", "IDLE"):
            if current.rollback is None:
                raise StateTransitionError("ROLLING_BACK completion requires rollback record")
            if current.rollback.mode == "precommit":
                if next_state.committed != current.committed:
                    raise StateTransitionError("Precommit rollback completion must keep committed")
                if next_state.previous != current.previous:
                    raise StateTransitionError("Precommit rollback completion must keep previous")
            elif current.rollback.mode == "postcommit":
                if next_state.committed != current.rollback.target:
                    raise StateTransitionError("Postcommit rollback must set committed = rollback target")
                if next_state.previous is not None:
                    raise StateTransitionError("Postcommit rollback must set previous = null")
            if next_state.rollback is not None:
                raise StateTransitionError("Rollback completion must clear rollback record")
            return
        raise StateTransitionError(f"Illegal transition from ROLLING_BACK to {np}")

    elif cp == "CLEANING":
        if np == "CLEANING":
            return
        elif np == "IDLE":
            if next_state.cleanup is not None:
                raise StateTransitionError("IDLE requires empty/null cleanup queue")
            return
        elif np == "ROLLING_BACK":
            if current.previous is None:
                raise StateTransitionError("Rollback from CLEANING requires non-null previous generation")
            return
        raise StateTransitionError(f"Illegal transition from CLEANING to {np}")

    raise StateTransitionError(f"Unsupported transition from {cp} to {np}")
