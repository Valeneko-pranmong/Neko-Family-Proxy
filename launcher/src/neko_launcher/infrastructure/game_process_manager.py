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
                # SW_SHOWNORMAL is a Win32 value (1), but unlike SW_HIDE it
                # is not exported by every supported Python subprocess build.
                startupinfo.wShowWindow = getattr(
                    subprocess,
                    "SW_SHOWNORMAL",
                    1,
                )
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
                self._terminate_owned_process_tree(process, timeout)
            self._process = None

    @staticmethod
    def _terminate_owned_process_tree(
        process: subprocess.Popen[bytes], timeout: float
    ) -> None:
        """End the selected Tweaker and its children, never matching by name."""
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
