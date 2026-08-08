from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder


class WindowsCoreProcessAdapter:
    """Manages the NekoProxyCore host process lifecycle.

    The adapter ensures that no secrets (private keys, tokens, passwords)
    are passed via command-line arguments or environment variables to the
    child process.
    """

    def __init__(
        self,
        executable: Path,
        pipe_name: str = "NekoProxyCore.s0-rc1",
        diagnostics: CoreDiagnosticsRecorder | None = None,
        debug_log_dir: Path | None = None,
    ) -> None:
        self._executable = executable
        self._pipe_name = pipe_name
        self._process: subprocess.Popen[Any] | None = None
        self._diagnostics = diagnostics
        self._debug_log_dir = debug_log_dir
        self._stdout_handle: Any = None
        self._stderr_handle: Any = None
        self._process_started_at: float | None = None
        self._early_exit_observed = False

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

    def _close_debug_streams(self) -> None:
        if self._stdout_handle is not None:
            try:
                self._stdout_handle.close()
            except Exception:
                pass
            self._stdout_handle = None
        if self._stderr_handle is not None:
            try:
                self._stderr_handle.close()
            except Exception:
                pass
            self._stderr_handle = None
        self._process_started_at = None
        self._early_exit_observed = False

    def start_host_without_secrets(self) -> None:
        """Start the Core executable as a child process.

        No secrets appear in *argv* or *env*.
        """
        self._close_debug_streams()
        if self._diagnostics:
            self._diagnostics.record_stage(
                "HOST_START",
                core_path=str(self._executable),
                exists=self._executable.exists(),
            )

        if not self._executable.exists():
            exc = FileNotFoundError(
                f"Core executable not found: {self._executable}"
            )
            if self._diagnostics:
                self._diagnostics.record_exception(exc, "HOST_START")
            raise exc

        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )

        stdout = None
        stderr = None

        if self._debug_log_dir and self._diagnostics:
            attempt_id = self._diagnostics.current_attempt_id
            if attempt_id:
                try:
                    self._debug_log_dir.mkdir(parents=True, exist_ok=True)
                    self._stdout_handle = open(
                        self._debug_log_dir / f"core_stdout-{attempt_id}.log",
                        "a",
                        encoding="utf-8",
                    )
                    self._stderr_handle = open(
                        self._debug_log_dir / f"core_stderr-{attempt_id}.log",
                        "a",
                        encoding="utf-8",
                    )
                    stdout = self._stdout_handle
                    stderr = self._stderr_handle
                except OSError:
                    self._close_debug_streams()

        try:
            self._process = subprocess.Popen(
                [str(self._executable)],
                cwd=str(self._executable.parent),
                shell=False,
                creationflags=creationflags,
                env=self._clean_env(),
                stdout=stdout,
                stderr=stderr,
            )
            self._process_started_at = time.monotonic()
            if self._diagnostics:
                self._diagnostics.record_stage("HOST_START", pid=self._process.pid)
        except OSError as exc:
            self._close_debug_streams()
            if self._diagnostics:
                self._diagnostics.record_exception(exc, "HOST_START")
            raise

    def wait_for_control_channel(self, timeout: float) -> None:
        """Block until the bundled Core's approved Named Pipe is available."""
        if self._diagnostics:
            self._diagnostics.record_stage("CONTROL_CHANNEL_WAIT")

        if os.name != "nt":
            # On non-Windows, pipes don't exist — brief sleep as stub.
            time.sleep(0.1)
            return

        pipe_path = rf"\\.\pipe\{self._pipe_name}"
        start_time = time.monotonic()
        deadline = start_time + timeout
        
        while time.monotonic() < deadline:
            # Observation only - do not alter the loop's natural timeout behavior
            if self._process is not None:
                return_code = self._process.poll()
                if return_code is not None and not self._early_exit_observed:
                    self._early_exit_observed = True
                    if self._diagnostics and self._process_started_at is not None:
                        runtime = time.monotonic() - self._process_started_at
                        self._diagnostics.record_process_event(
                            "PROCESS_EXITED_EARLY",
                            exit_code=return_code,
                            runtime=runtime,
                        )
            
            if Path(pipe_path).exists():
                if self._diagnostics:
                    self._diagnostics.record_stage("CONTROL_CHANNEL_WAIT", success=True)
                return
            time.sleep(0.1)

        exc = TimeoutError(f"Timeout waiting for control channel pipe {self._pipe_name}")
        if self._diagnostics:
            self._diagnostics.record_exception(exc, "CONTROL_CHANNEL_WAIT")
        raise exc

    def stop_gracefully(self, timeout: float) -> bool:
        """Terminate the process and wait up to *timeout* seconds.

        Returns ``True`` if the process exited, ``False`` on timeout.
        """
        if self._process is None or self._process.poll() is not None:
            self._close_debug_streams()
            return True

        try:
            self._process.terminate()
            self._process.wait(timeout=timeout)
            self._close_debug_streams()
            return True
        except subprocess.TimeoutExpired:
            return False

    def kill_owned_process_after_timeout(self) -> None:
        """Force-kill the owned process tree (Windows: ``taskkill /T /F``)."""
        if self._process is None or self._process.poll() is not None:
            self._close_debug_streams()
            return

        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                check=False,
            )
        else:
            self._process.kill()
        
        self._close_debug_streams()
