"""Detect whether specific game processes are currently running."""

from __future__ import annotations

import csv
import os
import subprocess
from dataclasses import dataclass
from io import StringIO
from threading import Event
from time import monotonic
from typing import Callable, FrozenSet, Sequence

# Process names that trigger automatic ProxyCore activation.
PSO2_PROCESS_NAMES: FrozenSet[str] = frozenset({"pso2.exe"})


@dataclass(frozen=True)
class TargetProcess:
    pid: int
    image_name: str


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
            for process in self._snapshot():
                if process.image_name.casefold() == "pso2.exe":
                    return process
            remaining = deadline - monotonic()
            if remaining <= 0:
                return None
            cancellation.wait(min(self._poll_interval, remaining))
        return None

    def is_same_target_still_running(self, target: TargetProcess) -> bool:
        return any(
            process.pid == target.pid
            and process.image_name.casefold() == "pso2.exe"
            for process in self._snapshot()
        )


def is_any_process_running(names: Sequence[str] | FrozenSet[str] = PSO2_PROCESS_NAMES) -> bool:
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
        # If the detection mechanism itself fails we must not crash the
        # launcher – simply report "not detected".
        return False


def _check_windows(lower_names: set[str]) -> bool:
    result = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
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
    for line in result.stdout.splitlines():
        comm = line.strip().lower()
        if comm in lower_names:
            return True
    return False


def _snapshot_processes() -> tuple[TargetProcess, ...]:
    """Return a sanitized process identity snapshot; detection errors fail closed."""
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            processes: list[TargetProcess] = []
            for row in csv.reader(StringIO(result.stdout)):
                if len(row) < 2:
                    continue
                try:
                    processes.append(TargetProcess(int(row[1]), row[0]))
                except ValueError:
                    continue
            return tuple(processes)

        result = subprocess.run(
            ["ps", "-eo", "pid=,comm="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        processes = []
        for line in result.stdout.splitlines():
            pid, separator, image = line.strip().partition(" ")
            if not separator:
                continue
            try:
                processes.append(TargetProcess(int(pid), image.strip()))
            except ValueError:
                continue
        return tuple(processes)
    except Exception:
        return ()
