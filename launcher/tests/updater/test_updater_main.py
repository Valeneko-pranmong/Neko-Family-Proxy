from pathlib import Path
from unittest.mock import Mock

from neko_launcher.updater.activation import ActivationResult
from neko_launcher.updater.broker import ApplyResult
from neko_launcher.updater.ipc_channel import IpcMessage, IpcProtocolError, IpcTimeoutError
from neko_launcher.updater.staging_handoff import RequestReadyResult


class FakeChannel:
    def __init__(self, to_receive):
        self.to_receive = to_receive
        self.sent = []
        self.closed = False
        self.receive_count = 0

    def receive_message(self, timeout_s=None):
        if self.receive_count < len(self.to_receive):
            item = self.to_receive[self.receive_count]
            self.receive_count += 1
            if isinstance(item, Exception):
                raise item
            return item
        raise IpcProtocolError("EOF reached on IPC read handle")

    def send_message(self, type, body, message_id=None):
        self.sent.append((type, body, message_id))

    def close(self):
        self.closed = True


class FakeSlotStore:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def get_updater_main():
    from neko_launcher.updater import main as updater_main

    return updater_main


def test_serve_session_happy_path():
    updater_main = get_updater_main()

    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="BEGIN",
                body={"envelope_b64": "dummy_env"},
                message_id="msg1",
            ),
            IpcMessage(
                protocol_version=1,
                type="APPLY",
                body={"transaction_id": "tx1", "request_id": "req1"},
                message_id="msg2",
            ),
            IpcProtocolError("EOF reached on IPC read handle"),
        ]
    )

    coordinator = Mock()
    coordinator.begin.return_value = RequestReadyResult(
        accepted=True,
        request_id="req1",
        transaction_id="tx1",
        changed={"launcher": True, "core": False},
        error=None,
    )
    coordinator.apply.return_value = ApplyResult(accepted=True, transaction_id="tx1", error=None)

    result = updater_main.serve_session(channel, coordinator)

    assert result is True
    assert channel.receive_count == 3

    coordinator.begin.assert_called_once_with("dummy_env")
    coordinator.apply.assert_called_once_with("tx1", "req1")

    assert len(channel.sent) == 2

    req_ready = channel.sent[0]
    assert req_ready[0] == "REQUEST_READY"
    assert req_ready[1] == {
        "accepted": True,
        "request_id": "req1",
        "transaction_id": "tx1",
        "changed": {"launcher": True, "core": False},
        "error": None,
    }
    assert req_ready[2] == "msg1"

    app_res = channel.sent[1]
    assert app_res[0] == "APPLY_RESULT"
    assert app_res[1] == {"accepted": True, "transaction_id": "tx1", "error": None}
    assert app_res[2] == "msg2"


def test_serve_session_begin_rejected():
    updater_main = get_updater_main()

    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="BEGIN",
                body={"envelope_b64": "bad_env"},
                message_id="msg1",
            ),
            IpcProtocolError("EOF reached on IPC read handle"),
        ]
    )

    coordinator = Mock()
    coordinator.begin.return_value = RequestReadyResult(
        accepted=False,
        request_id=None,
        transaction_id=None,
        changed=None,
        error="Invalid env",
    )

    result = updater_main.serve_session(channel, coordinator)

    assert result is False
    assert channel.receive_count == 1
    coordinator.begin.assert_called_once_with("bad_env")
    coordinator.apply.assert_not_called()

    assert len(channel.sent) == 1
    req_ready = channel.sent[0]
    assert req_ready[0] == "REQUEST_READY"
    assert req_ready[1]["accepted"] is False
    assert req_ready[1]["error"] == "Invalid env"
    assert req_ready[2] == "msg1"


