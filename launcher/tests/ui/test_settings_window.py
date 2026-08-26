from pathlib import Path
import tkinter as tk

import pytest
import customtkinter as ctk

from neko_launcher import __version__
from neko_launcher.ui.settings_window import (
    SettingsWindow,
    customer_connection_status,
    customer_game_status,
)
from neko_launcher.ui.app_window import AppWindow
from neko_launcher.domain.models import AuthStatus
from neko_launcher.ui.theme import PALETTE


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

        assert len(window.CATEGORIES) == 5
        expected_keys = [
            "status",
            "program",
            "account",
            "pso2",
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
        assert window._selected_category == "pso2"
        assert window._pages["pso2"].winfo_manager() != ""
        window._search_entry.delete(0, "end")
        window._filter_categories()
        assert window._nav_buttons["account"].winfo_manager() != ""
        assert window._selected_category == "pso2"

        # Test close
        window.close()
        assert closed is True
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_account_page_binds_shared_username_and_existing_actions_once() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        account_var = ctk.StringVar(master=root, value="neko-user")
        account_status_var = ctk.StringVar(master=root, value="เข้าสู่ระบบแล้ว")
        calls = {"password": 0, "sign_out": 0}
        window = SettingsWindow(
            root,
            account_var=account_var,
            account_status_var=account_status_var,
            on_change_password=lambda: calls.__setitem__(
                "password", calls["password"] + 1
            ),
            on_sign_out=lambda: calls.__setitem__(
                "sign_out", calls["sign_out"] + 1
            ),
        )

        assert str(window._account_label.cget("textvariable")) == str(account_var)
        assert str(window._account_status_label.cget("textvariable")) == str(
            account_status_var
        )
        assert account_var.get() == "neko-user"

        window._change_password_button.invoke()
        window._sign_out_button.invoke()

        assert calls == {"password": 1, "sign_out": 1}
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_repeated_settings_password_action_reuses_existing_app_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = object.__new__(AppWindow)
    window._password_dialog = None
    window._icon_path = None
    window._new_password = object()
    window._new_password_confirm = object()
    window._error = object()
    window.root = object()
    created = 0

    class FakeDialog:
        def winfo_exists(self) -> bool:
            return True

        def lift(self) -> None:
            pass

        def focus_force(self) -> None:
            pass

    def create_dialog(*_args: object) -> FakeDialog:
        nonlocal created
        created += 1
        return FakeDialog()

    monkeypatch.setattr(
        "neko_launcher.ui.app_window.open_password_dialog", create_dialog
    )

    window._open_password_dialog()
    window._open_password_dialog()

    assert created == 1


def test_subscription_page_uses_shared_entitlement_and_coupon_authority() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        days_var = ctk.StringVar(master=root, value="เหลือประมาณ 30 วัน")
        expiry_var = ctk.StringVar(master=root, value="20/09/2026 12:00")
        status_var = ctk.StringVar(master=root, value="ใช้งานได้ • เหลือประมาณ 30 วัน")
        coupon_var = ctk.StringVar(master=root, value="NEKO-TEST")
        calls = 0

        def redeem() -> None:
            nonlocal calls
            calls += 1
            coupon_var.set("")

        window = SettingsWindow(
            root,
            entitlement_status_var=status_var,
            entitlement_days_var=days_var,
            entitlement_expiry_var=expiry_var,
            coupon_var=coupon_var,
            on_redeem_coupon=redeem,
        )

        assert window._coupon_var is coupon_var
        assert window._coupon_entry.cget("placeholder_text") == "กรอกรหัสคูปอง"
        assert str(window._entitlement_status_label.cget("textvariable")) == str(
            window._customer_membership_status_var
        )
        assert window._customer_membership_status_var.get() == "ใช้งานได้"
        assert days_var.get() == "เหลือประมาณ 30 วัน"
        assert expiry_var.get() == "20/09/2026 12:00"
        window._redeem_coupon_button.invoke()
        assert calls == 1
        assert coupon_var.get() == ""
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_pso2_page_is_detection_only_and_tweaker_uses_shared_path_actions() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        game_status_var = ctk.StringVar(
            master=root, value="สถานะเกม: ยังไม่เข้าเกม (รอ pso2.exe)"
        )
        tweaker_path_var = ctk.StringVar(master=root, value=r"C:\PSO2\Tweaker.exe")
        calls = {"browse": 0, "launch": 0}
        window = SettingsWindow(
            root,
            game_status_var=game_status_var,
            game_path_var=tweaker_path_var,
            on_choose_game=lambda: calls.__setitem__("browse", calls["browse"] + 1),
            on_launch_game=lambda: calls.__setitem__("launch", calls["launch"] + 1),
        )

        assert window._customer_game_status_var.get() == "กำลังรอเปิด PSO2"
        assert str(window._tweaker_path_entry.cget("textvariable")) == str(
            tweaker_path_var
        )
        window._choose_tweaker_button.invoke()
        window._launch_tweaker_button.invoke()
        assert calls == {"browse": 1, "launch": 1}

        source = Path(__file__).parents[2].joinpath(
            "src", "neko_launcher", "ui", "settings_window.py"
        ).read_text(encoding="utf-8")
        pso2_page = source.split("def _create_pso2_page")[1].split(
            "def _create_tweaker_page"
        )[0]
        assert "_game_path_var" not in pso2_page
        assert "ตำแหน่งไฟล์เกม" not in pso2_page
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_diagnostics_uses_existing_local_tools_with_debug_gate(
    tmp_path: Path,
) -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        calls = {"logs": 0, "advanced": 0}
        normal_window = SettingsWindow(
            root,
            debug_mode=False,
            debug_log_dir=Path(r"C:\Neko\logs"),
            on_open_logs=lambda: calls.__setitem__("logs", calls["logs"] + 1),
            on_show_advanced_diagnostics=lambda: calls.__setitem__(
                "advanced", calls["advanced"] + 1
            ),
        )
        normal_window._open_logs_button.invoke()
        assert calls["logs"] == 1
        assert not hasattr(normal_window, "_advanced_diagnostics_button")
        normal_window.destroy()

        debug_window = SettingsWindow(
            root,
            debug_mode=True,
            debug_log_dir=Path(r"C:\Neko\logs"),
            on_open_logs=lambda: calls.__setitem__("logs", calls["logs"] + 1),
            on_show_advanced_diagnostics=lambda: calls.__setitem__(
                "advanced", calls["advanced"] + 1
            ),
        )
        debug_window._advanced_diagnostics_button.invoke()
        assert calls["advanced"] == 1
        debug_window.destroy()

        # The open-logs button stays rendered and wired even when the logs
        # directory does not exist yet; AppWindow._open_debug_logs creates it
        # on demand, so the callback contract must not depend on existence.
        missing_dir_window = SettingsWindow(
            root,
            debug_mode=False,
            debug_log_dir=tmp_path / "fresh" / "logs",
            on_open_logs=lambda: calls.__setitem__("logs", calls["logs"] + 1),
            on_show_advanced_diagnostics=lambda: calls.__setitem__(
                "advanced", calls["advanced"] + 1
            ),
        )
        assert hasattr(missing_dir_window, "_open_logs_button")
        assert not (tmp_path / "fresh" / "logs").exists()
        missing_dir_window._open_logs_button.invoke()
        assert calls["logs"] == 2
        missing_dir_window.destroy()
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
        "def _create_about_page"
    )[0]
    about = source.split("def _create_about_page")[1].split("# Lifecycle")[0]

    assert "ProxyCore" not in diagnostics
    assert "สถานะระบบเชื่อมต่อ" in diagnostics
    assert "โฟลเดอร์บันทึกการทำงาน" in diagnostics
    assert "CustomTkinter" not in about
    assert "DWM" not in about
    assert "สถาปัตยกรรม" not in about
    assert 'text=f"Version / Build: v{__version__}"' in about
    assert "NEKO FAMILY PROXY" in about
    assert "จัดทำโดย NEKO FAMILY STUDIO" in about
    assert "https://discord.gg/fkjXW9AJ6a" in about
    assert __version__


