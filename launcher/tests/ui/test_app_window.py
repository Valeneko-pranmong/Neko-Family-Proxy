from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from neko_launcher.domain.models import (
    AppState,
    AuthStatus,
    Entitlement,
    EntitlementStatus,
    GameStatus,
    ProxyStatus,
)
from neko_launcher.infrastructure.process.process_detector import (
    ProcessObservationUnavailable,
    TargetProcess,
)
from neko_launcher.ui.app_window import AppWindow, HEARTBEAT_INTERVAL_MS


@pytest.fixture(autouse=True)
def exact_pso2_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "neko_launcher.ui.app_window.observe_exact_pso2",
        lambda: TargetProcess(42, "pso2.exe", 100),
    )
    monkeypatch.setattr(
        "neko_launcher.ui.app_window.is_same_target_still_running",
        lambda target: target == TargetProcess(42, "pso2.exe", 100),
    )
from neko_launcher.domain.events import GameProcessStateChanged
from neko_launcher.application.reconnect import (
    AutomaticProxyReconnectController,
    ReconnectCompletion,
)
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

    def show_code_entry(self) -> None:
        self.manager = "recovery_code_entry"


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
        self.proxy_stopped = 0
        self.tweaker_started = 0
        self.sign_ins: list[tuple[str, str]] = []
        self.sign_outs = 0

    def stop_proxy(self) -> None:
        self.proxy_stopped += 1

    def sign_in(self, username: str, password: str) -> None:
        self.sign_ins.append((username, password))

    def launch_tweaker(self, executable: str) -> None:
        self.started.append(executable)
        self.tweaker_started += 1

    def start_proxy(self, **_kwargs: Any) -> None:
        self.proxy_started += 1

    def sign_out(self) -> None:
        self.sign_outs += 1


class FakeRecoveryService:
    def __init__(self) -> None:
        self.cancelled = 0

    def cancel_account_recovery(self) -> None:
        self.cancelled += 1


class FakeDiagnostics:
    def __init__(self) -> None:
        self.stages: list[tuple[str, dict[str, Any]]] = []

    def record_stage(self, stage: str, **details: Any) -> None:
        self.stages.append((stage, details))


class FakeController:
    def __init__(self, state: AppState) -> None:
        self.state = state

    def dispatch(self, event: object) -> None:
        if isinstance(event, GameProcessStateChanged):
            new_proxy_status = (
                ProxyStatus.STOPPED
                if not event.running
                and self.state.proxy_status
                in {
                    ProxyStatus.STARTING,
                    ProxyStatus.RECONNECTING,
                    ProxyStatus.RUNNING,
                }
                else self.state.proxy_status
            )
            self.state = replace(
                self.state,
                game_process_running=event.running,
                proxy_status=new_proxy_status,
            )

    def mark_proxy_reconnecting(self) -> None:
        self.state = replace(self.state, proxy_status=ProxyStatus.RECONNECTING)

    def suppress_proxy_reconnect(self) -> None:
        self.state = replace(self.state, proxy_reconnect_suppressed=True)

    def mark_proxy_reconnect_failed(self, message: str) -> None:
        self.state = replace(
            self.state,
            proxy_status=ProxyStatus.FAILED,
            proxy_start_retry_safe=False,
            last_error=message,
        )


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


def test_signed_out_closes_password_and_advanced_diagnostics_dialogs() -> None:
    window = object.__new__(AppWindow)
    window._coupon_code = FakeVariable("coupon")  # type: ignore[assignment]
    window._notice = FakeVariable()  # type: ignore[assignment]
    closed = {"password": 0, "debug": 0}
    window._close_password_dialog = (  # type: ignore[method-assign]
        lambda: closed.__setitem__("password", closed["password"] + 1)
    )
    window._close_debug_dialog = (  # type: ignore[method-assign]
        lambda: closed.__setitem__("debug", closed["debug"] + 1)
    )

    window._signed_out(None)

    assert closed == {"password": 1, "debug": 1}
    assert window._coupon_code.get() == ""


def test_signed_out_state_transition_closes_advanced_diagnostics_dialog() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "app_window.py"
    ).read_text(encoding="utf-8")
    auth_transition_cleanup = source.split("recovery = state.auth_status in {")[1].split(
        "if signed_in:"
    )[0]

    assert "if not signed_in:" in auth_transition_cleanup
    assert "self._close_password_dialog()" in auth_transition_cleanup
    assert "self._close_debug_dialog()" in auth_transition_cleanup
    assert "self._settings_window.destroy()" in auth_transition_cleanup


def test_auth_controls_update_without_removed_reset_password_button() -> None:
    window = object.__new__(AppWindow)
    window._auth_view = FakeAuthView()  # type: ignore[assignment]

    window._set_auth_enabled(signed_in=False, authenticating=True)

    assert window._auth_view.login_button_state == "disabled"
    assert window._auth_view.register_button_state == "disabled"


def test_recovery_link_wording_is_visible_from_login_source() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "views"
        / "auth_view.py"
    ).read_text(encoding="utf-8")
    assert "ลืมรหัสผ่าน? ใช้รหัสกู้บัญชี" in source


def test_back_to_login_clears_recovery_fields_and_cancels_flow() -> None:
    window = object.__new__(AppWindow)
    window._service = FakeRecoveryService()  # type: ignore[assignment]
    window._recovery_username = FakeVariable("testuser")  # type: ignore[assignment]
    window._recovery_code = FakeVariable("sensitive")  # type: ignore[assignment]
    window._recovery_password = FakeVariable("password")  # type: ignore[assignment]
    window._recovery_password_confirm = FakeVariable("password")  # type: ignore[assignment]

    window._cancel_account_recovery()

    assert window._service.cancelled == 1  # type: ignore[attr-defined]
    assert window._recovery_username.get() == ""
    assert window._recovery_code.get() == ""
    assert window._recovery_password.get() == ""
    assert window._recovery_password_confirm.get() == ""


def test_show_recovery_code_entry_clears_hidden_password_fields() -> None:
    window = object.__new__(AppWindow)
    window._recovery_password = FakeVariable("sensitive")  # type: ignore[assignment]
    window._recovery_password_confirm = FakeVariable("sensitive")  # type: ignore[assignment]
    window._recovery_view = FakeView()  # type: ignore[assignment]

    window._show_recovery_code_entry()

    assert window._recovery_password.get() == ""
    assert window._recovery_password_confirm.get() == ""
    assert window._recovery_view.manager == "recovery_code_entry"


