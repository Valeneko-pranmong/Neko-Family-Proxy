"""Detect whether specific game processes are currently running."""

from __future__ import annotations

import os
import subprocess
from typing import FrozenSet, Sequence

# Process names that trigger automatic ProxyCore activation.
PSO2_PROCESS_NAMES: FrozenSet[str] = frozenset({
    "pso2.exe",
    "pso2launcher.exe",
})


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