#!/usr/bin/env python3
"""
Unit Test Suite for Unified AWS Lightsail Discord Worker (Phase T7 V1B)
"""

from __future__ import annotations

import json
import os
import socket
import struct
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime
from unittest.mock import MagicMock, patch

# Import from parent directory
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from neko_discord_worker import (
    ETH_P_ALL,
    PACKET_OUTGOING,
    DEFAULT_PROXY_PORT,
    DEFAULT_ALERT_COOLDOWN_SECONDS,
    DEFAULT_STALE_AFTER_SECONDS,
    DEFAULT_TRAFFIC_MIN_REPORT_BYTES,
    TrafficSample,
    HealthSnapshot,
    WorkerState,
    StatusStateMachine,
    DiscordTransport,
    UnifiedDiscordWorker,
    parse_packet,
    format_bps,
    format_bytes,
    format_uptime,
    format_thai_period,
    get_timezone,
    derive_health_status,
    build_current_status_payload,
    build_traffic_summary_payload,
    build_alert_payload,
    load_state,
    save_state_atomic,
)


def _build_synthetic_ipv4_packet(
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
    protocol: int,
    payload_len: int = 100,
) -> bytes:
    """Construct a synthetic raw Ethernet + IPv4 + TCP/UDP frame."""
    # Ethernet Header (14 bytes): Dst MAC (6), Src MAC (6), EtherType 0x0800 (2)
    eth_header = b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\x08\x00"

    # IP Header (20 bytes)
    ip_ver_ihl = (4 << 4) | 5
    total_len = 20 + 20 + payload_len  # 20 IP + 20 Transport + payload
    src_ip_bytes = socket.inet_aton(src_ip)
    dst_ip_bytes = socket.inet_aton(dst_ip)
    ip_header = struct.pack(
        "!BBHHHBBH4s4s",
        ip_ver_ihl,
        0,
        total_len,
        54321,
        0,
        64,
        protocol,
        0,  # checksum
        src_ip_bytes,
        dst_ip_bytes,
    )

    # Transport Header (20 bytes for TCP, 8 for UDP)
    if protocol == 6:  # TCP
        transport_header = struct.pack(
            "!HHLLBBHHH",
            src_port,
            dst_port,
            1000,
            0,
            (5 << 4),
            2,
            65535,
            0,
            0,
        )
    else:  # UDP
        transport_header = struct.pack(
            "!HHHH",
            src_port,
            dst_port,
            8 + payload_len,
            0,
        )

    payload = b"\x00" * payload_len
    return eth_header + ip_header + transport_header + payload


class TestPacketParsingAndFiltering(unittest.TestCase):
    def test_tcp_inbound_upload(self):
        # Inbound packet to destination port 8388 (PACKET_HOST = 0)
        pkt = _build_synthetic_ipv4_packet("192.168.1.50", "172.26.29.162", 45678, 8388, protocol=6, payload_len=500)
        sample = parse_packet(pkt, packet_type=0, monitor_port=8388)
        self.assertIsNotNone(sample)
        self.assertEqual(sample.direction, "in")
        self.assertEqual(sample.byte_count, 20 + 20 + 500)

    def test_tcp_outbound_download(self):
        # Outbound packet from source port 8388 (PACKET_OUTGOING = 4)
        pkt = _build_synthetic_ipv4_packet("172.26.29.162", "192.168.1.50", 8388, 45678, protocol=6, payload_len=1000)
        sample = parse_packet(pkt, packet_type=PACKET_OUTGOING, monitor_port=8388)
        self.assertIsNotNone(sample)
        self.assertEqual(sample.direction, "out")
        self.assertEqual(sample.byte_count, 20 + 20 + 1000)

    def test_udp_inbound_upload(self):
        # Inbound UDP packet to port 8388
        pkt = _build_synthetic_ipv4_packet("192.168.1.50", "172.26.29.162", 55555, 8388, protocol=17, payload_len=250)
        sample = parse_packet(pkt, packet_type=0, monitor_port=8388)
        self.assertIsNotNone(sample)
        self.assertEqual(sample.direction, "in")

    def test_udp_outbound_download(self):
        # Outbound UDP packet from port 8388
        pkt = _build_synthetic_ipv4_packet("172.26.29.162", "192.168.1.50", 8388, 55555, protocol=17, payload_len=300)
        sample = parse_packet(pkt, packet_type=PACKET_OUTGOING, monitor_port=8388)
        self.assertIsNotNone(sample)
        self.assertEqual(sample.direction, "out")

    def test_non_8388_traffic_ignored(self):
        # SSH port 22 or HTTPS port 443
        pkt = _build_synthetic_ipv4_packet("192.168.1.50", "172.26.29.162", 12345, 22, protocol=6, payload_len=100)
        sample = parse_packet(pkt, packet_type=0, monitor_port=8388)
        self.assertIsNone(sample)

    def test_malformed_packets_handled_safely(self):
        # Truncated frames
        self.assertIsNone(parse_packet(b"", packet_type=0, monitor_port=8388))
        self.assertIsNone(parse_packet(b"\x00" * 10, packet_type=0, monitor_port=8388))
        self.assertIsNone(parse_packet(b"\x00" * 30, packet_type=0, monitor_port=8388))


