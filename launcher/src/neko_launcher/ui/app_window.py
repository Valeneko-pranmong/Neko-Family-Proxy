from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from queue import SimpleQueue
from typing import Any, Callable
from tkinter import filedialog, messagebox

import customtkinter as ctk
import tkinter as tk
from PIL import Image

from neko_launcher import __version__
from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.application.reconnect import (
    AutomaticProxyReconnectController,
    ReconnectAttempt,
    ReconnectCompletion,
)
from neko_launcher.application.services import LauncherService
from neko_launcher.domain.events import (
    GameProcessStateChanged,
    StateChanged,
    TelemetryUpdated,
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
from neko_launcher.infrastructure.config import ProgramPreferences

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
from .views.recovery_view import RecoveryView
from .settings_window import SettingsWindow
from .status_presentation import translate_customer_status


HEARTBEAT_INTERVAL_MS = 30_000
RECONNECT_BACKOFF_SECONDS = (1.0, 3.0, 8.0)


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
        telemetry_client: Any = None,
    ) -> None:
        apply_theme()
        self._controller = controller
        self._service = service
        self._event_bus = event_bus
        self._telemetry_client = telemetry_client
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="neko-launcher",
        )
        self._pending: list[
            tuple[
                Future[Any],
                Callable[[Any], None] | None,
                Callable[[Exception], None] | None,
            ]
        ] = []
        self._logo_image = None
        self._settings_control_image = None
        self._logo_path = logo_path
        self._icon_path = icon_path
        self._password_dialog: ctk.CTkToplevel | None = None
        self._debug_dialog: ctk.CTkToplevel | None = None
        self._settings_window: SettingsWindow | None = None
        self._closing = False
        self._tray_actions: SimpleQueue[str] = SimpleQueue()
        self._tray_manager: SystemTrayManager | None = None
        self._diagnostics = diagnostics
        self._debug_mode = debug_mode
        self._debug_log_dir = debug_log_dir
        self._debug_retry_pending = False
        self._proxy_start_attempted_for_detected_game = False
        self._proxy_retry_suppression_logged = False
        self._startup_recovery_in_progress = False
        self._startup_route_pending = False
        self._startup_route_completed = False
        self._startup_routed_session_id: str | None = None
        self._startup_route_generation = 0
        self._startup_process_probe = is_any_process_running
        self._reconnect_controller = AutomaticProxyReconnectController(
            backoff_seconds=RECONNECT_BACKOFF_SECONDS
        )
        self._last_debug_status: tuple[str, tuple[tuple[str, str], ...]] | None = None
        self._last_telemetry_state: Any = None
        self._last_truthful_telemetry_snapshot: Any = None
        self._redeem_in_flight = False
        self._record_debug_status("LAUNCHER_START", message="Debug console enabled")

        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.title("NEKO FAMILY")
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
        self._status_title = tk.StringVar(value="กำลังเตรียมข้อมูล…")
        self._status_subtitle = tk.StringVar(value="กำลังตรวจสอบการเข้าสู่ระบบ")
        self._entitlement_days = tk.StringVar(value="0 วัน")
        self._entitlement_expiry = tk.StringVar(value="ยังไม่มีวันใช้งาน")
        self._download_speed = tk.StringVar(value="ไม่พร้อมใช้งาน")
        self._upload_speed = tk.StringVar(value="ไม่พร้อมใช้งาน")
        self._session_duration = tk.StringVar(value="ไม่พร้อมใช้งาน")
        self._error = tk.StringVar(value="")
        self._notice = tk.StringVar(value="")
        self._error.trace_add("write", self._update_message_visibility)
        self._notice.trace_add("write", self._update_message_visibility)
        self._login_email = tk.StringVar()
        self._login_password = tk.StringVar()
        self._recovery_username = tk.StringVar()
        self._recovery_code = tk.StringVar()
        self._recovery_password = tk.StringVar()
        self._recovery_password_confirm = tk.StringVar()
        self._register_username = tk.StringVar()
        self._register_password = tk.StringVar()
        self._register_password_confirm = tk.StringVar()
        self._new_password = tk.StringVar()
        self._new_password_confirm = tk.StringVar()
        self._coupon_code = tk.StringVar()
        self._game_path = tk.StringVar(value=game_default_path)
        self._game_path_store = game_path_store
        self._auto_launch = tk.BooleanVar(value=True)
        preferences_dir = (
            game_path_store.parent
            if game_path_store is not None
            else Path(os.getenv("LOCALAPPDATA", ".")) / "NEKO FAMILY"
        )
        self._program_preferences = ProgramPreferences(
            preferences_dir / "program.json"
        )
        self._always_on_top = tk.BooleanVar(
            value=self._program_preferences.always_on_top
        )
        self._game_connection_status = tk.StringVar(value="รอให้เข้าเกม (pso2.exe)")
        self._proxy_connection_status = tk.StringVar(value="ProxyCore ยังไม่ทำงาน")
        self._telemetry_speed = tk.StringVar(value="ความเร็ว: ไม่พร้อมใช้งาน")
        self._telemetry_transfer = tk.StringVar(value="ยอดรับ/ส่ง: ไม่พร้อมใช้งาน")
        self._telemetry_session = tk.StringVar(value="เซสชัน: ไม่พร้อมใช้งาน")
        self._telemetry_health = tk.StringVar(value="สถานะระบบ: ไม่พร้อมใช้งาน")
        self._process_detection_pending = False
        self._process_detection_pending = False

        if self._telemetry_client is not None:
            self._telemetry_client.start()

        self._build_layout(logo_path)
        self._window_size = fit_portrait_window(self.root)
        self.root.after(250, lambda: center_window(self.root, self._window_size))
        self.root.after(350, self._show_initial_window)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain_events)
        self.root.after(100, lambda: drain_tray_actions(
            self._tray_actions, self.root, self.close,
        ))
        self.root.after(HEARTBEAT_INTERVAL_MS, self._heartbeat)
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
            self.root.attributes("-topmost", self._always_on_top.get())

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_layout(self, logo_path: Path | None) -> None:
        shell = ctk.CTkFrame(
            self.root,
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=14,
        )
        shell.pack(fill="both", expand=True, padx=8, pady=6)
        self._build_window_controls(shell)

        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(6, 2))

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left", fill="x", expand=True)
        if logo_path and logo_path.is_file():
            try:
                self._logo_image = ctk.CTkImage(
                    Image.open(logo_path),
                    size=(140, 50),
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
            text="NEKO FAMILY PROXY",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="center", pady=(4, 0))
        self._header_message = ctk.CTkLabel(
            brand,
            text="High Performance & Low Latency",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=PALETTE.text_muted,
        )
        self._header_message.pack(anchor="center")

        self._content = ctk.CTkFrame(shell, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=4, pady=(0, 2))

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
            on_forgot_password=self._begin_account_recovery,
        )
        self._recovery_view = RecoveryView(
            self._content,
            username_var=self._recovery_username,
            recovery_code_var=self._recovery_code,
            new_password_var=self._recovery_password,
            confirm_password_var=self._recovery_password_confirm,
            on_verify=self._verify_recovery_code,
            on_change_password=self._change_recovery_password,
            on_cancel=self._cancel_account_recovery,
        )
        self._dashboard_view = DashboardView(
            self._content,
            self.root,
            status_title_var=self._status_title,
            status_subtitle_var=self._status_subtitle,
            account_var=self._account,
            entitlement_days_var=self._entitlement_days,
            entitlement_expiry_var=self._entitlement_expiry,
            download_speed_var=self._download_speed,
            upload_speed_var=self._upload_speed,
            session_duration_var=self._session_duration,
        )
        self._show_auth_view()
        self._update_message_visibility()
        self._toast = ToastNotification(self.root)

        footer = ctk.CTkLabel(
            shell,
            text=f"v{__version__}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=PALETTE.text_muted,
        )
        footer.pack(pady=(0, 4))

    def _build_window_controls(self, drag_surface: ctk.CTkBaseClass) -> None:
        controls = ctk.CTkFrame(self.root, fg_color="transparent")
        controls.place(relx=1.0, x=-10, y=10, anchor="ne")

        # Settings control: always rendered from the approved project asset.
        # If the icon file is missing we leave image=None (ctk falls back to a
        # text-only button) — never substitute glyph fallbacks.
        if self._icon_path and self._icon_path.is_file():
            self._settings_control_image = ctk.CTkImage(
                Image.open(self._icon_path), size=(18, 18)
            )
        else:
            self._settings_control_image = None
        ctk.CTkButton(
            controls, text="", image=self._settings_control_image,
            command=self._open_settings_window, width=32, height=26,
            fg_color="transparent", hover_color="#F3F4F6",
        ).pack(side="left")

        # Hide-to-tray button (wired to existing _minimize_window which
        # withdraws the window and installs the SystemTrayManager on demand).
        hide_btn = secondary_button(
            controls, "Hide", command=self._minimize_window, width=40, height=26
        )
        hide_btn.pack(side="left")

        self._window_drag_handler = WindowDragHandler(self.root)
        self._window_drag_handler.bind_to(drag_surface)

    # ------------------------------------------------------------------
    # Settings window lifecycle
    # ------------------------------------------------------------------
    def _open_settings_window(self) -> None:
        if self._controller.state.auth_status is not AuthStatus.AUTHENTICATED:
            return
        if (
            self._settings_window is not None
            and self._settings_window.winfo_exists()
        ):
            self._settings_window.lift()
            self._settings_window.focus_force()
            return

        self._settings_window = SettingsWindow(
            self.root,
            icon_path=self._icon_path,
            logo_path=self._logo_path,
            account_var=self._account,
            account_status_var=self._status,
            entitlement_status_var=self._entitlement,
            entitlement_days_var=self._entitlement_days,
            entitlement_expiry_var=self._entitlement_expiry,
            coupon_var=self._coupon_code,
            game_status_var=self._game_connection_status,
            game_path_var=self._game_path,
            auto_launch_var=self._auto_launch,
            proxy_connection_var=self._proxy_connection_status,
            telemetry_speed_var=self._telemetry_speed,
            telemetry_transfer_var=self._telemetry_transfer,
            telemetry_session_var=self._telemetry_session,
            telemetry_health_var=self._telemetry_health,
            always_on_top_var=self._always_on_top,
            on_always_on_top_changed=self._apply_always_on_top,
            diagnostics=self._diagnostics,
            debug_mode=self._debug_mode,
            debug_log_dir=self._debug_log_dir,
            on_close=self._close_settings_window,
            on_change_password=self._open_password_dialog,
            on_sign_out=self._sign_out,
            on_redeem_coupon=self._redeem_coupon,
            on_choose_game=self._choose_game,
            on_launch_game=self._launch_game,
            on_open_logs=self._open_debug_logs,
            on_show_advanced_diagnostics=self._show_debug_dialog,
        )
        self._apply_always_on_top()

    def _apply_always_on_top(self) -> None:
        enabled = bool(self._always_on_top.get())
        self._program_preferences.set_always_on_top(enabled)
        self.root.attributes("-topmost", enabled)
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.attributes("-topmost", enabled)

    def _close_settings_window(self) -> None:
        self._settings_window = None

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
        recovery_view = getattr(self, "_recovery_view", None)
        if recovery_view is not None:
            recovery_view.frame.pack_forget()
        self._auth_view.frame.pack(fill="both", expand=True, padx=8, pady=(0, 3))

    def _show_recovery_view(self) -> None:
        self._auth_view.frame.pack_forget()
        self._dashboard_view.frame.pack_forget()
        self._recovery_view.frame.pack(
            fill="both", expand=True, padx=8, pady=(0, 3)
        )

    def _show_recovery_code_entry(self) -> None:
        self._recovery_password.set("")
        self._recovery_password_confirm.set("")
        self._recovery_view.show_code_entry()

    def _show_program_view(self) -> None:
        self._auth_view.frame.pack_forget()
        recovery_view = getattr(self, "_recovery_view", None)
        if recovery_view is not None:
            recovery_view.frame.pack_forget()
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
            self._retry_proxy_core_debug,
        ).pack(side="right")

        actions_frame = ctk.CTkFrame(frame, fg_color="transparent")
        actions_frame.pack(fill="x", pady=(0, 10))
        
        secondary_button(
            actions_frame,
            "Copy Debug",
            self._copy_debug_to_clipboard,
        ).pack(side="left", padx=(0, 10))
        
        if self._debug_log_dir:
            secondary_button(
                actions_frame,
                "Open Logs",
                self._open_debug_logs,
            ).pack(side="left")

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

    def _retry_proxy_core_debug(self) -> None:
        if self._debug_retry_pending:
            return
        state = self._controller.state.proxy_status
        if state in (ProxyStatus.STARTING, ProxyStatus.RUNNING, ProxyStatus.STOPPING):
            return
            
        self._debug_retry_pending = True
        self._submit(self._do_debug_retry, self._on_debug_retry_done)

    def _do_debug_retry(self) -> None:
        self._service.start_proxy()
        
    def _on_debug_retry_done(self, _result: Any) -> None:
        self._debug_retry_pending = False

    def _copy_debug_to_clipboard(self) -> None:
        if not self._diagnostics:
            return
        snapshot = self._diagnostics.snapshot()
        from neko_launcher.application.diagnostics import sanitize_diagnostic_text
        content = self._format_debug_snapshot(snapshot)
        sanitized = sanitize_diagnostic_text(content)
        self.root.clipboard_clear()
        self.root.clipboard_append(sanitized)
        self._show_toast("Copied to clipboard!", is_error=False)

    def _open_debug_logs(self) -> None:
        if not self._debug_log_dir:
            return
        log_dir = Path(self._debug_log_dir)
        try:
            # The folder may not exist yet on a fresh machine; create it on
            # demand so the button never dead-ends silently.
            log_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(log_dir)
        except (OSError, AttributeError) as exc:
            self._show_toast(f"เปิดโฟลเดอร์ Logs ไม่สำเร็จ: {exc}", is_error=True)
        else:
            self._show_toast("เปิดโฟลเดอร์ Logs แล้ว", is_error=False)

    def _format_debug_snapshot(self, snapshot: Any) -> str:
        content = (
            f"Attempt ID: {snapshot.attempt_id}\n"
            f"Stage:      {snapshot.stage}\n"
        )
        if snapshot.process_event:
            content += f"Event:      {snapshot.process_event}\n"
        
        content += (
            f"PID:        {snapshot.pid}\n"
            f"Runtime:    {snapshot.runtime}\n"
        )
        
        if snapshot.exit_code is not None:
            hex_exit = f"0x{snapshot.exit_code & 0xFFFFFFFF:08X}"
            content += f"Exit Code:  {snapshot.exit_code} (Hex: {hex_exit})\n"
        else:
            content += "Exit Code:  None\n"

        if snapshot.authorized_start_elapsed_ms is not None:
            content += (
                "START ms:   "
                f"{snapshot.authorized_start_elapsed_ms}\n"
                "START kind: "
                f"{snapshot.authorized_start_failure_category}\n"
                "Core alive: "
                f"{snapshot.authorized_start_core_alive}\n"
                "Transport:  "
                f"{snapshot.authorized_start_transport_outcome}\n"
            )
            
        content += (
            f"WinError:   {snapshot.winerror}\n"
            f"Core Path:  {snapshot.core_path}\n"
            "\n"
        )
        if snapshot.last_diagnostic:
            content += f"Last Error/Diagnostic:\n{snapshot.last_diagnostic}\n"
        return content

    def _update_debug_dialog(self) -> None:
        if self._debug_dialog is None or not self._debug_dialog.winfo_exists():
            return

        if self._diagnostics:
            snapshot = self._diagnostics.snapshot()
            content = self._format_debug_snapshot(snapshot)
            
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
        username = self._login_email.get()
        password = self._login_password.get()
        self._login_password.set("")
        self._submit(
            lambda: self._service.sign_in(username, password),
            self._login_succeeded,
        )

    def _begin_account_recovery(self) -> None:
        self._error.set("")
        self._notice.set("")
        self._recovery_username.set(self._login_email.get().strip())
        self._clear_recovery_sensitive_fields()
        self._service.begin_account_recovery()

    def _verify_recovery_code(self) -> None:
        username = self._recovery_username.get()
        recovery_code = self._recovery_code.get()
        self._recovery_code.set("")
        self._submit(
            lambda: self._service.verify_recovery_code(
                username, recovery_code
            ),
            self._recovery_verified,
        )

    def _recovery_verified(self, _: Any) -> None:
        self._recovery_code.set("")
        self._notice.set("ยืนยันรหัสกู้บัญชีแล้ว กรุณาตั้งรหัสผ่านใหม่")

    def _change_recovery_password(self) -> None:
        self._submit(
            lambda: self._service.change_recovery_password(
                self._recovery_password.get(),
                self._recovery_password_confirm.get(),
            ),
            self._recovery_password_changed,
        )

    def _recovery_password_changed(self, _: Any) -> None:
        self._clear_recovery_sensitive_fields()
        self._recovery_username.set("")
        self._notice.set(
            "เปลี่ยนรหัสผ่านเรียบร้อย กรุณาเข้าสู่ระบบด้วยรหัสผ่านใหม่"
        )

    def _cancel_account_recovery(self) -> None:
        self._service.cancel_account_recovery()
        self._clear_recovery_sensitive_fields()
        self._recovery_username.set("")

    def _clear_recovery_sensitive_fields(self) -> None:
        for name in (
            "_recovery_code",
            "_recovery_password",
            "_recovery_password_confirm",
        ):
            variable = getattr(self, name, None)
            if variable is not None:
                variable.set("")

    def _restore_completed(self, restored: bool) -> None:
        if restored:
            self._notice.set("กู้คืนการเข้าสู่ระบบสำเร็จ")
            self._route_after_authentication()
        elif self._controller.state.auth_status is AuthStatus.SIGNED_OUT:
            self._status.set("ยังไม่ได้เข้าสู่ระบบ")

    def _login_succeeded(self, _: Any) -> None:
        self._login_password.set("")
        self._notice.set("เข้าสู่ระบบสำเร็จ")
        self._route_after_authentication()

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
        if (
            getattr(getattr(self, "_controller", None), "state", AppState()).game_process_running
            and not self._confirm_game_active_action("ออกจากระบบ")
        ):
            return
        self._cancel_automatic_reconnect(reset_attempts=True)
        self._controller.suppress_proxy_reconnect()
        self._submit(self._service.sign_out, self._signed_out)

    def _signed_out(self, _: Any) -> None:
        self._close_password_dialog()
        self._close_debug_dialog()
        self._coupon_code.set("")
        self._notice.set("ออกจากระบบแล้ว")

    def _redeem_coupon(self) -> None:
        if self._redeem_in_flight:
            return
        self._redeem_in_flight = True
        self._set_redeem_busy(True)
        self._submit(
            lambda: self._service.redeem_coupon(self._coupon_code.get()),
            self._coupon_redeemed,
            self._coupon_redeem_failed,
        )

    def _coupon_redeemed(self, result: Any) -> None:
        self._redeem_in_flight = False
        self._set_redeem_busy(False)
        self._coupon_code.set("")
        self._notice.set(
            f"เติมวันสำเร็จ +{result.days_added} วัน "
            f"หมดอายุ {result.valid_until:%d/%m/%Y %H:%M}"
        )

    def _coupon_redeem_failed(self, _error: Exception) -> None:
        self._redeem_in_flight = False
        self._set_redeem_busy(False)

    def _set_redeem_busy(self, busy: bool) -> None:
        settings = self._settings_window
        if settings is not None and settings.winfo_exists():
            settings.set_redeem_busy(busy)

    def _confirm_game_active_action(self, action: str) -> bool:
        return messagebox.askyesno(
            "NEKO FAMILY",
            f"ตรวจพบว่า PSO2 กำลังทำงานอยู่\nยืนยันที่จะ{action}หรือไม่?\n"
            "เกมจะไม่ถูกปิด",
            parent=self.root,
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

    def _route_after_authentication(self) -> None:
        """Observe PSO2 before choosing recovery or normal Tweaker launch."""
        state = self._controller.state
        if state.session_id != self._startup_routed_session_id:
            self._startup_route_generation += 1
            self._startup_route_pending = False
            self._startup_route_completed = False
            self._startup_recovery_in_progress = False
            self._proxy_start_attempted_for_detected_game = False
            self._proxy_retry_suppression_logged = False
            self._startup_routed_session_id = state.session_id
        ready = (
            state.auth_status is AuthStatus.AUTHENTICATED
            and state.session_id is not None
            and entitlement_is_active(state.entitlement)
        )
        if not ready or self._startup_route_completed or self._startup_route_pending:
            return
        if state.game_process_running:
            self._complete_startup_route(True, self._startup_route_generation)
            return
        self._startup_route_pending = True
        generation = self._startup_route_generation
        self._submit(
            self._startup_process_probe,
            lambda detected: self._complete_startup_route(detected, generation),
            lambda error: self._startup_route_failed(error, generation),
        )

    def _complete_startup_route(
        self,
        detected: bool | None,
        generation: int,
    ) -> None:
        if generation != self._startup_route_generation:
            return
        self._startup_route_pending = False
        state = self._controller.state
        ready = (
            state.auth_status is AuthStatus.AUTHENTICATED
            and state.session_id is not None
            and entitlement_is_active(state.entitlement)
        )
        if not ready or self._startup_route_completed:
            return
        if detected is None:
            self._record_debug_status(
                "STARTUP_PROCESS_OBSERVATION_FAILED",
                reason="Tweaker launch suppressed until PSO2 state is known",
            )
            return
        self._startup_route_completed = True
        if detected:
            self._startup_recovery_in_progress = True
            self._on_game_detected(True)
            if self._proxy_start_attempted_for_detected_game:
                self._notice.set("ตรวจพบ PSO2 ที่กำลังทำงาน — กำลังเชื่อมต่อ...")
            else:
                self._startup_recovery_in_progress = False
            return
        self._auto_launch_tweaker()

    def _startup_route_failed(self, _error: Exception, generation: int) -> None:
        self._complete_startup_route(None, generation)

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
        on_failure: Callable[[Exception], None] | None = None,
    ) -> None:
        self._error.set("")
        self._notice.set("")
        self._pending.append((self._executor.submit(work), on_success, on_failure))

    def _drain_events(self) -> None:
        remaining: list[
            tuple[Future[Any], Callable[[Any], None] | None,
                  Callable[[Exception], None] | None]
        ] = []
        for future, on_success, on_failure in self._pending:
            if not future.done():
                remaining.append((future, on_success, on_failure))
                continue
            try:
                result = future.result()
            except LauncherServiceError as exc:
                self._error.set(str(exc))
                if on_failure:
                    on_failure(exc)
            except Exception as exc:
                self._error.set("เกิดข้อผิดพลาด กรุณาลองใหม่")
                if on_failure:
                    on_failure(exc)
            else:
                if on_success:
                    on_success(result)
        self._pending = remaining

        for event in self._event_bus.drain():
            if isinstance(event, StateChanged):
                self._render_state(event.state)
            elif isinstance(event, TelemetryUpdated):
                self._render_telemetry(event.state)
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
                AuthStatus.RECOVERY_CODE_ENTRY: "กู้บัญชี",
                AuthStatus.RECOVERY_VERIFYING: "กำลังตรวจสอบรหัสกู้บัญชี…",
                AuthStatus.RECOVERY_PASSWORD_CHANGE: "กรุณาตั้งรหัสผ่านใหม่",
            }[state.auth_status]
        )
        self._account.set(state.user_email or "")
        self._auth_view.set_status_signed_in(signed_in)
        self._render_entitlement(state)

        # Update customer status presentation
        cust_status = translate_customer_status(
            state, getattr(self, "_last_telemetry_state", None)
        )
        self._status_title.set(f"● {cust_status.title}")
        self._status_subtitle.set(cust_status.subtitle)
        if hasattr(self, "_dashboard_view") and hasattr(
            self._dashboard_view, "update_status_role"
        ):
            self._dashboard_view.update_status_role(cust_status.role)

        recovery = state.auth_status in {
            AuthStatus.RECOVERY_CODE_ENTRY,
            AuthStatus.RECOVERY_VERIFYING,
            AuthStatus.RECOVERY_PASSWORD_CHANGE,
        }
        if not signed_in:
            if self._password_dialog is not None:
                self._close_password_dialog()
            if self._debug_dialog is not None:
                self._close_debug_dialog()
            if self._settings_window is not None and self._settings_window.winfo_exists():
                self._settings_window.destroy()
                self._settings_window = None
        if signed_in:
            self._show_program_view()
        elif recovery:
            self._show_recovery_view()
            if state.auth_status is AuthStatus.RECOVERY_PASSWORD_CHANGE:
                self._recovery_view.show_password_change()
            else:
                self._show_recovery_code_entry()
        else:
            self._show_auth_view()
        self._recovery_view.set_busy(
            state.auth_status is AuthStatus.RECOVERY_VERIFYING
        )

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
            ProxyStatus.RECONNECTING: "ProxyCore: กำลังเชื่อมต่อใหม่...",
            ProxyStatus.RUNNING: "ProxyCore: ทำงานแล้ว",
            ProxyStatus.STOPPING: "ProxyCore: กำลังหยุดทำงาน...",
            ProxyStatus.FAILED: "ProxyCore: เริ่มทำงานไม่สำเร็จ",
        }[state.proxy_status]
        self._proxy_connection_status.set(proxy_text)
        if state.last_error:
            self._error.set(state.last_error)

    def _render_entitlement(self, state: AppState) -> None:
        entitlement = state.entitlement
        if entitlement is None:
            self._entitlement.set(
                "เหลือ 0 วัน • เติมวันด้วยคูปองเพื่อเริ่มต้น"
            )
            self._entitlement_days.set("0 วัน (ยังไม่มีวันใช้งาน)")
            self._entitlement_expiry.set("ยังไม่มีวันใช้งาน")
            if hasattr(self, "_dashboard_view") and hasattr(
                self._dashboard_view, "set_entitlement_style"
            ):
                self._dashboard_view.set_entitlement_style(PALETTE.warning)
            return
        if entitlement.valid_until is None:
            self._entitlement.set("ใช้งานได้ • ไม่จำกัดวัน")
            self._entitlement_days.set("ไม่จำกัดวัน")
            self._entitlement_expiry.set("ตลอดชีพ (Unlimited)")
            if hasattr(self, "_dashboard_view") and hasattr(
                self._dashboard_view, "set_entitlement_style"
            ):
                self._dashboard_view.set_entitlement_style(PALETTE.success)
                self._dashboard_view.set_tier_badge("ใช้งานได้", role="success")
            return
        now = datetime.now(entitlement.valid_until.tzinfo)
        remaining = entitlement.valid_until - now
        if entitlement.status is EntitlementStatus.ACTIVE and remaining.total_seconds() > 0:
            days = max(0, int((remaining.total_seconds() + 86399) // 86400))
            self._entitlement.set(
                f"ใช้งานได้ • เหลือประมาณ {days} วัน • "
                f"หมดอายุ {entitlement.valid_until:%d/%m/%Y %H:%M}"
            )
            self._entitlement_days.set(f"เหลือประมาณ {days} วัน")
            self._entitlement_expiry.set(f"{entitlement.valid_until:%d/%m/%Y %H:%M}")
            if hasattr(self, "_dashboard_view") and hasattr(
                self._dashboard_view, "set_entitlement_style"
            ):
                self._dashboard_view.set_entitlement_style(PALETTE.success)
                self._dashboard_view.set_tier_badge("ใช้งานได้", role="success")
        else:
            if state.game_process_running:
                self._entitlement.set(
                    "สิทธิ์หมดอายุแล้ว • จะตัดการเชื่อมต่อหลังออกจากเกม"
                )
                self._entitlement_days.set("0 วัน (หมดอายุ)")
                self._entitlement_expiry.set(f"{entitlement.valid_until:%d/%m/%Y %H:%M}")
                if hasattr(self, "_dashboard_view") and hasattr(
                    self._dashboard_view, "set_entitlement_style"
                ):
                    self._dashboard_view.set_entitlement_style(PALETTE.warning)
                    self._dashboard_view.set_tier_badge("หมดอายุ", role="warning")
            else:
                self._entitlement.set(
                    f"หมดอายุแล้ว • เหลือ 0 วัน • "
                    f"{entitlement.valid_until:%d/%m/%Y %H:%M}"
                )
                self._entitlement_days.set("0 วัน (หมดอายุ)")
                self._entitlement_expiry.set(f"{entitlement.valid_until:%d/%m/%Y %H:%M}")
                if hasattr(self, "_dashboard_view") and hasattr(
                    self._dashboard_view, "set_entitlement_style"
                ):
                    self._dashboard_view.set_entitlement_style(PALETTE.danger)
                    self._dashboard_view.set_tier_badge("หมดอายุ", role="danger")

    def _set_auth_enabled(self, *, signed_in: bool, authenticating: bool) -> None:
        self._auth_view.set_actions_enabled(
            signed_in=signed_in, authenticating=authenticating
        )

    # ------------------------------------------------------------------
    # Auto-connect: poll for the actual pso2.exe client process.
    # ------------------------------------------------------------------
    def _record_debug_status(self, stage: str, **details: Any) -> None:
        """Write useful launcher state transitions without flooding the log."""
        if not getattr(self, "_debug_mode", False):
            return
        diagnostics = getattr(self, "_diagnostics", None)
        if diagnostics is None:
            return
        signature = (
            stage,
            tuple(sorted((key, str(value)) for key, value in details.items())),
        )
        if getattr(self, "_last_debug_status", None) == signature:
            return
        self._last_debug_status = signature
        diagnostics.record_stage(stage, **details)

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

    def _on_game_detected(self, detected: bool | None) -> None:
        """Callback when process detection finishes."""
        self._process_detection_pending = False
        if self._startup_route_pending:
            self._record_debug_status(
                "GAME_PROCESS_POLL_DEFERRED",
                reason="post-authentication startup probe owns initial routing",
            )
            return
        if detected is None:
            self._record_debug_status(
                "GAME_PROCESS_OBSERVATION_FAILED",
                reason="preserving last known process state",
            )
            return
        state = self._controller.state
        detection_changed = state.game_process_running is not detected
        if detection_changed:
            self._controller.dispatch(GameProcessStateChanged(detected))
        state = self._controller.state
        startup_authority_ready = (
            state.auth_status is AuthStatus.AUTHENTICATED
            and state.session_id is not None
            and entitlement_is_active(state.entitlement)
        )
        if detected and startup_authority_ready and not self._startup_route_completed:
            self._startup_route_completed = True
            self._startup_recovery_in_progress = True
        if not detected:
            if startup_authority_ready and not self._startup_route_completed:
                self._startup_route_completed = True
                self._auto_launch_tweaker()
            self._cancel_automatic_reconnect(reset_attempts=True)
            self._proxy_start_attempted_for_detected_game = False
            self._proxy_retry_suppression_logged = False
            self._record_debug_status(
                "WAITING_FOR_GAME",
                process="pso2.exe",
                reason="ProxyCore starts only after the game process is detected",
            )
            return
        if detection_changed:
            self._record_debug_status("GAME_PROCESS_DETECTED", process="pso2.exe")
        state = self._controller.state
        if state.auth_status is not AuthStatus.AUTHENTICATED:
            self._record_debug_status("PROXY_START_BLOCKED", reason="not authenticated")
            return
        if state.session_id is None:
            self._record_debug_status("PROXY_START_BLOCKED", reason="session is unavailable")
            return
        if not entitlement_is_active(state.entitlement):
            self._record_debug_status("PROXY_START_BLOCKED", reason="entitlement is inactive")
            return
        if state.proxy_status in {
            ProxyStatus.STARTING,
            ProxyStatus.RECONNECTING,
            ProxyStatus.RUNNING,
        }:
            self._record_debug_status(
                "PROXY_ALREADY_ACTIVE",
                status=state.proxy_status.value,
            )
            return
        reconnect_controller = getattr(self, "_reconnect_controller", None)
        if (
            reconnect_controller is not None
            and reconnect_controller.owns_recovery
        ):
            self._record_debug_status(
                "PROXY_START_NOT_RETRIED",
                reason="automatic reconnect controller owns runtime recovery",
            )
            return
        if self._proxy_start_attempted_for_detected_game:
            if state.proxy_start_retry_safe:
                self._proxy_start_attempted_for_detected_game = False
                self._record_debug_status(
                    "PROXY_START_RETRY_SAFE",
                    reason="previous failure occurred before permit issuance",
                )
            else:
                if not self._proxy_retry_suppression_logged:
                    self._record_debug_status(
                        "PROXY_START_NOT_RETRIED",
                        reason="automatic start already attempted for this game process",
                    )
                    self._proxy_retry_suppression_logged = True
                return
        self._proxy_start_attempted_for_detected_game = True
        self._record_debug_status("PROXY_START_REQUESTED", process="pso2.exe")
        self._submit(
            self._service.start_proxy,
            self._startup_proxy_start_completed
            if self._startup_recovery_in_progress
            else None,
            self._startup_proxy_start_failed
            if self._startup_recovery_in_progress
            else None,
        )
        if self._startup_recovery_in_progress:
            self._notice.set("ตรวจพบ PSO2 ที่กำลังทำงาน — กำลังเชื่อมต่อ...")

    def _startup_proxy_start_completed(self, _result: Any) -> None:
        self._startup_recovery_in_progress = False
        if self._controller.state.proxy_status is ProxyStatus.RUNNING:
            self._notice.set("เชื่อมต่อแล้ว")

    def _startup_proxy_start_failed(self, _error: Exception) -> None:
        self._startup_recovery_in_progress = False

    def _heartbeat(self) -> None:
        if self._controller.state.session_id:
            self._submit(self._service.heartbeat)
        if self.root.winfo_exists():
            self.root.after(HEARTBEAT_INTERVAL_MS, self._heartbeat)

    @staticmethod
    def _add_heading(frame: ctk.CTkBaseClass) -> None:
        ctk.CTkLabel(
            frame,
            text="NEKO FAMILY PROXY PSO2NGS",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(anchor="w", pady=2)

    def _render_telemetry(self, state: Any) -> None:
        from neko_launcher.domain.telemetry import (
            TelemetryConnectionState,
            format_bytes,
            format_speed,
            format_uptime,
        )

        self._last_telemetry_state = state
        self._observe_runtime_health(state)

        if state.connection_state != TelemetryConnectionState.CONNECTED:
            self._telemetry_speed.set("ความเร็ว: ไม่พร้อมใช้งาน")
            self._telemetry_session.set("เซสชัน: ไม่พร้อมใช้งาน")
            self._telemetry_health.set("สถานะระบบ: ไม่พร้อมใช้งาน (รอข้อมูลล่าสุด)")
            self._download_speed.set("ไม่พร้อมใช้งาน")
            self._upload_speed.set("ไม่พร้อมใช้งาน")
            self._session_duration.set("ไม่พร้อมใช้งาน")
            return

        if state.is_stale:
            self._telemetry_speed.set("ความเร็ว: ไม่พร้อมใช้งาน (ข้อมูลล้าสมัย)")
            self._telemetry_session.set("เซสชัน: ไม่พร้อมใช้งาน (ข้อมูลล้าสมัย)")
            self._telemetry_health.set("สถานะระบบ: ไม่พร้อมใช้งาน (ข้อมูลล้าสมัย)")
            self._download_speed.set("ไม่พร้อมใช้งาน")
            self._upload_speed.set("ไม่พร้อมใช้งาน")
            self._session_duration.set("ไม่พร้อมใช้งาน (ข้อมูลล้าสมัย)")
            return
        else:
            rx_speed = format_speed(state.rx_rate_bps)
            tx_speed = format_speed(state.tx_rate_bps)

        self._last_truthful_telemetry_snapshot = state.snapshot

        rx_total = format_bytes(state.snapshot.rx_bytes)
        tx_total = format_bytes(state.snapshot.tx_bytes)
        uptime = format_uptime(state.snapshot.uptime_ms)

        self._telemetry_speed.set(f"ความเร็ว: ▼ {rx_speed} | ▲ {tx_speed}")
        self._telemetry_transfer.set(
            f"รับข้อมูล (RX): {rx_total} | ส่งข้อมูล (TX): {tx_total}"
        )
        self._telemetry_session.set(
            f"เวลาเชื่อมต่อ: {uptime} | TCP: {state.snapshot.tcp_active} active | DNS: {state.snapshot.dns_query_total} | ข้อผิดพลาด: {state.snapshot.network_error_total}"
        )
        self._download_speed.set(rx_speed)
        self._upload_speed.set(tx_speed)
        self._session_duration.set(uptime)

        core_str = (
            "Core ปกติ"
            if state.snapshot.core_state == "running"
            else f"Core: {state.snapshot.core_state}"
        )
        v2ray_str = "V2Ray ทำงาน" if state.snapshot.v2ray_running else "V2Ray ปิด"
        socks_str = (
            "SOCKS พร้อม" if state.snapshot.local_socks_running else "SOCKS ปิด"
        )
        ss_str = (
            "Upstream เชื่อมต่อแล้ว"
            if state.snapshot.shadowsocks_connected
            else "Upstream รอเชื่อมต่อ"
        )
        self._telemetry_health.set(
            f"ระบบ: {core_str} • {v2ray_str} • {socks_str} • {ss_str}"
        )

        # Update customer hero status
        cust_status = translate_customer_status(self._controller.state, state)
        self._status_title.set(f"● {cust_status.title}")
        self._status_subtitle.set(cust_status.subtitle)
        if hasattr(self, "_dashboard_view") and hasattr(
            self._dashboard_view, "update_status_role"
        ):
            self._dashboard_view.update_status_role(cust_status.role)

    def _observe_runtime_health(self, telemetry: Any) -> None:
        reconnect_controller = getattr(self, "_reconnect_controller", None)
        if reconnect_controller is None:
            return
        state = self._controller.state
        if telemetry.is_healthy:
            if state.proxy_status is ProxyStatus.RUNNING:
                reconnect_controller.observe_running()
            return
        attempt = reconnect_controller.request(
            state,
            shutting_down=getattr(self, "_closing", False),
        )
        if attempt is None:
            return
        self._controller.mark_proxy_reconnecting()
        self._record_debug_status(
            "RECONNECT_SCHEDULED",
            attempt=attempt.attempt,
            delay_seconds=attempt.delay_seconds,
        )
        self._schedule_reconnect(
            attempt.delay_seconds,
            lambda: self._begin_automatic_reconnect(attempt),
        )

    def _schedule_reconnect(
        self,
        delay_seconds: float,
        callback: Callable[[], None],
    ) -> None:
        self.root.after(max(1, round(delay_seconds * 1000)), callback)

    def _begin_automatic_reconnect(self, attempt: ReconnectAttempt) -> None:
        cancellation = self._reconnect_controller.begin(
            attempt,
            self._controller.state,
            shutting_down=self._closing,
        )
        if cancellation is None:
            return
        self._controller.mark_proxy_reconnecting()
        self._record_debug_status("RECONNECT_STARTED", attempt=attempt.attempt)
        self._submit(
            lambda: self._run_automatic_reconnect(attempt, cancellation),
            lambda completion: self._automatic_reconnect_completed(
                attempt, completion
            ),
            lambda _error: self._automatic_reconnect_crashed(attempt),
        )

    def _run_automatic_reconnect(
        self,
        attempt: ReconnectAttempt,
        cancellation: Any,
    ) -> ReconnectCompletion:
        self._service.start_proxy(
            cancellation=cancellation,
            automatic_reconnect=True,
        )
        state = self._controller.state
        return self._reconnect_controller.complete(
            attempt,
            succeeded=state.proxy_status is ProxyStatus.RUNNING,
            retry_safe=state.proxy_start_retry_safe,
            failure_code=state.proxy_failure_code,
        )

    def _automatic_reconnect_completed(
        self,
        attempt: ReconnectAttempt,
        completion: ReconnectCompletion,
    ) -> None:
        if completion is ReconnectCompletion.SUCCEEDED:
            self._record_debug_status("RECONNECT_SUCCEEDED", attempt=attempt.attempt)
            return
        if completion is ReconnectCompletion.RETRY:
            self._observe_runtime_health(self._last_telemetry_state)
            return
        if completion is ReconnectCompletion.EXHAUSTED:
            message = "เชื่อมต่อใหม่ไม่สำเร็จ กรุณาตรวจสอบเครือข่ายแล้วลองใหม่"
            self._controller.mark_proxy_reconnect_failed(message)
            self._record_debug_status("RECONNECT_EXHAUSTED", attempts=attempt.attempt)
            return
        if completion is ReconnectCompletion.FAILED:
            self._controller.mark_proxy_reconnect_failed(
                "การเชื่อมต่อขัดข้อง กรุณาลองใหม่"
            )
        self._record_debug_status(
            "RECONNECT_BLOCKED",
            attempt=attempt.attempt,
            completion=completion.value,
        )

    def _automatic_reconnect_crashed(self, attempt: ReconnectAttempt) -> None:
        completion = self._reconnect_controller.complete(
            attempt,
            succeeded=False,
            retry_safe=False,
        )
        self._automatic_reconnect_completed(attempt, completion)

    def _cancel_automatic_reconnect(self, *, reset_attempts: bool) -> None:
        controller = getattr(self, "_reconnect_controller", None)
        if controller is not None:
            controller.cancel(reset_attempts=reset_attempts)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._closing:
            return
        if (
            getattr(getattr(self, "_controller", None), "state", AppState()).game_process_running
            and not self._confirm_game_active_action("ปิด Launcher")
        ):
            return
        self._perform_close()

    def _perform_close(self) -> None:
        self._closing = True
        self._cancel_automatic_reconnect(reset_attempts=True)
        self._clear_recovery_sensitive_fields()
        if getattr(self, "_settings_window", None) is not None:
            try:
                if self._settings_window.winfo_exists():
                    self._settings_window.destroy()
            except Exception:
                pass
            self._settings_window = None
        if getattr(self, "_telemetry_client", None) is not None:
            try:
                self._telemetry_client.stop(timeout=0.5)
            except Exception:
                pass
        try:
            self._service.shutdown()
        except Exception:
            pass
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._tray_manager is not None:
            self._tray_manager.stop()
        self.root.quit()
        self.root.destroy()
