from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from neko_launcher.ui.components.buttons import (
    card,
    field_label,
    primary_button,
    secondary_button,
)
from neko_launcher.ui.platform.window_chrome import apply_rounded_window_shape
from neko_launcher.ui.theme import FONT_FAMILY, PALETTE


def _entry(
    parent: ctk.CTkBaseClass,
    placeholder: str,
    variable: tk.StringVar,
    *,
    show: str | None = None,
) -> ctk.CTkEntry:
    entry = ctk.CTkEntry(
        parent,
        textvariable=variable,
        placeholder_text=placeholder,
        show=show,
        height=34,
    )
    entry.pack(fill="x", padx=14, pady=(4, 0))
    return entry


class DashboardView:
    """Post-login dashboard — presentation only."""

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        root: ctk.CTk,
        *,
        account_var: tk.StringVar,
        entitlement_var: tk.StringVar,
        coupon_var: tk.StringVar,
        game_path_var: tk.StringVar,
        auto_launch_var: tk.BooleanVar,
        game_connection_var: tk.StringVar,
        proxy_connection_var: tk.StringVar,
        on_change_password: Callable[[], None],
        on_sign_out: Callable[[], None],
        on_redeem_coupon: Callable[[], None],
        on_choose_game: Callable[[], None],
        on_launch_game: Callable[[], None],
        debug_mode: bool = False,
        on_open_debug: Callable[[], None] | None = None,
    ) -> None:
        self._root = root
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")

        account = card(self.frame)
        account_header = ctk.CTkFrame(account, fg_color="transparent")
        account_header.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            account_header,
            text="พื้นที่ใช้งานของคุณ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        self._account_label = ctk.CTkLabel(
            account_header,
            textvariable=account_var,
            text_color=PALETTE.text_muted,
        )
        self._account_label.pack(side="right", pady=2)

        self._entitlement_label = ctk.CTkLabel(
            account,
            textvariable=entitlement_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
            wraplength=360,
            justify="left",
        )
        self._entitlement_label.pack(anchor="w", padx=14, pady=(2, 4))

        actions = ctk.CTkFrame(account, fg_color="transparent")
        actions.pack(fill="x", padx=10, pady=(2, 10))
        secondary_button(
            actions,
            "เปลี่ยนรหัสผ่าน",
            on_change_password,
        ).pack(side="left", padx=4)
        secondary_button(
            actions,
            "ออกจากระบบ",
            on_sign_out,
        ).pack(side="right", padx=4)

        usage = card(self.frame)
        ctk.CTkLabel(
            usage,
            text="เติมวันใช้งาน",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=14, pady=(10, 4))
        coupon_row = ctk.CTkFrame(usage, fg_color="transparent")
        coupon_row.pack(fill="x", padx=10, pady=(0, 10))
        self._coupon_entry = ctk.CTkEntry(
            coupon_row,
            textvariable=coupon_var,
            placeholder_text="NEKO-XXXXXXXX-…",
            fg_color="transparent",
            border_color=PALETTE.border,
            border_width=1,
            height=34,
        )
        self._coupon_entry.pack(fill="x", padx=4, pady=(0, 6))
        self._redeem_button = primary_button(
            coupon_row, "เติมวันจากคูปอง", on_redeem_coupon
        )
        self._redeem_button.pack(fill="x", padx=4)

        proxy = card(self.frame)
        
        proxy_header = ctk.CTkFrame(proxy, fg_color="transparent")
        proxy_header.pack(fill="x", padx=14, pady=(10, 4))
        
        ctk.CTkLabel(
            proxy_header,
            text="สถานะการเชื่อมต่อ (Connection Status)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(side="left")
        
        if debug_mode and on_open_debug:
            secondary_button(
                proxy_header,
                "DEBUG MODE",
                on_open_debug,
            ).pack(side="right")

        ctk.CTkLabel(
            proxy,
            text="ระบบจะเปิด ProxyCore อัตโนมัติเมื่อพบ pso2.exe",
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            wraplength=340,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 6))
        ctk.CTkLabel(
            proxy,
            textvariable=game_connection_var,
            text_color=PALETTE.text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(0, 3))
        ctk.CTkLabel(
            proxy,
            textvariable=proxy_connection_var,
            text_color=PALETTE.text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(0, 10))

        game = card(self.frame)
        ctk.CTkLabel(
            game,
            text="ตั้งค่าเข้าเกม (PSO2 Tweaker)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=14, pady=(10, 4))
        game_path_row = ctk.CTkFrame(game, fg_color="transparent")
        game_path_row.pack(fill="x", padx=10, pady=(0, 4))
        self._game_path_entry = ctk.CTkEntry(
            game_path_row,
            textvariable=game_path_var,
            placeholder_text="กรุณาเลือก Tweaker.exe ในเครื่องคุณ",
            fg_color="transparent",
            border_color=PALETTE.border,
            border_width=1,
            height=34,
        )
        self._game_path_entry.pack(side="left", fill="x", expand=True, padx=4)
        secondary_button(
            game_path_row,
            "เลือกไฟล์ (Browse)",
            on_choose_game,
        ).pack(side="left", padx=4)

        self._auto_launch_checkbox = ctk.CTkCheckBox(
            game,
            text="เปิด Tweaker อัตโนมัติเมื่อล็อคอินสำเร็จ",
            variable=auto_launch_var,
            text_color=PALETTE.text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            fg_color=PALETTE.primary,
            border_color=PALETTE.primary,
            hover_color=PALETTE.primary_hover,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
        )
        self._auto_launch_checkbox.pack(anchor="w", padx=14, pady=(10, 10))
        if auto_launch_var.get():
            self._auto_launch_checkbox.select()

        game_controls = ctk.CTkFrame(game, fg_color="transparent")
        game_controls.pack(fill="x", padx=10, pady=(0, 10))
        self._launch_game_button = primary_button(
            game_controls,
            "เปิดโปรแกรม PSO2 Tweaker",
            on_launch_game,
        )
        self._launch_game_button.pack(side="left", fill="x", expand=True, padx=4)
        self._launch_game_button.configure(state="disabled")

    def set_entitlement_style(self, text_color: str) -> None:
        self._entitlement_label.configure(text_color=text_color)

    def set_redeem_enabled(self, enabled: bool) -> None:
        self._redeem_button.configure(state="normal" if enabled else "disabled")

    def set_launch_enabled(self, enabled: bool) -> None:
        self._launch_game_button.configure(state="normal" if enabled else "disabled")


def open_password_dialog(
    root: ctk.CTk,
    icon_path: Any,
    new_password_var: tk.StringVar,
    new_password_confirm_var: tk.StringVar,
    error_var: tk.StringVar,
    on_change_password: Callable[[], None],
    on_close: Callable[[], None],
) -> ctk.CTkToplevel:
    """Create and show the change-password modal dialog."""
    new_password_var.set("")
    new_password_confirm_var.set("")
    error_var.set("")

    dialog = ctk.CTkToplevel(root)
    dialog_width = 400
    dialog_height = 380
    dialog.title("เปลี่ยนรหัสผ่าน")
    dialog.geometry(f"{dialog_width}x{dialog_height}")
    dialog.resizable(False, False)
    dialog.overrideredirect(True)
    dialog.configure(fg_color=PALETTE.background)
    if icon_path and icon_path.is_file():
        try:
            dialog.iconbitmap(icon_path)
        except Exception:
            pass
    dialog.transient(root)
    dialog.protocol("WM_DELETE_WINDOW", on_close)

    panel = ctk.CTkFrame(
        dialog,
        fg_color=PALETTE.card,
        border_color=PALETTE.border,
        border_width=1,
        corner_radius=16,
    )
    panel.pack(fill="both", expand=True, padx=14, pady=14)

    dialog_controls = ctk.CTkFrame(panel, fg_color="transparent")
    dialog_controls.pack(fill="x", padx=12, pady=(10, 0))
    ctk.CTkLabel(
        dialog_controls,
        text="เปลี่ยนรหัสผ่าน",
        font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
        text_color=PALETTE.primary_dark,
    ).pack(side="left", padx=6)
    secondary_button(
        dialog_controls,
        "×",
        on_close,
        width=28,
        height=24,
    ).pack(side="right")
    ctk.CTkLabel(
        panel,
        text="ตั้งรหัสผ่านใหม่อย่างน้อย 8 ตัวอักษร",
        font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        text_color=PALETTE.text_muted,
    ).pack(anchor="w", padx=18, pady=(0, 8))

    field_label(panel, "รหัสผ่านใหม่")
    new_password_entry = _entry(
        panel,
        "รหัสผ่านใหม่",
        new_password_var,
        show="●",
    )
    field_label(panel, "ยืนยันรหัสผ่านใหม่")
    new_password_confirm_entry = _entry(
        panel,
        "ยืนยันรหัสผ่านใหม่",
        new_password_confirm_var,
        show="●",
    )
    new_password_entry.bind(
        "<Return>", lambda _event: on_change_password()
    )
    new_password_confirm_entry.bind(
        "<Return>", lambda _event: on_change_password()
    )

    ctk.CTkLabel(
        panel,
        textvariable=error_var,
        text_color=PALETTE.danger,
        font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        wraplength=330,
    ).pack(padx=18, pady=(6, 0))

    buttons = ctk.CTkFrame(panel, fg_color="transparent")
    buttons.pack(fill="x", padx=14, pady=(8, 14))
    secondary_button(
        buttons,
        "ยกเลิก",
        on_close,
    ).pack(side="left", fill="x", expand=True, padx=4)
    change_password_button = primary_button(
        buttons,
        "ยืนยัน",
        on_change_password,
    )
    change_password_button.pack(
        side="left", fill="x", expand=True, padx=4
    )

    dialog.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - dialog_width) // 2
    y = root.winfo_rooty() + (root.winfo_height() - dialog_height) // 2
    dialog.geometry(
        f"{dialog_width}x{dialog_height}+{max(0, x)}+{max(0, y)}"
    )
    dialog.update_idletasks()
    apply_rounded_window_shape(dialog, radius=24)
    dialog.grab_set()
    new_password_entry.focus_set()
    return dialog
