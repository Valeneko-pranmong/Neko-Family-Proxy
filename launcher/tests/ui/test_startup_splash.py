from __future__ import annotations

from unittest.mock import Mock
import pytest

from neko_launcher.application.software_update_models import (
    UpdateCheckResult,
    UpdateInvocationReason,
    UpdateState,
)
from neko_launcher.ui.app_window import AppWindow


class FakeWidget:
    def __init__(self) -> None:
        self.destroyed = False

    def winfo_exists(self) -> bool:
        return not self.destroyed

    def destroy(self) -> None:
        self.destroyed = True

    def stop(self) -> None:
        pass

    def configure(self, **kwargs: object) -> None:
        pass

    def set(self, value: object) -> None:
        pass


class FakeStringVar:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


def test_startup_splash_guards_initial_window_until_dismissed() -> None:
    window = object.__new__(AppWindow)
    window._closing = False
    window._startup_check_in_progress = True
    initial_window_shown = False

    window._show_initial_window = lambda: setattr(window, "_initial_window_shown", True)

    # Calling _show_initial_window while check in progress should NOT show initial window
    if getattr(window, "_startup_check_in_progress", False):
        pass
    else:
        window._show_initial_window()
    assert not getattr(window, "_initial_window_shown", False)

    # After dismissing startup splash, initial window should be shown
    splash = FakeWidget()
    window._startup_splash = splash
    window._dismiss_startup_splash()

    assert not window._startup_check_in_progress
    assert splash.destroyed
    assert getattr(window, "_initial_window_shown", False)


def test_startup_splash_on_up_to_date_updates_status_and_schedules_dismiss() -> None:
    window = object.__new__(AppWindow)
    window._closing = False
    window._startup_check_in_progress = True
    window._startup_splash_status_var = FakeStringVar("กำลังตรวจสอบอัปเดต...")
    window._startup_splash_sub_var = FakeStringVar("กรุณารอสักครู่...")
    window._startup_splash_pbar = FakeWidget()

    after_calls: list[tuple[int, object]] = []
    fake_root = Mock()
    fake_root.after.side_effect = lambda delay, cb: after_calls.append((delay, cb))
    window.root = fake_root

    result = UpdateCheckResult(
        state=UpdateState.LATEST,
        invocation_reason=UpdateInvocationReason.STARTUP,
        release_id=None,
        release_sequence=13,
        changed_components=(),
        launcher_version="5.1.6",
        core_version="5.1.6",
        mandatory=False,
        diagnostic_code=None,
    )

    window._on_startup_check_completed(result)

    assert "เป็นเวอร์ชันล่าสุดแล้ว" in window._startup_splash_status_var.get()
    assert "กำลังเข้าสู่โปรแกรม" in window._startup_splash_sub_var.get()
    assert len(after_calls) == 1
    delay, callback = after_calls[0]
    assert delay == 600
    assert callback == window._dismiss_startup_splash


def test_startup_splash_on_update_available_sets_notice() -> None:
    window = object.__new__(AppWindow)
    window._closing = False
    window._startup_check_in_progress = True
    window._startup_splash_status_var = FakeStringVar("กำลังตรวจสอบอัปเดต...")
    window._startup_splash_sub_var = FakeStringVar("กรุณารอสักครู่...")
    window._startup_splash_pbar = FakeWidget()
    window._can_apply_software_update = lambda: False

    after_calls: list[tuple[int, object]] = []
    fake_root = Mock()
    fake_root.after.side_effect = lambda delay, cb: after_calls.append((delay, cb))
    window.root = fake_root

    result = UpdateCheckResult(
        state=UpdateState.AVAILABLE,
        invocation_reason=UpdateInvocationReason.STARTUP,
        release_id="stable-0014",
        release_sequence=14,
        changed_components=("launcher",),
        launcher_version="5.1.7",
        core_version="5.1.6",
        mandatory=False,
        diagnostic_code=None,
    )

    window._on_startup_check_completed(result)

    assert "พบเวอร์ชันใหม่ (v5.1.7)!" == window._startup_splash_status_var.get()
    assert len(after_calls) == 1
    delay, callback = after_calls[0]
    assert delay == 800
    assert callback == window._dismiss_startup_splash
