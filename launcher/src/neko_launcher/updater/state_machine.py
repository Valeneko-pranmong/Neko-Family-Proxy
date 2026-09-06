"""Exhaustive state transition automaton and transition validator."""
from __future__ import annotations

from neko_launcher.updater.state_models import State


class StateTransitionError(ValueError):
    """Raised when an illegal or non-adjacent state transition is attempted."""


def validate_transition(current: State, next_state: State) -> None:
    """Validate that transitioning from current to next_state conforms to Section 8.1."""
    raise NotImplementedError("validate_transition not implemented")
