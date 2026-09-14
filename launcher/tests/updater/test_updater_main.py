import sys
from pathlib import Path
from types import SimpleNamespace
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

    assert result == updater_main.SessionDisposition.APPLY_VERIFIED
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


def test_serve_session_uses_real_send_message_api():
    updater_main = get_updater_main()

    class StrictSendChannel(FakeChannel):
        def send_message(self, msg_type, body, message_id=None):
            self.sent.append((msg_type, body, message_id))

    channel = StrictSendChannel(
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
    coordinator.apply.return_value = ApplyResult(
        accepted=True, transaction_id="tx1", error=None
    )

    result = updater_main.serve_session(channel, coordinator)

    assert result == updater_main.SessionDisposition.APPLY_VERIFIED
    assert [message[0] for message in channel.sent] == ["REQUEST_READY", "APPLY_RESULT"]


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

    assert result == updater_main.SessionDisposition.FAILED
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

    assert result == updater_main.SessionDisposition.FAILED
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

    assert result == updater_main.SessionDisposition.FAILED
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

    assert result == updater_main.SessionDisposition.FAILED
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

    assert result == updater_main.SessionDisposition.FAILED
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

    assert result == updater_main.SessionDisposition.FAILED
    coordinator.begin.assert_called_once_with("dummy_env")
    coordinator.apply.assert_called_once_with("tx1", "req1")


def test_run_session_success(monkeypatch):
    updater_main = get_updater_main()

    monkeypatch.setattr(updater_main, "serve_session", lambda ch, coord: updater_main.SessionDisposition.APPLY_VERIFIED)

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

    cases = [
        (updater_main.SessionDisposition.FAILED, None),
        (updater_main.SessionDisposition.APPLY_VERIFIED, ActivationResult(False, None, "error")),
    ]

    for serve_disposition, act_result in cases:
        monkeypatch.setattr(updater_main, "serve_session", lambda ch, coord: serve_disposition)

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

        if serve_disposition == updater_main.SessionDisposition.FAILED:
            assert not activate_called
        else:
            assert activate_called



def test_cli_contract(monkeypatch, tmp_path):
    updater_main = get_updater_main()

    assert updater_main.main(["--self-check"]) == 0

    assert updater_main.main(["--session"]) != 0

    assert updater_main.main(["--root", str(tmp_path)]) != 0

    original_stdout = sys.stdout
    class FakeVerifiedProfile:
        release_public_keys = {"prod": b"\x02" * 32}

    monkeypatch.setattr(
        updater_main,
        "load_installed_update_trust_profile",
        lambda root: FakeVerifiedProfile(),
    )
    monkeypatch.setattr(
        updater_main,
        "validate_enrollment_trust_binding",
        lambda root, prof: None,
    )
    monkeypatch.setattr(
        updater_main,
        "get_expected_install_root",
        lambda: tmp_path / "install",
    )
    monkeypatch.setattr(
        updater_main,
        "validate_install_root",
        lambda root: SimpleNamespace(valid=True),
    )

    run_session_called = 0

    def fake_run_session(root, keys):
        nonlocal run_session_called
        assert sys.stdout is sys.stderr
        run_session_called += 1
        return 0

    monkeypatch.setattr(updater_main, "run_session", fake_run_session)

    try:
        assert updater_main.main(["--session"]) == 0
        assert run_session_called == 1
    finally:
        sys.stdout = original_stdout


def test_packaged_helper_does_not_embed_production_release_keys():
    updater_main = get_updater_main()
    assert not hasattr(updater_main, "PRODUCTION_RELEASE_PUBLIC_KEYS"), (
        "Packaged helper main must not import or embed PRODUCTION_RELEASE_PUBLIC_KEYS"
    )


def test_packaged_session_resolves_keys_from_fixed_verified_profile_and_pin(monkeypatch, tmp_path):
    updater_main = get_updater_main()
    root_dir = tmp_path / "install"
    monkeypatch.setattr(updater_main, "get_expected_install_root", lambda: root_dir)
    monkeypatch.setattr(updater_main, "validate_install_root", lambda r: SimpleNamespace(valid=True))

    profile_loaded = False
    binding_validated = False

    class FakeVerifiedProfile:
        release_public_keys = {"verified-key": b"\x05" * 32}

    def fake_load_profile(root):
        nonlocal profile_loaded
        assert root == root_dir
        profile_loaded = True
        return FakeVerifiedProfile()

    def fake_validate_binding(root, profile):
        nonlocal binding_validated
        assert root == root_dir
        assert profile.release_public_keys == {"verified-key": b"\x05" * 32}
        binding_validated = True

    passed_keys = None

    def fake_run_session(root, keys):
        nonlocal passed_keys
        passed_keys = keys
        return 0

    monkeypatch.setattr(updater_main, "load_installed_update_trust_profile", fake_load_profile, raising=False)
    monkeypatch.setattr(updater_main, "validate_enrollment_trust_binding", fake_validate_binding, raising=False)
    monkeypatch.setattr(updater_main, "run_session", fake_run_session)

    res = updater_main.main(["--session"])
    assert res == 0
    assert profile_loaded is True
    assert binding_validated is True
    assert passed_keys == {"verified-key": b"\x05" * 32}


def test_session_disposition_enum():
    updater_main = get_updater_main()
    assert hasattr(updater_main, "SessionDisposition")
    SD = updater_main.SessionDisposition
    assert hasattr(SD, "ADMISSION_ONLY")
    assert hasattr(SD, "APPLY_VERIFIED")
    assert hasattr(SD, "FAILED")


def test_serve_session_admit_authority_success():
    updater_main = get_updater_main()
    from neko_launcher.updater.staging_handoff import AuthorityAdmissionResponse
    from neko_launcher.updater.state_models import Binding

    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="ADMIT_AUTHORITY",
                body={"envelope_b64": "dummy_env"},
                message_id="msg_admit_1",
            ),
            IpcProtocolError("EOF reached on IPC read handle"),
        ]
    )

    coordinator = Mock()
    coordinator.admit_authority.return_value = AuthorityAdmissionResponse(
        accepted=True,
        binding=Binding(2, "rel-2", "2" * 64),
        changed=True,
        error=None,
    )

    disposition = updater_main.serve_session(channel, coordinator)
    assert disposition == updater_main.SessionDisposition.ADMISSION_ONLY
    coordinator.admit_authority.assert_called_once_with("dummy_env")

    assert len(channel.sent) == 1
    admitted_msg = channel.sent[0]
    assert admitted_msg[0] == "AUTHORITY_ADMITTED"
    assert admitted_msg[1] == {
        "accepted": True,
        "release_sequence": 2,
        "release_id": "rel-2",
        "payload_sha256": "2" * 64,
        "changed": True,
        "error": None,
    }
    assert admitted_msg[2] == "msg_admit_1"


