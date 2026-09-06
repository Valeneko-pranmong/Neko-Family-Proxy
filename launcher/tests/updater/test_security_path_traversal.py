import io
from pathlib import Path
import zipfile

import pytest

from neko_launcher.updater.zip_extractor import ZipSecurityError, extract_core_bundle


def test_rejects_dotdot_traversal(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.exe", b"bad")
    buf.seek(0)
    zip_path = tmp_path / "bad.zip"
    zip_path.write_bytes(buf.getvalue())

    dest = tmp_path / "out"
    with pytest.raises(ZipSecurityError, match="Path traversal rejected"):
        extract_core_bundle(zip_path, dest)


def test_rejects_reserved_device_names(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("con.txt", b"bad")
    buf.seek(0)
    zip_path = tmp_path / "bad.zip"
    zip_path.write_bytes(buf.getvalue())

    dest = tmp_path / "out"
    with pytest.raises(ZipSecurityError, match="Reserved Win32 device name"):
        extract_core_bundle(zip_path, dest)


def test_rejects_alternate_data_streams(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("file.txt:hidden", b"bad")
    buf.seek(0)
    zip_path = tmp_path / "bad.zip"
    zip_path.write_bytes(buf.getvalue())

    dest = tmp_path / "out"
    with pytest.raises(ZipSecurityError, match="Disallowed character ':'"):
        extract_core_bundle(zip_path, dest)


def test_rejects_backslash_in_zip_path() -> None:
    from neko_launcher.updater.zip_extractor import _validate_entry_path

    with pytest.raises(ZipSecurityError, match="Backslash disallowed"):
        _validate_entry_path(r"sub\file.txt")
