from pathlib import Path
from typing import Any

from neko_launcher.updater.activation import activate_verified_generation
from neko_launcher.updater.binary_frame import SlotFrame, pack_slot_frame
from neko_launcher.updater.broker import BrokerCoordinator
from neko_launcher.updater.ipc_channel import IpcMessage, IpcProtocolError
from neko_launcher.updater.main import run_session
from neko_launcher.updater.probation_runner import SelfTestResult
from neko_launcher.updater.recovery_engine import RecoveryEngine
from neko_launcher.updater.state_models import serialize_state
from tests.updater.test_broker_balanced import Env, FakeSlotStore


class ClosableStore(FakeSlotStore):
    def __init__(self, initial_state: Any = None) -> None:
        super().__init__(initial_state)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class SessionChannel:
    def __init__(self, env: Env) -> None:
        self.env = env
        self.closed = False
        self.receive_count = 0
        self.sent: list[IpcMessage] = []
        self.request_id: str | None = None
        self.transaction_id: str | None = None

    def send_message(self, type: str, body: dict[str, Any], message_id: str | None = None) -> str:
        mid = message_id or f"msg-{len(self.sent)}"
        msg = IpcMessage(protocol_version=1, type=type, message_id=mid, body=body)
        self.sent.append(msg)
        if type == "REQUEST_READY" and body.get("accepted"):
            self.request_id = body.get("request_id")
            self.transaction_id = body.get("transaction_id")
        return mid

    def receive_message(self, timeout_s: float = 5.0) -> IpcMessage:
        if self.closed:
            raise IpcProtocolError("EOF reached on IPC read handle")

        if self.receive_count == 0:
            self.receive_count += 1
            return IpcMessage(
                protocol_version=1,
                type="BEGIN",
                message_id="begin-1",
                body={"envelope_b64": self.env.envelope_b64},
            )
        elif self.receive_count == 1:
            self.receive_count += 1
            assert self.request_id is not None
            assert self.transaction_id is not None
            self.env.populate_incoming(self.request_id)
            return IpcMessage(
                protocol_version=1,
                type="APPLY",
                message_id="apply-1",
                body={"request_id": self.request_id, "transaction_id": self.transaction_id},
            )
        else:
            self.receive_count += 1
            raise IpcProtocolError("EOF reached on IPC read handle")

    def close(self) -> None:
        self.closed = True


def test_balanced_live_update_success_matrix(tmp_path: Path) -> None:
    cases = [
        (True, False, "launcher-only"),
        (False, True, "core-only"),
        (True, True, "both"),
        (False, False, "metadata-only"),
    ]

    for launcher_changed, core_changed, name in cases:
        case_root = tmp_path / name
        case_root.mkdir()
        env = Env(case_root, launcher_changed=launcher_changed, core_changed=core_changed)
        store = ClosableStore(env.state)
        env.store = store
        channel = SessionChannel(env)

        def pass_activation(root_dir: Path, slot_store: Any) -> Any:
            return activate_verified_generation(
                root_dir,
                slot_store,
                self_test=lambda path: SelfTestResult(passed=True),
            )

        rc = run_session(
            case_root,
            env.keys,
            channel=channel,
            slot_store=store,
            activate=pass_activation,
        )

        assert rc == 0
        assert channel.closed is True
        assert store.closed is True

        assert len(channel.sent) >= 2
        assert channel.sent[0].type == "REQUEST_READY"
        assert channel.sent[0].body["accepted"] is True
        assert channel.sent[0].body["changed"] == {
            "launcher": launcher_changed,
            "core": core_changed,
        }

        assert channel.sent[1].type == "APPLY_RESULT"
        assert channel.sent[1].body["accepted"] is True

        state = store.state
        assert state is not None
        assert state.phase == "CLEANING"
        assert state.committed == env.candidate
        assert state.previous == env.old
        assert state.highwater == env.candidate.binding
        assert state.observed == env.candidate.binding
        assert state.failed is None
        assert state.transaction is None

        seq = env.candidate.binding.release_sequence
        sha = env.candidate.binding.payload_sha256
        published_dir = case_root / "releases" / f"g-{seq:020d}-{sha}"
        assert published_dir.is_dir()
        assert (published_dir / "release-envelope.json").is_file()
        assert (published_dir / "NekoLauncher.exe").is_file()
        assert (published_dir / "ProxyCore").is_dir()


