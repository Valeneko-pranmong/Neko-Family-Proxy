from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LauncherConfig:
    workspace_root: Path
    product_code: str
    game_exe: str
    proxy_core_path: Path
    supabase_url: str
    supabase_publishable_key: str

    @classmethod
    def from_environment(cls, workspace_root: Path) -> LauncherConfig:
        proxy_override = os.getenv("NEKO_PROXY_CORE_PATH")
        proxy_path = (
            Path(proxy_override)
            if proxy_override
            else workspace_root / "ProxyCore" / "ProxyCore.exe"
        )
        return cls(
            workspace_root=workspace_root,
            product_code=os.getenv("NEKO_PRODUCT_CODE", "neko-family-proxy"),
            game_exe=os.getenv("NEKO_GAME_EXE", "pso2.exe"),
            proxy_core_path=proxy_path,
            supabase_url=os.getenv("NEKO_SUPABASE_URL", ""),
            supabase_publishable_key=os.getenv("NEKO_SUPABASE_PUBLISHABLE_KEY", ""),
        )
