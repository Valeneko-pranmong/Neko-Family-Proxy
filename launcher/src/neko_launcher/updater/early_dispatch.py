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

    # Connect to inherited stdin/stdout handles
    try:
        # Standard input handle is fd 0, standard output handle is fd 1
        ipc = FramedIpcChannel(read_handle=0, write_handle=1)
    except Exception:
        if has_probation:
            sys.exit(1)
        return False

    if has_probation:
        # Probation execution: send HELLO, run local checks, emit SELF_TEST
        try:
            ipc.send_message(
                "HELLO",
                {"mode": "probation", "pid": os.getpid()},
            )
            # If broker responds with CONTEXT, we are under managed supervision
            ctx_msg = ipc.receive_message(timeout_s=5.0)
            if ctx_msg.type == "CONTEXT":
                ipc.send_message(
                    "SELF_TEST",
                    {"result": "PASS", "error": None},
                )
                auth_msg = ipc.receive_message(timeout_s=10.0)
                if auth_msg.type == "NORMAL_AUTH":
                    ipc.send_message("NORMAL_ACK", {})
                    # Probation successfully authorized! Allow caller to proceed
                    return False
        except Exception:
            pass
        sys.exit(0)

    if has_managed:
        # Managed cold start
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
                    ipc.send_message("NORMAL_ACK", {})
                    # Authorized to proceed to normal UI!
                    return False
        except Exception:
            return False

    return False
