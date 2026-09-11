import os

from neko_launcher.updater.ipc_channel import (
    FramedIpcChannel,
)


def test_send_and_receive_frame() -> None:
    r1, w1 = os.pipe()
    r2, w2 = os.pipe()
    ch1 = FramedIpcChannel(read_handle=r1, write_handle=w2)
    ch2 = FramedIpcChannel(read_handle=r2, write_handle=w1)

    try:
        msg_id = ch1.send_message("HELLO", {"mode": "managed", "pid": 1234})
        received = ch2.receive_message(timeout_s=1.0)
        assert received.type == "HELLO"
        assert received.message_id == msg_id
        assert received.body["pid"] == 1234
    finally:
        ch1.close()
        ch2.close()
