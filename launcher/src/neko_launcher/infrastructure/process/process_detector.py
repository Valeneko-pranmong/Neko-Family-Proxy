"""Detect whether specific game processes are currently running."""

from __future__ import annotations

import csv
import ctypes
import os
import subprocess
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Callable, FrozenSet, Sequence

# Process names that trigger automatic ProxyCore activation.
PSO2_PROCESS_NAMES: FrozenSet[str] = frozenset({"pso2.exe"})


@dataclass(frozen=True)
class TargetProcess:
    pid: int
    image_name: str
    creation_identity: int


class ProcessObservationUnavailable(RuntimeError):
    """The process table could not be observed; this is not evidence of exit."""


class ExactPso2TargetDetector:
    """Bounded, cancellable detector for one exact pso2.exe process identity."""

    def __init__(
        self,
        *,
        snapshot: Callable[[], Sequence[TargetProcess]] | None = None,
        poll_interval: float = 0.25,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll interval must be positive")
        self._snapshot = snapshot or _snapshot_processes
        self._poll_interval = poll_interval

    def wait_for_exact_pso2(
        self, timeout: float, cancellation: Event
    ) -> TargetProcess | None:
        if timeout <= 0:
            raise ValueError("target timeout must be positive")
        deadline = monotonic() + timeout
        while not cancellation.is_set():
            try:
                snapshot = self._snapshot()
            except ProcessObservationUnavailable:
                snapshot = ()
            candidates = tuple(
                process for process in snapshot if process.image_name == "pso2.exe"
            )
            if len(candidates) == 1:
                return candidates[0]
            remaining = deadline - monotonic()
            if remaining <= 0:
                return None
            cancellation.wait(min(self._poll_interval, remaining))
        return None

    def is_same_target_still_running(self, target: TargetProcess) -> bool:
        return any(
            process.pid == target.pid
            and process.image_name == "pso2.exe"
            and process.creation_identity == target.creation_identity
            for process in self._snapshot()
        )


def is_any_process_running(
    names: Sequence[str] | FrozenSet[str] = PSO2_PROCESS_NAMES,
) -> bool | None:
    """Return *True* if any process whose name is in *names* is running.

    On Windows this shells out to ``tasklist`` which is available on all
    supported editions.  On other platforms it falls back to ``ps`` for
    development convenience but the launcher only targets Windows.
    """
    lower_names = {n.lower() for n in names}
    try:
        if os.name == "nt":
            return _check_windows(lower_names)
        return _check_posix(lower_names)
    except Exception:
        # Preserve the previous observation. An observation failure is not
        # evidence that the game exited and must not stop a healthy runtime.
        return None


def _check_windows(lower_names: set[str]) -> bool:
    result = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    result.check_returncode()
    for line in result.stdout.splitlines():
        # Each CSV line starts with "\"ImageName.exe\"", ...
        parts = line.split(",", 1)
        if not parts:
            continue
        image = parts[0].strip().strip('"').lower()
        if image in lower_names:
            return True
    return False


def _check_posix(lower_names: set[str]) -> bool:
    result = subprocess.run(
        ["ps", "-eo", "comm"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    result.check_returncode()
    for line in result.stdout.splitlines():
        comm = line.strip().lower()
        if comm in lower_names:
            return True
    return False


def _snapshot_processes() -> tuple[TargetProcess, ...]:
    """Return a sanitized snapshot while preserving observation failures."""
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            result.check_returncode()
            processes: list[TargetProcess] = []
            for row in csv.reader(StringIO(result.stdout)):
                if len(row) < 2:
                    continue
                try:
                    pid = int(row[1])
                except ValueError:
                    continue
                creation_identity = _windows_creation_identity(pid)
                if creation_identity is None:
                    if row[0].casefold() == "pso2.exe":
                        raise ProcessObservationUnavailable
                    continue
                processes.append(TargetProcess(pid, row[0], creation_identity))
            return tuple(processes)

        result = subprocess.run(
            ["ps", "-eo", "pid=,comm="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        result.check_returncode()
        processes = []
        for line in result.stdout.splitlines():
            pid, separator, image = line.strip().partition(" ")
            if not separator:
                continue
            try:
                numeric_pid = int(pid)
            except ValueError:
                continue
            creation_identity = _posix_creation_identity(numeric_pid)
            if creation_identity is not None:
                processes.append(
                    TargetProcess(numeric_pid, image.strip(), creation_identity)
                )
        return tuple(processes)
    except Exception as exc:
        raise ProcessObservationUnavailable from exc


def _windows_creation_identity(pid: int) -> int | None:
    """Return the immutable Windows process creation FILETIME, failing closed."""
    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    kernel32.GetProcessTimes.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None
    creation = ctypes.c_uint64()
    exit_time = ctypes.c_uint64()
    kernel = ctypes.c_uint64()
    user = ctypes.c_uint64()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        return creation.value
    finally:
        kernel32.CloseHandle(handle)


def _posix_creation_identity(pid: int) -> int | None:
    """Development-only process start ticks; production launcher targets Windows."""
    try:
        fields = (Path(f"/proc/{pid}/stat").read_text(encoding="ascii")).split()
        return int(fields[21])
    except (OSError, ValueError, IndexError):
        return None
