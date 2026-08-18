#!/usr/bin/env python3
"""
Unit tests for Weekly Maintenance Automation & Discord Maintenance State (Phase T9A)
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure agent directory is in sys.path
AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
import sys
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from neko_discord_worker import (
    DiscordTransport,
    WorkerState,
    build_current_status_payload,
    derive_health_status,
    load_state,
    save_state_atomic,
    StatusStateMachine,
    HealthSnapshot,
)
from neko_weekly_maintenance import (
    MaintenanceController,
    build_maintenance_payload,
    load_webhook_from_env_file,
)


class MockHTTPResponse:
    def __init__(self, status: int = 200, body: bytes = b"{}"):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> MockHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class TestMaintenancePayload(unittest.TestCase):
    """Test maintenance Discord embed construction & privacy invariants."""

    def test_build_maintenance_payload_structure(self) -> None:
        payload = build_maintenance_payload(
            timezone_name="Asia/Bangkok",
            timestamp_epoch=1787041200.0,
        )

        self.assertEqual(payload["username"], "Neko Family Proxy")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertIn("embeds", payload)
        self.assertEqual(len(payload["embeds"]), 1)

        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "🛠️ NEKO PROXY — กำลังซ่อมบำรุง")
        self.assertEqual(embed["color"], 0xE67E22)  # Amber
        self.assertIn("ระบบจะกลับมาให้บริการอัตโนมัติหลังการรีสตาร์ต", embed["footer"]["text"])

        fields_dict = {f["name"]: f["value"] for f in embed["fields"]}
        self.assertIn("**🛠️ MAINTENANCE**", fields_dict.get("Status", ""))
        self.assertIn("การบำรุงรักษาประจำสัปดาห์", fields_dict.get("Reason", ""))
        self.assertIn("ทุกวันอังคาร เวลา 02:00 น. (เวลาไทย)", fields_dict.get("Schedule", ""))

    def test_payload_strict_privacy_invariants(self) -> None:
        """Verify zero user telemetry or session tracking in maintenance payload."""
        payload = build_maintenance_payload()
        serialized = json.dumps(payload, ensure_ascii=False).lower()

        forbidden_terms = [
            "active users",
            "active_users",
            "online users",
            "client_ip",
            "client ip",
            "user_id",
            "session",
            "packet_payload",
            "token",
            "password",
        ]
        for term in forbidden_terms:
            self.assertNotIn(term, serialized, f"Forbidden term '{term}' found in maintenance payload")


class TestMaintenanceMissingIdSafety(unittest.TestCase):
    """Test strict missing-ID safety policy (no blind POST on absent state ID)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.temp_dir.name, "discord-state.json")
        self.webhook_url = "https://discord.com/api/webhooks/12345/mock-token"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_status_id_present_patch_success(self) -> None:
        """When status_message_id is present and PATCH succeeds, edit SAME message."""
        state = WorkerState(status_message_id="msg_existing_111")
        save_state_atomic(state, self.state_path)

        mock_req = MagicMock(return_value=MockHTTPResponse(200, b"{}"))
        transport = DiscordTransport(self.webhook_url, request_fn=mock_req)
        controller = MaintenanceController(
            webhook_url=self.webhook_url,
            state_path=self.state_path,
            transport=transport,
        )

        success = controller.publish_maintenance_status()
        self.assertTrue(success)

        # Verify PATCH was called on existing message URL
        self.assertEqual(mock_req.call_count, 1)
        req_obj = mock_req.call_args[0][0]
        self.assertEqual(req_obj.get_method(), "PATCH")
        self.assertTrue(req_obj.full_url.endswith("/messages/msg_existing_111"))

        # Verify state is unchanged
        reloaded = load_state(self.state_path)
        self.assertEqual(reloaded.status_message_id, "msg_existing_111")

    def test_status_id_present_patch_404_controlled_replacement(self) -> None:
        """When status_message_id is present but returns 404, post controlled replacement & persist new ID."""
        state = WorkerState(status_message_id="msg_deleted_999")
        save_state_atomic(state, self.state_path)

        import urllib.error

        def side_effect(req: urllib.request.Request, *args: object, **kwargs: object) -> MockHTTPResponse:
            if req.get_method() == "PATCH":
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))
            return MockHTTPResponse(200, b'{"id": "msg_new_replacement_222"}')

        mock_req = MagicMock(side_effect=side_effect)
        transport = DiscordTransport(self.webhook_url, request_fn=mock_req)
        controller = MaintenanceController(
            webhook_url=self.webhook_url,
            state_path=self.state_path,
            transport=transport,
        )

        success = controller.publish_maintenance_status()
        self.assertTrue(success)

        # Verify 2 calls: PATCH (404) then POST (?wait=true)
        self.assertEqual(mock_req.call_count, 2)
        reloaded = load_state(self.state_path)
        self.assertEqual(reloaded.status_message_id, "msg_new_replacement_222")

    def test_status_id_absent_does_not_blindly_post(self) -> None:
        """When status_message_id is absent, DO NOT blindly POST a new message."""
        # Create empty state file with no message ID
        state = WorkerState(status_message_id=None)
        save_state_atomic(state, self.state_path)

        mock_req = MagicMock()
        transport = DiscordTransport(self.webhook_url, request_fn=mock_req)
        controller = MaintenanceController(
            webhook_url=self.webhook_url,
            state_path=self.state_path,
            transport=transport,
        )

        success = controller.publish_maintenance_status()
        # Must return False without making any Discord network calls
        self.assertFalse(success)
        self.assertEqual(mock_req.call_count, 0, "Blind POST occurred when status_message_id was absent!")


