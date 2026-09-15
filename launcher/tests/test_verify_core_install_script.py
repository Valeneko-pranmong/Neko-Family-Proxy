from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = REPOSITORY_ROOT / "installer" / "scripts" / "verify-core-install.ps1"
EXPECTED_COMMIT = "6ab94bb"
APPROVED_V2RAY_HASH = "a219f435671fb214c0c530084c65e576fdc1404f40b187b5586e869d2a3e4dff"


def _get_approved_v2ray_bytes() -> bytes:
    candidates = [
        Path(r"E:\Github\NekoProxyCore\Storage\v2ray-sn.exe"),
        Path(
            r"E:\Github\artifacts\main-auto-release\34735305323-f4afa51878ccea590c33f758c9da70eb3ddbd43b\5.1.2\payload\CoreBundle\bin\v2ray-sn.exe"
        ),
        Path(r"E:\Github\archive\release-history\candidate-5.1.0-stable\core\bin\v2ray-sn.exe"),
    ]
    for c in candidates:
        if c.is_file():
            content = c.read_bytes()
            if hashlib.sha256(content).hexdigest().lower() == APPROVED_V2RAY_HASH:
                return content
    raise RuntimeError("Approved v2ray-sn.exe binary not found on test environment")


def make_core_fixture_with_array_manifest(tmp_path: Path) -> Path:
    core = tmp_path / "ProxyCore"
    core.mkdir(parents=True, exist_ok=True)
    bin_dir = core / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    v2ray_bytes = _get_approved_v2ray_bytes()
    (bin_dir / "v2ray-sn.exe").write_bytes(v2ray_bytes)
    (core / "dummy.dll").write_bytes(b"dummy-content")
    (core / "runtime-settings.nkps").write_bytes(b"protected-payload")

    manifest = {
        "source_commit": EXPECTED_COMMIT,
        "files": [
            {
                "path": "bin/v2ray-sn.exe",
                "size": len(v2ray_bytes),
                "sha256": APPROVED_V2RAY_HASH,
            },
            {
                "path": "dummy.dll",
                "size": len(b"dummy-content"),
                "sha256": hashlib.sha256(b"dummy-content").hexdigest(),
            },
        ],
    }
    (core / "core-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return core


def _run_verify(
    core_dir: Path,
    expected_commit: str = EXPECTED_COMMIT,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(VERIFY_SCRIPT),
        "-CoreDir",
        str(core_dir),
        "-ExpectedCommit",
        expected_commit,
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


def test_real_array_manifest_verifies_successfully(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    proc = _run_verify(core)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS: core manifest verified" in proc.stdout


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


def test_malformed_non_array_files_object_fails(tmp_path: Path) -> None:
    core = make_core_fixture_with_array_manifest(tmp_path)
    manifest_path = core / "core-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {"dummy.dll": "hash"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_verify(core)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "non-empty array" in proc.stdout.lower()


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
