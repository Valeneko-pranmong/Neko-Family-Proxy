"""Update notification banner and restart prompt for Neko Family Launcher."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UpdateBannerState:
    visible: bool = False
    message: str = ""
    restart_enabled: bool = True
    busy_warning: str | None = None


class UpdateBannerController:
    """Controller managing update notification banner state and idle safety."""

    def __init__(self) -> None:
        self.state = UpdateBannerState()

    def update_status(self, has_update: bool, is_proxy_active: bool, version: str = "") -> UpdateBannerState:
        """Update banner state based on update availability and proxy activity."""
        raise NotImplementedError("update_status not implemented")
