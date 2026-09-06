"""Postcommit rollback controller executing restricted probation and floor-preserving selection."""
from __future__ import annotations

from neko_launcher.updater.state_models import State


def initiate_postcommit_rollback(current_state: State, error_code: str) -> State:
    """Initiate postcommit rollback from IDLE or CLEANING phase into ROLLING_BACK DRAIN_INTENT."""
    raise NotImplementedError("initiate_postcommit_rollback not implemented")


def complete_postcommit_rollback_selection(current_state: State) -> State:
    """Finalize postcommit rollback selection into CLEANING or IDLE after RESTORE_DONE."""
    raise NotImplementedError("complete_postcommit_rollback_selection not implemented")
