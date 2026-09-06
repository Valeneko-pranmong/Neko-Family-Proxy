"""Win32 Job-Object bound process spawner with explicit handle inheritance."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path

from neko_launcher.updater.ipc_channel import FramedIpcChannel

STARTF_USESTDHANDLES = 0x00000100
CREATE_SUSPENDED = 0x00000004
HANDLE_FLAG_INHERIT = 0x00000001

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryLimit", ctypes.c_size_t),
        ("PeakJobMemoryLimit", ctypes.c_size_t),
    ]


_k32 = ctypes.windll.kernel32

_CreatePipe = _k32.CreatePipe
_CreatePipe.argtypes = [
    ctypes.POINTER(wintypes.HANDLE),
    ctypes.POINTER(wintypes.HANDLE),
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    wintypes.DWORD,
]
_CreatePipe.restype = wintypes.BOOL

_SetHandleInformation = _k32.SetHandleInformation
_SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
_SetHandleInformation.restype = wintypes.BOOL

_CreateJobObjectW = _k32.CreateJobObjectW
_CreateJobObjectW.argtypes = [ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.LPCWSTR]
_CreateJobObjectW.restype = wintypes.HANDLE

_SetInformationJobObject = _k32.SetInformationJobObject
_SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
_SetInformationJobObject.restype = wintypes.BOOL

_AssignProcessToJobObject = _k32.AssignProcessToJobObject
_AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_AssignProcessToJobObject.restype = wintypes.BOOL

_CreateProcessW = _k32.CreateProcessW
_CreateProcessW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    wintypes.BOOL,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
_CreateProcessW.restype = wintypes.BOOL

_ResumeThread = _k32.ResumeThread
_ResumeThread.argtypes = [wintypes.HANDLE]
_ResumeThread.restype = wintypes.DWORD

_CloseHandle = _k32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]
_CloseHandle.restype = wintypes.BOOL

_TerminateProcess = _k32.TerminateProcess
_TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_TerminateProcess.restype = wintypes.BOOL


@dataclass(frozen=True)
class ManagedChildProcess:
    process_handle: int
    thread_handle: int
    pid: int
    job_handle: int
    ipc: FramedIpcChannel

    def terminate(self) -> None:
        """Terminate the child and close job handles."""
        if self.process_handle:
            _TerminateProcess(wintypes.HANDLE(self.process_handle), 0)
        self.ipc.close()
        if self.thread_handle:
            _CloseHandle(wintypes.HANDLE(self.thread_handle))
        if self.process_handle:
            _CloseHandle(wintypes.HANDLE(self.process_handle))
        if self.job_handle:
            _CloseHandle(wintypes.HANDLE(self.job_handle))


def spawn_managed_child(
    executable_path: Path,
    args: list[str],
    lease_handle: int,
) -> ManagedChildProcess:
    """Spawn child process bound to a kill-on-close Job Object with duplex framed IPC."""
    # Create stdin pipe (parent writes, child reads)
    h_stdin_read = wintypes.HANDLE()
    h_stdin_write = wintypes.HANDLE()
    sa = SECURITY_ATTRIBUTES(nLength=ctypes.sizeof(SECURITY_ATTRIBUTES), lpSecurityDescriptor=None, bInheritHandle=True)
    if not _CreatePipe(ctypes.byref(h_stdin_read), ctypes.byref(h_stdin_write), ctypes.byref(sa), 0):
        raise OSError(f"CreatePipe for stdin failed (WinError {_k32.GetLastError()})")
    # Make parent write handle non-inheritable
    _SetHandleInformation(h_stdin_write, HANDLE_FLAG_INHERIT, 0)

    # Create stdout pipe (child writes, parent reads)
    h_stdout_read = wintypes.HANDLE()
    h_stdout_write = wintypes.HANDLE()
    if not _CreatePipe(ctypes.byref(h_stdout_read), ctypes.byref(h_stdout_write), ctypes.byref(sa), 0):
        _CloseHandle(h_stdin_read)
        _CloseHandle(h_stdin_write)
        raise OSError(f"CreatePipe for stdout failed (WinError {_k32.GetLastError()})")
    # Make parent read handle non-inheritable
    _SetHandleInformation(h_stdout_read, HANDLE_FLAG_INHERIT, 0)

    # Create Job Object
    h_job = _CreateJobObjectW(None, None)
    if not h_job:
        _CloseHandle(h_stdin_read)
        _CloseHandle(h_stdin_write)
        _CloseHandle(h_stdout_read)
        _CloseHandle(h_stdout_write)
        raise OSError(f"CreateJobObjectW failed (WinError {_k32.GetLastError()})")

    job_limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    job_limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    _SetInformationJobObject(
        h_job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(job_limits),
        ctypes.sizeof(job_limits),
    )

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    si.dwFlags = STARTF_USESTDHANDLES
    si.hStdInput = h_stdin_read
    si.hStdOutput = h_stdout_write
    si.hStdError = wintypes.HANDLE(lease_handle) if lease_handle else wintypes.HANDLE(0)

    pi = PROCESS_INFORMATION()

    cmd_line = f'"{executable_path.resolve()}" ' + " ".join(args)
    cmd_buf = ctypes.create_unicode_buffer(cmd_line)

    ok = _CreateProcessW(
        None,
        cmd_buf,
        None,
        None,
        True,  # bInheritHandles
        CREATE_SUSPENDED,
        None,
        None,
        ctypes.byref(si),
        ctypes.byref(pi),
    )

    # Close child pipe ends in parent process regardless of success
    _CloseHandle(h_stdin_read)
    _CloseHandle(h_stdout_write)

    if not ok:
        err = _k32.GetLastError()
        _CloseHandle(h_stdin_write)
        _CloseHandle(h_stdout_read)
        _CloseHandle(h_job)
        raise OSError(f"CreateProcessW failed for '{executable_path}' (WinError {err})")

    # Assign to Job Object before resuming thread
    _AssignProcessToJobObject(h_job, pi.hProcess)
    _ResumeThread(pi.hThread)

    # Convert parent pipe handles to python OS file descriptors
    import msvcrt
    parent_read_fd = msvcrt.open_osfhandle(int(h_stdout_read.value), os.O_RDONLY)
    parent_write_fd = msvcrt.open_osfhandle(int(h_stdin_write.value), os.O_WRONLY)

    ipc = FramedIpcChannel(read_handle=parent_read_fd, write_handle=parent_write_fd)

    return ManagedChildProcess(
        process_handle=int(pi.hProcess),
        thread_handle=int(pi.hThread),
        pid=int(pi.dwProcessId),
        job_handle=int(h_job),
        ipc=ipc,
    )
