from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from typing import Any

import customtkinter as ctk

def _get_window_handle(window: tk.Tk | tk.Toplevel) -> int:
    """
    Safely obtain the top-level native HWND for a Tk window.
    Uses GetAncestor(..., GA_ROOT) to ensure we get the true top-level native window,
    even if the Tkinter client area is deeply nested.
    """
    if not window.winfo_exists():
        return 0
    try:
        user32 = ctypes.windll.user32
        get_ancestor = user32.GetAncestor
        get_ancestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        get_ancestor.restype = ctypes.c_void_p
        
        GA_ROOT = 2
        
        hwnd = get_ancestor(window.winfo_id(), GA_ROOT)
        if not hwnd:
            hwnd = window.winfo_id()
        return int(hwnd)
    except Exception:
        return 0

def _set_native_window_position(window: tk.Tk | tk.Toplevel, x: int, y: int) -> None:
    """Uses SetWindowPos to move the window without resizing or activating."""
    try:
        hwnd = _get_window_handle(window)
        if not hwnd:
            return
            
        user32 = ctypes.windll.user32
        set_window_pos = user32.SetWindowPos
        set_window_pos.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        )
        set_window_pos.restype = ctypes.c_int
        
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        
        flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        
        set_window_pos(ctypes.c_void_p(hwnd), None, x, y, 0, 0, flags)
    except Exception:
        pass


def apply_rounded_window_shape(
    window: ctk.CTk | ctk.CTkToplevel,
    *,
    radius: int = 28,
) -> None:
    """Clip a borderless Windows window to softly rounded corners."""
    if sys.platform != "win32" or not window.winfo_exists():
        return
    try:
        hwnd = _get_window_handle(window)
        if not hwnd:
            return
        
        # Use Windows 11 hardware-accelerated DWM rounded corners.
        # We explicitly DO NOT use GDI CreateRoundRectRgn because it forces 
        # software rendering compositing, which causes horrific smearing when dragged!
        dwmapi = ctypes.windll.dwmapi
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        value = ctypes.c_int(DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(value),
            ctypes.c_size_t(ctypes.sizeof(value))
        )
    except Exception:
        pass


def style_native_title_bar(window: tk.Tk | tk.Toplevel, palette: Any) -> None:
    """Blend the Windows title bar with the UI and remove maximize."""
    if sys.platform != "win32" or not window.winfo_exists():
        return
    try:
        user32 = ctypes.windll.user32
        hwnd = _get_window_handle(window)
        if not hwnd:
            return
            
        gwl_style = -16
        ws_maximizebox = 0x00010000
        ws_thickframe = 0x00040000
        
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
        style &= ~(ws_maximizebox | ws_thickframe)
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
    """Handles native window dragging, safely interacting with Win32 APIs."""
    def __init__(self, root: tk.Tk | tk.Toplevel) -> None:
        self._root = root
        self._offset_x: int = 0
        self._offset_y: int = 0
        self._is_win32 = sys.platform == "win32"
        
        self._pending_x: int | None = None
        self._pending_y: int | None = None
        self._move_job: str | None = None

    def bind_to(self, drag_surface: ctk.CTkBaseClass) -> None:
        """Bind the appropriate events to the surface depending on the OS."""
        drag_surface.bind("<ButtonPress-1>", self.start, add="+")
        drag_surface.bind("<B1-Motion>", self.drag, add="+")
        if self._is_win32:
            drag_surface.bind("<ButtonRelease-1>", self.stop, add="+")

    def start(self, event: tk.Event) -> None:
        """Called upon mouse press."""
        if self._is_win32:
            self._offset_x = int(event.x_root) - self._root.winfo_x()
            self._offset_y = int(event.y_root) - self._root.winfo_y()
        else:
            self._offset_x = event.x_root - self._root.winfo_x()
            self._offset_y = event.y_root - self._root.winfo_y()

    def drag(self, event: tk.Event) -> None:
        """Called upon mouse motion."""
        if self._is_win32:
            x = int(event.x_root) - self._offset_x
            y = int(event.y_root) - self._offset_y
            
            self._pending_x = x
            self._pending_y = y
            
            if self._move_job is None:
                self._move_job = self._root.after(16, self._flush_move)
        else:
            x = event.x_root - self._offset_x
            y = event.y_root - self._offset_y
            self._root.geometry(f"+{x}+{y}")
            
    def stop(self, event: tk.Event) -> None:
        """Called upon mouse release."""
        if self._is_win32:
            if self._move_job is not None:
                self._root.after_cancel(self._move_job)
                self._move_job = None
                self._flush_move()
            self._pending_x = None
            self._pending_y = None

    def _flush_move(self) -> None:
        """Execute the physical move using Win32 API."""
        self._move_job = None
        
        if self._pending_x is None or self._pending_y is None:
            return
            
        x = self._pending_x
        y = self._pending_y
        
        self._pending_x = None
        self._pending_y = None
        
        if not self._root.winfo_exists():
            return
            
        _set_native_window_position(self._root, x, y)
