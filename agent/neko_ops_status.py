#!/usr/bin/env python3
"""
Neko Family Proxy — Production Operations & Health Diagnostics (Phase T8)

Single, zero-dependency, read-only operator diagnostic command.
Provides a sanitized operational summary of host resources, service lifecycles,
network listeners, persistent state integrity, and journal storage.

Strict Invariants:
- 100% Read-Only: NEVER mutates state, restarts services, deletes logs, or modifies files.
- Zero Secrets: NEVER prints or reads secret tokens, passwords, or webhook URLs.
- Zero User Data: NEVER queries database, Supabase, or client session identities.
- Bounded Execution: All probes and subprocesses have strict timeouts (<= 3.0s).

Exit Codes:
  0 = HEALTHY  (All core services active, listener 8388 open, legacy inactive, state valid, disk < 80%)
  1 = DEGRADED (Service inactive, listener closed, legacy active, state corrupt, disk >= 80%)
  2 = ERROR    (Tool error or unhandled environment failure)
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_PROXY_PORT = 8388
DEFAULT_STATE_PATH = "/var/lib/neko/discord-state.json"
DEFAULT_STATE_DIR = "/var/lib/neko"


@dataclass
class ServiceInfo:
    name: str
    active_state: str  # "active", "inactive", "failed", "unknown", "permission_denied"
    unit_file_state: str  # "enabled", "disabled", "unknown"
    pid: int | None
    restarts: int | None
    memory_bytes: int | None


@dataclass
class HostInfo:
    hostname: str
    os_release: str
    kernel: str
    uptime_seconds: int
    load_avg: tuple[float, float, float]
    mem_total_bytes: int
    mem_available_bytes: int
    mem_used_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    disk_free_bytes: int
    disk_used_percent: float
    inode_used_percent: float | None
    journal_usage_str: str


@dataclass
class StateInfo:
    path: str
    exists: bool
    size_bytes: int | None
    mode_octal: str | None
    owner_uid: int | None
    json_valid: bool
    confirmed_status: str | None
    has_status_message_id: bool
    last_checkpoint_epoch: float | None
    orphan_temp_count: int


# -----------------------------------------------------------------------------
# Host Probing
# -----------------------------------------------------------------------------
def get_host_info(disk_path: str = "/", journal_cmd: bool = True) -> HostInfo:
    """Collect host baseline metrics safely."""
    hostname = platform.node() or "unknown"
    kernel = platform.release() or "unknown"
    os_release = "Linux"

    if os.path.exists("/etc/os-release"):
        try:
            with open("/etc/os-release", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        os_release = line.split("=", 1)[1].strip().strip('"')
                        break
        except Exception:
            pass

    # Uptime
    uptime_seconds = 0
    if os.path.exists("/proc/uptime"):
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as f:
                uptime_seconds = int(float(f.readline().split()[0]))
        except Exception:
            pass

    # Load Average
    try:
        load_avg = os.getloadavg()
    except (AttributeError, OSError):
        load_avg = (0.0, 0.0, 0.0)

    # Memory
    mem_total = 0
    mem_avail = 0
    if os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        if key == "MemTotal":
                            mem_total = int(val) * 1024
                        elif key == "MemAvailable":
                            mem_avail = int(val) * 1024
        except Exception:
            pass

    mem_used = max(0, mem_total - mem_avail)

    # Disk
    try:
        usage = shutil.disk_usage(disk_path)
        disk_total = usage.total
        disk_used = usage.used
        disk_free = usage.free
        disk_percent = (disk_used / disk_total * 100.0) if disk_total > 0 else 0.0
    except Exception:
        disk_total = 0
        disk_used = 0
        disk_free = 0
        disk_percent = 0.0

    # Inodes
    inode_percent = None
    if hasattr(os, "statvfs"):
        try:
            st = os.statvfs(disk_path)
            if st.f_files > 0:
                used_inodes = st.f_files - st.f_ffree
                inode_percent = (used_inodes / st.f_files) * 100.0
        except Exception:
            pass

    # Journal disk usage
    journal_usage = "UNKNOWN"
    if journal_cmd:
        try:
            res = subprocess.run(
                ["journalctl", "--disk-usage"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            if res.returncode == 0 and res.stdout:
                # e.g., "Archived and active journals take up 352.0M in the file system."
                out = res.stdout.strip()
                if "take up " in out:
                    journal_usage = out.split("take up ")[1].split(" in ")[0].strip()
                else:
                    journal_usage = out
        except Exception:
            journal_usage = "UNKNOWN"

    return HostInfo(
        hostname=hostname,
        os_release=os_release,
        kernel=kernel,
        uptime_seconds=uptime_seconds,
        load_avg=load_avg,
        mem_total_bytes=mem_total,
        mem_available_bytes=mem_avail,
        mem_used_bytes=mem_used,
        disk_total_bytes=disk_total,
        disk_used_bytes=disk_used,
        disk_free_bytes=disk_free,
        disk_used_percent=disk_percent,
        inode_used_percent=inode_percent,
        journal_usage_str=journal_usage,
    )


# -----------------------------------------------------------------------------
# Service & Listener Probing
# -----------------------------------------------------------------------------
def query_service_info(
    service_name: str,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> ServiceInfo:
    """Query systemd service properties via systemctl without modifying runtime."""
    try:
        res = runner(
            [
                "systemctl",
                "show",
                service_name,
                "--property=ActiveState,SubState,UnitFileState,MainPID,NRestarts,MemoryCurrent",
            ],
            capture_output=True,
            text=True,
            timeout=2.5,
            check=False,
        )
        if res.returncode != 0:
            return ServiceInfo(service_name, "unknown", "unknown", None, None, None)

        props: dict[str, str] = {}
        for line in res.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()

        active = props.get("ActiveState", "unknown")
        unit_file = props.get("UnitFileState", "unknown")
        pid_str = props.get("MainPID")
        pid = int(pid_str) if (pid_str and pid_str.isdigit() and int(pid_str) > 0) else None

        restarts_str = props.get("NRestarts")
        restarts = int(restarts_str) if (restarts_str and restarts_str.isdigit()) else None

        mem_str = props.get("MemoryCurrent")
        memory = int(mem_str) if (mem_str and mem_str.isdigit()) else None

        return ServiceInfo(
            name=service_name,
            active_state=active,
            unit_file_state=unit_file,
            pid=pid,
            restarts=restarts,
            memory_bytes=memory,
        )
    except subprocess.TimeoutExpired:
        return ServiceInfo(service_name, "timeout", "unknown", None, None, None)
    except PermissionError:
        return ServiceInfo(service_name, "permission_denied", "unknown", None, None, None)
    except Exception:
        return ServiceInfo(service_name, "error", "unknown", None, None, None)


def probe_tcp_listener(port: int = DEFAULT_PROXY_PORT, timeout_sec: float = 1.0) -> tuple[bool, str]:
    """Test local TCP connectivity to proxy port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_sec):
            return (True, "LISTENING")
    except ConnectionRefusedError:
        return (False, "CLOSED")
    except socket.timeout:
        return (False, "TIMEOUT")
    except Exception as e:
        return (False, f"ERROR ({e.__class__.__name__})")