def test_app_window_settings_single_instance_contract() -> None:
    window = object.__new__(AppWindow)
    window._settings_window = None
    window._controller = type(
        "Controller",
        (),
        {"state": type("State", (), {"auth_status": AuthStatus.AUTHENTICATED})()},
    )()

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


def test_app_window_does_not_open_settings_while_unauthenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeController:
        state = type("State", (), {"auth_status": AuthStatus.SIGNED_OUT})()

    window = object.__new__(AppWindow)
    window._controller = FakeController()  # type: ignore[assignment]
    window._settings_window = None
    created = 0

    def create_settings(*_args: object, **_kwargs: object) -> object:
        nonlocal created
        created += 1
        return object()

    monkeypatch.setattr(
        "neko_launcher.ui.app_window.SettingsWindow", create_settings
    )

    window._open_settings_window()

    assert created == 0
    assert window._settings_window is None


@pytest.mark.parametrize(
    "auth_status",
    [
        AuthStatus.RECOVERY_CODE_ENTRY,
        AuthStatus.RECOVERY_VERIFYING,
        AuthStatus.RECOVERY_PASSWORD_CHANGE,
    ],
)
def test_app_window_does_not_open_settings_during_recovery(
    auth_status: AuthStatus,
) -> None:
    window = object.__new__(AppWindow)
    window._controller = type(
        "Controller",
        (),
        {"state": type("State", (), {"auth_status": auth_status})()},
    )()
    window._settings_window = None

    window._open_settings_window()

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


