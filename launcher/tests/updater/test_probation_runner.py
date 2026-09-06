import json
from pathlib import Path
import shutil
from unittest.mock import MagicMock

from neko_launcher.updater.probation_runner import run_probation_self_test

CANONICAL_A43_ROOT = Path("E:/Github/worktrees/NekoProxyCore-live-update/TestResults/task12/a43-core")


def test_probation_fails_when_core_missing(tmp_path: Path) -> None:
    gen_dir = tmp_path / "g-001"
    gen_dir.mkdir()
    (gen_dir / "NekoLauncher.exe").write_bytes(b"dummy launcher")
    # ProxyCore is missing
    res = run_probation_self_test(gen_dir, skip_tk=True)
    assert not res.passed
    assert res.error_code == "CORE_INVENTORY_INVALID"


def test_probation_fails_on_legacy_a43_core_without_preflight(tmp_path: Path) -> None:
    gen_dir = tmp_path / "g-legacy"
    gen_dir.mkdir()
    (gen_dir / "NekoLauncher.exe").write_bytes(b"dummy launcher")
    core_dir = gen_dir / "ProxyCore"
    core_dir.mkdir()
    shutil.copytree(CANONICAL_A43_ROOT, core_dir, dirs_exist_ok=True)

    # Legacy a43 Core does not support --update-preflight and exits code 2
    res = run_probation_self_test(gen_dir, skip_tk=True)
    assert not res.passed
    assert res.error_code == "SELFTEST_FAILED"
    assert "exited with code 2" in (res.reason or "")


def test_probation_passes_when_preflight_returns_pass(tmp_path: Path, monkeypatch) -> None:
    gen_dir = tmp_path / "g-002"
    gen_dir.mkdir()
    (gen_dir / "NekoLauncher.exe").write_bytes(b"dummy launcher")
    core_dir = gen_dir / "ProxyCore"
    core_dir.mkdir()
    shutil.copytree(CANONICAL_A43_ROOT, core_dir, dirs_exist_ok=True)

    # Mock subprocess.Popen for Core preflight to return PASS
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (json.dumps({"protocol_version": 1, "result": "PASS", "code": None}), "")
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)

    res = run_probation_self_test(gen_dir, skip_tk=True)
    assert res.passed
    assert res.error_code is None
