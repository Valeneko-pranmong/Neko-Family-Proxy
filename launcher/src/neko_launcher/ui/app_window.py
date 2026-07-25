from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
import tkinter as tk

from neko_launcher import __version__
from neko_launcher.application.controller import ApplicationController
from neko_launcher.domain.events import (
    StartProxyRequested,
    StateChanged,
    StopProxyRequested,
)
from neko_launcher.infrastructure.event_bus import EventBus

from .theme import PALETTE, apply_theme


class AppWindow:
    """Minimal V2 shell; business logic stays in the controller."""

    def __init__(
        self,
        controller: ApplicationController,
        event_bus: EventBus,
        logo_path: Path | None = None,
        icon_path: Path | None = None,
    ) -> None:
        apply_theme()
        self._controller = controller
        self._event_bus = event_bus
        self._logo_image = None
        self.root = ctk.CTk()
        self.root.title("Neko Family Launcher V2")
        self.root.geometry("560x500")
        self.root.minsize(520, 460)
        self.root.configure(fg_color=PALETTE.background)
        if icon_path and icon_path.is_file():
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        self._status = tk.StringVar(value="Signed out")
        self._error = tk.StringVar(value="")

        frame = ctk.CTkFrame(
            self.root,
            fg_color=PALETTE.card,
            border_color=PALETTE.border,
            border_width=1,
            corner_radius=20,
        )
        frame.pack(fill="both", expand=True, padx=24, pady=24)

        if logo_path and logo_path.is_file():
            try:
                from PIL import Image

                self._logo_image = ctk.CTkImage(
                    Image.open(logo_path),
                    size=(275, 96),
                )
                ctk.CTkLabel(
                    frame,
                    image=self._logo_image,
                    text="",
                    fg_color="transparent",
                ).pack(pady=(26, 4))
            except Exception:
                self._add_heading(frame)
        else:
            self._add_heading(frame)

        ctk.CTkLabel(
            frame,
            text="Neko Family Proxy Launcher",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(pady=(0, 18))

        status_card = ctk.CTkFrame(
            frame,
            fg_color=PALETTE.surface,
            corner_radius=14,
        )
        status_card.pack(fill="x", padx=28, pady=6)
        ctk.CTkLabel(
            status_card,
            text="Launcher Status",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PALETTE.text_muted,
        ).pack(anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(
            status_card,
            textvariable=self._status,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=PALETTE.text,
        ).pack(anchor="w", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            frame,
            textvariable=self._error,
            text_color=PALETTE.danger,
        ).pack(pady=(4, 0))

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.pack(fill="x", padx=24, pady=(16, 14))
        ctk.CTkButton(
            buttons,
            text="Start Proxy",
            fg_color=PALETTE.primary,
            hover_color=PALETTE.primary_hover,
            text_color=PALETTE.on_primary,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            command=lambda: controller.dispatch(StartProxyRequested()),
        ).pack(side="left", fill="x", expand=True, padx=6, ipady=4)
        ctk.CTkButton(
            buttons,
            text="Stop Proxy",
            fg_color="transparent",
            hover_color=PALETTE.surface,
            border_color=PALETTE.primary_soft,
            border_width=2,
            text_color=PALETTE.primary_dark,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            command=lambda: controller.dispatch(StopProxyRequested()),
        ).pack(side="left", fill="x", expand=True, padx=6, ipady=4)

        ctk.CTkLabel(
            frame,
            text=f"Version {__version__}",
            font=ctk.CTkFont(size=10),
            text_color=PALETTE.text_muted,
        ).pack(side="bottom", pady=(0, 12))

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain_events)

    def _add_heading(self, frame: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            frame,
            text="NEKO FAMILY",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=PALETTE.primary_dark,
        ).pack(pady=(32, 8))

    def _drain_events(self) -> None:
        for event in self._event_bus.drain():
            if isinstance(event, StateChanged):
                state = event.state
                self._status.set(
                    f"Auth: {state.auth_status.value} | "
                    f"Proxy: {state.proxy_status.value}"
                )
                self._error.set(state.last_error or "")
        if self.root.winfo_exists():
            self.root.after(100, self._drain_events)

    def close(self) -> None:
        self._controller.dispatch(StopProxyRequested())
        self.root.destroy()
