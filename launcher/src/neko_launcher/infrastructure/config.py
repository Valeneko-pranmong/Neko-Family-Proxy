from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .defaults import (
    ACCOUNT_RECOVERY_API_URL,
    IDENTITY_BASE_URL,
    PRODUCT_CODE,
    PROXY_STATUS_API_URL,
    SUPABASE_PUBLISHABLE_KEY,
    SUPABASE_URL,
)


class ProgramPreferences:
    """Small, non-sensitive Launcher UI preferences stored in Local AppData."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def always_on_top(self) -> bool:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        if not isinstance(value, dict):
            return False
        return value.get("always_on_top") is True

    @property
    def hide_to_tray(self) -> bool:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        if not isinstance(value, dict):
            return False
        return value.get("hide_to_tray") is True

    def set_always_on_top(self, enabled: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except (OSError, ValueError, TypeError):
            current = {}
        current["always_on_top"] = bool(enabled)
        self.path.write_text(
            json.dumps(current, ensure_ascii=False),
            encoding="utf-8",
        )

    def set_hide_to_tray(self, enabled: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except (OSError, ValueError, TypeError):
            current = {}
        current["hide_to_tray"] = bool(enabled)
        self.path.write_text(
            json.dumps(current, ensure_ascii=False),
            encoding="utf-8",
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
    account_recovery_api_url: str
    proxy_status_api_url: str
    identity_base_url: str
    web_auth_bridge_url: str
    proxy_api_url: str
    proxy_api_enabled: bool
    web_auth_enabled: bool
    web_auth_only: bool
    launcher_schema: str
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
        proxy_path = local_app_data / "NEKO FAMILY" / "ProxyCore" / "NekoProxyCore.exe"
        identity_base_url = (
            os.getenv("NEKO_IDENTITY_BASE_URL", "").strip() or IDENTITY_BASE_URL
        )
        web_auth_bridge_url = os.getenv("NEKO_AUTH_BRIDGE_URL", "").strip()
        proxy_api_url = os.getenv("NEKO_PROXY_API_URL", "").strip()
        if proxy_api_url:
            proxy_api_url = _require_https_origin(proxy_api_url, "NEKO_PROXY_API_URL")
        frozen_build = bool(getattr(sys, "frozen", False))
        if proxy_api_url and frozen_build:
            raise ValueError("NEKO_PROXY_API_URL is disabled in frozen builds")
        if proxy_api_url and web_auth_bridge_url:
            raise ValueError(
                "NEKO_PROXY_API_URL and NEKO_AUTH_BRIDGE_URL are mutually exclusive"
            )
        proxy_api_enabled = bool(proxy_api_url)
        legacy_web_auth_enabled = (
            os.getenv("NEKO_WEB_AUTH_ENABLED") == "1"
            and bool(web_auth_bridge_url)
        )
        # The new source/dev-only path is enabled by NEKO_PROXY_API_URL alone.
        web_auth_enabled = proxy_api_enabled or legacy_web_auth_enabled
        web_auth_only_override = os.getenv("NEKO_WEB_AUTH_ONLY", "").strip()
        if web_auth_only_override == "1":
            if not web_auth_enabled:
                raise ValueError(
                    "NEKO_WEB_AUTH_ONLY requires the web auth bridge"
                )
            web_auth_only = True
        elif web_auth_only_override == "0":
            if frozen_build:
                raise ValueError(
                    "password authentication is disabled in frozen builds"
                )
            if proxy_api_enabled:
                raise ValueError(
                    "NEKO_PROXY_API_URL requires web-only authentication"
                )
            web_auth_only = False
        elif frozen_build:
            if not web_auth_enabled:
                raise ValueError(
                    "frozen 5.2.0 builds require the web auth bridge"
                )
            web_auth_only = True
        else:
            web_auth_only = web_auth_enabled
        launcher_schema = (
            os.getenv("NEKO_LAUNCHER_SCHEMA", "").strip() or "launcher"
        )
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", launcher_schema):
            raise ValueError("NEKO_LAUNCHER_SCHEMA is invalid")
        # Single debug mode authority: NEKO_DEBUG_MODE=1
        debug_mode = os.getenv("NEKO_DEBUG_MODE") == "1"
        debug_log_dir = local_app_data / "NekoFamilyProxy" / "logs"
        return cls(
            workspace_root=workspace_root,
            product_code=PRODUCT_CODE,
            game_exe=stored_game_exe,
            game_path_store=game_path_store,
            proxy_core_path=proxy_path,
            supabase_url=SUPABASE_URL,
            supabase_publishable_key=SUPABASE_PUBLISHABLE_KEY,
            account_recovery_api_url=ACCOUNT_RECOVERY_API_URL,
            proxy_status_api_url=PROXY_STATUS_API_URL,
            identity_base_url=identity_base_url,
            web_auth_bridge_url=web_auth_bridge_url,
            proxy_api_url=proxy_api_url,
            proxy_api_enabled=proxy_api_enabled,
            web_auth_enabled=web_auth_enabled,
            web_auth_only=web_auth_only,
            launcher_schema=launcher_schema,
            debug_mode=debug_mode,
            debug_log_dir=debug_log_dir,
        )


def _require_https_origin(value: str, name: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{name} must be an HTTPS origin")
    return value.rstrip("/")
