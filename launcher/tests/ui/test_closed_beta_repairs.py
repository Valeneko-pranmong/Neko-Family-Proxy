from dataclasses import replace
from concurrent.futures import Future
import inspect
from pathlib import Path
from typing import Any

from neko_launcher.domain.models import AppState, AuthStatus
from neko_launcher.domain.telemetry import (
    CoreHealthSnapshot,
    TelemetryConnectionState,
    TelemetryState,
)
from neko_launcher.infrastructure.config import ProgramPreferences
from neko_launcher.ui.app_window import AppWindow
from neko_launcher.ui.components.buttons import icon_entry, toggle_password_visibility
from neko_launcher.ui.settings_window import SettingsWindow


class Variable:
    def __init__(self, value: Any = "") -> None:
        self.value = value

    def get(self) -> Any:
        return self.value

    def set(self, value: Any) -> None:
        self.value = value


class Entry:
    def __init__(self) -> None:
        self.show = "●"

    def cget(self, name: str) -> str:
        assert name == "show"
        return self.show

    def configure(self, **options: str) -> None:
        self.show = options["show"]


def test_program_preferences_default_false_and_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "NEKO FAMILY" / "program.json"
    first = ProgramPreferences(path)
    assert first.always_on_top is False
    first.set_always_on_top(True)
    assert ProgramPreferences(path).always_on_top is True


def test_password_visibility_toggles_without_changing_value() -> None:
    entry = Entry()
    value = Variable("never-log-this")
    toggle_password_visibility(entry, value)
    assert entry.show == ""
    assert value.get() == "never-log-this"
    toggle_password_visibility(entry, value)
    assert entry.show == "●"
    assert value.get() == "never-log-this"


def test_settings_categories_are_exact_functional_groups() -> None:
    assert SettingsWindow.CATEGORIES == [
        ("status", "Status"),
        ("program", "Program"),
        ("account", "Account & Subscription"),
        ("pso2", "PSO2"),
        ("about", "About"),
    ]


def test_beta_settings_do_not_expose_nonfunctional_minimize_to_tray() -> None:
    settings_source = inspect.getsource(SettingsWindow)
    app_source = inspect.getsource(AppWindow)

    assert "Minimize to tray" not in settings_source
    assert "minimize_to_tray" not in settings_source
    assert "minimize_to_tray" not in app_source


def test_named_closed_beta_controls_have_real_bindings() -> None:
    settings_source = inspect.getsource(SettingsWindow)
    app_source = inspect.getsource(AppWindow)

    assert "command=self._open_settings_window" in app_source
    assert "command=self._on_always_on_top_changed" in settings_source
    assert "self._program_preferences.set_always_on_top(enabled)" in app_source
    assert "self._invoke_redeem_coupon" in settings_source
    assert 'discord.bind(' in settings_source
    assert 'webbrowser.open("https://discord.gg/fkjXW9AJ6a")' in settings_source
    assert "eye.bind(" in inspect.getsource(icon_entry)
    assert "toggle_password_visibility(entry, variable)" in inspect.getsource(icon_entry)


def test_redeem_is_single_flight_and_failure_reenables() -> None:
    window = object.__new__(AppWindow)
    window._redeem_in_flight = False
    window._coupon_code = Variable("CODE")
    window._error = Variable()
    window._notice = Variable()
    calls: list[tuple[Any, ...]] = []
    window._submit = lambda *args: calls.append(args)  # type: ignore[method-assign]
    window._set_redeem_busy = lambda busy: calls.append(("busy", busy))  # type: ignore[method-assign]

    window._redeem_coupon()
    window._redeem_coupon()
    assert len([call for call in calls if call and callable(call[0])]) == 1
    assert ("busy", True) in calls

    on_failure = [call[2] for call in calls if call and callable(call[0])][0]
    on_failure(RuntimeError("nope"))
    assert window._redeem_in_flight is False
    assert calls[-1] == ("busy", False)


def test_pending_redeem_keeps_failure_callback_for_next_poll() -> None:
    window = object.__new__(AppWindow)
    future: Future[Any] = Future()

    def on_failure(_error: Exception) -> None:
        pass

    window._pending = [(future, None, on_failure)]
    window._event_bus = type("EventBus", (), {"drain": lambda _self: []})()
    window.root = type("Root", (), {"winfo_exists": lambda _self: False})()

    window._drain_events()

    assert window._pending == [(future, None, on_failure)]


def _confirmation_window(running: bool) -> AppWindow:
    window = object.__new__(AppWindow)
    window._closing = False
    window._controller = type("Controller", (), {"state": AppState(
        auth_status=AuthStatus.AUTHENTICATED, game_process_running=running
    )})()
    return window


def test_close_cancel_while_pso2_running_leaves_launcher_untouched() -> None:
    window = _confirmation_window(True)
    shutdown: list[bool] = []
    window._confirm_game_active_action = lambda _action: False  # type: ignore[method-assign]
    window._perform_close = lambda: shutdown.append(True)  # type: ignore[method-assign]
    window.close()
    assert shutdown == []
    assert window._closing is False


def test_logout_cancel_while_pso2_running_does_not_submit() -> None:
    window = _confirmation_window(True)
    submitted: list[Any] = []
    window._confirm_game_active_action = lambda _action: False  # type: ignore[method-assign]
    window._submit = lambda *args: submitted.append(args)  # type: ignore[method-assign]
    window._sign_out()
    assert submitted == []


def test_temporary_telemetry_loss_preserves_truthful_totals() -> None:
    window = object.__new__(AppWindow)
    for name in (
        "_telemetry_speed", "_telemetry_transfer", "_telemetry_session",
        "_telemetry_health", "_download_speed", "_upload_speed",
        "_session_duration", "_status_title", "_status_subtitle",
    ):
        setattr(window, name, Variable())
    window._controller = type("Controller", (), {"state": AppState()})()
    window._last_truthful_telemetry_snapshot = None

    connected = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(rx_bytes=4096, tx_bytes=2048, uptime_ms=5000),
        rx_rate_bps=1024,
        tx_rate_bps=512,
    )
    window._render_telemetry(connected)
    truthful_totals = window._telemetry_transfer.get()
    disconnected = replace(connected, connection_state=TelemetryConnectionState.DISCONNECTED)
    window._render_telemetry(disconnected)

    assert window._telemetry_transfer.get() == truthful_totals
    assert "ไม่พร้อมใช้งาน" in window._telemetry_speed.get()
    assert "0 B |" not in window._telemetry_transfer.get()
