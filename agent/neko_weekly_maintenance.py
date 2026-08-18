#!/usr/bin/env python3
"""
Neko Family Proxy — Weekly VPS Maintenance Controller (Phase T9A)

Responsibilities:
1. Scheduled weekly maintenance trigger via systemd timer (Tuesday 02:00 Asia/Bangkok).
2. Stop neko-discord-worker.service to prevent race condition where worker overwrites maintenance state.
3. Announce maintenance on Discord by editing the SAME persistent Current Status message.
4. If status_message_id is present:
   - PATCH 2xx -> Success, status updated in-place.
   - PATCH 404 -> Old message proven missing -> Controlled POST ?wait=true ONE replacement & persist new ID.
   - Other failure (timeout/5xx/429) -> Bounded retry -> Continue reboot.
5. If status_message_id is absent:
   - DO NOT blindly POST a new message (prevents duplicate status messages).
   - Log MAINTENANCE_STATUS_ID_MISSING -> Continue orderly reboot.
6. Initiate orderly host reboot via `systemctl reboot`.
7. Post-boot: Normal systemd boot starts Shadowsocks, Server Monitor, and Discord Worker.
   Discord Worker loads persistent state, evaluates real health, and naturally transitions
   the SAME message to ONLINE / DEGRADED.

Strict Invariants:
- Zero client telemetry, zero user IDs, zero session tracking.
- Reboot continues even if Discord delivery encounters bounded failure (REBOOT_CONTINUES_AFTER_BOUNDED_DISCORD_FAILURE = YES).
- No blind POST when state ID is absent (BLIND_POST_ON_MISSING_STATE_ID = NO).
- Abstracted command execution: local test runs never invoke real systemctl reboot (LOCAL_REBOOT_TRIGGERED = NO).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone as datetime_timezone
from typing import Any, Callable

# Add parent / agent directory to sys.path for sibling imports if needed
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

try:
    from neko_discord_worker import (
        DEFAULT_STATE_PATH,
        DEFAULT_TIMEZONE,
        DiscordTransport,
        WorkerState,
        get_timezone,
        load_state,
        save_state_atomic,
    )
except ImportError:
    # Standalone fallbacks if running in isolated environment
    DEFAULT_STATE_PATH = "/var/lib/neko/discord-state.json"
    DEFAULT_TIMEZONE = "Asia/Bangkok"

    class WorkerState:  # type: ignore[no-redef]
        def __init__(self, status_message_id: str | None = None, **kwargs: Any) -> None:
            self.status_message_id = status_message_id

        def to_dict(self) -> dict[str, Any]:
            return {"status_message_id": self.status_message_id}

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> WorkerState:
            return cls(status_message_id=data.get("status_message_id"))

    def load_state(state_path: str) -> WorkerState:  # type: ignore[no-redef]
        if not os.path.exists(state_path):
            return WorkerState()
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return WorkerState.from_dict(data)
        except Exception:
            pass
        return WorkerState()

    def save_state_atomic(state: WorkerState, state_path: str) -> bool:  # type: ignore[no-redef]
        import tempfile
        try:
            dir_name = os.path.dirname(state_path)
            if dir_name:
                os.makedirs(dir_name, mode=0o700, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="discord-state-", suffix=".tmp", dir=dir_name or None)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, state_path)
            return True
        except Exception:
            return False

    def get_timezone(timezone_name: str) -> datetime_timezone:  # type: ignore[no-redef]
        from zoneinfo import ZoneInfo
        try:
            return ZoneInfo(timezone_name)
        except Exception:
            from datetime import timedelta
            return datetime_timezone(timedelta(hours=7), name="ICT")

    class DiscordTransport:  # type: ignore[no-redef]
        def __init__(self, webhook_url: str, request_fn: Callable[..., Any] | None = None) -> None:
            self.webhook_url = webhook_url.rstrip("/")
            self._request_fn = request_fn or urllib.request.urlopen

        def post_message(self, payload: dict[str, Any], wait: bool = False) -> tuple[bool, str | None]:
            url = f"{self.webhook_url}?wait=true" if wait else self.webhook_url
            return self._send("POST", url, payload)

        def edit_message(self, message_id: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
            url = f"{self.webhook_url}/messages/{message_id}"
            return self._send("PATCH", url, payload)

        def _send(self, method: str, url: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "NekoMaintenanceController/1.0"},
                method=method,
            )
            for attempt in range(2):
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
                    if error.code == 404:
                        return (False, "404")
                    if error.code == 429:
                        if attempt == 0:
                            time.sleep(2.0)
                            continue
                        return (False, "429")
                    if 500 <= error.code < 600:
                        if attempt == 0:
                            time.sleep(2.0)
                            continue
                        return (False, str(error.code))
                    return (False, str(error.code))
                except Exception:
                    if attempt == 0:
                        time.sleep(1.0)
                        continue
                    return (False, "network_error")
            return (False, "retries_exhausted")


DISCORD_WORKER_SERVICE = "neko-discord-worker.service"
ENV_FILE_PATH = "/etc/neko/discord.env"


def _safe_log(event: str, **fields: Any) -> None:
    """Log events cleanly without exposing secrets."""
    details = " | ".join(f"{k}={v}" for k, v in fields.items())
    ts = datetime.now(datetime_timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {event} | {details}" if details else f"[{ts}] {event}", flush=True)


def build_maintenance_payload(
    timezone_name: str = DEFAULT_TIMEZONE,
    timestamp_epoch: float | None = None,
) -> dict[str, Any]:
    """
    Build the persistent Maintenance Discord embed.
    Strictly adheres to Phase T9A visual and privacy specification.
    """
    now_epoch = timestamp_epoch if timestamp_epoch is not None else time.time()
    dt_iso = datetime.fromtimestamp(now_epoch, datetime_timezone.utc).isoformat()

    fields = [
        {"name": "Status", "value": "**🛠️ MAINTENANCE**", "inline": True},
        {"name": "Reason", "value": "การบำรุงรักษาประจำสัปดาห์", "inline": True},
        {"name": "Schedule", "value": "ทุกวันอังคาร เวลา 02:00 น. (เวลาไทย)", "inline": False},
        {"name": "Action", "value": "ระบบกำลังรีสตาร์ตและจะกลับมาให้บริการอัตโนมัติ", "inline": False},
    ]

    return {
        "username": "Neko Family Proxy",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "🛠️ NEKO PROXY — กำลังซ่อมบำรุง",
                "color": 0xE67E22,  # Amber / Maintenance Orange
                "fields": fields,
                "timestamp": dt_iso,
                "footer": {"text": "ระบบจะกลับมาให้บริการอัตโนมัติหลังการรีสตาร์ต | AWS Lightsail JP"},
            }
        ],
    }


def load_webhook_from_env_file(env_file_path: str = ENV_FILE_PATH) -> str:
    """Load DISCORD_WEBHOOK_URL from environment or /etc/neko/discord.env without exposing it."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if url:
        return url

    if os.path.exists(env_file_path):
        try:
            with open(env_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    clean = line.strip()
                    if clean.startswith("DISCORD_WEBHOOK_URL="):
                        val = clean.split("=", 1)[1].strip().strip("'\"")
                        if val:
                            return val
        except Exception as e:
            _safe_log("ENV_FILE_READ_ERROR", path=env_file_path, reason=str(e))

    return ""


class MaintenanceController:
    """
    Controller for weekly scheduled maintenance workflow:
    1. Validate configuration & state
    2. Stop Discord Worker
    3. Update persistent Discord status to MAINTENANCE
    4. Trigger orderly host reboot
    """

    def __init__(
        self,
        webhook_url: str = "",
        state_path: str = DEFAULT_STATE_PATH,
        worker_service: str = DISCORD_WORKER_SERVICE,
        timezone_name: str = DEFAULT_TIMEZONE,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        transport: DiscordTransport | None = None,
    ) -> None:
        self.webhook_url = webhook_url or load_webhook_from_env_file()
        self.state_path = state_path
        self.worker_service = worker_service
        self.timezone_name = timezone_name
        self._command_runner = command_runner or self._default_command_runner
        self.transport = transport or (DiscordTransport(self.webhook_url) if self.webhook_url else None)

    @staticmethod
    def _default_command_runner(cmd: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def check_config(self) -> tuple[bool, list[str]]:
        """Validate configuration, state file accessibility, and webhook presence."""
        errors: list[str] = []
        if not self.webhook_url:
            errors.append("DISCORD_WEBHOOK_URL is missing or empty.")
        elif not self.webhook_url.startswith("https://discord.com/api/webhooks/"):
            errors.append("DISCORD_WEBHOOK_URL does not match expected Discord webhook format.")

        state_dir = os.path.dirname(self.state_path)
        if state_dir and not os.path.exists(state_dir):
            errors.append(f"State directory {state_dir} does not exist.")

        return len(errors) == 0, errors

    def stop_worker(self, dry_run: bool = False) -> bool:
        """
        Stop neko-discord-worker.service and confirm inactive.
        Prevents race where worker overwrites maintenance status.
        """
        if dry_run:
            _safe_log("DRY_RUN_STOP_WORKER", service=self.worker_service)
            return True

        _safe_log("STOPPING_DISCORD_WORKER", service=self.worker_service)
        res = self._command_runner(["systemctl", "stop", self.worker_service])
        if res.returncode != 0:
            _safe_log("WORKER_STOP_COMMAND_NONZERO", code=res.returncode, stderr=res.stderr.strip())

        # Confirm inactive
        check = self._command_runner(["systemctl", "is-active", self.worker_service])
        status = check.stdout.strip()
        _safe_log("WORKER_SERVICE_STATE", state=status)
        return status in ("inactive", "failed", "unknown")

    def publish_maintenance_status(self, dry_run: bool = False) -> bool:
        """
        Publish MAINTENANCE status to Discord following strict missing-ID safety:
        - status_message_id PRESENT:
            - PATCH 2xx: Success, edited in-place.
            - PATCH 404: Message proven missing -> controlled POST ?wait=true ONE replacement & persist new ID.
            - other failure: Bounded retry -> log MAINTENANCE_ANNOUNCEMENT_FAILED, return False.
        - status_message_id ABSENT:
            - DO NOT blindly POST a new message (prevents duplicate status messages).
            - Log MAINTENANCE_STATUS_ID_MISSING, return False.
        """
        payload = build_maintenance_payload(self.timezone_name)

        if dry_run:
            state = load_state(self.state_path)
            _safe_log(
                "DRY_RUN_MAINTENANCE_STATUS",
                has_webhook=bool(self.webhook_url),
                status_message_id=state.status_message_id or "ABSENT",
            )
            return True

        if not self.transport:
            _safe_log("MAINTENANCE_ANNOUNCEMENT_SKIPPED_NO_TRANSPORT")
            return False

        state = load_state(self.state_path)
        msg_id = state.status_message_id

        if not msg_id:
            # Policy Rule: Do NOT blindly POST when ID is absent
            _safe_log("MAINTENANCE_STATUS_ID_MISSING", action="SKIP_BLIND_POST")
            return False

        # Attempt to edit existing message
        _safe_log("EDITING_PERSISTENT_MAINTENANCE_STATUS", message_id=msg_id)
        success, err_or_id = self.transport.edit_message(msg_id, payload)

        if success:
            _safe_log("MAINTENANCE_STATUS_PUBLISHED_IN_PLACE", message_id=msg_id)
            return True

        if err_or_id == "404":
            # Referenced message is proven deleted / missing from Discord
            _safe_log("STATUS_MESSAGE_404_POSTING_REPLACEMENT")
            post_ok, new_id = self.transport.post_message(payload, wait=True)
            if post_ok and new_id:
                state.status_message_id = new_id
                save_state_atomic(state, self.state_path)
                _safe_log("MAINTENANCE_STATUS_REPLACEMENT_POSTED", new_message_id=new_id)
                return True
            _safe_log("MAINTENANCE_STATUS_REPLACEMENT_POST_FAILED")
            return False

        _safe_log("MAINTENANCE_ANNOUNCEMENT_FAILED", error=err_or_id)
        return False

    def request_reboot(self, dry_run: bool = False) -> bool:
        """
        Execute orderly host reboot: systemctl reboot.
        In dry-run or local tests, command is simulated and NOT executed on host.
        """
        if dry_run:
            _safe_log("DRY_RUN_REBOOT_INTENT", command="systemctl reboot")
            return True

        _safe_log("EXECUTING_ORDERLY_REBOOT", command="systemctl reboot")
        res = self._command_runner(["systemctl", "reboot"])
        if res.returncode != 0:
            _safe_log("REBOOT_COMMAND_FAILED", code=res.returncode, stderr=res.stderr.strip())
            return False
        return True

    def execute_maintenance(self, dry_run: bool = False) -> bool:
        """
        Execute full weekly maintenance sequence:
        1. Stop worker
        2. Publish maintenance status (bounded failure does not abort reboot)
        3. Reboot host
        """
        _safe_log("MAINTENANCE_SEQUENCE_START", mode="DRY_RUN" if dry_run else "EXECUTE")

        # 1. Stop worker
        self.stop_worker(dry_run=dry_run)

        # 2. Publish maintenance status
        self.publish_maintenance_status(dry_run=dry_run)

        # 3. Request reboot (REBOOT_CONTINUES_AFTER_BOUNDED_DISCORD_FAILURE = YES)
        reboot_ok = self.request_reboot(dry_run=dry_run)
        _safe_log("MAINTENANCE_SEQUENCE_COMPLETE", reboot_status="TRIGGERED" if reboot_ok else "FAILED")
        return reboot_ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Neko Family Proxy — Weekly VPS Maintenance Controller")
    parser.add_argument("--dry-run", action="store_true", help="Validate workflow without stopping services, sending Discord messages, or rebooting.")
    parser.add_argument("--check-config", action="store_true", help="Check configuration and state file accessibility.")
    parser.add_argument("--publish-only", action="store_true", help="Publish maintenance status embed without stopping worker or rebooting.")
    parser.add_argument("--execute", action="store_true", help="Execute full maintenance sequence (stop worker, publish maintenance status, reboot host).")
    parser.add_argument("--state-path", default=DEFAULT_STATE_PATH, help=f"Path to discord-state.json (default: {DEFAULT_STATE_PATH})")
    args = parser.parse_args()

    controller = MaintenanceController(state_path=args.state_path)

    if args.check_config:
        ok, errors = controller.check_config()
        if ok:
            print("[CONFIG_CHECK] SUCCESS: Weekly maintenance configuration is valid.")
            sys.exit(0)
        else:
            print("[CONFIG_CHECK] FAILED: Configuration issues found:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)

    if args.publish_only:
        ok = controller.publish_maintenance_status(dry_run=args.dry_run)
        sys.exit(0 if ok else 1)

    if args.dry_run and not args.execute:
        controller.execute_maintenance(dry_run=True)
        sys.exit(0)

    if args.execute or args.dry_run:
        controller.execute_maintenance(dry_run=args.dry_run)
        sys.exit(0)

    parser.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
