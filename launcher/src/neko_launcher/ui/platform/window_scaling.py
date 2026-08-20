from __future__ import annotations

import tkinter as tk
from typing import NamedTuple

import customtkinter as ctk


DESIGN_WIDTH = 440
DESIGN_HEIGHT = 592
SCREEN_MARGIN_RATIO = 0.04
SETTINGS_WIDTH = 880
SETTINGS_HEIGHT = 600
SETTINGS_SIDEBAR_WIDTH = 220
SETTINGS_CONTENT_MIN_WIDTH = 520
SETTINGS_FOOTER_RESERVE = 40


class WindowGeometry(NamedTuple):
    logical_width: int
    logical_height: int
    x: int
    y: int
    widget_scale: float


def calculate_portrait_geometry(
    screen_w: int,
    screen_h: int,
    window_scale: float,
    design_width: int,
    design_height: int,
    margin_ratio: float,
) -> WindowGeometry:
    safe_margin_y = int(screen_h * margin_ratio)
    available_h = max(1, screen_h - (safe_margin_y * 2))
    
    width = min(
        design_width / window_scale,
        max(1.0, (screen_w - 32) / window_scale),
    )
    height = min(
        design_height / window_scale,
        max(1.0, (available_h / window_scale) - 4),
    )
    scale = min(
        1.0,
        (width * window_scale) / design_width,
        (height * window_scale) / design_height,
    )
    
    logical_width = int(width)
    logical_height = int(height)
    x = max(0, (screen_w - logical_width) // 2)
    y = max(0, (screen_h - logical_height) // 2)
    
    return WindowGeometry(
        logical_width=logical_width,
        logical_height=logical_height,
        x=x,
        y=y,
        widget_scale=scale / window_scale,
    )


def calculate_centered_position(
    screen_w: int,
    screen_h: int,
    width: int,
    height: int,
) -> tuple[int, int]:
    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    return x, y


def calculate_settings_geometry(
    screen_w: int,
    screen_h: int,
    window_scale: float,
) -> WindowGeometry:
    """Describe the fixed Settings layout at supported Windows DPI values."""
    del window_scale
    x, y = calculate_centered_position(
        screen_w,
        screen_h,
        SETTINGS_WIDTH,
        SETTINGS_HEIGHT,
    )
    return WindowGeometry(
        logical_width=SETTINGS_WIDTH,
        logical_height=SETTINGS_HEIGHT,
        x=x,
        y=y,
        widget_scale=1.0,
    )


def fit_portrait_window(root: tk.Tk | tk.Toplevel) -> tuple[int, int]:
    root.update_idletasks()
    screen_w = int(root.winfo_screenwidth())
    screen_h = int(root.winfo_screenheight())
    
    window_scale = max(
        0.1,
        float(ctk.ScalingTracker.get_window_scaling(root)),
    )
    
    geometry = calculate_portrait_geometry(
        screen_w=screen_w,
        screen_h=screen_h,
        window_scale=window_scale,
        design_width=DESIGN_WIDTH,
        design_height=DESIGN_HEIGHT,
        margin_ratio=SCREEN_MARGIN_RATIO,
    )
    
    ctk.set_widget_scaling(geometry.widget_scale)
    
    root.minsize(geometry.logical_width, geometry.logical_height)
    root.maxsize(geometry.logical_width, geometry.logical_height)
    root.geometry(
        f"{geometry.logical_width}x{geometry.logical_height}+{geometry.x}+{geometry.y}"
    )
    
    return geometry.logical_width, geometry.logical_height


def center_window(root: tk.Tk | tk.Toplevel, window_size: tuple[int, int]) -> None:
    if not root.winfo_exists():
        return
    width, height = window_size
    screen_w = int(root.winfo_screenwidth())
    screen_h = int(root.winfo_screenheight())
    
    x, y = calculate_centered_position(screen_w, screen_h, width, height)
    
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.update_idletasks()