class TestUnitConversionsAndFormatting(unittest.TestCase):
    def test_format_bps(self):
        self.assertEqual(format_bps(0), "0 bps")
        self.assertEqual(format_bps(850), "850 bps")
        self.assertEqual(format_bps(1_500), "1.50 Kbps")
        self.assertEqual(format_bps(12_840_000), "12.84 Mbps")
        self.assertEqual(format_bps(2_500_000_000), "2.50 Gbps")

    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1024), "1.00 KB")
        self.assertEqual(format_bytes(1048576 * 10), "10.00 MB")
        self.assertEqual(format_bytes(1073741824 * 5), "5.00 GB")

    def test_format_uptime(self):
        self.assertEqual(format_uptime(300), "5m")
        self.assertEqual(format_uptime(7200), "2h 0m")
        self.assertEqual(format_uptime(86400 * 9 + 3600 * 14), "9d 14h")

    def test_format_thai_period(self):
        tz = get_timezone("Asia/Bangkok")
        start = datetime(2026, 8, 18, 13, 0, tzinfo=tz)
        end = datetime(2026, 8, 18, 13, 30, tzinfo=tz)
        period = format_thai_period(start, end)
        self.assertIn("18 สิงหาคม 2569", period)
        self.assertIn("13:00–13:30 น.", period)


class TestStatusModelAndDerivation(unittest.TestCase):
    def test_online_status(self):
        now = 100.0
        snap = HealthSnapshot(
            timestamp_mono=98.0,
            timestamp_epoch=1755518400.0,
            service_ok=True,
            service_status="active",
            listener_ok=True,
            listener_status="Listening",
            probe_ok=True,
            ping_ms=1.8,
            packet_loss_percent=0.0,
            uptime_seconds=3600,
        )
        self.assertEqual(derive_health_status(snap, now), "ONLINE")

    def test_degraded_service_or_listener(self):
        now = 100.0
        # Service failed
        snap1 = HealthSnapshot(
            timestamp_mono=98.0,
            timestamp_epoch=1755518400.0,
            service_ok=False,
            service_status="inactive",
            listener_ok=True,
            listener_status="Listening",
            probe_ok=True,
            ping_ms=1.8,
            packet_loss_percent=0.0,
            uptime_seconds=3600,
        )
        self.assertEqual(derive_health_status(snap1, now), "DEGRADED")

        # Listener closed
        snap2 = HealthSnapshot(
            timestamp_mono=98.0,
            timestamp_epoch=1755518400.0,
            service_ok=True,
            service_status="active",
            listener_ok=False,
            listener_status="Closed",
            probe_ok=True,
            ping_ms=1.8,
            packet_loss_percent=0.0,
            uptime_seconds=3600,
        )
        self.assertEqual(derive_health_status(snap2, now), "DEGRADED")

    def test_stale_status_when_sample_age_exceeds_threshold(self):
        now = 150.0  # 50s after sample
        snap = HealthSnapshot(
            timestamp_mono=100.0,
            timestamp_epoch=1755518400.0,
            service_ok=True,
            service_status="active",
            listener_ok=True,
            listener_status="Listening",
            probe_ok=True,
            ping_ms=1.8,
            packet_loss_percent=0.0,
            uptime_seconds=3600,
        )
        # Snapshot is older than 30s -> STALE
        self.assertEqual(derive_health_status(snap, now, stale_after_seconds=30.0), "STALE")

    def test_unknown_when_no_snapshot(self):
        self.assertEqual(derive_health_status(None, 100.0), "UNKNOWN")


