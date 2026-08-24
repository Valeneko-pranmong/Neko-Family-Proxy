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
from neko_launcher.ui.app_window import AppWindow, HEARTBEAT_INTERVAL_MS
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
        self.tweaker_started = 0
        self.sign_ins: list[tuple[str, str]] = []

    def sign_in(self, username: str, password: str) -> None:
        self.sign_ins.append((username, password))

    def launch_tweaker(self, executable: str) -> None:
        self.started.append(executable)
        self.tweaker_started += 1

    def start_proxy(self) -> None:
        self.proxy_started += 1


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


def test_open_debug_logs_failure_uses_existing_error_toast(
    monkeypatch: Any,
) -> None:
    window = object.__new__(AppWindow)
    window._debug_log_dir = Path("missing-logs")
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

    assert calls == [("Failed to open logs directory.", True)]


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
    window._proxy_start_attempted_for_detected_game = False
    window._proxy_retry_suppression_logged = False
    window._telemetry_speed = FakeVariable()  # type: ignore[assignment]
    window._telemetry_transfer = FakeVariable()  # type: ignore[assignment]
    window._telemetry_session = FakeVariable()  # type: ignore[assignment]
    window._telemetry_health = FakeVariable()  # type: ignore[assignment]
    window._download_speed = FakeVariable()  # type: ignore[assignment]
    window._upload_speed = FakeVariable()  # type: ignore[assignment]
    window._session_duration = FakeVariable()  # type: ignore[assignment]
    window._status_title = FakeVariable()  # type: ignore[assignment]
    window._status_subtitle = FakeVariable()  # type: ignore[assignment]
    window._tray_manager = None
    window._closing = False
    window._clear_recovery_sensitive_fields = lambda: None  # type: ignore[method-assign]
    window._submitted_work = []
    window._submit = (  # type: ignore[method-assign]
        lambda work, on_success=None: window._submitted_work.append(work)
    )
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

    assert len(window._submitted_work) == 2  # type: ignore[attr-defined]


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
    assert window._service.started == [str(tweaker.resolve())]  # type: ignore[attr-defined]


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

    truthful_totals = window._telemetry_transfer.get()
    disconnected = replace(
        s_conn, connection_state=TelemetryConnectionState.DISCONNECTED
    )
    window._render_telemetry(disconnected)
    assert window._telemetry_transfer.get() == truthful_totals
    assert window._telemetry_session.get() == "เซสชัน: ไม่พร้อมใช้งาน"
    assert window._session_duration.get() == "ไม่พร้อมใช้งาน"

    stale = replace(s_conn, is_stale=True)
    window._render_telemetry(stale)
    assert window._telemetry_transfer.get() == truthful_totals
    assert window._telemetry_session.get() == "เซสชัน: ไม่พร้อมใช้งาน (ข้อมูลล้าสมัย)"
    assert window._session_duration.get() == "ไม่พร้อมใช้งาน (ข้อมูลล้าสมัย)"


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
