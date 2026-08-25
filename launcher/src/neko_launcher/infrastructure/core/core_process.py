from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder


def _windows_bool_type() -> type[Any]:
    """Return the four-byte Win32 BOOL type used by native APIs."""
    from ctypes import wintypes

    return wintypes.BOOL


class ProcessIdentityApi(Protocol):
    def open_guarded_read_handle(self, path: Path) -> Any: ...

    def sha256_file(self, path: Path) -> str: ...

    def file_identity(self, handle: Any) -> tuple[int, int]: ...

    def query_process_image_path(self, process: subprocess.Popen[Any]) -> Path | None: ...


class CoreLifetimeJob(Protocol):
    def spawn(
        self,
        command: list[str],
        *,
        cwd: str,
        creationflags: int,
        env: dict[str, str],
    ) -> subprocess.Popen[Any]: ...

    def close(self) -> None: ...


class _NoopLifetimeJob:
    def spawn(
        self,
        command: list[str],
        *,
        cwd: str,
        creationflags: int,
        env: dict[str, str],
    ) -> subprocess.Popen[Any]:
        return subprocess.Popen(
            command,
            cwd=cwd,
            shell=False,
            creationflags=creationflags,
            env=env,
        )

    def close(self) -> None:
        pass


class _WindowsJobProcess:
    """Small Popen-compatible owner for a native Windows process handle."""

    def __init__(
        self,
        kernel32: Any,
        handle: int,
        pid: int,
        args: list[str],
    ) -> None:
        self._kernel32 = kernel32
        self._handle = handle
        self.pid = pid
        self.args = args
        self.returncode: int | None = None

    def close_owned_handles(self) -> None:
        import ctypes

        handle = self._handle
        self._handle = 0
        if handle:
            self._kernel32.CloseHandle(ctypes.c_void_p(handle))

    def _exit_code(self) -> int:
        import ctypes

        exit_code = ctypes.c_uint32()
        if not self._kernel32.GetExitCodeProcess(
            ctypes.c_void_p(self._handle),
            ctypes.byref(exit_code),
        ):
            raise OSError(ctypes.get_last_error(), "cannot query Core exit code")
        self.returncode = int(exit_code.value)
        return self.returncode

    def poll(self) -> int | None:
        import ctypes

        if self.returncode is not None:
            return self.returncode
        result = self._kernel32.WaitForSingleObject(
            ctypes.c_void_p(self._handle),
            ctypes.c_uint32(0),
        )
        if result == 0x00000102:
            return None
        if result != 0x00000000:
            raise OSError(ctypes.get_last_error(), "cannot poll Core process")
        return self._exit_code()

    def wait(self, timeout: float | None = None) -> int:
        import ctypes
        import math

        if self.returncode is not None:
            return self.returncode
        timeout_ms = 0xFFFFFFFF
        if timeout is not None:
            timeout_ms = min(0xFFFFFFFE, max(0, math.ceil(timeout * 1000)))
        result = self._kernel32.WaitForSingleObject(
            ctypes.c_void_p(self._handle),
            ctypes.c_uint32(timeout_ms),
        )
        if result == 0x00000102:
            raise subprocess.TimeoutExpired(self.args, timeout)
        if result != 0x00000000:
            raise OSError(ctypes.get_last_error(), "cannot wait for Core process")
        return self._exit_code()

    def kill(self) -> None:
        import ctypes

        if not self._kernel32.TerminateProcess(
            ctypes.c_void_p(self._handle),
            ctypes.c_uint32(1),
        ):
            error = ctypes.get_last_error()
            if self.poll() is None:
                raise OSError(error, "cannot terminate Core process")

    terminate = kill

    def __del__(self) -> None:
        try:
            self.close_owned_handles()
        except Exception:
            pass


