from pathlib import Path
import pytest
import customtkinter as ctk

from neko_launcher import __version__
from neko_launcher.ui.settings_window import (
    SettingsWindow,
    customer_connection_status,
)
from neko_launcher.ui.app_window import AppWindow


def test_settings_window_structure_and_categories() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        closed = False

        def on_close() -> None:
            nonlocal closed
            closed = True

        window = SettingsWindow(
            root,
            on_close=on_close,
        )

        assert len(window.CATEGORIES) == 10
        expected_keys = [
            "general",
            "account",
            "subscription",
            "pso2",
            "tweaker",
            "connection",
            "appearance",
            "notifications",
            "diagnostics",
            "about",
        ]
        assert [k for k, _ in window.CATEGORIES] == expected_keys

        # Test category switching
        for key in expected_keys:
            window.select_category(key)
            assert window._pages[key].winfo_manager() != ""

        # Test actual entry-driven search filtering and empty-state restoration.
        window._search_entry.insert(0, "pso2")
        window._filter_categories()
        assert window._nav_buttons["pso2"].winfo_manager() != ""
        assert window._nav_buttons["account"].winfo_manager() == ""
        window._search_entry.delete(0, "end")
        window._filter_categories()
        assert window._nav_buttons["account"].winfo_manager() != ""

        # Test close
        window.close()
        assert closed is True
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_connection_page_security_contract() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "settings_window.py"
    ).read_text(encoding="utf-8")

    # Strictly verify NO secrets or internal endpoints in Settings UI source
    assert "18.178.140.8" not in source
    assert "8388" not in source
    assert "aes-128-gcm" not in source
    assert "Shadowsocks" not in source.split("_create_connection_page")[1].split("def _create_appearance_page")[0]
    # Verify no raw vendor/infrastructure marketing terms in customer UI
    assert "AWS" not in source
    assert "Lightsail" not in source
    assert "Direct Tunnel" not in source


def test_settings_window_has_no_phase_or_developer_language() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "settings_window.py"
    ).read_text(encoding="utf-8")

    forbidden_tokens = [
        "T10",
        "T10B1",
        "T10B2",
        "รอบถัดไป",
        "เวอร์ชันถัดไป",
        "not implemented",
        "pending owner review",
    ]
    for token in forbidden_tokens:
        assert token not in source


def test_settings_search_placeholder_and_no_duplicate_close() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "settings_window.py"
    ).read_text(encoding="utf-8")

    assert "ค้นหาการตั้งค่า..." in source
    # Header should not have a duplicate internal close button
    header_section = source.split("# Header bar")[1].split("# Body container")[0]
    assert 'secondary_button(\n            header,\n            "×"' not in header_section
    assert '"×"' not in header_section


def test_settings_search_placeholder_uses_native_empty_entry_behavior() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "settings_window.py"
    ).read_text(encoding="utf-8")

    entry_section = source.split("self._search_entry = ctk.CTkEntry(")[1].split(")\n", 1)[0]
    assert 'placeholder_text="ค้นหาการตั้งค่า..."' in entry_section
    assert "textvariable=" not in entry_section
    assert 'self._search_entry.bind("<KeyRelease>", self._filter_categories)' in source


def test_diagnostics_maps_technical_state_to_customer_safe_copy() -> None:
    expected = {
        "ProxyCore: ยังไม่ทำงาน": "ยังไม่ทำงาน",
        "ProxyCore: กำลังเริ่มทำงาน...": "กำลังเชื่อมต่อ",
        "ProxyCore: ทำงานแล้ว": "เชื่อมต่อแล้ว",
        "ProxyCore: กำลังหยุดทำงาน...": "กำลังเชื่อมต่อ",
        "ProxyCore: เริ่มทำงานไม่สำเร็จ": "ไม่สามารถเชื่อมต่อได้",
    }

    for technical_state, customer_state in expected.items():
        assert customer_connection_status(technical_state) == customer_state
        assert "ProxyCore" not in customer_connection_status(technical_state)


    assert customer_connection_status("unexpected internal state") == (
        "ไม่สามารถเชื่อมต่อได้"
    )


