from dataclasses import replace
from pathlib import Path
from typing import Any

import customtkinter as ctk

from neko_launcher.domain.models import (
    AppState,
    AuthStatus,
    Entitlement,
    EntitlementStatus,
    GameStatus,
    ProxyStatus,
)
from neko_launcher.ui.app_window import AppWindow
from neko_launcher.domain.events import GameProcessStateChanged
from neko_launcher.ui.theme import PALETTE


class FakeVariable:
    def __init__(self, value: Any = "") -> None:
        self.value = value

    def get(self) -> Any:
        return self.value

    def set(self, value: Any) -> None:
        self.value = value


class FakeButton:
    def __init__(self) -> None:
        self.state = ""

    def configure(self, *, state: str) -> None:
        self.state = state


class FakeLabel:
    def __init__(self) -> None:
        self.options: dict[str, Any] = {}

    def configure(self, **kwargs: Any) -> None:
        self.options.update(kwargs)


class FakeShutdownService:
    def __init__(self) -> None:
        self.calls = 0

    def shutdown(self) -> None:
        self.calls += 1


class FakeExecutor:
    def __init__(self) -> None:
        self.options: dict[str, Any] = {}

    def shutdown(self, **kwargs: Any) -> None:
        self.options.update(kwargs)


class FakeRoot:
    def __init__(self) -> None:
        self.destroyed = False
        self.quit_called = False

    def quit(self) -> None:
        self.quit_called = True

    def destroy(self) -> None:
        self.destroyed = True


class FakeSizingRoot:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.minimum: tuple[int, int] | None = None
        self.maximum: tuple[int, int] | None = None

    def update_idletasks(self) -> None:
        self.events.append("update_idletasks")

    def winfo_screenwidth(self) -> int:
        return 1920

    def winfo_screenheight(self) -> int:
        return 1080

    def winfo_exists(self) -> bool:
        return True

    def minsize(self, width: int, height: int) -> None:
        self.minimum = (width, height)
        self.events.append(f"minsize:{width}x{height}")

    def maxsize(self, width: int, height: int) -> None:
        self.maximum = (width, height)
        self.events.append(f"maxsize:{width}x{height}")

    def geometry(self, value: str) -> None:
        self.events.append(f"geometry:{value}")


class FakeView:
    def __init__(self, manager: str = "") -> None:
        self.manager = manager
        self.pack_calls: list[dict[str, Any]] = []
        self.pack_forget_calls = 0

    def winfo_manager(self) -> str:
        return self.manager

    def pack(self, **kwargs: Any) -> None:
        self.pack_calls.append(kwargs)

    def pack_forget(self) -> None:
        self.pack_forget_calls += 1


class FakeDialog:
    def __init__(self) -> None:
        self.released = False
        self.destroyed = False

    def winfo_exists(self) -> bool:
        return True

    def grab_release(self) -> None:
        self.released = True

    def destroy(self) -> None:
        self.destroyed = True


class FakeService:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.proxy_started = 0
        self.tweaker_started = 0
    def launch_tweaker(self, executable: str) -> None:
        self.started.append(executable)
        self.tweaker_started += 1

    def start_proxy(self) -> None:
        self.proxy_started += 1


class FakeController:
    def __init__(self, state: AppState) -> None:
        self.state = state

    def dispatch(self, event: object) -> None:
        if isinstance(event, GameProcessStateChanged):
            self.state = replace(self.state, game_process_running=event.running)


def build_password_window() -> AppWindow:
    window = object.__new__(AppWindow)
    window._new_password = FakeVariable("new-password")  # type: ignore[assignment]
    window._new_password_confirm = FakeVariable("new-password")  # type: ignore[assignment]
    window._error = FakeVariable()  # type: ignore[assignment]
    window._notice = FakeVariable()  # type: ignore[assignment]
    window._password_dialog = None
    return window


def test_change_password_confirmation_must_match_before_submit() -> None:
    window = build_password_window()
    window._new_password_confirm.set("different")
    submitted: list[Any] = []
    window._submit = lambda *args: submitted.append(args)  # type: ignore[method-assign]

    window._change_password()

    assert submitted == []
    assert "ไม่ตรงกัน" in window._error.get()


def test_successful_password_change_clears_both_password_fields() -> None:
    window = build_password_window()
    dialog = FakeDialog()
    window._password_dialog = dialog  # type: ignore[assignment]

    window._password_changed(None)

    assert window._new_password.get() == ""
    assert window._new_password_confirm.get() == ""
    assert window._notice.get() == "เปลี่ยนรหัสผ่านสำเร็จ"
    assert window._password_dialog is None
    assert dialog.released
    assert dialog.destroyed


def test_auth_controls_update_without_removed_reset_password_button() -> None:
    window = object.__new__(AppWindow)
    window._login_button = FakeButton()  # type: ignore[assignment]
    window._register_button = FakeButton()  # type: ignore[assignment]

    window._set_auth_enabled(signed_in=False, authenticating=True)

    assert window._login_button.state == "disabled"
    assert window._register_button.state == "disabled"


def test_notification_reuses_header_subtitle_without_changing_layout() -> None:
    window = object.__new__(AppWindow)
    window._header_message = FakeLabel()  # type: ignore[assignment]
    window._notice = FakeVariable("บันทึกไฟล์เปิดเกมแล้ว")  # type: ignore[assignment]
    window._error = FakeVariable()  # type: ignore[assignment]

    window._update_message_visibility()

    assert window._header_message.options == {  # type: ignore[attr-defined]
        "text": "บันทึกไฟล์เปิดเกมแล้ว",
        "text_color": PALETTE.success,
    }


