from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

from neko_launcher.main import (
    _acquire_instance_mutex,
    _report_startup_error,
    _release_instance_mutex,
)
from neko_launcher.infrastructure.unavailable_gateway import (
    AuthorizationPendingProxyGateway,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex behavior")
def test_instance_mutex_rejects_a_second_launcher_process() -> None:
    name = f"Local\\NekoFamilyProxyLauncher-Test-{uuid4()}"
    first = _acquire_instance_mutex(name)
    assert first is not None
    try:
        assert _acquire_instance_mutex(name) is None
    finally:
        _release_instance_mutex(first)

    replacement = _acquire_instance_mutex(name)
    assert replacement is not None
    _release_instance_mutex(replacement)


def test_pending_authorization_contract_fails_closed_without_starting_core() -> None:
    gateway = AuthorizationPendingProxyGateway()

    with pytest.raises(RuntimeError, match="authorization integration is unavailable"):
        gateway.start()

    gateway.stop()


def test_startup_error_report_does_not_persist_or_display_exception_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sentinel = "sentinel-startup-token"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    messages: list[str] = []
    monkeypatch.setattr(
        "neko_launcher.main._show_startup_error_message",
        lambda message: messages.append(message),
    )

    try:
        raise RuntimeError(sentinel)
    except RuntimeError as exc:
        _report_startup_error(exc)

    log_text = (tmp_path / "NEKO FAMILY" / "launcher-error.log").read_text(
        encoding="utf-8"
    )
    assert sentinel not in log_text
    assert "Traceback" not in log_text
    assert messages and sentinel not in messages[0]
