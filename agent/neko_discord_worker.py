#!/usr/bin/env python3
"""
Neko Family Proxy — Unified AWS Lightsail Discord Worker (Phase T7 V1)

Responsibilities:
1. Continuously collect proxy traffic on Shadowsocks port 8388 via AF_PACKET raw socket.
2. Maintain near-realtime proxy throughput rate.
3. Sample local host and proxy service health (systemd, port 8388 listener, upstream ping, uptime).
4. Maintain a single persistent Current Status message on Discord (edited in-place every ~60s).
5. Post 30-minute epoch-aligned Traffic Summary messages reporting time-weighted average throughput.
6. Post discrete state-transition alerts (ONLINE -> DEGRADED/STALE, RECOVERY) with 2-sample anti-flap and 300s cooldown.
7. Persist minimal operational state locally in /var/lib/neko/discord-state.json (atomic write, 0600).

Strict Invariants:
- Local-only execution on AWS Lightsail Japan VPS. Zero Vercel Cron, zero Supabase/Backend dependencies.
- Zero Active Users or client session tracking.
- Zero packet payload capture, logging, or storage. Headers only for port 8388 classification.
- Discord delivery failures are completely isolated and never interrupt packet capture or local monitoring.
"""

from __future__ import annotations

import dataclasses
import json
import os
import queue
import select
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# Packet Parsing & Traffic Definitions
# -----------------------------------------------------------------------------
ETH_P_ALL = 0x0003
PACKET_OUTGOING = 4
VLAN_TYPES = {0x8100, 0x88A8, 0x9100}
IP_PROTOCOL_TCP = 6
IP_PROTOCOL_UDP = 17

DEFAULT_PROXY_PORT = 8388
DEFAULT_NETWORK_INTERFACE = "ens5"
DEFAULT_PING_TARGET = "1.1.1.1"
DEFAULT_SHADOWSOCKS_SERVICE = "shadowsocks-libev.service"

DEFAULT_HEALTH_SAMPLE_SECONDS = 5.0
DEFAULT_CURRENT_RATE_SAMPLE_SECONDS = 5.0
DEFAULT_STATUS_UPDATE_SECONDS = 60.0
DEFAULT_TRAFFIC_SUMMARY_SECONDS = 1800  # 30 minutes
DEFAULT_TRAFFIC_MIN_REPORT_BYTES = 1048576  # 1 MiB
DEFAULT_STALE_AFTER_SECONDS = 30.0
DEFAULT_ALERT_COOLDOWN_SECONDS = 300.0  # 5 minutes
DEFAULT_STATE_CHECKPOINT_SECONDS = 60.0

DEFAULT_TIMEZONE = "Asia/Bangkok"
DEFAULT_STATE_PATH = "/var/lib/neko/discord-state.json"

THAI_MONTHS = (
    "",
    "มกราคม",
    "กุมภาพันธ์",
    "มีนาคม",
    "เมษายน",
    "พฤษภาคม",
    "มิถุนายน",
    "กรกฎาคม",
    "สิงหาคม",
    "กันยายน",
    "ตุลาคม",
    "พฤศจิกายน",
    "ธันวาคม",
)


@dataclass(frozen=True)
class TrafficSample:
    direction: str  # "in" (Upload to VPS) or "out" (Download from VPS)
    byte_count: int


def _transport_ports(packet: bytes, offset: int) -> tuple[int, int] | None:
    if len(packet) < offset + 4:
        return None
    return struct.unpack_from("!HH", packet, offset)


def parse_packet(packet: bytes, packet_type: int, monitor_port: int) -> TrafficSample | None:
    """
    Parse an Ethernet frame and extract traffic sample for monitor_port (TCP/UDP).
    Download (from client perspective): Outbound packets from source port == monitor_port.
    Upload (from client perspective): Inbound packets to destination port == monitor_port.
    Non-monitor_port traffic and malformed frames return None.
    """
    if len(packet) < 14:
        return None

    ether_type = struct.unpack_from("!H", packet, 12)[0]
    network_offset = 14
    while ether_type in VLAN_TYPES:
        if len(packet) < network_offset + 4:
            return None
        ether_type = struct.unpack_from("!H", packet, network_offset + 2)[0]
        network_offset += 4

    if ether_type == 0x0800:
        # IPv4
        if len(packet) < network_offset + 20:
            return None
        version_ihl = packet[network_offset]
        if version_ihl >> 4 != 4:
            return None
        header_length = (version_ihl & 0x0F) * 4
        if header_length < 20 or len(packet) < network_offset + header_length:
            return None
        total_length = struct.unpack_from("!H", packet, network_offset + 2)[0]
        fragment = struct.unpack_from("!H", packet, network_offset + 6)[0]
        if fragment & 0x1FFF:  # Fragmented packet offset > 0
            return None
        protocol = packet[network_offset + 9]
        ports = _transport_ports(packet, network_offset + header_length)
        byte_count = min(total_length, max(0, len(packet) - network_offset))
    elif ether_type == 0x86DD:
        # IPv6
        if len(packet) < network_offset + 40 or packet[network_offset] >> 4 != 6:
            return None
        payload_length = struct.unpack_from("!H", packet, network_offset + 4)[0]
        protocol = packet[network_offset + 6]
        transport_offset = network_offset + 40

        while protocol in (0, 43, 60):  # Hop-by-Hop, Routing, Destination options
            if len(packet) < transport_offset + 2:
                return None
            next_protocol = packet[transport_offset]
            extension_length = (packet[transport_offset + 1] + 1) * 8
            transport_offset += extension_length
            protocol = next_protocol

        if protocol == 44:  # Fragment header
            if len(packet) < transport_offset + 8:
                return None
            fragment_offset = struct.unpack_from("!H", packet, transport_offset + 2)[0]
            if fragment_offset & 0xFFF8:
                return None
            protocol = packet[transport_offset]
            transport_offset += 8

        ports = _transport_ports(packet, transport_offset)
        byte_count = min(40 + payload_length, max(0, len(packet) - network_offset))
    else:
        return None

    if protocol not in (IP_PROTOCOL_TCP, IP_PROTOCOL_UDP) or ports is None:
        return None

    source_port, destination_port = ports
    # Outbound packet from monitor_port (VPS -> Client) = Download
    if packet_type == PACKET_OUTGOING and source_port == monitor_port:
        return TrafficSample("out", byte_count)
    # Inbound packet to monitor_port (Client -> VPS) = Upload
    if packet_type != PACKET_OUTGOING and destination_port == monitor_port:
        return TrafficSample("in", byte_count)

    return None


