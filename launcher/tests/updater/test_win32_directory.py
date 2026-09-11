import ctypes
from pathlib import Path
import sys

import pytest

from neko_launcher.updater.win32_directory import (
    create_incoming_container,
    get_directory_identity,
    open_directory_guarded,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 handle tests require Windows")
def test_create_incoming_container_returns_valid_identity(tmp_path: Path) -> None:
    req_id = "a" * 32
    handle, identity, path = create_incoming_container(tmp_path, req_id)
    try:
        assert path.exists()
        assert path.is_dir()
        assert len(identity.volume_serial) == 16
        assert len(identity.file_id) == 32
        assert len(identity.parent_file_id) == 32
        # Verify hex format
        int(identity.volume_serial, 16)
        int(identity.file_id, 16)
        int(identity.parent_file_id, 16)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 handle tests require Windows")
def test_open_directory_guarded_matches_get_directory_identity(tmp_path: Path) -> None:
    target_dir = tmp_path / "guarded_test"
    target_dir.mkdir()
    h1 = open_directory_guarded(target_dir)
    try:
        id1 = get_directory_identity(h1)
        assert len(id1.volume_serial) == 16
        assert len(id1.file_id) == 32
    finally:
        ctypes.windll.kernel32.CloseHandle(h1)
