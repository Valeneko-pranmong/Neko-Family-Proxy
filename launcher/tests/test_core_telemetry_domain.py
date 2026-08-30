from __future__ import annotations

from neko_launcher.domain.telemetry import (
    CoreHealthSnapshot,
    TelemetryConnectionState,
    TelemetryRateCalculator,
    TelemetryState,
    format_bytes,
    format_speed,
    format_uptime,
)


def test_core_health_snapshot_from_dict_complete() -> None:
    data = {
        "core_state": "running",
        "proxy_state": "connected",
        "uptime_ms": 125000,
        "tcp_connect_total": 412,
        "tcp_active": 8,
        "tcp_closed_total": 404,
        "udp_event_total": 95,
        "dns_query_total": 64,
        "dns_failure_total": 0,
        "redirect_success_total": 412,
        "redirect_failure_total": 0,
        "rx_bytes": 154820912,
        "tx_bytes": 12490184,
        "network_error_total": 0,
        "v2ray_running": True,
        "local_socks_running": True,
        "shadowsocks_connected": True,
        "dropped_telemetry_events": 0,
    }
    snapshot = CoreHealthSnapshot.from_dict(data)
    assert snapshot.core_state == "running"
    assert snapshot.proxy_state == "connected"
    assert snapshot.uptime_ms == 125000
    assert snapshot.tcp_connect_total == 412
    assert snapshot.tcp_active == 8
    assert snapshot.tcp_closed_total == 404
    assert snapshot.udp_event_total == 95
    assert snapshot.dns_query_total == 64
    assert snapshot.dns_failure_total == 0
    assert snapshot.redirect_success_total == 412
    assert snapshot.redirect_failure_total == 0
    assert snapshot.rx_bytes == 154820912
    assert snapshot.tx_bytes == 12490184
    assert snapshot.network_error_total == 0
    assert snapshot.v2ray_running is True
    assert snapshot.local_socks_running is True
    assert snapshot.shadowsocks_connected is True
    assert snapshot.dropped_telemetry_events == 0
    assert snapshot.proxy_rtt_ms is None


def test_core_health_snapshot_from_dict_defaults_on_missing_fields() -> None:
    snapshot = CoreHealthSnapshot.from_dict({})
    assert snapshot.core_state == "stopped"
    assert snapshot.proxy_state == "disconnected"
    assert snapshot.uptime_ms == 0
    assert snapshot.tcp_connect_total == 0
    assert snapshot.tcp_active == 0
    assert snapshot.rx_bytes == 0
    assert snapshot.tx_bytes == 0
    assert snapshot.v2ray_running is False
    assert snapshot.local_socks_running is False
    assert snapshot.shadowsocks_connected is False
    assert snapshot.proxy_rtt_ms is None


def test_core_health_snapshot_from_dict_proxy_rtt_ms_cases() -> None:
    # 1. missing field -> None
    assert CoreHealthSnapshot.from_dict({}).proxy_rtt_ms is None

    # 2. explicit null -> None
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": None}).proxy_rtt_ms is None

    # 3. 0 -> 0
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": 0}).proxy_rtt_ms == 0

    # 4. positive integer -> positive integer
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": 42}).proxy_rtt_ms == 42

    # 5. negative integer -> None (normalize/reject invalid RTT, safe from NetworkPath ValueError)
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": -1}).proxy_rtt_ms is None
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": -100}).proxy_rtt_ms is None

    # 6. wrong type / non-integer -> None (no float/string coercion)
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": "42"}).proxy_rtt_ms is None
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": 42.5}).proxy_rtt_ms is None
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": True}).proxy_rtt_ms is None
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": False}).proxy_rtt_ms is None
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": []}).proxy_rtt_ms is None
    assert CoreHealthSnapshot.from_dict({"proxy_rtt_ms": {}}).proxy_rtt_ms is None



def test_telemetry_state_health_mapping() -> None:
    # Disconnected state is not healthy
    s0 = TelemetryState(connection_state=TelemetryConnectionState.DISCONNECTED)
    assert s0.is_healthy is False
    assert s0.is_degraded is False

    # Fully healthy connected state
    snap_healthy = CoreHealthSnapshot(
        core_state="running",
        proxy_state="connected",
        v2ray_running=True,
        local_socks_running=True,
        shadowsocks_connected=True,
    )
    s1 = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=snap_healthy,
        is_stale=False,
    )
    assert s1.is_healthy is True
    assert s1.is_degraded is False

    # Degraded state: core running but upstream disconnected
    snap_degraded = CoreHealthSnapshot(
        core_state="running",
        proxy_state="connected",
        v2ray_running=True,
        local_socks_running=True,
        shadowsocks_connected=False,
    )
    s2 = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=snap_degraded,
        is_stale=False,
    )
    assert s2.is_healthy is False
    assert s2.is_degraded is True

    # Stale telemetry is neither healthy nor degraded
    s3 = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=snap_healthy,
        is_stale=True,
    )
    assert s3.is_healthy is False
    assert s3.is_degraded is False


def test_rate_calculator_initial_baseline() -> None:
    calc = TelemetryRateCalculator()
    rx_rate, tx_rate = calc.calculate_rates(
        rx_bytes=1000,
        tx_bytes=500,
        timestamp=100.0,
        sequence=1,
    )
    assert rx_rate == 0.0
    assert tx_rate == 0.0


