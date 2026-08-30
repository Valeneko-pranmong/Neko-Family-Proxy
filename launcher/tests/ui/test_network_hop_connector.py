"""Tests for NetworkHopConnector component.

Derived from docs/current/dashboard-redesign-plan.md Phase 2.
Contracts:
- Pure CustomTkinter presentation.
- NetworkHopConnector: default shows no latency number.
- Explicit supplied non-negative RTT may show exactly `N ms`; None shows no number.
- Never probes or measures network.
- Dynamic import / resolution so missing symbol produces test failure, not collection error.
"""

from __future__ import annotations

import pytest
import customtkinter as ctk


def _get_network_hop_connector_cls() -> type:
    try:
        import importlib
        mod = importlib.import_module("neko_launcher.ui.components.network_hop_connector")
    except ImportError:
        pytest.fail("Module neko_launcher.ui.components.network_hop_connector does not exist")
    cls = getattr(mod, "NetworkHopConnector", None)
    if cls is None:
        pytest.fail("NetworkHopConnector class missing from neko_launcher.ui.components.network_hop_connector")
    return cls


def test_network_hop_connector_symbol_exists() -> None:
    cls = _get_network_hop_connector_cls()
    assert isinstance(cls, type)


def test_network_hop_connector_creation_and_rtt() -> None:
    cls = _get_network_hop_connector_cls()
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        # Default with no RTT (None)
        connector = cls(root)
        frame = getattr(connector, "frame", connector)
        assert isinstance(frame, (ctk.CTkFrame, ctk.CTkBaseClass))

        # Connector with explicit RTT
        connector_rtt = cls(root, rtt_ms=45)
        if hasattr(connector_rtt, "set_rtt"):
            connector_rtt.set_rtt(50)
            connector_rtt.set_rtt(None)
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_network_hop_connector_never_probes() -> None:
    cls = _get_network_hop_connector_cls()
    import inspect
    source = inspect.getsource(cls)
    forbidden = ["socket", "ping", "psutil", "urllib", "requests", "traceroute", "icmp", "tcping"]
    for word in forbidden:
        assert word not in source.lower(), f"Forbidden probe logic '{word}' found in NetworkHopConnector"
