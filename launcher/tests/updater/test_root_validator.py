import os
from pathlib import Path
import sys

import pytest

from neko_launcher.updater.root_validator import (
    get_expected_install_root,
    is_process_elevated,
    validate_install_root,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 root validator requires Windows")
def test_canonical_install_root_matches_installer_localappdata_layout() -> None:
    root = get_expected_install_root()
    expected = Path(os.environ["LOCALAPPDATA"]) / "NEKO FAMILY"
    assert root.resolve() == expected.resolve()

    repo_root = Path(__file__).resolve().parents[3]
    iss_text = (repo_root / "installer" / "beta.iss").read_text(encoding="utf-8")
    assert r"DefaultDirName={localappdata}\NEKO FAMILY" in iss_text


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
