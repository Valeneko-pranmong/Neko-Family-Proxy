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
        self.usage_started = 0

    def start_usage(self, executable: str) -> None:
        self.started.append(executable)
        self.usage_started += 1

    def launch_tweaker(self, executable: str) -> None:
        self.started.append(executable)
        self.tweaker_started += 1

    def start_proxy(self) -> None:
        self.proxy_started += 1


class FakeController:
    def __init__(self, state: AppState) -> None:
        self.state = state


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
    window._auto_connect = FakeVariable(True)  # type: ignore[assignment]
    window._auto_launch = FakeVariable(auto_launch)  # type: ignore[assignment]
    window._error = FakeVariable()  # type: ignore[assignment]
    window._notice = FakeVariable()  # type: ignore[assignment]
    window._login_password = FakeVariable("password")  # type: ignore[assignment]
    return window


def test_auto_connect_open_starts_tweaker_without_proxy(tmp_path: Path) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)

    window._launch_game()

    assert window._service.started == [str(tweaker.resolve())]  # type: ignore[attr-defined]
    assert window._service.tweaker_started == 1  # type: ignore[attr-defined]
    assert window._service.proxy_started == 0  # type: ignore[attr-defined]


def test_manual_mode_open_starts_proxy_and_tweaker_together(tmp_path: Path) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._auto_connect.set(False)

    window._launch_game()

    assert window._service.started == [str(tweaker.resolve())]  # type: ignore[attr-defined]
    assert window._service.usage_started == 1  # type: ignore[attr-defined]
    assert window._service.tweaker_started == 0  # type: ignore[attr-defined]


def test_detected_pso2_starts_proxy_only_when_entitlement_is_valid(
    tmp_path: Path,
) -> None:
    tweaker = tmp_path / "Tweaker.exe"
    tweaker.touch()
    window = build_tweaker_window(tweaker)
    window._on_game_detected(True)

    assert window._service.proxy_started == 1  # type: ignore[attr-defined]


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