def test_error_notification_shows_complete_actionable_toast(monkeypatch: Any) -> None:
    window = object.__new__(AppWindow)
    window._header_message = FakeLabel()  # type: ignore[assignment]
    window._notice = FakeVariable()  # type: ignore[assignment]
    window._error = FakeVariable(
        "เซสชันนี้ถูกแทนที่ด้วยการเข้าสู่ระบบจากเครื่องอื่น "
        "กรุณาเข้าสู่ระบบอีกครั้ง"
    )  # type: ignore[assignment]

    toast_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        window,
        "_show_toast",
        lambda msg, is_error: toast_calls.append((msg, is_error)),
    )

    window._update_message_visibility()

    assert toast_calls == [(window._error.get(), True)]
    assert window._header_message.options == {  # type: ignore[attr-defined]
        "text": "High Performance & Low Latency",
        "text_color": PALETTE.text_muted,
    }


def test_copy_debug_uses_existing_toast_authority(monkeypatch: Any) -> None:
    window = object.__new__(AppWindow)
    snapshot = object()
    window._diagnostics = type(
        "Diagnostics", (), {"snapshot": lambda _self: snapshot}
    )()
    window.root = type(
        "Root",
        (),
        {
            "clipboard_clear": lambda _self: None,
            "clipboard_append": lambda _self, _text: None,
        },
    )()
    monkeypatch.setattr(window, "_format_debug_snapshot", lambda _value: "safe")
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        window,
        "_show_toast",
        lambda message, is_error: calls.append((message, is_error)),
    )

    window._copy_debug_to_clipboard()

    assert calls == [("Copied to clipboard!", False)]


def test_open_debug_logs_creates_missing_dir_then_opens(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    window = object.__new__(AppWindow)
    window._debug_log_dir = tmp_path / "NekoFamilyProxy" / "logs"
    opened: list[Path] = []

    def fake_startfile(path: object) -> None:
        opened.append(Path(str(path)))  # type: ignore[arg-type]

    monkeypatch.setattr("neko_launcher.ui.app_window.os.startfile", fake_startfile)
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        window,
        "_show_toast",
        lambda message, is_error: calls.append((message, is_error)),
    )

    window._open_debug_logs()

    assert window._debug_log_dir.is_dir()
    assert opened == [window._debug_log_dir]
    assert calls == [("เปิดโฟลเดอร์ Logs แล้ว", False)]


def test_open_debug_logs_reports_failure_when_dir_cannot_be_created(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    window = object.__new__(AppWindow)
    blocker = tmp_path / "blocked"
    blocker.write_text("regular file, not a directory", encoding="utf-8")
    window._debug_log_dir = blocker / "logs"
    started: list[Path] = []

    def record_startfile(path: object) -> None:
        started.append(Path(str(path)))  # type: ignore[arg-type]

    monkeypatch.setattr(
        "neko_launcher.ui.app_window.os.startfile", record_startfile
    )
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        window,
        "_show_toast",
        lambda message, is_error: calls.append((message, is_error)),
    )

    window._open_debug_logs()

    assert not window._debug_log_dir.exists()
    assert started == []
    assert len(calls) == 1
    message, is_error = calls[0]
    assert is_error is True
    assert message.startswith("เปิดโฟลเดอร์ Logs ไม่สำเร็จ:")


