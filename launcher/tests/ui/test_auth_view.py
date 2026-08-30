from __future__ import annotations

import tkinter as tk

import customtkinter as ctk
import pytest

from neko_launcher.ui.views.auth_view import AuthView


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
