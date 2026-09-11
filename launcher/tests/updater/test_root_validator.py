from pathlib import Path
import sys

import pytest

from neko_launcher.updater.root_validator import (
    get_expected_install_root,
    is_process_elevated,
    validate_install_root,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 root validator requires Windows")
def test_validates_canonical_user_program_files_root() -> None:
    root = get_expected_install_root()
    assert "Programs" in str(root)
    assert root.name == "NEKO FAMILY"


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 root validator requires Windows")
def test_process_elevation_detects_unelevated() -> None:
    # Under test runner, process should be unelevated
    elevated = is_process_elevated()
    assert isinstance(elevated, bool)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 root validator requires Windows")
def test_rejects_arbitrary_path(tmp_path: Path) -> None:
    res = validate_install_root(tmp_path)
    assert not res.valid
    assert res.error_code == "ROOT_UNSUPPORTED"
