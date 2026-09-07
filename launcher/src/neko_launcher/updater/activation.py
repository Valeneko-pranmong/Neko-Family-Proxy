import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neko_launcher.updater.precommit_abort import execute_precommit_abort
from neko_launcher.updater.probation_runner import run_probation_self_test
from neko_launcher.updater.slot_selector import SelectionStatus
from neko_launcher.updater.state_machine import validate_transition
from neko_launcher.updater.state_models import Cleanup, Generation


@dataclass(frozen=True)
class ActivationResult:
    committed: bool
    generation: Generation | None
    error: str | None = None

def activate_verified_generation(
    root_dir: Path, 
    slot_store: Any, 
    self_test: Callable = run_probation_self_test
) -> ActivationResult:
    selection = slot_store.load()
    if selection.status != SelectionStatus.SELECTED or selection.state is None:
        return ActivationResult(False, None, 'STATE_CORRUPT')
        
    current_state = selection.state
    tx = current_state.transaction
    
    if (
        current_state.phase != "PREPARING" or 
        tx is None or 
        tx.stage != "VERIFIED" or 
        tx.staging is None
    ):
        return ActivationResult(False, None, 'PROTOCOL_INVALID')
        
    candidate = tx.candidate
    candidate_path = root_dir / 'releases' / f"g-{candidate.binding.release_sequence:020d}-{candidate.binding.payload_sha256}"
    
    def _durable_write(state) -> bool:
        try:
            res = slot_store.write_state(state)
            return res.status == SelectionStatus.SELECTED and res.state == state
        except Exception:  # noqa: BLE001
            return False

    try:
        test_result = self_test(candidate_path)
    except Exception:  # noqa: BLE001
        test_result = None
        
    if test_result is None or not test_result.passed:
        error_code = test_result.error_code if (test_result and test_result.error_code) else 'SELFTEST_FAILED'
        try:
            abort_state = execute_precommit_abort(current_state, error_code)
            if not _durable_write(abort_state):
                return ActivationResult(False, None, 'STATE_CORRUPT')
        except Exception:  # noqa: BLE001
            return ActivationResult(False, None, 'STATE_CORRUPT')
        return ActivationResult(False, None, error_code)
        
    try:
        # a. QUIESCING
        new_tx_q = dataclasses.replace(tx, stage='QUIESCING', mutation=None)
        state_q = dataclasses.replace(
            current_state, 
            phase='QUIESCING', 
            transaction=new_tx_q, 
            revision=current_state.revision + 1
        )
        validate_transition(current_state, state_q)
    except Exception:  # noqa: BLE001
        return ActivationResult(False, None, 'STATE_CORRUPT')

    if not _durable_write(state_q):
        return ActivationResult(False, None, 'STATE_CORRUPT')
        
    try:
        # b. PROBATION
        new_tx_p = dataclasses.replace(state_q.transaction, stage='PROBATION', mutation=None)
        state_p = dataclasses.replace(
            state_q, 
            phase='PROBATION', 
            transaction=new_tx_p, 
            revision=state_q.revision + 1
        )
        validate_transition(state_q, state_p)
    except Exception:  # noqa: BLE001
        return ActivationResult(False, None, 'STATE_CORRUPT')

    if not _durable_write(state_p):
        return ActivationResult(False, None, 'STATE_CORRUPT')
        
    try:
        # c. CLEANING
        cleanups = [
            Cleanup(
                transaction_id=state_p.transaction.id,
                request_id=state_p.transaction.request_id,
                directory=state_p.transaction.incoming,
                target='incoming',
                status='INTENT'
            ),
            Cleanup(
                transaction_id=state_p.transaction.id,
                request_id=state_p.transaction.request_id,
                directory=state_p.transaction.staging,
                target='staging',
                status='INTENT'
            )
        ]
        
        state_c = dataclasses.replace(
            state_p,
            phase='CLEANING',
            revision=state_p.revision + 1,
            committed=candidate,
            previous=state_p.committed,
            highwater=candidate.binding,
            observed=candidate.binding,
            transaction=None,
            cleanup=cleanups,
            rollback=None,
            last_error=None
        )
        validate_transition(state_p, state_c)
    except Exception:  # noqa: BLE001
        return ActivationResult(False, None, 'STATE_CORRUPT')

    if not _durable_write(state_c):
        return ActivationResult(False, None, 'STATE_CORRUPT')
        
    return ActivationResult(True, candidate, None)