def test_settings_destroy_removes_shared_connection_trace() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        connection_var = ctk.StringVar(master=root, value="ProxyCore: ยังไม่ทำงาน")
        window = SettingsWindow(root, proxy_connection_var=connection_var)
        trace_id = window._proxy_connection_trace_id

        assert any(trace_id in callback for _, callback in connection_var.trace_info())

        window.destroy()

        assert all(trace_id not in callback for _, callback in connection_var.trace_info())
    finally:
        root.destroy()


def test_diagnostics_and_about_copy_is_customer_safe() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "settings_window.py"
    ).read_text(encoding="utf-8")
    diagnostics = source.split("def _create_diagnostics_page")[1].split(
        "def _open_logs_folder"
    )[0]
    about = source.split("def _create_about_page")[1].split("# Lifecycle")[0]

    assert "ProxyCore" not in diagnostics
    assert "สถานะระบบเชื่อมต่อ" in diagnostics
    assert "โฟลเดอร์บันทึกการทำงาน" in diagnostics
    assert "CustomTkinter" not in about
    assert "DWM" not in about
    assert "สถาปัตยกรรม" not in about
    assert 'text=f"v{__version__}"' in about
    assert __version__


def test_app_window_settings_single_instance_contract() -> None:
    window = object.__new__(AppWindow)
    window._settings_window = None

    class FakeToplevel:
        def __init__(self) -> None:
            self.lift_called = 0
            self.focus_called = 0
            self.destroyed = False

        def winfo_exists(self) -> bool:
            return not self.destroyed

        def lift(self) -> None:
            self.lift_called += 1

        def focus_force(self) -> None:
            self.focus_called += 1

        def destroy(self) -> None:
            self.destroyed = True

    fake_top = FakeToplevel()
    window._settings_window = fake_top  # type: ignore[assignment]

    # Reopening existing settings window lifts & focuses instead of creating duplicate
    window._open_settings_window()
    assert fake_top.lift_called == 1
    assert fake_top.focus_called == 1

    # Closing settings window clears owner reference
    window._close_settings_window()
    assert window._settings_window is None


def test_app_window_close_cleans_settings_window() -> None:
    window = object.__new__(AppWindow)
    window._closing = False

    class FakeToplevel:
        def __init__(self) -> None:
            self.destroyed = False

        def winfo_exists(self) -> bool:
            return not self.destroyed

        def destroy(self) -> None:
            self.destroyed = True

    class FakeRoot:
        def __init__(self) -> None:
            self.destroyed = False

        def quit(self) -> None:
            pass

        def destroy(self) -> None:
            self.destroyed = True

    class FakeService:
        def shutdown(self) -> None:
            pass

    class FakeExecutor:
        def shutdown(self, **kwargs: object) -> None:
            pass

    fake_top = FakeToplevel()
    window._settings_window = fake_top  # type: ignore[assignment]
    window._service = FakeService()  # type: ignore[assignment]
    window._executor = FakeExecutor()  # type: ignore[assignment]
    window._tray_manager = None
    window._clear_recovery_sensitive_fields = lambda: None  # type: ignore[method-assign]
    window.root = FakeRoot()  # type: ignore[assignment]

    window.close()

    assert fake_top.destroyed is True
    assert window._settings_window is None


def test_app_window_source_has_settings_gear_control_only() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "app_window.py"
    ).read_text(encoding="utf-8")

    assert "⚙" in source
    assert "self._open_settings_window" in source
    assert "self._settings_window" in source
    # Verify no duplicate internal minimize / close buttons in _build_window_controls
    controls_section = source.split("def _build_window_controls")[1].split("def _open_settings_window")[0]
    assert '"—"' not in controls_section
    assert '"×"' not in controls_section
