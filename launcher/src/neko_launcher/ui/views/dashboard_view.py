from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

import customtkinter as ctk

from neko_launcher.ui.theme import FONT_FAMILY, PALETTE
from neko_launcher.ui.components.buttons import (
    card,
    field_label,
    primary_button,
    secondary_button,
)
from neko_launcher.ui.platform.window_chrome import apply_rounded_window_shape


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
    """Post-login customer dashboard — pure read-only status presentation."""

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        root: ctk.CTk,
        *,
        status_title_var: tk.StringVar,
        status_subtitle_var: tk.StringVar,
        account_var: tk.StringVar,
        entitlement_days_var: tk.StringVar,
        entitlement_expiry_var: tk.StringVar,
        download_speed_var: tk.StringVar,
        upload_speed_var: tk.StringVar,
        session_duration_var: tk.StringVar,
    ) -> None:
        self._root = root
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")

        # --------------------------------------------------------------
        # 1. Connection Hero Card
        # --------------------------------------------------------------
        hero_card = card(self.frame)
        hero_inner = ctk.CTkFrame(hero_card, fg_color="transparent")
        hero_inner.pack(fill="x", padx=16, pady=(14, 14))

        self._status_pill = ctk.CTkFrame(
            hero_inner,
            fg_color=PALETTE.success_surface,
            border_color=PALETTE.success,
            border_width=1,
            corner_radius=16,
            height=34,
        )
        self._status_pill.pack(anchor="center", pady=(0, 6))

        self._status_title_label = ctk.CTkLabel(
            self._status_pill,
            textvariable=status_title_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.success,
            padx=16,
            pady=4,
        )
        self._status_title_label.pack(anchor="center")

        self._status_subtitle_label = ctk.CTkLabel(
            hero_inner,
            textvariable=status_subtitle_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
            wraplength=380,
            justify="center",
        )
        self._status_subtitle_label.pack(anchor="center")

        # --------------------------------------------------------------
        # 2. Membership Summary Card
        # --------------------------------------------------------------
        membership_card = card(self.frame)
        membership_inner = ctk.CTkFrame(membership_card, fg_color="transparent")
        membership_inner.pack(fill="x", padx=16, pady=(12, 12))

        header_row = ctk.CTkFrame(membership_inner, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            header_row,
            text="ข้อมูลสมาชิก (Membership)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(side="left")

        # Status badge (Truthful plan/state authority: ACTIVE)
        self._tier_badge = ctk.CTkLabel(
            header_row,
            text="ACTIVE",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            text_color=PALETTE.on_primary,
            fg_color=PALETTE.primary,
            corner_radius=10,
            padx=8,
            pady=2,
        )
        self._tier_badge.pack(side="right")

        user_row = ctk.CTkFrame(membership_inner, fg_color="transparent")
        user_row.pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(
            user_row,
            text="👤 ชื่อผู้ใช้:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            user_row,
            textvariable=account_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left", padx=(6, 0))

        days_row = ctk.CTkFrame(membership_inner, fg_color="transparent")
        days_row.pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(
            days_row,
            text="⏳ วันคงเหลือ:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        self._entitlement_days_label = ctk.CTkLabel(
            days_row,
            textvariable=entitlement_days_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        )
        self._entitlement_days_label.pack(side="left", padx=(6, 0))

        expiry_row = ctk.CTkFrame(membership_inner, fg_color="transparent")
        expiry_row.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(
            expiry_row,
            text="📅 วันหมดอายุ:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            expiry_row,
            textvariable=entitlement_expiry_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left", padx=(6, 0))

        # --------------------------------------------------------------
        # 3. Network Summary Card
        # --------------------------------------------------------------
        network_card = card(self.frame)
        network_inner = ctk.CTkFrame(network_card, fg_color="transparent")
        network_inner.pack(fill="x", padx=16, pady=(12, 12))

        ctk.CTkLabel(
            network_inner,
            text="สถิติเครือข่าย (Network)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", pady=(0, 6))

        dl_row = ctk.CTkFrame(network_inner, fg_color="transparent")
        dl_row.pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(
            dl_row,
            text="▼ ดาวน์โหลด:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            dl_row,
            textvariable=download_speed_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.primary,
        ).pack(side="left", padx=(6, 0))

        ul_row = ctk.CTkFrame(network_inner, fg_color="transparent")
        ul_row.pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(
            ul_row,
            text="▲ อัปโหลด:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            ul_row,
            textvariable=upload_speed_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left", padx=(6, 0))

        uptime_row = ctk.CTkFrame(network_inner, fg_color="transparent")
        uptime_row.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(
            uptime_row,
            text="⏱ เวลาเชื่อมต่อ:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            uptime_row,
            textvariable=session_duration_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left", padx=(6, 0))

        # --------------------------------------------------------------
        # 4. Passive Guidance Card
        # --------------------------------------------------------------
        guidance_card = card(self.frame)
        guidance_inner = ctk.CTkFrame(guidance_card, fg_color="transparent")
        guidance_inner.pack(fill="x", padx=16, pady=(10, 10))

        ctk.CTkLabel(
            guidance_inner,
            text="💡 ระบบจะเชื่อมต่อ Tokyo Proxy อัตโนมัติเมื่อเปิดเกม PSO2",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
            wraplength=380,
            justify="center",
        ).pack(anchor="center")

    def update_status_role(self, role: str) -> None:
        """Update the visual color theme of the hero status pill."""
        if role == "success":
            self._status_pill.configure(
                fg_color=PALETTE.success_surface,
                border_color=PALETTE.success,
            )
            self._status_title_label.configure(text_color=PALETTE.success)
        elif role == "warning":
            self._status_pill.configure(
                fg_color=PALETTE.surface,
                border_color=PALETTE.warning,
            )
            self._status_title_label.configure(text_color=PALETTE.warning)
        elif role == "danger":
            self._status_pill.configure(
                fg_color=PALETTE.danger_surface,
                border_color=PALETTE.danger,
            )
            self._status_title_label.configure(text_color=PALETTE.danger)
        else:
            self._status_pill.configure(
                fg_color=PALETTE.surface,
                border_color=PALETTE.border,
            )
            self._status_title_label.configure(text_color=PALETTE.text_muted)

    def set_entitlement_style(self, text_color: str) -> None:
        self._entitlement_days_label.configure(text_color=text_color)


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
