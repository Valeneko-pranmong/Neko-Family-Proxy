from __future__ import annotations

import os
import subprocess
from pathlib import Path
from threading import RLock


class ProxyProcessError(RuntimeError):
    """Raised when ProxyCore cannot be started or stopped cleanly."""


class ProxyProcessManager:
    """Owns one ProxyCore process instead of killing all matching processes."""

    def __init__(self, executable: Path) -> None:
        self._executable = executable
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = RLock()

    def start(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            if not self._executable.is_file():
                raise ProxyProcessError(f"ProxyCore not found: {self._executable}")

            import sys
            startupinfo = None
            creationflags = 0
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                # Run Netch on a separate virtual desktop to completely hide its tray icon and windows
                startupinfo.lpDesktop = "HiddenDesktop"
                
                try:
                    self._process = subprocess.Popen(
                        [str(self._executable)],
                        cwd=str(self._executable.parent),
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                except OSError as exc:
                    self._process = None
                    raise ProxyProcessError(str(exc)) from exc
            else:
                try:
                    self._process = subprocess.Popen(
                        [str(self._executable)],
                        cwd=str(self._executable.parent),
                    )
                except OSError as exc:
                    self._process = None
                    raise ProxyProcessError(str(exc)) from exc

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return
            if process.poll() is None:
                self._terminate_owned_process_tree(self._process, timeout=5.0)
            self._process = None
            if hasattr(self, "_desktop_handle") and self._desktop_handle:
                try:
                    import ctypes
                    ctypes.WinDLL("user32").CloseDesktop(self._desktop_handle)
                except Exception:
                    pass
                self._desktop_handle = None

    @staticmethod
    def _terminate_owned_process_tree(
        process: subprocess.Popen[bytes], timeout: float
    ) -> None:
        """End ProxyCore's own process tree without touching other sessions."""
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
            return
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
