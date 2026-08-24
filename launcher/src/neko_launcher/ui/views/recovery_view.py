from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from neko_launcher.ui.components.buttons import (
    card,
    field_label,
    icon_entry,
    primary_button,
    secondary_button,
)
from neko_launcher.ui.theme import FONT_FAMILY, PALETTE


class RecoveryView:
    """Minimal recovery-only UI; it never contains product or session actions."""

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        *,
        username_var: tk.StringVar,
        recovery_code_var: tk.StringVar,
        new_password_var: tk.StringVar,
        confirm_password_var: tk.StringVar,
        on_verify: Callable[[], None],
        on_change_password: Callable[[], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        panel = card(self.frame)
        panel.configure(height=540)
        panel.pack_propagate(False)

        ctk.CTkLabel(
            panel,
            text="กู้บัญชี",
            font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
            text_color=PALETTE.text,
        ).pack(pady=(28, 4))
        ctk.CTkLabel(
            panel,
            text="ใช้เฉพาะรหัสกู้บัญชีที่ได้รับจากผู้ดูแล",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(pady=(0, 18))

        self._code_frame = ctk.CTkFrame(panel, fg_color="transparent")
        field_label(self._code_frame, "ชื่อผู้ใช้")
        username_entry = icon_entry(
            self._code_frame, "👤", "กรอกชื่อผู้ใช้", username_var
        )
        field_label(self._code_frame, "รหัสกู้บัญชี")
        code_entry = icon_entry(
            self._code_frame,
            "🔒",
            "กรอกรหัสกู้บัญชี",
            recovery_code_var,
            show="●",
        )
        username_entry.bind("<Return>", lambda _event: on_verify())
        code_entry.bind("<Return>", lambda _event: on_verify())
        self._verify_button = primary_button(
            self._code_frame, "ดำเนินการต่อ ➔", on_verify
        )
        self._verify_button.pack(fill="x", padx=14, pady=(20, 8))
        secondary_button(
            self._code_frame, "กลับไปหน้าเข้าสู่ระบบ", on_cancel
        ).pack(fill="x", padx=14, pady=(0, 12))

        self._password_frame = ctk.CTkFrame(panel, fg_color="transparent")
        ctk.CTkLabel(
            self._password_frame,
            text="ตั้งรหัสผ่านใหม่",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(pady=(2, 10))
        field_label(self._password_frame, "รหัสผ่านใหม่")
        password_entry = icon_entry(
            self._password_frame,
            "🔒",
            "12-128 ตัวอักษร",
            new_password_var,
            show="●", right_icon="👁",
        )
        field_label(self._password_frame, "ยืนยันรหัสผ่านใหม่")
        confirm_entry = icon_entry(
            self._password_frame,
            "🔒",
            "กรอกรหัสผ่านอีกครั้ง",
            confirm_password_var,
            show="●", right_icon="👁",
        )
        ctk.CTkLabel(
            self._password_frame,
            text="ต้องมีตัวพิมพ์ใหญ่ ตัวพิมพ์เล็ก ตัวเลข และสัญลักษณ์",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(pady=(4, 8))
        password_entry.bind("<Return>", lambda _event: on_change_password())
        confirm_entry.bind("<Return>", lambda _event: on_change_password())
        self._change_button = primary_button(
            self._password_frame, "เปลี่ยนรหัสผ่าน", on_change_password
        )
        self._change_button.pack(fill="x", padx=14, pady=(14, 8))
        secondary_button(self._password_frame, "ยกเลิก", on_cancel).pack(
            fill="x", padx=14, pady=(0, 12)
        )
        self.show_code_entry()

    def show_code_entry(self) -> None:
        self._password_frame.pack_forget()
        self._code_frame.pack(fill="both", expand=True, padx=20, pady=8)

    def show_password_change(self) -> None:
        self._code_frame.pack_forget()
        self._password_frame.pack(fill="both", expand=True, padx=20, pady=8)

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._verify_button.configure(state=state)
        self._change_button.configure(state=state)
