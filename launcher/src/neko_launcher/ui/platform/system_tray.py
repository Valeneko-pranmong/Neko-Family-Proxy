from __future__ import annotations

import threading
from queue import Empty, SimpleQueue
from typing import Any, Callable

import tkinter as tk


class SystemTrayManager:
    def __init__(self, icon_path: str, action_queue: SimpleQueue) -> None:
        self._icon_path = icon_path
        self._action_queue = action_queue
        self._tray_icon = None

    def setup(self) -> None:
        import pystray
        from PIL import Image

        try:
            image = Image.open(self._icon_path)
        except Exception:
            image = Image.new("RGB", (64, 64), color=(255, 255, 255))

        menu = pystray.Menu(
            pystray.MenuItem("Show Launcher", self._on_restore, default=True),
            pystray.MenuItem("Exit", self._on_close),
        )
        self._tray_icon = pystray.Icon("NekoLauncher", image, "Neko Family Proxy", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def stop(self) -> None:
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass

    def _on_restore(self, icon: Any, item: Any) -> None:
        self._action_queue.put("restore")

    def _on_close(self, icon: Any, item: Any) -> None:
        self._action_queue.put("close")


def drain_tray_actions(
    action_queue: SimpleQueue,
    root: tk.Tk | tk.Toplevel,
    on_close: Callable[[], None],
) -> None:
    while True:
        try:
            action = action_queue.get_nowait()
        except Empty:
            break
            
        if action == "close":
            on_close()
            return
            
        if action == "restore" and root.winfo_exists():
            root.deiconify()
            root.attributes("-topmost", True)
            root.lift()
            root.after(100, lambda: root.attributes("-topmost", False))
            
    if root.winfo_exists():
        root.after(100, lambda: drain_tray_actions(action_queue, root, on_close))