def test_open_debug_logs_failure_uses_existing_error_toast(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    window = object.__new__(AppWindow)
    window._debug_log_dir = tmp_path / "existing-logs"
    window._debug_log_dir.mkdir(parents=True)
    calls: list[tuple[str, bool]] = []

    def fail_to_open(_path: Path) -> None:
        raise OSError

    monkeypatch.setattr("neko_launcher.ui.app_window.os.startfile", fail_to_open)
    monkeypatch.setattr(
        window,
        "_show_toast",
        lambda message, is_error: calls.append((message, is_error)),
    )

    window._open_debug_logs()

    assert len(calls) == 1
    message, is_error = calls[0]
    assert is_error is True
    assert message.startswith("เปิดโฟลเดอร์ Logs ไม่สำเร็จ:")


def test_session_heartbeat_polling_interval_is_bounded_to_thirty_seconds() -> None:
    assert HEARTBEAT_INTERVAL_MS == 30_000


def test_login_clears_password_before_background_authentication_finishes() -> None:
    window = object.__new__(AppWindow)
    window._service = FakeService()  # type: ignore[assignment]
    window._login_email = FakeVariable("testuser")  # type: ignore[assignment]
    window._login_password = FakeVariable("password123")  # type: ignore[assignment]
    submitted: list[tuple[Any, Any]] = []
    window._submit = (  # type: ignore[method-assign]
        lambda work, on_success=None: submitted.append((work, on_success))
    )

    window._login()

    assert window._login_password.get() == ""
    assert len(submitted) == 1
    submitted[0][0]()
    assert window._service.sign_ins == [("testuser", "password123")]  # type: ignore[attr-defined]


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
    from unittest.mock import Mock
    window = object.__new__(AppWindow)
    window.root = Mock()
    window.root.resizable = Mock()
    window.root.minsize = Mock()
    window.root.maxsize = Mock()
    window.root.geometry = Mock()
    window.root.winfo_screenwidth = Mock(return_value=1920)
    window.root.winfo_screenheight = Mock(return_value=1080)
    window._auth_view = FakeView()  # type: ignore[assignment]
    window._dashboard_view = FakeView(manager="grid")  # type: ignore[assignment]
    window._settings_button = Mock()

    window._show_program_view()

    assert window._auth_view.pack_forget_calls == 1
    assert window._dashboard_view.pack_calls == [
        {"fill": "both", "expand": True, "padx": 6, "pady": (2, 4)}
    ]
    window._settings_button.pack.assert_called_with(side="left")
    window.root.resizable.assert_called_with(True, True)

def test_show_auth_view_compacts_window(monkeypatch: Any) -> None:
    from unittest.mock import Mock
    window = object.__new__(AppWindow)
    window.root = Mock()
    window.root.resizable = Mock()
    window.root.winfo_screenwidth = Mock(return_value=1920)
    window.root.winfo_screenheight = Mock(return_value=1080)
    window.root.geometry = Mock()
    window._auth_view = FakeView()  # type: ignore[assignment]
    window._dashboard_view = FakeView()  # type: ignore[assignment]
    window._settings_button = Mock()
    monkeypatch.setattr(
        "neko_launcher.ui.app_window.fit_portrait_window",
        lambda _root: (440, 592),
    )

    window._show_auth_view()

    assert window._dashboard_view.pack_forget_calls == 1
    window._settings_button.pack_forget.assert_called_once()
    window.root.resizable.assert_called_with(False, False)
    assert window._window_size == (440, 592)


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
    window._bound_target = None
    window._proxy_start_attempted_for_detected_game = False
    window._proxy_retry_suppression_logged = False
    window._startup_recovery_in_progress = False
    window._startup_route_pending = False
    window._startup_route_completed = False
    window._startup_routed_session_id = None
    window._startup_route_generation = 0
    window._startup_process_probe = lambda: False
    window._reconnect_controller = AutomaticProxyReconnectController(
        backoff_seconds=(1.0, 2.0, 4.0)
    )
    window._runtime_was_healthy = False
    window._scheduled_reconnects = []
    window._schedule_reconnect = (  # type: ignore[method-assign]
        lambda delay, callback: window._scheduled_reconnects.append((delay, callback))
    )
    window._telemetry_speed = FakeVariable()  # type: ignore[assignment]
    window._telemetry_transfer = FakeVariable()  # type: ignore[assignment]
    window._telemetry_session = FakeVariable()  # type: ignore[assignment]
    window._telemetry_health = FakeVariable()  # type: ignore[assignment]
    window._download_speed = FakeVariable()  # type: ignore[assignment]
    window._upload_speed = FakeVariable()  # type: ignore[assignment]
    window._session_duration = FakeVariable()  # type: ignore[assignment]
    window._latency = FakeVariable()  # type: ignore[assignment]
    window._status_title = FakeVariable()  # type: ignore[assignment]
    window._status_subtitle = FakeVariable()  # type: ignore[assignment]
    window._tray_manager = None
    window._closing = False
    window._clear_recovery_sensitive_fields = lambda: None  # type: ignore[method-assign]
    window._submitted_work = []
    window._submitted_callbacks = []

    def submit(work: Any, on_success: Any = None, on_failure: Any = None) -> None:
        window._submitted_work.append(work)  # type: ignore[attr-defined]
        window._submitted_callbacks.append(  # type: ignore[attr-defined]
            (on_success, on_failure)
        )

    window._submit = submit  # type: ignore[method-assign]
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

    assert window._service.proxy_started == 0  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 1  # type: ignore[attr-defined]
    window._submitted_work[0]()  # type: ignore[attr-defined]
    assert window._service.proxy_started == 1  # type: ignore[attr-defined]
    assert window._controller.state.game_process_running is True  # type: ignore[attr-defined]


def test_process_observation_error_preserves_running_game_and_proxy_state(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._on_game_detected(True)
    submitted_before = len(window._submitted_work)  # type: ignore[attr-defined]

    window._on_game_detected(None)

    assert window._controller.state.game_process_running is True
    assert len(window._submitted_work) == submitted_before  # type: ignore[attr-defined]


def test_detected_pso2_attempts_proxy_only_once_until_game_exits(tmp_path: Path) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._on_game_detected(True)
    window._on_game_detected(True)

    assert len(window._submitted_work) == 1  # type: ignore[attr-defined]

    window._on_game_detected(False)
    window._on_game_detected(True)

    assert window._submitted_work == [  # type: ignore[attr-defined]
        window._service.start_proxy,
        window._service.start_proxy,
    ]


def test_repeated_startup_auth_callbacks_do_not_request_duplicate_proxy_start(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        game_process_running=True,
    )

    window._restore_completed(True)
    window._login_succeeded(None)
    window._on_game_detected(True)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 1  # type: ignore[attr-defined]


def test_repeated_auth_callback_while_startup_probe_is_pending_is_single_flight(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._login_succeeded(None)
    window._login_succeeded(None)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 1  # type: ignore[attr-defined]


def test_regular_poll_cannot_steal_pending_startup_recovery_completion(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._login_succeeded(None)
    assert window._startup_route_pending is True

    window._on_game_detected(True)
    assert len(window._submitted_work) == 1  # type: ignore[attr-defined]

    on_probe_success, _ = window._submitted_callbacks[0]  # type: ignore[attr-defined]
    assert on_probe_success is not None
    on_probe_success(True)

    assert len(window._submitted_work) == 2  # type: ignore[attr-defined]
    on_start_success, _ = window._submitted_callbacks[1]  # type: ignore[attr-defined]
    assert on_start_success == window._startup_proxy_start_completed


def test_regular_poll_completes_route_after_transient_startup_observation_failure(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._login_succeeded(None)
    on_probe_success, _ = window._submitted_callbacks[0]  # type: ignore[attr-defined]
    assert on_probe_success is not None
    on_probe_success(None)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert window._startup_route_completed is False

    window._on_game_detected(False)

    assert window._service.tweaker_started == 1  # type: ignore[attr-defined]
    assert window._startup_route_completed is True


def test_regular_poll_recovers_existing_game_after_transient_startup_observation_failure(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._login_succeeded(None)
    on_probe_success, _ = window._submitted_callbacks[0]  # type: ignore[attr-defined]
    assert on_probe_success is not None
    on_probe_success(None)

    window._on_game_detected(True)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert window._notice.get() == "ตรวจพบ PSO2 ที่กำลังทำงาน — กำลังเชื่อมต่อ..."
    assert len(window._submitted_work) == 2  # type: ignore[attr-defined]
    on_start_success, _ = window._submitted_callbacks[1]  # type: ignore[attr-defined]
    assert on_start_success == window._startup_proxy_start_completed


@pytest.mark.parametrize("detected", [False, True])
def test_pre_auth_regular_poll_does_not_consume_post_auth_startup_route(
    tmp_path: Path,
    detected: bool,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._controller.state = AppState()  # type: ignore[assignment]

    window._on_game_detected(detected)

    assert window._startup_route_completed is False
    assert window._startup_recovery_in_progress is False
    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]


def test_superseded_session_ignores_stale_startup_probe_result(tmp_path: Path) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._login_succeeded(None)
    first_success, _ = window._submitted_callbacks[0]  # type: ignore[attr-defined]
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        session_id="replacement-session-id",
    )
    window._login_succeeded(None)
    second_success, _ = window._submitted_callbacks[1]  # type: ignore[attr-defined]
    assert first_success is not None
    assert second_success is not None

    first_success(False)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert window._startup_route_pending is True

    second_success(True)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 3  # type: ignore[attr-defined]


def test_startup_recovery_does_not_compete_with_runtime_reconnect_owner(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        game_process_running=True,
        proxy_status=ProxyStatus.RUNNING,
    )
    window._reconnect_controller.observe_running()
    attempt = window._reconnect_controller.request(
        window._controller.state,
        shutting_down=False,
    )
    assert attempt is not None
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        proxy_status=ProxyStatus.STOPPED,
    )

    window._login_succeeded(None)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 0  # type: ignore[attr-defined]
    assert window._startup_recovery_in_progress is False


def test_safe_pre_permit_failure_retries_while_same_game_remains(tmp_path: Path) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._on_game_detected(True)
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        proxy_status=ProxyStatus.FAILED,
        proxy_start_retry_safe=True,
    )

    window._on_game_detected(True)

    assert len(window._submitted_work) == 2  # type: ignore[attr-defined]


def test_debug_log_records_game_detection_and_suppressed_retry_only_once(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    diagnostics = FakeDiagnostics()
    window._debug_mode = True
    window._diagnostics = diagnostics
    window._last_debug_status = None

    window._on_game_detected(True)
    window._on_game_detected(True)
    window._on_game_detected(True)

    stages = [stage for stage, _ in diagnostics.stages]
    assert stages.count("GAME_PROCESS_DETECTED") == 1
    assert stages.count("PROXY_START_NOT_RETRIED") == 1


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
    assert window._service.started == []  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 1  # type: ignore[attr-defined]
    observed = window._submitted_work[0]()  # type: ignore[attr-defined]
    on_success, _ = window._submitted_callbacks[0]  # type: ignore[attr-defined]
    on_success(observed)
    assert window._service.started == [str(tweaker.resolve())]  # type: ignore[attr-defined]


def test_successful_login_with_existing_pso2_suppresses_tweaker_and_starts_recovery(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._controller.state = AppState()  # type: ignore[assignment]
    window._on_game_detected(True)
    window._controller.state = AppState(  # type: ignore[assignment]
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("product", EntitlementStatus.ACTIVE),
        session_id="session-id",
        game_process_running=True,
    )

    window._login_succeeded(None)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 1  # type: ignore[attr-defined]
    assert window._notice.get() == "ตรวจพบ PSO2 ที่กำลังทำงาน — กำลังเชื่อมต่อ..."


def test_session_restore_with_existing_pso2_suppresses_tweaker_and_starts_recovery(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        game_process_running=True,
    )

    window._restore_completed(True)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 1  # type: ignore[attr-defined]


def test_successful_startup_recovery_reports_connected(tmp_path: Path) -> None:
    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        game_process_running=True,
    )
    window._login_succeeded(None)

    def succeed() -> None:
        window._controller.state = replace(  # type: ignore[assignment]
            window._controller.state,
            proxy_status=ProxyStatus.RUNNING,
        )

    window._submitted_work[0] = succeed  # type: ignore[attr-defined]
    result = window._submitted_work[0]()  # type: ignore[attr-defined]
    on_success, _ = window._submitted_callbacks[0]  # type: ignore[attr-defined]
    assert on_success is not None
    on_success(result)

    assert window._notice.get() == "เชื่อมต่อแล้ว"


def test_new_session_can_retry_startup_recovery_without_tweaker(tmp_path: Path) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        game_process_running=True,
    )

    window._login_succeeded(None)
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        session_id="replacement-session-id",
        proxy_status=ProxyStatus.STOPPED,
    )
    window._login_succeeded(None)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 2  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "state",
    [
        AppState(
            auth_status=AuthStatus.SIGNED_OUT,
            entitlement=Entitlement("product", EntitlementStatus.ACTIVE),
            session_id="session-id",
            game_process_running=True,
        ),
        AppState(
            auth_status=AuthStatus.AUTHENTICATED,
            entitlement=Entitlement("product", EntitlementStatus.ACTIVE),
            session_id=None,
            game_process_running=True,
        ),
        AppState(
            auth_status=AuthStatus.AUTHENTICATED,
            entitlement=Entitlement("product", EntitlementStatus.EXPIRED),
            session_id="session-id",
            game_process_running=True,
        ),
    ],
)
def test_startup_recovery_remains_fail_closed_without_all_authority_gates(
    tmp_path: Path,
    state: AppState,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._controller.state = state  # type: ignore[assignment]

    window._login_succeeded(None)

    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 0  # type: ignore[attr-defined]


def test_authenticated_login_without_entitlement_clears_password(tmp_path: Path) -> None:
    window = build_tweaker_window(tmp_path / "missing" / "Tweaker.exe")
    window._controller.state = AppState(  # type: ignore[assignment]
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=None,
        session_id=None,
    )
    window._login_email = FakeVariable("testuser")  # type: ignore[assignment]
    window._login_password = FakeVariable("password123")  # type: ignore[assignment]

    def submit(work: Any, on_success: Any = None) -> None:
        result = work()
        if on_success is not None:
            on_success(result)

    window._submit = submit  # type: ignore[method-assign]

    window._login()

    assert window._service.sign_ins == [  # type: ignore[attr-defined]
        ("testuser", "password123")
    ]
    assert window._login_password.get() == ""


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


def test_render_telemetry_updates_vars(tmp_path: Path) -> None:
    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    from neko_launcher.domain.telemetry import (
        CoreHealthSnapshot,
        TelemetryConnectionState,
        TelemetryState,
    )

    # Disconnected
    s_disc = TelemetryState(connection_state=TelemetryConnectionState.DISCONNECTED)
    window._render_telemetry(s_disc)
    assert "ไม่พร้อมใช้งาน" in window._telemetry_health.get()

    # Connected healthy
    snapshot = CoreHealthSnapshot(
        core_state="running",
        proxy_state="connected",
        uptime_ms=125000,
        tcp_active=5,
        dns_query_total=42,
        rx_bytes=1048576,
        tx_bytes=524288,
        network_error_total=0,
        v2ray_running=True,
        local_socks_running=True,
        shadowsocks_connected=True,
    )
    s_conn = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=snapshot,
        rx_rate_bps=102400.0,
        tx_rate_bps=51200.0,
        is_stale=False,
    )
    window._render_telemetry(s_conn)
    assert "100.0 KB/s" in window._telemetry_speed.get()
    assert "50.0 KB/s" in window._telemetry_speed.get()
    assert "1.0 MB" in window._telemetry_transfer.get()
    assert "512.0 KB" in window._telemetry_transfer.get()
    assert "00:02:05" in window._telemetry_session.get()
    assert "5 active" in window._telemetry_session.get()
    assert "Core ปกติ" in window._telemetry_health.get()
    assert "V2Ray ทำงาน" in window._telemetry_health.get()
    assert "SOCKS พร้อม" in window._telemetry_health.get()
    assert "Upstream เชื่อมต่อแล้ว" in window._telemetry_health.get()
    assert window._download_speed.get() == "100.0 KB/s"
    assert window._upload_speed.get() == "50.0 KB/s"
    assert window._session_duration.get() == "00:02:05"
    assert window._latency.get() == "—"

    # With proxy_rtt_ms
    s_rtt = replace(
        s_conn,
        snapshot=replace(snapshot, proxy_rtt_ms=45),
    )
    window._render_telemetry(s_rtt)
    assert window._latency.get() == "45 ms"

    truthful_totals = window._telemetry_transfer.get()

    disconnected = replace(
        s_conn, connection_state=TelemetryConnectionState.DISCONNECTED
    )
    window._render_telemetry(disconnected)
    assert window._telemetry_transfer.get() == truthful_totals
    assert window._telemetry_session.get() == "เซสชัน: ไม่พร้อมใช้งาน"
    assert window._download_speed.get() == "—"
    assert window._upload_speed.get() == "—"
    assert window._session_duration.get() == "—"
    assert window._latency.get() == "—"

    stale = replace(s_conn, is_stale=True)
    window._render_telemetry(stale)
    assert window._telemetry_transfer.get() == truthful_totals
    assert window._telemetry_session.get() == "เซสชัน: ไม่พร้อมใช้งาน (ข้อมูลล้าสมัย)"
    assert window._download_speed.get() == "—"
    assert window._upload_speed.get() == "—"
    assert window._session_duration.get() == "—"
    assert window._latency.get() == "—"



def test_running_proxy_transport_disconnect_with_pso2_queues_reconnect(
    tmp_path: Path,
) -> None:
    from neko_launcher.domain.telemetry import (
        CoreHealthSnapshot,
        TelemetryConnectionState,
        TelemetryState,
    )

    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    healthy = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            proxy_state="connected",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
        ),
    )

    window._render_telemetry(healthy)
    submitted_before = len(window._submitted_work)  # type: ignore[attr-defined]
    window._render_telemetry(
        replace(healthy, connection_state=TelemetryConnectionState.DISCONNECTED)
    )

    assert len(window._submitted_work) == submitted_before  # type: ignore[attr-defined]
    assert len(window._scheduled_reconnects) == 1  # type: ignore[attr-defined]
    delay, callback = window._scheduled_reconnects[0]  # type: ignore[attr-defined]
    assert delay == 1.0

    callback()

    assert len(window._submitted_work) == submitted_before + 1  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "changes",
    [
        {"core_state": "stopped"},
        {"proxy_state": "disconnected"},
        {"v2ray_running": False},
        {"local_socks_running": False},
        {"shadowsocks_connected": False},
    ],
)
def test_each_runtime_health_failure_queues_only_one_reconnect(
    tmp_path: Path,
    changes: dict[str, object],
) -> None:
    from neko_launcher.domain.telemetry import (
        CoreHealthSnapshot,
        TelemetryConnectionState,
        TelemetryState,
    )

    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    snapshot = CoreHealthSnapshot(
        core_state="running",
        proxy_state="connected",
        v2ray_running=True,
        local_socks_running=True,
        shadowsocks_connected=True,
    )
    healthy = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=snapshot,
    )
    window._render_telemetry(healthy)
    unhealthy = replace(healthy, snapshot=replace(snapshot, **changes))

    window._render_telemetry(unhealthy)
    window._render_telemetry(unhealthy)

    assert window._controller.state.proxy_status is ProxyStatus.RECONNECTING
    assert len(window._scheduled_reconnects) == 1  # type: ignore[attr-defined]


