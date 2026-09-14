from __future__ import annotations

import base64
import subprocess
from pathlib import Path
from unittest.mock import Mock


from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
)
try:
    from neko_launcher.infrastructure.software_update_authority_admission import (
        AuthorityAdmissionResult,
        SoftwareUpdateAuthorityAdmissionService,
    )
except ImportError:
    AuthorityAdmissionResult = None  # type: ignore[assignment, misc]
    SoftwareUpdateAuthorityAdmissionService = None  # type: ignore[assignment, misc]
from neko_launcher.updater.ipc_channel import (
    IpcMessage,
    IpcProtocolError,
    IpcTimeoutError,
)


class FakeChannel:
    def __init__(self, to_receive: list[object] | None = None) -> None:
        self.to_receive = to_receive or []
        self.sent: list[tuple[str, dict[str, object], str | None]] = []
        self.closed = False
        self.receive_count = 0

    def receive_message(self, timeout_s: float | None = None) -> IpcMessage:
        if self.receive_count < len(self.to_receive):
            item = self.to_receive[self.receive_count]
            self.receive_count += 1
            if isinstance(item, Exception):
                raise item
            assert isinstance(item, IpcMessage)
            return item
        raise IpcProtocolError("EOF reached on IPC read handle")

    def send_message(
        self,
        msg_type: str,
        body: dict[str, object],
        message_id: str | None = None,
    ) -> str:
        mid = message_id or "msg_1"
        self.sent.append((msg_type, body, mid))
        return mid

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.stdin = Mock()
        self.stdout = Mock()
        self.stderr = Mock()
        self.stdin.fileno.return_value = 10
        self.stdout.fileno.return_value = 11
        self.terminated = False
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        return self.exit_code

    def poll(self) -> int:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def test_authority_admission_result_dataclass() -> None:
    binding = AuthenticatedReleaseBinding(2, "r2", "a" * 64)
    res = AuthorityAdmissionResult(
        accepted=True,
        binding=binding,
        changed=True,
        error=None,
    )
    assert res.accepted is True
    assert res.binding == binding
    assert res.changed is True
    assert res.error is None


def test_admit_spawns_helper_with_exact_session_flag_and_no_trust_args(
    tmp_path: Path,
) -> None:
    spawn_cmds: list[list[str]] = []
    process = FakeProcess(exit_code=0)

    def fake_spawner(cmd: list[str], **kwargs: object) -> FakeProcess:
        spawn_cmds.append(cmd)
        return process

    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="AUTHORITY_ADMITTED",
                body={
                    "accepted": True,
                    "release_sequence": 2,
                    "release_id": "r2-stable",
                    "payload_sha256": "b" * 64,
                    "changed": True,
                    "error": None,
                },
                message_id="msg_1",
            ),
        ]
    )

    service = SoftwareUpdateAuthorityAdmissionService(
        root_dir=tmp_path,
        spawner=fake_spawner,
        channel_factory=lambda: channel,
    )

    envelope_bytes = b'{"test": "envelope"}'
    res = service.admit(envelope_bytes)

    assert len(spawn_cmds) == 1
    expected_exe = str(tmp_path / "NekoUpdater.exe")
    assert spawn_cmds[0] == [expected_exe, "--session"]
    # No trust, key, sequence, or path argument on argv!
    assert len(spawn_cmds[0]) == 2

    assert res.accepted is True
    assert res.binding == AuthenticatedReleaseBinding(2, "r2-stable", "b" * 64)
    assert res.changed is True
    assert res.error is None
    assert channel.closed is True


def test_admit_sends_admit_authority_and_receives_authority_admitted(
    tmp_path: Path,
) -> None:
    process = FakeProcess(exit_code=0)
    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="AUTHORITY_ADMITTED",
                body={
                    "accepted": True,
                    "release_sequence": 3,
                    "release_id": "r3-stable",
                    "payload_sha256": "c" * 64,
                    "changed": False,
                    "error": None,
                },
                message_id="msg_1",
            ),
        ]
    )

    service = SoftwareUpdateAuthorityAdmissionService(
        root_dir=tmp_path,
        spawner=lambda cmd, **kwargs: process,
        channel_factory=lambda: channel,
    )

    env_bytes = b"exact-envelope-bytes"
    res = service.admit(env_bytes)

    assert res.accepted is True
    assert res.changed is False
    assert res.binding == AuthenticatedReleaseBinding(3, "r3-stable", "c" * 64)

    assert len(channel.sent) == 1
    sent_type, sent_body, _ = channel.sent[0]
    assert sent_type == "ADMIT_AUTHORITY"
    assert sent_body == {
        "envelope_b64": base64.b64encode(env_bytes).decode("ascii")
    }