class TestStatusStateMachineAndAntiFlap(unittest.TestCase):
    def test_first_run_no_alert(self):
        sm = StatusStateMachine()
        decision = sm.update("ONLINE", now_mono=100.0)
        self.assertFalse(decision.send_alert)
        self.assertEqual(sm.confirmed_status, "ONLINE")

    def test_anti_flap_degraded_confirmation(self):
        sm = StatusStateMachine(confirmed_status="ONLINE")
        # Sample 1: First unhealthy sample -> Pending only
        d1 = sm.update("DEGRADED", now_mono=105.0)
        self.assertFalse(d1.send_alert)
        self.assertEqual(sm.confirmed_status, "ONLINE")
        self.assertEqual(sm.pending_count, 1)

        # Sample 2: Second consecutive unhealthy sample -> Alert confirmed!
        d2 = sm.update("DEGRADED", now_mono=110.0, reason="Listener Closed")
        self.assertTrue(d2.send_alert)
        self.assertEqual(d2.alert_type, "DEGRADED")
        self.assertEqual(sm.confirmed_status, "DEGRADED")

        # Sample 3: Subsequent sample in DEGRADED -> No duplicate alert
        d3 = sm.update("DEGRADED", now_mono=115.0)
        self.assertFalse(d3.send_alert)

    def test_anti_flap_recovery_confirmation(self):
        sm = StatusStateMachine(confirmed_status="DEGRADED", last_alert_status="DEGRADED", last_alert_at=100.0)
        # Sample 1: First healthy sample -> Pending only
        d1 = sm.update("ONLINE", now_mono=105.0)
        self.assertFalse(d1.send_alert)
        self.assertEqual(sm.confirmed_status, "DEGRADED")

        # Sample 2: Second healthy sample -> Recovery alert confirmed!
        d2 = sm.update("ONLINE", now_mono=110.0)
        self.assertTrue(d2.send_alert)
        self.assertEqual(d2.alert_type, "RECOVERY")
        self.assertEqual(sm.confirmed_status, "ONLINE")

    def test_alert_cooldown_suppression(self):
        sm = StatusStateMachine(confirmed_status="ONLINE", cooldown_seconds=300.0)
        # Transition to DEGRADED
        sm.update("DEGRADED", now_mono=105.0)
        d = sm.update("DEGRADED", now_mono=110.0)
        self.assertTrue(d.send_alert)

        # Transition to ONLINE then rapidly back to DEGRADED within 300s
        sm.confirmed_status = "ONLINE"
        sm.update("DEGRADED", now_mono=150.0)
        d_rapid = sm.update("DEGRADED", now_mono=155.0)
        # Alert should be suppressed by cooldown
        self.assertFalse(d_rapid.send_alert)