def test_successful_reconnect_returns_running_and_resets_retry_budget(
    tmp_path: Path,
) -> None:
    from neko_launcher.domain.telemetry import (
        CoreHealthSnapshot,
        TelemetryConnectionState,
        TelemetryState,
    )

    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    healthy = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            proxy_state="connected",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
        ),
    )
    window._render_telemetry(healthy)
    window._render_telemetry(
        replace(healthy, connection_state=TelemetryConnectionState.DISCONNECTED)
    )
    _, scheduled = window._scheduled_reconnects[0]  # type: ignore[attr-defined]
    scheduled()

    def succeed(**_kwargs: Any) -> None:
        window._controller.state = replace(  # type: ignore[assignment]
            window._controller.state,
            proxy_status=ProxyStatus.RUNNING,
            proxy_start_retry_safe=False,
        )

    window._service.start_proxy = succeed  # type: ignore[method-assign]
    result = window._submitted_work[0]()  # type: ignore[attr-defined]
    on_success, _ = window._submitted_callbacks[0]  # type: ignore[attr-defined]
    on_success(result)
    window._render_telemetry(healthy)

    assert window._controller.state.proxy_status is ProxyStatus.RUNNING
    assert window._reconnect_controller.attempts == 0
    assert len(window._scheduled_reconnects) == 1  # type: ignore[attr-defined]
    assert window._status_title.get() == "● เชื่อมต่อแล้ว"


