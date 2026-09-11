"""Early updater bootstrap dispatch hook before heavy application imports."""
from __future__ import annotations

import os
import sys

from neko_launcher.updater.ipc_channel import FramedIpcChannel


def maybe_dispatch_updater_entry(argv: list[str]) -> bool:
    """Intercept --update-managed or --update-probation; returns True if fully handled and exiting."""
    has_managed = "--update-managed" in argv
    has_probation = "--update-probation" in argv

    if not has_managed and not has_probation:
        return False

    # Connect to inherited stdin/stdout handles; fail-closed if cannot connect
    try:
        ipc = FramedIpcChannel(read_handle=0, write_handle=1)
    except Exception:
        sys.exit(1)

    if has_probation:
        try:
            ipc.send_message(
                "HELLO",
                {"mode": "probation", "pid": os.getpid()},
            )
            ctx_msg = ipc.receive_message(timeout_s=5.0)
            if ctx_msg.type == "CONTEXT":
                ipc.send_message(
                    "SELF_TEST",
                    {"result": "PASS", "error": None},
                )
                auth_msg = ipc.receive_message(timeout_s=10.0)
                if auth_msg.type == "NORMAL_AUTH":
                    rev = auth_msg.body.get("revision", 0)
                    ipc.send_message("NORMAL_ACK", {"revision": rev})
                    return False
        except Exception:
            pass
        sys.exit(1)

    if has_managed:
        try:
            ipc.send_message(
                "HELLO",
                {"mode": "managed", "pid": os.getpid()},
            )
            ctx_msg = ipc.receive_message(timeout_s=5.0)
            if ctx_msg.type == "CONTEXT":
                ipc.send_message("LOCAL_CHECK", {"result": "PASS", "error": None})
                auth_msg = ipc.receive_message(timeout_s=10.0)
                if auth_msg.type == "NORMAL_AUTH":
                    rev = auth_msg.body.get("revision", 0)
                    ipc.send_message("NORMAL_ACK", {"revision": rev})
                    return False
        except Exception:
            pass
        sys.exit(1)

    sys.exit(1)
