from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

import customtkinter as ctk

FONT_FAMILY = "Sarabun"
FONT_FILENAMES = ("Sarabun-Regular.ttf", "Sarabun-Bold.ttf")

CARD_RADIUS = 16
CONTROL_RADIUS = 10
SMALL_RADIUS = 8


@dataclass(frozen=True)
class PinkPalette:
    background: str = "#F6F2F4"
    card: str = "#FFFFFF"
    surface: str = "#FBF8FA"
    surface_accent: str = "#FDEFF5"
    primary: str = "#C2185B"
    primary_soft: str = "#FCE4EC"
    primary_dark: str = "#8E0E43"
    primary_hover: str = "#E0447C"
    text: str = "#241A20"
    text_muted: str = "#6E5E67"
    on_primary: str = "#FFFFFF"
    border: str = "#EADDE3"
    border_accent: str = "#F3B6CB"
    success: str = "#087A55"
    success_surface: str = "#E8F7F0"
    warning: str = "#B45309"
    warning_surface: str = "#FFF6E5"
    danger: str = "#C62828"
    danger_surface: str = "#FDECEC"
    # Phase 1 — semantic connection-diagram node tokens
    # (docs/current/dashboard-redesign-plan.md v1.2, sections 4.4 and 1.3).
    # Names use semantic roles; no raw address or infrastructure fields.
    node_local: str = "#0F9D6E"
    node_local_surface: str = "#E8F7F0"
    node_engine: str = "#1D4ED8"
    node_engine_surface: str = "#EAF1FF"
    node_remote: str = "#6D28D9"
    node_remote_surface: str = "#F3EEFF"
    node_game: str = "#C2185B"
    node_game_surface: str = "#FCE4EC"


PALETTE = PinkPalette()


def _load_bundled_fonts() -> None:
    """Register the bundled Noto Sans Thai fonts so Tkinter can use them (Windows only).

    Uses ``AddFontResourceExW`` with ``FR_PRIVATE`` so the font is available
    only within this process and is not installed system-wide.
    """
    if sys.platform != "win32":
        return
    # In a PyInstaller bundle sys._MEIPASS points to the temp extraction dir.
    # During development fall back to the repository root (3 levels up from
    # this file: ui/ -> neko_launcher/ -> src/ -> launcher/ -> repo root).
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[4]))
    FR_PRIVATE = 0x10
    for filename in FONT_FILENAMES:
        font_path = base / filename
        if font_path.is_file():
            ctypes.windll.gdi32.AddFontResourceExW(str(font_path), FR_PRIVATE, 0)


def apply_theme() -> None:
    _load_bundled_fonts()
    ctk.set_appearance_mode("light")
    # Widgets without an explicit CTkFont (entries, tab labels and secondary
    # buttons) inherit this family, so the whole interface uses Sarabun.
    ctk.ThemeManager.theme["CTkFont"]["family"] = FONT_FAMILY

    # Set the Tkinter default fonts so that widgets which do not specify an
    # explicit font (e.g. tab-view segment labels, placeholder text) also
    # render with the desired typeface.
    import tkinter.font as tkfont

    for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(font_name).configure(family=FONT_FAMILY)
        except Exception:
            pass