# -----------------------------------------------------------------------------
# Unit Formatting Utilities
# -----------------------------------------------------------------------------
def format_bps(bps: float) -> str:
    """Format bits-per-second into human-readable SI rate (bps, Kbps, Mbps, Gbps)."""
    if bps < 0:
        return "0 bps"
    if bps < 1_000:
        return f"{int(bps):,} bps"
    if bps < 1_000_000:
        return f"{bps / 1_000:,.2f} Kbps"
    if bps < 1_000_000_000:
        return f"{bps / 1_000_000:,.2f} Mbps"
    return f"{bps / 1_000_000_000:,.2f} Gbps"


def format_bytes(value: int) -> str:
    """Format bytes into binary IEC units (B, KB, MB, GB, TB)."""
    if value < 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount):,} {unit}"
            return f"{amount:,.2f} {unit}"
        amount /= 1024
    return f"{amount:,.2f} TB"


def format_uptime(seconds: int) -> str:
    """Format uptime seconds into human-readable string (e.g. '9d 14h', '3h 22m', '45m')."""
    if seconds < 0:
        return "0m"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_thai_period(start: datetime, end: datetime) -> str:
    """Format reporting period with Thai date and Buddhist Era year."""
    start_date = f"{start.day} {THAI_MONTHS[start.month]} {start.year + 543}"
    if start.date() == end.date():
        return f"{start_date} เวลา {start:%H:%M}–{end:%H:%M} น."
    end_date = f"{end.day} {THAI_MONTHS[end.month]} {end.year + 543}"
    return f"{start_date} เวลา {start:%H:%M} น. – {end_date} เวลา {end:%H:%M} น."


# -----------------------------------------------------------------------------
# Local Health Probes
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class HealthSnapshot:
    timestamp_mono: float
    timestamp_epoch: float
    service_ok: bool
    service_status: str
    listener_ok: bool
    listener_status: str
    probe_ok: bool
    ping_ms: float | None
    packet_loss_percent: float | None
    uptime_seconds: int


def probe_service_status(service_name: str = DEFAULT_SHADOWSOCKS_SERVICE) -> tuple[bool, str]:
    """Check systemd unit state for Shadowsocks."""
    try:
        res = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        status = res.stdout.strip()
        return (status == "active", status if status else "unknown")
    except Exception:
        return (False, "error")


