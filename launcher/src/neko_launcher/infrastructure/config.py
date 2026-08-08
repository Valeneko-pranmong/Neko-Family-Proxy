from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .defaults import (
    PRODUCT_CODE,
    SUPABASE_PUBLISHABLE_KEY,
    SUPABASE_URL,
)


@dataclass(frozen=True)
class LauncherConfig:
    workspace_root: Path
    product_code: str
    game_exe: str
    game_path_store: Path
    proxy_core_path: Path
    supabase_url: str
    supabase_publishable_key: str
    debug_mode: bool
    debug_log_dir: Path

    @classmethod
    def from_environment(cls, workspace_root: Path) -> LauncherConfig:
        """Build runtime settings without a launcher-specific env file.

        The API endpoint and publishable key are public client configuration and
        live in :mod:`defaults`.  Only the operating system's local-data
        location is used to remember per-machine paths.
        """
        local_app_data = Path(
            os.getenv("LOCALAPPDATA", workspace_root / ".local")
        )
        game_path_store = local_app_data / "NEKO FAMILY" / "tweaker.path"
        stored_game_exe = ""
        if game_path_store.is_file():
            try:
                stored_game_exe = game_path_store.read_text(
                    encoding="utf-8"
                ).strip()
            except OSError:
                stored_game_exe = ""
        bundled_proxy = workspace_root / "ProxyCore" / "NekoProxyCore.exe"
        proxy_path = (
            bundled_proxy
            if bundled_proxy.is_file()
            else local_app_data / "NEKO FAMILY" / "ProxyCore" / "NekoProxyCore.exe"
        )
        # Command-line arguments survive the Windows UAC elevation boundary,
        # while ad-hoc environment variables may not. Keep NEKO_DEBUG for
        # source development and use --debug for packaged shortcuts.
        debug_mode = os.getenv("NEKO_DEBUG") == "1" or "--debug" in sys.argv[1:]
        debug_log_dir = local_app_data / "NEKO FAMILY" / "logs"
        return cls(
            workspace_root=workspace_root,
            product_code=PRODUCT_CODE,
            game_exe=stored_game_exe,
            game_path_store=game_path_store,
            proxy_core_path=proxy_path,
            supabase_url=SUPABASE_URL,
            supabase_publishable_key=SUPABASE_PUBLISHABLE_KEY,
            debug_mode=debug_mode,
            debug_log_dir=debug_log_dir,
        )
