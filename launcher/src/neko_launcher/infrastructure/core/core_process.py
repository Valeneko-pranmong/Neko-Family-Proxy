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
        pipe_name: str = "NekoProxyCoreControl",
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
        if self._process is not None and self._process.poll() is None:
            # A runtime-only STOP intentionally keeps this exact owned host.
            # Reuse it instead of spawning a competing singleton instance.
            return
        self._close_debug_streams()
        self._process = None
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

    def owned_process_id(self) -> int | None:
        """Return the live Core child PID, never a stale process identifier."""
        if self._process is None or self._process.poll() is not None:
            return None
        return self._process.pid

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
                if return_code is not None:
                    if not self._early_exit_observed:
                        self._early_exit_observed = True
                        if self._diagnostics and self._process_started_at is not None:
                            runtime = time.monotonic() - self._process_started_at
                            self._diagnostics.record_process_event(
                                "PROCESS_EXITED_EARLY",
                                exit_code=return_code,
                                runtime=runtime,
                            )
                    raise RuntimeError(
                        f"Core exited before opening its control channel ({return_code})"
                    )

            if self._wait_named_pipe(pipe_path, 100):
                if self._diagnostics:
                    self._diagnostics.record_stage("CONTROL_CHANNEL_WAIT", success=True)
                return
            time.sleep(0.05)

        exc = TimeoutError(f"Timeout waiting for control channel pipe {self._pipe_name}")
        if self._diagnostics:
            self._diagnostics.record_exception(exc, "CONTROL_CHANNEL_WAIT")
        raise exc

    @staticmethod
    def _wait_named_pipe(pipe_path: str, timeout_ms: int) -> bool:
        """Observe Windows pipe readiness without opening an unverified channel."""
        import ctypes

        return bool(
            ctypes.windll.kernel32.WaitNamedPipeW(
                ctypes.c_wchar_p(pipe_path),
                ctypes.c_uint32(timeout_ms),
            )
        )

    def wait_for_owned_process_exit(self, expected_pid: int, timeout: float) -> int:
        """Wait on the retained exact child handle and return its exit code."""
        process = self._require_exact_owned_process(expected_pid)
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("owned Core process did not exit in time") from exc
        self._process = None
        self._close_debug_streams()
        return int(exit_code)

    def terminate_owned_process_after_timeout(
        self, expected_pid: int, timeout: float
    ) -> int:
        """Emergency fallback using only the exact retained child handle."""
        process = self._require_exact_owned_process(expected_pid)
        process.kill()
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("owned Core process resisted termination") from exc
        self._process = None
        self._close_debug_streams()
        return int(exit_code)

    def _require_exact_owned_process(self, expected_pid: int) -> subprocess.Popen[Any]:
        process = self._process
        if process is None or process.pid != expected_pid:
            raise RuntimeError("exact owned Core process is unavailable")
        return process
