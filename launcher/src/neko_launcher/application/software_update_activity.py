from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from neko_launcher.domain.models import AppState, GameStatus, ProxyStatus

__all__ = [
    "SessionActivityGuard",
    "UpdateApplyBlocker",
    "UpdateApplySafety",
    "evaluate_update_apply_safety",
]


class UpdateApplyBlocker(str, Enum):
    GAME_ACTIVE = "game_active"
    PROXY_ACTIVE = "proxy_active"
    GAME_TRANSITION = "game_transition"
    UPDATE_BUSY = "update_busy"


@dataclass(frozen=True)
class UpdateApplySafety:
    safe: bool
    blocker: UpdateApplyBlocker | None = None


def _state_val(val: Any) -> Any:
    return getattr(val, "value", val)


def evaluate_update_apply_safety(
    state: AppState,
    *,
    update_busy: bool = False,
) -> UpdateApplySafety:
    """Evaluate whether an update can safely be applied in the current launcher state.

    This pure policy enforces:
    - Game active (running process or RUNNING state) blocks with GAME_ACTIVE.
    - Game transition (STARTING, FAILED, or any non-STOPPED game state) blocks with GAME_TRANSITION.
    - Concurrent update in progress (update_busy=True) blocks with UPDATE_BUSY.
    - Active proxy (RUNNING, STARTING, RECONNECTING, STOPPING, FAILED) blocks with PROXY_ACTIVE.
    - Both stopped and idle is safe (safe=True, blocker=None).

    Precedence ensures game activity is protected above all else so game sessions
    are never terminated or disrupted.
    """
    is_game_process_running = bool(getattr(state, "game_process_running", False))
    game_status = getattr(state, "game_status", GameStatus.STOPPED)
    proxy_status = getattr(state, "proxy_status", ProxyStatus.STOPPED)

    norm_game = _state_val(game_status)
    norm_proxy = _state_val(proxy_status)

    if is_game_process_running or norm_game == GameStatus.RUNNING.value:
        return UpdateApplySafety(safe=False, blocker=UpdateApplyBlocker.GAME_ACTIVE)

    if norm_game != GameStatus.STOPPED.value:
        return UpdateApplySafety(safe=False, blocker=UpdateApplyBlocker.GAME_TRANSITION)

    if update_busy:
        return UpdateApplySafety(safe=False, blocker=UpdateApplyBlocker.UPDATE_BUSY)

    if norm_proxy != ProxyStatus.STOPPED.value:
        return UpdateApplySafety(safe=False, blocker=UpdateApplyBlocker.PROXY_ACTIVE)

    return UpdateApplySafety(safe=True, blocker=None)


class SessionActivityGuard:
    """Pure policy helper checking if an update can safely be applied."""

    @staticmethod
    def evaluate(
        state: AppState,
        *,
        update_busy: bool = False,
    ) -> UpdateApplySafety:
        return evaluate_update_apply_safety(state, update_busy=update_busy)

    @staticmethod
    def is_safe(
        state: AppState,
        *,
        update_busy: bool = False,
    ) -> bool:
        return evaluate_update_apply_safety(state, update_busy=update_busy).safe