def test_retry_budget_exhaustion_stays_failed_without_rescheduling(
    tmp_path: Path,
) -> None:
    from neko_launcher.domain.telemetry import (
        CoreHealthSnapshot,
        TelemetryConnectionState,
        TelemetryState,
    )

    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._reconnect_controller = AutomaticProxyReconnectController(
        backoff_seconds=(1.0, 2.0)
    )
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    healthy = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            proxy_state="connected",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
        ),
    )
    window._render_telemetry(healthy)
    unhealthy = replace(
        healthy, connection_state=TelemetryConnectionState.DISCONNECTED
    )
    window._render_telemetry(unhealthy)

    def fail_retry_safe(**_kwargs: Any) -> None:
        window._controller.state = replace(  # type: ignore[assignment]
            window._controller.state,
            proxy_status=ProxyStatus.FAILED,
            proxy_start_retry_safe=True,
        )

    window._service.start_proxy = fail_retry_safe  # type: ignore[method-assign]
    for index in range(2):
        _, scheduled = window._scheduled_reconnects[index]  # type: ignore[attr-defined]
        scheduled()
        result = window._submitted_work[index]()  # type: ignore[attr-defined]
        on_success, _ = window._submitted_callbacks[index]  # type: ignore[attr-defined]
        on_success(result)

    window._render_telemetry(unhealthy)

    assert len(window._scheduled_reconnects) == 2  # type: ignore[attr-defined]
    assert window._controller.state.proxy_status is ProxyStatus.FAILED
    assert "ตรวจสอบเครือข่าย" in (window._controller.state.last_error or "")
    assert window._reconnect_controller.attempts == 2


