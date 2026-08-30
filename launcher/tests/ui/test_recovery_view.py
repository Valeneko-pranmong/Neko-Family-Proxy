from __future__ import annotations

from pathlib import Path
import tkinter as tk

import customtkinter as ctk
import pytest

from neko_launcher.ui.views.recovery_view import RecoveryView


def test_recovery_view_has_always_visible_top_back_action() -> None:
    source = Path(__file__).parents[2].joinpath(
        "src", "neko_launcher", "ui", "views", "recovery_view.py"
    ).read_text(encoding="utf-8")
    assert 'self._back_button = secondary_button(' in source
    assert '"← กลับไปหน้าเข้าสู่ระบบ"' in source
    assert "panel.configure(height=540)" not in source
    assert "panel.pack_propagate(False)" not in source


def test_recovery_back_button_invokes_cancel() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")
    try:
        calls: list[str] = []
        view = RecoveryView(
            root,
            username_var=tk.StringVar(master=root),
            recovery_code_var=tk.StringVar(master=root),
            new_password_var=tk.StringVar(master=root),
            confirm_password_var=tk.StringVar(master=root),
            on_verify=lambda: None,
            on_change_password=lambda: None,
            on_cancel=lambda: calls.append("cancel"),
        )
        view._back_button.invoke()
        assert calls == ["cancel"]
    finally:
        root.destroy()
