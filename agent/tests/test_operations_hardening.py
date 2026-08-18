#!/usr/bin/env python3
"""
Neko Family Proxy — Operations Hardening & Health Diagnostics Unit Tests (Phase T8B)

Deterministic unit tests verifying:
1. Systemd candidate units and drop-in configurations contract.
2. State atomic write temporary file cleanup on disk/permission errors.
3. --check-config static validation and secret masking.
4. Read-only operator diagnostics (neko_ops_status.py) under all health scenarios.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

# Ensure agent module is in path
AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from neko_discord_worker import (
    WorkerState,
    load_state,
    save_state_atomic,
    validate_configuration,
    main as worker_main,
)
import neko_ops_status


class TestSystemdContracts(unittest.TestCase):
    """Verify systemd service unit and drop-in candidate files conform strictly to T8 architecture."""

    def setUp(self) -> None:
        self.worker_unit_path = os.path.join(AGENT_DIR, "systemd", "neko-discord-worker.service")
        self.ss_dropin_path = os.path.join(AGENT_DIR, "systemd", "shadowsocks-libev.service.d", "10-neko-recovery.conf")
        self.journal_dropin_path = os.path.join(AGENT_DIR, "systemd", "journald.conf.d", "10-neko-journal-cap.conf")

    def test_discord_worker_unit_contract(self) -> None:
        self.assertTrue(os.path.exists(self.worker_unit_path), f"Missing {self.worker_unit_path}")
        with open(self.worker_unit_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Restart policy
        self.assertIn("Restart=always", content)
        self.assertIn("RestartSec=5s", content)

        # Restart storm protection
        self.assertIn("StartLimitIntervalSec=60s", content)
        self.assertIn("StartLimitBurst=5", content)

        # Resource safety bounds
        self.assertIn("MemoryMax=128M", content)
        self.assertIn("TasksMax=16", content)

        # Static pre-flight check
        self.assertIn("ExecStartPre=/usr/bin/python3 /opt/neko/neko_discord_worker.py --check-config", content)

        # Capability bounding set CAP_NET_RAW preserved
        self.assertIn("CapabilityBoundingSet=CAP_NET_RAW", content)
        self.assertIn("AmbientCapabilities=CAP_NET_RAW", content)
        self.assertIn("NoNewPrivileges=true", content)

        # Zero lifecycle coupling to Shadowsocks or Monitor
        self.assertNotIn("Requires=shadowsocks", content)
        self.assertNotIn("PartOf=shadowsocks", content)
        self.assertNotIn("Requires=neko-server-monitor", content)
        self.assertNotIn("PartOf=neko-server-monitor", content)

    def test_shadowsocks_recovery_dropin_contract(self) -> None:
        self.assertTrue(os.path.exists(self.ss_dropin_path), f"Missing {self.ss_dropin_path}")
        with open(self.ss_dropin_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("[Unit]", content)
        self.assertIn("StartLimitIntervalSec=60s", content)
        self.assertIn("StartLimitBurst=5", content)

        self.assertIn("[Service]", content)
        self.assertIn("Restart=always", content)
        self.assertIn("RestartSec=5s", content)

        # Must NOT rewrite vendor properties
        self.assertNotIn("ExecStart", content)
        self.assertNotIn("User", content)
        self.assertNotIn("Group", content)
        self.assertNotIn("Requires", content)

    def test_journal_capacity_dropin_contract(self) -> None:
        self.assertTrue(os.path.exists(self.journal_dropin_path), f"Missing {self.journal_dropin_path}")
        with open(self.journal_dropin_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("[Journal]", content)
        self.assertIn("SystemMaxUse=500M", content)
        self.assertNotIn("Storage=volatile", content)


class TestStateAtomicCleanup(unittest.TestCase):
    """Verify state atomic persistence cleanup and exception safety."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.temp_dir, "discord-state.json")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_clean_save_leaves_no_temp_files(self) -> None:
        state = WorkerState(status_message_id="msg_123", confirmed_status="ONLINE")
        success = save_state_atomic(state, self.state_file)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(self.state_file))

        # Check directory contains only state file, no .tmp files
        files = os.listdir(self.temp_dir)
        self.assertEqual(files, ["discord-state.json"])

    def test_replace_failure_unlinks_temp_file_and_preserves_original(self) -> None:
        # 1. Establish initial valid state
        initial_state = WorkerState(status_message_id="initial_msg", confirmed_status="ONLINE")
        self.assertTrue(save_state_atomic(initial_state, self.state_file))

        # 2. Attempt to save new state with simulated replace failure (e.g. disk error / permission)
        new_state = WorkerState(status_message_id="corrupted_attempt", confirmed_status="DEGRADED")
        with mock.patch("os.replace", side_effect=OSError("Simulated disk replacement error")):
            success = save_state_atomic(new_state, self.state_file)
            self.assertFalse(success)

        # 3. Verify no orphaned .tmp files remain in directory
        files = os.listdir(self.temp_dir)
        self.assertEqual(files, ["discord-state.json"], f"Found orphaned temp files: {files}")

        # 4. Verify initial state file was preserved and remains intact
        loaded = load_state(self.state_file)
        self.assertEqual(loaded.status_message_id, "initial_msg")
        self.assertEqual(loaded.confirmed_status, "ONLINE")

    def test_fsync_failure_unlinks_temp_file(self) -> None:
        state = WorkerState(status_message_id="msg_456")
        with mock.patch("os.fsync", side_effect=OSError("Simulated fsync error")):
            success = save_state_atomic(state, self.state_file)
            self.assertFalse(success)

        files = os.listdir(self.temp_dir)
        self.assertEqual(files, [], f"Expected 0 files, found: {files}")


