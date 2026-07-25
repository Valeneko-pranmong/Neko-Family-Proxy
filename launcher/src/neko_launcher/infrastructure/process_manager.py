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

            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            try:
                self._process = subprocess.Popen(
                    [str(self._executable)],
                    cwd=str(self._executable.parent),
                    startupinfo=startupinfo,
                    creationflags=creationflags,
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
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=timeout)
            self._process = None

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None
