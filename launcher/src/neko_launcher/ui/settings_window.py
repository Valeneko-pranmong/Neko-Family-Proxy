from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
import tkinter as tk

import customtkinter as ctk

from neko_launcher import __version__
from neko_launcher.ui.theme import FONT_FAMILY, PALETTE
from neko_launcher.ui.components.buttons import (
    card,
    secondary_button,
)
from neko_launcher.ui.platform.window_chrome import (
    apply_rounded_window_shape,
    style_native_title_bar,
    WindowDragHandler,
)


def customer_connection_status(technical_status: str) -> str:
    """Map an internal connection status to customer-safe presentation."""
    normalized = technical_status.strip()
    if "ไม่สำเร็จ" in normalized or "ล้มเหลว" in normalized:
        return "ไม่สามารถเชื่อมต่อได้"
    if "ทำงานแล้ว" in normalized or "เชื่อมต่อแล้ว" in normalized:
        return "เชื่อมต่อแล้ว"
    if any(
        term in normalized
        for term in ("กำลังเริ่ม", "กำลังหยุด", "กำลังเชื่อมต่อ")
    ):
        return "กำลังเชื่อมต่อ"
    if "ยังไม่ทำงาน" in normalized or "รอการเชื่อมต่อ" in normalized:
        return "ยังไม่ทำงาน"
    return "ไม่สามารถเชื่อมต่อได้"


