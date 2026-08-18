from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

import customtkinter as ctk

FONT_FAMILY = "Sarabun"
FONT_FILENAMES = ("Sarabun-Regular.ttf", "Sarabun-Bold.ttf")


@dataclass(frozen=True)
class PinkPalette:
    background: str = "#FFFFFF"
    card: str = "#FFFFFF"
    surface: str = "#F9FAFB"
    surface_accent: str = "#FFF0F5"
    primary: str = "#F84B93"
    primary_soft: str = "#FCE7F0"
    primary_dark: str = "#E02B78"
    primary_hover: str = "#FF65A8"
    text: str = "#1F2937"
    text_muted: str = "#6B7280"
    on_primary: str = "#FFFFFF"
    border: str = "#E5E7EB"
    border_accent: str = "#FFC1D6"
    success: str = "#10B981"
    success_surface: str = "#F0FDF4"
    warning: str = "#F59E0B"
    warning_surface: str = "#FFFBEB"
    danger: str = "#EF4444"
    danger_surface: str = "#FEF2F2"


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
