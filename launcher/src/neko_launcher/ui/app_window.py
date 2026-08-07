from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from queue import SimpleQueue
from typing import Any, Callable
from tkinter import filedialog

import customtkinter as ctk
import tkinter as tk
from PIL import Image

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
from neko_launcher.infrastructure.process.process_detector import is_any_process_running

from .theme import FONT_FAMILY, PALETTE, apply_theme
from .platform.window_chrome import (
    apply_rounded_window_shape,
    style_native_title_bar,
    WindowDragHandler,
)
from .platform.window_scaling import fit_portrait_window, center_window
from .platform.system_tray import SystemTrayManager, drain_tray_actions
from .components.toast import ToastNotification
from .components.buttons import secondary_button
from .views.auth_view import AuthView
from .views.dashboard_view import DashboardView, open_password_dialog


class AppWindow:
    """Two-stage customer UI: account access first, launcher tools after login."""

    def __init__(
        self,
        controller: ApplicationController,
        service: LauncherService,
        event_bus: EventBus,
        logo_path: Path | None = None,
        icon_path: Path | None = None,
        game_default_path: str = "",
        game_path_store: Path | None = None,
        diagnostics: Any = None,
        debug_mode: bool = False,
        debug_log_dir: Path | None = None,
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
        self._debug_dialog: ctk.CTkToplevel | None = None
        self._closing = False
        self._tray_actions: SimpleQueue[str] = SimpleQueue()
        self._tray_manager: SystemTrayManager | None = None
        self._diagnostics = diagnostics
        self._debug_mode = debug_mode
        self._debug_log_dir = debug_log_dir

        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.title("Neko Family Proxy")
        self.root.resizable(False, False)
        self.root.configure(fg_color=PALETTE.background)
        if icon_path and icon_path.is_file():
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        self._window_size = fit_portrait_window(self.root)

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
        self._window_size = fit_portrait_window(self.root)
        self.root.after(250, lambda: center_window(self.root, self._window_size))
        self.root.after(350, self._show_initial_window)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain_events)
        self.root.after(100, lambda: drain_tray_actions(
            self._tray_actions, self.root, self.close,
        ))
        self.root.after(30_000, self._heartbeat)
        self.root.after(3_000, self._poll_game_process)
        self._submit(self._service.restore_session, self._restore_completed)

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------
    def _show_initial_window(self) -> None:
        """Ensure a borderless window is visible after Windows maps it."""
        if not self.root.winfo_exists() or self._closing:
            return
        style_native_title_bar(self.root, PALETTE)
        self.root.deiconify()
        self.root.update_idletasks()
        apply_rounded_window_shape(self.root)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()
        self.root.after(1_000, self._release_initial_topmost)

    def _release_initial_topmost(self) -> None:
        if self.root.winfo_exists() and not self._closing:
            self.root.attributes("-topmost", False)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
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

        self._auth_view = AuthView(
            self._content,
            status_var=self._status,
            login_email_var=self._login_email,
            login_password_var=self._login_password,
            register_username_var=self._register_username,
            register_password_var=self._register_password,
            register_password_confirm_var=self._register_password_confirm,
            on_login=self._login,
            on_register=self._register,
            on_forgot_password=lambda: self._notice.set(
                "กรุณาติดต่อแอดมินเพื่อรีเซ็ตรหัสผ่าน"
            ),
        )
        self._dashboard_view = DashboardView(
            self._content,
            self.root,
            account_var=self._account,
            entitlement_var=self._entitlement,
            coupon_var=self._coupon_code,
            game_path_var=self._game_path,
            auto_launch_var=self._auto_launch,
            game_connection_var=self._game_connection_status,
            proxy_connection_var=self._proxy_connection_status,
            on_change_password=self._open_password_dialog,
            on_sign_out=self._sign_out,
            on_redeem_coupon=self._redeem_coupon,
            on_choose_game=self._choose_game,
            on_launch_game=self._launch_game,
            debug_mode=self._debug_mode,
            on_open_debug=self._show_debug_dialog,
        )
        self._show_auth_view()
        self._update_message_visibility()
        self._toast = ToastNotification(self.root)

        footer = ctk.CTkLabel(
            shell,
            text=f"Version {__version__}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=PALETTE.text_muted,
        )
        footer.pack(pady=(0, 4))

    def _build_window_controls(self, drag_surface: ctk.CTkBaseClass) -> None:
        controls = ctk.CTkFrame(self.root, fg_color="transparent")
        controls.place(relx=1.0, x=-10, y=10, anchor="ne")
        secondary_button(
            controls,
            "—",
            self._minimize_window,
            width=30,
            height=24,
        ).pack(side="left", padx=(0, 3))
        secondary_button(
            controls,
            "×",
            self.close,
            width=30,
            height=24,
        ).pack(side="left")
        self._window_drag_handler = WindowDragHandler(self.root)
        self._window_drag_handler.bind_to(drag_surface)

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------
    def _minimize_window(self) -> None:
        if not self._closing and self.root.winfo_exists():
            if self._tray_manager is None:
                self._tray_manager = SystemTrayManager(
                    self._icon_path, self._tray_actions,
                )
                self._tray_manager.setup()
            self.root.withdraw()

    # ------------------------------------------------------------------
    # Toast / messages
    # ------------------------------------------------------------------
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
        if hasattr(self, "_toast"):
            self._toast.show(message, is_error)

    def _hide_toast(self) -> None:
        if hasattr(self, "_toast"):
            self._toast.hide()

    # ------------------------------------------------------------------
    # View switching
    # ------------------------------------------------------------------
    def _show_auth_view(self) -> None:
        self._dashboard_view.frame.pack_forget()
        self._auth_view.frame.pack(fill="both", expand=True, padx=8, pady=(0, 3))

    def _show_program_view(self) -> None:
        self._auth_view.frame.pack_forget()
        self._dashboard_view.frame.pack(fill="both", expand=True, padx=8, pady=(2, 6))

    # ------------------------------------------------------------------
    # Password dialog
    # ------------------------------------------------------------------
    def _open_password_dialog(self) -> None:
        if (
            self._password_dialog is not None
            and self._password_dialog.winfo_exists()
        ):
            self._password_dialog.lift()
            self._password_dialog.focus_force()
            return

        self._password_dialog = open_password_dialog(
            self.root,
            self._icon_path,
            self._new_password,
            self._new_password_confirm,
            self._error,
            self._change_password,
            self._close_password_dialog,
        )

    def _close_password_dialog(self) -> None:
        dialog = self._password_dialog
        self._password_dialog = None
        self._new_password.set("")
        self._new_password_confirm.set("")
        self._error.set("")
        if dialog is not None and dialog.winfo_exists():
            dialog.grab_release()
            dialog.destroy()

    # ------------------------------------------------------------------
    # Debug dialog
    # ------------------------------------------------------------------
    def _show_debug_dialog(self) -> None:
        if not self._debug_mode or self._diagnostics is None:
            return
        if self._debug_dialog is not None and self._debug_dialog.winfo_exists():
            self._debug_dialog.lift()
            self._debug_dialog.focus_force()
            return

        self._debug_dialog = ctk.CTkToplevel(self.root)
        self._debug_dialog.title("Development Debug Mode")
        self._debug_dialog.geometry("700x500")
        self._debug_dialog.attributes("-topmost", True)
        if self._icon_path and self._icon_path.is_file():
            try:
                self._debug_dialog.iconbitmap(self._icon_path)
            except Exception:
                pass

        self._debug_dialog.protocol("WM_DELETE_WINDOW", self._close_debug_dialog)

        frame = ctk.CTkFrame(self._debug_dialog, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            header,
            text="Diagnostics Recorder",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=PALETTE.primary,
        ).pack(side="left")
        
        secondary_button(
            header,
            "Retry ProxyCore (Simulate Restart)",
            self._service.start_proxy,
        ).pack(side="right")

        self._debug_text = ctk.CTkTextbox(
            frame,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
        )
        self._debug_text.pack(fill="both", expand=True, pady=(0, 10))
        self._debug_text.configure(state="disabled")
        
        if self._debug_log_dir:
            ctk.CTkLabel(
                frame,
                text=f"Logs written to: {self._debug_log_dir}",
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                text_color=PALETTE.text_muted,
            ).pack(anchor="w")

        self._update_debug_dialog()

    def _update_debug_dialog(self) -> None:
        if self._debug_dialog is None or not self._debug_dialog.winfo_exists():
            return

        if self._diagnostics:
            snapshot = self._diagnostics.snapshot()
            content = (
                f"Attempt ID: {snapshot.attempt_id}\n"
                f"Stage:      {snapshot.stage}\n"
                f"PID:        {snapshot.pid}\n"
                f"Exit Code:  {snapshot.exit_code}\n"
                f"WinError:   {snapshot.winerror}\n"
                f"Runtime:    {snapshot.runtime}\n"
                f"Core Path:  {snapshot.core_path}\n"
                "\n"
            )
            if snapshot.last_diagnostic:
                content += f"Last Error/Diagnostic:\n{snapshot.last_diagnostic}\n"
            
            self._debug_text.configure(state="normal")
            self._debug_text.delete("1.0", "end")
            self._debug_text.insert("1.0", content)
            self._debug_text.configure(state="disabled")

        self.root.after(250, self._update_debug_dialog)

    def _close_debug_dialog(self) -> None:
        dialog = self._debug_dialog
        self._debug_dialog = None
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()

    # ------------------------------------------------------------------
    # Auth actions (callbacks → service via _submit)
    # ------------------------------------------------------------------
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

    def _coupon_redeemed(self, result: Any) -> None:
        self._coupon_code.set("")
        self._notice.set(
            f"เติมวันสำเร็จ +{result.days_added} วัน "
            f"หมดอายุ {result.valid_until:%d/%m/%Y %H:%M}"
        )

    # ------------------------------------------------------------------
    # Game launch
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Background work / event loop
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # State rendering
    # ------------------------------------------------------------------
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
        self._auth_view.set_status_signed_in(signed_in)
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
        self._dashboard_view.set_redeem_enabled(signed_in)
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
        self._dashboard_view.set_launch_enabled(can_launch_game)
        if state.last_error:
            self._error.set(state.last_error)

    def _render_entitlement(self, state: AppState) -> None:
        entitlement = state.entitlement
        if entitlement is None:
            self._entitlement.set(
                "เหลือ 0 วัน • เติมวันด้วยคูปองเพื่อเริ่มต้น"
            )
            self._dashboard_view.set_entitlement_style(PALETTE.warning)
            return
        if entitlement.valid_until is None:
            self._entitlement.set("ใช้งานได้ • ไม่จำกัดวัน")
            self._dashboard_view.set_entitlement_style(PALETTE.success)
            return
        now = datetime.now(entitlement.valid_until.tzinfo)
        remaining = entitlement.valid_until - now
        if entitlement.status is EntitlementStatus.ACTIVE and remaining.total_seconds() > 0:
            days = max(0, int((remaining.total_seconds() + 86399) // 86400))
            self._entitlement.set(
                f"ใช้งานได้ • เหลือประมาณ {days} วัน • "
                f"หมดอายุ {entitlement.valid_until:%d/%m/%Y %H:%M}"
            )
            self._dashboard_view.set_entitlement_style(PALETTE.success)
        else:
            if state.game_process_running:
                self._entitlement.set(
                    "สิทธิ์หมดอายุแล้ว • จะตัดการเชื่อมต่อหลังออกจากเกม"
                )
                self._dashboard_view.set_entitlement_style(PALETTE.warning)
            else:
                self._entitlement.set(
                    f"หมดอายุแล้ว • เหลือ 0 วัน • "
                    f"{entitlement.valid_until:%d/%m/%Y %H:%M}"
                )
                self._dashboard_view.set_entitlement_style(PALETTE.danger)

    def _set_auth_enabled(self, *, signed_in: bool, authenticating: bool) -> None:
        self._auth_view.set_actions_enabled(
            signed_in=signed_in, authenticating=authenticating
        )

    # ------------------------------------------------------------------
    # Auto-connect: poll for the actual pso2.exe client process.
    # ------------------------------------------------------------------
    def _poll_game_process(self) -> None:
        """Every 3 seconds, check if a PSO2 process appeared."""
        if not self._process_detection_pending:
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
        state = self._controller.state
        if (
            state.auth_status is not AuthStatus.AUTHENTICATED
            or state.session_id is None
            or not entitlement_is_active(state.entitlement)
            or state.proxy_status in {ProxyStatus.STARTING, ProxyStatus.RUNNING}
        ):
            return
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

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            self._service.shutdown()
        except Exception:
            pass
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._tray_manager is not None:
            self._tray_manager.stop()
        self.root.quit()
        self.root.destroy()