def probe_listener_status(port: int = DEFAULT_PROXY_PORT) -> tuple[bool, str]:
    """Check whether local TCP listener on proxy port is accepting connections."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return (True, "Listening")
    except ConnectionRefusedError:
        return (False, "Closed")
    except Exception as e:
        return (False, f"Error: {e.__class__.__name__}")


def probe_upstream_ping(target: str = DEFAULT_PING_TARGET) -> tuple[bool, float | None, float | None]:
    """
    Probe upstream target latency (ms) and packet loss (%).
    Uses a small 3-packet ICMP ping with bounded timeout.
    """
    try:
        res = subprocess.run(
            ["ping", "-c", "3", "-W", "1", target],
            capture_output=True,
            text=True,
            timeout=3.5,
            check=False,
        )
        if res.returncode != 0 and not res.stdout:
            return (False, None, 100.0)

        loss_percent = None
        ping_ms = None
        for line in res.stdout.splitlines():
            if "packet loss" in line:
                parts = line.split(",")
                for p in parts:
                    if "packet loss" in p:
                        loss_str = p.replace("% packet loss", "").strip()
                        loss_percent = float(loss_str)
            if "rtt min/avg/max" in line or "round-trip min/avg/max" in line:
                stats = line.split("=")[1].strip().split("/")[1]
                ping_ms = float(stats)

        probe_ok = (loss_percent is not None and loss_percent < 100.0)
        return (probe_ok, ping_ms, loss_percent)
    except Exception:
        return (False, None, None)


def read_host_uptime() -> int:
    """Read host uptime seconds from /proc/uptime."""
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            return int(float(f.readline().split()[0]))
    except Exception:
        return 0


def collect_health_snapshot(
    service_name: str = DEFAULT_SHADOWSOCKS_SERVICE,
    proxy_port: int = DEFAULT_PROXY_PORT,
    ping_target: str = DEFAULT_PING_TARGET,
) -> HealthSnapshot:
    """Collect an instantaneous health snapshot from local authorities."""
    now_mono = time.monotonic()
    now_epoch = time.time()
    service_ok, service_status = probe_service_status(service_name)
    listener_ok, listener_status = probe_listener_status(proxy_port)
    probe_ok, ping_ms, packet_loss = probe_upstream_ping(ping_target)
    uptime_sec = read_host_uptime()
    return HealthSnapshot(
        timestamp_mono=now_mono,
        timestamp_epoch=now_epoch,
        service_ok=service_ok,
        service_status=service_status,
        listener_ok=listener_ok,
        listener_status=listener_status,
        probe_ok=probe_ok,
        ping_ms=ping_ms,
        packet_loss_percent=packet_loss,
        uptime_seconds=uptime_sec,
    )


# -----------------------------------------------------------------------------
# Status Derivation & State Machine
# -----------------------------------------------------------------------------
def derive_health_status(
    snapshot: HealthSnapshot | None,
    now_mono: float,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
) -> str:
    """
    Derive 4-tier health state: ONLINE, DEGRADED, STALE, UNKNOWN.
    STALE != OFFLINE invariant strictly enforced.
    """
    if snapshot is None:
        return "UNKNOWN"
    if (now_mono - snapshot.timestamp_mono) > stale_after_seconds:
        return "STALE"
    if snapshot.service_ok and snapshot.listener_ok and snapshot.probe_ok:
        return "ONLINE"
    return "DEGRADED"


@dataclass
class AlertDecision:
    send_alert: bool
    alert_type: str | None  # "DEGRADED", "STALE", "RECOVERY"
    old_status: str
    new_status: str
    reason: str


class StatusStateMachine:
    """
    Anti-flap state machine with 2-sample confirmation, 300s alert cooldown,
    and first-run baseline safety.
    """

    def __init__(
        self,
        confirmed_status: str = "UNKNOWN",
        last_alert_status: str | None = None,
        last_alert_at: float | None = None,
        cooldown_seconds: float = DEFAULT_ALERT_COOLDOWN_SECONDS,
    ):
        self.confirmed_status = confirmed_status
        self.pending_status: str | None = None
        self.pending_count: int = 0
        self.last_alert_status = last_alert_status
        self.last_alert_at = last_alert_at
        self.cooldown_seconds = cooldown_seconds
        self.initialized = (confirmed_status != "UNKNOWN")

    def update(
        self,
        evaluated_status: str,
        now_mono: float,
        reason: str = "",
    ) -> AlertDecision:
        # First clean run establishes baseline without alerting
        if not self.initialized:
            self.confirmed_status = evaluated_status
            self.last_alert_status = evaluated_status
            self.last_alert_at = now_mono
            self.initialized = True
            return AlertDecision(False, None, "UNKNOWN", evaluated_status, "Initial baseline established")

        if evaluated_status == self.confirmed_status:
            self.pending_status = None
            self.pending_count = 0
            return AlertDecision(False, None, self.confirmed_status, evaluated_status, "Status unchanged")

        # Track multi-sample pending transitions
        if self.pending_status == evaluated_status:
            self.pending_count += 1
        else:
            self.pending_status = evaluated_status
            self.pending_count = 1

        # Anti-flap confirmation rules:
        # - STALE: Immediate transition if snapshot is stale
        # - DEGRADED / ONLINE / UNKNOWN: 2 consecutive samples
        required_samples = 1 if evaluated_status == "STALE" else 2

        if self.pending_count < required_samples:
            return AlertDecision(
                False,
                None,
                self.confirmed_status,
                evaluated_status,
                f"Pending confirmation ({self.pending_count}/{required_samples})",
            )

        # Transition Confirmed!
        old_status = self.confirmed_status
        new_status = evaluated_status
        self.confirmed_status = new_status
        self.pending_status = None
        self.pending_count = 0

        # Determine Alert Type
        alert_type: str | None = None
        if new_status == "ONLINE" and old_status in ("DEGRADED", "STALE"):
            alert_type = "RECOVERY"
        elif new_status == "DEGRADED":
            alert_type = "DEGRADED"
        elif new_status == "STALE":
            alert_type = "STALE"

        if alert_type is None:
            return AlertDecision(False, None, old_status, new_status, "Transition confirmed without alert rule")

        # Cooldown check:
        # Recovery alerts are ALWAYS allowed.
        # Non-recovery alerts are suppressed if within cooldown and same as last alert status.
        if alert_type != "RECOVERY":
            if (
                self.last_alert_status == new_status
                and self.last_alert_at is not None
                and (now_mono - self.last_alert_at) < self.cooldown_seconds
            ):
                return AlertDecision(
                    False,
                    alert_type,
                    old_status,
                    new_status,
                    f"Alert suppressed by {self.cooldown_seconds}s cooldown",
                )

        self.last_alert_status = new_status
        self.last_alert_at = now_mono
        return AlertDecision(True, alert_type, old_status, new_status, reason)


# -----------------------------------------------------------------------------
# Local Persistent State Management
# -----------------------------------------------------------------------------
@dataclass
class WorkerState:
    version: int = 1
    status_message_id: str | None = None
    window_start_time: int = 0
    window_inbound_bytes: int = 0
    window_outbound_bytes: int = 0
    confirmed_status: str = "UNKNOWN"
    pending_status: str | None = None
    pending_count: int = 0
    last_alert_status: str | None = None
    last_alert_at: float | None = None
    last_status_edit_at: float | None = None
    last_checkpoint_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerState:
        return cls(
            version=int(data.get("version", 1)),
            status_message_id=data.get("status_message_id"),
            window_start_time=int(data.get("window_start_time", 0)),
            window_inbound_bytes=int(data.get("window_inbound_bytes", 0)),
            window_outbound_bytes=int(data.get("window_outbound_bytes", 0)),
            confirmed_status=str(data.get("confirmed_status", "UNKNOWN")),
            pending_status=data.get("pending_status"),
            pending_count=int(data.get("pending_count", 0)),
            last_alert_status=data.get("last_alert_status"),
            last_alert_at=float(data["last_alert_at"]) if data.get("last_alert_at") is not None else None,
            last_status_edit_at=float(data["last_status_edit_at"]) if data.get("last_status_edit_at") is not None else None,
            last_checkpoint_at=float(data.get("last_checkpoint_at", 0.0)),
        )


def load_state(state_path: str) -> WorkerState:
    """Load persistent worker state with corrupt file fallback."""
    if not os.path.exists(state_path):
        return WorkerState()
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return WorkerState.from_dict(data)
    except Exception as e:
        _safe_log("STATE_LOAD_FAILED_FALLBACK", reason=str(e))
    return WorkerState()


def save_state_atomic(state: WorkerState, state_path: str) -> bool:
    """Save state atomically using temporary file and atomic rename."""
    try:
        dir_name = os.path.dirname(state_path)
        if dir_name:
            os.makedirs(dir_name, mode=0o700, exist_ok=True)

        state.last_checkpoint_at = time.time()
        payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)

        fd, temp_file_path = tempfile.mkstemp(
            prefix="discord-state-",
            suffix=".tmp",
            dir=dir_name if dir_name else None,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())

        # Set 0600 permissions
        try:
            os.chmod(temp_file_path, 0o600)
        except OSError:
            pass

        os.replace(temp_file_path, state_path)
        return True
    except Exception as e:
        _safe_log("STATE_SAVE_FAILED", reason=str(e))
        return False


# -----------------------------------------------------------------------------
# Discord Embed Builders & Transport
# -----------------------------------------------------------------------------
def build_current_status_payload(
    status: str,
    snapshot: HealthSnapshot,
    download_bps: float,
    upload_bps: float,
) -> dict[str, Any]:
    """Build the persistent Current Status Discord embed."""
    status_indicator = {
        "ONLINE": "🟢 ONLINE",
        "DEGRADED": "🟡 DEGRADED",
        "STALE": "🟠 STALE",
        "UNKNOWN": "⚪ UNKNOWN",
    }.get(status, f"⚪ {status}")

    color = {
        "ONLINE": 0x2ECC71,   # Green
        "DEGRADED": 0xF1C40F, # Yellow
        "STALE": 0xE67E22,    # Orange
        "UNKNOWN": 0x95A5A6,  # Grey
    }.get(status, 0x95A5A6)

    ping_str = f"{snapshot.ping_ms:.1f} ms" if snapshot.ping_ms is not None else "—"
    loss_str = f"{snapshot.packet_loss_percent:.1f}%" if snapshot.packet_loss_percent is not None else "—"

    fields = [
        {"name": "Status", "value": f"**{status_indicator}**", "inline": True},
        {"name": "Ping", "value": ping_str, "inline": True},
        {"name": "Loss", "value": loss_str, "inline": True},
        {"name": "↓ VPS Speed", "value": f"**{format_bps(download_bps)}**", "inline": True},
        {"name": "↑ VPS Speed", "value": f"**{format_bps(upload_bps)}**", "inline": True},
        {"name": "Host Uptime", "value": format_uptime(snapshot.uptime_seconds), "inline": True},
        {"name": "Shadowsocks", "value": snapshot.service_status.capitalize(), "inline": True},
        {"name": "Listener", "value": snapshot.listener_status, "inline": True},
        {"name": "Probe Target", "value": "VPS → Upstream", "inline": True},
    ]

    return {
        "username": "Neko Family Proxy",
        "allowed_mentions": {"parse": []},  # Disable mass mentions
        "embeds": [
            {
                "title": "🌐 NEKO PROXY — CURRENT STATUS",
                "color": color,
                "fields": fields,
                "timestamp": datetime.fromtimestamp(snapshot.timestamp_epoch, datetime_timezone.utc).isoformat(),
                "footer": {"text": "Updated automatically every ~60s | AWS Lightsail JP"},
            }
        ],
    }


def get_timezone(timezone_name: str) -> datetime_timezone:
    """Get timezone with fallback for environments lacking system tzdata."""
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        if timezone_name in ("Asia/Bangkok", "Asia/Jakarta", "ICT", "GMT+7", "UTC+7"):
            from datetime import timedelta
            return datetime_timezone(timedelta(hours=7), name="ICT")
        return datetime_timezone.utc


def build_traffic_summary_payload(
    start_epoch: int,
    end_epoch: int,
    inbound_bytes: int,
    outbound_bytes: int,
    elapsed_seconds: float,
    status: str,
    uptime_seconds: int,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """
    Build the 30-minute Traffic Summary Discord embed.
    Primary: Time-weighted average throughput (bps).
    Secondary: Cumulative window total bytes (MB/GB).
    """
    tz = get_timezone(timezone_name)
    start_dt = datetime.fromtimestamp(start_epoch, tz)
    end_dt = datetime.fromtimestamp(end_epoch, tz)
    period = format_thai_period(start_dt, end_dt)

    safe_elapsed = max(1.0, elapsed_seconds)
    download_avg_bps = (outbound_bytes * 8) / safe_elapsed
    upload_avg_bps = (inbound_bytes * 8) / safe_elapsed

    status_indicator = {
        "ONLINE": "🟢 ONLINE",
        "DEGRADED": "🟡 DEGRADED",
        "STALE": "🟠 STALE",
    }.get(status, f"⚪ {status}")

    return {
        "username": "Neko Family Proxy",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "📊 NEKO PROXY — TRAFFIC SUMMARY",
                "description": f"ช่วงเวลา: **{period}** (เวลาไทย)",
                "color": 0x2F81F7,
                "fields": [
                    {
                        "name": "⬇️ ดาวน์โหลด (เฉลี่ย)",
                        "value": f"**{format_bps(download_avg_bps)}**\n*(รวม {format_bytes(outbound_bytes)})*",
                        "inline": True,
                    },
                    {
                        "name": "⬆️ อัปโหลด (เฉลี่ย)",
                        "value": f"**{format_bps(upload_avg_bps)}**\n*(รวม {format_bytes(inbound_bytes)})*",
                        "inline": True,
                    },
                    {
                        "name": "⚙️ ข้อมูลโฮสต์",
                        "value": f"สถานะ: **{status_indicator}**\nUptime: **{format_uptime(uptime_seconds)}**",
                        "inline": False,
                    },
                ],
                "timestamp": datetime.fromtimestamp(end_epoch, datetime_timezone.utc).isoformat(),
                "footer": {"text": f"Measured across {safe_elapsed:.1f}s actual elapsed time"},
            }
        ],
    }


def build_alert_payload(
    alert_type: str,
    old_status: str,
    new_status: str,
    reason: str,
    snapshot: HealthSnapshot | None,
) -> dict[str, Any]:
    """Build discrete transition alert embed (DEGRADED, STALE, RECOVERY)."""
    now_epoch = snapshot.timestamp_epoch if snapshot else time.time()

    if alert_type == "RECOVERY":
        title = "✅ NEKO SERVER RECOVERED"
        color = 0x2ECC71
        description = f"Status restored from **{old_status}** to **ONLINE**.\nProxy service and local listeners are operating normally."
    elif alert_type == "DEGRADED":
        title = "⚠️ NEKO SERVER DEGRADED"
        color = 0xF1C40F
        description = f"Status transitioned from **{old_status}** to **DEGRADED**.\nReason: {reason}"
    else:  # STALE
        title = "⏱️ NEKO PROBE STALE"
        color = 0xE67E22
        description = f"Status transitioned from **{old_status}** to **STALE**.\nReason: {reason}\n*Note: Proxy traffic routing is not independently proven offline.*"

    fields = []
    if snapshot:
        fields.append({"name": "Shadowsocks Service", "value": snapshot.service_status.capitalize(), "inline": True})
        fields.append({"name": "Listener", "value": snapshot.listener_status, "inline": True})
        if snapshot.ping_ms is not None:
            fields.append({"name": "Upstream Ping", "value": f"{snapshot.ping_ms:.1f} ms", "inline": True})

    return {
        "username": "Neko Family Proxy",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "fields": fields,
                "timestamp": datetime.fromtimestamp(now_epoch, datetime_timezone.utc).isoformat(),
                "footer": {"text": "Alert triggered upon confirmed state transition"},
            }
        ],
    }


def _safe_log(event: str, **fields: Any) -> None:
    """Log events cleanly without exposing secrets."""
    details = " | ".join(f"{k}={v}" for k, v in fields.items())
    print(f"[{datetime.now(datetime_timezone.utc):%Y-%m-%d %H:%M:%S UTC}] {event} | {details}" if details else f"[{datetime.now(datetime_timezone.utc):%Y-%m-%d %H:%M:%S UTC}] {event}", flush=True)


class DiscordTransport:
    """
    Bounded Discord webhook HTTP transport with retry, rate limit handling,
    and failure isolation.
    """

    def __init__(self, webhook_url: str, request_fn: Callable[..., Any] | None = None):
        self.webhook_url = webhook_url.rstrip("/")
        self._request_fn = request_fn or urllib.request.urlopen

    def post_message(self, payload: dict[str, Any], wait: bool = False) -> tuple[bool, str | None]:
        """POST a new message to Discord webhook. Returns (success, message_id)."""
        url = f"{self.webhook_url}?wait=true" if wait else self.webhook_url
        return self._send("POST", url, payload)

    def edit_message(self, message_id: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
        """PATCH an existing message by ID. Returns (success, status_or_error)."""
        url = f"{self.webhook_url}/messages/{message_id}"
        return self._send("PATCH", url, payload)

    def _send(self, method: str, url: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "NekoDiscordWorker/1.0",
            },
            method=method,
        )

        for attempt in range(2):  # Max 1 immediate retry
            try:
                with self._request_fn(req, timeout=10.0) as resp:
                    resp_body = resp.read().decode("utf-8", errors="replace")
                    message_id = None
                    if resp_body:
                        try:
                            parsed = json.loads(resp_body)
                            if isinstance(parsed, dict):
                                message_id = str(parsed.get("id")) if parsed.get("id") else None
                        except Exception:
                            pass
                    return (200 <= resp.status < 300, message_id)
            except urllib.error.HTTPError as error:
                status_code = error.code
                if status_code == 404:
                    _safe_log("DISCORD_HTTP_404_NOT_FOUND", method=method)
                    return (False, "404")
                if status_code == 429:
                    # Rate limit handling
                    retry_after = 2.0
                    try:
                        err_body = error.read().decode("utf-8", errors="replace")
                        err_json = json.loads(err_body)
                        retry_after = min(5.0, float(err_json.get("retry_after", 2.0)))
                    except Exception:
                        pass
                    _safe_log("DISCORD_RATE_LIMITED", retry_after=retry_after, attempt=attempt)
                    if attempt == 0:
                        time.sleep(retry_after)
                        continue
                    return (False, "429")
                if 500 <= status_code < 600:
                    _safe_log("DISCORD_SERVER_ERROR", status=status_code, attempt=attempt)
                    if attempt == 0:
                        time.sleep(2.0)
                        continue
                    return (False, str(status_code))

                _safe_log("DISCORD_CLIENT_ERROR", status=status_code)
                return (False, str(status_code))
            except (urllib.error.URLError, TimeoutError, OSError) as net_err:
                _safe_log("DISCORD_NETWORK_ERROR", reason=net_err.__class__.__name__, attempt=attempt)
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                return (False, "network_error")

        return (False, "retries_exhausted")


# -----------------------------------------------------------------------------
# Unified Discord Worker Daemon
# -----------------------------------------------------------------------------
class UnifiedDiscordWorker:
    """
    Continuous packet sniffer and scheduler managing:
    - Packet filtering on port 8388
    - Instantaneous rate deltas
    - Persistent current status updates (~60s)
    - 30-minute epoch-aligned summary messages
    - Anti-flap transition alerts
    """

    def __init__(
        self,
        webhook_url: str,
        interface: str = DEFAULT_NETWORK_INTERFACE,
        proxy_port: int = DEFAULT_PROXY_PORT,
        ping_target: str = DEFAULT_PING_TARGET,
        shadowsocks_service: str = DEFAULT_SHADOWSOCKS_SERVICE,
        state_path: str = DEFAULT_STATE_PATH,
        health_interval: float = DEFAULT_HEALTH_SAMPLE_SECONDS,
        status_interval: float = DEFAULT_STATUS_UPDATE_SECONDS,
        summary_interval: int = DEFAULT_TRAFFIC_SUMMARY_SECONDS,
        min_report_bytes: int = DEFAULT_TRAFFIC_MIN_REPORT_BYTES,
        stale_after: float = DEFAULT_STALE_AFTER_SECONDS,
        alert_cooldown: float = DEFAULT_ALERT_COOLDOWN_SECONDS,
        timezone_name: str = DEFAULT_TIMEZONE,
        transport: DiscordTransport | None = None,
    ):
        self.webhook_url = webhook_url
        self.interface = interface
        self.proxy_port = proxy_port
        self.ping_target = ping_target
        self.shadowsocks_service = shadowsocks_service
        self.state_path = state_path
        self.health_interval = health_interval
        self.status_interval = status_interval
        self.summary_interval = summary_interval
        self.min_report_bytes = min_report_bytes
        self.stale_after = stale_after
        self.alert_cooldown = alert_cooldown
        self.timezone_name = timezone_name

        self.transport = transport or DiscordTransport(webhook_url)

        # Persistent State
        self.state = load_state(self.state_path)

        # In-memory traffic window counters
        self.window_inbound_bytes = self.state.window_inbound_bytes
        self.window_outbound_bytes = self.state.window_outbound_bytes

        # Timing baselines
        now_epoch = int(time.time())
        now_mono = time.monotonic()

        if self.state.window_start_time <= 0 or self.state.window_start_time > now_epoch:
            self.state.window_start_time = now_epoch
            self.window_inbound_bytes = 0
            self.window_outbound_bytes = 0

        self.window_start_mono = now_mono

        # Rate calculation baselines
        self.prev_rate_inbound = self.window_inbound_bytes
        self.prev_rate_outbound = self.window_outbound_bytes
        self.prev_rate_mono = now_mono
        self.current_download_bps = 0.0
        self.current_upload_bps = 0.0

        # Health & State Machine
        self.latest_health: HealthSnapshot | None = None
        self.state_machine = StatusStateMachine(
            confirmed_status=self.state.confirmed_status,
            last_alert_status=self.state.last_alert_status,
            last_alert_at=self.state.last_alert_at,
            cooldown_seconds=self.alert_cooldown,
        )

        # Next Cadence Deadlines (Monotonic)
        self.next_health_mono = now_mono
        self.next_status_mono = now_mono + 5.0  # Initial status update after 5s
        self.next_checkpoint_mono = now_mono + DEFAULT_STATE_CHECKPOINT_SECONDS

        # Next epoch summary boundary
        self.next_summary_epoch = ((now_epoch // self.summary_interval) + 1) * self.summary_interval

        self.running = False
        self.packet_socket: socket.socket | None = None

    def _sync_state(self) -> None:
        """Sync in-memory worker variables to persistent WorkerState object."""
        self.state.window_inbound_bytes = self.window_inbound_bytes
        self.state.window_outbound_bytes = self.window_outbound_bytes
        self.state.confirmed_status = self.state_machine.confirmed_status
        self.state.pending_status = self.state_machine.pending_status
        self.state.pending_count = self.state_machine.pending_count
        self.state.last_alert_status = self.state_machine.last_alert_status
        self.state.last_alert_at = self.state_machine.last_alert_at

    def checkpoint_state(self) -> None:
        """Persist state to disk."""
        self._sync_state()
        save_state_atomic(self.state, self.state_path)

    def tick_health_and_rates(self, now_mono: float) -> None:
        """Execute health sample, current rate derivation, and alert evaluation."""
        self.latest_health = collect_health_snapshot(
            self.shadowsocks_service,
            self.proxy_port,
            self.ping_target,
        )

        # Update Current Throughput Rates
        elapsed_rate = max(0.001, now_mono - self.prev_rate_mono)
        delta_in = max(0, self.window_inbound_bytes - self.prev_rate_inbound)
        delta_out = max(0, self.window_outbound_bytes - self.prev_rate_outbound)

        self.current_upload_bps = (delta_in * 8) / elapsed_rate
        self.current_download_bps = (delta_out * 8) / elapsed_rate

        self.prev_rate_inbound = self.window_inbound_bytes
        self.prev_rate_outbound = self.window_outbound_bytes
        self.prev_rate_mono = now_mono

        # Evaluate Health State & Transition Alerts
        evaluated_status = derive_health_status(self.latest_health, now_mono, self.stale_after)
        reason = ""
        if evaluated_status == "DEGRADED":
            if not self.latest_health.service_ok:
                reason = f"Service {self.shadowsocks_service} is {self.latest_health.service_status}"
            elif not self.latest_health.listener_ok:
                reason = f"Listener port {self.proxy_port} is {self.latest_health.listener_status}"
            elif not self.latest_health.probe_ok:
                reason = "Upstream ping probe timeout or 100% loss"
        elif evaluated_status == "STALE":
            reason = "No fresh health samples received within tolerance"

        alert_dec = self.state_machine.update(evaluated_status, now_mono, reason)
        if alert_dec.send_alert and alert_dec.alert_type:
            _safe_log("SENDING_ALERT", alert_type=alert_dec.alert_type, old=alert_dec.old_status, new=alert_dec.new_status)
            payload = build_alert_payload(
                alert_dec.alert_type,
                alert_dec.old_status,
                alert_dec.new_status,
                alert_dec.reason,
                self.latest_health,
            )
            success, _ = self.transport.post_message(payload, wait=False)
            if success:
                _safe_log("ALERT_SENT", alert_type=alert_dec.alert_type)
            self.checkpoint_state()

        self.next_health_mono = now_mono + self.health_interval

    def tick_status_message(self, now_mono: float) -> None:
        """Edit or create the persistent Current Status Discord message."""
        if self.latest_health is None:
            return

        status = self.state_machine.confirmed_status
        payload = build_current_status_payload(
            status,
            self.latest_health,
            self.current_download_bps,
            self.current_upload_bps,
        )

        msg_id = self.state.status_message_id
        if not msg_id:
            _safe_log("CREATING_PERSISTENT_STATUS_MESSAGE")
            success, new_id = self.transport.post_message(payload, wait=True)
            if success and new_id:
                self.state.status_message_id = new_id
                self.state.last_status_edit_at = time.time()
                _safe_log("PERSISTENT_STATUS_MESSAGE_CREATED", message_id=new_id)
                self.checkpoint_state()
        else:
            success, err = self.transport.edit_message(msg_id, payload)
            if success:
                self.state.last_status_edit_at = time.time()
            elif err == "404":
                _safe_log("STATUS_MESSAGE_404_RESETTING_ID")
                self.state.status_message_id = None
                self.checkpoint_state()

        self.next_status_mono = now_mono + self.status_interval

    def tick_traffic_summary(self, now_epoch: int, now_mono: float) -> None:
        """Process 30-minute epoch-aligned Traffic Summary."""
        start_epoch = self.state.window_start_time
        end_epoch = now_epoch
        actual_elapsed = max(1.0, now_mono - self.window_start_mono)

        inbound = self.window_inbound_bytes
        outbound = self.window_outbound_bytes
        total_bytes = inbound + outbound

        if total_bytes >= self.min_report_bytes:
            _safe_log("POSTING_TRAFFIC_SUMMARY", total_bytes=total_bytes, elapsed=actual_elapsed)
            payload = build_traffic_summary_payload(
                start_epoch=start_epoch,
                end_epoch=end_epoch,
                inbound_bytes=inbound,
                outbound_bytes=outbound,
                elapsed_seconds=actual_elapsed,
                status=self.state_machine.confirmed_status,
                uptime_seconds=self.latest_health.uptime_seconds if self.latest_health else 0,
                timezone_name=self.timezone_name,
            )
            success, _ = self.transport.post_message(payload, wait=False)
            if success:
                _safe_log("TRAFFIC_SUMMARY_SENT", start=start_epoch, end=end_epoch)
        else:
            _safe_log(
                "TRAFFIC_SUMMARY_SKIPPED_BELOW_THRESHOLD",
                total_bytes=total_bytes,
                min_bytes=self.min_report_bytes,
            )

        # Start new window
        self.state.window_start_time = end_epoch
        self.window_start_mono = now_mono
        self.window_inbound_bytes = 0
        self.window_outbound_bytes = 0
        self.prev_rate_inbound = 0
        self.prev_rate_outbound = 0
        self.next_summary_epoch = ((now_epoch // self.summary_interval) + 1) * self.summary_interval
        self.checkpoint_state()

    def run(self) -> None:
        """Main event loop with bounded select() on AF_PACKET socket."""
        _safe_log("STARTING_DISCORD_WORKER", interface=self.interface, port=self.proxy_port)

        try:
            self.packet_socket = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
            self.packet_socket.bind((self.interface, 0))
            self.packet_socket.setblocking(False)
        except PermissionError:
            raise SystemExit("ERROR: CAP_NET_RAW or root privilege required for AF_PACKET raw socket.")
        except Exception as e:
            raise SystemExit(f"ERROR: Failed to bind socket on {self.interface}: {e}")

        self.running = True
        _safe_log("DISCORD_WORKER_READY", next_summary_epoch=self.next_summary_epoch)

        try:
            while self.running:
                now_mono = time.monotonic()
                now_epoch = int(time.time())

                # 1. Health & Current Rate Tick
                if now_mono >= self.next_health_mono:
                    self.tick_health_and_rates(now_mono)

                # 2. Status Message Edit Tick
                if now_mono >= self.next_status_mono:
                    self.tick_status_message(now_mono)

                # 3. Traffic Summary Epoch Tick
                if now_epoch >= self.next_summary_epoch:
                    self.tick_traffic_summary(now_epoch, now_mono)

                # 4. State Checkpoint Tick
                if now_mono >= self.next_checkpoint_mono:
                    self.checkpoint_state()
                    self.next_checkpoint_mono = now_mono + DEFAULT_STATE_CHECKPOINT_SECONDS

                # 5. Compute timeout to next deadline
                timeout = max(
                    0.0,
                    min(
                        1.0,
                        self.next_health_mono - now_mono,
                        self.next_status_mono - now_mono,
                        float(max(0, self.next_summary_epoch - now_epoch)),
                    ),
                )

                # 6. Wait for packets or timeout
                readable, _, _ = select.select([self.packet_socket], [], [], timeout)
                if readable and self.packet_socket:
                    try:
                        packet, address = self.packet_socket.recvfrom(65535)
                        packet_type = address[2]
                        sample = parse_packet(packet, packet_type, self.proxy_port)
                        if sample is not None:
                            if sample.direction == "in":
                                self.window_inbound_bytes += sample.byte_count
                            else:
                                self.window_outbound_bytes += sample.byte_count
                    except BlockingIOError:
                        pass
                    except OSError:
                        pass
        finally:
            self.checkpoint_state()
            if self.packet_socket:
                self.packet_socket.close()


# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------
def main() -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url or not webhook_url.startswith("https://"):
        raise SystemExit("CONFIGURATION_ERROR: Valid DISCORD_WEBHOOK_URL starting with https:// is required.")

    interface = os.environ.get("NETWORK_INTERFACE", DEFAULT_NETWORK_INTERFACE).strip()
    proxy_port = int(os.environ.get("PROXY_PORT", str(DEFAULT_PROXY_PORT)))
    ping_target = os.environ.get("PING_TARGET", DEFAULT_PING_TARGET).strip()
    shadowsocks_service = os.environ.get("SHADOWSOCKS_SERVICE", DEFAULT_SHADOWSOCKS_SERVICE).strip()
    state_path = os.environ.get("STATE_PATH", DEFAULT_STATE_PATH).strip()

    health_interval = float(os.environ.get("HEALTH_SAMPLE_SECONDS", str(DEFAULT_HEALTH_SAMPLE_SECONDS)))
    status_interval = float(os.environ.get("STATUS_UPDATE_SECONDS", str(DEFAULT_STATUS_UPDATE_SECONDS)))
    summary_interval = int(os.environ.get("TRAFFIC_SUMMARY_SECONDS", str(DEFAULT_TRAFFIC_SUMMARY_SECONDS)))
    min_report_bytes = int(os.environ.get("TRAFFIC_MIN_REPORT_BYTES", str(DEFAULT_TRAFFIC_MIN_REPORT_BYTES)))
    stale_after = float(os.environ.get("STALE_AFTER_SECONDS", str(DEFAULT_STALE_AFTER_SECONDS)))
    alert_cooldown = float(os.environ.get("ALERT_COOLDOWN_SECONDS", str(DEFAULT_ALERT_COOLDOWN_SECONDS)))
    timezone_name = os.environ.get("MONITOR_TIMEZONE", DEFAULT_TIMEZONE).strip()

    worker = UnifiedDiscordWorker(
        webhook_url=webhook_url,
        interface=interface,
        proxy_port=proxy_port,
        ping_target=ping_target,
        shadowsocks_service=shadowsocks_service,
        state_path=state_path,
        health_interval=health_interval,
        status_interval=status_interval,
        summary_interval=summary_interval,
        min_report_bytes=min_report_bytes,
        stale_after=stale_after,
        alert_cooldown=alert_cooldown,
        timezone_name=timezone_name,
    )

    worker.run()


if __name__ == "__main__":
    main()
