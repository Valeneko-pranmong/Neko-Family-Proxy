"""Tests for MetricCard component.

Derived from docs/current/dashboard-redesign-plan.md Phase 2.
Contracts:
- Pure CustomTkinter presentation.
- MetricCard: caller supplies label/value/role; never derives metrics.
- Dynamic import / resolution so missing symbol produces test failure, not collection error.
"""

from __future__ import annotations

import pytest
import customtkinter as ctk


def _get_metric_card_cls() -> type:
    try:
        import importlib
        mod = importlib.import_module("neko_launcher.ui.components.metric_card")
    except ImportError:
        pytest.fail("Module neko_launcher.ui.components.metric_card does not exist")
    cls = getattr(mod, "MetricCard", None)
    if cls is None:
        pytest.fail("MetricCard class missing from neko_launcher.ui.components.metric_card")
    return cls


def test_metric_card_symbol_exists() -> None:
    cls = _get_metric_card_cls()
    assert isinstance(cls, type)


def test_metric_card_creation_and_update() -> None:
    cls = _get_metric_card_cls()
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        card = cls(root, label="เวลาเชื่อมต่อรวม", value="01:23:45", role="neutral")
        frame = getattr(card, "frame", card)
        assert isinstance(frame, (ctk.CTkFrame, ctk.CTkBaseClass))
        
        # Test update_value
        if hasattr(card, "update_value"):
            card.update_value("02:00:00")
            assert getattr(card, "value", None) == "02:00:00" or getattr(card, "_value", None) == "02:00:00"
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_metric_card_does_not_derive_metrics() -> None:
    cls = _get_metric_card_cls()
    # Contract: MetricCard does not calculate RTT, uptime, or RX/TX internally.
    import inspect
    source = inspect.getsource(cls)
    forbidden = ["socket", "ping", "psutil", "urllib", "requests", "traceroute"]
    for word in forbidden:
        assert word not in source.lower(), f"Forbidden logic '{word}' found in MetricCard"
