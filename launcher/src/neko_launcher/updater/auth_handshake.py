"""Broker-child authorization handshake and cold-start protocol handler."""
from __future__ import annotations

from dataclasses import asdict

from neko_launcher.updater.ipc_channel import FramedIpcChannel
from neko_launcher.updater.state_models import Generation


def execute_broker_auth_handshake(
    broker_ipc: FramedIpcChannel,
    expected_generation: Generation,
    expected_revision: int,
    expected_pid: int | None = None,
    mode: str = "managed",
    timeout_s: float = 10.0,
) -> bool:
    """Execute broker-side authorization handshake with child process."""
    try:
        hello_msg = broker_ipc.receive_message(timeout_s=timeout_s)
        if hello_msg.type != "HELLO" or hello_msg.body.get("mode") != mode:
            return False

        if expected_pid is not None and hello_msg.body.get("pid") != expected_pid:
            return False

        child_gen = hello_msg.body.get("generation")
        if child_gen != asdict(expected_generation):
            return False

        broker_ipc.send_message(
            "CONTEXT",
            {
                "generation": asdict(expected_generation),
                "transaction_id": None,
                "mode": mode,
            },
        )

        check_msg = broker_ipc.receive_message(timeout_s=timeout_s)
        expected_check_type = "LOCAL_CHECK" if mode == "managed" else "SELF_TEST"
        if check_msg.type != expected_check_type or check_msg.body.get("result") != "PASS":
            return False

        broker_ipc.send_message(
            "NORMAL_AUTH",
            {
                "generation": asdict(expected_generation),
                "revision": expected_revision,
            },
        )

        ack_msg = broker_ipc.receive_message(timeout_s=timeout_s)
        if ack_msg.type != "NORMAL_ACK" or ack_msg.body.get("revision") != expected_revision:
            return False

        return True
    except Exception:
        return False


def execute_child_auth_handshake(
    child_ipc: FramedIpcChannel,
    current_generation: Generation,
    pid: int,
    mode: str = "managed",
    timeout_s: float = 10.0,
) -> bool:
    """Execute child-side authorization handshake before normal startup or probation completion."""
    try:
        child_ipc.send_message(
            "HELLO",
            {
                "mode": mode,
                "pid": pid,
                "generation": asdict(current_generation),
            },
        )

        ctx_msg = child_ipc.receive_message(timeout_s=timeout_s)
        if ctx_msg.type != "CONTEXT":
            return False
        if ctx_msg.body.get("generation") != asdict(current_generation):
            return False

        check_type = "LOCAL_CHECK" if mode == "managed" else "SELF_TEST"
        child_ipc.send_message(
            check_type,
            {
                "generation": asdict(current_generation),
                "result": "PASS",
                "error": None,
            },
        )

        auth_msg = child_ipc.receive_message(timeout_s=timeout_s)
        if auth_msg.type != "NORMAL_AUTH":
            return False

        rev = auth_msg.body.get("revision", 0)
        child_ipc.send_message("NORMAL_ACK", {"revision": rev})
        return True
    except Exception:
        return False