def test_serve_session_admit_authority_rejection():
    updater_main = get_updater_main()
    from neko_launcher.updater.staging_handoff import AuthorityAdmissionResponse

    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="ADMIT_AUTHORITY",
                body={"envelope_b64": "dummy_env"},
                message_id="msg_admit_2",
            ),
        ]
    )

    coordinator = Mock()
    coordinator.admit_authority.return_value = AuthorityAdmissionResponse(
        accepted=False,
        binding=None,
        changed=False,
        error="DOWNGRADE_REJECTED",
    )

    disposition = updater_main.serve_session(channel, coordinator)
    assert disposition == updater_main.SessionDisposition.FAILED

    assert len(channel.sent) == 1
    admitted_msg = channel.sent[0]
    assert admitted_msg[0] == "AUTHORITY_ADMITTED"
    assert admitted_msg[1] == {
        "accepted": False,
        "release_sequence": None,
        "release_id": None,
        "payload_sha256": None,
        "changed": False,
        "error": "DOWNGRADE_REJECTED",
    }


def test_run_session_admission_only_skips_activation(tmp_path):
    updater_main = get_updater_main()

    channel = FakeChannel([])
    slot_store = FakeSlotStore()
    activate_mock = Mock()

    from unittest.mock import patch
    with patch.object(updater_main, "serve_session", return_value=updater_main.SessionDisposition.ADMISSION_ONLY):
        exit_code = updater_main.run_session(
            tmp_path,
            {"k": b"v" * 32},
            channel=channel,
            slot_store=slot_store,
            activate=activate_mock,
        )

    assert exit_code == 0
    assert channel.closed is True
    assert slot_store.closed is True
    activate_mock.assert_not_called()


def test_run_session_apply_verified_activates(tmp_path):
    updater_main = get_updater_main()

    channel = FakeChannel([])
    slot_store = FakeSlotStore()
    activate_mock = Mock(return_value=ActivationResult(committed=True, generation=None, error=None))

    from unittest.mock import patch
    with patch.object(updater_main, "serve_session", return_value=updater_main.SessionDisposition.APPLY_VERIFIED):
        exit_code = updater_main.run_session(
            tmp_path,
            {"k": b"v" * 32},
            channel=channel,
            slot_store=slot_store,
            activate=activate_mock,
        )

    assert exit_code == 0
    assert channel.closed is True
    assert slot_store.closed is True
    activate_mock.assert_called_once_with(tmp_path, slot_store)
