from __future__ import annotations

import tkinter as tk
import webbrowser
from pathlib import Path
from typing import Callable

import customtkinter as ctk
from PIL import Image

from neko_launcher.ui.theme import CONTROL_RADIUS, FONT_FAMILY, PALETTE
from neko_launcher.ui.components.buttons import (
    card,
    field_label,
    icon_entry,
    primary_button,
    secondary_button,
)

WEB_LOGIN_LABEL = "ล็อคอินด้วย Neko Family Network ID"
DISCORD_HELP_URL = "https://discord.gg/fkjXW9AJ6a"


def _load_login_icon(path: Path | None) -> ctk.CTkImage | None:
    if path is None or not Path(path).is_file():
        return None
    try:
        with Image.open(path) as source:
            image = source.convert("RGBA")
        return ctk.CTkImage(image, size=(18, 18))
    except (OSError, ValueError):
        return None


def _apply_login_icon(button: ctk.CTkButton, icon: ctk.CTkImage | None) -> None:
    if icon is not None:
        button.configure(image=icon, compound="left")


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
        on_web_login: Callable[[], None] | None = None,
        on_cancel_web_login: Callable[[], None] | None = None,
        web_auth_enabled: bool = False,
        web_auth_only: bool = False,
        web_login_icon_path: Path | None = None,
    ) -> None:
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._on_cancel_web_login = on_cancel_web_login
        self._web_login_icon = _load_login_icon(web_login_icon_path)
        self._progress_panel: ctk.CTkFrame | None = None
        self._progress_text: ctk.CTkLabel | None = None
        self._progress_bar: ctk.CTkProgressBar | None = None
        self._cancel_button: ctk.CTkButton | None = None
        self._progress_pack_kwargs: dict[str, object] = {}
        self._progress_visible = False
        self._progress_overlay = False
        self._progress_host: ctk.CTkFrame | None = None
        self._help_label: ctk.CTkLabel | None = None
        self._web_auth_only = bool(
            web_auth_only and web_auth_enabled and on_web_login is not None
        )
        intro = card(self.frame)
        intro.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        top_row = ctk.CTkFrame(intro, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(6, 0))

        layout = intro
        content = intro
        if self._web_auth_only:
            # Keep the status row pinned at the top; center only the content.
            # The full-height layout also gives the floating progress panel
            # room below the content without reflowing the login controls.
            layout = ctk.CTkFrame(intro, fg_color="transparent")
            layout.pack(fill="both", expand=True, padx=18, pady=(0, 8))
            content = ctk.CTkFrame(layout, fg_color="transparent")
            content.pack(fill="x", expand=True, pady=(0, 48))

        self._auth_hint = ctk.CTkLabel(
            top_row,
            text="ยังไม่ได้เข้าสู่ระบบ",
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

        title_frame = ctk.CTkFrame(content, fg_color="transparent")
        title_frame.pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(
            title_frame,
            text=(
                WEB_LOGIN_LABEL
                if self._web_auth_only
                else "เข้าสู่ระบบและสมัครสมาชิก"
            ),
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="center")

        self._web_login_button: ctk.CTkButton | None = None
        self._login_button: ctk.CTkButton | None = None
        self._register_button: ctk.CTkButton | None = None
        if self._web_auth_only:
            self._build_web_only(
                content,
                on_web_login,
                overlay_host=layout,
            )
            return

        self._tab_controls = ctk.CTkFrame(
            intro,
            fg_color=PALETTE.surface,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=12,
            height=38,
        )
        self._tab_controls.pack(fill="x", padx=20, pady=(6, 6))
        self._tab_controls.pack_propagate(False)

        self._login_tab_btn = ctk.CTkButton(
            self._tab_controls,
            text="เข้าสู่ระบบ",
            fg_color=PALETTE.primary,
            text_color=PALETTE.on_primary,
            hover_color=PALETTE.primary_hover,
            corner_radius=10,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=lambda: self._switch_tab("login"),
        )
        self._login_tab_btn.pack(side="left", padx=3, pady=3, expand=True, fill="both")

        self._register_tab_btn = ctk.CTkButton(
            self._tab_controls,
            text="สมัครสมาชิก",
            fg_color="transparent",
            text_color=PALETTE.text_muted,
            hover_color=PALETTE.surface_accent,
            corner_radius=10,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=lambda: self._switch_tab("register"),
        )
        self._register_tab_btn.pack(side="left", padx=3, pady=3, expand=True, fill="both")

        self._login_frame = ctk.CTkFrame(intro, fg_color="transparent")
        self._register_frame = ctk.CTkFrame(intro, fg_color="transparent")

        # Login Frame
        login = self._login_frame
        if web_auth_enabled and on_web_login is not None:
            self._web_login_button = primary_button(
                login,
                WEB_LOGIN_LABEL,
                on_web_login,
            )
            self._web_login_button.configure(
                height=32,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            )
            _apply_login_icon(self._web_login_button, self._web_login_icon)
            self._web_login_button.pack(fill="x", padx=14, pady=(6, 0))
            ctk.CTkLabel(
                login,
                text="หรือใช้บัญชีเดิม",
                text_color=PALETTE.text_muted,
                font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            ).pack(pady=(2, 0))
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
        self._build_progress_panel(login, padx=14, side="bottom")

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
        self._register_action = ctk.CTkFrame(
            register, fg_color="transparent", height=76
        )
        self._register_action.pack(fill="x", padx=14, pady=(16, 12))
        self._register_action.pack_propagate(False)
        self._register_button = primary_button(
            self._register_action, "สร้างบัญชี ➔", on_register
        )
        self._register_button.configure(
            height=56,
            corner_radius=12,
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
        )
        self._register_button.pack(fill="both", expand=True)

        self._switch_tab("login")

    def _build_web_only(
        self,
        parent: ctk.CTkFrame,
        on_web_login: Callable[[], None],
        *,
        overlay_host: ctk.CTkFrame,
    ) -> None:
        body = ctk.CTkFrame(parent, fg_color="transparent")
        body.pack(fill="x", pady=(14, 18))
        ctk.CTkLabel(
            body,
            text="ยินดีต้อนรับสู่ Neko Family Proxy",
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            wraplength=360,
            justify="center",
        ).pack(anchor="center", pady=(8, 14))
        self._web_login_button = primary_button(
            body,
            WEB_LOGIN_LABEL,
            on_web_login,
        )
        self._web_login_button.configure(
            height=44,
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
        )
        _apply_login_icon(self._web_login_button, self._web_login_icon)
        self._web_login_button.pack(fill="x", padx=4, pady=(0, 10))
        self._help_label = ctk.CTkLabel(
            body,
            text=f"มีปัญหาการใช้งานติดต่อ ที่ดิสคอส {DISCORD_HELP_URL}",
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            wraplength=360,
            justify="center",
            cursor="hand2",
        )
        self._help_label.pack(anchor="center")
        self._help_label.bind(
            "<Button-1>", lambda _event: webbrowser.open(DISCORD_HELP_URL)
        )
        self._build_progress_panel(
            body,
            padx=4,
            overlay=True,
            overlay_host=overlay_host,
        )

    def _build_progress_panel(
        self,
        parent: ctk.CTkBaseClass,
        *,
        padx: int,
        side: str = "top",
        overlay: bool = False,
        overlay_host: ctk.CTkFrame | None = None,
    ) -> None:
        panel_parent = (
            overlay_host if overlay and overlay_host is not None else parent
        )
        panel = ctk.CTkFrame(
            panel_parent,
            fg_color=PALETTE.surface_accent,
            border_color=PALETTE.border_accent,
            border_width=1,
            corner_radius=CONTROL_RADIUS,
        )
        self._progress_panel = panel
        self._progress_overlay = bool(overlay)
        self._progress_host = panel_parent if overlay else None
        self._progress_pack_kwargs = {
            "side": side,
            "fill": "x",
            "padx": padx,
            "pady": (10, 2),
        }

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            row,
            text="◐",
            text_color=PALETTE.primary,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
        ).pack(side="left", padx=(0, 6))
        self._progress_text = ctk.CTkLabel(
            row,
            text="กำลังเข้าสู่ระบบ",
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            anchor="w",
            wraplength=300,
            justify="left",
        )
        self._progress_text.pack(side="left", fill="x", expand=True)

        self._progress_bar = ctk.CTkProgressBar(
            panel,
            mode="indeterminate",
            height=4,
            fg_color=PALETTE.card,
            progress_color=PALETTE.primary,
        )
        self._progress_bar.pack(fill="x", padx=12, pady=(2, 8))

        if self._on_cancel_web_login is not None:
            self._cancel_button = secondary_button(
                panel,
                "ยกเลิกการเข้าสู่ระบบ",
                self._on_cancel_web_login,
                height=28,
            )
            self._cancel_button.pack(padx=12, pady=(0, 10))

    def set_auth_progress(self, text: str | None) -> None:
        """Show the current sign-in step, or hide the panel when it is None."""
        panel = self._progress_panel
        if panel is None:
            return
        if text is None:
            if self._progress_bar is not None:
                self._progress_bar.stop()
            if self._progress_overlay:
                panel.place_forget()
            else:
                panel.pack_forget()
            self._progress_visible = False
            return
        if self._progress_text is not None:
            self._progress_text.configure(text=text)
        if self._progress_overlay:
            self.frame.update_idletasks()
            host = self._progress_host
            help_label = self._help_label
            if host is not None and help_label is not None:
                top = (
                    help_label.winfo_rooty()
                    + help_label.winfo_height()
                    + 10
                    - host.winfo_rooty()
                )
                bottom_margin = 8
                max_top = max(
                    bottom_margin,
                    host.winfo_height() - panel.winfo_reqheight() - bottom_margin,
                )
                top = max(bottom_margin, min(top, max_top))
                panel.place(
                    in_=host,
                    x=0,
                    y=top,
                    relwidth=1.0,
                )
            self._progress_visible = True
        elif not self._progress_visible:
            panel.pack(**self._progress_pack_kwargs)
            self._progress_visible = True
        if self._progress_bar is not None:
            self._progress_bar.start()

    def set_status_signed_in(self, signed_in: bool) -> None:
        self._status_badge.configure(
            text_color=PALETTE.success if signed_in else PALETTE.text_muted,
        )

    def set_actions_enabled(self, *, signed_in: bool, authenticating: bool) -> None:
        state = "normal" if not signed_in and not authenticating else "disabled"
        for button in (
            self._login_button,
            self._register_button,
            self._web_login_button,
        ):
            if button is not None:
                button.configure(state=state)

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
                hover_color=PALETTE.surface_accent,
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
                hover_color=PALETTE.surface_accent,
            )
            self._login_frame.pack_forget()
            self._register_frame.pack(fill="both", expand=True)