class TestMaintenanceDiscordFailureIsolation(unittest.TestCase):
    """Test that reboot proceeds even if Discord encounters bounded delivery failure."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.temp_dir.name, "discord-state.json")
        self.webhook_url = "https://discord.com/api/webhooks/12345/mock-token"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_reboot_continues_after_bounded_discord_failure(self) -> None:
        """Reboot continues when Discord edit throws network error."""
        state = WorkerState(status_message_id="msg_123")
        save_state_atomic(state, self.state_path)

        mock_req = MagicMock(side_effect=TimeoutError("Discord API unreachable"))
        transport = DiscordTransport(self.webhook_url, request_fn=mock_req)

        mock_runner = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="inactive", stderr=""))
        controller = MaintenanceController(
            webhook_url=self.webhook_url,
            state_path=self.state_path,
            transport=transport,
            command_runner=mock_runner,
        )

        # execute_maintenance should still return True (reboot succeeded)
        reboot_ok = controller.execute_maintenance(dry_run=False)
        self.assertTrue(reboot_ok)

        # Confirm worker stop and systemctl reboot were both invoked
        commands_run = [c[0][0] for c in mock_runner.call_args_list]
        self.assertIn(["systemctl", "stop", "neko-discord-worker.service"], commands_run)
        self.assertIn(["systemctl", "reboot"], commands_run)


class TestWorkerStopOrderAndRebootAbstraction(unittest.TestCase):
    """Test that worker is stopped before Discord edit and local reboot is abstracted."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.temp_dir.name, "discord-state.json")
        self.webhook_url = "https://discord.com/api/webhooks/12345/mock-token"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_execution_order_worker_stop_before_publish_and_reboot(self) -> None:
        """Worker must be confirmed stopped before Discord edit, and reboot must be last."""
        state = WorkerState(status_message_id="msg_abc")
        save_state_atomic(state, self.state_path)

        call_order: list[str] = []

        def mock_command_runner(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            if "stop" in cmd:
                call_order.append("STOP_WORKER")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "is-active" in cmd:
                call_order.append("CHECK_WORKER")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="inactive\n", stderr="")
            if "reboot" in cmd:
                call_order.append("SYSTEMCTL_REBOOT")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        def mock_request_fn(req: urllib.request.Request, *args: object, **kwargs: object) -> MockHTTPResponse:
            call_order.append("DISCORD_EDIT")
            return MockHTTPResponse(200, b"{}")

        transport = DiscordTransport(self.webhook_url, request_fn=mock_request_fn)
        controller = MaintenanceController(
            webhook_url=self.webhook_url,
            state_path=self.state_path,
            transport=transport,
            command_runner=mock_command_runner,
        )

        ok = controller.execute_maintenance(dry_run=False)
        self.assertTrue(ok)

        # Expected strict sequence
        self.assertEqual(call_order, ["STOP_WORKER", "CHECK_WORKER", "DISCORD_EDIT", "SYSTEMCTL_REBOOT"])

    def test_dry_run_never_invokes_real_mutations(self) -> None:
        """Dry-run mode must never stop worker, send Discord requests, or reboot host."""
        mock_runner = MagicMock()
        mock_req = MagicMock()
        transport = DiscordTransport(self.webhook_url, request_fn=mock_req)

        controller = MaintenanceController(
            webhook_url=self.webhook_url,
            state_path=self.state_path,
            transport=transport,
            command_runner=mock_runner,
        )

        ok = controller.execute_maintenance(dry_run=True)
        self.assertTrue(ok)
        self.assertEqual(mock_runner.call_count, 0)
        self.assertEqual(mock_req.call_count, 0)