class _WindowsKillOnCloseJob:
    """Kill only the Core child tree if Launcher ownership disappears."""

    def __init__(self) -> None:
        import ctypes

        windows_bool = _windows_bool_type()

        class _BasicLimits(ctypes.Structure):
            _fields_ = [
                ("per_process_user_time_limit", ctypes.c_int64),
                ("per_job_user_time_limit", ctypes.c_int64),
                ("limit_flags", ctypes.c_uint32),
                ("minimum_working_set_size", ctypes.c_size_t),
                ("maximum_working_set_size", ctypes.c_size_t),
                ("active_process_limit", ctypes.c_uint32),
                ("affinity", ctypes.c_size_t),
                ("priority_class", ctypes.c_uint32),
                ("scheduling_class", ctypes.c_uint32),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "read_operation_count",
                "write_operation_count",
                "other_operation_count",
                "read_transfer_count",
                "write_transfer_count",
                "other_transfer_count",
            )]

        class _ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic_limit_information", _BasicLimits),
                ("io_info", _IoCounters),
                ("process_memory_limit", ctypes.c_size_t),
                ("job_memory_limit", ctypes.c_size_t),
                ("peak_process_memory_used", ctypes.c_size_t),
                ("peak_job_process_memory_used", ctypes.c_size_t),
            ]

        class _StartupInfo(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_uint32),
                ("reserved", ctypes.c_wchar_p),
                ("desktop", ctypes.c_wchar_p),
                ("title", ctypes.c_wchar_p),
                ("x", ctypes.c_uint32),
                ("y", ctypes.c_uint32),
                ("x_size", ctypes.c_uint32),
                ("y_size", ctypes.c_uint32),
                ("x_chars", ctypes.c_uint32),
                ("y_chars", ctypes.c_uint32),
                ("fill_attribute", ctypes.c_uint32),
                ("flags", ctypes.c_uint32),
                ("show_window", ctypes.c_uint16),
                ("reserved_size", ctypes.c_uint16),
                ("reserved2", ctypes.c_void_p),
                ("std_input", ctypes.c_void_p),
                ("std_output", ctypes.c_void_p),
                ("std_error", ctypes.c_void_p),
            ]

        class _StartupInfoEx(ctypes.Structure):
            _fields_ = [
                ("startup_info", _StartupInfo),
                ("attribute_list", ctypes.c_void_p),
            ]

        class _ProcessInformation(ctypes.Structure):
            _fields_ = [
                ("process", ctypes.c_void_p),
                ("thread", ctypes.c_void_p),
                ("process_id", ctypes.c_uint32),
                ("thread_id", ctypes.c_uint32),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        kernel32.SetInformationJobObject.restype = windows_bool
        kernel32.InitializeProcThreadAttributeList.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_size_t),
        )
        kernel32.InitializeProcThreadAttributeList.restype = windows_bool
        kernel32.UpdateProcThreadAttribute.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
        )
        kernel32.UpdateProcThreadAttribute.restype = windows_bool
        kernel32.DeleteProcThreadAttributeList.argtypes = (ctypes.c_void_p,)
        kernel32.DeleteProcThreadAttributeList.restype = None
        kernel32.CreateProcessW.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            windows_bool,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.POINTER(_StartupInfo),
            ctypes.POINTER(_ProcessInformation),
        )
        kernel32.CreateProcessW.restype = windows_bool
        kernel32.IsProcessInJob.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(windows_bool),
        )
        kernel32.IsProcessInJob.restype = windows_bool
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.GetExitCodeProcess.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        )
        kernel32.GetExitCodeProcess.restype = windows_bool
        kernel32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.TerminateProcess.restype = windows_bool
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = windows_bool
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "cannot create Core lifetime job")
        limits = _ExtendedLimits()
        limits.basic_limit_information.limit_flags = 0x00002000
        if not kernel32.SetInformationJobObject(
            ctypes.c_void_p(handle),
            ctypes.c_int(9),
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            raise OSError(error, "cannot configure Core lifetime job")
        self._kernel32 = kernel32
        self._handle: int | None = int(handle)
        self._startup_info = _StartupInfo
        self._startup_info_ex = _StartupInfoEx
        self._process_information = _ProcessInformation
        self._windows_bool = windows_bool

    def spawn(
        self,
        command: list[str],
        *,
        cwd: str,
        creationflags: int,
        env: dict[str, str],
    ) -> subprocess.Popen[Any]:
        import ctypes

        if self._handle is None:
            raise RuntimeError("Core lifetime job is closed")
        attribute_size = ctypes.c_size_t()
        self._kernel32.InitializeProcThreadAttributeList(
            None,
            1,
            0,
            ctypes.byref(attribute_size),
        )
        if attribute_size.value == 0:
            raise OSError(
                ctypes.get_last_error(),
                "cannot size Core process attribute list",
            )
        attribute_buffer = ctypes.create_string_buffer(attribute_size.value)
        attribute_list = ctypes.cast(attribute_buffer, ctypes.c_void_p)
        if not self._kernel32.InitializeProcThreadAttributeList(
            attribute_list,
            1,
            0,
            ctypes.byref(attribute_size),
        ):
            raise OSError(
                ctypes.get_last_error(),
                "cannot initialize Core process attribute list",
            )

        process_info = self._process_information()
        process_handle = 0
        thread_handle = 0
        try:
            job_list = (ctypes.c_void_p * 1)(self._handle)
            if not self._kernel32.UpdateProcThreadAttribute(
                attribute_list,
                0,
                0x0002000D,
                ctypes.cast(job_list, ctypes.c_void_p),
                ctypes.sizeof(job_list),
                None,
                None,
            ):
                raise OSError(
                    ctypes.get_last_error(),
                    "cannot bind Core process creation to lifetime job",
                )
            startup = self._startup_info_ex()
            startup.startup_info.cb = ctypes.sizeof(startup)
            startup.attribute_list = attribute_list
            command_line = ctypes.create_unicode_buffer(
                subprocess.list2cmdline(command)
            )
            environment_text = "\0".join(
                f"{key}={value}"
                for key, value in sorted(env.items(), key=lambda item: item[0].casefold())
            ) + "\0\0"
            environment = ctypes.create_unicode_buffer(environment_text)
            flags = creationflags | 0x00000400 | 0x00080000
            if not self._kernel32.CreateProcessW(
                str(command[0]),
                command_line,
                None,
                None,
                False,
                flags,
                ctypes.cast(environment, ctypes.c_void_p),
                cwd,
                ctypes.cast(
                    ctypes.byref(startup),
                    ctypes.POINTER(self._startup_info),
                ),
                ctypes.byref(process_info),
            ):
                raise OSError(ctypes.get_last_error(), "cannot create owned Core process")
            process_handle = int(process_info.process)
            thread_handle = int(process_info.thread)
            is_in_job = self._windows_bool(False)
            if not self._kernel32.IsProcessInJob(
                ctypes.c_void_p(process_handle),
                ctypes.c_void_p(self._handle),
                ctypes.byref(is_in_job),
            ) or not is_in_job.value:
                self._kernel32.TerminateProcess(
                    ctypes.c_void_p(process_handle),
                    ctypes.c_uint32(1),
                )
                self._kernel32.CloseHandle(ctypes.c_void_p(process_handle))
                process_handle = 0
                raise RuntimeError("Core process was not created inside lifetime job")
            owned_handle = process_handle
            process_handle = 0
            return _WindowsJobProcess(
                self._kernel32,
                owned_handle,
                int(process_info.process_id),
                command,
            )
        finally:
            self._kernel32.DeleteProcThreadAttributeList(attribute_list)
            if thread_handle:
                self._kernel32.CloseHandle(ctypes.c_void_p(thread_handle))
            if process_handle:
                self._kernel32.CloseHandle(ctypes.c_void_p(process_handle))

    def close(self) -> None:
        import ctypes

        handle = self._handle
        self._handle = None
        if handle is not None:
            self._kernel32.CloseHandle(ctypes.c_void_p(handle))


def _create_lifetime_job() -> CoreLifetimeJob:
    return _WindowsKillOnCloseJob() if os.name == "nt" else _NoopLifetimeJob()


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
        lifetime_job_factory: Callable[[], CoreLifetimeJob] | None = None,
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
        self._lifetime_job_factory = lifetime_job_factory or _create_lifetime_job
        self._lifetime_job: CoreLifetimeJob | None = None
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

    def _close_lifetime_job(self) -> None:
        job = self._lifetime_job
        self._lifetime_job = None
        if job is not None:
            job.close()

    @staticmethod
    def _close_process_handles(process: subprocess.Popen[Any] | None) -> None:
        if isinstance(process, _WindowsJobProcess):
            process.close_owned_handles()

    def _release_process(self) -> None:
        process = self._process
        self._process = None
        self._close_process_handles(process)

    def _spawn_lifetime_bound(
        self,
        executable: Path,
    ) -> subprocess.Popen[Any]:
        job = self._lifetime_job_factory()
        self._lifetime_job = job
        try:
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            )
            return job.spawn(
                [str(executable)],
                cwd=str(executable.parent),
                creationflags=creationflags,
                env=self._clean_env(),
            )
        except Exception:
            self._close_lifetime_job()
            raise

    def start_host_without_secrets(self) -> None:
        """Start the Core executable as a child process.

        No secrets appear in *argv* or *env*.
        """
        if self._process is not None and self._process.poll() is None:
            # A runtime-only STOP intentionally keeps this exact owned host.
            # Reuse it instead of spawning a competing singleton instance.
            return
        self._close_debug_streams()
        self._close_lifetime_job()
        self._release_process()

        core_dir = self._executable.parent
        exe_exists = self._executable.is_file()
        dll_exists = (core_dir / "NekoProxyCore.dll").is_file()
        settings_exists = (core_dir / "runtime-settings.nkps").is_file()
        redirector_exists = (core_dir / "Redirector.bin").is_file() or (core_dir / "bin" / "Redirector.bin").is_file()
        nfapi_exists = (core_dir / "nfapi.dll").is_file() or (core_dir / "bin" / "nfapi.dll").is_file()
        nfdriver_exists = (core_dir / "nfdriver.sys").is_file() or (core_dir / "bin" / "nfdriver.sys").is_file()
        pso2_mode_exists = (core_dir / "mode" / "Custom" / "PSO2.json").is_file()

        if self._diagnostics:
            self._diagnostics.record_stage(
                "CORE_RESOLVE",
                core_path=str(self._executable),
                working_dir=str(core_dir),
                CORE_EXE_EXISTS=exe_exists,
                CORE_DLL_EXISTS=dll_exists,
                RUNTIME_SETTINGS_EXISTS=settings_exists,
                REDIRECTOR_EXISTS=redirector_exists,
                NFAPI_EXISTS=nfapi_exists,
                NFDRIVER_EXISTS=nfdriver_exists,
                PSO2_MODE_EXISTS=pso2_mode_exists,
            )

        if not self._executable.exists():
            exc = FileNotFoundError(
                f"Core executable not found: {self._executable}"
            )
            if self._diagnostics:
                self._diagnostics.record_exception(exc, "HOST_START")
            raise exc

        try:
            self._process = self._spawn_lifetime_bound(self._executable)
            self._process_started_at = time.monotonic()
            if self._diagnostics:
                self._diagnostics.record_stage(
                    "HOST_START",
                    pid=self._process.pid,
                    core_path=str(self._executable),
                    working_dir=str(self._executable.parent),
                    status="PROCESS_CREATED",
                )
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
                process = self._spawn_lifetime_bound(canonical)
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
                if self._lifetime_job is None:
                    raise RuntimeError("Core lifetime job is unavailable")
                return self._provenance
        except Exception:
            if process is not None:
                self._cleanup_failed_spawn(process)
            raise

    def _cleanup_failed_spawn(self, process: subprocess.Popen[Any]) -> None:
        self._process = process
        try:
            try:
                child_is_live = process.poll() is None
            except Exception:
                return
            if child_is_live:
                try:
                    process.kill()
                except Exception:
                    # Closing the exact owning Job is the fail-closed fallback.
                    return
            try:
                process.wait(timeout=1.0)
            except Exception:
                return
        finally:
            self._release_process()
            self._provenance = None
            self._close_provenance_guards()
            self._close_lifetime_job()

    def owned_process_id(self) -> int | None:
        """Return the live Core child PID, never a stale process identifier."""
        if self._process is None:
            return None
        if self._process.poll() is not None:
            self._close_process_handles(self._process)
            self._provenance = None
            self._close_provenance_guards()
            self._close_lifetime_job()
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

        is_alive = bool(self._process is not None and self._process.poll() is None)
        pid = self._process.pid if self._process is not None else None
        if self._diagnostics:
            self._diagnostics.record_stage(
                "PIPE_TIMEOUT",
                pipe_name=self._pipe_name,
                core_alive=is_alive,
                core_pid=pid,
            )
        exc = TimeoutError(f"Timeout waiting for control channel pipe {self._pipe_name} (core_alive={is_alive}, pid={pid})")
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
        self._release_process()
        self._close_debug_streams()
        self._provenance = None
        self._close_provenance_guards()
        self._close_lifetime_job()
        return int(exit_code)

    def terminate_owned_process_after_timeout(
        self, expected_pid: int, timeout: float
    ) -> int:
        """Emergency fallback using only the exact retained child handle."""
        process = self._require_exact_owned_process(expected_pid)
        try:
            process.kill()
            try:
                return int(process.wait(timeout=timeout))
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError("owned Core process resisted termination") from exc
        finally:
            self._release_process()
            self._close_debug_streams()
            self._provenance = None
            self._close_provenance_guards()
            self._close_lifetime_job()

    def _require_exact_owned_process(self, expected_pid: int) -> subprocess.Popen[Any]:
        process = self._process
        if process is None or process.pid != expected_pid:
            raise RuntimeError("exact owned Core process is unavailable")
        return process
