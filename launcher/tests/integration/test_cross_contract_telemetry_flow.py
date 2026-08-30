from __future__ import annotations

import dataclasses
import json
import tkinter as tk
from typing import Any

import customtkinter as ctk
import pytest

from neko_launcher.application.ports import EventPublisher
from neko_launcher.domain.events import Event
from neko_launcher.domain.models import (
    AppState,
    GameStatus,
    HopConnectionState,
    NetworkHop,
    NetworkHopRole,
    NetworkPath,
    ProxyStatus,
)
from neko_launcher.domain.telemetry import (
    CoreHealthSnapshot,
    TelemetryConnectionState,
    TelemetryRateCalculator,
    TelemetryState,
    format_bytes,
    format_latency,
    format_speed,
    format_uptime,
)
from neko_launcher.infrastructure.core.core_telemetry_client import (
    NamedPipeCoreTelemetryClient,
)
from neko_launcher.ui.network_path_presentation import map_network_path
from neko_launcher.ui.views.dashboard_view import DashboardView

FORBIDDEN_FIELDS = {"ip", "hostname", "port", "address", "endpoint", "bangkok", "per_hop_latency_ms"}
FORBIDDEN_STRING_PATTERNS = ("127.0.0.1", "192.168.", "10.", "8443", "1080", "proxy.internal")