def test_balanced_live_update_broken_candidate(tmp_path: Path) -> None:
    env = Env(tmp_path, launcher_changed=True, core_changed=True)
    store = ClosableStore(env.state)
    env.store = store
    channel = SessionChannel(env)

    def fail_activation(root_dir: Path, slot_store: Any) -> Any:
        return activate_verified_generation(
            root_dir,
            slot_store,
            self_test=lambda path: SelfTestResult(
                False, "SELFTEST_FAILED", "broken candidate"
            ),
        )

    rc = run_session(
        tmp_path,
        env.keys,
        channel=channel,
        slot_store=store,
        activate=fail_activation,
    )

    assert rc != 0
    assert channel.closed is True
    assert store.closed is True

    assert len(channel.sent) >= 2
    assert channel.sent[0].type == "REQUEST_READY"
    assert channel.sent[0].body["accepted"] is True
    assert channel.sent[1].type == "APPLY_RESULT"
    assert channel.sent[1].body["accepted"] is True

    state = store.state
    assert state is not None
    assert state.phase == "CLEANING"
    assert state.committed == env.old
    assert state.highwater == env.old.binding
    assert state.failed == env.candidate.binding
    assert state.transaction is None
    assert state.last_error == "SELFTEST_FAILED"

    seq = env.candidate.binding.release_sequence
    sha = env.candidate.binding.payload_sha256
    published_dir = tmp_path / "releases" / f"g-{seq:020d}-{sha}"
    assert state.committed != env.candidate
    assert published_dir.is_dir()


def test_balanced_live_update_recovery_checkpoints(tmp_path: Path) -> None:
    for stage in ("ADMITTED", "VERIFIED"):
        case_root = tmp_path / f"recovery-{stage.lower()}"
        case_root.mkdir()
        env = Env(case_root, launcher_changed=True, core_changed=True)
        store = ClosableStore(env.state)

        coordinator = BrokerCoordinator(case_root, store, env.keys)
        begin_res = coordinator.begin(env.envelope_b64)
        assert begin_res.accepted is True

        if stage == "VERIFIED":
            env.populate_incoming(begin_res.request_id)
            apply_res = coordinator.apply(begin_res.transaction_id, begin_res.request_id)
            assert apply_res.accepted is True
            assert store.state is not None
            assert store.state.transaction is not None
            assert store.state.transaction.stage == "VERIFIED"
        else:
            assert store.state is not None
            assert store.state.transaction is not None
            assert store.state.transaction.stage == "ADMITTED"

        assert store.state is not None
        state_bytes = serialize_state(store.state)
        frame = SlotFrame(
            revision=store.state.revision,
            format_version=1,
            body_bytes=state_bytes,
        )
        state_dir = case_root / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "slot-a.bin").write_bytes(pack_slot_frame(frame))

        engine = RecoveryEngine(case_root, env.keys)
        res1 = engine.run_recovery()
        assert res1.converged is True
        assert res1.selected_generation == env.old
        assert res1.final_state is not None
        assert res1.final_state.phase == "IDLE"
        assert res1.final_state.committed == env.old
        assert res1.final_state.highwater == env.old.binding
        assert res1.final_state.failed == env.candidate.binding
        assert res1.final_state.transaction is None

        res2 = engine.run_recovery()
        assert res2.converged is True
        assert res2.selected_generation == env.old
        assert res2.mutations_performed == 0
