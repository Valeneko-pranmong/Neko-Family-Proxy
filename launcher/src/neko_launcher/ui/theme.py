from __future__ import annotations

from dataclasses import dataclass

import customtkinter as ctk


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


def apply_theme() -> None:
    ctk.set_appearance_mode("light")
