from pathlib import Path
from typing import Any

import neko_launcher.infrastructure.game_process_manager as process_module
from neko_launcher.infrastructure.game_process_manager import GameProcessManager


class FakeProcess:
    def poll(self) -> None:
        return None


def test_start_launches_selected_executable_in_its_own_directory(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "folder with spaces" / "Tweaker.exe"
    executable.parent.mkdir()
    executable.touch()
    popen_calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        popen_calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(process_module.subprocess, "Popen", fake_popen)

    manager = GameProcessManager()
    manager.start(executable)

    assert popen_calls[0][0] == [str(executable)]
    assert popen_calls[0][1]["cwd"] == str(executable.parent)
