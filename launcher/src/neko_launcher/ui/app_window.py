from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog

from neko_launcher import __version__
from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.application.services import LauncherService
from neko_launcher.domain.events import (
    LaunchGameRequested,
    StateChanged,
    StopGameRequested,
    StopProxyRequested,
)
from neko_launcher.domain.models import (
    AppState,
    AuthStatus,
    EntitlementStatus,
    GameStatus,
    ProxyStatus,
    RegistrationResult,
)
from neko_launcher.infrastructure.event_bus import EventBus
from neko_launcher.infrastructure.process_detector import is_any_process_running

from .theme import FONT_FAMILY, PALETTE, apply_theme


class AppWindow:
    """Two-stage customer UI: account access first, launcher tools after login."""

    def __init__(
        self,
        controller: ApplicationController,
        service: LauncherService,
        event_bus: EventBus,
        logo_path: Path | None = None,
        icon_path: Path | None = None,
        game_default_path: str = "Tweaker.exe",
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

        self.root = ctk.CTk()
        self.root.title("Neko Family Proxy Launcher")
        self.root.minsize(420, 640)
        self.root.configure(fg_color=PALETTE.background)
        if icon_path and icon_path.is_file():
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        self._status = tk.StringVar(value="กำลังเตรียมข้อมูล…")
        self._account = tk.StringVar(value="")
        self._entitlement = tk.StringVar(value="ยังไม่มีวันใช้งาน")
        self._error = tk.StringVar(value="")
        self._notice = tk.StringVar(value="")
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
        self._auto_connect = tk.BooleanVar(value=True)
        self._auto_launch = tk.BooleanVar(value=True)

        self._build_layout(logo_path)
        self._fit_portrait_window()
        self.root.after_idle(self._fit_portrait_window)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain_events)
        self.root.after(30_000, self._heartbeat)
        self.root.after(3_000, self._poll_game_process)
        self._submit(self._service.restore_session, self._restore_completed)

    def _fit_portrait_window(self) -> None:
        """Centered One UI card."""
        self.root.update_idletasks()
        screen_w = int(self.root.winfo_screenwidth())
        screen_h = int(self.root.winfo_screenheight())
        width = 480
        height = 850
        width = min(width, screen_w - 48)
        height = min(height, screen_h - 48)
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(420, 640)

    def _build_layout(self, logo_path: Path | None) -> None:
        shell = ctk.CTkFrame(
            self.root,
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=20,
        )
        shell.pack(fill="both", expand=True, padx=12, pady=12)

        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(8, 2))

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left", fill="x", expand=True)
        if logo_path and logo_path.is_file():
            try:
                from PIL import Image

                self._logo_image = ctk.CTkImage(
                    Image.open(logo_path),
                    size=(110, 38),
                )
                ctk.CTkLabel(
                    brand,
                    image=self._logo_image,
                    text="",
                    fg_color="transparent",
                ).pack(anchor="w")
            except Exception:
                self._add_heading(brand)
        else:
            self._add_heading(brand)

        ctk.CTkLabel(
            brand,
            text="Neko Family Proxy",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(
            brand,
            text="บัญชีและการใช้งาน",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=PALETTE.text_muted,
        ).pack(anchor="w")

        self._status_badge = ctk.CTkLabel(
            header,
            textvariable=self._status,
            fg_color=PALETTE.surface,
            corner_radius=10,
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
        )
        self._status_badge.pack(side="right", padx=(6, 0), pady=2, ipadx=6, ipady=3)

        self._content = ctk.CTkFrame(shell, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=6, pady=(2, 4))
        self._build_auth_view()
        self._build_program_view()
        self._show_auth_view()

        footer = ctk.CTkLabel(
            shell,
            text=f"Version {__version__}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=PALETTE.text_muted,
        )
        footer.pack(pady=(0, 6))

    def _build_auth_view(self) -> None:
        self._auth_view = ctk.CTkFrame(
            self._content,
            fg_color="transparent",
        )
        intro = self._card(self._auth_view)
        intro.pack_configure(fill="both", expand=True)
        ctk.CTkLabel(
            intro,
            text="เข้าสู่ระบบและสมัครสมาชิก",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=14, pady=(10, 6))

        self._auth_panel = ctk.CTkTabview(
            intro,
            fg_color=PALETTE.surface,
            segmented_button_selected_color=PALETTE.primary,
            segmented_button_selected_hover_color=PALETTE.primary_hover,
            text_color=PALETTE.text,
            corner_radius=12,
        )
        self._auth_panel.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        login = self._auth_panel.add("เข้าสู่ระบบ")
        self._field_label(login, "ชื่อผู้ใช้สำหรับเข้าสู่ระบบ")
        self._login_email_entry = self._entry(
            login, "ชื่อผู้ใช้", self._login_email
        )
        self._field_label(login, "รหัสผ่าน")
        self._login_password_entry = self._entry(
            login, "รหัสผ่าน", self._login_password, show="●"
        )
        self._login_email_entry.configure(placeholder_text="ชื่อผู้ใช้")
        self._login_email_entry.bind("<Return>", lambda _event: self._login())
        self._login_password_entry.bind("<Return>", lambda _event: self._login())
        self._login_button = self._primary_button(
            login, "เข้าสู่ระบบ", self._login
        )
        self._login_button.pack(fill="x", padx=14, pady=(10, 6))
        ctk.CTkLabel(
            login,
            text="ลืมรหัสผ่าน กรุณาติดต่อผู้ดูแลระบบ",
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        ).pack(pady=(0, 12))

        register = self._auth_panel.add("สมัครสมาชิก")
        self._field_label(register, "ชื่อผู้ใช้")
        self._register_email_entry = self._entry(
            register, "เช่น tester_01", self._register_username
        )
        self._field_label(register, "รหัสผ่าน (อย่างน้อย 8 ตัวอักษร)")
        self._register_password_entry = self._entry(
            register,
            "รหัสผ่านอย่างน้อย 8 ตัวอักษร",
            self._register_password,
            show="●",
        )
        self._field_label(register, "ยืนยันรหัสผ่าน")
        self._register_password_confirm_entry = self._entry(
            register,
            "ยืนยันรหัสผ่าน",
            self._register_password_confirm,
            show="●",
        )
        self._register_email_entry.configure(placeholder_text="เช่น tester_01")
        self._register_email_entry.bind("<Return>", lambda _event: self._register())
        self._register_password_entry.bind("<Return>", lambda _event: self._register())
        self._register_password_confirm_entry.bind(
            "<Return>", lambda _event: self._register()
        )
        self._register_button = self._primary_button(
            register, "สร้างบัญชี", self._register
        )
        self._register_button.pack(fill="x", padx=14, pady=(10, 12))

        self._auth_hint = ctk.CTkLabel(
            self._auth_view,
            text="เข้าสู่ระบบเพื่อเริ่มใช้งาน",
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
        )
        self._auth_hint.pack(pady=(4, 0))
        ctk.CTkLabel(
            self._auth_view,
            textvariable=self._notice,
            text_color=PALETTE.success,
            wraplength=360,
        ).pack(pady=(2, 0))
        ctk.CTkLabel(
            self._auth_view,
            textvariable=self._error,
            text_color=PALETTE.danger,
            wraplength=360,
        ).pack(pady=(2, 2))

    def _build_program_view(self) -> None:
        self._program_view = ctk.CTkScrollableFrame(
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
            "ออกจากระบบ",
            self._sign_out,
        ).pack(side="right", padx=4)

        password_card = self._card(self._program_view)
        ctk.CTkLabel(
            password_card,
            text="เปลี่ยนรหัสผ่าน",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=14, pady=(10, 4))
        self._new_password_entry = self._entry(
            password_card,
            "รหัสผ่านใหม่อย่างน้อย 8 ตัวอักษร",
            self._new_password,
            show="●",
        )
        self._new_password_confirm_entry = self._entry(
            password_card,
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
        self._change_password_button = self._primary_button(
            password_card,
            "เปลี่ยนรหัสผ่าน",
            self._change_password,
        )
        self._change_password_button.pack(fill="x", padx=14, pady=(10, 12))

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
            text="ตั้งค่าการเชื่อมต่อ (Connection Mode)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=14, pady=(10, 4))

        self._auto_connect_checkbox = ctk.CTkCheckBox(
            proxy,
            text="เชื่อมต่อโดยอัตโนมัติ เมื่อเริ่มเกม (Auto Connect)",
            variable=self._auto_connect,
            text_color=PALETTE.text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self._auto_connect_checkbox.pack(anchor="w", padx=14, pady=(0, 10))

        ctk.CTkLabel(
            proxy,
            text="ควบคุมด้วยตนเอง (Manual Control)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=14, pady=(4, 4))

        controls = ctk.CTkFrame(proxy, fg_color="transparent")
        controls.pack(fill="x", padx=10, pady=(0, 10))

        self._auto_mode_btn = ctk.CTkButton(
            controls,
            text="Auto Mode Active...",
            state="disabled",
            fg_color=PALETTE.surface,
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            corner_radius=8,
            height=34,
        )

        self._start_button = self._primary_button(
            controls, "เริ่มเชื่อมต่อ", self._start_usage
        )
        self._stop_button = self._secondary_button(
            controls,
            "หยุดเชื่อมต่อ",
            lambda: self._controller.dispatch(StopProxyRequested()),
        )
        self._start_button.configure(state="disabled")
        self._stop_button.configure(state="disabled")

        def _toggle_auto_connect(*_args: Any) -> None:
            if self._auto_connect.get():
                self._start_button.pack_forget()
                self._stop_button.pack_forget()
                self._auto_mode_btn.pack(fill="x", expand=True, padx=4)
            else:
                self._auto_mode_btn.pack_forget()
                self._start_button.pack(side="left", fill="x", expand=True, padx=4)
                self._stop_button.pack(side="left", fill="x", expand=True, padx=4)

        self._auto_connect.trace_add("write", _toggle_auto_connect)
        _toggle_auto_connect()

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

        game_controls = ctk.CTkFrame(game, fg_color="transparent")
        game_controls.pack(fill="x", padx=10, pady=(0, 10))
        self._launch_game_button = self._primary_button(
            game_controls,
            "เปิดโปรแกรม PSO2 Tweaker",
            self._launch_game,
        )
        self._launch_game_button.pack(side="left", fill="x", expand=True, padx=4)
        
        self._stop_game_button = self._secondary_button(
            game_controls,
            "ปิดโปรแกรม",
            lambda: self._controller.dispatch(StopGameRequested()),
        )
        self._stop_game_button.pack(side="left", fill="x", expand=True, padx=4)
        
        self._launch_game_button.configure(state="disabled")
        self._stop_game_button.configure(state="disabled")

        self._message_frame = ctk.CTkFrame(
            self._program_view, fg_color="transparent"
        )
        self._message_frame.pack(fill="x", padx=12, pady=(2, 0))
        ctk.CTkLabel(
            self._message_frame,
            textvariable=self._notice,
            text_color=PALETTE.success,
            wraplength=360,
        ).pack(anchor="w")
        ctk.CTkLabel(
            self._message_frame,
            textvariable=self._error,
            text_color=PALETTE.danger,
            wraplength=360,
        ).pack(anchor="w", pady=(2, 4))

    @staticmethod
    def _card(parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=PALETTE.surface,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=12,
        )
        card.pack(fill="x", padx=8, pady=4)
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
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
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
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            corner_radius=8,
            height=34,
            command=command,
        )

    @staticmethod
    def _secondary_button(
        parent: ctk.CTkBaseClass,
        text: str,
        command: Callable[[], None],
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            fg_color="transparent",
            hover_color=PALETTE.card,
            border_color=PALETTE.primary_soft,
            border_width=2,
            text_color=PALETTE.primary_dark,
            corner_radius=8,
            height=32,
            command=command,
        )

    def _show_auth_view(self) -> None:
        self._program_view.pack_forget()
        if not self._auth_view.winfo_manager():
            self._auth_view.pack(fill="both", expand=True, padx=8, pady=(2, 6))

    def _show_program_view(self) -> None:
        self._auth_view.pack_forget()
        if not self._program_view.winfo_manager():
            self._program_view.pack(fill="both", expand=True, padx=8, pady=(2, 6))

    def _login(self) -> None:
        self._submit(
            lambda: self._service.sign_in(
                self._login_email.get(),
                self._login_password.get(),
            ),
            self._login_succeeded,
        )

    def _restore_completed(self, restored: bool) -> None:
        if not restored and self._controller.state.auth_status is AuthStatus.SIGNED_OUT:
            self._status.set("ยังไม่ได้เข้าสู่ระบบ")

    def _login_succeeded(self, _: Any) -> None:
        self._login_password.set("")
        self._notice.set("เข้าสู่ระบบสำเร็จ")

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
        self._new_password.set("")
        self._new_password_confirm.set("")
        self._notice.set("เปลี่ยนรหัสผ่านสำเร็จ")

    def _sign_out(self) -> None:
        self._submit(self._service.sign_out, self._signed_out)

    def _signed_out(self, _: Any) -> None:
        self._coupon_code.set("")
        self._new_password.set("")
        self._new_password_confirm.set("")
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
        executable = self._game_path.get().strip()
        if not executable:
            self._error.set("กรุณาเลือกไฟล์เปิดเกมก่อน")
            return
        self._controller.dispatch(LaunchGameRequested(executable))

    def _start_usage(self) -> None:
        executable = self._game_path.get().strip()
        if not executable:
            self._error.set("กรุณาเลือกไฟล์เปิดเกมก่อนเริ่มใช้งาน")
            return
        self._service.start_usage(executable)

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
            fg_color=PALETTE.success if signed_in else PALETTE.surface,
            text_color=PALETTE.on_primary if signed_in else PALETTE.primary_dark,
        )
        self._render_entitlement(state)

        if signed_in:
            self._show_program_view()
        else:
            self._show_auth_view()

        self._set_auth_enabled(
            signed_in=signed_in,
            authenticating=state.auth_status is AuthStatus.AUTHENTICATING,
        )
        can_start = (
            signed_in
            and state.session_id is not None
            and state.entitlement is not None
            and state.entitlement.status is EntitlementStatus.ACTIVE
            and bool(self._game_path.get().strip())
            and state.proxy_status not in {
                ProxyStatus.STARTING,
                ProxyStatus.STOPPING,
            }
            and state.game_status is not GameStatus.STARTING
            and not (
                state.proxy_status is ProxyStatus.RUNNING
                and state.game_status is GameStatus.RUNNING
            )
        )
        can_stop = state.proxy_status in {
            ProxyStatus.STARTING,
            ProxyStatus.RUNNING,
        }
        self._start_button.configure(state="normal" if can_start else "disabled")
        self._stop_button.configure(state="normal" if can_stop else "disabled")
        self._redeem_button.configure(state="normal" if signed_in else "disabled")
        can_launch_game = (
            signed_in
            and state.session_id is not None
            and state.entitlement is not None
            and state.entitlement.status is EntitlementStatus.ACTIVE
            and state.proxy_status is ProxyStatus.RUNNING
            and state.game_status is not GameStatus.RUNNING
        )
        can_stop_game = state.game_status is GameStatus.RUNNING
        self._launch_game_button.configure(
            state="normal" if can_launch_game else "disabled"
        )
        self._stop_game_button.configure(
            state="normal" if can_stop_game else "disabled"
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
        self._reset_password_button.configure(
            state="normal" if not signed_in and not authenticating else "disabled"
        )

    # ------------------------------------------------------------------
    # Auto-connect: poll for pso2.exe / pso2launcher.exe
    # ------------------------------------------------------------------
    def _poll_game_process(self) -> None:
        """Every 3 seconds, check if a PSO2 process appeared.

        When *Auto Connect* is enabled and a target process is detected,
        automatically start ProxyCore (and the configured Tweaker) so the
        user doesn't have to press the button manually.
        """
        if self._auto_connect.get():
            state = self._controller.state
            already_running = state.proxy_status in {
                ProxyStatus.STARTING,
                ProxyStatus.RUNNING,
            }
            ready = (
                state.auth_status is AuthStatus.AUTHENTICATED
                and state.session_id is not None
                and state.entitlement is not None
                and state.entitlement.status is EntitlementStatus.ACTIVE
            )
            if ready and not already_running:
                # Run detection in background to avoid blocking the UI.
                self._submit(
                    is_any_process_running,
                    self._on_game_detected,
                )

        if self.root.winfo_exists():
            self.root.after(3_000, self._poll_game_process)

    def _on_game_detected(self, detected: bool) -> None:
        """Callback when process detection finishes."""
        if not detected:
            return
        # Double-check conditions haven't changed while the check ran.
        if not self._auto_connect.get():
            return
        state = self._controller.state
        if state.proxy_status in {ProxyStatus.STARTING, ProxyStatus.RUNNING}:
            return
        # Auto-start ProxyCore (without launching Tweaker – the user
        # already has the game running or is about to start it).
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
            text="NEKO FAMILY",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", pady=2)

    def close(self) -> None:
        self._controller.dispatch(StopGameRequested())
        self._controller.dispatch(StopProxyRequested())
        self._service.shutdown()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()
