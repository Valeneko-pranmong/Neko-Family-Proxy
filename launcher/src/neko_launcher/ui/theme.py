from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

import customtkinter as ctk

FONT_FAMILY = "Noto Sans Thai"
FONT_FILENAME = "NotoSansThai-Regular.ttf"


@dataclass(frozen=True)
class PinkPalette:
    background: str = "#FFF0F5"
    card: str = "#FFFFFF"
    surface: str = "#FFE4EC"
    primary: str = "#FF69B4"
    primary_soft: str = "#FFB6C1"
    primary_dark: str = "#FF1493"
    primary_hover: str = "#FF4FA3"
    text: str = "#555555"
    text_muted: str = "#8A7180"
    on_primary: str = "#FFFFFF"
    border: str = "#FFC1D6"
    success: str = "#32CD72"
    warning: str = "#FFA07A"
    danger: str = "#FF6347"


PALETTE = PinkPalette()


def _load_bundled_font() -> None:
    """Register the bundled .ttf so Tkinter can use it (Windows only).

    Uses ``AddFontResourceExW`` with ``FR_PRIVATE`` so the font is available
    only within this process and is not installed system-wide.
    """
    if sys.platform != "win32":
        return
    # In a PyInstaller bundle sys._MEIPASS points to the temp extraction dir.
    # During development fall back to the repository root (3 levels up from
    # this file: ui/ -> neko_launcher/ -> src/ -> launcher/ -> repo root).
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[4]))
    font_path = base / FONT_FILENAME
    if not font_path.is_file():
        return
    FR_PRIVATE = 0x10
    ctypes.windll.gdi32.AddFontResourceExW(str(font_path), FR_PRIVATE, 0)


def apply_theme() -> None:
    _load_bundled_font()
    ctk.set_appearance_mode("light")

    # Set the Tkinter default fonts so that widgets which do not specify an
    # explicit font (e.g. tab-view segment labels, placeholder text) also
    # render with the desired typeface.
    import tkinter.font as tkfont

    for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(font_name).configure(family=FONT_FAMILY)
        except Exception:
            pass