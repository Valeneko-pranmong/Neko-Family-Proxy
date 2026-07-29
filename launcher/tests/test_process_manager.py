from typing import Any

import neko_launcher.infrastructure.process_manager as process_module
from neko_launcher.infrastructure.process_manager import ProxyProcessManager


class FakeProcess:
    pid = 5252

    def poll(self) -> None:
        return None

    def wait(self, timeout: float) -> None:
        return None


def test_stop_terminates_only_the_owned_proxy_process_tree(
    monkeypatch: Any,
    tmp_path,
) -> None:
    taskkill_calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> None:
        taskkill_calls.append(command)

    monkeypatch.setattr(process_module.os, "name", "nt")
    monkeypatch.setattr(process_module.subprocess, "run", fake_run)
    manager = ProxyProcessManager(tmp_path / "ProxyCore.exe")
    manager._process = FakeProcess()  # type: ignore[assignment]

    manager.stop()

    assert taskkill_calls == [["taskkill", "/PID", "5252", "/T", "/F"]]
