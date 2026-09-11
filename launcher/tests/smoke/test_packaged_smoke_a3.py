from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

import pytest

EXPECTED_VERSION = "5.1.0"
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
STILL_ACTIVE = 259
WM_CLOSE = 0x0010
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_USER32: object | None = None


def _bind_user32(user32: object) -> object:
    signatures = {
        "EnumWindows": ([WNDENUMPROC, wintypes.LPARAM], wintypes.BOOL),
        "GetWindowThreadProcessId": (
            [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
        "GetWindowTextLengthW": ([wintypes.HWND], ctypes.c_int),
        "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        "PostMessageW": (
            [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(user32, name)
        function.argtypes = argtypes
        function.restype = restype
    return user32


def _user32() -> object:
    global _USER32
    if _USER32 is None:
        _USER32 = _bind_user32(ctypes.windll.user32)
    return _USER32


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
                ("hStdError", wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _job_limit_flags() -> int:
    return JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE


class WindowsJobApi:
    def __init__(self) -> None:
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "CreateProcessW": (
                [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                 wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                 ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)],
                wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
            "QueryInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                 ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "GetExitCodeProcess": (
                [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        }
        for name, (argtypes, restype) in signatures.items():
            function = getattr(self.k32, name)
            function.argtypes = argtypes
            function.restype = restype

    def _assert(self, ok: object, operation: str) -> None:
        if not ok:
            raise AssertionError(f"{operation} failed with Windows error {ctypes.get_last_error()}")

    def create_job(self) -> int:
        handle = self.k32.CreateJobObjectW(None, None)
        self._assert(handle, "CreateJobObjectW")
        return int(handle)

    def set_limits(self, job: int, flags: int) -> None:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = flags
        self._assert(self.k32.SetInformationJobObject(
            job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)),
            "SetInformationJobObject")

    def create_suspended(self, executable: Path, cwd: Path, env: dict[str, str]) -> tuple[int, int, int]:
        startup = STARTUPINFOW(cb=ctypes.sizeof(STARTUPINFOW))
        process = PROCESS_INFORMATION()
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(executable)]))
        environment = ctypes.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in sorted(env.items())) + "\0\0")
        self._assert(self.k32.CreateProcessW(
            str(executable), command, None, None, False,
            CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT, environment, str(cwd),
            ctypes.byref(startup), ctypes.byref(process)), "CreateProcessW")
        return int(process.hProcess), int(process.hThread), int(process.dwProcessId)

    def assign(self, job: int, process: int) -> None:
        self._assert(self.k32.AssignProcessToJobObject(job, process), "AssignProcessToJobObject")

    def resume(self, thread: int) -> None:
        result = self.k32.ResumeThread(thread)
        self._assert(result != 0xFFFFFFFF, "ResumeThread")

    def members(self, job: int) -> set[int]:
        capacity = 16
        while True:
            size = ctypes.sizeof(wintypes.DWORD) * 2 + ctypes.sizeof(ctypes.c_size_t) * capacity
            buffer = ctypes.create_string_buffer(size)
            if self.k32.QueryInformationJobObject(job, JOB_OBJECT_BASIC_PROCESS_ID_LIST,
                                                   buffer, size, None):
                assigned = wintypes.DWORD.from_buffer(buffer, 0).value
                count = wintypes.DWORD.from_buffer(buffer, ctypes.sizeof(wintypes.DWORD)).value
                if assigned > capacity:
                    capacity = assigned
                    continue
                array_type = ctypes.c_size_t * count
                offset = ctypes.sizeof(wintypes.DWORD) * 2
                return set(array_type.from_buffer(buffer, offset))
            error = ctypes.get_last_error()
            if error == 122:
                capacity *= 2
                continue
            raise AssertionError(f"QueryInformationJobObject failed with Windows error {error}")

    def terminate_process(self, process: int) -> None:
        self._assert(self.k32.TerminateProcess(process, 1), "TerminateProcess")

    def terminate_job(self, job: int) -> None:
        self._assert(self.k32.TerminateJobObject(job, 1), "TerminateJobObject")

    def close(self, handle: int) -> None:
        self._assert(self.k32.CloseHandle(handle), "CloseHandle")

    def exit_code(self, process: int) -> int:
        value = wintypes.DWORD()
        self._assert(self.k32.GetExitCodeProcess(process, ctypes.byref(value)), "GetExitCodeProcess")
        return int(value.value)


