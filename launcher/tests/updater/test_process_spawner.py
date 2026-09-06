from pathlib import Path
import sys

import pytest

from neko_launcher.updater.process_spawner import spawn_managed_child


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 job spawner requires Windows")
def test_spawn_managed_child_lifecycle(tmp_path: Path) -> None:
    # Use current python executable as test child
    py_exe = Path(sys.executable)
    dummy_lease = 0  # Dummy handle
    args = ["-c", "import time; time.sleep(10)"]

    child = spawn_managed_child(py_exe, args, dummy_lease)
    try:
        assert child.pid > 0
        assert child.process_handle != 0
        assert child.job_handle != 0
    finally:
        child.terminate()
