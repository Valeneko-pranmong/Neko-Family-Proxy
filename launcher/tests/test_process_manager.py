from typing import Any

import pytest

import neko_launcher.infrastructure.process_manager as process_module
from neko_launcher.infrastructure.process_manager import (
    ProxyProcessError,
    ProxyProcessManager,
)


class FakeProcess:
    pid = 5252

    def poll(self) -> None:
        return None


def test_start_opens_proxycore_visibly_without_hidden_options(
    monkeypatch: Any,
    tmp_path,
) -> None:
    executable = tmp_path / "ProxyCore.exe"
    executable.touch()
    popen_calls: list[tuple[list[str], dict[str, Any]]] = []
    process = FakeProcess()

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        popen_calls.append((command, kwargs))
        return process

    monkeypatch.setattr(process_module.subprocess, "Popen", fake_popen)
    manager = ProxyProcessManager(executable)

    manager.start()

    assert popen_calls == [
        (
            [str(executable)],
            {"cwd": str(executable.parent)},
        )
    ]


def test_start_does_not_open_a_second_owned_process(
    monkeypatch: Any,
    tmp_path,
) -> None:
    executable = tmp_path / "ProxyCore.exe"
    executable.touch()
    popen_calls: list[bool] = []
    manager = ProxyProcessManager(executable)
    manager._process = FakeProcess()  # type: ignore[assignment]
    monkeypatch.setattr(
        process_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: popen_calls.append(True),
    )

    manager.start()

    assert popen_calls == []


def test_stop_releases_ownership_without_killing_visible_proxycore(tmp_path) -> None:
    manager = ProxyProcessManager(tmp_path / "ProxyCore.exe")
    manager._process = FakeProcess()  # type: ignore[assignment]

    manager.stop()

    assert manager._process is None


def test_missing_proxycore_is_reported(tmp_path) -> None:
    manager = ProxyProcessManager(tmp_path / "missing" / "ProxyCore.exe")

    with pytest.raises(ProxyProcessError, match="ProxyCore not found"):
        manager.start()