class InMemoryEventPublisher(EventPublisher):
    """Deterministic in-memory event publisher for integration testing."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def publish(self, event: Event) -> None:
        self.events.append(event)


def _make_core_wire_frame(
    payload: dict[str, Any],
    sequence: int = 1,
    timestamp_utc: str = "2026-08-29T12:00:00.000Z",
) -> str:
    """Build a standard JSON frame matching Core schema version 1 wire contract."""
    return json.dumps(
        {
            "schema_version": 1,
            "sequence": sequence,
            "timestamp_utc": timestamp_utc,
            "message_type": "core.health.snapshot",
            "component": "core",
            "payload": payload,
        }
    )


def _create_connected_client(pub: EventPublisher | None = None) -> NamedPipeCoreTelemetryClient:
    """Initialize a telemetry client with active CONNECTED state for deterministic frame testing."""
    if pub is None:
        pub = InMemoryEventPublisher()
    client = NamedPipeCoreTelemetryClient(pub)
    client._update_state(connection_state=TelemetryConnectionState.CONNECTED, is_stale=False)
    return client


def _create_dashboard_harness() -> tuple[ctk.CTk, DashboardView, dict[str, tk.StringVar]] | None:
    """Safely initialize CTk root and DashboardView with StringVars if display is available."""
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        return None

    vars_dict = {
        "status_title": tk.StringVar(value="● พร้อมใช้งาน"),
        "status_subtitle": tk.StringVar(value="กำลังรอเปิด PSO2"),
        "account": tk.StringVar(value="pilot@example.com"),
        "entitlement_days": tk.StringVar(value="เหลือ 30 วัน"),
        "entitlement_expiry": tk.StringVar(value="28/10/2026 12:00"),
        "server_status": tk.StringVar(value="ออฟไลน์"),
        "download_speed": tk.StringVar(value="—"),
        "upload_speed": tk.StringVar(value="—"),
        "session_duration": tk.StringVar(value="—"),
        "latency": tk.StringVar(value="—"),
    }

    view = DashboardView(
        root,
        root,
        status_title_var=vars_dict["status_title"],
        status_subtitle_var=vars_dict["status_subtitle"],
        account_var=vars_dict["account"],
        entitlement_days_var=vars_dict["entitlement_days"],
        entitlement_expiry_var=vars_dict["entitlement_expiry"],
        server_status_var=vars_dict["server_status"],
        download_speed_var=vars_dict["download_speed"],
        upload_speed_var=vars_dict["upload_speed"],
        session_duration_var=vars_dict["session_duration"],
        latency_var=vars_dict["latency"],
    )
    return root, view, vars_dict


# ===========================================================================
# Case 1: proxy_rtt_ms missing from wire payload -> None -> NetworkPath None -> displayed "—"
# ===========================================================================


def test_case_1_proxy_rtt_ms_missing_yields_none_and_dash_placeholder() -> None:
    wire_payload: dict[str, Any] = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 15000,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": True,
        "rx_bytes": 2048,
        "tx_bytes": 1024,
    }
    assert "proxy_rtt_ms" not in wire_payload

    # Stage 1: Parse through CoreHealthSnapshot wire deserializer
    snapshot = CoreHealthSnapshot.from_dict(wire_payload)
    assert snapshot.proxy_rtt_ms is None

    # Stage 2: TelemetryClient processes the wire frame
    client = _create_connected_client()
    client._handle_frame(_make_core_wire_frame(wire_payload), timestamp=100.0)
    assert client.state.snapshot.proxy_rtt_ms is None

    # Stage 3: Map to presentation domain NetworkPath
    app_state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
        game_status=GameStatus.RUNNING,
    )
    network_path = map_network_path(app_state, client.state)
    assert network_path.proxy_rtt_ms is None

    # Stage 4: Formatting contract produces "—"
    latency_formatted = format_latency(network_path.proxy_rtt_ms)
    assert latency_formatted == "—"

    # Stage 5: DashboardView presentation integration
    harness = _create_dashboard_harness()
    if harness is not None:
        root, view, vars_dict = harness
        try:
            vars_dict["latency"].set(latency_formatted)
            view.set_network_path(network_path)
            assert view._connection_diagram.displayed_rtt is None
        finally:
            try:
                root.destroy()
            except Exception:
                pass


# ===========================================================================
# Case 2: proxy_rtt_ms explicit null -> None -> NetworkPath None -> displayed "—"
# ===========================================================================


def test_case_2_proxy_rtt_ms_null_yields_none_and_dash_placeholder() -> None:
    wire_payload: dict[str, Any] = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 20000,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": True,
        "proxy_rtt_ms": None,
    }

    # Stage 1 & 2: Deserialization & Client
    snapshot = CoreHealthSnapshot.from_dict(wire_payload)
    assert snapshot.proxy_rtt_ms is None

    client = _create_connected_client()
    client._handle_frame(_make_core_wire_frame(wire_payload), timestamp=100.0)
    assert client.state.snapshot.proxy_rtt_ms is None

    # Stage 3: NetworkPath mapping
    app_state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
        game_status=GameStatus.RUNNING,
    )
    network_path = map_network_path(app_state, client.state)
    assert network_path.proxy_rtt_ms is None

    # Stage 4: Formatted latency is "—"
    latency_formatted = format_latency(network_path.proxy_rtt_ms)
    assert latency_formatted == "—"

    # Stage 5: DashboardView metric value
    harness = _create_dashboard_harness()
    if harness is not None:
        root, view, vars_dict = harness
        try:
            vars_dict["latency"].set(latency_formatted)
            assert view._connection_diagram.displayed_rtt is None
        finally:
            try:
                root.destroy()
            except Exception:
                pass


# ===========================================================================
# Case 3: proxy_rtt_ms 0 -> 0 -> NetworkPath 0 -> displayed "0 ms"
# ===========================================================================


def test_case_3_proxy_rtt_ms_zero_yields_zero_ms_displayed() -> None:
    wire_payload: dict[str, Any] = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 30000,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": True,
        "proxy_rtt_ms": 0,
    }

    # Stage 1 & 2: Deserialization & Client
    snapshot = CoreHealthSnapshot.from_dict(wire_payload)
    assert snapshot.proxy_rtt_ms == 0

    client = _create_connected_client()
    client._handle_frame(_make_core_wire_frame(wire_payload), timestamp=100.0)
    assert client.state.snapshot.proxy_rtt_ms == 0

    # Stage 3: NetworkPath mapping preserves 0
    app_state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
        game_status=GameStatus.RUNNING,
    )
    network_path = map_network_path(app_state, client.state)
    assert network_path.proxy_rtt_ms == 0

    # Stage 4: Formatting contract produces "0 ms"
    latency_formatted = format_latency(network_path.proxy_rtt_ms)
    assert latency_formatted == "0 ms"

    # Stage 5: DashboardView metric value
    harness = _create_dashboard_harness()
    if harness is not None:
        root, view, vars_dict = harness
        try:
            vars_dict["latency"].set(latency_formatted)
            view.set_network_path(network_path)
            assert view._connection_diagram.displayed_rtt == "0 ms"
        finally:
            try:
                root.destroy()
            except Exception:
                pass


# ===========================================================================
# Case 4: proxy_rtt_ms positive 42 -> 42 -> NetworkPath 42 -> displayed "42 ms"
# ===========================================================================


def test_case_4_proxy_rtt_ms_positive_yields_formatted_ms_displayed() -> None:
    wire_payload: dict[str, Any] = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 45000,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": True,
        "proxy_rtt_ms": 42,
    }

    # Stage 1 & 2: Deserialization & Client
    snapshot = CoreHealthSnapshot.from_dict(wire_payload)
    assert snapshot.proxy_rtt_ms == 42

    client = _create_connected_client()
    client._handle_frame(_make_core_wire_frame(wire_payload), timestamp=100.0)
    assert client.state.snapshot.proxy_rtt_ms == 42

    # Stage 3: NetworkPath mapping flows 42
    app_state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
        game_status=GameStatus.RUNNING,
    )
    network_path = map_network_path(app_state, client.state)
    assert network_path.proxy_rtt_ms == 42

    # Stage 4: Formatting contract produces "42 ms"
    latency_formatted = format_latency(network_path.proxy_rtt_ms)
    assert latency_formatted == "42 ms"

    # Stage 5: DashboardView metric value
    harness = _create_dashboard_harness()
    if harness is not None:
        root, view, vars_dict = harness
        try:
            vars_dict["latency"].set(latency_formatted)
            view.set_network_path(network_path)
            assert view._connection_diagram.displayed_rtt == "42 ms"
        finally:
            try:
                root.destroy()
            except Exception:
                pass


# ===========================================================================
# Case 5: negative/wrong-type from wire -> normalized None -> displayed "—"
# ===========================================================================


@pytest.mark.parametrize(
    "invalid_wire_rtt",
    [
        -1,
        -42,
        -1000,
        "42",
        "fast",
        "",
        42.0,
        42.5,
        True,
        False,
        [],
        [42],
        {},
        {"latency": 42},
    ],
)
def test_case_5_negative_and_wrong_type_normalized_to_none(invalid_wire_rtt: Any) -> None:
    wire_payload: dict[str, Any] = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 10000,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": True,
        "proxy_rtt_ms": invalid_wire_rtt,
    }

    # Deserialization must normalize invalid or non-integer RTTs to None
    snapshot = CoreHealthSnapshot.from_dict(wire_payload)
    assert snapshot.proxy_rtt_ms is None

    # Telemetry client processing
    client = _create_connected_client()
    client._handle_frame(_make_core_wire_frame(wire_payload), timestamp=100.0)
    assert client.state.snapshot.proxy_rtt_ms is None

    # Mapping to NetworkPath must succeed without ValueError
    app_state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
        game_status=GameStatus.RUNNING,
    )
    network_path = map_network_path(app_state, client.state)
    assert network_path.proxy_rtt_ms is None

    # Latency formatting yields "—"
    assert format_latency(network_path.proxy_rtt_ms) == "—"


# ===========================================================================
# Case 6: safe full-connected flags produce four semantic hops in correct order,
# no raw endpoint/address info
# ===========================================================================


def test_case_6_safe_full_connected_semantic_hops_and_privacy_invariants() -> None:
    wire_payload: dict[str, Any] = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 60000,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": True,
        "proxy_rtt_ms": 35,
    }

    snapshot = CoreHealthSnapshot.from_dict(wire_payload)
    assert snapshot.core_state == "running"
    client = _create_connected_client()
    client._handle_frame(_make_core_wire_frame(wire_payload), timestamp=100.0)

    app_state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
        game_status=GameStatus.RUNNING,
    )
    network_path = map_network_path(app_state, client.state)

    # Invariant: exactly four hops in strict canonical order
    assert len(network_path.hops) == 4
    assert network_path.hops[0].role == NetworkHopRole.LOCAL_DEVICE
    assert network_path.hops[1].role == NetworkHopRole.LOCAL_PROXY_ENGINE
    assert network_path.hops[2].role == NetworkHopRole.REMOTE_PROXY
    assert network_path.hops[3].role == NetworkHopRole.GAME_NETWORK

    # Invariant: all hops SUCCESS in full connected state
    assert network_path.hops[0].connection_state == HopConnectionState.SUCCESS
    assert network_path.hops[1].connection_state == HopConnectionState.SUCCESS
    assert network_path.hops[2].connection_state == HopConnectionState.SUCCESS
    assert network_path.hops[3].connection_state == HopConnectionState.SUCCESS

    # Invariant: safe customer-facing labels
    assert network_path.hops[0].label == "อุปกรณ์ของคุณ"
    assert network_path.hops[1].label == "Neko Core"
    assert network_path.hops[2].label == "Neko Proxy"
    assert network_path.hops[3].label == "PSO2"

    # Invariant: safe customer-facing locations
    assert network_path.hops[0].location == "Local PC"
    assert network_path.hops[1].location == "Local Service"
    assert network_path.hops[2].location == "Japan, Tokyo"
    assert network_path.hops[3].location is None

    # Privacy verification: no forbidden field names in dataclasses
    hop_fields = {f.name for f in dataclasses.fields(NetworkHop)}
    path_fields = {f.name for f in dataclasses.fields(NetworkPath)}
    snapshot_fields = {f.name for f in dataclasses.fields(CoreHealthSnapshot)}

    assert hop_fields.isdisjoint(FORBIDDEN_FIELDS)
    assert path_fields.isdisjoint(FORBIDDEN_FIELDS)
    assert snapshot_fields.isdisjoint(FORBIDDEN_FIELDS)

    # Privacy verification: no raw IP or port pattern appears in text copy
    all_hop_strings = [
        hop.label for hop in network_path.hops
    ] + [
        hop.location or "" for hop in network_path.hops
    ]
    for pattern in FORBIDDEN_STRING_PATTERNS:
        for s in all_hop_strings:
            assert pattern not in s, f"Forbidden pattern {pattern!r} leaked in {s!r}"


# ===========================================================================
# Case 7: stale/disconnected telemetry clears/withholds unsafe metrics
# ===========================================================================


def test_case_7_disconnected_telemetry_withholds_metrics() -> None:
    app_state = AppState(
        proxy_status=ProxyStatus.STOPPED,
        game_process_running=False,
        game_status=GameStatus.STOPPED,
    )

    # Telemetry is disconnected even if underlying snapshot has values
    snapshot_with_data = CoreHealthSnapshot(
        core_state="running",
        proxy_state="connected",
        v2ray_running=True,
        local_socks_running=True,
        shadowsocks_connected=True,
        proxy_rtt_ms=42,
        rx_bytes=100000,
        tx_bytes=50000,
        uptime_ms=60000,
    )
    disconnected_telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.DISCONNECTED,
        snapshot=snapshot_with_data,
        is_stale=False,
    )

    network_path = map_network_path(app_state, disconnected_telemetry)
    # RTT must be withheld (None) when disconnected
    assert network_path.proxy_rtt_ms is None
    assert format_latency(network_path.proxy_rtt_ms) == "—"

    # Hops degrade safely
    roles = {h.role: h.connection_state for h in network_path.hops}
    assert roles[NetworkHopRole.LOCAL_DEVICE] == HopConnectionState.UNAVAILABLE
    assert roles[NetworkHopRole.LOCAL_PROXY_ENGINE] == HopConnectionState.UNAVAILABLE
    assert roles[NetworkHopRole.REMOTE_PROXY] == HopConnectionState.UNAVAILABLE
    assert roles[NetworkHopRole.GAME_NETWORK] == HopConnectionState.UNAVAILABLE


def test_case_7_stale_telemetry_withholds_metrics_and_degrades_hops() -> None:
    app_state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
        game_status=GameStatus.RUNNING,
    )

    stale_snapshot = CoreHealthSnapshot(
        core_state="running",
        proxy_state="connected",
        v2ray_running=True,
        local_socks_running=True,
        shadowsocks_connected=True,
        proxy_rtt_ms=42,
    )
    stale_telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=stale_snapshot,
        is_stale=True,
    )

    assert stale_telemetry.is_healthy is False
    assert stale_telemetry.is_degraded is False

    network_path = map_network_path(app_state, stale_telemetry)

    # RTT must be withheld (None) when stale
    assert network_path.proxy_rtt_ms is None
    assert format_latency(network_path.proxy_rtt_ms) == "—"

    # Hops degrade: engine is conservatively CONNECTING, remote proxy is UNAVAILABLE
    roles = {h.role: h.connection_state for h in network_path.hops}
    assert roles[NetworkHopRole.LOCAL_DEVICE] == HopConnectionState.SUCCESS
    assert roles[NetworkHopRole.LOCAL_PROXY_ENGINE] == HopConnectionState.CONNECTING
    assert roles[NetworkHopRole.REMOTE_PROXY] == HopConnectionState.UNAVAILABLE
    assert roles[NetworkHopRole.GAME_NETWORK] == HopConnectionState.CONNECTING


def test_case_7_none_telemetry_withholds_metrics() -> None:
    app_state = AppState(proxy_status=ProxyStatus.STOPPED)
    network_path = map_network_path(app_state, telemetry=None)
    assert network_path.proxy_rtt_ms is None
    assert format_latency(network_path.proxy_rtt_ms) == "—"


# ===========================================================================
# Case 8: rx_bytes/tx_bytes/uptime formatting reaches existing metric presentation
# without inventing measurements
# ===========================================================================


def test_case_8_throughput_and_uptime_flow_without_invented_measurements() -> None:
    client = _create_connected_client()

    # Frame 1 at t=100.0: initial baseline establishing
    frame_1_payload = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 125000,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": True,
        "rx_bytes": 100_000_000,
        "tx_bytes": 50_000_000,
        "proxy_rtt_ms": 40,
    }
    client._handle_frame(_make_core_wire_frame(frame_1_payload, sequence=1), timestamp=100.0)

    # Baseline frame calculates rate 0.0 without inventing speed
    assert client.state.rx_rate_bps == 0.0
    assert client.state.tx_rate_bps == 0.0

    # Frame 2 at t=102.0 (elapsed = 2.0s):
    # +5,242,880 bytes rx (+5 MB) -> rate = 2,621,440 B/s (2.50 MB/s)
    # +2,621,440 bytes tx (+2.5 MB) -> rate = 1,310,720 B/s (1.25 MB/s)
    # uptime increases by 2000 ms -> 127000 ms (00:02:07)
    frame_2_payload = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 127000,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": True,
        "rx_bytes": 105_242_880,
        "tx_bytes": 52_621_440,
        "proxy_rtt_ms": 38,
    }
    client._handle_frame(_make_core_wire_frame(frame_2_payload, sequence=2), timestamp=102.0)

    assert client.state.rx_rate_bps == 2_621_440.0
    assert client.state.tx_rate_bps == 1_310_720.0

    # Verify formatting contracts
    rx_speed_str = format_speed(client.state.rx_rate_bps)
    tx_speed_str = format_speed(client.state.tx_rate_bps)
    uptime_str = format_uptime(client.state.snapshot.uptime_ms)
    rx_total_str = format_bytes(client.state.snapshot.rx_bytes)
    tx_total_str = format_bytes(client.state.snapshot.tx_bytes)
    latency_str = format_latency(client.state.snapshot.proxy_rtt_ms)

    assert rx_speed_str == "2.50 MB/s"
    assert tx_speed_str == "1.25 MB/s"
    assert uptime_str == "00:02:07"
    assert rx_total_str == "100.4 MB"
    assert tx_total_str == "50.2 MB"
    assert latency_str == "38 ms"

    # DashboardView integration update
    harness = _create_dashboard_harness()
    if harness is not None:
        root, view, vars_dict = harness
        try:
            vars_dict["download_speed"].set(rx_speed_str)
            vars_dict["upload_speed"].set(tx_speed_str)
            vars_dict["session_duration"].set(uptime_str)
            vars_dict["latency"].set(latency_str)

            assert vars_dict["download_speed"].get() == "2.50 MB/s"
            assert vars_dict["upload_speed"].get() == "1.25 MB/s"
            assert str(view._connection_diagram._download_value_label.cget("textvariable")) == str(vars_dict["download_speed"])
            assert str(view._connection_diagram._upload_value_label.cget("textvariable")) == str(vars_dict["upload_speed"])
            app_state = AppState(
                proxy_status=ProxyStatus.RUNNING,
                game_process_running=True,
                game_status=GameStatus.RUNNING,
            )
            view.set_network_path(map_network_path(app_state, client.state))
            assert view._connection_diagram.displayed_rtt == "38 ms"
        finally:
            try:
                root.destroy()
            except Exception:
                pass


def test_case_8_counter_reset_and_zero_elapsed_protection() -> None:
    calc = TelemetryRateCalculator()

    # Establish baseline
    calc.calculate_rates(rx_bytes=10_000_000, tx_bytes=5_000_000, timestamp=100.0, sequence=10)

    # Normal delta
    rx_rate, tx_rate = calc.calculate_rates(
        rx_bytes=11_048_576, tx_bytes=5_524_288, timestamp=101.0, sequence=11
    )
    assert rx_rate == 1_048_576.0
    assert tx_rate == 524_288.0

    # Counter reset (e.g. Core restart): rx_bytes decreased
    rx_reset, tx_reset = calc.calculate_rates(
        rx_bytes=1000, tx_bytes=500, timestamp=102.0, sequence=12
    )
    assert rx_reset == 0.0
    assert tx_reset == 0.0
    assert format_speed(rx_reset) == "0 B/s"

    # Sequence regression: sequence jumped back to 1
    rx_seq, tx_seq = calc.calculate_rates(
        rx_bytes=2000, tx_bytes=1000, timestamp=103.0, sequence=1
    )
    assert rx_seq == 0.0
    assert tx_seq == 0.0

    # Zero elapsed time (timestamp identical)
    rx_zero, tx_zero = calc.calculate_rates(
        rx_bytes=3000, tx_bytes=1500, timestamp=103.0, sequence=2
    )
    assert rx_zero == 0.0
    assert tx_zero == 0.0


# ===========================================================================
# End-to-End multi-stage cross-contract pipeline simulation
# ===========================================================================


def test_end_to_end_core_to_dashboard_full_lifecycle() -> None:
    client = _create_connected_client()
    app_state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
        game_status=GameStatus.RUNNING,
    )

    # 1. First snapshot: connecting state, baseline establishment
    frame_connecting = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 1000,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": False,
        "rx_bytes": 0,
        "tx_bytes": 0,
        "proxy_rtt_ms": None,
    }
    client._handle_frame(_make_core_wire_frame(frame_connecting, sequence=1), timestamp=10.0)
    path_1 = map_network_path(app_state, client.state)

    assert path_1.proxy_rtt_ms is None
    assert path_1.hops[1].connection_state == HopConnectionState.SUCCESS  # local engine
    assert path_1.hops[2].connection_state == HopConnectionState.CONNECTING  # remote proxy
    assert format_latency(path_1.proxy_rtt_ms) == "—"

    # 2. Second snapshot: fully connected Neko proxy, measuring RTT and throughput
    frame_connected = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 3000,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": True,
        "rx_bytes": 4_194_304,
        "tx_bytes": 2_097_152,
        "proxy_rtt_ms": 48,
    }
    client._handle_frame(_make_core_wire_frame(frame_connected, sequence=2), timestamp=12.0)
    path_2 = map_network_path(app_state, client.state)

    assert path_2.proxy_rtt_ms == 48
    assert path_2.hops[1].connection_state == HopConnectionState.SUCCESS
    assert path_2.hops[2].connection_state == HopConnectionState.SUCCESS
    assert path_2.hops[3].connection_state == HopConnectionState.SUCCESS
    assert format_latency(path_2.proxy_rtt_ms) == "48 ms"
    assert format_speed(client.state.rx_rate_bps) == "2.00 MB/s"
    assert format_speed(client.state.tx_rate_bps) == "1.00 MB/s"
    assert format_uptime(client.state.snapshot.uptime_ms) == "00:00:03"

    # 3. Third stage: Stream becomes stale, latency is withheld, hops degrade
    client._update_state(is_stale=True)
    path_3 = map_network_path(app_state, client.state)

    assert path_3.proxy_rtt_ms is None
    assert format_latency(path_3.proxy_rtt_ms) == "—"
    assert path_3.hops[1].connection_state == HopConnectionState.CONNECTING
    assert path_3.hops[2].connection_state == HopConnectionState.UNAVAILABLE
