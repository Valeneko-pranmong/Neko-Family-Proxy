import os
import threading

from neko_launcher.updater.auth_handshake import (
    execute_broker_auth_handshake,
    execute_child_auth_handshake,
)
from neko_launcher.updater.ipc_channel import FramedIpcChannel
from neko_launcher.updater.state_models import Binding, Generation


def _make_dummy_gen(seq: int) -> Generation:
    return Generation(
        binding=Binding(release_sequence=seq, release_id=f"r-{seq}", payload_sha256=f"{seq:064x}"),
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )


def test_managed_cold_start_handshake_success() -> None:
    r_b, w_c = os.pipe()  # Child writes to w_c, broker reads from r_b
    r_c, w_b = os.pipe()  # Broker writes to w_b, child reads from r_c

    broker_ipc = FramedIpcChannel(read_handle=r_b, write_handle=w_b)
    child_ipc = FramedIpcChannel(read_handle=r_c, write_handle=w_c)

    gen = _make_dummy_gen(1)
    broker_result = [False]
    child_result = [False]

    def _broker_thread():
        broker_result[0] = execute_broker_auth_handshake(
            broker_ipc,
            expected_generation=gen,
            expected_revision=5,
            mode="managed",
            timeout_s=2.0,
        )

    def _child_thread():
        child_result[0] = execute_child_auth_handshake(
            child_ipc,
            current_generation=gen,
            pid=1234,
            mode="managed",
            timeout_s=2.0,
        )

    t_b = threading.Thread(target=_broker_thread)
    t_c = threading.Thread(target=_child_thread)

    t_b.start()
    t_c.start()
    t_b.join()
    t_c.join()

    broker_ipc.close()
    child_ipc.close()

    assert broker_result[0] is True
    assert child_result[0] is True
