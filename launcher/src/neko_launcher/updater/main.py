import sys
from collections.abc import Mapping
from enum import Enum
from pathlib import Path

from neko_launcher.updater.activation import activate_verified_generation
from neko_launcher.updater.broker import BrokerCoordinator
from neko_launcher.updater.enrollment import validate_enrollment_trust_binding
from neko_launcher.updater.ipc_channel import FramedIpcChannel, IpcProtocolError
from neko_launcher.updater.root_validator import get_expected_install_root, validate_install_root
from neko_launcher.updater.slot_store import SlotStore
from neko_launcher.updater.trust_profile import load_installed_update_trust_profile


class SessionDisposition(Enum):
    ADMISSION_ONLY = "ADMISSION_ONLY"
    APPLY_VERIFIED = "APPLY_VERIFIED"
    FAILED = "FAILED"


def serve_session(channel, coordinator) -> SessionDisposition:
    try:
        msg = channel.receive_message(timeout_s=5.0)
        if msg.type == "ADMIT_AUTHORITY":
            if not isinstance(msg.body, dict) or set(msg.body.keys()) != {"envelope_b64"}:
                return SessionDisposition.FAILED
            envelope_b64 = msg.body["envelope_b64"]
            if not isinstance(envelope_b64, str) or not envelope_b64:
                return SessionDisposition.FAILED

            admit_res = coordinator.admit_authority(envelope_b64)
            if admit_res.accepted and admit_res.binding is not None:
                channel.send_message(
                    "AUTHORITY_ADMITTED",
                    message_id=msg.message_id,
                    body={
                        "accepted": True,
                        "release_sequence": admit_res.binding.release_sequence,
                        "release_id": admit_res.binding.release_id,
                        "payload_sha256": admit_res.binding.payload_sha256,
                        "changed": admit_res.changed,
                        "error": None,
                    },
                )
                try:
                    channel.receive_message(timeout_s=5.0)
                    return SessionDisposition.FAILED
                except IpcProtocolError as e:
                    if str(e) == "EOF reached on IPC read handle":
                        return SessionDisposition.ADMISSION_ONLY
                    return SessionDisposition.FAILED
                except Exception:
                    return SessionDisposition.FAILED
            else:
                channel.send_message(
                    "AUTHORITY_ADMITTED",
                    message_id=msg.message_id,
                    body={
                        "accepted": False,
                        "release_sequence": None,
                        "release_id": None,
                        "payload_sha256": None,
                        "changed": False,
                        "error": admit_res.error,
                    },
                )
                return SessionDisposition.FAILED

        elif msg.type == "BEGIN":
            if not isinstance(msg.body, dict) or set(msg.body.keys()) != {"envelope_b64"}:
                return SessionDisposition.FAILED
            envelope_b64 = msg.body["envelope_b64"]
            if not isinstance(envelope_b64, str) or not envelope_b64:
                return SessionDisposition.FAILED

            begin_res = coordinator.begin(envelope_b64)
            channel.send_message(
                "REQUEST_READY",
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
                return SessionDisposition.FAILED

            msg2 = channel.receive_message(timeout_s=5.0)
            if msg2.type != "APPLY":
                return SessionDisposition.FAILED
            if not isinstance(msg2.body, dict) or set(msg2.body.keys()) != {"transaction_id", "request_id"}:
                return SessionDisposition.FAILED
            tx_id = msg2.body["transaction_id"]
            req_id = msg2.body["request_id"]
            if not isinstance(tx_id, str) or not tx_id:
                return SessionDisposition.FAILED
            if not isinstance(req_id, str) or not req_id:
                return SessionDisposition.FAILED

            apply_res = coordinator.apply(tx_id, req_id)
            channel.send_message(
                "APPLY_RESULT",
                message_id=msg2.message_id,
                body={
                    "accepted": apply_res.accepted,
                    "transaction_id": apply_res.transaction_id,
                    "error": apply_res.error,
                },
            )
            if not apply_res.accepted:
                return SessionDisposition.FAILED

            try:
                channel.receive_message(timeout_s=5.0)
                return SessionDisposition.FAILED
            except IpcProtocolError as e:
                if str(e) == "EOF reached on IPC read handle":
                    return SessionDisposition.APPLY_VERIFIED
                return SessionDisposition.FAILED
            except Exception:
                return SessionDisposition.FAILED

        return SessionDisposition.FAILED

    except Exception:
        return SessionDisposition.FAILED


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

    disposition = SessionDisposition.FAILED
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
        disposition = serve_session(channel, coordinator)
    except Exception:
        disposition = SessionDisposition.FAILED
    finally:
        if channel is not None:
            try:
                channel.close()
            except Exception:
                pass

    if disposition == SessionDisposition.ADMISSION_ONLY:
        if slot_store is not None:
            try:
                slot_store.close()
            except Exception:
                pass
        return 0

    if disposition != SessionDisposition.APPLY_VERIFIED:
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
        try:
            root_dir = get_expected_install_root()
            val_res = validate_install_root(root_dir)
            if not val_res.valid:
                return 1
            profile = load_installed_update_trust_profile(root_dir)
            validate_enrollment_trust_binding(root_dir, profile)
        except Exception:
            return 1

        return run_session(root_dir, profile.release_public_keys)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())