class JobOwner:
    def __init__(self, api: object | None = None) -> None:
        self.api = api or WindowsJobApi()
        self.job: int | None = None
        self.process: int | None = None
        self.thread: int | None = None
        self.pid: int | None = None

    def launch(self, executable: Path, cwd: Path, env: dict[str, str]) -> None:
        self.job = self.api.create_job()
        thread_close_attempted = False
        try:
            self.api.set_limits(self.job, _job_limit_flags())
            self.process, self.thread, self.pid = self.api.create_suspended(executable, cwd, env)
            self.api.assign(self.job, self.process)
            self.api.resume(self.thread)
            thread_close_attempted = True
            self._close_handles(("thread",))
        except BaseException as primary:
            cleanup_errors: list[Exception] = []
            if self.process is not None:
                try:
                    self.api.terminate_process(self.process)
                except Exception as error:  # noqa: BLE001 - cleanup must remain best-effort
                    cleanup_errors.append(error)
            fields = ("process", "job") if thread_close_attempted else ("thread", "process", "job")
            cleanup_errors.extend(self._close_handles(fields, raise_first=False))
            for error in cleanup_errors:
                primary.add_note(f"cleanup failure: {error!r}")
            raise

    def _close_handles(self, fields: tuple[str, ...], *,
                       raise_first: bool = True) -> list[Exception]:
        errors: list[Exception] = []
        for field in fields:
            handle = getattr(self, field)
            if handle is None:
                continue
            try:
                self.api.close(handle)
            except Exception as error:  # noqa: BLE001 - attempt every handle release
                errors.append(error)
            else:
                setattr(self, field, None)
        if errors and raise_first:
            raise errors[0]
        return errors

    @staticmethod
    def _raise_first(errors: list[Exception]) -> None:
        if errors:
            raise errors[0]

    def member_pids(self) -> set[int]:
        assert self.job is not None
        return self.api.members(self.job)

    def wait_for_drain(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if not self.member_pids():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def root_exit_code(self) -> int:
        assert self.process is not None
        return self.api.exit_code(self.process)

    def cleanup(self) -> None:
        errors: list[BaseException] = []
        if self.job is not None:
            try:
                self.api.terminate_job(self.job)
            except Exception as error:  # noqa: BLE001 - closes must still be attempted
                errors.append(error)
        errors.extend(self._close_handles(("process", "job"), raise_first=False))
        self._raise_first(errors)

    def close(self) -> None:
        self._close_handles(("process", "job"))


class FakeJobApi:
    def __init__(self, *, fail_assign: bool = False, fail_resume: bool = False,
                 fail_query: bool = False, fail_terminate_process: bool = False,
                 fail_terminate_job: bool = False, fail_close: set[int] | None = None,
                 member_sequences: list[set[int]] | None = None) -> None:
        self.fail_assign, self.fail_resume, self.fail_query = fail_assign, fail_resume, fail_query
        self.fail_terminate_process, self.fail_terminate_job = fail_terminate_process, fail_terminate_job
        self.fail_close = set(fail_close or set())
        self.member_sequences = list(member_sequences or [set()])
        self.calls: list[str] = []
        self.closed: list[int] = []
        self.close_attempts: list[int] = []
        self.terminated: list[int] = []
        self.terminated_jobs: list[int] = []

    def create_job(self) -> int:
        self.calls.append("create_job")
        return 303

    def set_limits(self, job: int, flags: int) -> None: self.calls.append("set_limits")
    def create_suspended(self, executable: Path, cwd: Path, env: dict[str, str]) -> tuple[int, int, int]:
        self.calls.append("create_suspended")
        return 101, 202, 101
    def assign(self, job: int, process: int) -> None:
        self.calls.append("assign")
        if self.fail_assign:
            raise AssertionError("AssignProcessToJobObject failed")
    def resume(self, thread: int) -> None:
        self.calls.append("resume")
        if self.fail_resume:
            raise AssertionError("ResumeThread failed")
    def members(self, job: int) -> set[int]:
        if self.fail_query:
            raise AssertionError("QueryInformationJobObject failed")
        return self.member_sequences.pop(0) if len(self.member_sequences) > 1 else self.member_sequences[0]
    def terminate_process(self, process: int) -> None:
        self.terminated.append(process)
        if self.fail_terminate_process:
            raise AssertionError("TerminateProcess failed")
    def terminate_job(self, job: int) -> None:
        self.terminated_jobs.append(job)
        if self.fail_terminate_job:
            raise AssertionError("TerminateJobObject failed")
    def close(self, handle: int) -> None:
        self.close_attempts.append(handle)
        if handle in self.fail_close:
            raise AssertionError(f"CloseHandle failed: {handle}")
        self.closed.append(handle)
    def exit_code(self, process: int) -> int: return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _visible_windows(owned: set[int]) -> list[tuple[int, int, str, str]]:
    user32 = _user32()
    found: list[tuple[int, int, str, str]] = []
    @WNDENUMPROC
    def visit(hwnd: int, _lparam: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in owned and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            user32.GetClassNameW(hwnd, class_name, len(class_name))
            found.append((int(hwnd), int(pid.value), title.value, class_name.value))
        return True
    assert user32.EnumWindows(visit, 0), "EnumWindows failed"
    return found


def _wait_for_window(owner: JobOwner, timeout: float = 30.0) -> list[tuple[int, int, str, str]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        windows = _visible_windows(owner.member_pids())
        if any("NEKO FAMILY PROXY" in title.upper() for _, _, title, _ in windows):
            return windows
        time.sleep(0.2)
    pytest.fail("job-owned launcher process tree did not expose a visible NEKO FAMILY PROXY window")


def _candidate_version_evidence(candidate_dir: Path, launcher: Path) -> None:
    record_path = candidate_dir / "build-record.json"
    assert record_path.is_file(), "build-record.json is required to bind launcher hash to version evidence"
    assert json.loads(record_path.read_text(encoding="utf-8")).get("launcher_sha256") == _sha256(launcher)
    launcher_root = Path(__file__).resolve().parents[2]
    assert f'version = "{EXPECTED_VERSION}"' in (launcher_root / "pyproject.toml").read_text(encoding="utf-8")
    assert f'__version__ = "{EXPECTED_VERSION}"' in (launcher_root / "src/neko_launcher/__init__.py").read_text(encoding="utf-8")


def test_packaged_candidate_a3_lifecycle(candidate_dir: Path, tmp_path: Path) -> None:
    launcher, updater = candidate_dir / "NekoLauncher.exe", candidate_dir / "NekoUpdater.exe"
    check = subprocess.run(
        [updater, "--self-check"], capture_output=True, text=True, timeout=15, check=False,
    )
    assert check.returncode == 0, check.stderr or check.stdout
    _candidate_version_evidence(candidate_dir, launcher)
    scratch = tmp_path / "isolated-profile"
    scratch.mkdir()
    before_mei = set(scratch.glob("_MEI*"))
    env = os.environ.copy()
    env.update({"TEMP": str(scratch), "TMP": str(scratch), "LOCALAPPDATA": str(scratch)})
    owner = JobOwner()
    graceful = False
    try:
        owner.launch(launcher, candidate_dir, env)
        windows = _wait_for_window(owner)
        dialogs = [title for _, _, title, cls in windows if cls == "#32770" and any(w in title.lower() for w in ("error", "exception", "traceback"))]
        assert not dialogs, f"unhandled exception dialog(s): {dialogs}"
        for hwnd, _, title, _ in windows:
            if "NEKO FAMILY PROXY" in title.upper():
                _user32().PostMessageW(hwnd, WM_CLOSE, 0, 0)
        graceful = owner.wait_for_drain(10)
        assert graceful, "job-owned process remained after graceful shutdown"
        assert owner.root_exit_code() == 0, "launcher did not shut down normally with exit code 0"
    finally:
        if graceful:
            owner.close()
        else:
            owner.cleanup()
    assert not list(scratch.rglob("launcher-error.log")), "launcher-error.log was produced"
    after_mei = set(scratch.glob("_MEI*"))
    assert after_mei == before_mei, f"candidate-created _MEI directories were not cleaned: {after_mei - before_mei}"


def test_job_limits_kill_on_close_without_breakaway() -> None:
    assert _job_limit_flags() & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert not _job_limit_flags() & JOB_OBJECT_LIMIT_BREAKAWAY_OK
    assert not _job_limit_flags() & JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK


def test_user32_api_declares_complete_pointer_safe_signatures() -> None:
    class FakeFunction:
        pass

    class FakeUser32:
        def __init__(self) -> None:
            for name in (
                "EnumWindows", "GetWindowThreadProcessId", "IsWindowVisible",
                "GetWindowTextLengthW", "GetWindowTextW", "GetClassNameW", "PostMessageW",
            ):
                setattr(self, name, FakeFunction())

    user32 = FakeUser32()
    bound = _bind_user32(user32)

    assert bound is user32
    expected = {
        "EnumWindows": ([WNDENUMPROC, wintypes.LPARAM], wintypes.BOOL),
        "GetWindowThreadProcessId": (
            [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
        "GetWindowTextLengthW": ([wintypes.HWND], ctypes.c_int),
        "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        "PostMessageW": (
            [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
    }
    for name, (argtypes, restype) in expected.items():
        function = getattr(user32, name)
        assert function.argtypes == argtypes, name
        assert function.restype is restype, name
    assert ctypes.sizeof(expected["IsWindowVisible"][0][0]) == ctypes.sizeof(ctypes.c_void_p)


def test_windows_job_api_declares_complete_handle_safe_signatures(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeFunction:
        pass

    class FakeKernel32:
        def __init__(self) -> None:
            for name in (
                "CreateJobObjectW", "SetInformationJobObject", "CreateProcessW",
                "AssignProcessToJobObject", "ResumeThread", "QueryInformationJobObject",
                "TerminateProcess", "TerminateJobObject", "CloseHandle", "GetExitCodeProcess",
            ):
                setattr(self, name, FakeFunction())

    kernel32 = FakeKernel32()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    WindowsJobApi()

    expected = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": (
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "CreateProcessW": (
            [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
             wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
             ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)], wintypes.BOOL),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
    }
    for name, (argtypes, restype) in expected.items():
        function = getattr(kernel32, name)
        assert function.argtypes == argtypes, name
        assert function.restype is restype, name


def test_launch_thread_close_failure_attempts_each_acquired_handle_once() -> None:
    api = FakeJobApi(fail_close={202})
    owner = JobOwner(api)
    with pytest.raises(AssertionError, match="CloseHandle failed: 202"):
        owner.launch(Path("candidate.exe"), Path("."), {})
    assert api.close_attempts == [202, 101, 303]
    assert owner.thread == 202 and owner.process is None and owner.job is None


def test_job_launch_orders_suspended_assign_resume() -> None:
    api = FakeJobApi()
    JobOwner(api).launch(Path("candidate.exe"), Path("."), {})
    assert api.calls == ["create_job", "set_limits", "create_suspended", "assign", "resume"]


def test_job_assignment_failure_fails_closed_and_cleans_suspended_process() -> None:
    api = FakeJobApi(fail_assign=True)
    with pytest.raises(AssertionError, match="AssignProcessToJobObject"):
        JobOwner(api).launch(Path("candidate.exe"), Path("."), {})
    assert api.terminated == [101]
    assert api.closed == [202, 101, 303]


def test_cleanup_terminate_failure_still_attempts_each_close_once() -> None:
    api = FakeJobApi(fail_terminate_job=True)
    owner = JobOwner(api)
    owner.job, owner.process = 303, 101
    with pytest.raises(AssertionError, match="TerminateJobObject"):
        owner.cleanup()
    assert api.terminated_jobs == [303]
    assert api.close_attempts == [101, 303]
    assert owner.process is None and owner.job is None


def test_process_close_failure_still_attempts_job_close_and_retains_failed_handle() -> None:
    api = FakeJobApi(fail_close={101})
    owner = JobOwner(api)
    owner.job, owner.process = 303, 101
    with pytest.raises(AssertionError, match="CloseHandle failed: 101"):
        owner.close()
    assert api.close_attempts == [101, 303]
    assert owner.process == 101 and owner.job is None


@pytest.mark.parametrize(("fail_assign", "fail_resume", "primary"), [
    (True, False, "AssignProcessToJobObject"),
    (False, True, "ResumeThread"),
])
def test_launch_primary_failure_survives_all_cleanup_failures(
        fail_assign: bool, fail_resume: bool, primary: str) -> None:
    api = FakeJobApi(
        fail_assign=fail_assign, fail_resume=fail_resume, fail_terminate_process=True,
        fail_close={101, 202, 303},
    )
    owner = JobOwner(api)
    with pytest.raises(AssertionError, match=primary):
        owner.launch(Path("candidate.exe"), Path("."), {})
    assert api.terminated == [101]
    assert api.close_attempts == [202, 101, 303]
    assert owner.thread == 202 and owner.process == 101 and owner.job == 303


def test_persistent_member_fails_drain_then_cleanup_targets_job_only() -> None:
    api = FakeJobApi(member_sequences=[{101, 102}, {102}])
    owner = JobOwner(api)
    owner.launch(Path("candidate.exe"), Path("."), {})
    assert not owner.wait_for_drain(0)
    owner.cleanup()
    assert api.terminated_jobs == [303] and api.terminated == []


def test_late_child_remains_owned_after_intermediate_parent_exits() -> None:
    api = FakeJobApi(member_sequences=[{101, 102}, {101, 103}, {103}])
    owner = JobOwner(api)
    owner.launch(Path("candidate.exe"), Path("."), {})
    assert owner.member_pids() == {101, 102}
    assert owner.member_pids() == {101, 103}
    assert owner.member_pids() == {103}


def test_job_query_error_fails_closed() -> None:
    api = FakeJobApi(fail_query=True)
    owner = JobOwner(api)
    owner.launch(Path("candidate.exe"), Path("."), {})
    with pytest.raises(AssertionError, match="QueryInformationJobObject"):
        owner.member_pids()


def test_ownership_has_no_pid_ppid_snapshot_implementation() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = "CreateToolhelp32" + "Snapshot"
    assert forbidden not in source
    assert ("th32Parent" + "ProcessID") not in source
