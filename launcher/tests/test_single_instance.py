from __future__ import annotations

import sys
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from neko_launcher.bootstrap.single_instance import (
    acquire_instance_mutex,
    release_instance_mutex,
    show_already_running_message,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex behavior")
def test_instance_mutex_lifecycle_acquire_and_release() -> None:
    name = f"Local\\NekoFamilyProxyLauncher-Test-{uuid4()}"
    handle = acquire_instance_mutex(name)
    assert handle is not None
    try:
        # Second acquire while held must return None
        second = acquire_instance_mutex(name)
        assert second is None
    finally:
        release_instance_mutex(handle)

    # After release, acquire must succeed again
    replacement = acquire_instance_mutex(name)
    assert replacement is not None
    release_instance_mutex(replacement)


def test_show_already_running_message_invokes_user32_messagebox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32":
        # Non-win32 no-op check
        show_already_running_message()
        return

    calls: list[tuple[object, ...]] = []
    fake_windll = MagicMock()
    fake_windll.user32.MessageBoxW.side_effect = lambda *args: calls.append(args) or 1
    monkeypatch.setattr("ctypes.windll", fake_windll)

    show_already_running_message()

    assert len(calls) == 1
    hwnd, text, caption, u_type = calls[0]
    assert hwnd is None
    assert "เปิดอยู่แล้ว" in text
    assert caption == "Neko Launcher"
    assert u_type == 0x40
