from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from typing import Any

import customtkinter as ctk


def apply_rounded_window_shape(
    window: ctk.CTk | ctk.CTkToplevel,
    *,
    radius: int = 28,
) -> None:
    """Clip a borderless Windows window to softly rounded corners."""
    if sys.platform != "win32" or not window.winfo_exists():
        return
    try:
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        width = max(1, int(window.winfo_width()))
        height = max(1, int(window.winfo_height()))
        region = ctypes.windll.gdi32.CreateRoundRectRgn(
            0,
            0,
            width + 1,
            height + 1,
            radius,
            radius,
        )
        if region:
            ctypes.windll.user32.SetWindowRgn(hwnd, region, True)
    except (AttributeError, OSError):
        pass


def style_native_title_bar(window: tk.Tk | tk.Toplevel, palette: Any) -> None:
    """Blend the Windows title bar with the UI and remove maximize."""
    if sys.platform != "win32" or not window.winfo_exists():
        return
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        gwl_style = -16
        ws_maximizebox = 0x00010000
        ws_thickframe = 0x00040000
        ws_caption = 0x00C00000
        get_window_long = user32.GetWindowLongPtrW
        get_window_long.argtypes = (ctypes.c_void_p, ctypes.c_int)
        get_window_long.restype = ctypes.c_ssize_t
        set_window_long = user32.SetWindowLongPtrW
        set_window_long.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_ssize_t,
        )
        set_window_long.restype = ctypes.c_ssize_t
        style = get_window_long(hwnd, gwl_style)
        style &= ~(ws_maximizebox | ws_thickframe | ws_caption)
        set_window_long(hwnd, gwl_style, style)
        swp_flags = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, swp_flags)

        def _colorref(hex_color: str) -> int:
            value = hex_color.lstrip("#")
            red = int(value[0:2], 16)
            green = int(value[2:4], 16)
            blue = int(value[4:6], 16)
            return red | (green << 8) | (blue << 16)

        dwmapi = ctypes.windll.dwmapi
        for attribute, color in (
            (34, palette.border),
            (35, palette.background),
            (36, palette.text),
        ):
            color_value = ctypes.c_int(_colorref(color))
            dwmapi.DwmSetWindowAttribute(
                hwnd,
                attribute,
                ctypes.byref(color_value),
                ctypes.sizeof(color_value),
            )
    except (AttributeError, OSError, ValueError):
        pass


class WindowDragHandler:
    def __init__(self, root: tk.Tk | tk.Toplevel) -> None:
        self._root = root
        self._offset_x: int = 0
        self._offset_y: int = 0
        self._target_x: int = 0
        self._target_y: int = 0
        self._after_id: str | None = None

    def start(self, event: tk.Event) -> None:
        if self._after_id is not None:
            self._root.after_cancel(self._after_id)
            self._after_id = None
        self._offset_x = event.x_root - self._root.winfo_x()
        self._offset_y = event.y_root - self._root.winfo_y()

    def drag(self, event: tk.Event) -> None:
        self._target_x = event.x_root - self._offset_x
        self._target_y = event.y_root - self._offset_y
        
        if self._after_id is None:
            self._after_id = self._root.after(12, self._apply_drag)

    def _apply_drag(self) -> None:
        self._after_id = None
        self._root.geometry(f"+{self._target_x}+{self._target_y}")
        self._root.update_idletasks()
