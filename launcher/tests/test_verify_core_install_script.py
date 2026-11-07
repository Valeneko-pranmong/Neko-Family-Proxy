from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = REPOSITORY_ROOT / "installer" / "scripts" / "verify-core-install.ps1"
EXPECTED_COMMIT = "6ab94bb"
APPROVED_V2RAY_HASH = "a219f435671fb214c0c530084c65e576fdc1404f40b187b5586e869d2a3e4dff"
TEST_V2RAY_BYTES = b"deterministic-v2ray-test-fixture"
TEST_V2RAY_HASH = hashlib.sha256(TEST_V2RAY_BYTES).hexdigest()


def make_core_fixture_with_array_manifest(tmp_path: Path) -> Path:
    core = tmp_path / "ProxyCore"
    core.mkdir(parents=True, exist_ok=True)
    bin_dir = core / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    v2ray_bytes = TEST_V2RAY_BYTES
    (bin_dir / "v2ray-sn.exe").write_bytes(v2ray_bytes)
    (core / "dummy.dll").write_bytes(b"dummy-content")
    (core / "runtime-settings.nkps").write_bytes(b"protected-payload")

    manifest = {
        "source_commit": EXPECTED_COMMIT,
        "files": [
            {
                "path": "bin/v2ray-sn.exe",
                "size": len(v2ray_bytes),
                "sha256": TEST_V2RAY_HASH,
            },
            {
                "path": "dummy.dll",
                "size": len(b"dummy-content"),
                "sha256": hashlib.sha256(b"dummy-content").hexdigest(),
            },
            {
                "path": "runtime-settings.nkps",
                "size": len(b"protected-payload"),
                "sha256": hashlib.sha256(b"protected-payload").hexdigest(),
            },
        ],
    }
    (core / "core-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return core


def make_core_fixture_with_object_manifest(tmp_path: Path) -> Path:
    core = tmp_path / "ProxyCore"
    core.mkdir(parents=True, exist_ok=True)
    bin_dir = core / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    v2ray_bytes = TEST_V2RAY_BYTES
    (bin_dir / "v2ray-sn.exe").write_bytes(v2ray_bytes)
    (core / "dummy.dll").write_bytes(b"dummy-content")
    (core / "runtime-settings.nkps").write_bytes(b"protected-payload")

    manifest = {
        "source_commit": EXPECTED_COMMIT,
        "file_count": 3,
        "files": {
            "bin/v2ray-sn.exe": TEST_V2RAY_HASH,
            "dummy.dll": hashlib.sha256(b"dummy-content").hexdigest(),
            "runtime-settings.nkps": hashlib.sha256(b"protected-payload").hexdigest(),
        },
    }
    (core / "core-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return core


def _run_verify(
    core_dir: Path,
    expected_commit: str = EXPECTED_COMMIT,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script_text = VERIFY_SCRIPT.read_text(encoding="utf-8")
    assert script_text.count(APPROVED_V2RAY_HASH) == 1
    test_script = core_dir.parent / "verify-core-install.test.ps1"
    test_script.write_text(
        script_text.replace(APPROVED_V2RAY_HASH, TEST_V2RAY_HASH),
        encoding="utf-8",
    )
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(test_script),
        "-CoreDir",
        str(core_dir),
        "-ExpectedCommit",
        expected_commit,
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


def test_production_verifier_retains_approved_v2ray_pin() -> None:
    script_text = VERIFY_SCRIPT.read_text(encoding="utf-8")
    assert script_text.count(APPROVED_V2RAY_HASH) == 1
    assert TEST_V2RAY_HASH not in script_text


def test_real_array_manifest_verifies_successfully(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    proc = _run_verify(core)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS: core manifest verified" in proc.stdout


def test_real_object_manifest_verifies_successfully(tmp_path: Path) -> None:
    core = make_core_fixture_with_object_manifest(tmp_path)
    proc = _run_verify(core)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS: core manifest verified" in proc.stdout


def test_object_manifest_missing_file_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_object_manifest(tmp_path)
    (core / "dummy.dll").unlink()
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "MISSING dummy.dll" in proc.stdout


def test_object_manifest_wrong_hash_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_object_manifest(tmp_path)
    (core / "dummy.dll").write_bytes(b"tampered-content")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "HASH dummy.dll" in proc.stdout


def test_object_manifest_file_count_mismatch_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_object_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["file_count"] = 4
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "file_count mismatch" in proc.stdout.lower()


def test_missing_file_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    (core / "dummy.dll").unlink()
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "MISSING dummy.dll" in proc.stdout


def test_wrong_size_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    (core / "dummy.dll").write_bytes(b"dummy-content-longer-bytes")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "SIZE dummy.dll" in proc.stdout


def test_wrong_sha256_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    # same size (13 bytes), different content
    (core / "dummy.dll").write_bytes(b"dummy-mod-123")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "HASH dummy.dll" in proc.stdout


def test_wrong_source_commit_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    proc = _run_verify(core, expected_commit="0000000")
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "FAIL: source_commit mismatch" in proc.stdout


def test_duplicate_path_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {
            "path": "dummy.dll",
            "size": len(b"dummy-content"),
            "sha256": hashlib.sha256(b"dummy-content").hexdigest(),
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "duplicate path" in proc.stdout.lower()


def test_unsafe_path_traversal_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {
            "path": "../evil.dll",
            "size": 10,
            "sha256": "a" * 64,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "unsafe" in proc.stdout.lower() or "escape" in proc.stdout.lower()


def test_unsafe_path_absolute_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {
            "path": "C:\\evil.dll",
            "size": 10,
            "sha256": "a" * 64,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "unsafe" in proc.stdout.lower() or "escape" in proc.stdout.lower()


def test_object_manifest_invalid_hash_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {"dummy.dll": "hash"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "invalid sha256" in proc.stdout.lower()


def test_malformed_non_array_files_string_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = "not-an-array"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "non-empty array" in proc.stdout.lower()


def test_empty_files_array_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode in (5, 6), proc.stdout + proc.stderr
    assert "zero files" in proc.stdout.lower() or "non-empty array" in proc.stdout.lower()


def test_malformed_entry_missing_field_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {
            "path": "dummy.dll",
            "size": len(b"dummy-content"),
            # missing sha256
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr


def test_malformed_entry_extra_field_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][1]["unexpected_field"] = "bad"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr


def test_v2ray_not_declared_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [f for f in manifest["files"] if f["path"] != "bin/v2ray-sn.exe"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode in (6, 7), proc.stdout + proc.stderr
    assert "v2ray-sn.exe not declared" in proc.stdout or "declared files bad" in proc.stdout


def test_v2ray_pin_disk_mismatch_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    # Tamper with v2ray-sn.exe on disk
    (core / "bin" / "v2ray-sn.exe").write_bytes(b"tampered-v2ray-bytes")
    # Update manifest to match tampered size/hash so file check passes, but v2ray pin check fails
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for f in manifest["files"]:
        if f["path"] == "bin/v2ray-sn.exe":
            f["size"] = len(b"tampered-v2ray-bytes")
            f["sha256"] = hashlib.sha256(b"tampered-v2ray-bytes").hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 7, proc.stdout + proc.stderr
    assert "v2ray-sn.exe hash mismatch" in proc.stdout


def test_v2ray_pin_manifest_mismatch_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for f in manifest["files"]:
        if f["path"] == "bin/v2ray-sn.exe":
            f["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode in (6, 7), proc.stdout + proc.stderr


def test_missing_runtime_settings_nkps_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    (core / "runtime-settings.nkps").unlink()
    proc = _run_verify(core)
    assert proc.returncode == 8, proc.stdout + proc.stderr
    assert "FAIL: runtime-settings.nkps missing" in proc.stdout


def test_plaintext_runtime_settings_key_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    (core / "runtime-settings.key").write_bytes(b"plaintext-key")
    proc = _run_verify(core)
    assert proc.returncode == 8, proc.stdout + proc.stderr
    assert "FAIL: plaintext runtime-settings.key present" in proc.stdout


def test_prohibited_plaintext_settings_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    (core / "appsettings.json").write_text("{}", encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 9, proc.stdout + proc.stderr
    assert "FAIL: plaintext settings/key-like files present" in proc.stdout


@pytest.mark.parametrize("object_manifest", [False, True])
@pytest.mark.parametrize("contents", [b"", b"V2Ray output\r\n\x00\xff"])
def test_archives_only_known_runtime_log_and_preserves_bytes(
    tmp_path: Path, object_manifest: bool, contents: bytes
) -> None:
    make_fixture = (
        make_core_fixture_with_object_manifest
        if object_manifest
        else make_core_fixture_with_array_manifest
    )
    core = make_fixture(tmp_path)
    log = core / "logging" / "V2Ray (SagerNet).log"
    log.parent.mkdir()
    log.write_bytes(contents)
    archive = tmp_path / "พื้นที่ O'Brien" / "core-install-archive"
    archive.mkdir(parents=True)
    previous = archive / "previous.log"
    previous.write_bytes(b"previous evidence")
    args = ["-RuntimeLogArchiveDir", str(archive)]

    proc = _run_verify(core, extra_args=args)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ARCHIVED:" in proc.stdout
    assert not log.exists()
    archived = [p for p in archive.iterdir() if p != previous]
    assert len(archived) == 1
    assert archived[0].read_bytes() == contents
    assert previous.read_bytes() == b"previous evidence"
    assert _run_verify(core).returncode == 0

    log.write_bytes(b"next run")
    proc = _run_verify(core, extra_args=args)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(list(archive.iterdir())) == 3
    assert archived[0].read_bytes() == contents


def test_runtime_log_stays_strict_without_archive_opt_in(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    log = core / "logging" / "V2Ray (SagerNet).log"
    log.parent.mkdir()
    log.write_bytes(b"runtime evidence")

    proc = _run_verify(core)

    assert proc.returncode == 10, proc.stdout + proc.stderr
    assert log.read_bytes() == b"runtime evidence"


@pytest.mark.parametrize(
    "extra_name, expected_exit",
    [
        ("bin/extra.dll", 10),
        ("logging/other.log", 10),
        ("logging/nested/V2Ray (SagerNet).log", 10),
        ("V2Ray (SagerNet).log", 10),
        ("logging/appsettings.json", 9),
        ("logging/private.pem", 9),
    ],
)
def test_unknown_files_prevent_any_runtime_log_archival(
    tmp_path: Path, extra_name: str, expected_exit: int
) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    log = core / "logging" / "V2Ray (SagerNet).log"
    log.parent.mkdir()
    log.write_bytes(b"runtime evidence")
    extra = core / extra_name
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(b"unknown bytes")
    archive = tmp_path / "archive"

    proc = _run_verify(core, extra_args=["-RuntimeLogArchiveDir", str(archive)])

    assert proc.returncode == expected_exit, proc.stdout + proc.stderr
    assert not archive.exists()
    assert log.read_bytes() == b"runtime evidence"
    assert extra.read_bytes() == b"unknown bytes"


@pytest.mark.parametrize("archive_relative", [".", "logging/archive", "nested/.."])
def test_runtime_log_archive_inside_core_is_refused(
    tmp_path: Path, archive_relative: str
) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    log = core / "logging" / "V2Ray (SagerNet).log"
    log.parent.mkdir()
    log.write_bytes(b"runtime evidence")

    proc = _run_verify(
        core, extra_args=["-RuntimeLogArchiveDir", str(core / archive_relative)]
    )

    assert proc.returncode == 10, proc.stdout + proc.stderr
    assert log.read_bytes() == b"runtime evidence"


def test_hash_failure_does_not_archive_runtime_log(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    log = core / "logging" / "V2Ray (SagerNet).log"
    log.parent.mkdir()
    log.write_bytes(b"runtime evidence")
    (core / "dummy.dll").write_bytes(b"changed bytes")
    archive = tmp_path / "archive"

    proc = _run_verify(core, extra_args=["-RuntimeLogArchiveDir", str(archive)])

    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert not archive.exists()
    assert log.read_bytes() == b"runtime evidence"


def test_archive_path_as_file_preserves_runtime_log(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    log = core / "logging" / "V2Ray (SagerNet).log"
    log.parent.mkdir()
    log.write_bytes(b"runtime evidence")
    archive = tmp_path / "archive"
    archive.write_bytes(b"existing file")

    proc = _run_verify(core, extra_args=["-RuntimeLogArchiveDir", str(archive)])

    assert proc.returncode == 10, proc.stdout + proc.stderr
    assert log.read_bytes() == b"runtime evidence"
    assert archive.read_bytes() == b"existing file"


def test_archive_opt_in_without_runtime_log_has_no_side_effects(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    archive = tmp_path / "archive"

    proc = _run_verify(core, extra_args=["-RuntimeLogArchiveDir", str(archive)])

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not archive.exists()


@pytest.mark.parametrize("junction_location", ["source", "archive"])
def test_runtime_log_archival_refuses_junctions(
    tmp_path: Path, junction_location: str
) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    archive = tmp_path / "archive"
    if junction_location == "source":
        target = tmp_path / "external-logging"
        target.mkdir()
        junction = core / "logging"
        log = target / "V2Ray (SagerNet).log"
    else:
        target = core / "archive-target"
        target.mkdir()
        junction = archive
        log = core / "logging" / "V2Ray (SagerNet).log"
        log.parent.mkdir()
    log.write_bytes(b"runtime evidence")
    mklink = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
    )
    assert mklink.returncode == 0, mklink.stdout + mklink.stderr

    proc = _run_verify(core, extra_args=["-RuntimeLogArchiveDir", str(archive)])

    assert proc.returncode == 10, proc.stdout + proc.stderr
    assert "reparse point" in proc.stdout
    assert log.read_bytes() == b"runtime evidence"


def test_locked_runtime_log_is_preserved_when_archival_fails(tmp_path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    core = make_core_fixture_with_array_manifest(tmp_path)
    log = core / "logging" / "V2Ray (SagerNet).log"
    log.parent.mkdir()
    log.write_bytes(b"runtime evidence")
    archive = tmp_path / "archive"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateFileW(str(log), 0x80000000, 0, None, 3, 0x80, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    try:
        proc = _run_verify(core, extra_args=["-RuntimeLogArchiveDir", str(archive)])
    finally:
        kernel32.CloseHandle(handle)

    assert proc.returncode == 10, proc.stdout + proc.stderr
    assert log.read_bytes() == b"runtime evidence"
    assert list(archive.iterdir()) == []


def test_installer_requests_runtime_log_archival_outside_core() -> None:
    source = (REPOSITORY_ROOT / "installer" / "beta.iss").read_text(encoding="utf-8")
    assert "RuntimeLogArchiveDir" in source
    assert "AppDir + '\\logging\\core-install-archive'" in source
