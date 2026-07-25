from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk
import tkinter as tk

from neko_launcher import __version__
from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.application.services import LauncherService
from neko_launcher.domain.events import StateChanged, StopProxyRequested
from neko_launcher.domain.models import (
    AppState,
    AuthStatus,
    EntitlementStatus,
    ProxyStatus,
    RegistrationResult,
)
from neko_launcher.infrastructure.event_bus import EventBus

from .theme import PALETTE, apply_theme


class AppWindow:
    """Customer UI for Supabase Auth, coupons, entitlement, and proxy lifecycle."""

    def __init__(
        self,
        controller: ApplicationController,
        service: LauncherService,
        event_bus: EventBus,
        logo_path: Path | None = None,
        icon_path: Path | None = None,
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
        self.root.title("Neko Family Launcher V2")
        self.root.geometry("640x760")
        self.root.minsize(580, 680)
        self.root.configure(fg_color=PALETTE.background)
        if icon_path and icon_path.is_file():
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        self._status = tk.StringVar(value="ยังไม่ได้เข้าสู่ระบบ")
        self._account = tk.StringVar(value="")
        self._entitlement = tk.StringVar(value="ยังไม่มีสิทธิ์ใช้งาน")
        self._error = tk.StringVar(value="")
        self._notice = tk.StringVar(value="")
        self._login_email = tk.StringVar()
        self._login_password = tk.StringVar()
        self._register_email = tk.StringVar()
        self._register_password = tk.StringVar()
        self._coupon_code = tk.StringVar()

        self._build_layout(logo_path)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain_events)
        self.root.after(30_000, self._heartbeat)
        self._submit(self._service.restore_session)

    def _build_layout(self, logo_path: Path | None) -> None:
        frame = ctk.CTkScrollableFrame(
            self.root,
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=20,
        )
        frame.pack(fill="both", expand=True, padx=24, pady=24)

        if logo_path and logo_path.is_file():
            try:
                from PIL import Image

                self._logo_image = ctk.CTkImage(
                    Image.open(logo_path),
                    size=(240, 84),
                )
                ctk.CTkLabel(
                    frame,
                    image=self._logo_image,
                    text="",
                    fg_color="transparent",
                ).pack(pady=(18, 2))
            except Exception:
                self._add_heading(frame)
        else:
            self._add_heading(frame)

        ctk.CTkLabel(
            frame,
            text="Neko Family Proxy Launcher",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(pady=(0, 14))

        self._build_status_card(frame)
        self._build_auth_panel(frame)
        self._build_account_panel(frame)
        self._build_proxy_controls(frame)

        ctk.CTkLabel(
            frame,
            textvariable=self._notice,
            text_color=PALETTE.success,
            wraplength=500,
        ).pack(pady=(6, 0))
        ctk.CTkLabel(
            frame,
            textvariable=self._error,
            text_color=PALETTE.danger,
            wraplength=500,
        ).pack(pady=(4, 10))
        ctk.CTkLabel(
            frame,
            text=f"Version {__version__}",
            font=ctk.CTkFont(size=10),
            text_color=PALETTE.text_muted,
        ).pack(pady=(4, 14))

    def _build_status_card(self, parent: ctk.CTkBaseClass) -> None:
        card = ctk.CTkFrame(
            parent,
            fg_color=PALETTE.surface,
            corner_radius=14,
        )
        card.pack(fill="x", padx=28, pady=6)
        ctk.CTkLabel(
            card,
            text="สถานะ Launcher",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(
            card,
            textvariable=self._status,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16)
        ctk.CTkLabel(
            card,
            textvariable=self._account,
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=16, pady=(2, 0))
        ctk.CTkLabel(
            card,
            textvariable=self._entitlement,
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=16, pady=(2, 12))

    def _build_auth_panel(self, parent: ctk.CTkBaseClass) -> None:
        self._auth_panel = ctk.CTkTabview(
            parent,
            fg_color=PALETTE.surface,
            segmented_button_selected_color=PALETTE.primary,
            segmented_button_selected_hover_color=PALETTE.primary_hover,
            text_color=PALETTE.text,
        )
        self._auth_panel.pack(fill="x", padx=28, pady=(12, 6))
        login = self._auth_panel.add("เข้าสู่ระบบ")
        register = self._auth_panel.add("สมัครสมาชิก")

        self._login_email_entry = self._entry(
            login,
            "อีเมล",
            self._login_email,
        )
        self._login_password_entry = self._entry(
            login,
            "รหัสผ่าน",
            self._login_password,
            show="•",
        )
        self._primary_button(
            login,
            "เข้าสู่ระบบ",
            self._login,
        ).pack(fill="x", padx=18, pady=(6, 16))

        self._register_email_entry = self._entry(
            register,
            "อีเมล",
            self._register_email,
        )
        self._register_password_entry = self._entry(
            register,
            "รหัสผ่านอย่างน้อย 8 ตัวอักษร",
            self._register_password,
            show="•",
        )
        self._primary_button(
            register,
            "สร้างบัญชี",
            self._register,
        ).pack(fill="x", padx=18, pady=(6, 16))

    def _build_account_panel(self, parent: ctk.CTkBaseClass) -> None:
        self._account_panel = ctk.CTkFrame(
            parent,
            fg_color=PALETTE.surface,
            corner_radius=14,
        )
        ctk.CTkLabel(
            self._account_panel,
            text="เติมสิทธิ์ด้วยคูปอง",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", padx=18, pady=(14, 4))
        self._coupon_entry = ctk.CTkEntry(
            self._account_panel,
            textvariable=self._coupon_code,
            placeholder_text="NEKO-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX",
            height=38,
        )
        self._coupon_entry.pack(fill="x", padx=18, pady=6)
        row = ctk.CTkFrame(self._account_panel, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(4, 14))
        self._primary_button(
            row,
            "ใช้คูปอง",
            self._redeem_coupon,
        ).pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkButton(
            row,
            text="ออกจากระบบ",
            fg_color="transparent",
            hover_color=PALETTE.card,
            border_color=PALETTE.primary_soft,
            border_width=2,
            text_color=PALETTE.primary_dark,
            command=self._sign_out,
        ).pack(side="left", fill="x", expand=True, padx=6)

    def _build_proxy_controls(self, parent: ctk.CTkBaseClass) -> None:
        controls = ctk.CTkFrame(parent, fg_color="transparent")
        controls.pack(fill="x", padx=22, pady=(12, 6))
        self._start_button = self._primary_button(
            controls,
            "เริ่ม Proxy",
            self._service.start_proxy,
        )
        self._start_button.pack(
            side="left",
            fill="x",
            expand=True,
            padx=6,
            ipady=4,
        )
        self._stop_button = ctk.CTkButton(
            controls,
            text="หยุด Proxy",
            fg_color="transparent",
            hover_color=PALETTE.surface,
            border_color=PALETTE.primary_soft,
            border_width=2,
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            command=lambda: self._controller.dispatch(
                StopProxyRequested()
            ),
        )
        self._stop_button.pack(
            side="left",
            fill="x",
            expand=True,
            padx=6,
            ipady=4,
        )
        self._start_button.configure(state="disabled")
        self._stop_button.configure(state="disabled")

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
            height=38,
        )
        entry.pack(fill="x", padx=18, pady=(10, 0))
        return entry

    def _primary_button(
        self,
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
            command=command,
        )

    def _login(self) -> None:
        email = self._login_email.get()
        password = self._login_password.get()

        def complete(_: Any) -> None:
            self._login_password.set("")
            self._notice.set("เข้าสู่ระบบสำเร็จ")

        self._submit(
            lambda: self._service.sign_in(email, password),
            complete,
        )

    def _register(self) -> None:
        email = self._register_email.get()
        password = self._register_password.get()

        def complete(result: RegistrationResult) -> None:
            self._register_password.set("")
            if result.requires_email_confirmation:
                self._notice.set(
                    "สมัครสมาชิกแล้ว กรุณาตรวจสอบอีเมลเพื่อยืนยันบัญชี"
                )
            else:
                self._notice.set("สมัครสมาชิกและเข้าสู่ระบบสำเร็จ")

        self._submit(
            lambda: self._service.sign_up(email, password),
            complete,
        )

    def _sign_out(self) -> None:
        def complete(_: Any) -> None:
            self._coupon_code.set("")
            self._notice.set("ออกจากระบบแล้ว")

        self._submit(self._service.sign_out, complete)

    def _redeem_coupon(self) -> None:
        code = self._coupon_code.get()

        def complete(result: Any) -> None:
            self._coupon_code.set("")
            self._notice.set(
                f"เติมสิทธิ์สำเร็จ {result.days_added} วัน "
                f"หมดอายุ {result.valid_until:%d/%m/%Y}"
            )

        self._submit(
            lambda: self._service.redeem_coupon(code),
            complete,
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

        if state.entitlement is None:
            self._entitlement.set("ยังไม่มีสิทธิ์ใช้งาน")
        elif state.entitlement.valid_until is None:
            self._entitlement.set("มีสิทธิ์ใช้งาน")
        else:
            self._entitlement.set(
                "มีสิทธิ์ใช้งานถึง "
                f"{state.entitlement.valid_until:%d/%m/%Y %H:%M}"
            )

        if signed_in:
            self._auth_panel.pack_forget()
            if not self._account_panel.winfo_manager():
                self._account_panel.pack(
                    fill="x",
                    padx=28,
                    pady=(12, 6),
                )
        else:
            self._account_panel.pack_forget()
            if not self._auth_panel.winfo_manager():
                self._auth_panel.pack(
                    fill="x",
                    padx=28,
                    pady=(12, 6),
                )

        can_start = (
            signed_in
            and state.session_id is not None
            and state.entitlement is not None
            and state.entitlement.status is EntitlementStatus.ACTIVE
            and state.proxy_status is not ProxyStatus.RUNNING
        )
        can_stop = state.proxy_status in {
            ProxyStatus.STARTING,
            ProxyStatus.RUNNING,
        }
        self._start_button.configure(
            state="normal" if can_start else "disabled"
        )
        self._stop_button.configure(
            state="normal" if can_stop else "disabled"
        )
        if state.last_error:
            self._error.set(state.last_error)

    def _heartbeat(self) -> None:
        if self._controller.state.session_id:
            self._submit(self._service.heartbeat)
        if self.root.winfo_exists():
            self.root.after(30_000, self._heartbeat)

    def _add_heading(self, frame: ctk.CTkBaseClass) -> None:
        ctk.CTkLabel(
            frame,
            text="NEKO FAMILY",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(pady=(28, 8))

    def close(self) -> None:
        self._controller.dispatch(StopProxyRequested())
        self._service.shutdown()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()