def test_runtime_reconnect_retry_cannot_race_legacy_game_detection_retry(
    tmp_path: Path,
) -> None:
    from neko_launcher.domain.telemetry import (
        CoreHealthSnapshot,
        TelemetryConnectionState,
        TelemetryState,
    )

    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    window._proxy_start_attempted_for_detected_game = True
    healthy = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            proxy_state="connected",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
        ),
    )
    window._render_telemetry(healthy)
    window._render_telemetry(
        replace(healthy, connection_state=TelemetryConnectionState.DISCONNECTED)
    )
    _, scheduled = window._scheduled_reconnects[0]  # type: ignore[attr-defined]
    scheduled()

    def fail_retry_safe(**_kwargs: Any) -> None:
        window._controller.state = replace(  # type: ignore[assignment]
            window._controller.state,
            proxy_status=ProxyStatus.FAILED,
            proxy_start_retry_safe=True,
        )

    window._service.start_proxy = fail_retry_safe  # type: ignore[method-assign]
    result = window._submitted_work[0]()  # type: ignore[attr-defined]

    # Reproduce the UI ordering window before the worker completion callback
    # has scheduled bounded reconnect attempt 2.
    window._on_game_detected(True)

    assert result is ReconnectCompletion.RETRY
    assert len(window._submitted_work) == 1  # type: ignore[attr-defined]


def test_confirmed_logout_cancels_scheduled_reconnect_before_background_work(
    tmp_path: Path,
) -> None:
    from neko_launcher.domain.telemetry import (
        CoreHealthSnapshot,
        TelemetryConnectionState,
        TelemetryState,
    )

    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._controller.state = replace(  # type: ignore[assignment]
        window._controller.state,
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    window._confirm_game_active_action = lambda _action: True  # type: ignore[method-assign]
    healthy = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            proxy_state="connected",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
        ),
    )
    window._render_telemetry(healthy)
    window._render_telemetry(
        replace(healthy, connection_state=TelemetryConnectionState.DISCONNECTED)
    )
    _, reconnect_callback = window._scheduled_reconnects[0]  # type: ignore[attr-defined]

    window._sign_out()
    reconnect_callback()

    assert len(window._submitted_work) == 1  # type: ignore[attr-defined]


def test_close_stops_telemetry_client(tmp_path: Path) -> None:
    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    stopped = False

    class FakeTelemetryClient:
        def stop(self, timeout: float = 0.5) -> None:
            nonlocal stopped
            stopped = True

    window._telemetry_client = FakeTelemetryClient()  # type: ignore[assignment]
    window._service = FakeShutdownService()  # type: ignore[assignment]
    window._executor = FakeExecutor()  # type: ignore[assignment]
    window.root = FakeRoot()  # type: ignore[assignment]

    window.close()
    assert stopped is True


def test_main_window_is_responsive_and_landscape_first(monkeypatch: Any) -> None:
    source = Path(__file__).parents[2].joinpath('src', 'neko_launcher', 'ui', 'app_window.py').read_text(encoding='utf-8')
    assert 'self.root.resizable(True, True)' in source
    assert 'self.root.minsize(480, 580)' in source


# A18_NATIVE_MINIMIZE

def test_a18_native_minimize_respects_hide_to_tray_preference() -> None:
    from types import SimpleNamespace
    from neko_launcher.ui.app_window import AppWindow

    class Root:
        def __init__(self, state: str) -> None:
            self._state = state
        def state(self) -> str:
            return self._state

    class Toggle:
        def __init__(self, value: bool) -> None:
            self.value = value
        def get(self) -> bool:
            return self.value

    for enabled, iconic, closing, programmatic, expected in (
        (False, True, False, False, 0),
        (True, True, False, False, 1),
        (True, False, False, False, 0),
        (True, True, True, False, 0),
        (True, True, False, True, 0),
    ):
        window = AppWindow.__new__(AppWindow)
        window.root = Root("iconic" if iconic else "normal")
        window._hide_to_tray = Toggle(enabled)
        window._closing = closing
        window._programmatic_withdraw = programmatic
        calls: list[str] = []
        window._minimize_window = lambda: calls.append("tray")
        window._on_window_state_changed(SimpleNamespace(widget=window.root))
        assert len(calls) == expected


def test_a18_window_contract_uses_compact_dashboard_and_exact_title() -> None:
    from pathlib import Path
    source = Path(__file__).parents[2].joinpath("src", "neko_launcher", "ui", "app_window.py").read_text(encoding="utf-8")
    assert 'self.root.title("NEKO FAMILY PROXY")' in source
    assert 'self.root.minsize(480, 580)' in source
    assert 'self.root.geometry("500x640")' in source
    assert 'controls.pack(side="right", anchor="ne")' in source
    assert 'controls, "Hide"' not in source


# A21_VIEW_SWITCH_FLICKER

def test_a21_dashboard_geometry_is_compact_and_single_step() -> None:
    source = Path(__file__).parents[2].joinpath(
        "src", "neko_launcher", "ui", "app_window.py"
    ).read_text(encoding="utf-8")
    program = source.split("def _show_program_view")[1].split("# Password dialog")[0]
    assert 'width, height = (500, 640)' in program
    assert 'self.root.minsize(480, 580)' in program
    assert program.count("self.root.geometry(") == 1
    assert "center_window(self.root" not in program
    assert 'getattr(self, "_active_view", None) == "program"' in program


def test_a21_cancel_recovery_immediately_routes_back_when_views_exist() -> None:
    window = object.__new__(AppWindow)
    window._service = FakeRecoveryService()  # type: ignore[assignment]
    window._recovery_username = FakeVariable("tester")  # type: ignore[assignment]
    window._recovery_code = FakeVariable("secret")  # type: ignore[assignment]
    window._recovery_password = FakeVariable("secret")  # type: ignore[assignment]
    window._recovery_password_confirm = FakeVariable("secret")  # type: ignore[assignment]
    window._auth_view = object()
    window._dashboard_view = object()
    called: list[str] = []
    window._show_auth_view = lambda: called.append("auth")  # type: ignore[method-assign]
    window._cancel_account_recovery()
    assert called == ["auth"]
    assert window._active_view is None



