from __future__ import annotations

import datetime
import os
import sys
import traceback
from pathlib import Path
from threading import RLock
from typing import Any

from neko_launcher.application.diagnostics import (
    format_safe_diagnostic_metadata,
    safe_authorized_start_details,
    sanitize_diagnostic_text,
)


class DevelopmentLogger:
    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        self._log_file = self._log_dir / "debug.log"
        self._session_id = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        self._timestamped_log_file = self._log_dir / f"neko-debug-{self._session_id}.log"
        self._attempt_id: str | None = None
        self._lock = RLock()
        self._header_written = False

        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def log_session_header(
        self,
        *,
        core_path: str = "",
        workspace_root: str = "",
    ) -> None:
        if self._header_written:
            return
        self._header_written = True

        is_elevated = False
        if os.name == "nt":
            try:
                import ctypes

                is_elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                is_elevated = False

        packaged = getattr(sys, "frozen", False)
        runtime_cat = f"Python {sys.version.split()[0]}"
        if packaged:
            runtime_cat += f" (PyInstaller _MEIPASS: {getattr(sys, '_MEIPASS', 'NONE')})"

        lines = [
            "======================================================================",
            "NEKO FAMILY PROXY RUNTIME DIAGNOSTIC SESSION",
            "======================================================================",
            f"DEBUG_SESSION_ID = {self._session_id}",
            f"TIMESTAMP_UTC = {datetime.datetime.utcnow().isoformat()}Z",
            "LAUNCHER_VERSION_BUILD_CLASS = NekoLauncher-5.0.0a6 (Debug)",
            f"PACKAGED_VS_SOURCE = {'PACKAGED' if packaged else 'SOURCE'}",
            f"PID = {os.getpid()}",
            f"ELEVATION_STATE = {'YES' if is_elevated else 'NO'}",
            f"PYTHON_PYINSTALLER_RUNTIME_CATEGORY = {runtime_cat}",
            f"CORE_PATH = {core_path}",
            f"WORKSPACE_ROOT = {workspace_root}",
            "======================================================================",
        ]
        for line in lines:
            self._write(line)

    def begin_attempt(self, attempt_id: str) -> None:
        with self._lock:
            self._attempt_id = attempt_id
            self._write_unlocked(f"=== BEGIN ATTEMPT {attempt_id} ===")

    def record_stage(self, stage: str, **kwargs: Any) -> None:
        msg = f"[CORE] [{stage}]"
        if stage == "AUTHORIZED_START_RESULT":
            kwargs = safe_authorized_start_details(kwargs)
        if kwargs:
            details = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            msg += f" {details}"
        self._write(msg)

    def record_process_event(self, event: str, **kwargs: Any) -> None:
        msg = f"[PROCESS] [{event}]"
        if kwargs:
            details = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            msg += f" {details}"
        self._write(msg)

    def record_exception(self, exc: Exception, stage: str) -> None:
        exc_type = type(exc).__name__
        sanitized_msg = sanitize_diagnostic_text(str(exc))
        msg = f"[CORE] [{stage}] FAILED - {exc_type}: {sanitized_msg}"
        metadata = format_safe_diagnostic_metadata(exc)
        if metadata:
            msg += f" {metadata}"
        winerror = getattr(exc, "winerror", None)
        if winerror is not None:
            msg += f" (WinError {winerror})"

        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        sanitized_tb = sanitize_diagnostic_text(tb)
        if sanitized_tb.strip():
            msg += f"\nTraceback:\n{sanitized_tb.rstrip()}"
        self._write(msg)

    def _write(self, message: str) -> None:
        with self._lock:
            self._write_unlocked(message)

    def _write_unlocked(self, message: str) -> None:
        sanitized = sanitize_diagnostic_text(message)
        now = datetime.datetime.now()
        ts = now.strftime("%H:%M:%S.%f")[:-3]
        attempt = f"[{self._attempt_id}]" if self._attempt_id else "[]"

        log_line = f"[{ts}] {attempt} {sanitized}\n"
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(log_line)
            if self._timestamped_log_file and self._timestamped_log_file != self._log_file:
                with open(self._timestamped_log_file, "a", encoding="utf-8") as f:
                    f.write(log_line)
        except OSError:
            pass

        try:
            sys.stdout.write(log_line)
            sys.stdout.flush()
        except Exception:
            pass
