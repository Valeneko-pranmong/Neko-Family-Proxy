from __future__ import annotations

import subprocess
from pathlib import Path
from threading import RLock


class ProxyProcessError(RuntimeError):
    """Raised when ProxyCore cannot be started."""


class ProxyProcessManager:
    """Open ProxyCore visibly and leave its lifecycle to the user."""

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
            try:
                self._process = subprocess.Popen(
                    [str(self._executable)],
                    cwd=str(self._executable.parent),
                )
            except OSError as exc:
                self._process = None
                raise ProxyProcessError(str(exc)) from exc

    def stop(self, timeout: float = 5.0) -> None:
        """Release Launcher ownership without closing the visible ProxyCore."""
        del timeout
        with self._lock:
            self._process = None
