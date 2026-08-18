from __future__ import annotations

import json
import time

from neko_launcher.application.ports import EventPublisher
from neko_launcher.domain.events import Event, TelemetryUpdated
from neko_launcher.domain.telemetry import (
    TelemetryConnectionState,
)
from neko_launcher.infrastructure.core.core_telemetry_client import (
    NamedPipeCoreTelemetryClient,
)


class MockEventPublisher(EventPublisher):
    def __init__(self) -> None:
        self.events: list[Event] = []

    def publish(self, event: Event) -> None:
        self.events.append(event)


def test_handle_frame_valid_snapshot() -> None:
    pub = MockEventPublisher()
    client = NamedPipeCoreTelemetryClient(pub)

    frame = json.dumps(
        {
            "schema_version": 1,
            "sequence": 101,
            "timestamp_utc": "2026-08-17T02:30:15.123Z",
            "message_type": "core.health.snapshot",
            "component": "core",
            "payload": {
                "core_state": "running",
                "proxy_state": "connected",
                "uptime_ms": 5000,
                "tcp_connect_total": 10,
                "tcp_active": 2,
                "tcp_closed_total": 8,
                "udp_event_total": 20,
                "dns_query_total": 15,
                "dns_failure_total": 0,
                "redirect_success_total": 10,
                "redirect_failure_total": 0,
                "rx_bytes": 10000,
                "tx_bytes": 5000,
                "network_error_total": 0,
                "v2ray_running": True,
                "local_socks_running": True,
                "shadowsocks_connected": True,
                "dropped_telemetry_events": 0,
            },
        }
    )

    client._handle_frame(frame, timestamp=100.0)
    assert client.state.snapshot.core_state == "running"
    assert client.state.snapshot.proxy_state == "connected"
    assert client.state.snapshot.rx_bytes == 10000
    assert client.state.snapshot.tx_bytes == 5000
    assert client.state.snapshot.v2ray_running is True
    assert client.state.last_sequence == 101
    assert client.state.is_stale is False
    assert client.state.schema_incompatible is False
    assert len(pub.events) == 1
    assert isinstance(pub.events[0], TelemetryUpdated)


def test_handle_frame_unknown_additive_fields_lenient() -> None:
    pub = MockEventPublisher()
    client = NamedPipeCoreTelemetryClient(pub)

    frame = json.dumps(
        {
            "schema_version": 1,
            "sequence": 102,
            "timestamp_utc": "2026-08-17T02:30:16.123Z",
            "message_type": "core.health.snapshot",
            "component": "core",
            "unknown_envelope_field": "test",
            "payload": {
                "core_state": "running",
                "proxy_state": "connected",
                "rx_bytes": 20000,
                "tx_bytes": 10000,
                "future_additive_counter": 9999,
                "future_feature_flag": True,
            },
        }
    )

    client._handle_frame(frame, timestamp=101.0)
    assert client.state.snapshot.core_state == "running"
    assert client.state.snapshot.rx_bytes == 20000
    assert client.state.last_sequence == 102
    assert client.state.parse_error_count == 0


def test_handle_frame_malformed_json() -> None:
    pub = MockEventPublisher()
    client = NamedPipeCoreTelemetryClient(pub)

    client._handle_frame("invalid json { [", timestamp=100.0)
    assert client.state.parse_error_count == 1

    client._handle_frame('"just a string"', timestamp=100.0)
    assert client.state.parse_error_count == 2


def test_handle_frame_unsupported_schema_version() -> None:
    pub = MockEventPublisher()
    client = NamedPipeCoreTelemetryClient(pub)

    frame = json.dumps(
        {
            "schema_version": 99,
            "sequence": 1,
            "message_type": "core.health.snapshot",
            "component": "core",
            "payload": {},
        }
    )

    client._handle_frame(frame, timestamp=100.0)
    assert client.state.schema_incompatible is True


def test_single_consumer_thread_invariant() -> None:
    pub = MockEventPublisher()
    client = NamedPipeCoreTelemetryClient(pub, pipe_path=r"\\.\pipe\NonExistentTestPipe")

    client.start()
    t1 = client._thread
    assert t1 is not None and t1.is_alive()

    # Calling start() again must not spawn a second thread
    client.start()
    t2 = client._thread
    assert t1 is t2

    client.stop(timeout=1.0)
    assert client._thread is None


def test_core_absent_does_not_crash_launcher() -> None:
    pub = MockEventPublisher()
    client = NamedPipeCoreTelemetryClient(
        pub,
        pipe_path=r"\\.\pipe\NonExistentCoreTelemetryPipe_9999",
    )

    client.start()
    time.sleep(0.1)
    assert client.state.connection_state == TelemetryConnectionState.DISCONNECTED
    client.stop(timeout=1.0)


def test_client_is_strictly_read_only() -> None:
    # NamedPipeCoreTelemetryClient opens pipe with "rb" mode
    pub = MockEventPublisher()
    client = NamedPipeCoreTelemetryClient(pub)
    assert not hasattr(client, "write")
    assert not hasattr(client, "send")
    assert not hasattr(client, "send_command")