def test_admit_fail_closed_on_rejection(tmp_path: Path) -> None:
    process = FakeProcess(exit_code=1)
    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="AUTHORITY_ADMITTED",
                body={
                    "accepted": False,
                    "release_sequence": None,
                    "release_id": None,
                    "payload_sha256": None,
                    "changed": False,
                    "error": "DOWNGRADE_REJECTED",
                },
                message_id="msg_1",
            ),
        ]
    )

    service = SoftwareUpdateAuthorityAdmissionService(
        root_dir=tmp_path,
        spawner=lambda cmd, **kwargs: process,
        channel_factory=lambda: channel,
    )

    res = service.admit(b"env")
    assert res.accepted is False
    assert res.binding is None
    assert res.changed is False
    assert res.error == "DOWNGRADE_REJECTED"


def test_admit_fail_closed_on_nonzero_exit_despite_accepted_body(
    tmp_path: Path,
) -> None:
    process = FakeProcess(exit_code=1)  # Helper crashes or exits nonzero!
    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="AUTHORITY_ADMITTED",
                body={
                    "accepted": True,
                    "release_sequence": 2,
                    "release_id": "r2-stable",
                    "payload_sha256": "b" * 64,
                    "changed": True,
                    "error": None,
                },
                message_id="msg_1",
            ),
        ]
    )

    service = SoftwareUpdateAuthorityAdmissionService(
        root_dir=tmp_path,
        spawner=lambda cmd, **kwargs: process,
        channel_factory=lambda: channel,
    )

    res = service.admit(b"env")
    assert res.accepted is False
    assert res.binding is None
    assert res.error is not None


def test_admit_fail_closed_on_process_timeout(tmp_path: Path) -> None:
    class TimeoutProcess(FakeProcess):
        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd=["NekoUpdater.exe"], timeout=5.0)

    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="AUTHORITY_ADMITTED",
                body={
                    "accepted": True,
                    "release_sequence": 2,
                    "release_id": "r2-stable",
                    "payload_sha256": "b" * 64,
                    "changed": True,
                    "error": None,
                },
                message_id="msg_1",
            ),
        ]
    )

    proc = TimeoutProcess()
    service = SoftwareUpdateAuthorityAdmissionService(
        root_dir=tmp_path,
        spawner=lambda cmd, **kwargs: proc,
        channel_factory=lambda: channel,
    )

    res = service.admit(b"env")
    assert res.accepted is False
    assert res.binding is None
    assert proc.killed is True


def test_admit_fail_closed_on_response_timeout(tmp_path: Path) -> None:
    channel = FakeChannel([IpcTimeoutError("Timeout waiting for message")])
    process = FakeProcess(exit_code=0)

    service = SoftwareUpdateAuthorityAdmissionService(
        root_dir=tmp_path,
        spawner=lambda cmd, **kwargs: process,
        channel_factory=lambda: channel,
    )

    res = service.admit(b"env")
    assert res.accepted is False
    assert res.binding is None


def test_admit_fail_closed_on_malformed_response(tmp_path: Path) -> None:
    channel = FakeChannel(
        [
            IpcMessage(
                protocol_version=1,
                type="AUTHORITY_ADMITTED",
                body={
                    "accepted": True,
                    # Missing release_sequence, release_id, payload_sha256
                    "extra_key": "forbidden",
                },
                message_id="msg_1",
            ),
        ]
    )
    process = FakeProcess(exit_code=0)

    service = SoftwareUpdateAuthorityAdmissionService(
        root_dir=tmp_path,
        spawner=lambda cmd, **kwargs: process,
        channel_factory=lambda: channel,
    )

    res = service.admit(b"env")
    assert res.accepted is False
    assert res.binding is None


def test_admit_fail_closed_on_premature_eof(tmp_path: Path) -> None:
    channel = FakeChannel([IpcProtocolError("EOF reached on IPC read handle")])
    process = FakeProcess(exit_code=1)

    service = SoftwareUpdateAuthorityAdmissionService(
        root_dir=tmp_path,
        spawner=lambda cmd, **kwargs: process,
        channel_factory=lambda: channel,
    )

    res = service.admit(b"env")
    assert res.accepted is False
    assert res.binding is None
