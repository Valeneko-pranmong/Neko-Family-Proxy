from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from typing import Any

import customtkinter as ctk

from neko_launcher.domain.models import (
    HopConnectionState,
    NetworkHop,
    NetworkHopRole,
    NetworkPath,
)
from neko_launcher.ui.components.network_hop_connector import NetworkHopConnector
from neko_launcher.ui.components.network_hop_node import NetworkHopNode
from neko_launcher.ui.theme import FONT_FAMILY, PALETTE


_ROLE_ICON_FILES = {
    NetworkHopRole.LOCAL_PROXY_ENGINE: "computer.png",
    NetworkHopRole.REMOTE_PROXY: "internet.png",
}

_VISIBLE_ROLES = (
    NetworkHopRole.LOCAL_PROXY_ENGINE,
    NetworkHopRole.REMOTE_PROXY,
)


def _asset_file(name: str) -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate = Path(sys._MEIPASS) / name
    else:
        candidate = Path(__file__).resolve().parents[5] / "Asset" / name
    return candidate if candidate.is_file() else None


class ConnectionDiagram:
    """Stable two-node customer connection view.

    The internal NetworkPath remains the four-hop semantic contract. This
    component intentionally presents only the two states that the product can
    measure directly and explain truthfully to customers: local Neko Core and
    remote Neko Proxy. Widgets are created once and updated in place to avoid
    status flicker during telemetry updates.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        path: NetworkPath | None = None,
        *,
        download_var: tk.StringVar | None = None,
        upload_var: tk.StringVar | None = None,
        server_status_var: tk.StringVar | None = None,
        latency_var: tk.StringVar | None = None,
        server_load_var: tk.StringVar | None = None,
        server_avg_download_var: tk.StringVar | None = None,
        server_avg_upload_var: tk.StringVar | None = None,
        server_average_window_var: tk.StringVar | None = None,
        **kwargs: Any,
    ) -> None:
        self._path = NetworkPath()
        self._download_var = download_var or tk.StringVar(master=master, value="—")
        self._upload_var = upload_var or tk.StringVar(master=master, value="—")
        self._server_status_var = server_status_var or tk.StringVar(
            master=master, value="ออฟไลน์"
        )
        self._latency_var = latency_var or tk.StringVar(
            master=master, value="—"
        )
        self._server_load_var = server_load_var
        self._server_avg_download_var = server_avg_download_var
        self._server_avg_upload_var = server_avg_upload_var
        self._server_average_window_var = server_average_window_var

        self.frame = ctk.CTkFrame(
            master,
            fg_color=PALETTE.surface,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=10,
            **kwargs,
        )
        self._grid = ctk.CTkFrame(self.frame, fg_color="transparent")
        self._grid.pack(fill="x", padx=10, pady=(7, 7))
        self._grid.grid_columnconfigure(0, weight=1, uniform="hop")
        self._grid.grid_columnconfigure(1, weight=0)
        self._grid.grid_columnconfigure(2, weight=1, uniform="hop")

        placeholders = (
            NetworkHop(
                role=NetworkHopRole.LOCAL_PROXY_ENGINE,
                label="Neko Core",
                location="ยังไม่เริ่ม",
                connection_state=HopConnectionState.UNAVAILABLE,
            ),
            NetworkHop(
                role=NetworkHopRole.REMOTE_PROXY,
                label="Neko Proxy",
                location="ยังไม่เชื่อมต่อ",
                connection_state=HopConnectionState.UNAVAILABLE,
            ),
        )
        self._visible_hops: tuple[NetworkHop, ...] = placeholders
        self._node_widgets: list[NetworkHopNode] = []

        for index, hop in enumerate(placeholders):
            column = index * 2
            icon_name = _ROLE_ICON_FILES.get(hop.role)
            node = NetworkHopNode(
                self._grid,
                hop=hop,
                icon_path=_asset_file(icon_name) if icon_name else None,
            )
            node.grid(row=0, column=column, sticky="ew", padx=2)
            self._node_widgets.append(node)

        self._connector = NetworkHopConnector(self._grid)
        self._connector.grid(row=0, column=1, padx=8)
        self._connector_widgets = [self._connector]

        # Current per-client traffic belongs under Neko Core.
        core_metrics = ctk.CTkFrame(self._grid, fg_color="transparent")
        core_metrics.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self._metric_line(
            core_metrics, "Download", self._download_var, value_bold=True
        ).pack(anchor="center")
        self._metric_line(
            core_metrics, "Upload", self._upload_var, value_bold=True
        ).pack(anchor="center")

        # Proxy server status and ping belong under Neko Proxy.
        proxy_metrics = ctk.CTkFrame(self._grid, fg_color="transparent")
        proxy_metrics.grid(row=1, column=2, sticky="ew", pady=(4, 0))
        self._metric_line(
            proxy_metrics,
            "NEKO PROXY SERVER Status :",
            self._server_status_var,
            value_bold=True,
        ).pack(anchor="center")
        self._metric_line(
            proxy_metrics,
            "PING :",
            self._latency_var,
            value_bold=True,
        ).pack(anchor="center")

        self._server_status_trace_id: str | None = None
        if self._server_status_var is not None:
            self._server_status_trace_id = self._server_status_var.trace_add(
                "write", self._on_server_status_changed
            )

        self.set_path(path or NetworkPath())

    def _on_server_status_changed(self, *_: Any) -> None:
        self._refresh_remote_node()

    def _refresh_remote_node(self) -> None:
        if len(self._node_widgets) < 2 or len(self._visible_hops) < 2:
            return
        remote_hop = self._display_hop(self._get_raw_remote_hop())
        if remote_hop != self._visible_hops[1]:
            self._visible_hops = (self._visible_hops[0], remote_hop)
            self._node_widgets[1].set_hop(remote_hop)

    def _get_raw_remote_hop(self) -> NetworkHop:
        for hop in self._path.hops:
            if hop.role == NetworkHopRole.REMOTE_PROXY:
                return hop
        return self._placeholder(NetworkHopRole.REMOTE_PROXY)

    def _metric_line(
        self,
        master: ctk.CTkBaseClass,
        name: str,
        variable: tk.StringVar,
        *,
        value_bold: bool = False,
    ) -> ctk.CTkFrame:
        row = ctk.CTkFrame(master, fg_color="transparent")
        self._small_label(row, text=f"{name} ").pack(side="left")
        value_label = self._small_label(
            row, textvariable=variable, bold=value_bold
        )
        value_label.pack(side="left")
        if name == "Download":
            self._download_value_label = value_label
        elif name == "Upload":
            self._upload_value_label = value_label
        elif "Status" in name:
            self._server_status_value_label = value_label
            self.update_server_status_color("neutral")
        elif "PING" in name:
            self._latency_value_label = value_label
        return row

    def update_server_status_color(self, role: str) -> None:
        color_map = {
            "success": PALETTE.success,
            "danger": PALETTE.danger,
            "warning": PALETTE.warning,
            "neutral": PALETTE.text_muted
        }
        if hasattr(self, "_server_status_value_label"):
            self._server_status_value_label.configure(text_color=color_map.get(role, PALETTE.text_muted))

    def _small_label(
        self,
        master: ctk.CTkBaseClass,
        *,
        text: str = "",
        textvariable: tk.StringVar | None = None,
        bold: bool = False,
    ) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            master,
            text=text,
            textvariable=textvariable,
            text_color=PALETTE.text if bold else PALETTE.text_muted,
            font=ctk.CTkFont(
                family=FONT_FAMILY,
                size=10,
                weight="bold" if bold else "normal",
            ),
        )

    def _status_text(self, hop: NetworkHop) -> str:
        if hop.role is NetworkHopRole.REMOTE_PROXY:
            server_status = ""
            if self._server_status_var is not None:
                server_status = str(self._server_status_var.get()).strip()
            if server_status == "ONLINE":
                return "พร้อมเชื่อมต่อ"
            if server_status == "OFFLINE":
                return "ไม่พร้อมเชื่อมต่อ"

        state = hop.connection_state
        if hop.role is NetworkHopRole.LOCAL_PROXY_ENGINE:
            if state is HopConnectionState.SUCCESS:
                return "กำลังทำงาน"
            if state is HopConnectionState.CONNECTING:
                return "กำลังเริ่ม"
            return "ยังไม่เริ่ม"
        if hop.role is NetworkHopRole.REMOTE_PROXY:
            if state is HopConnectionState.SUCCESS:
                return "เชื่อมต่อแล้ว"
            if state is HopConnectionState.CONNECTING:
                return "กำลังเชื่อมต่อ"
            return "ยังไม่เชื่อมต่อ"
        return "ยังไม่พร้อม"

    def _display_hop(self, hop: NetworkHop) -> NetworkHop:
        label = {
            NetworkHopRole.LOCAL_PROXY_ENGINE: "Neko Core",
            NetworkHopRole.REMOTE_PROXY: "Neko Proxy",
        }.get(hop.role, hop.label)
        return NetworkHop(
            role=hop.role,
            label=label,
            location=self._status_text(hop),
            connection_state=hop.connection_state,
        )

    def _placeholder(self, role: NetworkHopRole) -> NetworkHop:
        if role is NetworkHopRole.LOCAL_PROXY_ENGINE:
            return NetworkHop(
                role=role,
                label="Neko Core",
                location="ยังไม่เริ่ม",
                connection_state=HopConnectionState.UNAVAILABLE,
            )
        return NetworkHop(
            role=role,
            label="Neko Proxy",
            location="ยังไม่เชื่อมต่อ",
            connection_state=HopConnectionState.UNAVAILABLE,
        )

    @property
    def visible_roles(self) -> tuple[NetworkHopRole, ...]:
        return tuple(hop.role for hop in self._visible_hops)

    @property
    def displayed_rtt(self) -> str | None:
        if self._connector._rtt_label is None:
            return None
        return str(self._connector._rtt_label.cget("text"))

    def set_path(self, path: NetworkPath) -> None:
        if path == self._path and self._visible_hops:
            return
        self._path = path
        by_role = {
            hop.role: self._display_hop(hop)
            for hop in path.hops
            if hop.role in _VISIBLE_ROLES
        }
        new_hops = tuple(
            by_role.get(role, self._placeholder(role)) for role in _VISIBLE_ROLES
        )
        for index, hop in enumerate(new_hops):
            if index >= len(self._visible_hops) or hop != self._visible_hops[index]:
                self._node_widgets[index].set_hop(hop)
        self._visible_hops = new_hops
        self._connector.set_rtt(path.proxy_rtt_ms)

    def pack(self, **kwargs: Any) -> None:
        self.frame.pack(**kwargs)

    def grid(self, **kwargs: Any) -> None:
        self.frame.grid(**kwargs)
