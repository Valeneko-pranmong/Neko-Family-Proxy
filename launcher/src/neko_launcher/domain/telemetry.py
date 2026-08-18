from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
from typing import Any


class TelemetryConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


@dataclass(frozen=True)
class CoreHealthSnapshot:
    """Represents a validated snapshot from Core (schema_version 1)."""

    core_state: str = "stopped"
    proxy_state: str = "disconnected"
    uptime_ms: int = 0

    tcp_connect_total: int = 0
    tcp_active: int = 0
    tcp_closed_total: int = 0

    udp_event_total: int = 0

    dns_query_total: int = 0
    dns_failure_total: int = 0

    redirect_success_total: int = 0
    redirect_failure_total: int = 0

    rx_bytes: int = 0
    tx_bytes: int = 0

    network_error_total: int = 0

    v2ray_running: bool = False
    local_socks_running: bool = False
    shadowsocks_connected: bool = False

    dropped_telemetry_events: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoreHealthSnapshot:
        return cls(
            core_state=str(data.get("core_state", "stopped")),
            proxy_state=str(data.get("proxy_state", "disconnected")),
            uptime_ms=int(data.get("uptime_ms", 0)),
            tcp_connect_total=int(data.get("tcp_connect_total", 0)),
            tcp_active=int(data.get("tcp_active", 0)),
            tcp_closed_total=int(data.get("tcp_closed_total", 0)),
            udp_event_total=int(data.get("udp_event_total", 0)),
            dns_query_total=int(data.get("dns_query_total", 0)),
            dns_failure_total=int(data.get("dns_failure_total", 0)),
            redirect_success_total=int(data.get("redirect_success_total", 0)),
            redirect_failure_total=int(data.get("redirect_failure_total", 0)),
            rx_bytes=int(data.get("rx_bytes", 0)),
            tx_bytes=int(data.get("tx_bytes", 0)),
            network_error_total=int(data.get("network_error_total", 0)),
            v2ray_running=bool(data.get("v2ray_running", False)),
            local_socks_running=bool(data.get("local_socks_running", False)),
            shadowsocks_connected=bool(data.get("shadowsocks_connected", False)),
            dropped_telemetry_events=int(data.get("dropped_telemetry_events", 0)),
        )


@dataclass(frozen=True)
class TelemetryState:
    """Current aggregate telemetry state stored by the Launcher."""

    connection_state: TelemetryConnectionState = TelemetryConnectionState.DISCONNECTED
    snapshot: CoreHealthSnapshot = CoreHealthSnapshot()
    rx_rate_bps: float = 0.0
    tx_rate_bps: float = 0.0
    last_sequence: int | None = None
    last_snapshot_timestamp: float | None = None
    is_stale: bool = False
    parse_error_count: int = 0
    schema_incompatible: bool = False

    @property
    def is_healthy(self) -> bool:
        return (
            self.connection_state == TelemetryConnectionState.CONNECTED
            and not self.is_stale
            and self.snapshot.core_state == "running"
            and self.snapshot.proxy_state == "connected"
            and self.snapshot.v2ray_running
            and self.snapshot.local_socks_running
            and self.snapshot.shadowsocks_connected
        )

    @property
    def is_degraded(self) -> bool:
        if self.connection_state != TelemetryConnectionState.CONNECTED or self.is_stale:
            return False
        if self.snapshot.core_state == "running":
            return not (
                self.snapshot.v2ray_running
                and self.snapshot.local_socks_running
                and self.snapshot.shadowsocks_connected
            )
        return False


class TelemetryRateCalculator:
    """Calculates instantaneous RX/TX rates from cumulative byte counters.

    Guarantees:
    - Never produces negative rates.
    - Accurately accounts for non-1-second intervals.
    - Detects counter / session / sequence resets and safely re-establishes baseline.
    - Zero elapsed time protection.
    """

    def __init__(self) -> None:
        self._prev_rx_bytes: int | None = None
        self._prev_tx_bytes: int | None = None
        self._prev_timestamp: float | None = None
        self._prev_sequence: int | None = None

    def reset(self) -> None:
        self._prev_rx_bytes = None
        self._prev_tx_bytes = None
        self._prev_timestamp = None
        self._prev_sequence = None

    def calculate_rates(
        self,
        rx_bytes: int,
        tx_bytes: int,
        timestamp: float | None = None,
        sequence: int | None = None,
    ) -> tuple[float, float]:
        ts = time.monotonic() if timestamp is None else timestamp

        if (
            self._prev_rx_bytes is None
            or self._prev_tx_bytes is None
            or self._prev_timestamp is None
        ):
            # First snapshot establishes baseline
            self._prev_rx_bytes = rx_bytes
            self._prev_tx_bytes = tx_bytes
            self._prev_timestamp = ts
            self._prev_sequence = sequence
            return 0.0, 0.0

        # Detect counter reset, session restart, or sequence regression
        sequence_regressed = (
            sequence is not None
            and self._prev_sequence is not None
            and sequence < self._prev_sequence
        )
        counter_decreased = (
            rx_bytes < self._prev_rx_bytes or tx_bytes < self._prev_tx_bytes
        )

        if sequence_regressed or counter_decreased:
            self._prev_rx_bytes = rx_bytes
            self._prev_tx_bytes = tx_bytes
            self._prev_timestamp = ts
            self._prev_sequence = sequence
            return 0.0, 0.0

        elapsed = ts - self._prev_timestamp
        if elapsed <= 0.0:
            # Zero or negative elapsed time protection
            return 0.0, 0.0

        rx_delta = rx_bytes - self._prev_rx_bytes
        tx_delta = tx_bytes - self._prev_tx_bytes

        rx_rate = max(0.0, float(rx_delta) / elapsed)
        tx_rate = max(0.0, float(tx_delta) / elapsed)

        self._prev_rx_bytes = rx_bytes
        self._prev_tx_bytes = tx_bytes
        self._prev_timestamp = ts
        self._prev_sequence = sequence

        return rx_rate, tx_rate


def format_bytes(num_bytes: int) -> str:
    """Format byte counts into human-friendly representation."""
    if num_bytes < 0:
        return "0 B"
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_speed(rate_bps: float) -> str:
    """Format transfer rates into human-friendly representation."""
    if rate_bps <= 0.0:
        return "0 B/s"
    if rate_bps < 1024:
        return f"{rate_bps:.0f} B/s"
    if rate_bps < 1024 * 1024:
        return f"{rate_bps / 1024:.1f} KB/s"
    return f"{rate_bps / (1024 * 1024):.2f} MB/s"


def format_uptime(uptime_ms: int) -> str:
    """Format milliseconds uptime into HH:MM:SS."""
    if uptime_ms <= 0:
        return "00:00:00"
    total_seconds = uptime_ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