def test_app_window_source_uses_approved_asset_for_settings_control() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "app_window.py"
    ).read_text(encoding="utf-8")

    assert "self._settings_control_image" in source
    assert "Image.open(self._icon_path)" in source
    assert "⚙" not in source
    assert "self._open_settings_window" in source
    assert "self._settings_window" in source
    # Verify no duplicate internal minimize / close buttons in _build_window_controls
    controls_section = source.split("def _build_window_controls")[1].split("def _open_settings_window")[0]
    assert '"—"' not in controls_section
    assert '"×"' not in controls_section


def test_coupon_placeholder_is_guidance_not_coupon_value() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        coupon_var = ctk.StringVar(master=root, value="")
        window = SettingsWindow(root, coupon_var=coupon_var)

        assert window._coupon_entry.cget("placeholder_text") == "กรอกรหัสคูปอง"
        assert window._coupon_entry._placeholder_text_active is True
        assert coupon_var.get() == ""
        window._coupon_entry.focus_set()
        window._coupon_entry.insert(0, "NEKO-TEST")
        window._sync_coupon_from_entry()
        assert coupon_var.get() == "NEKO-TEST"
        window._coupon_entry.delete(0, "end")
        window._sync_coupon_from_entry()
        assert coupon_var.get() == ""
        window._search_entry.focus_set()
        window.update_idletasks()
        assert window._coupon_entry._placeholder_text_active is True
    finally:
        root.destroy()


def test_redeem_button_syncs_entry_to_shared_coupon_authority() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        coupon_var = ctk.StringVar(master=root, value="")
        redeemed: list[str] = []
        window = SettingsWindow(
            root,
            coupon_var=coupon_var,
            on_redeem_coupon=lambda: redeemed.append(coupon_var.get()),
        )
        window._coupon_entry.focus_set()
        window._coupon_entry.insert(0, "NEKO-PASTE")

        window._redeem_coupon_button.invoke()

        assert redeemed == ["NEKO-PASTE"]
        assert coupon_var.get() == "NEKO-PASTE"
    finally:
        root.destroy()


