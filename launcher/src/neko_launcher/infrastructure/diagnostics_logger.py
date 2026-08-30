from __future__ import annotations

import datetime
import hashlib
import os
import sys
import traceback
from pathlib import Path
from threading import RLock
from typing import Any

from neko_launcher import __version__
from neko_launcher.application.diagnostics import (
    format_safe_diagnostic_metadata,
    safe_authorized_start_details,
    sanitize_diagnostic_text,
)


class DevelopmentLogger:
    """Always-on sanitized support logger.

    The historical class name is retained to avoid unnecessary API churn.
    ``verbose`` represents development/debug mode; support logging itself is
    always enabled by the application factory.
    """

    _MAX_SESSION_LOGS = 10

    def __init__(self, log_dir: Path, *, verbose: bool = False) -> None:
        self._log_dir = log_dir
        self._verbose = bool(verbose)
        self._session_id = f"{datetime.datetime.utcnow():%Y%m%d-%H%M%S}-{os.getpid()}"
        self._log_file = self._log_dir / "support.log"
        self._legacy_debug_log_file = self._log_dir / "debug.log"
        self._legacy_debug_log_file = self._log_dir / "debug.log"
        self._timestamped_log_file = self._log_dir / f"neko-support-{self._session_id}.log"
        self._attempt_id: str | None = None
        self._lock = RLock()
        self._header_written = False

        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._rotate_session_logs()
            self._log_file.write_text("", encoding="utf-8")
            self._legacy_debug_log_file.write_text("", encoding="utf-8")
            self._timestamped_log_file.write_text("", encoding="utf-8")
        except OSError:
            pass

    def _rotate_session_logs(self) -> None:
        try:
            logs = sorted(
                self._log_dir.glob("neko-support-*.log"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        for stale in logs[self._MAX_SESSION_LOGS - 1 :]:
            try:
                stale.unlink()
            except OSError:
                pass


    @staticmethod
    def _safe_path_display(value: str) -> str:
        if not value:
            return ""
        text = str(value)
        replacements = []
        for env_name, marker in (("LOCALAPPDATA", "%LOCALAPPDATA%"), ("USERPROFILE", "%USERPROFILE%"), ("TEMP", "%TEMP%"), ("TMP", "%TEMP%")):
            root = os.getenv(env_name, "").strip()
            if root:
                replacements.append((root, marker))
        for root, marker in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
            if text.lower().startswith(root.lower()):
                return marker + text[len(root):]
        return text

    @staticmethod
    def _sha256_file(path: Path) -> str:
        if not path.is_file():
            return "UNAVAILABLE"
        try:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return "UNAVAILABLE"

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
            runtime_cat += " (PyInstaller frozen)"

        core_exe = Path(core_path) if core_path else Path()
        core_dll = core_exe.with_name("NekoProxyCore.dll") if core_path else Path()
        lines = [
            "======================================================================",
            "NEKO FAMILY PROXY SUPPORT DIAGNOSTIC SESSION",
            "======================================================================",
            f"SUPPORT_SESSION_ID = {self._session_id}",
            f"TIMESTAMP_UTC = {datetime.datetime.utcnow().isoformat()}Z",
            f"LAUNCHER_VERSION = {__version__}",
            f"DEBUG_VERBOSE = {'YES' if self._verbose else 'NO'}",
            f"PACKAGED_VS_SOURCE = {'PACKAGED' if packaged else 'SOURCE'}",
            f"PID = {os.getpid()}",
            f"ELEVATION_STATE = {'YES' if is_elevated else 'NO'}",
            f"PYTHON_PYINSTALLER_RUNTIME_CATEGORY = {runtime_cat}",
            f"CORE_EXE_SHA256 = {self._sha256_file(core_exe) if core_path else 'UNAVAILABLE'}",
            f"CORE_DLL_SHA256 = {self._sha256_file(core_dll) if core_path else 'UNAVAILABLE'}",
            f"CORE_PATH = {self._safe_path_display(core_path)}",
            f"WORKSPACE_ROOT = {self._safe_path_display(workspace_root) if not packaged else 'PACKAGED'}",
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
            with self._log_file.open("a", encoding="utf-8") as stream:
                stream.write(log_line)
            with self._legacy_debug_log_file.open("a", encoding="utf-8") as stream:
                stream.write(log_line)
            with self._timestamped_log_file.open("a", encoding="utf-8") as stream:
                stream.write(log_line)
        except OSError:
            pass

        if self._verbose:
            try:
                sys.stdout.write(log_line)
                sys.stdout.flush()
            except Exception:
                pass