def test_close_stops_worker_and_quits_before_destroying_the_window() -> None:
    window = object.__new__(AppWindow)
    window._closing = False
    window._service = FakeShutdownService()  # type: ignore[assignment]
    window._executor = FakeExecutor()  # type: ignore[assignment]
    window.root = FakeRoot()  # type: ignore[assignment]

    window.close()

    assert window._service.calls == 1  # type: ignore[attr-defined]
    assert window._executor.options == {  # type: ignore[attr-defined]
        "wait": False,
        "cancel_futures": True,
    }
    assert window.root.quit_called  # type: ignore[attr-defined]
    assert window.root.destroyed  # type: ignore[attr-defined]


def test_fit_portrait_window_locks_native_size_before_rounded_region(
    monkeypatch: Any,
) -> None:
    window = object.__new__(AppWindow)
    window.root = FakeSizingRoot()  # type: ignore[assignment]
    widget_scales: list[float] = []
    monkeypatch.setattr(
        ctk.ScalingTracker,
        "get_window_scaling",
        staticmethod(lambda _root: 1.0),
    )
    monkeypatch.setattr(ctk, "set_widget_scaling", widget_scales.append)

    window._fit_portrait_window()

    assert window._window_size == (480, 760)
    assert window.root.minimum == (480, 760)  # type: ignore[attr-defined]
    assert window.root.maximum == (480, 760)  # type: ignore[attr-defined]
    assert widget_scales == [1.0]
    assert window.root.events[-3:] == [  # type: ignore[attr-defined]
        "minsize:480x760",
        "maxsize:480x760",
        "geometry:480x760+720+160",
    ]


def test_center_window_flushes_geometry_before_applying_rounded_region(
    monkeypatch: Any,
) -> None:
    window = object.__new__(AppWindow)
    window.root = FakeSizingRoot()  # type: ignore[assignment]
    window._window_size = (480, 760)
    monkeypatch.setattr(
        AppWindow,
        "_apply_rounded_window_shape",
        staticmethod(lambda root: root.events.append("rounded_region")),
    )

    window._center_window()

    assert window.root.events == [  # type: ignore[attr-defined]
        "geometry:480x760+720+160",
        "update_idletasks",
        "rounded_region",
    ]


def test_show_program_view_packs_scrollable_frame_with_internal_manager() -> None:
    window = object.__new__(AppWindow)
    window._auth_view = FakeView()  # type: ignore[assignment]
    window._program_view = FakeView(manager="grid")  # type: ignore[assignment]

    window._show_program_view()

    assert window._auth_view.pack_forget_calls == 1
    assert window._program_view.pack_calls == [
        {"fill": "both", "expand": True, "padx": 8, "pady": (2, 6)}
    ]


def build_tweaker_window(tweaker: Path, *, auto_launch: bool = True) -> AppWindow:
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("product", EntitlementStatus.ACTIVE),
        session_id="session-id",
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.STOPPED,
    )
    window = object.__new__(AppWindow)
    window._controller = FakeController(state)  # type: ignore[assignment]
    window._service = FakeService()  # type: ignore[assignment]
    window._game_path = FakeVariable(str(tweaker))  # type: ignore[assignment]
    window._game_path_store = None
    window._auto_launch = FakeVariable(auto_launch)  # type: ignore[assignment]
    window._error = FakeVariable()  # type: ignore[assignment]
    window._notice = FakeVariable()  # type: ignore[assignment]
    window._login_password = FakeVariable("password")  # type: ignore[assignment]
    return window


def test_open_starts_tweaker_without_proxy(tmp_path: Path) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._launch_game()

    assert window._service.started == [str(tweaker.resolve())]  # type: ignore[attr-defined]
    assert window._service.tweaker_started == 1  # type: ignore[attr-defined]
    assert window._service.proxy_started == 0  # type: ignore[attr-defined]


def test_detected_pso2_starts_proxy_only_when_entitlement_is_valid(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._on_game_detected(True)

    assert window._service.proxy_started == 1  # type: ignore[attr-defined]
    assert window._controller.state.game_process_running is True  # type: ignore[attr-defined]


def test_detected_pso2_does_not_start_proxy_when_entitlement_is_missing(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._controller.state = AppState(  # type: ignore[assignment]
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=None,
        session_id=None,
    )

    window._on_game_detected(True)

    assert window._service.proxy_started == 0  # type: ignore[attr-defined]


def test_successful_login_auto_launches_checked_tweaker(tmp_path: Path) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._login_succeeded(None)

    assert window._login_password.get() == ""
    assert window._service.started == [str(tweaker.resolve())]  # type: ignore[attr-defined]


def test_successful_login_does_not_launch_when_checkbox_is_off(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker, auto_launch=False)

    window._login_succeeded(None)

    assert window._service.started == []  # type: ignore[attr-defined]


def test_missing_tweaker_is_reported_before_starting_proxy(tmp_path: Path) -> None:
    window = build_tweaker_window(tmp_path / "missing" / "Tweaker.exe")

    window._launch_game()

    assert window._service.started == []  # type: ignore[attr-defined]
    assert "ไม่พบไฟล์ Tweaker.exe" in window._error.get()
