from __future__ import annotations

import customtkinter as ctk

from neko_launcher.ui.theme import FONT_FAMILY, PALETTE


class ToastNotification:
    """Auto-dismissing notification bar anchored at the bottom of a window."""

    def __init__(self, root: ctk.CTk) -> None:
        self._root = root
        self._frame: ctk.CTkFrame | None = None
        self._label: ctk.CTkLabel | None = None
        self._close_btn: ctk.CTkButton | None = None
        self._timer: str | None = None

    def _ensure_widgets(self) -> None:
        if self._frame is not None:
            return
        self._frame = ctk.CTkFrame(
            self._root,
            corner_radius=0,
            fg_color=PALETTE.surface,
            bg_color="transparent",
            border_width=1,
            border_color=PALETTE.border,
        )
        self._label = ctk.CTkLabel(
            self._frame,
            text="",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=PALETTE.text,
        )
        self._label.pack(side="left", padx=(30, 14), pady=14)

        self._close_btn = ctk.CTkButton(
            self._frame,
            text="×",
            width=24,
            height=24,
            corner_radius=0,
            fg_color="black",
            text_color="white",
            hover_color="#333333",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            command=self.hide,
        )
        self._close_btn.pack(side="left", padx=(0, 10), pady=14)

    def show(self, message: str, is_error: bool) -> None:
        self._ensure_widgets()
        assert self._label is not None
        assert self._frame is not None
        self._label.configure(
            text=message,
            text_color=PALETTE.danger if is_error else PALETTE.text,
        )
        self._frame.place(relx=0.5, rely=1.0, y=-20, anchor="s")
        self._frame.lift()
        if self._timer:
            self._root.after_cancel(self._timer)
        self._timer = self._root.after(5000, self.hide)

    def hide(self) -> None:
        if self._frame is not None:
            self._frame.place_forget()
            if self._timer:
                self._root.after_cancel(self._timer)
                self._timer = None
