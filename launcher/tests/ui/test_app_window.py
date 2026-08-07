from dataclasses import replace
from pathlib import Path
from typing import Any

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


class FakeBanner(FakeLabel):
    def __init__(self) -> None:
        super().__init__()
        self.pack_options: dict[str, Any] = {}
        self.pack_forget_calls = 0

    def pack(self, **kwargs: Any) -> None:
        self.pack_options = kwargs

    def pack_forget(self) -> None:
        self.pack_forget_calls += 1


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








class FakeView:
    def __init__(self, manager: str = "") -> None:
        self.manager = manager
        self.frame = self
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


class FakeAuthView:
    def __init__(self) -> None:
        self.login_button_state = ""
        self.register_button_state = ""
        self.status_signed_in = False
    
    def set_actions_enabled(self, *, signed_in: bool, authenticating: bool) -> None:
        state = "normal" if not signed_in and not authenticating else "disabled"
        self.login_button_state = state
        self.register_button_state = state
        
    def set_status_signed_in(self, signed_in: bool) -> None:
        self.status_signed_in = signed_in


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
    window._auth_view = FakeAuthView()  # type: ignore[assignment]

    window._set_auth_enabled(signed_in=False, authenticating=True)

    assert window._auth_view.login_button_state == "disabled"
    assert window._auth_view.register_button_state == "disabled"


def test_error_notification_shows_toast(monkeypatch: Any) -> None:
    window = object.__new__(AppWindow)
    window._header_message = FakeLabel()  # type: ignore[assignment]
    window._notice = FakeVariable()  # type: ignore[assignment]
    window._error = FakeVariable(
        "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง กรุณาตรวจสอบแล้วลองใหม่"
    )  # type: ignore[assignment]

    toast_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        window,
        "_show_toast",
        lambda msg, is_error: toast_calls.append((msg, is_error)),
    )

    window._update_message_visibility()

    expected_msg = f"{window._error.get()[:47]}…"
    assert toast_calls == [(expected_msg, True)]
    assert window._header_message.options == {  # type: ignore[attr-defined]
        "text": "High Performance & Low Latency",
        "text_color": PALETTE.text_muted,
    }


def test_empty_notification_restores_default_header_subtitle(monkeypatch: Any) -> None:
    window = object.__new__(AppWindow)
    window._header_message = FakeLabel()  # type: ignore[assignment]
    window._notice = FakeVariable()  # type: ignore[assignment]
    window._error = FakeVariable()  # type: ignore[assignment]

    hidden: list[bool] = []
    monkeypatch.setattr(window, "_hide_toast", lambda: hidden.append(True))

    window._update_message_visibility()

    assert hidden == [True]
    assert window._header_message.options == {  # type: ignore[attr-defined]
        "text": "High Performance & Low Latency",
        "text_color": PALETTE.text_muted,
    }





def test_close_stops_worker_and_quits_before_destroying_the_window() -> None:
    window = object.__new__(AppWindow)
    window._closing = False
    window._service = FakeShutdownService()  # type: ignore[assignment]
    window._executor = FakeExecutor()  # type: ignore[assignment]
    window._tray_manager = None
    window.root = FakeRoot()  # type: ignore[assignment]

    window.close()

    assert window._service.calls == 1  # type: ignore[attr-defined]
    assert window._executor.options == {  # type: ignore[attr-defined]
        "wait": False,
        "cancel_futures": True,
    }
    assert window.root.quit_called  # type: ignore[attr-defined]
    assert window.root.destroyed  # type: ignore[attr-defined]





def test_show_program_view_packs_scrollable_frame_with_internal_manager() -> None:
    window = object.__new__(AppWindow)
    window._auth_view = FakeView()  # type: ignore[assignment]
    window._dashboard_view = FakeView(manager="grid")  # type: ignore[assignment]

    window._show_program_view()

    assert window._auth_view.pack_forget_calls == 1
    assert window._dashboard_view.pack_calls == [
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


def test_debug_window_retry_submits_to_executor(tmp_path: Path) -> None:
    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._debug_retry_pending = False
    
    # Mock submit
    submitted_tasks = []
    def fake_submit(task: Any, callback: Any = None) -> None:
        submitted_tasks.append(task)
    
    window._submit = fake_submit  # type: ignore[method-assign]
    
    window._retry_proxy_core_debug()
    
    assert len(submitted_tasks) == 1
    assert window._debug_retry_pending is True
    
    # Duplicate should not queue again
    window._retry_proxy_core_debug()
    assert len(submitted_tasks) == 1

def test_debug_window_hex_format(tmp_path: Path) -> None:
    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    from neko_launcher.application.diagnostics import CoreDiagnosticsSnapshot
    
    snapshot = CoreDiagnosticsSnapshot(
        attempt_id="TEST",
        stage="STAGE",
        process_event=None,
        core_path="core.exe",
        pid=123,
        runtime=1.0,
        exit_code=-1073741819, # 0xC0000005
        winerror=None,
        last_diagnostic=None
    )
    
    content = window._format_debug_snapshot(snapshot)
    assert "Hex: 0xC0000005" in content
    
    snapshot_zero = CoreDiagnosticsSnapshot(
        attempt_id="TEST",
        stage="STAGE",
        process_event=None,
        core_path="core.exe",
        pid=123,
        runtime=1.0,
        exit_code=0,
        winerror=None,
        last_diagnostic=None
    )
    content_zero = window._format_debug_snapshot(snapshot_zero)
    assert "Hex: 0x00000000" in content_zero
