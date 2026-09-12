from __future__ import annotations

from types import SimpleNamespace

import pytest

from neko_launcher.application.software_update_activity import (
    SessionActivityGuard,
    UpdateApplyBlocker,
    UpdateApplySafety,
    evaluate_update_apply_safety,
)
from neko_launcher.domain.models import AppState, GameStatus, ProxyStatus


def test_update_apply_blocker_enum_values() -> None:
    assert UpdateApplyBlocker.GAME_ACTIVE.value == "game_active"
    assert UpdateApplyBlocker.PROXY_ACTIVE.value == "proxy_active"
    assert UpdateApplyBlocker.GAME_TRANSITION.value == "game_transition"
    assert UpdateApplyBlocker.UPDATE_BUSY.value == "update_busy"


def test_update_apply_safety_frozen() -> None:
    safety = UpdateApplySafety(safe=True, blocker=None)
    assert safety.safe is True
    assert safety.blocker is None
    with pytest.raises(AttributeError):
        safety.safe = False  # type: ignore[misc]


def test_evaluate_safety_when_stopped_and_idle_is_safe() -> None:
    state = AppState(
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.STOPPED,
        game_process_running=False,
    )
    safety = evaluate_update_apply_safety(state, update_busy=False)
    assert safety == UpdateApplySafety(safe=True, blocker=None)
    assert safety.safe is True
    assert safety.blocker is None


@pytest.mark.parametrize(
    "proxy_status",
    [
        ProxyStatus.RUNNING,
        ProxyStatus.STARTING,
        ProxyStatus.RECONNECTING,
        ProxyStatus.STOPPING,
        ProxyStatus.FAILED,
    ],
)
def test_evaluate_safety_blocks_when_proxy_active(proxy_status: ProxyStatus) -> None:
    state = AppState(
        proxy_status=proxy_status,
        game_status=GameStatus.STOPPED,
        game_process_running=False,
    )
    safety = evaluate_update_apply_safety(state, update_busy=False)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.PROXY_ACTIVE


def test_evaluate_safety_blocks_when_game_process_running() -> None:
    state = AppState(
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.STOPPED,
        game_process_running=True,
    )
    safety = evaluate_update_apply_safety(state, update_busy=False)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.GAME_ACTIVE


def test_evaluate_safety_blocks_when_game_status_running() -> None:
    state = AppState(
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.RUNNING,
        game_process_running=False,
    )
    safety = evaluate_update_apply_safety(state, update_busy=False)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.GAME_ACTIVE


def test_evaluate_safety_blocks_when_game_in_transition() -> None:
    state = AppState(
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.STARTING,
        game_process_running=False,
    )
    safety = evaluate_update_apply_safety(state, update_busy=False)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.GAME_TRANSITION


def test_evaluate_safety_blocks_when_game_status_failed() -> None:
    state = AppState(
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.FAILED,
        game_process_running=False,
    )
    safety = evaluate_update_apply_safety(state, update_busy=False)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.GAME_TRANSITION


def test_evaluate_safety_blocks_when_update_busy() -> None:
    state = AppState(
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.STOPPED,
        game_process_running=False,
    )
    safety = evaluate_update_apply_safety(state, update_busy=True)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.UPDATE_BUSY


def test_game_active_precedence_over_proxy_active() -> None:
    # Game must never be terminated or interrupted by proxy shutdown
    state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_status=GameStatus.RUNNING,
        game_process_running=True,
    )
    safety = evaluate_update_apply_safety(state, update_busy=False)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.GAME_ACTIVE


def test_game_process_running_precedence_over_proxy_active() -> None:
    # Game process alive takes precedence even if controller game_status is STOPPED
    state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_status=GameStatus.STOPPED,
        game_process_running=True,
    )
    safety = evaluate_update_apply_safety(state, update_busy=False)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.GAME_ACTIVE


def test_game_transition_precedence_over_proxy_active() -> None:
    state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_status=GameStatus.STARTING,
        game_process_running=False,
    )
    safety = evaluate_update_apply_safety(state, update_busy=False)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.GAME_TRANSITION


def test_game_active_precedence_over_update_busy() -> None:
    # Active game session takes precedence as root blocker
    state = AppState(
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.RUNNING,
        game_process_running=True,
    )
    safety = evaluate_update_apply_safety(state, update_busy=True)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.GAME_ACTIVE


def test_update_busy_precedence_over_proxy_active() -> None:
    state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_status=GameStatus.STOPPED,
        game_process_running=False,
    )
    safety = evaluate_update_apply_safety(state, update_busy=True)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.UPDATE_BUSY


def test_string_status_compatibility() -> None:
    mock_state = SimpleNamespace(
        proxy_status="running",
        game_status="stopped",
        game_process_running=False,
    )
    safety = evaluate_update_apply_safety(mock_state, update_busy=False)  # type: ignore[arg-type]
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.PROXY_ACTIVE


def test_session_activity_guard_helper() -> None:
    idle_state = AppState(
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.STOPPED,
        game_process_running=False,
    )
    assert SessionActivityGuard.is_safe(idle_state, update_busy=False) is True
    assert SessionActivityGuard.evaluate(idle_state, update_busy=False) == UpdateApplySafety(
        safe=True, blocker=None
    )

    busy_state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_status=GameStatus.STOPPED,
        game_process_running=False,
    )
    assert SessionActivityGuard.is_safe(busy_state, update_busy=False) is False
    assert SessionActivityGuard.evaluate(busy_state, update_busy=False) == UpdateApplySafety(
        safe=False, blocker=UpdateApplyBlocker.PROXY_ACTIVE
    )


def test_keyword_only_argument_enforced() -> None:
    state = AppState()
    with pytest.raises(TypeError):
        evaluate_update_apply_safety(state, True)  # type: ignore[misc]


def test_pure_policy_does_not_mutate_state() -> None:
    state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_status=GameStatus.RUNNING,
        game_process_running=True,
    )
    copy_state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_status=GameStatus.RUNNING,
        game_process_running=True,
    )
    evaluate_update_apply_safety(state, update_busy=False)
    assert state == copy_state


def test_module_has_no_tkinter_or_ui_imports() -> None:
    import neko_launcher.application.software_update_activity as mod

    source_file = mod.__file__
    assert source_file is not None
    with open(source_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "tkinter" not in content
    assert "customtkinter" not in content
    assert "neko_launcher.ui" not in content
    assert "neko_launcher.infrastructure" not in content
    assert "subprocess" not in content
    assert "os.kill" not in content