# -----------------------------------------------------------------------------
# State File Integrity Probing
# -----------------------------------------------------------------------------
def inspect_state_file(
    state_path: str = DEFAULT_STATE_PATH,
    state_dir: str = DEFAULT_STATE_DIR,
) -> StateInfo:
    """Inspect state file integrity and directory temp files without modifying."""
    if not os.path.exists(state_path):
        # Check orphan temp files
        orphan_count = 0
        if os.path.isdir(state_dir):
            try:
                for name in os.listdir(state_dir):
                    if name.endswith(".tmp") or name.startswith("discord-state-"):
                        orphan_count += 1
            except Exception:
                pass
        return StateInfo(
            path=state_path,
            exists=False,
            size_bytes=None,
            mode_octal=None,
            owner_uid=None,
            json_valid=False,
            confirmed_status=None,
            has_status_message_id=False,
            last_checkpoint_epoch=None,
            orphan_temp_count=orphan_count,
        )

    try:
        st = os.stat(state_path)
        size_bytes = st.st_size
        mode_octal = oct(stat.S_IMODE(st.st_mode))
        owner_uid = st.st_uid
    except Exception:
        size_bytes = None
        mode_octal = None
        owner_uid = None

    json_valid = False
    confirmed_status = None
    has_status_id = False
    last_checkpoint = None

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            json_valid = True
            confirmed_status = str(data.get("confirmed_status", "UNKNOWN"))
            has_status_id = bool(data.get("status_message_id"))
            chk = data.get("last_checkpoint_at")
            if chk is not None:
                last_checkpoint = float(chk)
    except Exception:
        json_valid = False

    # Check orphan temp files
    orphan_count = 0
    target_dir = os.path.dirname(state_path) or state_dir
    if os.path.isdir(target_dir):
        try:
            for name in os.listdir(target_dir):
                full = os.path.join(target_dir, name)
                if full != state_path and (name.endswith(".tmp") or name.startswith("discord-state-")):
                    orphan_count += 1
        except Exception:
            pass

    return StateInfo(
        path=state_path,
        exists=True,
        size_bytes=size_bytes,
        mode_octal=mode_octal,
        owner_uid=owner_uid,
        json_valid=json_valid,
        confirmed_status=confirmed_status,
        has_status_message_id=has_status_id,
        last_checkpoint_epoch=last_checkpoint,
        orphan_temp_count=orphan_count,
    )


