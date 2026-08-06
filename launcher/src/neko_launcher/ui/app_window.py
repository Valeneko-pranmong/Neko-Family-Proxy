from __future__ import annotations

import ctypes
import os
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Any, Callable

import customtkinter as ctk
import tkinter as tk
from PIL import Image
from tkinter import filedialog

from neko_launcher import __version__
from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.application.services import LauncherService
from neko_launcher.domain.events import (
    GameProcessStateChanged,
    StateChanged,
)
from neko_launcher.domain.models import (
    AppState,
    AuthStatus,
    EntitlementStatus,
    GameStatus,
    ProxyStatus,
    RegistrationResult,
    entitlement_is_active,
)
from neko_launcher.infrastructure.event_bus import EventBus
from neko_launcher.infrastructure.process_detector import is_any_process_running

from .theme import FONT_FAMILY, PALETTE, apply_theme


class AppWindow:
    """Two-stage customer UI: account access first, launcher tools after login."""

    # The UI is authored at this size and scaled down as needed so that the
    # whole launcher remains visible on short laptop displays.  The actual
    # window is never resizable and is kept inside the red guide frame.
    _DESIGN_WIDTH = 480
    _DESIGN_HEIGHT = 760
    # Keep a small breathing room from the physical top/bottom edges, matching
    # the red guide frame used for the launcher layout.
    _SCREEN_MARGIN_RATIO = 0.04

    def __init__(
        self,
        controller: ApplicationController,
        service: LauncherService,
        event_bus: EventBus,
        logo_path: Path | None = None,
        icon_path: Path | None = None,
        game_default_path: str = "",
        game_path_store: Path | None = None,
    ) -> None:
        apply_theme()
        self._controller = controller
        self._service = service
        self._event_bus = event_bus
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="neko-launcher",
        )
        self._pending: list[
            tuple[Future[Any], Callable[[Any], None] | None]
        ] = []
        self._logo_image = None
        self._icon_path = icon_path
        self._password_dialog: ctk.CTkToplevel | None = None
        self._closing = False
        self._tray_actions: SimpleQueue[str] = SimpleQueue()

        self.root = ctk.CTk()
        self.root.withdraw()
        # A custom title bar gives us exactly two controls: minimize and close.
        # The custom title bar remains visual-only, while the window title
        # keeps the launcher identifiable to Windows and accessibility tools.
        self.root.title("Neko Family Proxy")
        # Ensure the window appears in the taskbar by NOT using overrideredirect(True).
        # We will style the native title bar instead to make it borderless.
        self.root.resizable(False, False)
        self.root.configure(fg_color=PALETTE.background)
        if icon_path and icon_path.is_file():
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        # Configure the window/scaling before creating widgets.  This keeps
        # the same compact layout on 1080p monitors and smaller notebooks.
        self._fit_portrait_window()

        self._status = tk.StringVar(value="กำลังเตรียมข้อมูล…")
        self._account = tk.StringVar(value="")
        self._entitlement = tk.StringVar(value="ยังไม่มีวันใช้งาน")
        self._error = tk.StringVar(value="")
        self._notice = tk.StringVar(value="")
        self._error.trace_add("write", self._update_message_visibility)
        self._notice.trace_add("write", self._update_message_visibility)
        self._login_email = tk.StringVar()
        self._login_password = tk.StringVar()
        self._register_username = tk.StringVar()
        self._register_password = tk.StringVar()
        self._register_password_confirm = tk.StringVar()
        self._new_password = tk.StringVar()
        self._new_password_confirm = tk.StringVar()
        self._coupon_code = tk.StringVar()
        self._game_path = tk.StringVar(value=game_default_path)
        self._game_path_store = game_path_store
        self._auto_launch = tk.BooleanVar(value=True)
        self._game_connection_status = tk.StringVar(value="รอให้เข้าเกม (pso2.exe)")
        self._proxy_connection_status = tk.StringVar(value="ProxyCore ยังไม่ทำงาน")
        self._process_detection_pending = False

        self._build_layout(logo_path)
        self._fit_portrait_window()
        # The first geometry call can be ignored before the native window is
        # mapped; apply it once more after the window manager has created it.
        self.root.after(250, self._center_window)
        self.root.after(350, self._show_initial_window)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain_events)
        self.root.after(100, self._drain_tray_actions)
        self.root.after(30_000, self._heartbeat)
        self.root.after(3_000, self._poll_game_process)
        self._submit(self._service.restore_session, self._restore_completed)

    def _fit_portrait_window(self) -> None:
        """Center a fixed-size window inside the guide-frame safe area."""
        self.root.update_idletasks()
        screen_w = int(self.root.winfo_screenwidth())
        screen_h = int(self.root.winfo_screenheight())
        safe_margin_y = int(screen_h * self._SCREEN_MARGIN_RATIO)
        available_h = max(1, screen_h - (safe_margin_y * 2))
        # Tk geometry uses logical pixels on a scaled Windows desktop.  Work
        # in that coordinate space so the physical window still honors the
        # screen margins on 100%, 125% and 150% DPI settings.
        window_scale = max(
            0.1,
            float(ctk.ScalingTracker.get_window_scaling(self.root)),
        )
        width = min(
            self._DESIGN_WIDTH / window_scale,
            max(1.0, (screen_w - 32) / window_scale),
        )
        height = min(
            self._DESIGN_HEIGHT / window_scale,
            # Leave a few logical pixels for the native title-bar border.
            max(1.0, (available_h / window_scale) - 4),
        )

        # CustomTkinter scales fonts, paddings and widget dimensions together.
        # Scale against the authored height so no internal scrollbar is needed.
        scale = min(
            1.0,
            (width * window_scale) / self._DESIGN_WIDTH,
            (height * window_scale) / self._DESIGN_HEIGHT,
        )
        # The DPI tracker multiplies widget scaling by the window scale on
        # Windows, so compensate here to keep the final visual scale stable.
        ctk.set_widget_scaling(scale / window_scale)

        logical_width = int(width)
        logical_height = int(height)
        x = max(0, (screen_w - logical_width) // 2)
        y = max(0, (screen_h - logical_height) // 2)
        self._window_size = (logical_width, logical_height)

        # set_widget_scaling() temporarily restores CTk's default 600x500
        # min/max bounds until its delayed scaling callback runs.  If Windows
        # receives the rounded region during that interval, the later 480x760
        # resize remains clipped to 600x500.  Lock the calculated bounds now so
        # the native size and the rounded region always agree.
        self.root.minsize(logical_width, logical_height)
        self.root.maxsize(logical_width, logical_height)
        self.root.geometry(
            f"{logical_width}x{logical_height}+{x}+{y}"
        )

    def _center_window(self) -> None:
        """Apply the final centered position after the native window is mapped."""
        if not self.root.winfo_exists():
            return
        width, height = getattr(self, "_window_size", (480, 760))
        screen_w = int(self.root.winfo_screenwidth())
        screen_h = int(self.root.winfo_screenheight())
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        # Geometry changes are asynchronous in Tk.  Flush the native resize.
        # Note: Do not apply rounded shape here since the window is withdrawn and
        # winfo_width() will return an incorrect default size, clipping the UI.
        self.root.update_idletasks()

    @staticmethod
    def _apply_rounded_window_shape(
        window: ctk.CTk | ctk.CTkToplevel,
        *,
        radius: int = 28,
    ) -> None:
        """Clip a borderless Windows window to softly rounded corners."""
        if sys.platform != "win32" or not window.winfo_exists():
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
            width = max(1, int(window.winfo_width()))
            height = max(1, int(window.winfo_height()))
            region = ctypes.windll.gdi32.CreateRoundRectRgn(
                0,
                0,
                width + 1,
                height + 1,
                radius,
                radius,
            )
            if region:
                # Windows owns the region after a successful SetWindowRgn.
                ctypes.windll.user32.SetWindowRgn(hwnd, region, True)
        except (AttributeError, OSError):
            # Rounded corners are cosmetic; keep the launcher functional on
            # restricted or older Windows installations.
            pass

    def _show_initial_window(self) -> None:
        """Ensure a borderless window is visible after Windows maps it."""
        if not self.root.winfo_exists() or self._closing:
            return
        self._style_native_title_bar()
        self.root.deiconify()
        self.root.update_idletasks()
        self._apply_rounded_window_shape(self.root)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()
        self.root.after(1_000, self._release_initial_topmost)

    def _release_initial_topmost(self) -> None:
        if self.root.winfo_exists() and not self._closing:
            self.root.attributes("-topmost", False)

    def _style_native_title_bar(self) -> None:
        """Blend the Windows title bar with the UI and remove maximize."""
        if sys.platform != "win32" or not self.root.winfo_exists():
            return

        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()

            # Keep minimize and close, but remove the maximize button and the
            # resizable frame from the native Windows chrome.
            gwl_style = -16
            ws_maximizebox = 0x00010000
            ws_thickframe = 0x00040000
            ws_caption = 0x00C00000
            get_window_long = user32.GetWindowLongPtrW
            get_window_long.argtypes = (ctypes.c_void_p, ctypes.c_int)
            get_window_long.restype = ctypes.c_ssize_t
            set_window_long = user32.SetWindowLongPtrW
            set_window_long.argtypes = (
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_ssize_t,
            )
            set_window_long.restype = ctypes.c_ssize_t
            style = get_window_long(hwnd, gwl_style)
            style &= ~(ws_maximizebox | ws_thickframe | ws_caption)
            set_window_long(hwnd, gwl_style, style)

            # Ask Windows to redraw the non-client frame after changing style.
            swp_flags = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, swp_flags)

            def _colorref(hex_color: str) -> int:
                value = hex_color.lstrip("#")
                red = int(value[0:2], 16)
                green = int(value[2:4], 16)
                blue = int(value[4:6], 16)
                return red | (green << 8) | (blue << 16)

            dwmapi = ctypes.windll.dwmapi
            # Windows 11 attributes: border, caption background and caption
            # text. Unsupported versions simply ignore these calls.
            for attribute, color in (
                (34, PALETTE.border),
                (35, PALETTE.background),
                (36, PALETTE.text),
            ):
                color_value = ctypes.c_int(_colorref(color))
                dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    attribute,
                    ctypes.byref(color_value),
                    ctypes.sizeof(color_value),
                )
        except (AttributeError, OSError, ValueError):
            # The launcher still works with the system-default title bar on
            # older Windows builds or restricted desktop environments.
            pass

    def _build_layout(self, logo_path: Path | None) -> None:
        shell = ctk.CTkFrame(
            self.root,
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=2,
            corner_radius=20,
        )
        shell.pack(fill="both", expand=True, padx=10, pady=8)
        self._build_window_controls(shell)

        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(8, 2))

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left", fill="x", expand=True)
        if logo_path and logo_path.is_file():
            try:
                self._logo_image = ctk.CTkImage(
                    Image.open(logo_path),
                    size=(260, 90),
                )
                ctk.CTkLabel(
                    brand,
                    image=self._logo_image,
                    text="",
                    fg_color="transparent",
                ).pack(anchor="center")
            except Exception:
                self._add_heading(brand)
        else:
            self._add_heading(brand)

        ctk.CTkLabel(
            brand,
            text="NEKO FAMILY PROXY PSO2NGS",
            font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="center", pady=(10, 0))
        self._header_message = ctk.CTkLabel(
            brand,
            text="High Performance & Low Latency",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        )
        self._header_message.pack(anchor="center")



        self._content = ctk.CTkFrame(shell, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=6, pady=(0, 2))
        self._build_auth_view()
        self._build_program_view()
        self._show_auth_view()
        self._update_message_visibility()

        footer = ctk.CTkLabel(
            shell,
            text=f"Version {__version__}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=PALETTE.text_muted,
        )
        footer.pack(pady=(0, 4))

    def _update_message_visibility(self, *_args: Any) -> None:
        if not hasattr(self, "_header_message"):
            return
        error = self._error.get().strip()
        notice = self._notice.get().strip()
        message = error or notice

        self._header_message.configure(
            text="High Performance & Low Latency",
            text_color=PALETTE.text_muted,
        )

        if message:
            if len(message) > 48:
                message = f"{message[:47]}…"
            self._show_toast(message, is_error=bool(error))
        else:
            self._hide_toast()

    def _show_toast(self, message: str, is_error: bool) -> None:
        if not hasattr(self, "_toast_frame"):
            self._toast_frame = ctk.CTkFrame(
                self.root,
                corner_radius=0,
                fg_color=PALETTE.surface,
                bg_color="transparent",
                border_width=1,
                border_color=PALETTE.border,
            )
            self._toast_label = ctk.CTkLabel(
                self._toast_frame,
                text="",
                font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
                text_color=PALETTE.text,
            )
            self._toast_label.pack(side="left", padx=(30, 14), pady=14)

            self._toast_close_btn = ctk.CTkButton(
                self._toast_frame,
                text="×",
                width=24,
                height=24,
                corner_radius=0,
                fg_color="black",
                text_color="white",
                hover_color="#333333",
                font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
                command=self._hide_toast
            )
            self._toast_close_btn.pack(side="left", padx=(0, 10), pady=14)
            self._toast_timer = None

        self._toast_label.configure(
            text=message,
            text_color=PALETTE.danger if is_error else PALETTE.text,
        )

        self._toast_frame.place(relx=0.5, rely=1.0, y=-20, anchor="s")
        self._toast_frame.lift()

        if self._toast_timer:
            self.root.after_cancel(self._toast_timer)
        self._toast_timer = self.root.after(5000, self._hide_toast)

    def _hide_toast(self) -> None:
        if hasattr(self, "_toast_frame"):
            self._toast_frame.place_forget()
            if self._toast_timer:
                self.root.after_cancel(self._toast_timer)
                self._toast_timer = None
        
        # Note: Do not call self._error.set("") here as it will trigger an infinite trace loop
        # Instead we just hide the UI until the next set("") clears it, or set("msg") updates it.

    def _build_window_controls(self, drag_surface: ctk.CTkBaseClass) -> None:
        controls = ctk.CTkFrame(self.root, fg_color="transparent")
        controls.place(relx=1.0, x=-10, y=10, anchor="ne")
        self._secondary_button(
            controls,
            "—",
            self._minimize_window,
            width=30,
            height=24,
        ).pack(side="left", padx=(0, 3))
        self._secondary_button(
            controls,
            "×",
            self.close,
            width=30,
            height=24,
        ).pack(side="left")
        drag_surface.bind("<ButtonPress-1>", self._start_window_drag, add="+")
        drag_surface.bind("<B1-Motion>", self._drag_window, add="+")

    def _setup_tray(self) -> None:
        import pystray
        from PIL import Image
        import threading
        try:
            image = Image.open(self._icon_path)
        except Exception:
            image = Image.new('RGB', (64, 64), color=(255, 255, 255))
        menu = pystray.Menu(
            pystray.MenuItem("Show Launcher", self._restore_from_tray, default=True),
            pystray.MenuItem("Exit", self._close_from_tray)
        )
        self._tray_icon = pystray.Icon("NekoLauncher", image, "Neko Family Proxy", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _minimize_window(self) -> None:
        if not self._closing and self.root.winfo_exists():
            if not hasattr(self, "_tray_icon") or self._tray_icon is None:
                self._setup_tray()
            self.root.withdraw()

    def _restore_from_tray(self, icon, item) -> None:
        self._tray_actions.put("restore")

    def _close_from_tray(self, icon, item) -> None:
        self._tray_actions.put("close")

    def _drain_tray_actions(self) -> None:
        """Run all Tk work on the main UI thread, never pystray's thread."""
        if self._closing:
            return
        while True:
            try:
                action = self._tray_actions.get_nowait()
            except Empty:
                break
            if action == "close":
                self.close()
                return
            if action == "restore" and self.root.winfo_exists():
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self.root.lift()
                self.root.after(100, lambda: self.root.attributes("-topmost", False))
        if self.root.winfo_exists():
            self.root.after(100, self._drain_tray_actions)

    def _start_window_drag(self, event: tk.Event[tk.Misc]) -> None:
        self._drag_offset = (event.x_root, event.y_root)

    def _drag_window(self, event: tk.Event[tk.Misc]) -> None:
        if not hasattr(self, "_drag_offset"):
            return
        previous_x, previous_y = self._drag_offset
        x = self.root.winfo_x() + event.x_root - previous_x
        y = self.root.winfo_y() + event.y_root - previous_y
        self.root.geometry(f"+{x}+{y}")
        self._drag_offset = (event.x_root, event.y_root)

    def _build_auth_view(self) -> None:
        self._auth_view = ctk.CTkFrame(
            self._content,
            fg_color="transparent",
        )
        intro = self._card(self._auth_view)
        intro.configure(height=540)
        intro.pack_propagate(False)
        intro.pack_configure(side="top", fill="x", expand=False, padx=8, pady=8)

        top_row = ctk.CTkFrame(intro, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(6, 0))
        
        self._auth_hint = ctk.CTkLabel(
            top_row,
            text="เข้าสู่ระบบเพื่อเริ่มใช้งาน",
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
        )
        self._auth_hint.pack(side="left")

        self._status_badge = ctk.CTkLabel(
            top_row,
            textvariable=self._status,
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self._status_badge.pack(side="right")
        
        title_frame = ctk.CTkFrame(intro, fg_color="transparent")
        title_frame.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(
            title_frame,
            text="เข้าสู่ระบบและสมัครสมาชิก",
            font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="center")
        ctk.CTkLabel(
            title_frame,
            text="— ♥ —",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.primary_soft,
        ).pack(anchor="center", pady=(0, 6))

        self._tab_controls = ctk.CTkFrame(
            intro,
            fg_color="#F3F4F6", # Very light gray for pill container
            corner_radius=22,
            height=44,
        )
        self._tab_controls.pack(fill="x", padx=30, pady=(6, 6))
        self._tab_controls.pack_propagate(False)
        
        self._login_tab_btn = ctk.CTkButton(
            self._tab_controls,
            text="เข้าสู่ระบบ",
            fg_color=PALETTE.card,
            text_color=PALETTE.primary,
            hover_color=PALETTE.card,
            corner_radius=18,
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            command=lambda: self._switch_tab("login"),
        )
        self._login_tab_btn.pack(side="left", padx=4, pady=4, expand=True, fill="both")
        
        self._register_tab_btn = ctk.CTkButton(
            self._tab_controls,
            text="สมัครสมาชิก",
            fg_color="transparent",
            text_color="#888888",
            hover_color="#E5E7EB",
            corner_radius=18,
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            command=lambda: self._switch_tab("register"),
        )
        self._register_tab_btn.pack(side="left", padx=4, pady=4, expand=True, fill="both")
        
        self._login_frame = ctk.CTkFrame(intro, fg_color="transparent")
        self._register_frame = ctk.CTkFrame(intro, fg_color="transparent")

        # Login Frame
        login = self._login_frame
        self._field_label(login, "ชื่อผู้ใช้")
        self._login_email_entry = self._icon_entry(
            login, "👤", "กรอกชื่อผู้ใช้", self._login_email
        )
        self._field_label(login, "รหัสผ่าน")
        self._login_password_entry = self._icon_entry(
            login, "🔒", "กรอกรหัสผ่าน", self._login_password, show="●", right_icon="👁"
        )
        self._login_email_entry.bind("<Return>", lambda _event: self._login())
        self._login_password_entry.bind("<Return>", lambda _event: self._login())
        
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
            text="ลืมรหัสผ่าน?",
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            cursor="hand2"
        )
        forgot_pw.pack(side="right", pady=(2, 0))
        forgot_pw.bind("<Button-1>", lambda e: self._notice.set("กรุณาติดต่อแอดมินเพื่อรีเซ็ตรหัสผ่าน"))
        
        self._login_button = self._primary_button(
            login, "เข้าสู่ระบบ ➔", self._login
        )
        self._login_button.pack(side="bottom", fill="x", padx=14, pady=(10, 14))

        # Register Frame
        register = self._register_frame
        self._field_label(register, "ชื่อผู้ใช้")
        self._register_email_entry = self._icon_entry(
            register, "👤", "กรอกชื่อผู้ใช้", self._register_username
        )
        self._field_label(register, "รหัสผ่าน (อย่างน้อย 8 ตัวอักษร)")
        self._register_password_entry = self._icon_entry(
            register, "🔒", "กรอกรหัสผ่าน", self._register_password, show="●", right_icon="👁"
        )
        ctk.CTkLabel(
            register,
            text="ใช้ตัวอักษรอย่างน้อย 8 ตัวอักษร",
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        ).pack(anchor="w", padx=16, pady=(2, 0))
        self._field_label(register, "ยืนยันรหัสผ่าน")
        self._register_password_confirm_entry = self._icon_entry(
            register, "🔒", "กรอกรหัสผ่านอีกครั้ง", self._register_password_confirm, show="●", right_icon="👁"
        )
        self._register_email_entry.bind("<Return>", lambda _event: self._register())
        self._register_password_entry.bind("<Return>", lambda _event: self._register())
        self._register_password_confirm_entry.bind(
            "<Return>", lambda _event: self._register()
        )
        self._register_button = self._primary_button(
            register, "สร้างบัญชี ➔", self._register
        )
        self._register_button.pack(side="bottom", fill="x", padx=14, pady=(10, 14))

        self._switch_tab("login")

    def _switch_tab(self, tab: str) -> None:
        if tab == "login":
            self._login_tab_btn.configure(
                fg_color=PALETTE.card, text_color=PALETTE.primary, hover_color=PALETTE.card
            )
            self._register_tab_btn.configure(
                fg_color="transparent", text_color="#888888", hover_color="#E5E7EB"
            )
            self._register_frame.pack_forget()
            self._login_frame.pack(fill="both", expand=True)
        else:
            self._register_tab_btn.configure(
                fg_color=PALETTE.primary, text_color=PALETTE.on_primary, hover_color=PALETTE.primary_hover
            )
            self._login_tab_btn.configure(
                fg_color="transparent", text_color="#888888", hover_color="#E5E7EB"
            )
            self._login_frame.pack_forget()
            self._register_frame.pack(fill="both", expand=True)

    def _icon_entry(
        self,
        parent: ctk.CTkBaseClass,
        icon: str,
        placeholder: str,
        variable: tk.StringVar,
        *,
        show: str | None = None,
        right_icon: str | None = None,
    ) -> ctk.CTkEntry:
        frame = ctk.CTkFrame(
            parent,
            fg_color=PALETTE.card,
            border_width=0,
            corner_radius=10,
        )
        frame.pack(fill="x", padx=16, pady=(2, 4))

        ctk.CTkLabel(
            frame,
            text=icon,
            text_color="#A0A0A0",
            font=ctk.CTkFont(family=FONT_FAMILY, size=18),
            width=30,
        ).pack(side="left", padx=(10, 4), pady=4)

        entry = ctk.CTkEntry(
            frame,
            textvariable=variable,
            placeholder_text=placeholder,
            show=show,
            fg_color="transparent",
            text_color=PALETTE.text,
            border_width=0,
            height=38,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13)
        )
        entry.pack(side="left", fill="both", expand=True, pady=4)
        
        if right_icon:
            ctk.CTkLabel(
                frame,
                text=right_icon,
                text_color="#C0C0C0",
                font=ctk.CTkFont(family=FONT_FAMILY, size=18),
                width=30,
            ).pack(side="right", padx=(4, 10), pady=4)
            
        return entry


    def _build_program_view(self) -> None:
        # Keep the original single-page layout; the outer window is scaled to
        # the display rather than introducing an internal scrollbar.
        self._program_view = ctk.CTkFrame(
            self._content,
            fg_color="transparent",
        )

        account = self._card(self._program_view)
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
            textvariable=self._account,
            text_color=PALETTE.text_muted,
        )
        self._account_label.pack(side="right", pady=2)

        self._entitlement_label = ctk.CTkLabel(
            account,
            textvariable=self._entitlement,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=PALETTE.text,
            wraplength=360,
            justify="left",
        )
        self._entitlement_label.pack(anchor="w", padx=14, pady=(2, 4))

        actions = ctk.CTkFrame(account, fg_color="transparent")
        actions.pack(fill="x", padx=10, pady=(2, 10))
        self._secondary_button(
            actions,
            "เปลี่ยนรหัสผ่าน",
            self._open_password_dialog,
        ).pack(side="left", padx=4)
        self._secondary_button(
            actions,
            "ออกจากระบบ",
            self._sign_out,
        ).pack(side="right", padx=4)

        usage = self._card(self._program_view)
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
            textvariable=self._coupon_code,
            placeholder_text="NEKO-XXXXXXXX-…",
            height=34,
        )
        self._coupon_entry.pack(fill="x", padx=4, pady=(0, 6))
        self._redeem_button = self._primary_button(
            coupon_row, "เติมวันจากคูปอง", self._redeem_coupon
        )
        self._redeem_button.pack(fill="x", padx=4)

        proxy = self._card(self._program_view)
        ctk.CTkLabel(
            proxy,
            text="สถานะการเชื่อมต่อ (Connection Status)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=14, pady=(10, 4))

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
            textvariable=self._game_connection_status,
            text_color=PALETTE.text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(0, 3))
        ctk.CTkLabel(
            proxy,
            textvariable=self._proxy_connection_status,
            text_color=PALETTE.text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(0, 10))

        game = self._card(self._program_view)
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
            textvariable=self._game_path,
            placeholder_text="กรุณาเลือก Tweaker.exe ในเครื่องคุณ",
            height=34,
        )
        self._game_path_entry.pack(side="left", fill="x", expand=True, padx=4)
        self._secondary_button(
            game_path_row,
            "เลือกไฟล์ (Browse)",
            self._choose_game,
        ).pack(side="left", padx=4)

        self._auto_launch_checkbox = ctk.CTkCheckBox(
            game,
            text="เปิด Tweaker อัตโนมัติเมื่อล็อคอินสำเร็จ",
            variable=self._auto_launch,
            text_color=PALETTE.text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self._auto_launch_checkbox.pack(anchor="w", padx=14, pady=(10, 10))
        # Keep the visual state in sync with the default BooleanVar.  Calling
        # select explicitly also avoids an unchecked first paint on Windows.
        if self._auto_launch.get():
            self._auto_launch_checkbox.select()

        game_controls = ctk.CTkFrame(game, fg_color="transparent")
        game_controls.pack(fill="x", padx=10, pady=(0, 10))
        self._launch_game_button = self._primary_button(
            game_controls,
            "เปิดโปรแกรม PSO2 Tweaker",
            self._launch_game,
        )
        self._launch_game_button.pack(side="left", fill="x", expand=True, padx=4)
        self._launch_game_button.configure(state="disabled")

    @staticmethod
    def _card(parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=PALETTE.surface,
            border_width=0,
            corner_radius=14,
        )
        card.pack(fill="x", padx=8, pady=3)
        return card

    def _entry(
        self,
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

    @staticmethod
    def _field_label(parent: ctk.CTkBaseClass, text: str) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            text_color=PALETTE.text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(6, 0))

    @staticmethod
    def _primary_button(
        parent: ctk.CTkBaseClass,
        text: str,
        command: Callable[[], None],
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            fg_color=PALETTE.primary,
            hover_color=PALETTE.primary_hover,
            text_color=PALETTE.on_primary,
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            corner_radius=10,
            height=42,
            command=command,
        )

    @staticmethod
    def _secondary_button(
        parent: ctk.CTkBaseClass,
        text: str,
        command: Callable[[], None],
        *,
        width: int | None = None,
        height: int = 32,
    ) -> ctk.CTkButton:
        options: dict[str, Any] = {}
        if width is not None:
            options["width"] = width
        return ctk.CTkButton(
            parent,
            text=text,
            fg_color="transparent",
            hover_color=PALETTE.card,
            border_color=PALETTE.primary_soft,
            border_width=2,
            text_color=PALETTE.primary_dark,
            corner_radius=8,
            height=height,
            command=command,
            **options,
        )

    def _show_auth_view(self) -> None:
        self._program_view.pack_forget()
        self._auth_view.pack(fill="both", expand=True, padx=8, pady=(0, 3))

    def _show_program_view(self) -> None:
        self._auth_view.pack_forget()
        self._program_view.pack(fill="both", expand=True, padx=8, pady=(2, 6))

    def _open_password_dialog(self) -> None:
        if (
            self._password_dialog is not None
            and self._password_dialog.winfo_exists()
        ):
            self._password_dialog.lift()
            self._password_dialog.focus_force()
            return

        self._new_password.set("")
        self._new_password_confirm.set("")
        self._error.set("")

        dialog = ctk.CTkToplevel(self.root)
        self._password_dialog = dialog
        dialog_width = 400
        dialog_height = 380
        dialog.title("เปลี่ยนรหัสผ่าน")
        dialog.geometry(f"{dialog_width}x{dialog_height}")
        dialog.resizable(False, False)
        # Avoid the default CustomTkinter/Windows blue title-bar icon.  The
        # dialog uses the same borderless, rounded treatment as the launcher.
        dialog.overrideredirect(True)
        dialog.configure(fg_color=PALETTE.background)
        if self._icon_path and self._icon_path.is_file():
            try:
                dialog.iconbitmap(self._icon_path)
            except Exception:
                pass
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", self._close_password_dialog)

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
        self._secondary_button(
            dialog_controls,
            "×",
            self._close_password_dialog,
            width=28,
            height=24,
        ).pack(side="right")
        ctk.CTkLabel(
            panel,
            text="ตั้งรหัสผ่านใหม่อย่างน้อย 8 ตัวอักษร",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=18, pady=(0, 8))

        self._field_label(panel, "รหัสผ่านใหม่")
        self._new_password_entry = self._entry(
            panel,
            "รหัสผ่านใหม่",
            self._new_password,
            show="●",
        )
        self._field_label(panel, "ยืนยันรหัสผ่านใหม่")
        self._new_password_confirm_entry = self._entry(
            panel,
            "ยืนยันรหัสผ่านใหม่",
            self._new_password_confirm,
            show="●",
        )
        self._new_password_entry.bind(
            "<Return>", lambda _event: self._change_password()
        )
        self._new_password_confirm_entry.bind(
            "<Return>", lambda _event: self._change_password()
        )

        ctk.CTkLabel(
            panel,
            textvariable=self._error,
            text_color=PALETTE.danger,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            wraplength=330,
        ).pack(padx=18, pady=(6, 0))

        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(8, 14))
        self._secondary_button(
            buttons,
            "ยกเลิก",
            self._close_password_dialog,
        ).pack(side="left", fill="x", expand=True, padx=4)
        self._change_password_button = self._primary_button(
            buttons,
            "ยืนยัน",
            self._change_password,
        )
        self._change_password_button.pack(
            side="left", fill="x", expand=True, padx=4
        )

        dialog.update_idletasks()
        x = (
            self.root.winfo_rootx()
            + (self.root.winfo_width() - dialog_width) // 2
        )
        y = (
            self.root.winfo_rooty()
            + (self.root.winfo_height() - dialog_height) // 2
        )
        dialog.geometry(
            f"{dialog_width}x{dialog_height}+{max(0, x)}+{max(0, y)}"
        )
        dialog.update_idletasks()
        self._apply_rounded_window_shape(dialog, radius=24)
        dialog.grab_set()
        self._new_password_entry.focus_set()

    def _close_password_dialog(self) -> None:
        dialog = self._password_dialog
        self._password_dialog = None
        self._new_password.set("")
        self._new_password_confirm.set("")
        self._error.set("")
        if dialog is not None and dialog.winfo_exists():
            dialog.grab_release()
            dialog.destroy()

    def _login(self) -> None:
        self._submit(
            lambda: self._service.sign_in(
                self._login_email.get(),
                self._login_password.get(),
            ),
            self._login_succeeded,
        )

    def _restore_completed(self, restored: bool) -> None:
        if restored:
            self._notice.set("กู้คืนการเข้าสู่ระบบสำเร็จ")
            self._auto_launch_tweaker()
        elif self._controller.state.auth_status is AuthStatus.SIGNED_OUT:
            self._status.set("ยังไม่ได้เข้าสู่ระบบ")

    def _login_succeeded(self, _: Any) -> None:
        self._login_password.set("")
        self._notice.set("เข้าสู่ระบบสำเร็จ")
        self._auto_launch_tweaker()

    def _register(self) -> None:
        password = self._register_password.get()
        if not password or password != self._register_password_confirm.get():
            self._error.set("รหัสผ่านและการยืนยันไม่ตรงกัน")
            return
        self._submit(
            lambda: self._service.sign_up(
                self._register_username.get(),
                password,
            ),
            self._register_succeeded,
        )

    def _register_succeeded(self, result: RegistrationResult) -> None:
        self._register_password.set("")
        self._register_password_confirm.set("")
        if result.requires_email_confirmation:
            self._notice.set(
                "รับคำขอสมัครสมาชิกแล้ว หากระบบส่งอีเมลยืนยัน "
                "กรุณาตรวจกล่องจดหมายก่อนเข้าสู่ระบบ"
            )
        else:
            self._notice.set(
                "สมัครสมาชิกสำเร็จ ใช้ชื่อผู้ใช้และรหัสผ่านเข้าสู่ระบบได้เลย"
            )

    def _change_password(self) -> None:
        password = self._new_password.get()
        if not password or password != self._new_password_confirm.get():
            self._error.set("รหัสผ่านใหม่และการยืนยันไม่ตรงกัน")
            return
        self._submit(
            lambda: self._service.change_password(password),
            self._password_changed,
        )

    def _password_changed(self, _: Any) -> None:
        self._close_password_dialog()
        self._notice.set("เปลี่ยนรหัสผ่านสำเร็จ")

    def _sign_out(self) -> None:
        self._submit(self._service.sign_out, self._signed_out)

    def _signed_out(self, _: Any) -> None:
        self._close_password_dialog()
        self._coupon_code.set("")
        self._notice.set("ออกจากระบบแล้ว")

    def _redeem_coupon(self) -> None:
        self._submit(
            lambda: self._service.redeem_coupon(self._coupon_code.get()),
            self._coupon_redeemed,
        )

    def _choose_game(self) -> None:
        selected = filedialog.askopenfilename(
            title="เลือกไฟล์เปิดเกม",
            filetypes=[
                ("ไฟล์เปิดเกม", "Tweaker.exe"),
                ("โปรแกรม Windows", "*.exe"),
                ("ไฟล์ทั้งหมด", "*.*"),
            ],
        )
        if not selected:
            return
        self._game_path.set(selected)
        if self._game_path_store:
            try:
                self._game_path_store.parent.mkdir(parents=True, exist_ok=True)
                self._game_path_store.write_text(selected, encoding="utf-8")
            except OSError:
                pass
        self._notice.set("บันทึกไฟล์เปิดเกมแล้ว")

    def _launch_game(self) -> None:
        # ProxyCore is always process-driven: launch Tweaker, then wait for
        # the actual pso2.exe process before connecting.
        self._launch_tweaker_only()

    def _auto_launch_tweaker(self) -> None:
        """Launch once after a successful sign-in/session restoration."""
        if not self._auto_launch.get():
            return
        state = self._controller.state
        ready = (
            state.auth_status is AuthStatus.AUTHENTICATED
            and state.session_id is not None
            and entitlement_is_active(state.entitlement)
        )
        if ready:
            self._launch_tweaker_only()

    def _launch_tweaker_only(self) -> None:
        """Open Tweaker without starting ProxyCore."""
        executable = self._selected_tweaker_executable()
        if executable is None:
            return
        self._error.set("")
        self._persist_game_path(executable)
        self._service.launch_tweaker(executable)
        if self._controller.state.game_status is GameStatus.RUNNING:
            self._notice.set("เปิดโปรแกรม PSO2 Tweaker แล้ว")

    def _selected_tweaker_executable(self) -> str | None:
        raw_path = self._game_path.get().strip().strip('"')
        if not raw_path:
            self._error.set("กรุณาเลือกไฟล์ Tweaker.exe ก่อน")
            return None

        executable = Path(os.path.expandvars(raw_path)).expanduser()
        if not executable.is_file():
            self._error.set(
                "ไม่พบไฟล์ Tweaker.exe กรุณากด Browse แล้วเลือกไฟล์ใหม่"
            )
            return None
        return str(executable.resolve())

    def _persist_game_path(self, executable: str) -> None:
        self._game_path.set(executable)
        if self._game_path_store is None:
            return
        try:
            self._game_path_store.parent.mkdir(parents=True, exist_ok=True)
            self._game_path_store.write_text(executable, encoding="utf-8")
        except OSError:
            pass

    def _coupon_redeemed(self, result: Any) -> None:
        self._coupon_code.set("")
        self._notice.set(
            f"เติมวันสำเร็จ +{result.days_added} วัน "
            f"หมดอายุ {result.valid_until:%d/%m/%Y %H:%M}"
        )

    def _submit(
        self,
        work: Callable[[], Any],
        on_success: Callable[[Any], None] | None = None,
    ) -> None:
        self._error.set("")
        self._notice.set("")
        self._pending.append((self._executor.submit(work), on_success))

    def _drain_events(self) -> None:
        remaining: list[
            tuple[Future[Any], Callable[[Any], None] | None]
        ] = []
        for future, on_success in self._pending:
            if not future.done():
                remaining.append((future, on_success))
                continue
            try:
                result = future.result()
            except LauncherServiceError as exc:
                self._error.set(str(exc))
            except Exception:
                self._error.set("เกิดข้อผิดพลาด กรุณาลองใหม่")
            else:
                if on_success:
                    on_success(result)
        self._pending = remaining

        for event in self._event_bus.drain():
            if isinstance(event, StateChanged):
                self._render_state(event.state)
        if self.root.winfo_exists():
            self.root.after(100, self._drain_events)

    def _render_state(self, state: AppState) -> None:
        signed_in = state.auth_status is AuthStatus.AUTHENTICATED
        self._status.set(
            {
                AuthStatus.SIGNED_OUT: "ยังไม่ได้เข้าสู่ระบบ",
                AuthStatus.AUTHENTICATING: "กำลังเข้าสู่ระบบ…",
                AuthStatus.AUTHENTICATED: "เข้าสู่ระบบแล้ว",
                AuthStatus.FAILED: "เข้าสู่ระบบไม่สำเร็จ",
            }[state.auth_status]
        )
        self._account.set(state.user_email or "")
        self._status_badge.configure(
            text_color=PALETTE.success if signed_in else PALETTE.text_muted,
        )
        self._render_entitlement(state)

        if signed_in:
            self._show_program_view()
        else:
            if self._password_dialog is not None:
                self._close_password_dialog()
            self._show_auth_view()

        self._set_auth_enabled(
            signed_in=signed_in,
            authenticating=state.auth_status is AuthStatus.AUTHENTICATING,
        )
        self._game_connection_status.set(
            "สถานะเกม: เข้าเกมแล้ว (พบ pso2.exe)"
            if state.game_process_running
            else "สถานะเกม: ยังไม่เข้าเกม (รอ pso2.exe)"
        )
        proxy_text = {
            ProxyStatus.STOPPED: "ProxyCore: ยังไม่ทำงาน",
            ProxyStatus.STARTING: "ProxyCore: กำลังเริ่มทำงาน...",
            ProxyStatus.RUNNING: "ProxyCore: ทำงานแล้ว",
            ProxyStatus.STOPPING: "ProxyCore: กำลังหยุดทำงาน...",
            ProxyStatus.FAILED: "ProxyCore: เริ่มทำงานไม่สำเร็จ",
        }[state.proxy_status]
        self._proxy_connection_status.set(proxy_text)
        self._redeem_button.configure(state="normal" if signed_in else "disabled")
        can_launch_game = (
            signed_in
            and state.session_id is not None
            and entitlement_is_active(state.entitlement)
            and bool(self._game_path.get().strip())
            and state.proxy_status not in {
                ProxyStatus.STARTING,
                ProxyStatus.STOPPING,
            }
            and state.game_status not in {
                GameStatus.STARTING,
                GameStatus.RUNNING,
            }
        )
        self._launch_game_button.configure(
            state="normal" if can_launch_game else "disabled"
        )
        if state.last_error:
            self._error.set(state.last_error)

    def _render_entitlement(self, state: AppState) -> None:
        entitlement = state.entitlement
        if entitlement is None:
            self._entitlement.set(
                "เหลือ 0 วัน • เติมวันด้วยคูปองเพื่อเริ่มต้น"
            )
            self._entitlement_label.configure(text_color=PALETTE.warning)
            return
        if entitlement.valid_until is None:
            self._entitlement.set("ใช้งานได้ • ไม่จำกัดวัน")
            self._entitlement_label.configure(text_color=PALETTE.success)
            return
        now = datetime.now(entitlement.valid_until.tzinfo)
        remaining = entitlement.valid_until - now
        if entitlement.status is EntitlementStatus.ACTIVE and remaining.total_seconds() > 0:
            # Always show an integer day count.  A newly expired entitlement
            # must read 0 days instead of being rounded up to 1.
            days = max(0, int((remaining.total_seconds() + 86399) // 86400))
            self._entitlement.set(
                f"ใช้งานได้ • เหลือประมาณ {days} วัน • "
                f"หมดอายุ {entitlement.valid_until:%d/%m/%Y %H:%M}"
            )
            self._entitlement_label.configure(text_color=PALETTE.success)
        else:
            if state.game_process_running:
                self._entitlement.set(
                    "สิทธิ์หมดอายุแล้ว • จะตัดการเชื่อมต่อหลังออกจากเกม"
                )
                self._entitlement_label.configure(text_color=PALETTE.warning)
            else:
                self._entitlement.set(
                    f"หมดอายุแล้ว • เหลือ 0 วัน • "
                    f"{entitlement.valid_until:%d/%m/%Y %H:%M}"
                )
                self._entitlement_label.configure(text_color=PALETTE.danger)

    def _set_auth_enabled(self, *, signed_in: bool, authenticating: bool) -> None:
        self._login_button.configure(
            state="normal" if not signed_in and not authenticating else "disabled"
        )
        self._register_button.configure(
            state="normal" if not signed_in and not authenticating else "disabled"
        )

    # ------------------------------------------------------------------
    # Auto-connect: poll for the actual pso2.exe client process.
    # ------------------------------------------------------------------
    def _poll_game_process(self) -> None:
        """Every 3 seconds, check if a PSO2 process appeared.

        Detection is always enabled.  It updates the status panel and starts
        ProxyCore only after the actual game client is present.
        """
        if not self._process_detection_pending:
            # Run detection in background to avoid blocking the UI.
            self._process_detection_pending = True
            self._submit(
                is_any_process_running,
                self._on_game_detected,
            )

        if self.root.winfo_exists():
            self.root.after(3_000, self._poll_game_process)

    def _on_game_detected(self, detected: bool) -> None:
        """Callback when process detection finishes."""
        self._process_detection_pending = False
        state = self._controller.state
        if state.game_process_running is not detected:
            self._controller.dispatch(GameProcessStateChanged(detected))
        if not detected:
            return
        # Double-check conditions haven't changed while the check ran.
        state = self._controller.state
        if (
            state.auth_status is not AuthStatus.AUTHENTICATED
            or state.session_id is None
            or not entitlement_is_active(state.entitlement)
            or state.proxy_status in {ProxyStatus.STARTING, ProxyStatus.RUNNING}
        ):
            return
        # Auto-start ProxyCore only after pso2.exe was detected.  Tweaker is
        # launched separately by the login checkbox or the launch button.
        self._service.start_proxy()

    def _heartbeat(self) -> None:
        if self._controller.state.session_id:
            self._submit(self._service.heartbeat)
        if self.root.winfo_exists():
            self.root.after(30_000, self._heartbeat)

    @staticmethod
    def _add_heading(frame: ctk.CTkBaseClass) -> None:
        ctk.CTkLabel(
            frame,
            text="NEKO FAMILY PROXY PSO2NGS",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", pady=2)

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            self._service.shutdown()
        except Exception:
            pass
        # Do not block the UI thread waiting for background tasks to finish.
        self._executor.shutdown(wait=False, cancel_futures=True)
        if hasattr(self, "_tray_icon") and self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.root.quit()
        self.root.destroy()