def test_serve_session_protocol_fail():
    updater_main = get_updater_main()

    # Subcase: invalid-order APPLY-first
    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="APPLY",
                body={"transaction_id": "tx1", "request_id": "req1"},
                message_id="msg1",
            )
        ]
    )

    coordinator = Mock()

    result = updater_main.serve_session(channel, coordinator)

    assert result is False
    coordinator.begin.assert_not_called()
    coordinator.apply.assert_not_called()

    if channel.sent:
        assert len(channel.sent) == 1
        assert channel.sent[0][1].get("accepted") is False

    # Subcase: invalid-BEGIN-body (wrong type for envelope_b64)
    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="BEGIN",
                body={"envelope_b64": 123},
                message_id="msg1",
            )
        ]
    )
    coordinator = Mock()

    result = updater_main.serve_session(channel, coordinator)

    assert result is False
    coordinator.begin.assert_not_called()
    coordinator.apply.assert_not_called()

    # Subcase: post-successful-APPLY tail raises IpcTimeoutError
    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="BEGIN",
                body={"envelope_b64": "dummy_env"},
                message_id="msg1",
            ),
            IpcMessage(
                protocol_version=1,
                type="APPLY",
                body={"transaction_id": "tx1", "request_id": "req1"},
                message_id="msg2",
            ),
            IpcTimeoutError("timeout"),
        ]
    )
    coordinator = Mock()
    coordinator.begin.return_value = RequestReadyResult(
        accepted=True,
        request_id="req1",
        transaction_id="tx1",
        changed={"launcher": True, "core": False},
        error=None,
    )
    coordinator.apply.return_value = ApplyResult(accepted=True, transaction_id="tx1", error=None)

    result = updater_main.serve_session(channel, coordinator)

    assert result is False
    coordinator.begin.assert_called_once_with("dummy_env")
    coordinator.apply.assert_called_once_with("tx1", "req1")

    # Subcase: post-successful-APPLY tail raises IpcProtocolError (non-EOF)
    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="BEGIN",
                body={"envelope_b64": "dummy_env"},
                message_id="msg1",
            ),
            IpcMessage(
                protocol_version=1,
                type="APPLY",
                body={"transaction_id": "tx1", "request_id": "req1"},
                message_id="msg2",
            ),
            IpcProtocolError("malformed"),
        ]
    )
    coordinator = Mock()
    coordinator.begin.return_value = RequestReadyResult(
        accepted=True,
        request_id="req1",
        transaction_id="tx1",
        changed={"launcher": True, "core": False},
        error=None,
    )
    coordinator.apply.return_value = ApplyResult(accepted=True, transaction_id="tx1", error=None)

    result = updater_main.serve_session(channel, coordinator)

    assert result is False
    coordinator.begin.assert_called_once_with("dummy_env")
    coordinator.apply.assert_called_once_with("tx1", "req1")

    # Subcase: post-successful-APPLY tail returns extra IpcMessage
    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="BEGIN",
                body={"envelope_b64": "dummy_env"},
                message_id="msg1",
            ),
            IpcMessage(
                protocol_version=1,
                type="APPLY",
                body={"transaction_id": "tx1", "request_id": "req1"},
                message_id="msg2",
            ),
            IpcMessage(
                protocol_version=1,
                type="EXTRA",
                message_id="msg3",
                body={},
            ),
        ]
    )
    coordinator = Mock()
    coordinator.begin.return_value = RequestReadyResult(
        accepted=True,
        request_id="req1",
        transaction_id="tx1",
        changed={"launcher": True, "core": False},
        error=None,
    )
    coordinator.apply.return_value = ApplyResult(accepted=True, transaction_id="tx1", error=None)

    result = updater_main.serve_session(channel, coordinator)

    assert result is False
    coordinator.begin.assert_called_once_with("dummy_env")
    coordinator.apply.assert_called_once_with("tx1", "req1")


def test_run_session_success(monkeypatch):
    updater_main = get_updater_main()

    monkeypatch.setattr(updater_main, "serve_session", lambda ch, coord: True)

    channel = FakeChannel([])
    store = FakeSlotStore()

    def fake_activate(root, s):
        assert channel.closed is True
        assert store.closed is False
        return ActivationResult(True, None, None)

    res = updater_main.run_session(
        root_dir=Path("/dummy"),
        public_keys={"test-key": b"\x01" * 32},
        channel=channel,
        slot_store=store,
        activate=fake_activate,
    )

    assert res == 0
    assert store.closed is True


def test_run_session_fail_closed(monkeypatch):
    updater_main = get_updater_main()

    cases = [(False, None), (True, ActivationResult(False, None, "error"))]

    for serve_success, act_result in cases:
        monkeypatch.setattr(updater_main, "serve_session", lambda ch, coord: serve_success)

        channel = FakeChannel([])
        store = FakeSlotStore()

        activate_called = False

        def fake_activate(root, s):
            nonlocal activate_called
            activate_called = True
            return act_result

        res = updater_main.run_session(
            root_dir=Path("/dummy"),
            public_keys={"test-key": b"\x01" * 32},
            channel=channel,
            slot_store=store,
            activate=fake_activate,
        )

        assert res != 0
        assert channel.closed is True
        assert store.closed is True

        if not serve_success:
            assert not activate_called
        else:
            assert activate_called


def test_cli_contract(monkeypatch, tmp_path):
    updater_main = get_updater_main()

    assert updater_main.main(["--self-check"]) == 0

    assert updater_main.main(["--session"]) != 0

    assert updater_main.main(["--root", str(tmp_path)]) != 0
