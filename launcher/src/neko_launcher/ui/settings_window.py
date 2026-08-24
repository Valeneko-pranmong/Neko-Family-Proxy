from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import tkinter as tk
import webbrowser

import customtkinter as ctk
from PIL import Image

from neko_launcher import __version__
from neko_launcher.ui.theme import FONT_FAMILY, PALETTE
from neko_launcher.ui.components.buttons import (
    card,
    destructive_button,
    primary_button,
    secondary_button,
)
from neko_launcher.ui.platform.window_scaling import SETTINGS_HEIGHT, SETTINGS_WIDTH
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


def customer_game_status(technical_status: str) -> str:
    """Map internal process-detection copy to a customer-safe PSO2 state."""
    normalized = technical_status.strip()
    if "เข้าเกมแล้ว" in normalized or "ตรวจพบ" in normalized:
        return "ตรวจพบ PSO2 แล้ว"
    return "กำลังรอเปิด PSO2"


def customer_membership_status(entitlement_status: str) -> str:
    """Reduce shared entitlement detail to one truthful membership state."""
    normalized = entitlement_status.strip()
    if normalized.startswith("ใช้งานได้"):
        return "ใช้งานได้"
    if normalized.startswith(("สิทธิ์หมดอายุแล้ว", "หมดอายุแล้ว")):
        return "หมดอายุ"
    return "ไม่พร้อมใช้งาน"