class TestConfigurationValidation(unittest.TestCase):
    """Verify --check-config validation rules, exit codes, and secret safety."""

    def setUp(self) -> None:
        self.valid_env = {
            "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1234567890/EXAMPLE_SECRET_TOKEN",
            "NETWORK_INTERFACE": "ens5",
            "PROXY_PORT": "8388",
            "PING_TARGET": "8.8.8.8",
            "SHADOWSOCKS_SERVICE": "shadowsocks-libev.service",
            "STATE_PATH": "/var/lib/neko/discord-state.json",
            "HEALTH_SAMPLE_SECONDS": "5.0",
            "STATUS_UPDATE_SECONDS": "60.0",
            "TRAFFIC_SUMMARY_SECONDS": "1800",
            "TRAFFIC_MIN_REPORT_BYTES": "1048576",
            "STALE_AFTER_SECONDS": "180.0",
            "ALERT_COOLDOWN_SECONDS": "300.0",
            "MONITOR_TIMEZONE": "Asia/Bangkok",
        }

    def test_valid_configuration_passes(self) -> None:
        is_valid, errors = validate_configuration(self.valid_env, print_output=False)
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_missing_webhook_fails(self) -> None:
        env = dict(self.valid_env)
        env["DISCORD_WEBHOOK_URL"] = ""
        is_valid, errors = validate_configuration(env, print_output=False)
        self.assertFalse(is_valid)
        self.assertTrue(any("DISCORD_WEBHOOK_URL is missing" in e for e in errors))

    def test_invalid_webhook_url_fails(self) -> None:
        env = dict(self.valid_env)
        env["DISCORD_WEBHOOK_URL"] = "http://insecure-webhook.com"
        is_valid, errors = validate_configuration(env, print_output=False)
        self.assertFalse(is_valid)
        self.assertTrue(any("must be a valid HTTPS URL" in e for e in errors))

    def test_invalid_port_fails(self) -> None:
        for bad_port in ["0", "65536", "-1", "not_a_number"]:
            env = dict(self.valid_env)
            env["PROXY_PORT"] = bad_port
            is_valid, errors = validate_configuration(env, print_output=False)
            self.assertFalse(is_valid, f"Port {bad_port} should have failed")
            self.assertTrue(any("PROXY_PORT" in e for e in errors))

    def test_invalid_intervals_fail(self) -> None:
        env = dict(self.valid_env)
        env["HEALTH_SAMPLE_SECONDS"] = "0"
        env["TRAFFIC_SUMMARY_SECONDS"] = "-10"
        is_valid, errors = validate_configuration(env, print_output=False)
        self.assertFalse(is_valid)
        self.assertTrue(any("HEALTH_SAMPLE_SECONDS" in e for e in errors))
        self.assertTrue(any("TRAFFIC_SUMMARY_SECONDS" in e for e in errors))

    def test_invalid_timezone_fails(self) -> None:
        env = dict(self.valid_env)
        env["MONITOR_TIMEZONE"] = "Invalid/Nonexistent_Timezone"
        is_valid, errors = validate_configuration(env, print_output=False)
        self.assertFalse(is_valid)
        self.assertTrue(any("not a recognized timezone" in e for e in errors))

    def test_secret_not_printed_in_config_check(self) -> None:
        secret_token = "SUPER_SECRET_DISCORD_TOKEN_99999"
        env = dict(self.valid_env)
        env["DISCORD_WEBHOOK_URL"] = f"https://discord.com/api/webhooks/111111/{secret_token}"

        captured_output = io.StringIO()
        with mock.patch("sys.stdout", captured_output):
            validate_configuration(env, print_output=True)

        output = captured_output.getvalue()
        self.assertNotIn(secret_token, output)
        self.assertNotIn("https://discord.com", output)

    def test_cli_check_config_flag_exit_code_zero(self) -> None:
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch("sys.argv", ["neko_discord_worker.py", "--check-config"]):
                with self.assertRaises(SystemExit) as cm:
                    worker_main()
                self.assertEqual(cm.exception.code, 0)

    def test_cli_check_config_flag_exit_code_one(self) -> None:
        invalid_env = dict(self.valid_env)
        invalid_env["DISCORD_WEBHOOK_URL"] = ""
        with mock.patch.dict(os.environ, invalid_env, clear=True):
            with mock.patch("sys.argv", ["neko_discord_worker.py", "--check-config"]):
                with self.assertRaises(SystemExit) as cm:
                    worker_main()
                self.assertEqual(cm.exception.code, 1)


