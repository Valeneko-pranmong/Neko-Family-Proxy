"""Win32 Job-Object bound process spawner with explicit handle inheritance."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from neko_launcher.updater.ipc_channel import FramedIpcChannel


@dataclass(frozen=True)
class ManagedChildProcess:
    process_handle: int
    thread_handle: int
    pid: int
    job_handle: int
    ipc: FramedIpcChannel

    def terminate(self) -> None:
        """Terminate the child and close job handles."""
        raise NotImplementedError("terminate not implemented")


def spawn_managed_child(
    executable_path: Path,
    args: list[str],
    lease_handle: int,
) -> ManagedChildProcess:
    """Spawn child process bound to a kill-on-close Job Object with duplex framed IPC."""
    raise NotImplementedError("spawn_managed_child not implemented")