class SettingsWindow(ctk.CTkToplevel):
    """Standalone, single-instance Settings top-level window."""

    CATEGORIES = [
        ("status", "Status"),
        ("program", "Program"),
        ("account", "Account & Subscription"),
        ("pso2", "PSO2"),
        ("about", "About"),
    ]

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        *,
        icon_path: Path | None = None,
        logo_path: Path | None = None,
        account_var: tk.StringVar | None = None,
        account_status_var: tk.StringVar | None = None,
        entitlement_status_var: tk.StringVar | None = None,
        entitlement_days_var: tk.StringVar | None = None,
        entitlement_expiry_var: tk.StringVar | None = None,
        coupon_var: tk.StringVar | None = None,
        game_status_var: tk.StringVar | None = None,
        game_path_var: tk.StringVar | None = None,
        auto_launch_var: tk.BooleanVar | None = None,
        proxy_connection_var: tk.StringVar | None = None,
        telemetry_speed_var: tk.StringVar | None = None,
        telemetry_transfer_var: tk.StringVar | None = None,
        telemetry_session_var: tk.StringVar | None = None,
        telemetry_health_var: tk.StringVar | None = None,
        always_on_top_var: tk.BooleanVar | None = None,
        on_always_on_top_changed: Callable[[], None] | None = None,
        diagnostics: Any = None,
        debug_mode: bool = False,
        debug_log_dir: Path | None = None,
        on_close: Callable[[], None] | None = None,
        on_change_password: Callable[[], None] | None = None,
        on_sign_out: Callable[[], None] | None = None,
        on_redeem_coupon: Callable[[], None] | None = None,
        on_choose_game: Callable[[], None] | None = None,
        on_launch_game: Callable[[], None] | None = None,
        on_open_logs: Callable[[], None] | None = None,
        on_show_advanced_diagnostics: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_close_callback = on_close
        self._logo_path = logo_path
        self._about_logo_image = None
        self._account_var = account_var or tk.StringVar(value="")
        self._account_status_var = account_status_var or tk.StringVar(value="")
        self._entitlement_status_var = entitlement_status_var or tk.StringVar(value="")
        self._customer_membership_status_var = tk.StringVar(
            value=customer_membership_status(self._entitlement_status_var.get())
        )
        self._entitlement_status_trace_id = self._entitlement_status_var.trace_add(
            "write", self._update_customer_membership_status
        )
        self._entitlement_days_var = entitlement_days_var or tk.StringVar(value="")
        self._entitlement_expiry_var = entitlement_expiry_var or tk.StringVar(value="")
        self._coupon_var = coupon_var or tk.StringVar(value="")
        self._coupon_syncing = False
        self._coupon_trace_id = self._coupon_var.trace_add(
            "write", self._sync_coupon_to_entry
        )
        self._game_status_var = game_status_var or tk.StringVar(
            value="สถานะเกม: ยังไม่เข้าเกม (รอ pso2.exe)"
        )
        self._customer_game_status_var = tk.StringVar(
            value=customer_game_status(self._game_status_var.get())
        )
        self._game_status_trace_id = self._game_status_var.trace_add(
            "write", self._update_customer_game_status
        )
        self._game_path_var = game_path_var or tk.StringVar(value="")
        self._auto_launch_var = auto_launch_var or tk.BooleanVar(value=True)
        self._proxy_connection_var = proxy_connection_var or tk.StringVar(value="พร้อมใช้งาน")
        self._telemetry_speed_var = telemetry_speed_var or tk.StringVar(value="ไม่พร้อมใช้งาน")
        self._telemetry_transfer_var = telemetry_transfer_var or tk.StringVar(value="ไม่พร้อมใช้งาน")
        self._telemetry_session_var = telemetry_session_var or tk.StringVar(value="ไม่พร้อมใช้งาน")
        self._telemetry_health_var = telemetry_health_var or tk.StringVar(value="ไม่พร้อมใช้งาน")
        self._always_on_top_var = always_on_top_var or tk.BooleanVar(value=False)
        self._on_always_on_top_changed = on_always_on_top_changed
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
        self._on_open_logs = on_open_logs
        self._on_show_advanced_diagnostics = on_show_advanced_diagnostics

        self.title("NEKO FAMILY — Settings")
        window_width = SETTINGS_WIDTH
        window_height = SETTINGS_HEIGHT
        self.geometry(f"{window_width}x{window_height}")
        self.minsize(window_width, window_height)
        self.maxsize(window_width, window_height)
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
        self.bind("<Control-f>", self._focus_search)
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
            text="NEKO FAMILY — Settings",
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
        self.select_category("status")

    def _init_pages(self) -> None:
        self._pages["status"] = self._create_diagnostics_page()
        self._pages["program"] = self._create_general_page()
        self._pages["account"] = self._create_account_page()
        self._create_subscription_page(self._pages["account"])
        self._pages["pso2"] = self._create_pso2_page()
        self._create_tweaker_page(self._pages["pso2"])
        self._pages["about"] = self._create_about_page()
        self._focus_controls = tuple(
            control for control in (
                self._search_entry, self._change_password_button,
                self._sign_out_button, self._coupon_entry,
                self._redeem_coupon_button, self._tweaker_path_entry,
                self._choose_tweaker_button, self._launch_tweaker_button,
                getattr(self, "_open_logs_button", None),
            ) if control is not None
        )

    def select_category(self, key: str) -> None:
        if key not in self._pages:
            return
        self._selected_category = key
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
        visible_keys: list[str] = []
        for key, title in self.CATEGORIES:
            btn = self._nav_buttons[key]
            if not query or query in title.lower() or query in key.lower():
                btn.pack(fill="x", pady=1)
                visible_keys.append(key)
            else:
                btn.pack_forget()
        if query and self._selected_category not in visible_keys and visible_keys:
            self.select_category(visible_keys[0])

    # ------------------------------------------------------------------
    # Page Builders (B1.1 Foundation)
    # ------------------------------------------------------------------
    def _create_general_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="Program",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))
        self._always_on_top_switch = ctk.CTkSwitch(
            c, text="Always on top", variable=self._always_on_top_var,
            command=self._on_always_on_top_changed,
        )
        self._always_on_top_switch.pack(anchor="w", padx=16, pady=8)
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
        self._account_label = ctk.CTkLabel(
            row1,
            textvariable=self._account_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        )
        self._account_label.pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row2,
            text="สถานะบัญชี",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        self._account_status_label = ctk.CTkLabel(
            row2,
            textvariable=self._account_status_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        )
        self._account_status_label.pack(side="right")

        actions = ctk.CTkFrame(c, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(12, 12))
        self._change_password_button = secondary_button(
            actions,
            "เปลี่ยนรหัสผ่าน",
            self._invoke_change_password,
        )
        self._change_password_button.pack(side="left", padx=(0, 8))
        self._sign_out_button = destructive_button(
            actions,
            "ออกจากระบบ",
            self._invoke_sign_out,
        )
        self._sign_out_button.pack(side="left")
        return page

    def _invoke_change_password(self) -> None:
        if self._on_change_password is not None:
            self._on_change_password()

    def _invoke_sign_out(self) -> None:
        if self._on_sign_out is not None:
            self._on_sign_out()

    def _create_subscription_page(
        self, page: ctk.CTkFrame | None = None
    ) -> ctk.CTkFrame:
        page = page or ctk.CTkFrame(self._content_area, fg_color="transparent")
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
        self._entitlement_status_label = ctk.CTkLabel(
            row1,
            textvariable=self._customer_membership_status_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        )
        self._entitlement_status_label.pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row2,
            text="วันคงเหลือ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        self._entitlement_days_label = ctk.CTkLabel(
            row2,
            textvariable=self._entitlement_days_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        )
        self._entitlement_days_label.pack(side="right")

        row3 = ctk.CTkFrame(c, fg_color="transparent")
        row3.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row3,
            text="วันหมดอายุ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        self._entitlement_expiry_label = ctk.CTkLabel(
            row3,
            textvariable=self._entitlement_expiry_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        )
        self._entitlement_expiry_label.pack(side="right")

        coupon = ctk.CTkFrame(c, fg_color="transparent")
        coupon.pack(fill="x", padx=16, pady=(12, 12))
        self._coupon_entry = ctk.CTkEntry(
            coupon,
            placeholder_text="กรอกรหัสคูปอง",
            placeholder_text_color=PALETTE.text_muted,
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=8,
            height=32,
        )
        self._coupon_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        if self._coupon_var.get():
            self._coupon_entry.insert(0, self._coupon_var.get())
        self._coupon_entry.bind("<KeyRelease>", self._sync_coupon_from_entry)
        self._coupon_entry.bind("<<Paste>>", self._schedule_coupon_sync, add="+")
        self._coupon_entry.bind("<<Cut>>", self._schedule_coupon_sync, add="+")
        self._coupon_entry.bind("<Return>", self._redeem_coupon_from_entry)
        self._redeem_coupon_button = primary_button(
            coupon,
            "เติมวัน",
            self._invoke_redeem_coupon,
        )
        self._redeem_coupon_button.pack(side="right")
        return page

    def _invoke_redeem_coupon(self) -> None:
        self._sync_coupon_from_entry()
        if self._on_redeem_coupon is not None:
            self._on_redeem_coupon()

    def _schedule_coupon_sync(self, *_args: Any) -> None:
        self.after_idle(self._sync_coupon_from_entry)

    def _redeem_coupon_from_entry(self, _event: tk.Event[Any]) -> str:
        self._sync_coupon_from_entry()
        self._invoke_redeem_coupon()
        return "break"

    def _sync_coupon_from_entry(self, *_args: Any) -> None:
        if self._coupon_syncing:
            return
        self._coupon_syncing = True
        try:
            self._coupon_var.set(self._coupon_entry.get())
            if not self._coupon_var.get():
                self._coupon_entry._activate_placeholder()
        finally:
            self._coupon_syncing = False

    def _sync_coupon_to_entry(self, *_args: Any) -> None:
        if self._coupon_syncing or not hasattr(self, "_coupon_entry"):
            return
        self._coupon_syncing = True
        try:
            value = self._coupon_var.get()
            self._coupon_entry.delete(0, "end")
            if value:
                self._coupon_entry.insert(0, value)
        finally:
            self._coupon_syncing = False

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
            text="การตรวจจับเกมอัตโนมัติ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        ctk.CTkLabel(
            row1,
            text="เปิดใช้งาน",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.success,
        ).pack(side="right")

        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkLabel(
            row2,
            text="สถานะเกม",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(side="left")
        self._game_status_label = ctk.CTkLabel(
            row2,
            textvariable=self._customer_game_status_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
        )
        self._game_status_label.pack(side="right")
        return page

    def _create_tweaker_page(
        self, page: ctk.CTkFrame | None = None
    ) -> ctk.CTkFrame:
        page = page or ctk.CTkFrame(self._content_area, fg_color="transparent")
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
            text="ตำแหน่ง PSO2 Tweaker",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(anchor="w")
        self._tweaker_path_entry = ctk.CTkEntry(
            row1,
            textvariable=self._game_path_var,
            height=32,
            state="readonly",
            fg_color=PALETTE.surface,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=8,
        )
        self._tweaker_path_entry.pack(fill="x", pady=(4, 0))

        actions = ctk.CTkFrame(c, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(8, 12))
        self._choose_tweaker_button = secondary_button(
            actions,
            "เลือกไฟล์",
            self._invoke_choose_game,
        )
        self._choose_tweaker_button.pack(side="left", padx=(0, 8))
        self._launch_tweaker_button = primary_button(
            actions,
            "เปิด PSO2 Tweaker",
            self._invoke_launch_game,
        )
        self._launch_tweaker_button.pack(side="left")
        return page

    def _invoke_choose_game(self) -> None:
        if self._on_choose_game is not None:
            self._on_choose_game()

    def _invoke_launch_game(self) -> None:
        if self._on_launch_game is not None:
            self._on_launch_game()

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
            text_color=PALETTE.text,
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
            text="ธีม Neko Pink",
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
            text=FONT_FAMILY,
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
            text_color=PALETTE.text,
        ).pack(side="right")

        for variable in (
            self._telemetry_speed_var,
            self._telemetry_transfer_var,
            self._telemetry_session_var,
            self._telemetry_health_var,
        ):
            ctk.CTkLabel(
                c,
                textvariable=variable,
                anchor="w",
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                text_color=PALETTE.text_muted,
            ).pack(fill="x", padx=16, pady=2)

        if self._debug_log_dir:
            row2 = ctk.CTkFrame(c, fg_color="transparent")
            row2.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(
                row2,
                text="โฟลเดอร์บันทึกการทำงาน",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                text_color=PALETTE.text_muted,
            ).pack(side="left")
            self._open_logs_button = secondary_button(
                row2,
                "เปิดโฟลเดอร์",
                self._invoke_open_logs,
                width=90,
                height=32,
            )
            self._open_logs_button.pack(side="right")

        if self._debug_mode and self._on_show_advanced_diagnostics is not None:
            actions = ctk.CTkFrame(c, fg_color="transparent")
            actions.pack(fill="x", padx=16, pady=(8, 12))
            self._advanced_diagnostics_button = secondary_button(
                actions,
                "เครื่องมือวินิจฉัยขั้นสูง",
                self._invoke_advanced_diagnostics,
            )
            self._advanced_diagnostics_button.pack(side="left")

        return page

    def set_redeem_busy(self, busy: bool) -> None:
        self._redeem_coupon_button.configure(
            state="disabled" if busy else "normal",
            text="กำลังดำเนินการ..." if busy else "เติมวัน",
        )

    def _focus_search(self, _event: tk.Event[Any]) -> str:
        self._search_entry.focus_set()
        return "break"

    def _update_customer_connection_status(self, *_args: Any) -> None:
        self._customer_connection_var.set(
            customer_connection_status(self._proxy_connection_var.get())
        )

    def _update_customer_game_status(self, *_args: Any) -> None:
        self._customer_game_status_var.set(
            customer_game_status(self._game_status_var.get())
        )

    def _update_customer_membership_status(self, *_args: Any) -> None:
        self._customer_membership_status_var.set(
            customer_membership_status(self._entitlement_status_var.get())
        )

    def _invoke_open_logs(self) -> None:
        if self._on_open_logs is not None:
            self._on_open_logs()

    def _invoke_advanced_diagnostics(self) -> None:
        if self._on_show_advanced_diagnostics is not None:
            self._on_show_advanced_diagnostics()

    def _create_about_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content_area, fg_color="transparent")
        c = card(page)
        ctk.CTkLabel(
            c,
            text="NEKO FAMILY",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(12, 8))
        if self._logo_path and self._logo_path.is_file():
            try:
                self._about_logo_image = ctk.CTkImage(
                    Image.open(self._logo_path), size=(140, 50)
                )
                ctk.CTkLabel(c, image=self._about_logo_image, text="").pack(pady=4)
            except Exception:
                pass
        ctk.CTkLabel(
            c, text="NEKO FAMILY PROXY",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(pady=2)
        ctk.CTkLabel(
            c, text="จัดทำโดย NEKO FAMILY STUDIO",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(pady=2)
        ctk.CTkLabel(
            c, text=f"Version / Build: v{__version__}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        ).pack(pady=2)
        discord = ctk.CTkLabel(
            c, text="https://discord.gg/fkjXW9AJ6a", cursor="hand2",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, underline=True),
            text_color=PALETTE.primary,
        )
        discord.pack(pady=(6, 12))
        discord.bind(
            "<Button-1>",
            lambda _event: webbrowser.open("https://discord.gg/fkjXW9AJ6a"),
        )
        return page

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def destroy(self) -> None:
        entitlement_trace_id = getattr(self, "_entitlement_status_trace_id", None)
        if entitlement_trace_id is not None:
            try:
                self._entitlement_status_var.trace_remove("write", entitlement_trace_id)
            except tk.TclError:
                pass
            self._entitlement_status_trace_id = None
        coupon_trace_id = getattr(self, "_coupon_trace_id", None)
        if coupon_trace_id is not None:
            try:
                self._coupon_var.trace_remove("write", coupon_trace_id)
            except tk.TclError:
                pass
            self._coupon_trace_id = None
        game_trace_id = getattr(self, "_game_status_trace_id", None)
        if game_trace_id is not None:
            try:
                self._game_status_var.trace_remove("write", game_trace_id)
            except tk.TclError:
                pass
            self._game_status_trace_id = None
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