class TestOpsStatusDiagnostics(unittest.TestCase):
    """Verify neko_ops_status.py read-only diagnostics under all health states."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.temp_dir, "discord-state.json")

        # Create healthy state
        valid_state_dict = {
            "version": 1,
            "status_message_id": "1539165666089762837",
            "window_start_time": 1787036400,
            "window_inbound_bytes": 1000,
            "window_outbound_bytes": 2000,
            "confirmed_status": "ONLINE",
            "last_checkpoint_at": time.time(),
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(valid_state_dict, f)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _mock_service_runner(
        self,
        ss_active: str = "active",
        monitor_active: str = "active",
        worker_active: str = "active",
        legacy_active: str = "inactive",
    ):
        def runner(cmd, **kwargs):
            svc = cmd[2] if len(cmd) > 2 else ""
            if "shadowsocks" in svc:
                stdout = f"ActiveState={ss_active}\nSubState=running\nUnitFileState=enabled\nMainPID=431\nNRestarts=0\nMemoryCurrent=5566464\n"
            elif "neko-server-monitor" in svc:
                stdout = f"ActiveState={monitor_active}\nSubState=running\nUnitFileState=enabled\nMainPID=46806\nNRestarts=0\nMemoryCurrent=10731520\n"
            elif "neko-discord-worker" in svc:
                stdout = f"ActiveState={worker_active}\nSubState=running\nUnitFileState=enabled\nMainPID=50924\nNRestarts=0\nMemoryCurrent=15187968\n"
            elif "neko-traffic-monitor" in svc:
                stdout = f"ActiveState={legacy_active}\nSubState=dead\nUnitFileState=disabled\nMainPID=0\nNRestarts=0\nMemoryCurrent=\n"
            else:
                stdout = "ActiveState=unknown\n"
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout, stderr="")
        return runner

    def test_all_healthy_scenario_exit_code_zero(self) -> None:
        runner = self._mock_service_runner()
        with mock.patch("neko_ops_status.probe_tcp_listener", return_value=(True, "LISTENING")):
            with mock.patch("shutil.disk_usage", return_value=mock.Mock(total=40_000_000_000, used=4_000_000_000, free=36_000_000_000)):
                exit_code, report = neko_ops_status.run_diagnostics(
                    disk_path=self.temp_dir,
                    state_path=self.state_file,
                    state_dir=self.temp_dir,
                    service_runner=runner,
                    journal_cmd=False,
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("ALL SYSTEMS HEALTHY (0_HEALTHY)", report)
        self.assertIn("shadowsocks-libev:    ACTIVE", report)
        self.assertIn("neko-server-monitor:  ACTIVE", report)
        self.assertIn("neko-discord-worker:  ACTIVE", report)
        self.assertIn("TCP Listener :8388:  LISTENING", report)
        self.assertIn("discord-state.json:   VALID", report)

    def test_shadowsocks_inactive_causes_degraded_exit_one(self) -> None:
        runner = self._mock_service_runner(ss_active="failed")
        with mock.patch("neko_ops_status.probe_tcp_listener", return_value=(False, "CLOSED")):
            exit_code, report = neko_ops_status.run_diagnostics(
                disk_path=self.temp_dir,
                state_path=self.state_file,
                state_dir=self.temp_dir,
                service_runner=runner,
                journal_cmd=False,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("DEGRADED OPERATIONAL CONDITION (1_DEGRADED)", report)
        self.assertIn("Shadowsocks service is not active", report)
        self.assertIn("Proxy port 8388 is not listening", report)

    def test_discord_worker_inactive_causes_degraded(self) -> None:
        runner = self._mock_service_runner(worker_active="inactive")
        with mock.patch("neko_ops_status.probe_tcp_listener", return_value=(True, "LISTENING")):
            exit_code, report = neko_ops_status.run_diagnostics(
                disk_path=self.temp_dir,
                state_path=self.state_file,
                state_dir=self.temp_dir,
                service_runner=runner,
                journal_cmd=False,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("Discord Worker is not active", report)

    def test_legacy_service_unexpectedly_active_causes_degraded(self) -> None:
        runner = self._mock_service_runner(legacy_active="active")
        with mock.patch("neko_ops_status.probe_tcp_listener", return_value=(True, "LISTENING")):
            exit_code, report = neko_ops_status.run_diagnostics(
                disk_path=self.temp_dir,
                state_path=self.state_file,
                state_dir=self.temp_dir,
                service_runner=runner,
                journal_cmd=False,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("Legacy neko-traffic-monitor service is unexpectedly ACTIVE", report)

    def test_corrupt_state_json_causes_degraded(self) -> None:
        with open(self.state_file, "w", encoding="utf-8") as f:
            f.write("{invalid_json: true,")

        runner = self._mock_service_runner()
        with mock.patch("neko_ops_status.probe_tcp_listener", return_value=(True, "LISTENING")):
            exit_code, report = neko_ops_status.run_diagnostics(
                disk_path=self.temp_dir,
                state_path=self.state_file,
                state_dir=self.temp_dir,
                service_runner=runner,
                journal_cmd=False,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("Discord state file is missing or invalid JSON", report)

    def test_disk_pressure_warning_and_critical(self) -> None:
        runner = self._mock_service_runner()
        with mock.patch("neko_ops_status.probe_tcp_listener", return_value=(True, "LISTENING")):
            # 85% used -> WARNING
            with mock.patch("shutil.disk_usage", return_value=mock.Mock(total=100, used=85, free=15)):
                exit_code, report = neko_ops_status.run_diagnostics(
                    disk_path=self.temp_dir,
                    state_path=self.state_file,
                    state_dir=self.temp_dir,
                    service_runner=runner,
                    journal_cmd=False,
                )
                self.assertEqual(exit_code, 1)
                self.assertIn("WARNING band (85.0%)", report)

            # 95% used -> CRITICAL
            with mock.patch("shutil.disk_usage", return_value=mock.Mock(total=100, used=95, free=5)):
                exit_code, report = neko_ops_status.run_diagnostics(
                    disk_path=self.temp_dir,
                    state_path=self.state_file,
                    state_dir=self.temp_dir,
                    service_runner=runner,
                    journal_cmd=False,
                )
                self.assertEqual(exit_code, 1)
                self.assertIn("CRITICAL (95.0%)", report)

    def test_secret_safety_in_ops_output(self) -> None:
        runner = self._mock_service_runner()
        with mock.patch("neko_ops_status.probe_tcp_listener", return_value=(True, "LISTENING")):
            exit_code, report = neko_ops_status.run_diagnostics(
                disk_path=self.temp_dir,
                state_path=self.state_file,
                state_dir=self.temp_dir,
                service_runner=runner,
                journal_cmd=False,
            )
            self.assertEqual(exit_code, 0)
            # Ensure no secret keywords
            self.assertNotIn("DISCORD_WEBHOOK_URL", report)
            self.assertNotIn("https://discord.com", report)
            self.assertNotIn("SERVER_METRICS_INGEST_SECRET", report)
            self.assertNotIn("SHADOWSOCKS_PASSWORD", report)


if __name__ == "__main__":
    unittest.main()
