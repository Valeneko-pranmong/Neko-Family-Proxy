from __future__ import annotations

import tkinter as tk
from pathlib import Path

import customtkinter as ctk
import pytest
from PIL import Image

from neko_launcher.ui.views.auth_view import WEB_LOGIN_LABEL, AuthView


def test_web_login_button_is_optional_and_invokes_handler() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        calls: list[int] = []
        view = AuthView(
            root,
            status_var=tk.StringVar(master=root, value="ยังไม่ได้เข้าสู่ระบบ"),
            login_email_var=tk.StringVar(master=root),
            login_password_var=tk.StringVar(master=root),
            register_username_var=tk.StringVar(master=root),
            register_password_var=tk.StringVar(master=root),
            register_password_confirm_var=tk.StringVar(master=root),
            on_login=lambda: None,
            on_register=lambda: None,
            on_forgot_password=lambda: None,
            on_web_login=lambda: calls.append(1),
            web_auth_enabled=True,
        )
        root.geometry("440x592")
        view.frame.pack(fill="both", expand=True)
        root.deiconify()
        root.update()

        assert view._web_login_button is not None
        assert view._web_login_button.cget("text") == WEB_LOGIN_LABEL
        view._web_login_button.invoke()
        assert calls == [1]

        view.set_actions_enabled(signed_in=False, authenticating=True)
        assert view._web_login_button.cget("state") == "disabled"
    finally:
        root.destroy()


def test_web_only_auth_view_hides_password_and_registration_controls() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        calls: list[int] = []
        view = AuthView(
            root,
            status_var=tk.StringVar(master=root, value="ยังไม่ได้เข้าสู่ระบบ"),
            login_email_var=tk.StringVar(master=root),
            login_password_var=tk.StringVar(master=root),
            register_username_var=tk.StringVar(master=root),
            register_password_var=tk.StringVar(master=root),
            register_password_confirm_var=tk.StringVar(master=root),
            on_login=lambda: None,
            on_register=lambda: None,
            on_forgot_password=lambda: None,
            on_web_login=lambda: calls.append(1),
            web_auth_enabled=True,
            web_auth_only=True,
        )
        root.geometry("440x592")
        view.frame.pack(fill="both", expand=True)
        root.deiconify()
        root.update()

        assert view._web_login_button is not None
        assert view._web_login_button.cget("text") == WEB_LOGIN_LABEL
        assert view._login_button is None
        assert view._register_button is None
        assert not hasattr(view, "_tab_controls")
        view._web_login_button.invoke()
        assert calls == [1]

        view.set_actions_enabled(signed_in=False, authenticating=True)
        assert view._web_login_button.cget("state") == "disabled"
    finally:
        root.destroy()


def test_register_cta_has_real_visual_height() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        view = AuthView(
            root,
            status_var=tk.StringVar(master=root, value="ยังไม่ได้เข้าสู่ระบบ"),
            login_email_var=tk.StringVar(master=root),
            login_password_var=tk.StringVar(master=root),
            register_username_var=tk.StringVar(master=root),
            register_password_var=tk.StringVar(master=root),
            register_password_confirm_var=tk.StringVar(master=root),
            on_login=lambda: None,
            on_register=lambda: None,
            on_forgot_password=lambda: None,
        )
        root.geometry("440x592")
        view.frame.pack(fill="both", expand=True)
        view._switch_tab("register")
        root.deiconify()
        root.update()

        assert view._register_action.winfo_height() >= 70
        assert view._register_button.winfo_height() >= 50
    finally:
        root.destroy()


