from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class LauncherConfig:
    workspace_root: Path
    product_code: str
    game_exe: str
    game_path_store: Path
    proxy_core_path: Path
    supabase_url: str
    supabase_publishable_key: str

    @classmethod
    def from_environment(cls, workspace_root: Path) -> LauncherConfig:
        local_app_data = Path(
            os.getenv("LOCALAPPDATA", workspace_root / ".local")
        )
        env_files = [
            local_app_data / "NEKO FAMILY" / "launcher.env",
        ]
        if getattr(sys, "frozen", False):
            env_files.append(Path(sys.executable).resolve().parent / "launcher.env")
        env_files.extend(
            (
                workspace_root / "launcher" / ".env.local",
                workspace_root / ".env.local",
            )
        )
        for env_file in env_files:
            load_dotenv(env_file, override=False)
        game_path_store = local_app_data / "NEKO FAMILY" / "tweaker.path"
        stored_game_exe = ""
        if game_path_store.is_file():
            try:
                stored_game_exe = game_path_store.read_text(
                    encoding="utf-8"
                ).strip()
            except OSError:
                stored_game_exe = ""
        proxy_override = os.getenv("NEKO_PROXY_CORE_PATH")
        proxy_path = (
            Path(proxy_override)
            if proxy_override
            else (
                workspace_root / "ProxyCore" / "ProxyCore.exe"
                if getattr(sys, "frozen", False)
                and (workspace_root / "ProxyCore" / "ProxyCore.exe").is_file()
                else local_app_data
                / "NEKO FAMILY"
                / "ProxyCore"
                / "ProxyCore.exe"
            )
        )
        return cls(
            workspace_root=workspace_root,
            product_code=os.getenv("NEKO_PRODUCT_CODE", "neko-family-proxy"),
            game_exe=os.getenv("NEKO_GAME_EXE") or stored_game_exe or "Tweaker.exe",
            game_path_store=game_path_store,
            proxy_core_path=proxy_path,
            supabase_url=os.getenv("NEKO_SUPABASE_URL", ""),
            supabase_publishable_key=os.getenv("NEKO_SUPABASE_PUBLISHABLE_KEY", ""),
        )