class SettingsWindow(ctk.CTkToplevel):
    """Standalone, single-instance Settings top-level window."""

    CATEGORIES = [
        ("general", "การตั้งค่าทั่วไป"),
        ("account", "บัญชีผู้ใช้"),
        ("subscription", "สมาชิก"),
        ("pso2", "PSO2"),
        ("tweaker", "PSO2 Tweaker"),
        ("connection", "การเชื่อมต่อ"),
        ("appearance", "การแสดงผล"),
        ("notifications", "การแจ้งเตือน"),
        ("diagnostics", "การวินิจฉัย"),
        ("about", "เกี่ยวกับ"),
    ]

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        *,
        icon_path: Path | None = None,
        account_var: tk.StringVar | None = None,
        entitlement_days_var: tk.StringVar | None = None,
        entitlement_expiry_var: tk.StringVar | None = None,
        game_path_var: tk.StringVar | None = None,
        auto_launch_var: tk.BooleanVar | None = None,
        proxy_connection_var: tk.StringVar | None = None,
        diagnostics: Any = None,
        debug_mode: bool = False,
        debug_log_dir: Path | None = None,
        on_close: Callable[[], None] | None = None,
        on_change_password: Callable[[], None] | None = None,
        on_sign_out: Callable[[], None] | None = None,
        on_redeem_coupon: Callable[[], None] | None = None,
        on_choose_game: Callable[[], None] | None = None,
        on_launch_game: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_close_callback = on_close
        self._account_var = account_var or tk.StringVar(value="")
        self._entitlement_days_var = entitlement_days_var or tk.StringVar(value="")
        self._entitlement_expiry_var = entitlement_expiry_var or tk.StringVar(value="")
        self._game_path_var = game_path_var or tk.StringVar(value="")
        self._auto_launch_var = auto_launch_var or tk.BooleanVar(value=True)
        self._proxy_connection_var = proxy_connection_var or tk.StringVar(value="พร้อมใช้งาน")
        self._customer_connection_var = tk.StringVar(
            value=customer_connection_status(self._proxy_connection_var.get())
        )
        self._proxy_connection_trace_id = self._proxy_connection_var.trace_add(
            "write", self._update_customer_connection_status
        )
        self._diagnostics = diagnostics
        self._debug_mode = debug_mode
        self._debug_log_dir = debug_log_dir
        self._on_change_password = on_change_password
        self._on_sign_out = on_sign_out
        self._on_redeem_coupon = on_redeem_coupon
        self._on_choose_game = on_choose_game
        self._on_launch_game = on_launch_game

        self.title("การตั้งค่า — Neko Family Proxy")
        window_width = 880
        window_height = 600
        self.geometry(f"{window_width}x{window_height}")
        self.resizable(False, False)
        self.configure(fg_color=PALETTE.background)

        if icon_path and icon_path.is_file():
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.protocol("WM_DELETE_WINDOW", self.close)

        # Center window over parent if possible
        try:
            parent_root = parent.winfo_toplevel()
            px = parent_root.winfo_rootx() + (parent_root.winfo_width() - window_width) // 2
            py = parent_root.winfo_rooty() + (parent_root.winfo_height() - window_height) // 2
            self.geometry(f"{window_width}x{window_height}+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass

        self._build_layout()
        style_native_title_bar(self, PALETTE)
        apply_rounded_window_shape(self, radius=20)

    def _build_layout(self) -> None:
        shell = ctk.CTkFrame(
            self,
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=14,
        )
        shell.pack(fill="both", expand=True, padx=8, pady=8)

        # Header bar
        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(10, 6))

        ctk.CTkLabel(
            header,
            text="⚙ การตั้งค่า",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")

        self._drag_handler = WindowDragHandler(self)
        self._drag_handler.bind_to(header)

        # Body container: Left Sidebar + Right Content
        body = ctk.CTkFrame(shell, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # --------------------------------------------------------------
        # Left Navigation Sidebar
        # --------------------------------------------------------------
        self._sidebar = ctk.CTkFrame(
            body,
            fg_color=PALETTE.surface,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=10,
            width=220,
        )
        self._sidebar.pack(side="left", fill="y", padx=(0, 10), pady=0)
        self._sidebar.pack_propagate(False)

        # Search bar
        self._search_entry = ctk.CTkEntry(
            self._sidebar,
            placeholder_text="ค้นหาการตั้งค่า...",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=1,
            height=32,
            corner_radius=6,
        )
        self._search_entry.pack(fill="x", padx=8, pady=(8, 8))
        self._search_entry.bind("<KeyRelease>", self._filter_categories)

        # Nav Buttons list
        self._nav_container = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        self._nav_container.pack(fill="both", expand=True, padx=4, pady=(0, 6))

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, title in self.CATEGORIES:
            btn = ctk.CTkButton(
                self._nav_container,
                text=title,
                anchor="w",
                fg_color="transparent",
                text_color=PALETTE.text,
                hover_color="#F3F4F6",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                height=34,
                corner_radius=6,
                command=lambda k=key: self.select_category(k),
            )
            btn.pack(fill="x", pady=1)
            self._nav_buttons[key] = btn

        # --------------------------------------------------------------
        # Right Page Content Area
        # --------------------------------------------------------------
        self._content_area = ctk.CTkFrame(
            body,
            fg_color="transparent",
        )
        self._content_area.pack(side="left", fill="both", expand=True)

        self._pages: dict[str, ctk.CTkFrame] = {}
        self._init_pages()
        self.select_category("general")

    def _init_pages(self) -> None:
        self._pages["general"] = self._create_general_page()
        self._pages["account"] = self._create_account_page()
        self._pages["subscription"] = self._create_subscription_page()
        self._pages["pso2"] = self._create_pso2_page()
        self._pages["tweaker"] = self._create_tweaker_page()
        self._pages["connection"] = self._create_connection_page()
        self._pages["appearance"] = self._create_appearance_page()
        self._pages["notifications"] = self._create_notifications_page()
        self._pages["diagnostics"] = self._create_diagnostics_page()
        self._pages["about"] = self._create_about_page()

    def select_category(self, key: str) -> None:
        if key not in self._pages:
            return
        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(
                    fg_color=PALETTE.primary,
                    text_color=PALETTE.on_primary,
                    hover_color=PALETTE.primary_hover,
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=PALETTE.text,
                    hover_color="#F3F4F6",
                )
        for page in self._pages.values():
            page.pack_forget()
        self._pages[key].pack(fill="both", expand=True)

    def _filter_categories(self, *_args: Any) -> None:
        query = self._search_entry.get().strip().lower()
        for key, title in self.CATEGORIES:
            btn = self._nav_buttons[key]
            if not query or query in title.lower() or query in key.lower():
                btn.pack(fill="x", pady=1)
            else:
                btn.pack_forget()

    # ------------------------------------------------------------------
    # Page Builders (B1.1 Foundation)
    # ------------------------------------------------------------------
    def _create_general_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="การตั้งค่าทั่วไป",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        item1 = ctk.CTkFrame(c, fg_color="transparent")
        item1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            item1,
            text="การเชื่อมต่ออัตโนมัติ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            item1,
            text="เปิดใช้งาน (เมื่อพบ pso2.exe)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        ).pack(side="right")

        item2 = ctk.CTkFrame(c, fg_color="transparent")
        item2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            item2,
            text="ย่อเข้า System Tray",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            item2,
            text="เปิดใช้งาน",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="right")
        return page

    def _create_account_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="บัญชีผู้ใช้",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row1,
            text="ชื่อผู้ใช้",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            textvariable=self._account_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row2,
            text="สถานะบัญชี",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row2,
            text="ปกติ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        ).pack(side="right")
        return page

    def _create_subscription_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="สมาชิก",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row1,
            text="สถานะสมาชิก",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            text="ใช้งานได้",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        ).pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row2,
            text="วันคงเหลือ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row2,
            textvariable=self._entitlement_days_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        ).pack(side="right")

        row3 = ctk.CTkFrame(c, fg_color="transparent")
        row3.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row3,
            text="วันหมดอายุ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row3,
            textvariable=self._entitlement_expiry_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="right")
        return page

    def _create_pso2_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="PSO2",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row1,
            text="ตำแหน่งไฟล์เกม (pso2.exe)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            textvariable=self._game_path_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row2,
            text="การตรวจจับเกมอัตโนมัติ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row2,
            text="เปิดใช้งาน",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        ).pack(side="right")
        return page

    def _create_tweaker_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="PSO2 Tweaker",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row1,
            text="ตำแหน่งโปรแกรม Tweaker",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            textvariable=self._game_path_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(side="right")
        return page

    def _create_connection_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="การเชื่อมต่อ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row1,
            text="ภูมิภาค",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            text="Japan (Tokyo)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.primary,
        ).pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row2,
            text="โหมด",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row2,
            text="อัตโนมัติ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        ).pack(side="right")
        return page

    def _create_appearance_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="การแสดงผล",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row1,
            text="ธีมสี",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            text="Neko Pink (Light Mode)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.primary,
        ).pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row2,
            text="รูปแบบตัวอักษร",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row2,
            text=f"{FONT_FAMILY} (Bundled)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="right")
        return page

    def _create_notifications_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="การแจ้งเตือน",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row1,
            text="การแจ้งเตือนในโปรแกรม",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            text="เปิดใช้งาน",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        ).pack(side="right")
        return page

    def _create_diagnostics_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="การวินิจฉัย",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row1,
            text="สถานะระบบเชื่อมต่อ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            textvariable=self._customer_connection_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.primary,
        ).pack(side="right")

        if self._debug_log_dir:
            row2 = ctk.CTkFrame(c, fg_color="transparent")
            row2.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(
                row2,
                text="โฟลเดอร์บันทึกการทำงาน",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                text_color=PALETTE.text_muted,
            ).pack(side="left")
            secondary_button(
                row2,
                "เปิดโฟลเดอร์",
                self._open_logs_folder,
                width=90,
                height=26,
            ).pack(side="right")
        return page

    def _update_customer_connection_status(self, *_args: Any) -> None:
        self._customer_connection_var.set(
            customer_connection_status(self._proxy_connection_var.get())
        )

    def _open_logs_folder(self) -> None:
        if self._debug_log_dir:
            try:
                os.startfile(self._debug_log_dir)
            except Exception:
                pass

    def _create_about_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="เกี่ยวกับ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row1,
            text="เวอร์ชันโปรแกรม",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            text=f"v{__version__}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.primary,
        ).pack(side="right")

        ctk.CTkLabel(
            c,
            text="© 2026 NEKO FAMILY. All rights reserved.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(anchor="center", pady=(14, 8))
        return page

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def destroy(self) -> None:
        trace_id = getattr(self, "_proxy_connection_trace_id", None)
        if trace_id is not None:
            try:
                self._proxy_connection_var.trace_remove("write", trace_id)
            except tk.TclError:
                pass
            self._proxy_connection_trace_id = None
        super().destroy()

    def close(self) -> None:
        if self._on_close_callback:
            self._on_close_callback()
        self.destroy()
