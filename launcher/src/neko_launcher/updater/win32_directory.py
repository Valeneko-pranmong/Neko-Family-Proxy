"""Win32 DirectoryIdentity and handle-safe directory operations."""
from __future__ import annotations

from pathlib import Path

from neko_launcher.updater.state_models import DirectoryIdentity


def get_directory_identity(dir_handle: int) -> DirectoryIdentity:
    """Retrieve 64-bit volume serial and 128-bit file ID from an open directory handle."""
    raise NotImplementedError("get_directory_identity not implemented")


def open_directory_guarded(path: Path) -> int:
    """Open a directory with FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, denying delete/rename sharing."""
    raise NotImplementedError("open_directory_guarded not implemented")


def create_incoming_container(root_dir: Path, request_id: str) -> tuple[int, DirectoryIdentity, Path]:
    """Exclusively create incoming/<request-id> directory and return (handle, identity, path)."""
    raise NotImplementedError("create_incoming_container not implemented")
