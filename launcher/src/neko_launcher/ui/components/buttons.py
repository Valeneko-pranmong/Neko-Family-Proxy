from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk

from neko_launcher.ui.theme import FONT_FAMILY, PALETTE


def primary_button(
    parent: ctk.CTkBaseClass,
    text: str,
    command: Callable[[], None],
) -> ctk.CTkButton:
    return ctk.CTkButton(
        parent,
        text=text,
        fg_color=PALETTE.primary,
        hover_color=PALETTE.primary_hover,
        text_color=PALETTE.on_primary,
        font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
        corner_radius=18,
        height=36,
        command=command,
    )


def secondary_button(
    parent: ctk.CTkBaseClass,
    text: str,
    command: Callable[[], None],
    *,
    width: int | None = None,
    height: int = 28,
) -> ctk.CTkButton:
    options: dict[str, Any] = {}
    if width is not None:
        options["width"] = width
    return ctk.CTkButton(
        parent,
        text=text,
        fg_color="transparent",
        hover_color=PALETTE.card,
        border_color=PALETTE.primary_soft,
        border_width=2,
        text_color=PALETTE.primary_dark,
        corner_radius=14,
        height=height,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        command=command,
        **options,
    )


def card(parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
    frame = ctk.CTkFrame(
        parent,
        fg_color=PALETTE.surface,
        border_color=PALETTE.border,
        border_width=1,
        corner_radius=12,
    )
    frame.pack(fill="x", padx=8, pady=6)
    return frame


def field_label(parent: ctk.CTkBaseClass, text: str) -> None:
    ctk.CTkLabel(
        parent,
        text=text,
        text_color=PALETTE.text,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
    ).pack(anchor="w", padx=14, pady=(6, 0))


def icon_entry(
    parent: ctk.CTkBaseClass,
    icon: str,
    placeholder: str,
    variable: Any,
    *,
    show: str | None = None,
    right_icon: str | None = None,
) -> ctk.CTkEntry:
    frame = ctk.CTkFrame(
        parent,
        fg_color=PALETTE.card,
        border_width=0,
        corner_radius=10,
    )
    frame.pack(fill="x", padx=16, pady=(2, 4))

    ctk.CTkLabel(
        frame,
        text=icon,
        text_color="#A0A0A0",
        font=ctk.CTkFont(family=FONT_FAMILY, size=18),
        width=30,
    ).pack(side="left", padx=(10, 4), pady=4)

    entry = ctk.CTkEntry(
        frame,
        textvariable=variable,
        placeholder_text=placeholder,
        show=show,
        fg_color="transparent",
        text_color=PALETTE.text,
        border_width=0,
        height=38,
        font=ctk.CTkFont(family=FONT_FAMILY, size=13),
    )
    entry.pack(side="left", fill="both", expand=True, pady=4)

    if right_icon:
        ctk.CTkLabel(
            frame,
            text=right_icon,
            text_color="#C0C0C0",
            font=ctk.CTkFont(family=FONT_FAMILY, size=18),
            width=30,
        ).pack(side="right", padx=(4, 10), pady=4)

    return entry
