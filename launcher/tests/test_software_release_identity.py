import hashlib
import re
from pathlib import Path
from typing import Any

import pytest

from neko_launcher.application.software_update_models import LocalReleaseIdentity

_READ_SIZE = 1024 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def execute_sha256_file(path: Path) -> str:
    from neko_launcher.infrastructure.software_release_identity import sha256_file

    return sha256_file(path)


def execute_load_local_release_identity(
    *,
    release_sequence: int,
    release_id: str,
    launcher_version: str,
    launcher_executable: Path,
    core_version: str,
    core_manifest: Path,
) -> LocalReleaseIdentity:
    from neko_launcher.infrastructure.software_release_identity import (
        load_local_release_identity,
    )

    return load_local_release_identity(
        release_sequence=release_sequence,
        release_id=release_id,
        launcher_version=launcher_version,
        launcher_executable=launcher_executable,
        core_version=core_version,
        core_manifest=core_manifest,
    )


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"known launcher bytes\n",
        bytes(range(256)),
        b"\x00\xff\x10\x80binary\x00payload\xfe",
    ],
    ids=["empty", "text", "all-byte-values", "binary"],
)
def test_sha256_file_returns_exact_lowercase_digest(
    tmp_path: Path,
    data: bytes,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(data)

    digest = execute_sha256_file(source)

    assert digest == hashlib.sha256(data).hexdigest()
    assert _SHA256_PATTERN.fullmatch(digest)


def test_sha256_file_streams_using_one_mibibyte_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = (bytes(range(256)) * (_READ_SIZE // 256) * 2) + b"remainder"
    source = tmp_path / "large.bin"
    source.write_bytes(data)
    original_open = Path.open
    requested_read_sizes: list[int] = []

    class RecordingFile:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped

        def read(self, size: int = -1) -> bytes:
            requested_read_sizes.append(size)
            return self._wrapped.read(size)

        def __enter__(self) -> "RecordingFile":
            self._wrapped.__enter__()
            return self

        def __exit__(self, *args: object) -> object:
            return self._wrapped.__exit__(*args)

        def close(self) -> None:
            self._wrapped.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

    def recording_open(path: Path, *args: Any, **kwargs: Any) -> RecordingFile:
        return RecordingFile(original_open(path, *args, **kwargs))

    monkeypatch.setattr(Path, "open", recording_open)

    digest = execute_sha256_file(source)

    assert digest == hashlib.sha256(data).hexdigest()
    positive_read_sizes = [size for size in requested_read_sizes if size > 0]
    assert len(positive_read_sizes) >= 3
    assert set(positive_read_sizes) == {_READ_SIZE}


def test_sha256_file_raises_oserror_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        execute_sha256_file(tmp_path / "missing.bin")


def test_sha256_file_raises_oserror_for_directory(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()

    with pytest.raises(OSError):
        execute_sha256_file(directory)


def test_loader_returns_identity_with_independent_exact_hashes(
    tmp_path: Path,
) -> None:
    launcher_bytes = b"launcher executable identity\x00\xff"
    core_manifest_bytes = b'{"core":"manifest","version":"8.4.2"}\n'
    launcher = tmp_path / "launcher.exe"
    core_manifest = tmp_path / "core-manifest.json"
    launcher.write_bytes(launcher_bytes)
    core_manifest.write_bytes(core_manifest_bytes)

    result = execute_load_local_release_identity(
        release_sequence=42,
        release_id="release-42",
        launcher_version="5.1.0",
        launcher_executable=launcher,
        core_version="8.4.2",
        core_manifest=core_manifest,
    )

    launcher_digest = hashlib.sha256(launcher_bytes).hexdigest()
    core_digest = hashlib.sha256(core_manifest_bytes).hexdigest()
    assert isinstance(result, LocalReleaseIdentity)
    assert result.release_sequence == 42
    assert result.release_id == "release-42"
    assert result.launcher_version == "5.1.0"
    assert result.launcher_installed_identity_sha256 == launcher_digest
    assert result.core_version == "8.4.2"
    assert result.core_installed_identity_sha256 == core_digest
    assert result.launcher_installed_identity_sha256 != core_digest
    assert result.core_installed_identity_sha256 != launcher_digest
    assert _SHA256_PATTERN.fullmatch(
        result.launcher_installed_identity_sha256
    )
    assert _SHA256_PATTERN.fullmatch(result.core_installed_identity_sha256)


@pytest.mark.parametrize(
    "invalid_input",
    [
        "missing-launcher",
        "missing-core-manifest",
        "launcher-directory",
        "core-directory",
    ],
)
def test_loader_raises_oserror_for_missing_or_non_file_inputs(
    tmp_path: Path,
    invalid_input: str,
) -> None:
    launcher = tmp_path / "launcher.exe"
    core_manifest = tmp_path / "core-manifest.json"
    launcher.write_bytes(b"launcher")
    core_manifest.write_bytes(b"core manifest")

    if invalid_input == "missing-launcher":
        launcher.unlink()
    elif invalid_input == "missing-core-manifest":
        core_manifest.unlink()
    elif invalid_input == "launcher-directory":
        launcher.unlink()
        launcher.mkdir()
    else:
        core_manifest.unlink()
        core_manifest.mkdir()

    with pytest.raises(OSError):
        execute_load_local_release_identity(
            release_sequence=1,
            release_id="release-1",
            launcher_version="5.1.0",
            launcher_executable=launcher,
            core_version="1.0.0",
            core_manifest=core_manifest,
        )


def test_loader_accepts_unpublished_development_identity(
    tmp_path: Path,
) -> None:
    launcher_bytes = b"development launcher"
    manifest_bytes = b"development core manifest"
    launcher = tmp_path / "launcher.exe"
    core_manifest = tmp_path / "core-manifest.json"
    launcher.write_bytes(launcher_bytes)
    core_manifest.write_bytes(manifest_bytes)

    result = execute_load_local_release_identity(
        release_sequence=0,
        release_id="dev-unpublished",
        launcher_version="5.1.0-dev",
        launcher_executable=launcher,
        core_version="1.0.0-dev",
        core_manifest=core_manifest,
    )

    assert result.release_sequence == 0
    assert result.release_id == "dev-unpublished"
    assert result.launcher_installed_identity_sha256 == hashlib.sha256(
        launcher_bytes
    ).hexdigest()
    assert result.core_installed_identity_sha256 == hashlib.sha256(
        manifest_bytes
    ).hexdigest()


@pytest.mark.parametrize(
    "release_id",
    ["release-0", "dev", "", "DEV-UNPUBLISHED"],
)
def test_loader_rejects_non_development_id_for_sequence_zero(
    tmp_path: Path,
    release_id: str,
) -> None:
    launcher = tmp_path / "launcher.exe"
    core_manifest = tmp_path / "core-manifest.json"
    launcher.write_bytes(b"launcher")
    core_manifest.write_bytes(b"manifest")

    with pytest.raises(ValueError):
        execute_load_local_release_identity(
            release_sequence=0,
            release_id=release_id,
            launcher_version="5.1.0-dev",
            launcher_executable=launcher,
            core_version="1.0.0-dev",
            core_manifest=core_manifest,
        )


def test_loader_preserves_published_release_identity(tmp_path: Path) -> None:
    launcher = tmp_path / "launcher.exe"
    core_manifest = tmp_path / "core-manifest.json"
    launcher.write_bytes(b"published launcher")
    core_manifest.write_bytes(b"published manifest")

    result = execute_load_local_release_identity(
        release_sequence=1,
        release_id="beta-1",
        launcher_version="5.1.0-beta.1",
        launcher_executable=launcher,
        core_version="1.0.0-beta.1",
        core_manifest=core_manifest,
    )

    assert result.release_sequence == 1
    assert result.release_id == "beta-1"


def test_loader_does_not_mutate_inputs_or_create_files(tmp_path: Path) -> None:
    launcher = tmp_path / "launcher.exe"
    core_manifest = tmp_path / "core-manifest.json"
    launcher.write_bytes(b"\x00launcher input\xff")
    core_manifest.write_bytes(b'{"files":["core.exe"]}\n')

    launcher_bytes_before = launcher.read_bytes()
    manifest_bytes_before = core_manifest.read_bytes()
    launcher_size_before = launcher.stat().st_size
    manifest_size_before = core_manifest.stat().st_size
    files_before = sorted(path.name for path in tmp_path.iterdir())

    execute_load_local_release_identity(
        release_sequence=7,
        release_id="release-7",
        launcher_version="5.1.0",
        launcher_executable=launcher,
        core_version="7.0.0",
        core_manifest=core_manifest,
    )

    assert launcher.read_bytes() == launcher_bytes_before
    assert core_manifest.read_bytes() == manifest_bytes_before
    assert launcher.stat().st_size == launcher_size_before
    assert core_manifest.stat().st_size == manifest_size_before
    assert sorted(path.name for path in tmp_path.iterdir()) == files_before
    assert files_before == ["core-manifest.json", "launcher.exe"]


def test_loader_uses_core_manifest_file_as_exact_core_identity(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "launcher.exe"
    core_directory = tmp_path / "core"
    core_directory.mkdir()
    core_manifest = core_directory / "manifest.json"
    unrelated_file = core_directory / "unrelated.dat"
    manifest_bytes = b'{"canonical":true,"files":["core.exe"]}\n'
    unrelated_bytes = b"unrelated directory content"
    launcher.write_bytes(b"launcher")
    core_manifest.write_bytes(manifest_bytes)
    unrelated_file.write_bytes(unrelated_bytes)

    first_result = execute_load_local_release_identity(
        release_sequence=9,
        release_id="release-9",
        launcher_version="5.1.0",
        launcher_executable=launcher,
        core_version="9.0.0",
        core_manifest=core_manifest,
    )
    unrelated_file.write_bytes(b"changed unrelated directory content")
    second_result = execute_load_local_release_identity(
        release_sequence=9,
        release_id="release-9",
        launcher_version="5.1.0",
        launcher_executable=launcher,
        core_version="9.0.0",
        core_manifest=core_manifest,
    )

    expected_manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    synthetic_combined_digest = hashlib.sha256(
        manifest_bytes + unrelated_bytes
    ).hexdigest()
    assert first_result.core_installed_identity_sha256 == expected_manifest_digest
    assert second_result.core_installed_identity_sha256 == expected_manifest_digest
    assert first_result.core_installed_identity_sha256 != synthetic_combined_digest
