"""Tests for StatusLegend component.

Derived from docs/current/dashboard-redesign-plan.md Phase 2.
Contracts:
- Pure CustomTkinter presentation.
- StatusLegend: SUCCESS / CONNECTING / UNAVAILABLE indicators using existing semantic surfaces.
- Dynamic import / resolution so missing symbol produces test failure, not collection error.
"""

from __future__ import annotations

import pytest
import customtkinter as ctk

from neko_launcher.ui import theme as ui_theme


def _get_status_legend_cls() -> type:
    try:
        import importlib
        mod = importlib.import_module("neko_launcher.ui.components.status_legend")
    except ImportError:
        pytest.fail("Module neko_launcher.ui.components.status_legend does not exist")
    cls = getattr(mod, "StatusLegend", None)
    if cls is None:
        pytest.fail("StatusLegend class missing from neko_launcher.ui.components.status_legend")
    return cls


def test_status_legend_symbol_exists() -> None:
    cls = _get_status_legend_cls()
    assert isinstance(cls, type)


def test_status_legend_creation() -> None:
    cls = _get_status_legend_cls()
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        legend = cls(root)
        frame = getattr(legend, "frame", legend)
        assert isinstance(frame, (ctk.CTkFrame, ctk.CTkBaseClass))
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_status_legend_semantic_colors() -> None:
    _ = _get_status_legend_cls()
    palette = getattr(ui_theme, "PALETTE", None)
    if palette is None:
        pytest.fail("PALETTE missing from ui.theme")
    assert hasattr(palette, "success")
    assert hasattr(palette, "warning")
    assert hasattr(palette, "text_muted")
