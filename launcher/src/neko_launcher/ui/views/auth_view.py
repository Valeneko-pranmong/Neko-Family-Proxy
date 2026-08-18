from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from neko_launcher.ui.theme import FONT_FAMILY, PALETTE
from neko_launcher.ui.components.buttons import (
    card,
    field_label,
    icon_entry,
    primary_button,
)


class AuthView:
    """Login and registration view — presentation only."""

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        *,
        status_var: tk.StringVar,
        login_email_var: tk.StringVar,
        login_password_var: tk.StringVar,
        register_username_var: tk.StringVar,
        register_password_var: tk.StringVar,
        register_password_confirm_var: tk.StringVar,
        on_login: Callable[[], None],
        on_register: Callable[[], None],
        on_forgot_password: Callable[[], None],
    ) -> None:
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        intro = card(self.frame)
        intro.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        top_row = ctk.CTkFrame(intro, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(6, 0))

        self._auth_hint = ctk.CTkLabel(
            top_row,
            text="เข้าสู่ระบบเพื่อเริ่มใช้งาน",
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        )
        self._auth_hint.pack(side="left")

        self._status_badge = ctk.CTkLabel(
            top_row,
            textvariable=status_var,
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        )
        self._status_badge.pack(side="right")

        title_frame = ctk.CTkFrame(intro, fg_color="transparent")
        title_frame.pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(
            title_frame,
            text="เข้าสู่ระบบและสมัครสมาชิก",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="center")

        self._tab_controls = ctk.CTkFrame(
            intro,
            fg_color="#F3F4F6",
            corner_radius=10,
            height=36,
        )
        self._tab_controls.pack(fill="x", padx=20, pady=(6, 6))
        self._tab_controls.pack_propagate(False)

        self._login_tab_btn = ctk.CTkButton(
            self._tab_controls,
            text="เข้าสู่ระบบ",
            fg_color=PALETTE.primary,
            text_color=PALETTE.on_primary,
            hover_color=PALETTE.primary_hover,
            corner_radius=8,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=lambda: self._switch_tab("login"),
        )
        self._login_tab_btn.pack(side="left", padx=3, pady=3, expand=True, fill="both")

        self._register_tab_btn = ctk.CTkButton(
            self._tab_controls,
            text="สมัครสมาชิก",
            fg_color="transparent",
            text_color=PALETTE.text_muted,
            hover_color="#E5E7EB",
            corner_radius=8,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=lambda: self._switch_tab("register"),
        )
        self._register_tab_btn.pack(side="left", padx=3, pady=3, expand=True, fill="both")

        self._login_frame = ctk.CTkFrame(intro, fg_color="transparent")
        self._register_frame = ctk.CTkFrame(intro, fg_color="transparent")

        # Login Frame
        login = self._login_frame
        field_label(login, "ชื่อผู้ใช้")
        self._login_email_entry = icon_entry(
            login, "👤", "กรอกชื่อผู้ใช้", login_email_var
        )
        field_label(login, "รหัสผ่าน")
        self._login_password_entry = icon_entry(
            login, "🔒", "กรอกรหัสผ่าน", login_password_var, show="●", right_icon="👁"
        )
        self._login_email_entry.bind("<Return>", lambda _event: on_login())
        self._login_password_entry.bind("<Return>", lambda _event: on_login())

        options_row = ctk.CTkFrame(login, fg_color="transparent")
        options_row.pack(fill="x", padx=14, pady=(8, 8))

        self._remember_me = ctk.CTkCheckBox(
            options_row,
            text="จำฉันไว้ในระบบ",
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color=PALETTE.primary,
            border_color=PALETTE.primary,
            hover_color=PALETTE.primary_hover,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
        )
        self._remember_me.pack(side="left")
        self._remember_me.select()

        forgot_pw = ctk.CTkLabel(
            options_row,
            text="ลืมรหัสผ่าน? ใช้รหัสกู้บัญชี",
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            cursor="hand2",
        )
        forgot_pw.pack(side="right", pady=(2, 0))
        forgot_pw.bind("<Button-1>", lambda e: on_forgot_password())

        self._login_button = primary_button(login, "เข้าสู่ระบบ ➔", on_login)
        self._login_button.pack(side="bottom", fill="x", padx=14, pady=(10, 14))

        # Register Frame
        register = self._register_frame
        field_label(register, "ชื่อผู้ใช้")
        self._register_email_entry = icon_entry(
            register, "👤", "กรอกชื่อผู้ใช้", register_username_var
        )
        field_label(register, "รหัสผ่าน (อย่างน้อย 8 ตัวอักษร)")
        self._register_password_entry = icon_entry(
            register, "🔒", "กรอกรหัสผ่าน", register_password_var, show="●", right_icon="👁"
        )
        ctk.CTkLabel(
            register,
            text="ใช้ตัวอักษรอย่างน้อย 8 ตัวอักษร",
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        ).pack(anchor="w", padx=16, pady=(2, 0))
        field_label(register, "ยืนยันรหัสผ่าน")
        self._register_password_confirm_entry = icon_entry(
            register, "🔒", "กรอกรหัสผ่านอีกครั้ง", register_password_confirm_var, show="●", right_icon="👁"
        )
        self._register_email_entry.bind("<Return>", lambda _event: on_register())
        self._register_password_entry.bind("<Return>", lambda _event: on_register())
        self._register_password_confirm_entry.bind(
            "<Return>", lambda _event: on_register()
        )
        self._register_button = primary_button(register, "สร้างบัญชี ➔", on_register)
        self._register_button.pack(side="bottom", fill="x", padx=14, pady=(10, 14))

        self._switch_tab("login")

    def set_status_signed_in(self, signed_in: bool) -> None:
        self._status_badge.configure(
            text_color=PALETTE.success if signed_in else PALETTE.text_muted,
        )

    def set_actions_enabled(self, *, signed_in: bool, authenticating: bool) -> None:
        state = "normal" if not signed_in and not authenticating else "disabled"
        self._login_button.configure(state=state)
        self._register_button.configure(state=state)

    def _switch_tab(self, tab: str) -> None:
        if tab == "login":
            self._login_tab_btn.configure(
                fg_color=PALETTE.primary,
                text_color=PALETTE.on_primary,
                hover_color=PALETTE.primary_hover,
            )
            self._register_tab_btn.configure(
                fg_color="transparent",
                text_color=PALETTE.text_muted,
                hover_color="#E5E7EB",
            )
            self._register_frame.pack_forget()
            self._login_frame.pack(fill="both", expand=True)
        else:
            self._register_tab_btn.configure(
                fg_color=PALETTE.primary,
                text_color=PALETTE.on_primary,
                hover_color=PALETTE.primary_hover,
            )
            self._login_tab_btn.configure(
                fg_color="transparent",
                text_color=PALETTE.text_muted,
                hover_color="#E5E7EB",
            )
            self._login_frame.pack_forget()
            self._register_frame.pack(fill="both", expand=True)
