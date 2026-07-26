from __future__ import annotations

import os
import subprocess
from pathlib import Path
from threading import RLock


class GameProcessError(RuntimeError):
    """Raised when the selected game/Tweaker executable cannot be started."""


class GameProcessManager:
    """Owns the selected Tweaker process without touching unrelated processes."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = RLock()

    def start(self, executable: Path) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            if not executable.is_file():
                raise GameProcessError(f"Tweaker.exe not found: {executable}")

            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_SHOWNORMAL
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

            try:
                self._process = subprocess.Popen(
                    [str(executable)],
                    cwd=str(executable.parent),
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                )
            except OSError as exc:
                self._process = None
                raise GameProcessError(str(exc)) from exc

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