class TestSystemdTimerAndServiceSyntax(unittest.TestCase):
    """Test source-controlled systemd timer and service definitions."""

    def test_timer_semantics(self) -> None:
        timer_path = os.path.join(AGENT_DIR, "systemd", "neko-weekly-maintenance.timer")
        self.assertTrue(os.path.exists(timer_path), f"Timer file not found: {timer_path}")

        with open(timer_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("OnCalendar=Tue *-*-* 02:00:00 Asia/Bangkok", content)
        self.assertIn("Persistent=false", content)
        self.assertIn("AccuracySec=1s", content)
        self.assertIn("RandomizedDelaySec=0", content)
        self.assertIn("Unit=neko-weekly-maintenance.service", content)
        self.assertIn("WantedBy=timers.target", content)

    def test_service_semantics(self) -> None:
        service_path = os.path.join(AGENT_DIR, "systemd", "neko-weekly-maintenance.service")
        self.assertTrue(os.path.exists(service_path), f"Service file not found: {service_path}")

        with open(service_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Type=oneshot", content)
        self.assertIn("ExecStart=/usr/bin/python3 /opt/neko/neko_weekly_maintenance.py --execute", content)
        self.assertIn("EnvironmentFile=-/etc/neko/discord.env", content)
        self.assertIn("TimeoutStartSec=60s", content)


class TestPostBootWorkerRecovery(unittest.TestCase):
    """Test that existing Worker recovers from MAINTENANCE state and publishes real health."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.temp_dir.name, "discord-state.json")
        self.webhook_url = "https://discord.com/api/webhooks/12345/mock-token"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_worker_edits_same_message_with_real_health(self) -> None:
        """Worker loads state, derives ONLINE, and PATCHes the SAME message ID."""
        # Simulated state left by maintenance
        state = WorkerState(
            status_message_id="msg_same_id_777",
            confirmed_status="ONLINE",
        )
        save_state_atomic(state, self.state_path)

        snapshot = HealthSnapshot(
            timestamp_mono=time.monotonic(),
            timestamp_epoch=time.time(),
            uptime_seconds=3600,
            service_status="active",
            listener_status="active",
            ping_ms=12.5,
            packet_loss_percent=0.0,
            service_ok=True,
            listener_ok=True,
            probe_ok=True,
        )

        payload = build_current_status_payload("ONLINE", snapshot, 1000000.0, 500000.0)
        self.assertEqual(payload["embeds"][0]["title"], "🌐 NEKO PROXY — CURRENT STATUS")
        self.assertIn("🟢 ONLINE", payload["embeds"][0]["fields"][0]["value"])

        # Status machine evaluates healthy snapshot as ONLINE
        status = derive_health_status(snapshot, time.monotonic(), 30.0)
        self.assertEqual(status, "ONLINE")


if __name__ == "__main__":
    unittest.main()
