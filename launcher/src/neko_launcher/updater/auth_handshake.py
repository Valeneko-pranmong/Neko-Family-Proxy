"""Broker-child authorization handshake and cold-start protocol handler."""
from __future__ import annotations

from neko_launcher.updater.ipc_channel import FramedIpcChannel
from neko_launcher.updater.state_models import Generation, State


def execute_broker_auth_handshake(
    broker_ipc: FramedIpcChannel,
    expected_generation: Generation,
    expected_revision: int,
    mode: str = "managed",
    timeout_s: float = 10.0,
) -> bool:
    """Execute broker-side authorization handshake with child process."""
    raise NotImplementedError("execute_broker_auth_handshake not implemented")


def execute_child_auth_handshake(
    child_ipc: FramedIpcChannel,
    current_generation: Generation,
    pid: int,
    mode: str = "managed",
    timeout_s: float = 10.0,
) -> bool:
    """Execute child-side authorization handshake before normal startup or probation completion."""
    raise NotImplementedError("execute_child_auth_handshake not implemented")
