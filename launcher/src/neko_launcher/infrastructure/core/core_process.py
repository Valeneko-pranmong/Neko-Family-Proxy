from __future__ import annotations

import os
import subprocess
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder


class ProcessIdentityApi(Protocol):
    def open_guarded_read_handle(self, path: Path) -> Any: ...

    def sha256_file(self, path: Path) -> str: ...

    def file_identity(self, handle: Any) -> tuple[int, int]: ...

    def query_process_image_path(self, process: subprocess.Popen[Any]) -> Path | None: ...


@dataclass(frozen=True)
class OwnedCoreProcessIdentity:
    pid: int
    canonical_executable_path: Path
    expected_sha256: str
    verified_sha256: str
    file_identity: tuple[int, int]
    provenance_verified: bool = True


class _GuardedReadHandle:
    def __init__(self, native_handle: int) -> None:
        self.native_handle = native_handle

    def __enter__(self) -> _GuardedReadHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self.native_handle))


class _WindowsProcessIdentityApi:
    @staticmethod
    def open_guarded_read_handle(path: Path) -> _GuardedReadHandle:
        if os.name != "nt":
            raise OSError("Windows process identity is unavailable")
        import ctypes

        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.restype = ctypes.c_void_p
        handle = create_file(
            ctypes.c_wchar_p(str(path)),
            ctypes.c_uint32(0x80000000),
            ctypes.c_uint32(0x00000001),
            None,
            ctypes.c_uint32(3),
            ctypes.c_uint32(0x00000080),
            None,
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            raise OSError(ctypes.get_last_error(), "cannot guard Core executable")
        return _GuardedReadHandle(handle)

    @staticmethod
    def sha256_file(path: Path) -> str:
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def file_identity(handle: _GuardedReadHandle) -> tuple[int, int]:
        import ctypes

        class _FileInfo(ctypes.Structure):
            _fields_ = [
                ("file_attributes", ctypes.c_uint32),
                ("creation_time_low", ctypes.c_uint32),
                ("creation_time_high", ctypes.c_uint32),
                ("last_access_time_low", ctypes.c_uint32),
                ("last_access_time_high", ctypes.c_uint32),
                ("last_write_time_low", ctypes.c_uint32),
                ("last_write_time_high", ctypes.c_uint32),
                ("volume_serial_number", ctypes.c_uint32),
                ("file_size_high", ctypes.c_uint32),
                ("file_size_low", ctypes.c_uint32),
                ("number_of_links", ctypes.c_uint32),
                ("file_index_high", ctypes.c_uint32),
                ("file_index_low", ctypes.c_uint32),
            ]

        info = _FileInfo()
        if not ctypes.windll.kernel32.GetFileInformationByHandle(
            ctypes.c_void_p(handle.native_handle), ctypes.byref(info)
        ):
            raise OSError(ctypes.get_last_error(), "cannot identify Core executable")
        return (
            (int(info.volume_serial_number) << 64)
            | (int(info.file_index_high) << 32)
            | int(info.file_index_low),
            (int(info.file_size_high) << 32) | int(info.file_size_low),
        )

    @staticmethod
    def query_process_image_path(process: subprocess.Popen[Any]) -> Path | None:
        if os.name != "nt":
            raise OSError("Windows process image query is unavailable")
        import ctypes

        length = ctypes.c_uint32(32768)
        buffer = ctypes.create_unicode_buffer(length.value)
        if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
            ctypes.c_void_p(process._handle), 0, buffer, ctypes.byref(length)
        ):
            raise OSError(ctypes.get_last_error(), "cannot query Core process image")
        return Path(buffer.value)


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
        identity_api: ProcessIdentityApi | None = None,
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
        self._identity_api = identity_api or _WindowsProcessIdentityApi()
        self._provenance: OwnedCoreProcessIdentity | None = None
        self._provenance_guards: ExitStack | None = None

    @staticmethod
    def _clean_env() -> dict[str, str]:
        """Build a minimal environment without secret or runtime-injection inputs."""
        allowed_keys = {
            "APPDATA",
            "LOCALAPPDATA",
            "NUMBER_OF_PROCESSORS",
            "OS",
            "PROCESSOR_ARCHITECTURE",
            "PROGRAMDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "PROGRAMW6432",
            "SYSTEMDRIVE",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "WINDIR",
        }
        return {
            key: value
            for key, value in os.environ.items()
            if key.upper() in allowed_keys
        }

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

    def _close_provenance_guards(self) -> None:
        if self._provenance_guards is not None:
            self._provenance_guards.close()
            self._provenance_guards = None

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

    def start_admitted_core(self, admission: Any) -> OwnedCoreProcessIdentity:
        """Spawn only an admitted Core image and retain proof for its child."""
        if self._process is not None and self._process.poll() is None:
            if self._provenance is None:
                raise RuntimeError("owned Core process provenance is unavailable")
            if self._provenance.expected_sha256 != admission.core_exe_sha256:
                raise RuntimeError("admitted Core identity conflicts with owned process")
            return self._provenance

        artifact_root = Path(admission.artifact_path).resolve(strict=True)
        canonical = (artifact_root / "NekoProxyCore.exe").resolve(strict=True)
        if not canonical.is_file():
            raise RuntimeError("admitted Core executable is unavailable")

        guarded_files = getattr(admission, "guarded_files", ())
        if not guarded_files:
            raise RuntimeError("admitted Core artifact inventory is unavailable")
        process = None
        try:
            with ExitStack() as guards:
                expected_identity = None
                executable_inventory_hash = None
                guarded_inventory: list[tuple[Path, str]] = []
                seen_paths: set[Path] = set()
                for admitted_file in guarded_files:
                    relative_path = Path(admitted_file.relative_path)
                    if relative_path.is_absolute():
                        raise RuntimeError("admitted Core artifact path is invalid")
                    guarded_path = (artifact_root / relative_path).resolve(strict=True)
                    if artifact_root not in guarded_path.parents:
                        raise RuntimeError("admitted Core artifact path is invalid")
                    if guarded_path in seen_paths:
                        raise RuntimeError("admitted Core artifact inventory is invalid")
                    seen_paths.add(guarded_path)
                    guard = guards.enter_context(
                        self._identity_api.open_guarded_read_handle(guarded_path)
                    )
                    if self._identity_api.sha256_file(guarded_path) != admitted_file.sha256:
                        raise RuntimeError("admitted Core artifact hash mismatch")
                    guarded_inventory.append((guarded_path, admitted_file.sha256))
                    if guarded_path == canonical:
                        expected_identity = self._identity_api.file_identity(guard)
                        executable_inventory_hash = admitted_file.sha256
                physical_files = {
                    path.resolve(strict=True)
                    for path in artifact_root.rglob("*")
                    if path.is_file()
                }
                if physical_files != seen_paths:
                    raise RuntimeError("admitted Core artifact inventory is incomplete")
                if expected_identity is None:
                    raise RuntimeError("admitted Core executable inventory is unavailable")
                if admission.core_exe_sha256 != executable_inventory_hash:
                    raise RuntimeError("admitted Core executable hash mismatch")
                process = self._spawn_exact(canonical)
                if process.poll() is not None:
                    raise RuntimeError("Core process provenance could not be proven")
                actual_path = self._identity_api.query_process_image_path(process)
                if actual_path is None or actual_path.resolve(strict=True) != canonical:
                    raise RuntimeError("Core process provenance could not be proven")
                with self._identity_api.open_guarded_read_handle(actual_path.resolve(strict=True)) as actual:
                    if self._identity_api.file_identity(actual) != expected_identity:
                        raise RuntimeError("Core process provenance could not be proven")
                for guarded_path, admitted_hash in guarded_inventory:
                    verified_hash = self._identity_api.sha256_file(guarded_path)
                    if verified_hash != admitted_hash:
                        raise RuntimeError("Core process provenance could not be proven")
                post_spawn_files = {
                    path.resolve(strict=True)
                    for path in artifact_root.rglob("*")
                    if path.is_file()
                }
                if post_spawn_files != seen_paths:
                    raise RuntimeError("Core process provenance could not be proven")
                verified_sha = self._identity_api.sha256_file(canonical)
                if process.poll() is not None:
                    raise RuntimeError("Core process provenance could not be proven")
                self._process = process
                self._process_started_at = time.monotonic()
                self._provenance = OwnedCoreProcessIdentity(
                    pid=process.pid,
                    canonical_executable_path=canonical,
                    expected_sha256=admission.core_exe_sha256,
                    verified_sha256=verified_sha,
                    file_identity=expected_identity,
                )
                self._provenance_guards = guards.pop_all()
                return self._provenance
        except Exception:
            if process is not None:
                self._cleanup_failed_spawn(process)
            raise

    def _spawn_exact(self, executable: Path) -> subprocess.Popen[Any]:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        return subprocess.Popen(
            [str(executable)],
            cwd=str(executable.parent),
            shell=False,
            creationflags=creationflags,
            env=self._clean_env(),
        )

    def _cleanup_failed_spawn(self, process: subprocess.Popen[Any]) -> None:
        self._process = process
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("unverified Core child resisted exact cleanup") from exc
        self._process = None
        self._provenance = None
        self._close_provenance_guards()

    def owned_process_id(self) -> int | None:
        """Return the live Core child PID, never a stale process identifier."""
        if self._process is None:
            return None
        if self._process.poll() is not None:
            self._provenance = None
            self._close_provenance_guards()
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
        self._provenance = None
        self._close_provenance_guards()
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
        self._provenance = None
        self._close_provenance_guards()
        return int(exit_code)

    def _require_exact_owned_process(self, expected_pid: int) -> subprocess.Popen[Any]:
        process = self._process
        if process is None or process.pid != expected_pid:
            raise RuntimeError("exact owned Core process is unavailable")
        return process
