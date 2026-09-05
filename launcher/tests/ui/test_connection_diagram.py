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


def test_connection_diagram_server_status_color_roles() -> None:
    from neko_launcher.ui.theme import PALETTE

    root = _root()
    try:
        diagram = ConnectionDiagram(root)
        label = diagram._server_status_value_label
        download_label = diagram._download_value_label
        upload_label = diagram._upload_value_label
        latency_label = diagram._latency_value_label

        # Initial default role is neutral
        assert label.cget("text_color") == PALETTE.text_muted

        roles_to_colors = [
            ("success", PALETTE.success),
            ("danger", PALETTE.danger),
            ("warning", PALETTE.warning),
            ("neutral", PALETTE.text_muted),
        ]

        for role, expected_color in roles_to_colors:
            dl_color_before = download_label.cget("text_color")
            ul_color_before = upload_label.cget("text_color")
            lat_color_before = latency_label.cget("text_color")

            diagram.update_server_status_color(role)
            assert label.cget("text_color") == expected_color

            # Only server status value label changes; other metric labels remain unchanged
            assert download_label.cget("text_color") == dl_color_before
            assert upload_label.cget("text_color") == ul_color_before
            assert latency_label.cget("text_color") == lat_color_before
    finally:
        root.destroy()


def test_connection_diagram_neko_proxy_node_reflects_server_status_in_place() -> None:
    root = _root()
    try:
        server_status = tk.StringVar(master=root, value="กำลังเช็ค")
        path = NetworkPath(
            hops=(
                NetworkHop(NetworkHopRole.LOCAL_PROXY_ENGINE, "Neko Core", connection_state=HopConnectionState.SUCCESS),
                NetworkHop(NetworkHopRole.REMOTE_PROXY, "Neko Proxy", connection_state=HopConnectionState.CONNECTING),
            ),
        )
        diagram = ConnectionDiagram(root, path=path, server_status_var=server_status)
        node_widgets_before = tuple(diagram._node_widgets)
        remote_node = diagram._node_widgets[1]

        # 1. Transient/non-definitive status preserves existing NetworkHop wording ("กำลังเชื่อมต่อ")
        assert remote_node._location_widget.cget("text") == "กำลังเชื่อมต่อ"
        assert diagram._visible_hops[1].location == "กำลังเชื่อมต่อ"

        # 2. Server ONLINE => exactly "พร้อมเชื่อมต่อ", updated in place
        server_status.set("ONLINE")
        assert tuple(diagram._node_widgets) == node_widgets_before
        assert remote_node._location_widget.cget("text") == "พร้อมเชื่อมต่อ"
        assert diagram._visible_hops[1].location == "พร้อมเชื่อมต่อ"

        # 3. Server OFFLINE => exactly "ไม่พร้อมเชื่อมต่อ", updated in place
        server_status.set("OFFLINE")
        assert tuple(diagram._node_widgets) == node_widgets_before
        assert remote_node._location_widget.cget("text") == "ไม่พร้อมเชื่อมต่อ"
        assert diagram._visible_hops[1].location == "ไม่พร้อมเชื่อมต่อ"

        # 4. Back to transient (e.g. กำลังเชื่อมต่อ) => preserves NetworkHop wording
        server_status.set("กำลังเชื่อมต่อ")
        assert tuple(diagram._node_widgets) == node_widgets_before
        assert remote_node._location_widget.cget("text") == "กำลังเชื่อมต่อ"
        assert diagram._visible_hops[1].location == "กำลังเชื่อมต่อ"

        # 5. ONLINE again => exactly "พร้อมเชื่อมต่อ"
        server_status.set("ONLINE")
        assert tuple(diagram._node_widgets) == node_widgets_before
        assert remote_node._location_widget.cget("text") == "พร้อมเชื่อมต่อ"
        assert diagram._visible_hops[1].location == "พร้อมเชื่อมต่อ"
    finally:
        root.destroy()
