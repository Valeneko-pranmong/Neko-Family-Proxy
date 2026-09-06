import shutil
from pathlib import Path

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


def test_probation_passes_with_valid_core(tmp_path: Path) -> None:
    gen_dir = tmp_path / "g-002"
    gen_dir.mkdir()
    (gen_dir / "NekoLauncher.exe").write_bytes(b"dummy launcher")
    # Copy a minimal valid core dummy or point to fixture
    core_dir = gen_dir / "ProxyCore"
    core_dir.mkdir()
    shutil.copytree(CANONICAL_A43_ROOT, core_dir, dirs_exist_ok=True)

    res = run_probation_self_test(gen_dir, skip_tk=True)
    assert res.passed
    assert res.error_code is None
