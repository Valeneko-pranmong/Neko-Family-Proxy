from __future__ import annotations

from pathlib import Path
from typing import Any

import customtkinter as ctk
from PIL import Image

from neko_launcher.domain.models import HopConnectionState, NetworkHop, NetworkHopRole
from neko_launcher.ui.theme import FONT_FAMILY, PALETTE


class NetworkHopNode:
    """Pure centered CustomTkinter network-hop presentation."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        hop: NetworkHop,
        *,
        icon_path: Path | None = None,
        **kwargs: Any,
    ) -> None:
        self._hop = hop
        self._icon_path = icon_path
        self._icon_image: ctk.CTkImage | None = None
        fg_color, border_color = self._resolve_colors(
            self._hop.role, self._hop.connection_state
        )

        self.frame = ctk.CTkFrame(
            master,
            fg_color=fg_color,
            border_color=border_color,
            border_width=1,
            corner_radius=8,
            **kwargs,
        )

        self._content_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        self._content_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self._icon_label: ctk.CTkLabel | None = None
        if self._icon_path is not None and self._icon_path.is_file():
            try:
                self._icon_image = ctk.CTkImage(
                    Image.open(self._icon_path), size=(28, 28)
                )
                self._icon_label = ctk.CTkLabel(
                    self._content_frame,
                    image=self._icon_image,
                    text="",
                    fg_color="transparent",
                    height=30,
                )
                self._icon_label.pack(anchor="center", pady=(0, 1))
            except (OSError, ValueError):
                self._icon_image = None
                self._icon_label = None

        self._label_widget = ctk.CTkLabel(
            self._content_frame,
            text=self._hop.label,
            text_color=PALETTE.text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            anchor="center",
        )
        self._label_widget.pack(anchor="center")

        self._status_row = ctk.CTkFrame(self._content_frame, fg_color="transparent")
        self._status_row.pack(anchor="center", pady=(1, 0))
        state_symbol, state_color = self._resolve_state_indicator(
            self._hop.connection_state
        )
        self._state_dot = ctk.CTkLabel(
            self._status_row,
            text=state_symbol,
            text_color=state_color,
            font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
            width=8,
        )
        self._state_dot.pack(side="left", padx=(0, 3))

        self._location_widget = ctk.CTkLabel(
            self._status_row,
            text=self._hop.location or "",
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=9),
            anchor="center",
        )
        self._location_widget.pack(side="left")

    def _resolve_colors(
        self,
        role: NetworkHopRole,
        connection_state: HopConnectionState,
    ) -> tuple[str, str]:
        if role == NetworkHopRole.LOCAL_DEVICE:
            surface = PALETTE.node_local_surface
            border = PALETTE.node_local
        elif role == NetworkHopRole.LOCAL_PROXY_ENGINE:
            surface = PALETTE.node_engine_surface
            border = PALETTE.node_engine
        elif role == NetworkHopRole.REMOTE_PROXY:
            surface = PALETTE.node_remote_surface
            border = PALETTE.node_remote
        elif role == NetworkHopRole.GAME_NETWORK:
            surface = PALETTE.node_game_surface
            border = PALETTE.node_game
        else:
            surface = PALETTE.surface
            border = PALETTE.border

        if connection_state == HopConnectionState.UNAVAILABLE:
            surface = PALETTE.surface
            border = PALETTE.border
        return surface, border

    def _resolve_state_indicator(
        self,
        connection_state: HopConnectionState,
    ) -> tuple[str, str]:
        if connection_state == HopConnectionState.SUCCESS:
            return "●", PALETTE.success
        if connection_state == HopConnectionState.CONNECTING:
            return "●", PALETTE.warning
        return "●", PALETTE.text_muted

    def set_hop(self, hop: NetworkHop) -> None:
        self._hop = hop
        fg_color, border_color = self._resolve_colors(
            self._hop.role, self._hop.connection_state
        )
        self.frame.configure(fg_color=fg_color, border_color=border_color)

        state_symbol, state_color = self._resolve_state_indicator(
            self._hop.connection_state
        )
        self._state_dot.configure(text=state_symbol, text_color=state_color)
        self._label_widget.configure(text=self._hop.label)
        self._location_widget.configure(text=self._hop.location or "")

    def pack(self, **kwargs: Any) -> None:
        self.frame.pack(**kwargs)

    def grid(self, **kwargs: Any) -> None:
        self.frame.grid(**kwargs)
