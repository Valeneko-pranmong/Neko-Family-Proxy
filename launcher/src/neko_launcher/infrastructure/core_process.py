from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any


class WindowsCoreProcessAdapter:
    """Manages the NekoProxyCore host process lifecycle.

    The adapter ensures that no secrets (private keys, tokens, passwords)
    are passed via command-line arguments or environment variables to the
    child process.
    """

    def __init__(
        self, executable: Path, pipe_name: str = "NekoProxyCoreControl",
    ) -> None:
        self._executable = executable
        self._pipe_name = pipe_name
        self._process: subprocess.Popen[Any] | None = None

    @staticmethod
    def _clean_env() -> dict[str, str]:
        """Return a copy of the current environment with sensitive keys removed."""
        sensitive_keywords = {"SECRET", "PRIVATE", "PASSWORD", "TOKEN"}
        env = os.environ.copy()
        keys_to_remove = [
            key
            for key in env
            if any(kw in key.upper() for kw in sensitive_keywords)
        ]
        for key in keys_to_remove:
            del env[key]
        return env

    def start_host_without_secrets(self) -> None:
        """Start the Core executable as a child process.

        No secrets appear in *argv* or *env*.
        """
        if not self._executable.exists():
            raise FileNotFoundError(
                f"Core executable not found: {self._executable}"
            )

        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )

        self._process = subprocess.Popen(
            [str(self._executable)],
            cwd=str(self._executable.parent),
            shell=False,
            creationflags=creationflags,
            env=self._clean_env(),
        )

    def wait_for_control_channel(self, timeout: float) -> None:
        """Block until the Named Pipe ``NekoProxyCoreControl`` is available."""
        if os.name != "nt":
            # On non-Windows, pipes don't exist — brief sleep as stub.
            time.sleep(0.1)
            return

        pipe_path = rf"\\.\pipe\{self._pipe_name}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if Path(pipe_path).exists():
                return
            time.sleep(0.1)

        raise TimeoutError(
            f"Timeout waiting for control channel pipe {self._pipe_name}"
        )

    def stop_gracefully(self, timeout: float) -> bool:
        """Terminate the process and wait up to *timeout* seconds.

        Returns ``True`` if the process exited, ``False`` on timeout.
        """
        if self._process is None or self._process.poll() is not None:
            return True

        try:
            self._process.terminate()
            self._process.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            return False

    def kill_owned_process_after_timeout(self) -> None:
        """Force-kill the owned process tree (Windows: ``taskkill /T /F``)."""
        if self._process is None or self._process.poll() is not None:
            return

        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                check=False,
            )
        else:
            self._process.kill()
