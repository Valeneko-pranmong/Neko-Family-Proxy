from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

import pytest


EXPECTED_VERSION = "5.1.0a3"
CREATE_NO_WINDOW = 0x08000000
TH32CS_SNAPPROCESS = 0x00000002
WM_CLOSE = 0x0010


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _process_parents() -> dict[int, int]:
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    assert snapshot != wintypes.HANDLE(-1).value, "CreateToolhelp32Snapshot failed"
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    parents: dict[int, int] = {}
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


def _owned_pids(root_pid: int) -> set[int]:
    parents = _process_parents()
    owned = {root_pid}
    changed = True
    while changed:
        before = len(owned)
        owned.update(pid for pid, parent in parents.items() if parent in owned)
        changed = len(owned) != before
    return owned


def _visible_windows(owned: set[int]) -> list[tuple[int, int, str, str]]:
    user32 = ctypes.windll.user32
    found: list[tuple[int, int, str, str]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd: int, _lparam: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in owned and user32.IsWindowVisible(hwnd):
            title_length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(title_length + 1)
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            user32.GetClassNameW(hwnd, class_name, len(class_name))
            found.append((int(hwnd), int(pid.value), title.value, class_name.value))
        return True

    assert user32.EnumWindows(visit, 0), "EnumWindows failed"
    return found


def _wait_for_window(root_pid: int, timeout: float = 30.0) -> tuple[set[int], list[tuple[int, int, str, str]]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        owned = _owned_pids(root_pid)
        windows = _visible_windows(owned)
        if any("NEKO FAMILY PROXY" in title.upper() for _, _, title, _ in windows):
            return owned, windows
        time.sleep(0.2)
    pytest.fail("owned launcher process tree did not expose a visible NEKO FAMILY PROXY window")


def _candidate_version_evidence(candidate_dir: Path, launcher: Path) -> None:
    record_path = candidate_dir / "build-record.json"
    assert record_path.is_file(), (
        "UI title has no version; build-record.json is required to bind the selected candidate "
        "launcher hash to canonical source version evidence"
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record.get("launcher_sha256") == _sha256(launcher)

    # There is no supported packaged version diagnostic and the main title omits version.
    # Keep source identity canonical while build-record.json binds it to this exact EXE.
    launcher_root = Path(__file__).resolve().parents[2]
    pyproject = (launcher_root / "pyproject.toml").read_text(encoding="utf-8")
    package_init = (launcher_root / "src" / "neko_launcher" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert f'version = "{EXPECTED_VERSION}"' in pyproject
    assert f'__version__ = "{EXPECTED_VERSION}"' in package_init


def test_packaged_candidate_a3_lifecycle(candidate_dir: Path, tmp_path: Path) -> None:
    launcher = candidate_dir / "NekoLauncher.exe"
    updater = candidate_dir / "NekoUpdater.exe"
    updater_check = subprocess.run(
        [updater, "--self-check"], capture_output=True, text=True, timeout=15
    )
    assert updater_check.returncode == 0, updater_check.stderr or updater_check.stdout
    _candidate_version_evidence(candidate_dir, launcher)

    scratch = tmp_path / "isolated-profile"
    scratch.mkdir()
    before_mei = set(scratch.glob("_MEI*"))
    env = os.environ.copy()
    env.update({"TEMP": str(scratch), "TMP": str(scratch), "LOCALAPPDATA": str(scratch)})
    process = subprocess.Popen([launcher], env=env, cwd=candidate_dir)
    owned: set[int] = {process.pid}
    try:
        owned, windows = _wait_for_window(process.pid)
        assert any("NEKO FAMILY PROXY" in title.upper() for _, _, title, _ in windows)
        exception_dialogs = [
            title
            for _, _, title, class_name in windows
            if class_name == "#32770" and any(word in title.lower() for word in ("error", "exception", "traceback"))
        ]
        assert not exception_dialogs, f"unhandled exception dialog(s): {exception_dialogs}"
        for hwnd, _, title, _ in windows:
            if "NEKO FAMILY PROXY" in title.upper():
                ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        assert process.wait(timeout=15) == 0, "launcher did not shut down normally with exit code 0"
    finally:
        if process.poll() is None:
            # Cleanup is restricted to the exact spawned handle; never kill by image name.
            process.terminate()
            process.wait(timeout=5)

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and (_owned_pids(process.pid) - {process.pid}):
        time.sleep(0.2)
    assert not (_owned_pids(process.pid) - {process.pid}), "owned launcher child remained after shutdown"
    assert not list(scratch.rglob("launcher-error.log")), "launcher-error.log was produced"
    after_mei = set(scratch.glob("_MEI*"))
    assert after_mei == before_mei, f"candidate-created _MEI directories were not cleaned: {after_mei - before_mei}"