@pytest.mark.parametrize(
    ("technical_status", "expected"),
    [
        ("สถานะเกม: ยังไม่เข้าเกม (รอ pso2.exe)", "กำลังรอเปิด PSO2"),
        ("สถานะเกม: เข้าเกมแล้ว (พบ pso2.exe)", "ตรวจพบ PSO2 แล้ว"),
    ],
)
def test_pso2_customer_copy_hides_detector_implementation(
    technical_status: str,
    expected: str,
) -> None:
    result = customer_game_status(technical_status)

    assert result == expected
    assert "pso2.exe" not in result.lower()


def test_tweaker_long_path_is_read_only_and_preserves_shared_value() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        long_path = "C:\\Users\\customer\\" + ("very-long-folder\\" * 20) + "Tweaker.exe"
        path_var = ctk.StringVar(master=root, value=long_path)
        window = SettingsWindow(root, game_path_var=path_var)
        window.update_idletasks()

        assert window._tweaker_path_entry.cget("state") == "readonly"
        assert path_var.get() == long_path
        assert window._tweaker_path_entry.winfo_width() <= window._content_area.winfo_width()
    finally:
        root.destroy()


def test_settings_action_hierarchy_and_consistent_control_height() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        window = SettingsWindow(root, debug_log_dir=Path(r"C:\Neko\logs"))

        assert window._redeem_coupon_button.cget("fg_color") == PALETTE.primary
        assert window._launch_tweaker_button.cget("fg_color") == PALETTE.primary
        assert window._change_password_button.cget("fg_color") == "transparent"
        assert window._choose_tweaker_button.cget("fg_color") == "transparent"
        assert window._sign_out_button.cget("text_color") == PALETTE.danger
        assert window._sign_out_button.cget("border_color") == PALETTE.danger
        assert window._sign_out_button.cget("fg_color") != PALETTE.primary
        for control in (
            window._search_entry,
            window._coupon_entry,
            window._tweaker_path_entry,
            window._change_password_button,
            window._sign_out_button,
            window._redeem_coupon_button,
            window._choose_tweaker_button,
            window._launch_tweaker_button,
            window._open_logs_button,
        ):
            assert control.cget("height") >= 32
    finally:
        root.destroy()


def test_normal_settings_widgets_hide_customer_forbidden_terms() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        game_status = ctk.StringVar(
            master=root, value="สถานะเกม: ยังไม่เข้าเกม (รอ pso2.exe)"
        )
        connection_status = ctk.StringVar(master=root, value="ProxyCore: ยังไม่ทำงาน")
        window = SettingsWindow(
            root,
            game_status_var=game_status,
            proxy_connection_var=connection_status,
            debug_mode=False,
        )
        forbidden = (
            "T10",
            "ProxyCore",
            "pso2.exe",
            "AWS",
            "Lightsail",
            "Shadowsocks",
            "V2Ray",
            "8388",
            "Direct Tunnel",
            "Named Pipe",
            "CustomTkinter",
            "DWM",
        )

        def visible_copy(widget: object) -> list[str]:
            values: list[str] = []
            cget = getattr(widget, "cget", None)
            if cget is not None:
                for option in ("text", "placeholder_text"):
                    try:
                        value = cget(option)
                    except (tk.TclError, ValueError, TypeError):
                        continue
                    if isinstance(value, str):
                        values.append(value)
            for child in getattr(widget, "winfo_children")():
                values.extend(visible_copy(child))
            return values

        copy = "\n".join(visible_copy(window))
        for term in forbidden:
            assert term.lower() not in copy.lower()
    finally:
        root.destroy()


def test_settings_keyboard_focus_order_covers_important_controls() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        window = SettingsWindow(root, debug_log_dir=Path(r"C:\Neko\logs"))

        assert window._focus_controls == (
            window._search_entry,
            window._change_password_button,
            window._sign_out_button,
            window._coupon_entry,
            window._redeem_coupon_button,
            window._tweaker_path_entry,
            window._choose_tweaker_button,
            window._launch_tweaker_button,
            window._open_logs_button,
        )
        assert len(set(window._focus_controls)) == len(window._focus_controls)
    finally:
        root.destroy()
