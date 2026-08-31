"""A28 customer-facing connection diagram contract."""
from __future__ import annotations

import tkinter as tk
import customtkinter as ctk
import pytest

from neko_launcher.domain.models import HopConnectionState, NetworkHop, NetworkHopRole, NetworkPath
from neko_launcher.ui.components.connection_diagram import ConnectionDiagram


def _root():
    try:
        root = ctk.CTk()
        root.withdraw()
        return root
    except Exception:
        pytest.skip("Tkinter display not available")


def test_connection_diagram_two_node_semantics_and_metrics() -> None:
    root = _root()
    try:
        download = tk.StringVar(master=root, value="2.50 MB/s")
        upload = tk.StringVar(master=root, value="1.25 MB/s")
        server_status = tk.StringVar(master=root, value="ออนไลน์")
        latency = tk.StringVar(master=root, value="42 ms")
        path = NetworkPath(
            hops=(
                NetworkHop(NetworkHopRole.LOCAL_DEVICE, "device", connection_state=HopConnectionState.SUCCESS),
                NetworkHop(NetworkHopRole.LOCAL_PROXY_ENGINE, "Neko Core", connection_state=HopConnectionState.SUCCESS),
                NetworkHop(NetworkHopRole.REMOTE_PROXY, "Neko Proxy", connection_state=HopConnectionState.SUCCESS),
                NetworkHop(NetworkHopRole.GAME_NETWORK, "PSO2", connection_state=HopConnectionState.SUCCESS),
            ),
            proxy_rtt_ms=42,
        )
        diagram = ConnectionDiagram(
            root,
            path=path,
            download_var=download,
            upload_var=upload,
            server_status_var=server_status,
            latency_var=latency,
        )
        assert diagram.visible_roles == (
            NetworkHopRole.LOCAL_PROXY_ENGINE,
            NetworkHopRole.REMOTE_PROXY,
        )
        assert [h.label for h in diagram._visible_hops] == ["Neko Core", "Neko Proxy"]
        assert [h.location for h in diagram._visible_hops] == ["กำลังทำงาน", "เชื่อมต่อแล้ว"]
        assert diagram.displayed_rtt == "42 ms"
        assert len(diagram._node_widgets) == 2
        assert len(diagram._connector_widgets) == 1
        assert str(diagram._download_value_label.cget("textvariable")) == str(download)
        assert str(diagram._upload_value_label.cget("textvariable")) == str(upload)
        assert str(diagram._server_status_value_label.cget("textvariable")) == str(server_status)
        assert str(diagram._latency_value_label.cget("textvariable")) == str(latency)
    finally:
        root.destroy()


def test_connection_diagram_updates_in_place_without_flicker() -> None:
    root = _root()
    try:
        diagram = ConnectionDiagram(root)
        nodes = tuple(diagram._node_widgets)
        connectors = tuple(diagram._connector_widgets)
        path = NetworkPath(
            hops=(
                NetworkHop(NetworkHopRole.LOCAL_PROXY_ENGINE, "Neko Core", connection_state=HopConnectionState.SUCCESS),
                NetworkHop(NetworkHopRole.REMOTE_PROXY, "Neko Proxy", connection_state=HopConnectionState.SUCCESS),
            ),
            proxy_rtt_ms=38,
        )
        diagram.set_path(path)
        diagram.set_path(path)
        assert tuple(diagram._node_widgets) == nodes
        assert tuple(diagram._connector_widgets) == connectors
        assert diagram.displayed_rtt == "38 ms"
    finally:
        root.destroy()


def test_connection_diagram_role_icons_and_privacy_boundary() -> None:
    import inspect
    root = _root()
    try:
        diagram = ConnectionDiagram(root)
        assert len(diagram._node_widgets) == 2
        assert all(node._icon_image is not None for node in diagram._node_widgets)
        source = inspect.getsource(ConnectionDiagram).lower()
        for forbidden in ("socket", "requests", "traceroute", "icmp", "subprocess", "sega pso2", "game_path_reachable"):
            assert forbidden not in source
    finally:
        root.destroy()
