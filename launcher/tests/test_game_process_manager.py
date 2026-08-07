from pathlib import Path
from typing import Any

import neko_launcher.infrastructure.process.game_process_manager as process_module
from neko_launcher.infrastructure.process.game_process_manager import GameProcessManager


class FakeProcess:
    pid = 4242

    def poll(self) -> None:
        return None

    def wait(self, timeout: float) -> None:
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


def test_stop_terminates_only_the_owned_tweaker_process_tree(
    monkeypatch: Any,
) -> None:
    taskkill_calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> None:
        taskkill_calls.append(command)

    monkeypatch.setattr(process_module.os, "name", "nt")
    monkeypatch.setattr(process_module.subprocess, "run", fake_run)
    manager = GameProcessManager()
    manager._process = FakeProcess()  # type: ignore[assignment]

    manager.stop()

    assert taskkill_calls == [["taskkill", "/PID", "4242", "/T", "/F"]]
