from queue import SimpleQueue
from typing import Any

from neko_launcher.ui.platform.system_tray import drain_tray_actions


class FakeTrayRoot:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.scheduled: list[Any] = []

    def winfo_exists(self) -> bool:
        self.events.append("winfo_exists")
        return True

    def deiconify(self) -> None:
        self.events.append("deiconify")

    def attributes(self, name: str, value: bool) -> None:
        self.events.append(f"attributes:{name}:{value}")

    def lift(self) -> None:
        self.events.append("lift")

    def after(self, _delay: int, callback: Any) -> None:
        self.scheduled.append(callback)


def test_tray_restore_is_marshaled_to_the_ui_thread() -> None:
    """Test that restore action is marshaled through queue to the UI thread."""
    action_queue: SimpleQueue[str] = SimpleQueue()
    root = FakeTrayRoot()

    # Simulate a tray manager putting a restore action
    action_queue.put("restore")

    # Drain should process on the main thread
    drain_tray_actions(action_queue, root, lambda: None)  # type: ignore[arg-type]

    assert root.events == [
        "winfo_exists",
        "deiconify",
        "attributes:-topmost:True",
        "lift",
        "winfo_exists",
    ]


def test_tray_exit_is_marshaled_to_the_ui_thread() -> None:
    """Test that close action is marshaled through queue to the UI thread."""
    action_queue: SimpleQueue[str] = SimpleQueue()
    close_calls: list[bool] = []

    action_queue.put("close")

    # Use a fake root that won't be checked since close returns early
    drain_tray_actions(action_queue, FakeTrayRoot(), lambda: close_calls.append(True))  # type: ignore[arg-type]

    assert close_calls == [True]
