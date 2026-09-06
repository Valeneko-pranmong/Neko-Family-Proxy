"""Precommit update abort handler preserving active family and prior rollback descriptor."""
from __future__ import annotations

from neko_launcher.updater.state_models import State


def execute_precommit_abort(current_state: State, error_code: str) -> State:
    """Execute pre-quiesce abort from PREPARING phase, preserving healthy active family and previous backup."""
    raise NotImplementedError("execute_precommit_abort not implemented")
