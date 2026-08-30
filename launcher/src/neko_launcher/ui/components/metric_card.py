from __future__ import annotations

from typing import Any

import customtkinter as ctk

from neko_launcher.ui.theme import FONT_FAMILY, PALETTE


class MetricCard:
    """Pure CustomTkinter metric card presentation.

    Caller supplies label, value, and role. Never derives metrics or conducts I/O.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        label: str,
        value: str = "—",
        role: str = "neutral",
        **kwargs: Any,
    ) -> None:
        self._label_text = label
        self._value = value
        self._role = role

        self.frame = ctk.CTkFrame(
            master,
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=8,
            **kwargs,
        )

        self._title_label = ctk.CTkLabel(
            self.frame,
            text=self._label_text,
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
        )
        self._title_label.pack(anchor="w", padx=8, pady=(4, 0))

        self._value_label = ctk.CTkLabel(
            self.frame,
            text=self._value,
            text_color=self._resolve_text_color(self._role),
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
        )
        self._value_label.pack(anchor="w", padx=8, pady=(0, 4))

    @property
    def value(self) -> str:
        return self._value

    def _resolve_text_color(self, role: str) -> str:
        if role == "success":
            return PALETTE.success
        if role == "warning":
            return PALETTE.warning
        if role == "danger":
            return PALETTE.danger
        return PALETTE.text

    def update_value(self, value: str, role: str | None = None) -> None:
        self._value = value
        if role is not None:
            self._role = role
        self._value_label.configure(
            text=self._value,
            text_color=self._resolve_text_color(self._role),
        )

    def pack(self, **kwargs: Any) -> None:
        self.frame.pack(**kwargs)

    def grid(self, **kwargs: Any) -> None:
        self.frame.grid(**kwargs)