def test_rate_calculator_non_1_second_interval() -> None:
    calc = TelemetryRateCalculator()
    calc.calculate_rates(rx_bytes=1000, tx_bytes=500, timestamp=100.0, sequence=1)

    # 0.5s later, +5000 bytes rx, +2500 bytes tx
    rx_rate, tx_rate = calc.calculate_rates(
        rx_bytes=6000,
        tx_bytes=3000,
        timestamp=100.5,
        sequence=2,
    )
    assert rx_rate == 10000.0  # 5000 / 0.5 = 10000 B/s
    assert tx_rate == 5000.0   # 2500 / 0.5 = 5000 B/s

    # 1.25s later, +2500 bytes rx, +1250 bytes tx
    rx_rate2, tx_rate2 = calc.calculate_rates(
        rx_bytes=8500,
        tx_bytes=4250,
        timestamp=101.75,
        sequence=3,
    )
    assert rx_rate2 == 2000.0  # 2500 / 1.25 = 2000 B/s
    assert tx_rate2 == 1000.0  # 1250 / 1.25 = 1000 B/s


def test_rate_calculator_counter_reset_no_negative_rates() -> None:
    calc = TelemetryRateCalculator()
    calc.calculate_rates(rx_bytes=100000, tx_bytes=50000, timestamp=100.0, sequence=1)
    calc.calculate_rates(rx_bytes=110000, tx_bytes=55000, timestamp=101.0, sequence=2)

    # Core session resets counters to 0
    rx_rate, tx_rate = calc.calculate_rates(
        rx_bytes=500,
        tx_bytes=200,
        timestamp=102.0,
        sequence=3,
    )
    assert rx_rate == 0.0
    assert tx_rate == 0.0

    # Subsequent update from new baseline produces valid positive rate
    rx_rate2, tx_rate2 = calc.calculate_rates(
        rx_bytes=1500,
        tx_bytes=700,
        timestamp=103.0,
        sequence=4,
    )
    assert rx_rate2 == 1000.0
    assert tx_rate2 == 500.0


def test_rate_calculator_sequence_regression_resets_baseline() -> None:
    calc = TelemetryRateCalculator()
    calc.calculate_rates(rx_bytes=1000, tx_bytes=500, timestamp=100.0, sequence=50)

    # New core starts at sequence 1
    rx_rate, tx_rate = calc.calculate_rates(
        rx_bytes=2000,
        tx_bytes=1000,
        timestamp=101.0,
        sequence=1,
    )
    assert rx_rate == 0.0
    assert tx_rate == 0.0


def test_rate_calculator_zero_or_negative_elapsed_protection() -> None:
    calc = TelemetryRateCalculator()
    calc.calculate_rates(rx_bytes=1000, tx_bytes=500, timestamp=100.0, sequence=1)

    # Identical timestamp (elapsed = 0)
    rx_rate, tx_rate = calc.calculate_rates(
        rx_bytes=2000,
        tx_bytes=1000,
        timestamp=100.0,
        sequence=2,
    )
    assert rx_rate == 0.0
    assert tx_rate == 0.0

    # Negative timestamp jump (elapsed < 0)
    rx_rate2, tx_rate2 = calc.calculate_rates(
        rx_bytes=3000,
        tx_bytes=1500,
        timestamp=99.0,
        sequence=3,
    )
    assert rx_rate2 == 0.0
    assert tx_rate2 == 0.0


def test_rate_calculator_large_64bit_counters() -> None:
    calc = TelemetryRateCalculator()
    large_base = 10_000_000_000_000  # 10 TB
    calc.calculate_rates(
        rx_bytes=large_base,
        tx_bytes=large_base,
        timestamp=100.0,
        sequence=1,
    )

    # +10 MB in 1.0 second
    rx_rate, tx_rate = calc.calculate_rates(
        rx_bytes=large_base + 10_485_760,
        tx_bytes=large_base + 5_242_880,
        timestamp=101.0,
        sequence=2,
    )
    assert rx_rate == 10_485_760.0
    assert tx_rate == 5_242_880.0


def test_format_bytes() -> None:
    assert format_bytes(-5) == "0 B"
    assert format_bytes(0) == "0 B"
    assert format_bytes(512) == "512 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(1024 * 1024) == "1.0 MB"
    assert format_bytes(50 * 1024 * 1024) == "50.0 MB"
    assert format_bytes(2 * 1024 * 1024 * 1024) == "2.00 GB"


def test_format_speed() -> None:
    assert format_speed(-10.0) == "0 B/s"
    assert format_speed(0.0) == "0 B/s"
    assert format_speed(500.0) == "500 B/s"
    assert format_speed(1024.0) == "1.0 KB/s"
    assert format_speed(150_000.0) == "146.5 KB/s"
    assert format_speed(2_500_000.0) == "2.38 MB/s"


def test_format_uptime() -> None:
    assert format_uptime(-1) == "00:00:00"
    assert format_uptime(0) == "00:00:00"
    assert format_uptime(5000) == "00:00:05"
    assert format_uptime(65000) == "00:01:05"
    assert format_uptime(3665000) == "01:01:05"
    assert format_uptime(86400000) == "24:00:00"


def test_format_latency() -> None:
    from neko_launcher.domain.telemetry import format_latency

    assert format_latency(None) == "—"
    assert format_latency(0) == "0 ms"
    assert format_latency(38) == "38 ms"
    assert format_latency(150) == "150 ms"
    assert format_latency(-1) == "—"
    assert format_latency(-100) == "—"