# -----------------------------------------------------------------------------
# Diagnostics Formatting & Assessment
# -----------------------------------------------------------------------------
def format_bytes_human(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "N/A"
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KiB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MiB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GiB"


def format_uptime_human(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def run_diagnostics(
    disk_path: str = "/",
    state_path: str = DEFAULT_STATE_PATH,
    state_dir: str = DEFAULT_STATE_DIR,
    proxy_port: int = DEFAULT_PROXY_PORT,
    service_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    journal_cmd: bool = True,
) -> tuple[int, str]:
    """
    Run all read-only diagnostic checks and return (exit_code, formatted_report).
    Exit code: 0 = HEALTHY, 1 = DEGRADED, 2 = ERROR.
    """
    try:
        host = get_host_info(disk_path=disk_path, journal_cmd=journal_cmd)
        ss_info = query_service_info("shadowsocks-libev.service", runner=service_runner)
        listener_ok, listener_status = probe_tcp_listener(port=proxy_port)
        monitor_info = query_service_info("neko-server-monitor.service", runner=service_runner)
        worker_info = query_service_info("neko-discord-worker.service", runner=service_runner)
        legacy_info = query_service_info("neko-traffic-monitor.service", runner=service_runner)
        state = inspect_state_file(state_path=state_path, state_dir=state_dir)
    except Exception as e:
        return (2, f"OPS_STATUS_ERROR: Failed to run diagnostic probes ({e.__class__.__name__}: {e})")

    # Evaluation Rules
    degraded_reasons: list[str] = []

    if ss_info.active_state != "active":
        degraded_reasons.append(f"Shadowsocks service is not active ({ss_info.active_state})")

    if not listener_ok:
        degraded_reasons.append(f"Proxy port {proxy_port} is not listening ({listener_status})")

    if monitor_info.active_state != "active":
        degraded_reasons.append(f"Monitoring Agent is not active ({monitor_info.active_state})")

    if worker_info.active_state != "active":
        degraded_reasons.append(f"Discord Worker is not active ({worker_info.active_state})")

    if legacy_info.active_state == "active":
        degraded_reasons.append("Legacy neko-traffic-monitor service is unexpectedly ACTIVE (dual publisher risk)")

    if not state.exists or not state.json_valid:
        degraded_reasons.append("Discord state file is missing or invalid JSON")

    if host.disk_used_percent >= 90.0:
        degraded_reasons.append(f"Root disk usage is CRITICAL ({host.disk_used_percent:.1f}%)")
    elif host.disk_used_percent >= 80.0:
        degraded_reasons.append(f"Root disk usage is in WARNING band ({host.disk_used_percent:.1f}%)")

    overall_healthy = (len(degraded_reasons) == 0)
    exit_code = 0 if overall_healthy else 1

    lines = [
        "=============================================================================",
        "NEKO FAMILY PROXY — PRODUCTION OPS DIAGNOSTICS",
        "=============================================================================",
        f"HOST:               {host.hostname} ({host.os_release} / {host.kernel})",
        f"UPTIME:             {format_uptime_human(host.uptime_seconds)} | Load: {host.load_avg[0]:.2f}, {host.load_avg[1]:.2f}, {host.load_avg[2]:.2f}",
        f"RAM USAGE:          {format_bytes_human(host.mem_used_bytes)} / {format_bytes_human(host.mem_total_bytes)} ({format_bytes_human(host.mem_available_bytes)} available)",
        f"DISK USAGE:         {format_bytes_human(host.disk_used_bytes)} / {format_bytes_human(host.disk_total_bytes)} ({host.disk_used_percent:.1f}% used, {format_bytes_human(host.disk_free_bytes)} free)",
        f"JOURNAL USAGE:      {host.journal_usage_str}",
        "",
        "SERVICES:",
        f"  shadowsocks-libev:    {ss_info.active_state.upper()} (PID: {ss_info.pid or 'N/A'}, Restarts: {ss_info.restarts if ss_info.restarts is not None else 'N/A'}, Mem: {format_bytes_human(ss_info.memory_bytes)})",
        f"  neko-server-monitor:  {monitor_info.active_state.upper()} (PID: {monitor_info.pid or 'N/A'}, Restarts: {monitor_info.restarts if monitor_info.restarts is not None else 'N/A'}, Mem: {format_bytes_human(monitor_info.memory_bytes)})",
        f"  neko-discord-worker:  {worker_info.active_state.upper()} (PID: {worker_info.pid or 'N/A'}, Restarts: {worker_info.restarts if worker_info.restarts is not None else 'N/A'}, Mem: {format_bytes_human(worker_info.memory_bytes)})",
        f"  neko-traffic-monitor: {legacy_info.active_state.upper()} (Enabled: {legacy_info.unit_file_state}, Rollback Authority)",
        "",
        "NETWORK & LISTENERS:",
        f"  TCP Listener :{proxy_port}:  {listener_status}",
        "",
        "STATE INTEGRITY:",
        f"  discord-state.json:   {'VALID' if (state.exists and state.json_valid) else ('CORRUPT' if state.exists else 'MISSING')} (Size: {format_bytes_human(state.size_bytes)}, Mode: {state.mode_octal or 'N/A'}, Status: {state.confirmed_status or 'N/A'})",
        f"  Persistent Msg ID:    {'PRESENT' if state.has_status_message_id else 'NONE'}",
        f"  Orphan Temp Files:    {state.orphan_temp_count}",
        "=============================================================================",
    ]

    if overall_healthy:
        lines.append("OVERALL STATUS:         ALL SYSTEMS HEALTHY (0_HEALTHY)")
    else:
        lines.append("OVERALL STATUS:         DEGRADED OPERATIONAL CONDITION (1_DEGRADED)")
        lines.append("DEGRADED REASONS:")
        for r in degraded_reasons:
            lines.append(f"  - {r}")
    lines.append("=============================================================================")

    return (exit_code, "\n".join(lines))


def main() -> None:
    exit_code, report = run_diagnostics()
    print(report)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
