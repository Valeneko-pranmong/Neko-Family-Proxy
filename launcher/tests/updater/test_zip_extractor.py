import io
from pathlib import Path
import zipfile

import pytest

from neko_launcher.updater.zip_extractor import (
    ZipSecurityError,
    extract_core_bundle,
)


def test_extracts_valid_minimal_zip(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("test.txt", b"hello world")
        zf.writestr("mode/Game.txt", b"game mode config")
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(buf.getvalue())

    dest = tmp_path / "dest"
    summary = extract_core_bundle(zip_path, dest)
    assert (dest / "test.txt").read_bytes() == b"hello world"
    assert (dest / "mode" / "Game.txt").read_bytes() == b"game mode config"
    assert summary.file_count == 2
    assert summary.total_bytes == len(b"hello world") + len(b"game mode config")


def test_rejects_path_traversal(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", b"evil")
    zip_path = tmp_path / "evil.zip"
    zip_path.write_bytes(buf.getvalue())

    with pytest.raises(ZipSecurityError, match="Path traversal rejected"):
        extract_core_bundle(zip_path, tmp_path / "dest")


def test_rejects_win32_reserved_names(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nul.txt", b"evil device")
    zip_path = tmp_path / "con.zip"
    zip_path.write_bytes(buf.getvalue())

    with pytest.raises(ZipSecurityError, match="Reserved Win32 device name"):
        extract_core_bundle(zip_path, tmp_path / "dest")


def test_rejects_disallowed_characters(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test:stream.txt", b"ads")
    zip_path = tmp_path / "ads.zip"
    zip_path.write_bytes(buf.getvalue())

    with pytest.raises(ZipSecurityError, match="Disallowed character"):
        extract_core_bundle(zip_path, tmp_path / "dest")