def test_a22_set_if_changed_deduplicates_visible_updates() -> None:
    class Var:
        def __init__(self) -> None:
            self.value = "same"
            self.calls = 0
        def get(self) -> str:
            return self.value
        def set(self, value: str) -> None:
            self.calls += 1
            self.value = value
    var = Var()
    AppWindow._set_if_changed(var, "same")
    assert var.calls == 0
    AppWindow._set_if_changed(var, "new")
    assert var.calls == 1
    assert var.value == "new"


# A24_HEADER_CENTERING
def test_a24_header_uses_symmetric_fixed_slots() -> None:
    source = Path(__file__).parents[2].joinpath(
        "src", "neko_launcher", "ui", "app_window.py"
    ).read_text(encoding="utf-8")
    assert 'self._header_left_spacer = ctk.CTkFrame(' in source
    assert 'header, fg_color="transparent", width=32, height=26' in source
    assert 'self._header_left_spacer.pack_propagate(False)' in source
    controls = source.split("def _build_window_controls")[1].split(
        "def _open_settings_window"
    )[0]
    assert 'width=32, height=26' in controls
    assert 'controls.pack_propagate(False)' in controls
    assert 'self._window_controls = controls' in controls


# A25_DASHBOARD_COMPACT
def test_a25_dashboard_is_more_compact() -> None:
    source = Path(__file__).parents[2].joinpath(
        "src", "neko_launcher", "ui", "app_window.py"
    ).read_text(encoding="utf-8")
    program = source.split("def _show_program_view")[1].split("# Password dialog")[0]
    assert 'width, height = (500, 640)' in program
    assert 'self.root.minsize(480, 580)' in program


# A25_REGISTER_CTA
def test_a25_register_cta_is_large_enough() -> None:
    source = Path(__file__).parents[2].joinpath(
        "src", "neko_launcher", "ui", "views", "auth_view.py"
    ).read_text(encoding="utf-8")
    section = source.split('self._register_action = ctk.CTkFrame')[1].split('self._switch_tab("login")')[0]
    assert "height=76" in section
    assert "pack_propagate(False)" in section
    assert "height=56" in section
    assert "size=16" in section
    assert 'side="bottom"' not in section
    assert "corner_radius=12" in section


def test_positive_poll_requires_unconditional_exact_revalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    monkeypatch.setattr(
        "neko_launcher.ui.app_window.observe_exact_pso2",
        lambda: None,
    )

    window._on_game_detected(True)

    assert window._controller.state.game_process_running is False
    assert window._service.proxy_started == 0  # type: ignore[attr-defined]
    assert len(window._submitted_work) == 0


def test_confirmed_absence_clears_state_cancels_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._controller.state = replace(
        window._controller.state,
        game_process_running=True,
        proxy_status=ProxyStatus.RUNNING,
    )
    window._reconnect_controller.observe_running()
    monkeypatch.setattr("neko_launcher.ui.app_window.observe_exact_pso2", lambda: None)

    window._on_game_detected(True)

    assert window._controller.state.game_process_running is False
    assert window._reconnect_controller.owns_recovery is False
    assert len(window._submitted_work) == 0


def test_delayed_reconnect_is_inert_after_confirmed_disappearance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._controller.state = replace(
        window._controller.state,
        game_process_running=True,
        proxy_status=ProxyStatus.RUNNING,
    )
    window._reconnect_controller.observe_running()
    window._observe_runtime_health(SimpleNamespace(is_healthy=False))
    _, delayed_reconnect = window._scheduled_reconnects[0]
    monkeypatch.setattr("neko_launcher.ui.app_window.observe_exact_pso2", lambda: None)
    monkeypatch.setattr(
        "neko_launcher.ui.app_window.is_same_target_still_running",
        lambda _: False,
    )

    window._on_game_detected(True)
    delayed_reconnect()

    assert window._controller.state.game_process_running is False
    assert len(window._submitted_work) == 0
    assert window._service.proxy_started == 0


def test_unhealthy_telemetry_with_stale_game_does_not_reconnect(monkeypatch, tmp_path) -> None:
    from neko_launcher.domain.telemetry import (
        CoreHealthSnapshot, TelemetryConnectionState, TelemetryState
    )

    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._controller.state = replace(
        window._controller.state,
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    healthy = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(
            core_state="running", proxy_state="connected", v2ray_running=True,
            local_socks_running=True, shadowsocks_connected=True,
        )
    )
    window._render_telemetry(healthy)

    monkeypatch.setattr("neko_launcher.ui.app_window.observe_exact_pso2", lambda: None)

    unhealthy = replace(healthy, connection_state=TelemetryConnectionState.DISCONNECTED)
    window._render_telemetry(unhealthy)



    assert window._controller.state.game_process_running is False
    assert len(window._submitted_work) == 0
    assert window._service.proxy_stopped == 0
    assert len(window._scheduled_reconnects) == 0


def test_unhealthy_telemetry_with_unknown_game_preserves_reconnect(monkeypatch, tmp_path) -> None:
    from neko_launcher.domain.telemetry import (
        CoreHealthSnapshot, TelemetryConnectionState, TelemetryState
    )

    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._controller.state = replace(
        window._controller.state,
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    healthy = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(
            core_state="running", proxy_state="connected", v2ray_running=True,
            local_socks_running=True, shadowsocks_connected=True,
        )
    )
    window._render_telemetry(healthy)

    def fail_observation():
        raise ProcessObservationUnavailable
    monkeypatch.setattr("neko_launcher.ui.app_window.observe_exact_pso2", fail_observation)

    unhealthy = replace(healthy, connection_state=TelemetryConnectionState.DISCONNECTED)
    window._render_telemetry(unhealthy)

    assert window._controller.state.game_process_running is True
    assert len(window._scheduled_reconnects) == 0
    assert window._controller.state.proxy_status is ProxyStatus.RUNNING

