from __future__ import annotations

from typing import Any

import customtkinter as ctk

from neko_launcher.ui.theme import FONT_FAMILY, PALETTE


class NetworkHopConnector:
    """Pure CustomTkinter network hop connector presentation.

    Default shows no latency number. Explicit supplied non-negative RTT
    may show exactly 'N ms'; None shows no number. Never probes or conducts I/O.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        rtt_ms: int | None = None,
        **kwargs: Any,
    ) -> None:
        self._rtt_ms = rtt_ms

        self.frame = ctk.CTkFrame(
            master,
            fg_color="transparent",
            **kwargs,
        )

        self._arrow_label = ctk.CTkLabel(
            self.frame,
            text="→",
            text_color=PALETTE.text_muted,
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
        )
        self._arrow_label.pack(side="top", expand=True)

        self._rtt_label: ctk.CTkLabel | None = None
        if self._rtt_ms is not None and self._rtt_ms >= 0:
            self._rtt_label = ctk.CTkLabel(
                self.frame,
                text=f"{self._rtt_ms} ms",
                text_color=PALETTE.text_muted,
                font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            )
            self._rtt_label.pack(side="top")

    def set_rtt(self, rtt_ms: int | None) -> None:
        self._rtt_ms = rtt_ms
        if self._rtt_ms is not None and self._rtt_ms >= 0:
            if self._rtt_label is None:
                self._rtt_label = ctk.CTkLabel(
                    self.frame,
                    text=f"{self._rtt_ms} ms",
                    text_color=PALETTE.text_muted,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                )
                self._rtt_label.pack(side="top")
            else:
                self._rtt_label.configure(text=f"{self._rtt_ms} ms")
        elif self._rtt_label is not None:
            self._rtt_label.pack_forget()
            self._rtt_label = None

    def pack(self, **kwargs: Any) -> None:
        self.frame.pack(**kwargs)

    def grid(self, **kwargs: Any) -> None:
        self.frame.grid(**kwargs)