class TestStatePersistence(unittest.TestCase):
    def test_save_and_load_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "discord-state.json")
            state = WorkerState(
                version=1,
                status_message_id="123456789",
                window_start_time=1755518400,
                window_inbound_bytes=5000,
                window_outbound_bytes=15000,
                confirmed_status="ONLINE",
            )
            saved = save_state_atomic(state, state_file)
            self.assertTrue(saved)
            self.assertTrue(os.path.exists(state_file))

            loaded = load_state(state_file)
            self.assertEqual(loaded.status_message_id, "123456789")
            self.assertEqual(loaded.window_inbound_bytes, 5000)
            self.assertEqual(loaded.window_outbound_bytes, 15000)
            self.assertEqual(loaded.confirmed_status, "ONLINE")

    def test_corrupt_state_fallback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "corrupt.json")
            with open(state_file, "w", encoding="utf-8") as f:
                f.write("{invalid_json: true")

            loaded = load_state(state_file)
            self.assertEqual(loaded.confirmed_status, "UNKNOWN")
            self.assertIsNone(loaded.status_message_id)


class TestDiscordPayloads(unittest.TestCase):
    def test_current_status_payload(self):
        snap = HealthSnapshot(
            timestamp_mono=100.0,
            timestamp_epoch=1755518400.0,
            service_ok=True,
            service_status="active",
            listener_ok=True,
            listener_status="Listening",
            probe_ok=True,
            ping_ms=1.8,
            packet_loss_percent=0.0,
            uptime_seconds=3600,
        )
        payload = build_current_status_payload("ONLINE", snap, download_bps=12_840_000, upload_bps=2_110_000)
        self.assertEqual(payload["username"], "Neko Family Proxy")
        embed = payload["embeds"][0]
        self.assertIn("NEKO PROXY — CURRENT STATUS", embed["title"])

        field_names = [f["name"] for f in embed["fields"]]
        self.assertIn("Status", field_names)
        self.assertIn("Ping", field_names)
        self.assertIn("↓ VPS Speed", field_names)
        self.assertIn("Host Uptime", field_names)
        self.assertNotIn("Active Users", field_names)  # Strict privacy invariant

    def test_traffic_summary_payload(self):
        payload = build_traffic_summary_payload(
            start_epoch=1755518400,
            end_epoch=1755520200,
            inbound_bytes=40_500_000,
            outbound_bytes=319_500_000,
            elapsed_seconds=1800.0,
            status="ONLINE",
            uptime_seconds=86400 * 9,
            timezone_name="Asia/Bangkok",
        )
        embed = payload["embeds"][0]
        self.assertIn("TRAFFIC SUMMARY", embed["title"])
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        self.assertIn("⬇️ ดาวน์โหลด (เฉลี่ย)", fields)
        self.assertIn("⬆️ อัปโหลด (เฉลี่ย)", fields)
        self.assertIn("1.42 Mbps", fields["⬇️ ดาวน์โหลด (เฉลี่ย)"])  # 319.5MB * 8 / 1800s ≈ 1.42 Mbps


class TestDiscordTransportMocks(unittest.TestCase):
    def test_post_message_success(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"id": "987654321"}).encode("utf-8")
        mock_urlopen = MagicMock(return_value=mock_resp)
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        transport = DiscordTransport("https://fake.discord.webhook", request_fn=mock_urlopen)
        success, msg_id = transport.post_message({"content": "test"}, wait=True)
        self.assertTrue(success)
        self.assertEqual(msg_id, "987654321")

    def test_edit_message_404_handling(self):
        http_error = urllib.error.HTTPError(
            url="https://fake.discord.webhook/messages/123",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None,
        )
        mock_urlopen = MagicMock(side_effect=http_error)
        transport = DiscordTransport("https://fake.discord.webhook", request_fn=mock_urlopen)
        success, err = transport.edit_message("123", {"content": "test"})
        self.assertFalse(success)
        self.assertEqual(err, "404")

    @patch("time.sleep", return_value=None)
    def test_rate_limit_429_retry(self, mock_sleep):
        http_error_429 = urllib.error.HTTPError(
            url="https://fake.discord.webhook",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=None,
        )
        http_error_429.read = MagicMock(return_value=b'{"retry_after": 0.5}')

        mock_resp_200 = MagicMock()
        mock_resp_200.status = 200
        mock_resp_200.read.return_value = json.dumps({"id": "111222333"}).encode("utf-8")
        mock_resp_200.__enter__.return_value = mock_resp_200
        mock_resp_200.__exit__.return_value = None

        # First call fails with 429, second succeeds with 200
        mock_urlopen = MagicMock(side_effect=[http_error_429, mock_resp_200])
        transport = DiscordTransport("https://fake.discord.webhook", request_fn=mock_urlopen)
        success, msg_id = transport.post_message({"content": "rate_limited_then_ok"}, wait=True)
        self.assertTrue(success)
        self.assertEqual(msg_id, "111222333")
        self.assertEqual(mock_sleep.call_count, 1)

    @patch("time.sleep", return_value=None)
    def test_server_error_500_retry(self, mock_sleep):
        http_error_500 = urllib.error.HTTPError(
            url="https://fake.discord.webhook",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None,
        )
        mock_urlopen = MagicMock(side_effect=[http_error_500, http_error_500])
        transport = DiscordTransport("https://fake.discord.webhook", request_fn=mock_urlopen)
        success, err = transport.post_message({"content": "server_error"}, wait=False)
        self.assertFalse(success)
        self.assertEqual(err, "500")
        self.assertEqual(mock_sleep.call_count, 1)  # Retried once