def test_confirmed_absence_invokes_real_controller_and_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from neko_launcher.application.controller import ApplicationController
    from neko_launcher.domain.events import GameProcessStateChanged
    from neko_launcher.domain.models import AppState, AuthStatus, Entitlement, EntitlementStatus, ProxyStatus

    class FakeGateway:
        def __init__(self) -> None:
            self.stop_count = 0
            self.starts = 0
        def start_proxy(self, **kwargs: Any) -> None:
            self.starts += 1
        def stop(self) -> None:
            self.stop_count += 1
        def stop_proxy(self) -> None:
            pass

    gateway = FakeGateway()
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("pso2-proxy", EntitlementStatus.ACTIVE),
        session_id="session",
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )

    class FakeCoreDiagnosticsService:
        def record_stage(self, stage: str, **kwargs: Any) -> None:
            pass

    class FakeEventPublisher:
        def publish(self, event: Any) -> None:
            pass

    real_controller = ApplicationController(
        event_bus=FakeEventPublisher(),  # type: ignore
        proxy_gateway=gateway,  # type: ignore
        game_gateway=None,  # type: ignore
    )
    real_controller._state = state


    window = build_tweaker_window(tmp_path / "Tweaker.exe")
    window._controller = real_controller  # type: ignore

    monkeypatch.setattr("neko_launcher.ui.app_window.observe_exact_pso2", lambda: None)

    # 1. First trigger
    window._on_game_detected(True)
    # Because we're verifying real controller side-effects without the event bus integration,
    # manually dispatch the GameProcessStateChanged event just as AppWindow would when calling
    # self._event_bus.publish(GameProcessStateChanged(running=False)) inside _on_game_detected
    window._controller.dispatch(GameProcessStateChanged(running=False))

    assert real_controller.state.game_process_running is False
    assert gateway.stop_count == 1

    # Assert queued service work wasn't populated bypassing controller
    assert len(window._submitted_work) == 0
    assert window._service.proxy_stopped == 0

    # 2. Second trigger (should not stop again if state is already stopped)
    window._on_game_detected(True)
    assert gateway.stop_count == 1


def test_bound_pso2_session_liveness_ignores_transient_window_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    target1 = TargetProcess(101, "pso2.exe", 1001)
    target2 = TargetProcess(202, "pso2.exe", 2002)

    active_target: TargetProcess | None = target1
    window_visible = True

    monkeypatch.setattr(
        "neko_launcher.ui.app_window.observe_exact_pso2",
        lambda: active_target if window_visible else None,
    )
    monkeypatch.setattr(
        "neko_launcher.ui.app_window.is_same_target_still_running",
        lambda target: active_target is not None and target == active_target,
        raising=False,
    )

    # 1. Initial target bind -> running
    window._on_game_detected(True)
    assert window._controller.state.game_process_running is True
    assert getattr(window, "_bound_target", None) == target1
    assert len(window._submitted_work) == 1
    assert window._service.proxy_started == 0
    window._submitted_work[0]()
    assert window._service.proxy_started == 1

    window._controller.state = replace(
        window._controller.state,
        proxy_status=ProxyStatus.RUNNING,
    )
    window._reconnect_controller.observe_running()

    # 2. Transient window unavailable: observe_exact_pso2 returns None, but target1 is still running
    window_visible = False
    window._on_game_detected(True)

    # Must NOT stop, reset, or start second proxy
    assert window._controller.state.game_process_running is True
    assert getattr(window, "_bound_target", None) == target1
    assert window._service.proxy_stopped == 0
    assert len(window._submitted_work) == 1
    assert window._proxy_start_attempted_for_detected_game is True

    # 3. Telemetry unhealthy path regression
    window._observe_runtime_health(SimpleNamespace(is_healthy=False))
    assert window._controller.state.game_process_running is True
    assert getattr(window, "_bound_target", None) == target1
    assert window._service.proxy_stopped == 0
    assert len(window._scheduled_reconnects) == 1

    # 4. Exact target disappears: target1 exits
    active_target = None
    window._on_game_detected(True)

    assert window._controller.state.game_process_running is False
    assert getattr(window, "_bound_target", None) is None
    assert window._proxy_start_attempted_for_detected_game is False
    assert window._reconnect_controller.owns_recovery is False

    # 5. New game identity after real exit may start once
    active_target = target2
    window_visible = True
    window._on_game_detected(True)

    assert window._controller.state.game_process_running is True
    assert getattr(window, "_bound_target", None) == target2
    assert len(window._submitted_work) == 2
    window._submitted_work[1]()
    assert window._service.proxy_started == 2


def test_unhealthy_telemetry_with_bound_target_ignores_window_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neko_launcher.domain.telemetry import (
        CoreHealthSnapshot,
        TelemetryConnectionState,
        TelemetryState,
    )

    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    target = TargetProcess(101, "pso2.exe", 1001)
    active_target: TargetProcess | None = target
    window_visible = True

    monkeypatch.setattr(
        "neko_launcher.ui.app_window.observe_exact_pso2",
        lambda: active_target if window_visible else None,
    )
    monkeypatch.setattr(
        "neko_launcher.ui.app_window.is_same_target_still_running",
        lambda t: active_target is not None and t == active_target,
        raising=False,
    )

    window._on_game_detected(True)
    assert window._controller.state.game_process_running is True
    window._controller.state = replace(
        window._controller.state,
        proxy_status=ProxyStatus.RUNNING,
    )
    window._reconnect_controller.observe_running()

    healthy = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            proxy_state="connected",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
        ),
    )
    window._render_telemetry(healthy)

    window_visible = False
    unhealthy = replace(healthy, connection_state=TelemetryConnectionState.DISCONNECTED)
    window._render_telemetry(unhealthy)

    assert window._controller.state.game_process_running is True
    assert getattr(window, "_bound_target", None) == target
    assert len(window._scheduled_reconnects) == 1


def test_bound_target_observation_failure_preserves_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    target = TargetProcess(101, "pso2.exe", 1001)
    monkeypatch.setattr(
        "neko_launcher.ui.app_window.observe_exact_pso2",
        lambda: target,
    )
    monkeypatch.setattr(
        "neko_launcher.ui.app_window.is_same_target_still_running",
        lambda t: True,
        raising=False,
    )

    window._on_game_detected(True)
    assert window._controller.state.game_process_running is True

    def fail_running(_target: Any) -> bool:
        raise ProcessObservationUnavailable("tasklist failed")

    monkeypatch.setattr(
        "neko_launcher.ui.app_window.is_same_target_still_running",
        fail_running,
        raising=False,
    )

    window._on_game_detected(True)
    assert window._controller.state.game_process_running is True
    assert getattr(window, "_bound_target", None) == target
