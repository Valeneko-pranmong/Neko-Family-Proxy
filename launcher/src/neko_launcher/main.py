from __future__ import annotations

import sys
from pathlib import Path

from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.services import LauncherService
from neko_launcher.infrastructure.config import LauncherConfig
from neko_launcher.infrastructure.event_bus import EventBus
from neko_launcher.infrastructure.game_process_manager import GameProcessManager
from neko_launcher.infrastructure.installation import LocalInstallationIdentity
from neko_launcher.infrastructure.process_manager import ProxyProcessManager
from neko_launcher.infrastructure.secure_store import KeyringSecureStore
from neko_launcher.infrastructure.supabase_gateway import SupabaseGateway
from neko_launcher.infrastructure.unavailable_gateway import (
    UnavailableSupabaseGateway,
)
from neko_launcher.ui.app_window import AppWindow


def application_root() -> Path:
    """Return the source checkout or PyInstaller extraction directory."""
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def build_window(workspace_root: Path | None = None) -> AppWindow:
    root = workspace_root or application_root()
    config = LauncherConfig.from_environment(root)
    event_bus = EventBus()
    proxy_manager = ProxyProcessManager(config.proxy_core_path)
    game_manager = GameProcessManager()
    controller = ApplicationController(event_bus, proxy_manager, game_manager)
    secure_store = KeyringSecureStore()
    installation = LocalInstallationIdentity(secure_store)
    if config.supabase_url and config.supabase_publishable_key:
        gateway = SupabaseGateway(
            config.supabase_url,
            config.supabase_publishable_key,
            secure_store,
        )
    else:
        gateway = UnavailableSupabaseGateway()
    service = LauncherService(
        controller,
        gateway,
        gateway,
        installation,
        config.product_code,
    )
    logo_path = root / "image_11.png"
    icon_path = root / "icon_app.ico"
    return AppWindow(
        controller,
        service,
        event_bus,
        logo_path,
        icon_path,
        game_default_path=config.game_exe,
        game_path_store=config.game_path_store,
    )


def main() -> None:
    build_window().root.mainloop()


if __name__ == "__main__":
    main()