class TestTrafficSummaryThresholdsAndWorkerSimulation(unittest.TestCase):
    def test_summary_threshold_evaluation(self):
        # 1 MiB threshold = 1,048,576 bytes
        # Total bytes < 1 MiB -> Below threshold
        total_below = 500_000 + 400_000
        self.assertLess(total_below, DEFAULT_TRAFFIC_MIN_REPORT_BYTES)

        # Total bytes >= 1 MiB -> Eligible
        total_above = 600_000 + 500_000
        self.assertGreaterEqual(total_above, DEFAULT_TRAFFIC_MIN_REPORT_BYTES)

    def test_time_weighted_average_varying_duration(self):
        # 100 MB outbound (800 Mb) in 900 seconds (15 min) -> 800 / 900 ≈ 0.888 Mbps
        bytes_out = 100 * 1024 * 1024
        elapsed = 900.0
        avg_bps = (bytes_out * 8) / elapsed
        self.assertAlmostEqual(avg_bps, 932067.555, delta=1.0)
        formatted = format_bps(avg_bps)
        self.assertIn("932.07 Kbps", formatted)

    def test_worker_simulation_flow(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "test-state.json")
            mock_transport = MagicMock()
            mock_transport.post_message.return_value = (True, "mock_status_msg_id_123")
            mock_transport.edit_message.return_value = (True, None)

            worker = UnifiedDiscordWorker(
                webhook_url="https://fake.discord.webhook",
                state_path=state_file,
                transport=mock_transport,
                health_interval=5.0,
                status_interval=60.0,
                summary_interval=1800,
                min_report_bytes=1000,
            )

            # Mock health snapshot
            worker.latest_health = HealthSnapshot(
                timestamp_mono=100.0,
                timestamp_epoch=1755518400.0,
                service_ok=True,
                service_status="active",
                listener_ok=True,
                listener_status="Listening",
                probe_ok=True,
                ping_ms=1.5,
                packet_loss_percent=0.0,
                uptime_seconds=5000,
            )

            # Simulate initial status message creation
            worker.tick_status_message(now_mono=100.0)
            self.assertEqual(worker.state.status_message_id, "mock_status_msg_id_123")
            mock_transport.post_message.assert_called()

            # Simulate status edit on next tick
            worker.tick_status_message(now_mono=160.0)
            mock_transport.edit_message.assert_called_with("mock_status_msg_id_123", unittest.mock.ANY)

            # Simulate traffic accumulation and summary post
            worker.window_inbound_bytes = 20_000
            worker.window_outbound_bytes = 80_000
            worker.tick_traffic_summary(now_epoch=1755520200, now_mono=1900.0)

            # Window reset verified
            self.assertEqual(worker.window_inbound_bytes, 0)
            self.assertEqual(worker.window_outbound_bytes, 0)
            self.assertEqual(worker.state.window_start_time, 1755520200)


if __name__ == "__main__":
    unittest.main()
