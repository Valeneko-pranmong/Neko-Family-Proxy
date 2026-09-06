import ctypes
from pathlib import Path
import sys

import pytest

from neko_launcher.updater.generation_publisher import GenerationPublisher


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 publisher requires Windows")
def test_atomic_generation_publication(tmp_path: Path) -> None:
    pub = GenerationPublisher(tmp_path)
    tx_id = "a" * 32
    handle, identity, stage_dir = pub.create_staging_area(tx_id)
    try:
        assert stage_dir.exists()
        assert len(identity.volume_serial) == 16
        assert len(identity.file_id) == 32

        gen_stage = stage_dir / "generation"
        gen_stage.mkdir()
        (gen_stage / "test.txt").write_text("hello payload")

        target_gen_id = "g-00000000000000000002-abcd"
        final_path = pub.publish_generation(gen_stage, target_gen_id)
        assert final_path.exists()
        assert (final_path / "test.txt").read_text() == "hello payload"
        assert not gen_stage.exists()
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
