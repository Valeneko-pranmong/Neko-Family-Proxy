"""Tests for NetworkHopNode component.

Derived from docs/current/dashboard-redesign-plan.md Phase 2.
Contracts:
- Pure CustomTkinter presentation.
- NetworkHopNode: renders Phase-1 NetworkHop label + optional location.
- Role maps to node_local/node_engine/node_remote/node_game + surfaces.
- Supports three connection states: SUCCESS, CONNECTING, UNAVAILABLE.
- Never renders or references raw IP, hostname, port, endpoint, or destination history.
- Dynamic import / resolution so missing symbol produces test failure, not collection error.
"""

from __future__ import annotations

import pytest
import customtkinter as ctk

from neko_launcher.domain.models import HopConnectionState, NetworkHop, NetworkHopRole


def _get_network_hop_node_cls() -> type:
    try:
        import importlib
        mod = importlib.import_module("neko_launcher.ui.components.network_hop_node")
    except ImportError:
        pytest.fail("Module neko_launcher.ui.components.network_hop_node does not exist")
    cls = getattr(mod, "NetworkHopNode", None)
    if cls is None:
        pytest.fail("NetworkHopNode class missing from neko_launcher.ui.components.network_hop_node")
    return cls


def test_network_hop_node_symbol_exists() -> None:
    cls = _get_network_hop_node_cls()
    assert isinstance(cls, type)


def test_network_hop_node_creation_and_states() -> None:
    cls = _get_network_hop_node_cls()
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        hop = NetworkHop(
            role=NetworkHopRole.REMOTE_PROXY,
            label="Neko Proxy",
            location="Japan/Tokyo",
            connection_state=HopConnectionState.SUCCESS,
        )
        node = cls(root, hop=hop)
        frame = getattr(node, "frame", node)
        assert isinstance(frame, (ctk.CTkFrame, ctk.CTkBaseClass))

        # Test updating hop or state
        if hasattr(node, "set_hop"):
            connecting_hop = NetworkHop(
                role=NetworkHopRole.REMOTE_PROXY,
                label="Neko Proxy",
                location="Japan/Tokyo",
                connection_state=HopConnectionState.CONNECTING,
            )
            node.set_hop(connecting_hop)
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_network_hop_node_privacy_contract() -> None:
    cls = _get_network_hop_node_cls()
    import inspect
    source = inspect.getsource(cls)
    forbidden = ["ip", "host", "port", "bangkok", "endpoint", "traceroute", "raw_ip"]
    for word in forbidden:
        assert word not in source.lower(), f"Forbidden privacy identifier '{word}' found in NetworkHopNode"
