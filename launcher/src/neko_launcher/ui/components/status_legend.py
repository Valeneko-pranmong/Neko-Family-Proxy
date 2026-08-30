from __future__ import annotations

from typing import Any

import customtkinter as ctk

from neko_launcher.ui.theme import FONT_FAMILY, PALETTE


class StatusLegend:
    """Pure CustomTkinter status indicator legend.

    Shows SUCCESS, CONNECTING, and UNAVAILABLE semantic indicator states
    using existing theme palette tokens.
    """

    def __init__(self, master: ctk.CTkBaseClass, **kwargs: Any) -> None:
        self.frame = ctk.CTkFrame(
            master,
            fg_color="transparent",
            **kwargs,
        )

        self._items = [
            ("● เชื่อมต่อแล้ว", PALETTE.success),
            ("● กำลังเชื่อมต่อ", PALETTE.warning),
            ("● ไม่พร้อมใช้งาน", PALETTE.text_muted),
        ]

        for text, color in self._items:
            ctk.CTkLabel(
                self.frame,
                text=text,
                text_color=color,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            ).pack(side="left", padx=6)

    def pack(self, **kwargs: Any) -> None:
        self.frame.pack(**kwargs)

    def grid(self, **kwargs: Any) -> None:
        self.frame.grid(**kwargs)
