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
    WindowDragHandler,
)


class SettingsWindow(ctk.CTkToplevel):
    """Standalone, single-instance Settings top-level window."""

    CATEGORIES = [
        ("general", "📌 ทั่วไป"),
        ("account", "👤 บัญชี"),
        ("subscription", "💎 สมาชิก"),
        ("pso2", "🎮 PSO2"),
        ("tweaker", "🛠 PSO2 Tweaker"),
        ("connection", "🌐 การเชื่อมต่อ"),
        ("appearance", "🎨 การแสดงผล"),
        ("notifications", "🔔 การแจ้งเตือน"),
        ("diagnostics", "🩺 การวินิจฉัย"),
        ("about", "ℹ️ เกี่ยวกับ"),
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
        self._diagnostics = diagnostics
        self._debug_mode = debug_mode
        self._debug_log_dir = debug_log_dir
        self._on_change_password = on_change_password
        self._on_sign_out = on_sign_out
        self._on_redeem_coupon = on_redeem_coupon
        self._on_choose_game = on_choose_game
        self._on_launch_game = on_launch_game

        self.title("การตั้งค่า — Neko Family Proxy")
        window_width = 740
        window_height = 520
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
        apply_rounded_window_shape(self, radius=20)

    def _build_layout(self) -> None:
        shell = ctk.CTkFrame(
            self,
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=2,
            corner_radius=16,
        )
        shell.pack(fill="both", expand=True, padx=10, pady=10)

        # Header bar
        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(
            header,
            text="⚙ การตั้งค่า (Settings)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(side="left")

        secondary_button(
            header,
            "×",
            self.close,
            width=30,
            height=26,
        ).pack(side="right")

        self._drag_handler = WindowDragHandler(self)
        self._drag_handler.bind_to(header)

        # Body container: Left Sidebar + Right Content
        body = ctk.CTkFrame(shell, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # --------------------------------------------------------------
        # Left Navigation Sidebar
        # --------------------------------------------------------------
        self._sidebar = ctk.CTkFrame(
            body,
            fg_color=PALETTE.surface,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=12,
            width=200,
        )
        self._sidebar.pack(side="left", fill="y", padx=(0, 8), pady=0)
        self._sidebar.pack_propagate(False)

        # Search bar
        self._search_var = tk.StringVar()
        self._search_entry = ctk.CTkEntry(
            self._sidebar,
            textvariable=self._search_var,
            placeholder_text="🔍 ค้นหาการตั้งค่า...",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            height=30,
            corner_radius=8,
        )
        self._search_entry.pack(fill="x", padx=8, pady=(8, 8))
        self._search_var.trace_add("write", self._filter_categories)

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
                hover_color=PALETTE.card,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                height=32,
                corner_radius=8,
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
                    hover_color=PALETTE.card,
                )
        for page in self._pages.values():
            page.pack_forget()
        self._pages[key].pack(fill="both", expand=True)

    def _filter_categories(self, *_args: Any) -> None:
        query = self._search_var.get().strip().lower()
        for key, title in self.CATEGORIES:
            btn = self._nav_buttons[key]
            if not query or query in title.lower() or query in key.lower():
                btn.pack(fill="x", pady=1)
            else:
                btn.pack_forget()

    # ------------------------------------------------------------------
    # Page Builders (B1 Foundation)
    # ------------------------------------------------------------------
    def _create_general_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="ตั้งค่าทั่วไป (General Settings)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        item1 = ctk.CTkFrame(c, fg_color="transparent")
        item1.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            item1,
            text="📌 การเชื่อมต่ออัตโนมัติ (Auto Connect):",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            item1,
            text="เปิดใช้งาน (ทำงานเมื่อพบ pso2.exe)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.success,
        ).pack(side="right")

        item2 = ctk.CTkFrame(c, fg_color="transparent")
        item2.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            item2,
            text="📌 ย่อเข้า System Tray:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            item2,
            text="เปิดใช้งาน (กด — เพื่อซ่อนหน้าต่าง)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="right")

        item3 = ctk.CTkFrame(c, fg_color="transparent")
        item3.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            item3,
            text="📌 เปิดพร้อม Windows (Start with Windows):",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            item3,
            text="ยังไม่เปิดใช้งาน (รองรับในเวอร์ชันถัดไป)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(side="right")
        return page

    def _create_account_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="ข้อมูลบัญชีผู้ใช้ (Account)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row,
            text="👤 ชื่อผู้ใช้:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row,
            textvariable=self._account_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.primary,
        ).pack(side="left", padx=8)

        ctk.CTkLabel(
            c,
            text="ℹ️ การเปลี่ยนรหัสผ่านและออกจากระบบจะเปิดใช้งานสมบูรณ์ในรอบ T10B2",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=16, pady=(8, 12))
        return page

    def _create_subscription_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="ข้อมูลสมาชิก & วันใช้งาน (Subscription)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row1,
            text="⏳ วันคงเหลือ:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            textvariable=self._entitlement_days_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.success,
        ).pack(side="left", padx=8)

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row2,
            text="📅 วันหมดอายุ:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row2,
            textvariable=self._entitlement_expiry_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left", padx=8)

        ctk.CTkLabel(
            c,
            text="ℹ️ แบบฟอร์มเติมวันใช้งานด้วยคูปองจะเปิดใช้งานสมบูรณ์ในรอบ T10B2",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=16, pady=(8, 12))
        return page

    def _create_pso2_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="ตั้งค่าเกม PSO2 (Game Settings)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row1,
            text="🎮 ที่อยู่ไฟล์เปิดเกม:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            textvariable=self._game_path_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(side="left", padx=8)

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row2,
            text="🔍 ตรวจจับตัวเกมอัตโนมัติ:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row2,
            text="เปิดใช้งาน (pso2.exe)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.success,
        ).pack(side="right")
        return page

    def _create_tweaker_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="ตั้งค่า PSO2 Tweaker",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row1,
            text="🛠 Tweaker Executable:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            textvariable=self._game_path_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(side="left", padx=8)
        return page

    def _create_connection_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="ข้อมูลการเชื่อมต่อ (Connection)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row1,
            text="🌐 โซนเซิร์ฟเวอร์:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            text="Japan (Tokyo) — AWS Lightsail",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.primary,
        ).pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row2,
            text="🔒 โหมดการเชื่อมต่อ:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row2,
            text="Automatic High-Speed Direct Tunnel",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.success,
        ).pack(side="right")
        return page

    def _create_appearance_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="การแสดงผล (Appearance)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row1,
            text="🎨 ธีมสี:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            text="Neko Pink (Light Mode)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.primary,
        ).pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row2,
            text="🔤 รูปแบบตัวอักษร:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
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
            text="การแจ้งเตือน (Notifications)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row1,
            text="🔔 การแจ้งเตือนในโปรแกรม:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            text="เปิดใช้งาน (In-App Toast Active)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.success,
        ).pack(side="right")
        return page

    def _create_diagnostics_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="การวินิจฉัย & สนับสนุน (Diagnostics)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row1,
            text="🩺 สถานะ ProxyCore:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            textvariable=self._proxy_connection_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.primary,
        ).pack(side="right")

        if self._debug_log_dir:
            row2 = ctk.CTkFrame(c, fg_color="transparent")
            row2.pack(fill="x", padx=16, pady=6)
            ctk.CTkLabel(
                row2,
                text="📁 โฟลเดอร์บันทึก Log:",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                text_color=PALETTE.text,
            ).pack(side="left")
            secondary_button(
                row2,
                "เปิดโฟลเดอร์",
                self._open_logs_folder,
                width=90,
                height=26,
            ).pack(side="right")

        ctk.CTkLabel(
            c,
            text="ℹ️ เครื่องมือวินิจฉัยและหน้าต่าง Log Viewer แบบละเอียดจะเปิดใช้งานในรอบ T10B2",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=16, pady=(8, 12))
        return page

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
            text="เกี่ยวกับโปรแกรม (About)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row1,
            text="เวอร์ชันโปรแกรม (Launcher):",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            text=f"v{__version__}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.primary,
        ).pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(
            row2,
            text="สถาปัตยกรรม (Architecture):",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        ctk.CTkLabel(
            row2,
            text="CustomTkinter + Windows Native DWM",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
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
    def close(self) -> None:
        if self._on_close_callback:
            self._on_close_callback()
        self.destroy()
