from __future__ import annotations

import hashlib
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from neko_launcher.application.software_update_models import ComponentRelease

MIB = 1024 * 1024
LAUNCHER_MAX = 128 * MIB
CORE_MAX = 1024 * MIB
PAYLOAD = b'candidate artifact bytes\x00\xff'


def component(
    *,
    name: str = 'launcher',
    size: int | None = None,
    sha256: str | None = None,
) -> ComponentRelease:
    return ComponentRelease(
        name=name,
        version='5.1.0a2' if name == 'launcher' else 'core-2',
        artifact_id=f'{name}-win-x64-beta-0002',
        artifact_sha256=sha256 or hashlib.sha256(PAYLOAD).hexdigest(),
        artifact_size=len(PAYLOAD) if size is None else size,
        installed_identity_sha256='a' * 64,
    )


def load_api() -> tuple[Any, type[ValueError], type[Any]]:
    try:
        from neko_launcher.infrastructure.software_update_artifact import (
            ArtifactVerificationError,
            VerifiedArtifact,
            verify_artifact,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f'software update artifact verifier is not implemented: {exc}')
    return verify_artifact, ArtifactVerificationError, VerifiedArtifact


def assert_error(
    path: Any,
    release: ComponentRelease,
    expected_code: str,
) -> None:
    verify_artifact, error_type, _ = load_api()
    with pytest.raises(error_type) as caught:
        verify_artifact(path, release)
    assert caught.value.code == expected_code
    assert str(caught.value) == expected_code


def test_exact_artifact_is_verified_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / 'candidate.bin'
    path.write_bytes(PAYLOAD)
    before = path.stat()
    names_before = sorted(item.name for item in tmp_path.iterdir())
    verify_artifact, _, verified_type = load_api()

    result = verify_artifact(path, component())

    assert isinstance(result, verified_type)
    assert result.component == 'launcher'
    assert result.path == path
    assert result.sha256 == hashlib.sha256(PAYLOAD).hexdigest()
    assert result.size == len(PAYLOAD)
    assert path.read_bytes() == PAYLOAD
    after = path.stat()
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert sorted(item.name for item in tmp_path.iterdir()) == names_before
    with pytest.raises(FrozenInstanceError):
        result.size = 0


def test_hashing_streams_read_only_in_one_mibibyte_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = (bytes(range(256)) * (MIB // 256) * 2) + b'remainder'
    path = tmp_path / 'streamed.bin'
    path.write_bytes(data)
    original_open = Path.open
    modes: list[str] = []
    read_sizes: list[int] = []

    class RecordingFile:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped

        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            return self._wrapped.read(size)

        def __enter__(self) -> 'RecordingFile':
            self._wrapped.__enter__()
            return self

        def __exit__(self, *args: object) -> object:
            return self._wrapped.__exit__(*args)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

    def recording_open(
        opened_path: Path,
        mode: str = 'r',
        *args: Any,
        **kwargs: Any,
    ) -> RecordingFile:
        modes.append(mode)
        return RecordingFile(original_open(opened_path, mode, *args, **kwargs))

    monkeypatch.setattr(Path, 'open', recording_open)
    verify_artifact, _, _ = load_api()
    release = component(size=len(data), sha256=hashlib.sha256(data).hexdigest())

    result = verify_artifact(path, release)

    assert result.size == len(data)
    assert modes == ['rb']
    assert len(read_sizes) >= 3
    assert set(read_sizes) == {MIB}


@pytest.mark.parametrize('signed_size', [len(PAYLOAD) - 1, len(PAYLOAD) + 1])
def test_wrong_size_is_rejected_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signed_size: int,
) -> None:
    path = tmp_path / 'candidate.bin'
    path.write_bytes(PAYLOAD)

    def forbidden_open(*args: object, **kwargs: object) -> object:
        raise AssertionError('size mismatch must be rejected before reading')

    monkeypatch.setattr(Path, 'open', forbidden_open)
    assert_error(path, component(size=signed_size), 'ARTIFACT_SIZE_MISMATCH')


def test_wrong_sha_is_rejected_without_mutating_file(tmp_path: Path) -> None:
    path = tmp_path / 'candidate.bin'
    path.write_bytes(PAYLOAD)
    before = path.stat()
    assert_error(path, component(sha256='0' * 64), 'ARTIFACT_HASH_MISMATCH')
    after = path.stat()
    assert path.read_bytes() == PAYLOAD
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)


@pytest.mark.parametrize('kind', ['missing', 'directory'])
def test_missing_or_non_file_artifact_fails_closed(
    tmp_path: Path,
    kind: str,
) -> None:
    path = tmp_path / 'candidate.bin'
    if kind == 'directory':
        path.mkdir()
    assert_error(path, component(), 'ARTIFACT_MISSING')


def test_sparse_launcher_larger_than_128_mib_is_rejected_without_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / 'oversized-launcher.bin'
    with path.open('wb') as stream:
        stream.truncate(LAUNCHER_MAX + 1)
    before = path.stat()

    def forbidden_open(*args: object, **kwargs: object) -> object:
        raise AssertionError('oversized artifact must be rejected before reading')

    monkeypatch.setattr(Path, 'open', forbidden_open)
    assert_error(path, component(size=LAUNCHER_MAX), 'ARTIFACT_TOO_LARGE')
    after = path.stat()
    assert after.st_size == before.st_size == LAUNCHER_MAX + 1
    assert after.st_mtime_ns == before.st_mtime_ns


def test_core_metadata_above_one_gib_is_rejected_before_path_access() -> None:
    class ForbiddenPath:
        def stat(self) -> object:
            raise AssertionError('oversized metadata must precede stat')

        def open(self, *args: object, **kwargs: object) -> object:
            raise AssertionError('oversized metadata must precede open')

    assert_error(
        ForbiddenPath(),
        component(name='core', size=CORE_MAX + 1),
        'ARTIFACT_TOO_LARGE',
    )