def test_web_only_view_shows_live_step_and_cancel_while_authenticating() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        cancelled: list[int] = []
        view = AuthView(
            root,
            status_var=tk.StringVar(master=root, value="กำลังเข้าสู่ระบบ"),
            login_email_var=tk.StringVar(master=root),
            login_password_var=tk.StringVar(master=root),
            register_username_var=tk.StringVar(master=root),
            register_password_var=tk.StringVar(master=root),
            register_password_confirm_var=tk.StringVar(master=root),
            on_login=lambda: None,
            on_register=lambda: None,
            on_forgot_password=lambda: None,
            on_web_login=lambda: None,
            on_cancel_web_login=lambda: cancelled.append(1),
            web_auth_enabled=True,
            web_auth_only=True,
        )
        root.geometry("440x592")
        view.frame.pack(fill="both", expand=True)
        root.deiconify()
        root.update()

        assert view._progress_panel is not None
        assert view._progress_panel.winfo_manager() == ""

        view.set_auth_progress("กำลังรอการยืนยันจากเบราว์เซอร์")
        root.update()
        assert view._progress_panel.winfo_manager() == "place"
        assert (
            view._progress_text.cget("text")
            == "กำลังรอการยืนยันจากเบราว์เซอร์"
        )

        assert view._cancel_button is not None
        view._cancel_button.invoke()
        assert cancelled == [1]

        view.set_auth_progress(None)
        root.update()
        assert view._progress_panel.winfo_manager() == ""
    finally:
        root.destroy()


def test_web_only_progress_panel_does_not_move_login_controls() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        view = AuthView(
            root,
            status_var=tk.StringVar(master=root, value="กำลังเข้าสู่ระบบ"),
            login_email_var=tk.StringVar(master=root),
            login_password_var=tk.StringVar(master=root),
            register_username_var=tk.StringVar(master=root),
            register_password_var=tk.StringVar(master=root),
            register_password_confirm_var=tk.StringVar(master=root),
            on_login=lambda: None,
            on_register=lambda: None,
            on_forgot_password=lambda: None,
            on_web_login=lambda: None,
            on_cancel_web_login=lambda: None,
            web_auth_enabled=True,
            web_auth_only=True,
        )
        root.geometry("440x592")
        view.frame.pack(fill="both", expand=True)
        root.deiconify()
        root.update()

        before = view._web_login_button.winfo_rooty()
        view.set_auth_progress("กำลังรอการยืนยันจากเบราว์เซอร์")
        root.update()
        assert view._web_login_button.winfo_rooty() == before

        view.set_auth_progress("ยืนยันแล้ว กำลังเชื่อมต่อบัญชี")
        root.update()
        assert view._web_login_button.winfo_rooty() == before
    finally:
        root.destroy()


def test_web_only_copy_matches_customer_facing_requirements() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "views"
        / "auth_view.py"
    ).read_text(encoding="utf-8")

    assert "ล็อคอินด้วย Neko Family Network ID" in source
    assert "ยินดีต้อนรับสู่ Neko Family Proxy" in source
    assert "https://discord.gg/fkjXW9AJ6a" in source
    assert "เข้าสู่ระบบด้วย Discord" not in source
    assert "ไม่ต้องสมัครสมาชิกใหม่" not in source
    assert "เบราว์เซอร์จะเปิดขึ้นเอง" not in source


def test_web_login_button_uses_discord_icon(tmp_path: Path) -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        icon_path = tmp_path / "discord-icon.png"
        Image.new("RGBA", (32, 32), (88, 101, 242, 255)).save(icon_path)
        view = AuthView(
            root,
            status_var=tk.StringVar(master=root, value="ยังไม่ได้เข้าสู่ระบบ"),
            login_email_var=tk.StringVar(master=root),
            login_password_var=tk.StringVar(master=root),
            register_username_var=tk.StringVar(master=root),
            register_password_var=tk.StringVar(master=root),
            register_password_confirm_var=tk.StringVar(master=root),
            on_login=lambda: None,
            on_register=lambda: None,
            on_forgot_password=lambda: None,
            on_web_login=lambda: None,
            web_auth_enabled=True,
            web_auth_only=True,
            web_login_icon_path=icon_path,
        )
        root.geometry("440x592")
        view.frame.pack(fill="both", expand=True)
        root.deiconify()
        root.update()

        assert view._web_login_icon is not None
        assert view._web_login_button.cget("compound") == "left"
    finally:
        root.destroy()
