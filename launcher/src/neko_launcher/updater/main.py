import sys
from collections.abc import Mapping
from pathlib import Path

from neko_launcher.updater.activation import activate_verified_generation
from neko_launcher.updater.broker import BrokerCoordinator
from neko_launcher.updater.ipc_channel import FramedIpcChannel, IpcProtocolError
from neko_launcher.updater.root_validator import get_expected_install_root, validate_install_root
from neko_launcher.updater.slot_store import SlotStore

PRODUCTION_RELEASE_PUBLIC_KEYS: Mapping[str, bytes] = {}


def serve_session(channel, coordinator) -> bool:
    try:
        msg = channel.receive_message(timeout_s=5.0)
        if msg.type != "BEGIN":
            return False
        if not isinstance(msg.body, dict) or set(msg.body.keys()) != {"envelope_b64"}:
            return False
        envelope_b64 = msg.body["envelope_b64"]
        if not isinstance(envelope_b64, str) or not envelope_b64:
            return False

        begin_res = coordinator.begin(envelope_b64)
        channel.send_message(
            type="REQUEST_READY",
            message_id=msg.message_id,
            body={
                "accepted": begin_res.accepted,
                "request_id": begin_res.request_id,
                "transaction_id": begin_res.transaction_id,
                "changed": begin_res.changed,
                "error": begin_res.error,
            },
        )
        if not begin_res.accepted:
            return False

        msg2 = channel.receive_message(timeout_s=5.0)
        if msg2.type != "APPLY":
            return False
        if not isinstance(msg2.body, dict) or set(msg2.body.keys()) != {"transaction_id", "request_id"}:
            return False
        tx_id = msg2.body["transaction_id"]
        req_id = msg2.body["request_id"]
        if not isinstance(tx_id, str) or not tx_id:
            return False
        if not isinstance(req_id, str) or not req_id:
            return False

        apply_res = coordinator.apply(tx_id, req_id)
        channel.send_message(
            type="APPLY_RESULT",
            message_id=msg2.message_id,
            body={
                "accepted": apply_res.accepted,
                "transaction_id": apply_res.transaction_id,
                "error": apply_res.error,
            },
        )
        if not apply_res.accepted:
            return False

        try:
            channel.receive_message(timeout_s=5.0)
            return False
        except IpcProtocolError as e:
            if str(e) == "EOF reached on IPC read handle":
                return True
            return False
        except Exception:
            return False

    except Exception:
        return False


def run_session(
    root_dir: Path,
    public_keys: Mapping[str, bytes],
    *,
    channel=None,
    slot_store=None,
    activate=activate_verified_generation,
) -> int:
    if not public_keys:
        return 2

    served = False
    try:
        if channel is None:
            channel = FramedIpcChannel(read_handle=0, write_handle=1)
        if slot_store is None:
            slot_store = SlotStore(
                root_dir / "state" / "slot-a.bin",
                root_dir / "state" / "slot-b.bin",
                public_keys,
            )

        coordinator = BrokerCoordinator(root_dir, slot_store, public_keys)
        served = serve_session(channel, coordinator)
    except Exception:
        served = False
    finally:
        if channel is not None:
            try:
                channel.close()
            except Exception:
                pass

    if not served:
        if slot_store is not None:
            try:
                slot_store.close()
            except Exception:
                pass
        return 1

    try:
        act_res = activate(root_dir, slot_store)
        return 0 if act_res.committed else 1
    except Exception:
        return 1
    finally:
        if slot_store is not None:
            try:
                slot_store.close()
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    sys.stdout = sys.stderr
    if argv is None:
        argv = sys.argv[1:]

    if argv == ["--self-check"]:
        return 0

    if argv == ["--session"]:
        if not PRODUCTION_RELEASE_PUBLIC_KEYS:
            return 2

        try:
            root_dir = get_expected_install_root()
            val_res = validate_install_root(root_dir)
            if not val_res.valid:
                return 1
        except Exception:
            return 1

        return run_session(root_dir, PRODUCTION_RELEASE_PUBLIC_KEYS)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())