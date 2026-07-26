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

from .theme import PALETTE, apply_theme


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
        self.root.geometry("960x760")
        self.root.minsize(820, 680)
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
        self._register_recovery_email = tk.StringVar()
        self._register_password = tk.StringVar()
        self._register_password_confirm = tk.StringVar()
        self._reset_email = tk.StringVar()
        self._coupon_code = tk.StringVar()
        self._game_path = tk.StringVar(value=game_default_path)
        self._game_path_store = game_path_store

        self._build_layout(logo_path)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain_events)
        self.root.after(30_000, self._heartbeat)
        self._submit(self._service.restore_session, self._restore_completed)

    def _build_layout(self, logo_path: Path | None) -> None:
        shell = ctk.CTkFrame(
            self.root,
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=24,
        )
        shell.pack(fill="both", expand=True, padx=28, pady=28)

        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(20, 4))
        if logo_path and logo_path.is_file():
            try:
                from PIL import Image

                self._logo_image = ctk.CTkImage(
                    Image.open(logo_path),
                    size=(190, 66),
                )
                ctk.CTkLabel(
                    header,
                    image=self._logo_image,
                    text="",
                    fg_color="transparent",
                ).pack(side="left")
            except Exception:
                self._add_heading(header)
        else:
            self._add_heading(header)

        title = ctk.CTkFrame(header, fg_color="transparent")
        title.pack(side="left", padx=(18, 0), pady=4)
        ctk.CTkLabel(
            title,
            text="Neko Family Proxy",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w")
        ctk.CTkLabel(
            title,
            text="บัญชีและการใช้งาน",
            font=ctk.CTkFont(size=12),
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", pady=(2, 0))

        self._status_badge = ctk.CTkLabel(
            header,
            textvariable=self._status,
            fg_color=PALETTE.surface,
            corner_radius=12,
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self._status_badge.pack(side="right", padx=14, pady=8, ipadx=10, ipady=5)

        self._content = ctk.CTkScrollableFrame(
            shell,
            fg_color="transparent",
            scrollbar_button_color=PALETTE.primary_soft,
            scrollbar_button_hover_color=PALETTE.primary,
        )
        self._content.pack(fill="both", expand=True, padx=14, pady=(4, 16))
        self._build_auth_view()
        self._build_program_view()
        self._show_auth_view()

        footer = ctk.CTkLabel(
            shell,
            text=f"Version {__version__}",
            font=ctk.CTkFont(size=10),
            text_color=PALETTE.text_muted,
        )
        footer.pack(pady=(0, 12))

    def _build_auth_view(self) -> None:
        self._auth_view = ctk.CTkFrame(
            self._content,
            fg_color="transparent",
        )
        intro = self._card(self._auth_view)
        ctk.CTkLabel(
            intro,
            text="เข้าสู่ระบบและสมัครสมาชิก",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=24, pady=(22, 2))
        ctk.CTkLabel(
            intro,
            text="เข้าสู่ระบบหรือสมัครสมาชิกเพื่อเริ่มใช้งานและดูวันคงเหลือ",
            text_color=PALETTE.text_muted,
            wraplength=680,
        ).pack(anchor="w", padx=24, pady=(0, 16))

        self._auth_panel = ctk.CTkTabview(
            intro,
            fg_color=PALETTE.surface,
            segmented_button_selected_color=PALETTE.primary,
            segmented_button_selected_hover_color=PALETTE.primary_hover,
            text_color=PALETTE.text,
            corner_radius=14,
        )
        self._auth_panel.pack(fill="x", padx=18, pady=(0, 18))

        login = self._auth_panel.add("เข้าสู่ระบบ")
        ctk.CTkLabel(
            login,
            text="ใช้บัญชี Neko Family เพื่อเข้าสู่โปรแกรม",
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=18, pady=(16, 0))
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
        self._login_button.pack(fill="x", padx=18, pady=(14, 20))

        register = self._auth_panel.add("สมัครสมาชิก")
        ctk.CTkLabel(
            register,
            text="สร้างบัญชีใหม่ โดยไม่ต้องยืนยันอีเมล",
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=18, pady=(16, 0))
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
        self._field_label(register, "อีเมลสำหรับกู้คืนรหัสผ่าน")
        self._register_recovery_email_entry = self._entry(
            register,
            "เช่น yourname@example.com",
            self._register_recovery_email,
        )
        self._register_email_entry.configure(placeholder_text="เช่น tester_01")
        self._register_email_entry.bind("<Return>", lambda _event: self._register())
        self._register_password_entry.bind("<Return>", lambda _event: self._register())
        self._register_password_confirm_entry.bind(
            "<Return>", lambda _event: self._register()
        )
        self._register_recovery_email_entry.bind(
            "<Return>", lambda _event: self._register()
        )
        self._register_button = self._primary_button(
            register, "สร้างบัญชี", self._register
        )
        self._register_button.pack(fill="x", padx=18, pady=(14, 20))

        change = self._auth_panel.add("ลืมรหัสผ่าน")
        ctk.CTkLabel(
            change,
            text="กรอกอีเมลที่ใช้สมัคร เราจะส่งลิงก์สำหรับตั้งรหัสผ่านใหม่ให้",
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=18, pady=(16, 0))
        self._field_label(change, "อีเมลที่ใช้สมัคร")
        self._reset_email_entry = self._entry(
            change,
            "เช่น yourname@example.com",
            self._reset_email,
        )
        self._reset_email_entry.bind(
            "<Return>", lambda _event: self._request_password_reset()
        )
        self._change_password_button = self._primary_button(
            change, "ส่งลิงก์ตั้งรหัสผ่านใหม่", self._request_password_reset
        )
        self._change_password_button.pack(fill="x", padx=18, pady=(14, 20))

        self._auth_hint = ctk.CTkLabel(
            self._auth_view,
            text="เข้าสู่ระบบเพื่อเริ่มใช้งาน",
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._auth_hint.pack(pady=(10, 0))
        ctk.CTkLabel(
            self._auth_view,
            textvariable=self._notice,
            text_color=PALETTE.success,
            wraplength=700,
        ).pack(pady=(8, 0))
        ctk.CTkLabel(
            self._auth_view,
            textvariable=self._error,
            text_color=PALETTE.danger,
            wraplength=700,
        ).pack(pady=(4, 8))

    def _build_program_view(self) -> None:
        self._program_view = ctk.CTkFrame(
            self._content,
            fg_color="transparent",
        )

        account = self._card(self._program_view)
        account_header = ctk.CTkFrame(account, fg_color="transparent")
        account_header.pack(fill="x", padx=22, pady=(18, 4))
        ctk.CTkLabel(
            account_header,
            text="พื้นที่ใช้งานของคุณ",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=PALETTE.text,
        ).pack(side="left")
        self._account_label = ctk.CTkLabel(
            account_header,
            textvariable=self._account,
            text_color=PALETTE.text_muted,
        )
        self._account_label.pack(side="right", pady=4)

        actions = ctk.CTkFrame(account, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(8, 16))
        self._secondary_button(
            actions,
            "เปลี่ยนรหัสผ่าน",
            self._open_password_tab,
        ).pack(side="left", padx=6)
        self._secondary_button(
            actions,
            "ออกจากระบบ",
            self._sign_out,
        ).pack(side="right", padx=6)

        entitlement = self._card(self._program_view)
        ctk.CTkLabel(
            entitlement,
            text="วันใช้งานคงเหลือ",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=22, pady=(18, 4))
        self._entitlement_label = ctk.CTkLabel(
            entitlement,
            textvariable=self._entitlement,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=PALETTE.text,
        )
        self._entitlement_label.pack(anchor="w", padx=22, pady=(0, 18))

        usage = self._card(self._program_view)
        ctk.CTkLabel(
            usage,
            text="เติมวันใช้งาน",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=22, pady=(18, 2))
        ctk.CTkLabel(
            usage,
            text="กรอกรหัสคูปองเพื่อเพิ่มวันให้บัญชีนี้",
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=22, pady=(0, 6))
        self._coupon_entry = ctk.CTkEntry(
            usage,
            textvariable=self._coupon_code,
            placeholder_text="NEKO-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX",
            height=40,
        )
        self._coupon_entry.pack(fill="x", padx=22, pady=6)
        self._redeem_button = self._primary_button(
            usage, "เติมวันจากคูปอง", self._redeem_coupon
        )
        self._redeem_button.pack(fill="x", padx=22, pady=(6, 18))

        proxy = self._card(self._program_view)
        ctk.CTkLabel(
            proxy,
            text="เริ่มใช้งาน",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=22, pady=(18, 2))
        ctk.CTkLabel(
            proxy,
            text="กดเริ่มใช้งานเพื่อเชื่อมต่อและเปิดเกมตามไฟล์ที่เลือก",
            text_color=PALETTE.text_muted,
            wraplength=680,
        ).pack(anchor="w", padx=22, pady=(0, 10))
        controls = ctk.CTkFrame(proxy, fg_color="transparent")
        controls.pack(fill="x", padx=16, pady=(0, 18))
        self._start_button = self._primary_button(
            controls, "เริ่มใช้งาน", self._start_usage
        )
        self._start_button.pack(side="left", fill="x", expand=True, padx=6)
        self._stop_button = self._secondary_button(
            controls,
            "หยุดการเชื่อมต่อ",
            lambda: self._controller.dispatch(StopProxyRequested()),
        )
        self._stop_button.pack(side="left", fill="x", expand=True, padx=6)
        self._start_button.configure(state="disabled")
        self._stop_button.configure(state="disabled")

        game = self._card(self._program_view)
        ctk.CTkLabel(
            game,
            text="ตั้งค่าไฟล์เปิดเกม",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=22, pady=(18, 2))
        ctk.CTkLabel(
            game,
            text="เลือกไฟล์เปิดเกม ระบบจะจำตำแหน่งไว้สำหรับครั้งถัดไป",
            text_color=PALETTE.text_muted,
            wraplength=680,
        ).pack(anchor="w", padx=22, pady=(0, 8))
        game_path_row = ctk.CTkFrame(game, fg_color="transparent")
        game_path_row.pack(fill="x", padx=16, pady=(0, 8))
        self._game_path_entry = ctk.CTkEntry(
            game_path_row,
            textvariable=self._game_path,
            height=38,
        )
        self._game_path_entry.pack(side="left", fill="x", expand=True, padx=6)
        self._secondary_button(
            game_path_row,
            "เลือกไฟล์",
            self._choose_game,
        ).pack(side="left", padx=6)
        game_controls = ctk.CTkFrame(game, fg_color="transparent")
        game_controls.pack(fill="x", padx=16, pady=(0, 18))
        self._launch_game_button = self._primary_button(
            game_controls,
            "เปิดเกม",
            self._launch_game,
        )
        self._launch_game_button.pack(side="left", fill="x", expand=True, padx=6)
        self._stop_game_button = self._secondary_button(
            game_controls,
            "ปิดเกม",
            lambda: self._controller.dispatch(StopGameRequested()),
        )
        self._stop_game_button.pack(side="left", fill="x", expand=True, padx=6)
        self._launch_game_button.configure(state="disabled")
        self._stop_game_button.configure(state="disabled")

        self._message_frame = ctk.CTkFrame(
            self._program_view, fg_color="transparent"
        )
        self._message_frame.pack(fill="x", padx=18, pady=(6, 0))
        ctk.CTkLabel(
            self._message_frame,
            textvariable=self._notice,
            text_color=PALETTE.success,
            wraplength=700,
        ).pack(anchor="w")
        ctk.CTkLabel(
            self._message_frame,
            textvariable=self._error,
            text_color=PALETTE.danger,
            wraplength=700,
        ).pack(anchor="w", pady=(4, 10))

    @staticmethod
    def _card(parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=PALETTE.surface,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=16,
        )
        card.pack(fill="x", padx=12, pady=8)
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
            height=40,
        )
        entry.pack(fill="x", padx=18, pady=(10, 0))
        return entry

    @staticmethod
    def _field_label(parent: ctk.CTkBaseClass, text: str) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            text_color=PALETTE.text,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(10, 0))

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
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            height=40,
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
            corner_radius=10,
            height=36,
            command=command,
        )

    def _show_auth_view(self) -> None:
        self._program_view.pack_forget()
        if not self._auth_view.winfo_manager():
            self._auth_view.pack(fill="x", padx=12, pady=(4, 12))

    def _show_program_view(self) -> None:
        self._auth_view.pack_forget()
        if not self._program_view.winfo_manager():
            self._program_view.pack(fill="x", padx=12, pady=(4, 12))

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
                self._register_recovery_email.get(),
            ),
            self._register_succeeded,
        )

    def _register_succeeded(self, _: RegistrationResult) -> None:
        self._register_password.set("")
        self._register_password_confirm.set("")
        self._register_recovery_email.set("")
        self._notice.set(
            "สมัครสมาชิกสำเร็จ ใช้ชื่อผู้ใช้และรหัสผ่านเข้าสู่ระบบได้เลย"
        )

    def _request_password_reset(self) -> None:
        self._submit(
            lambda: self._service.request_password_reset(self._reset_email.get()),
            self._password_reset_requested,
        )

    def _password_reset_requested(self, _: Any) -> None:
        self._reset_email.set("")
        self._notice.set("ส่งลิงก์ตั้งรหัสผ่านใหม่แล้ว กรุณาตรวจสอบอีเมล")

    def _open_password_tab(self) -> None:
        self._show_auth_view()
        self._auth_panel.set("ลืมรหัสผ่าน")
        self._notice.set("")
        self._error.set("")

    def _sign_out(self) -> None:
        self._submit(self._service.sign_out, self._signed_out)

    def _signed_out(self, _: Any) -> None:
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
        self._change_password_button.configure(
            state="normal" if not signed_in and not authenticating else "disabled"
        )

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
            font=ctk.CTkFont(size=25, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(side="left", pady=8)

    def close(self) -> None:
        self._controller.dispatch(StopGameRequested())
        self._controller.dispatch(StopProxyRequested())
        self._service.shutdown()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()
