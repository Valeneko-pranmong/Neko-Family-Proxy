"""Staging area creation and atomic generation publication."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from neko_launcher.updater.state_models import DirectoryIdentity
from neko_launcher.updater.win32_directory import get_directory_identity, open_directory_guarded

MOVEFILE_WRITE_THROUGH = 0x00000008

_MoveFileExW = ctypes.windll.kernel32.MoveFileExW
_MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
_MoveFileExW.restype = wintypes.BOOL


class GenerationPublisher:
    """Manages transaction staging creation and atomic publication into releases/."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def create_staging_area(self, transaction_id: str) -> tuple[int, DirectoryIdentity, Path]:
        """Exclusively create staging/<transaction-id> and return (handle, identity, path)."""
        staging_parent = self.root_dir / "staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        stage_dir = staging_parent / transaction_id
        stage_dir.mkdir(parents=False, exist_ok=False)  # Exclusive create

        handle = open_directory_guarded(stage_dir)
        try:
            identity = get_directory_identity(handle)
            return handle, identity, stage_dir
        except Exception:
            ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle))
            raise

    def publish_generation(self, staging_generation_dir: Path, generation_id: str) -> Path:
        """Atomically rename staging_generation_dir into releases/<generation-id>."""
        releases_parent = self.root_dir / "releases"
        releases_parent.mkdir(parents=True, exist_ok=True)
        dest_dir = releases_parent / generation_id

        if dest_dir.exists():
            raise OSError(f"Destination generation directory '{dest_dir}' already exists")

        src_str = str(staging_generation_dir.resolve())
        dst_str = str(dest_dir.resolve())

        ok = _MoveFileExW(src_str, dst_str, MOVEFILE_WRITE_THROUGH)
        if not ok:
            err = ctypes.GetLastError()
            raise OSError(f"MoveFileExW failed to publish generation to '{dst_str}' (WinError {err})")

        return dest_dir
