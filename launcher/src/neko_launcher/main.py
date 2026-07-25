from __future__ import annotations

from pathlib import Path

from neko_launcher.application.controller import ApplicationController
from neko_launcher.infrastructure.config import LauncherConfig
from neko_launcher.infrastructure.event_bus import EventBus
from neko_launcher.infrastructure.process_manager import ProxyProcessManager
from neko_launcher.ui.app_window import AppWindow


def build_window(workspace_root: Path | None = None) -> AppWindow:
    root = workspace_root or Path(__file__).resolve().parents[3]
    config = LauncherConfig.from_environment(root)
    event_bus = EventBus()
    proxy_manager = ProxyProcessManager(config.proxy_core_path)
    controller = ApplicationController(event_bus, proxy_manager)
    logo_path = root / "image_11.png"
    icon_path = root / "icon_app.ico"
    return AppWindow(controller, event_bus, logo_path, icon_path)


def main() -> None:
    build_window().root.mainloop()


if __name__ == "__main__":
    main()
