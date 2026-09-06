"""Balanced Phase 3 test contract for broker."""

from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

import pytest

from neko_launcher.updater.generation_builder import GenerationBuildResult, GenerationBuildError
from neko_launcher.updater.state_models import (
    Binding,
    Generation,
    State,
)
from neko_launcher.updater.slot_selector import SelectionResult, SelectionStatus
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    canonical_payload_bytes,
)

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

class FakeSlotStore:
    def __init__(self, initial_state: State | None = None) -> None:
        self.state = initial_state
        self.slot = "a"
        self.history: list[State] = []
        self.write_fail_mode = False
        if initial_state:
            self.history.append(initial_state)

    def load(self) -> SelectionResult:
        if self.state is None:
            return SelectionResult(SelectionStatus.REPAIR_REQUIRED, None, None, "missing state")
        return SelectionResult(SelectionStatus.SELECTED, self.state, self.slot, None)

    def write_state(self, new_state: State) -> SelectionResult:
        if self.write_fail_mode:
            return SelectionResult(SelectionStatus.SELECTED, self.state, self.slot, None)
        self.state = new_state
        self.slot = "b" if self.slot == "a" else "a"
        self.history.append(new_state)
        return SelectionResult(SelectionStatus.SELECTED, self.state, self.slot, None)

class Env:
    def __init__(self, tmp: Path, launcher_changed: bool = True, core_changed: bool = True) -> None:
        self.root = tmp
        self.keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}

        self.old_launcher = b"old-launcher"
        self.old_launcher_sha = sha256_bytes(self.old_launcher)

        old_core_manifest_doc = self.build_core_manifest("old-commit")
        old_core_manifest_bytes = canonical_payload_bytes(old_core_manifest_doc)
        self.old_core_id = sha256_bytes(old_core_manifest_bytes)

        self.old_core_zip_bytes = self.build_core_zip(old_core_manifest_bytes)
        self.old_core_zip_sha = sha256_bytes(self.old_core_zip_bytes)

        old_payload_doc = self.build_release_doc(
            1, self.old_launcher_sha, len(self.old_launcher),
            self.old_core_zip_sha, len(self.old_core_zip_bytes), self.old_core_id
        )
        self.old_payload_bytes = canonical_payload_bytes(old_payload_doc)
        self.old_envelope_dict = signed_envelope(old_payload_doc)
        self.old_envelope = canonical_payload_bytes(self.old_envelope_dict)
        self.old_payload_sha = sha256_bytes(self.old_payload_bytes)

        self.old_generation_id = f"g-00000000000000000001-{self.old_payload_sha}"
        self.old = Generation(
            Binding(1, "rel-1", self.old_payload_sha),
            self.old_launcher_sha,
            self.old_core_id,
        )
        self.old_dir = tmp / "releases" / self.old_generation_id
        self.old_dir.mkdir(parents=True)
        (self.old_dir / "NekoLauncher.exe").write_bytes(self.old_launcher)
        core_dir = self.old_dir / "ProxyCore"
        core_dir.mkdir()
        self.write_core_files(core_dir, old_core_manifest_bytes)
        (self.old_dir / "release-envelope.json").write_bytes(self.old_envelope)

        self.state = State(
            1, 2, "d"*32, 1, True, "IDLE", self.old, None, self.old.binding, None, None, None, None, None, None,
            {self.old.binding.payload_sha256: base64.standard_b64encode(self.old_envelope).decode("ascii")}
        )

        self.new_launcher = b"new-launcher"
        self.new_launcher_sha = sha256_bytes(self.new_launcher)

        new_core_manifest_doc = self.build_core_manifest("new-commit")
        new_core_manifest_bytes = canonical_payload_bytes(new_core_manifest_doc)
        self.new_core_id = sha256_bytes(new_core_manifest_bytes)

        self.new_core_zip_bytes = self.build_core_zip(new_core_manifest_bytes)
        self.new_core_zip_sha = sha256_bytes(self.new_core_zip_bytes)

        self.l_sha = self.new_launcher_sha if launcher_changed else self.old_launcher_sha
        self.l_size = len(self.new_launcher) if launcher_changed else len(self.old_launcher)
        self.c_sha = self.new_core_zip_sha if core_changed else self.old_core_zip_sha
        self.c_size = len(self.new_core_zip_bytes) if core_changed else len(self.old_core_zip_bytes)
        self.c_id = self.new_core_id if core_changed else self.old_core_id

        self.payload_doc = self.build_release_doc(
            2, self.l_sha, self.l_size, self.c_sha, self.c_size, self.c_id
        )
        self.payload_bytes = canonical_payload_bytes(self.payload_doc)
        self.envelope_dict = signed_envelope(self.payload_doc)
        self.envelope = canonical_payload_bytes(self.envelope_dict)
        self.envelope_b64 = base64.standard_b64encode(self.envelope).decode("ascii")
        self.payload_sha = sha256_bytes(self.payload_bytes)

        self.candidate = Generation(
            Binding(2, "rel-2", self.payload_sha), self.l_sha, self.c_id
        )
        self.store = FakeSlotStore(self.state)

    def build_core_manifest(self, commit: str) -> dict:
        files = {
            "NekoProxyCore.exe": b"exe-content",
            "NekoProxyCore.dll": b"dll-content",
            "runtime-settings.nkps": b"nkps-content",
            "bin/Redirector.bin": b"redir-content",
            "bin/nfapi.dll": b"nfapi-content",
            "bin/v2ray-sn.exe": b"v2ray-content",
        }
        total_bytes = sum(len(c) for c in files.values())
        return {
            "source_commit": commit,
            "candidate": "candidate-1",
            "authority": "auth-1",
            "file_count": 6,
            "total_bytes": total_bytes,
            "neko_proxy_core_exe_hash": sha256_bytes(files["NekoProxyCore.exe"]),
            "neko_proxy_core_dll_hash": sha256_bytes(files["NekoProxyCore.dll"]),
            "protected_settings_payload_hash": sha256_bytes(files["runtime-settings.nkps"]),
            "redirector_bin_hash": sha256_bytes(files["bin/Redirector.bin"]),
            "nfapi_dll_hash": sha256_bytes(files["bin/nfapi.dll"]),
            "v2ray_sn_exe_hash": sha256_bytes(files["bin/v2ray-sn.exe"]),
            "security": {
                "runtime_settings_key_files": 0,
                "plaintext_settings_files": 0,
                "plaintext_secret_marker_hits": 0,
                "external_dotnet_dependency": False
            },
            "files": {name: sha256_bytes(content) for name, content in files.items()}
        }

    def write_core_files(self, core_dir: Path, manifest_bytes: bytes) -> None:
        (core_dir / "NekoProxyCore.exe").write_bytes(b"exe-content")
        (core_dir / "NekoProxyCore.dll").write_bytes(b"dll-content")
        (core_dir / "runtime-settings.nkps").write_bytes(b"nkps-content")
        bin_dir = core_dir / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "Redirector.bin").write_bytes(b"redir-content")
        (bin_dir / "nfapi.dll").write_bytes(b"nfapi-content")
        (bin_dir / "v2ray-sn.exe").write_bytes(b"v2ray-content")
        (core_dir / "canonical-core-manifest.json").write_bytes(manifest_bytes)

    def build_core_zip(self, manifest_bytes: bytes) -> bytes:
        import io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("NekoProxyCore.exe", b"exe-content")
            z.writestr("NekoProxyCore.dll", b"dll-content")
            z.writestr("runtime-settings.nkps", b"nkps-content")
            z.writestr("bin/Redirector.bin", b"redir-content")
            z.writestr("bin/nfapi.dll", b"nfapi-content")
            z.writestr("bin/v2ray-sn.exe", b"v2ray-content")
            z.writestr("canonical-core-manifest.json", manifest_bytes)
        return buf.getvalue()

    def build_release_doc(
        self, seq: int, l_sha: str, l_size: int, c_sha: str, c_size: int, c_id: str
    ) -> dict[str, object]:
        return {
            "schema_version": 2,
            "channel": "beta",
            "release_sequence": seq,
            "release_id": f"rel-{seq}",
            "mandatory": False,
            "minimum_supported_sequence": 1,
            "updater_protocol": {"minimum": 1, "maximum": 1},
            "components": {
                "core": {
                    "version": "1.0.0",
                    "artifact_size": c_size,
                    "artifact_sha256": c_sha,
                    "installed_identity_sha256": c_id,
                    "artifact_format": "zip-core-v1",
                },
                "launcher": {
                    "version": "1.0.0",
                    "artifact_size": l_size,
                    "artifact_sha256": l_sha,
                    "installed_identity_sha256": l_sha,
                    "artifact_format": "raw-pe-v1",
                },
            }
        }

    def populate_incoming(self, req_id: str) -> None:
        inc = self.root / "incoming" / req_id
        inc.mkdir(parents=True, exist_ok=True)
        if self.l_sha == self.new_launcher_sha:
            (inc / "launcher.artifact").write_bytes(self.new_launcher)
        if self.c_sha == self.new_core_zip_sha:
            (inc / "core.artifact.zip").write_bytes(self.new_core_zip_bytes)

def _assert_cleanup(state, admitted_tx, staging_identity=None):
    assert state.phase == "CLEANING"
    assert state.transaction is None
    assert state.cleanup is not None
    if staging_identity is None:
        assert len(state.cleanup) == 1
    else:
        assert len(state.cleanup) == 2

    c0 = state.cleanup[0]
    assert c0.transaction_id == admitted_tx.id
    assert c0.request_id == admitted_tx.request_id
    assert c0.target == "incoming"
    assert c0.status == "INTENT"
    assert c0.directory == admitted_tx.incoming

    if staging_identity is not None:
        c1 = state.cleanup[1]
        assert c1.transaction_id == admitted_tx.id
        assert c1.request_id == admitted_tx.request_id
        assert c1.target == "staging"
        assert c1.status == "INTENT"
        assert c1.directory == staging_identity

def test_begin_rejection_for_write_corrupt(tmp_path: Path) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)
    env.store.write_fail_mode = True
    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys)

    result = coordinator.begin(env.envelope_b64)
    assert result.accepted is False
    assert result.error == "STATE_CORRUPT"

def test_begin_success_admission(tmp_path: Path) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)
    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys)

    result = coordinator.begin(env.envelope_b64)
    assert result.accepted is True
    assert result.request_id is not None
    assert result.transaction_id is not None
    assert result.changed == {"launcher": True, "core": True}

    assert env.store.state.phase == "PREPARING"
    assert env.store.state.transaction.stage == "ADMITTED"
    assert env.store.state.highwater == env.old.binding

def test_begin_rejection_for_non_selected(tmp_path: Path) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)
    env.store.state = None
    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys)

    result = coordinator.begin(env.envelope_b64)
    assert result.accepted is False
    assert result.error == "STATE_CORRUPT"

def test_begin_rejection_for_downgrade(tmp_path: Path) -> None:
    import dataclasses
    import neko_launcher.updater.broker as broker
    from neko_launcher.updater.state_models import Binding
    env = Env(tmp_path)

    env.store.state = dataclasses.replace(env.store.state, highwater=Binding(5, "rel-5", "abc"))

    payload_doc = env.build_release_doc(
        1, env.new_launcher_sha, len(env.new_launcher),
        env.new_core_zip_sha, len(env.new_core_zip_bytes), env.new_core_id
    )
    envelope = canonical_payload_bytes(signed_envelope(payload_doc))
    env_b64 = base64.standard_b64encode(envelope).decode("ascii")

    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys)
    result = coordinator.begin(env_b64)
    assert result.accepted is False
    assert result.error == "DOWNGRADE_REJECTED"
    assert len(env.store.history) == 1
    if (tmp_path / "incoming").exists():
        assert not list((tmp_path / "incoming").iterdir())

def test_second_begin_while_preparing(tmp_path: Path) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)
    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys)

    result1 = coordinator.begin(env.envelope_b64)
    assert result1.accepted is True

    result2 = coordinator.begin(env.envelope_b64)
    assert result2.accepted is False
    assert result2.error == "LOCK_BUSY"

def test_metadata_only_valid_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path, launcher_changed=False, core_changed=False)
    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys, lambda p,g,e: None)

    def mock_build(root, state, keys):
        staging_dir = root / "staging" / state.transaction.id
        staging_dir.mkdir(parents=True, exist_ok=True)
        gen_dir = staging_dir / "generation"
        gen_dir.mkdir(parents=True)
        return GenerationBuildResult({"launcher": False, "core": False}, "g-meta", gen_dir, state.transaction.candidate)

    monkeypatch.setattr(broker, "build_generation", mock_build)

    class MockPublisher:
        def __init__(self, root_dir: Path):
            self.root_dir = root_dir
        def create_staging_area(self, txid: str):
            from neko_launcher.updater.state_models import DirectoryIdentity
            stage = self.root_dir / "staging" / txid
            stage.mkdir(parents=True, exist_ok=True)
            return 999, DirectoryIdentity(0, 0), stage
        def publish_generation(self, staging_dir: Path, gen_id: str):
            dest = self.root_dir / "releases" / gen_id
            dest.mkdir(parents=True, exist_ok=True)
            return dest

    monkeypatch.setattr(broker, "GenerationPublisher", MockPublisher)

    res = coordinator.begin(env.envelope_b64)
    assert res.accepted is True
    assert res.changed == {"launcher": False, "core": False}

    env.populate_incoming(res.request_id)
    apply_res = coordinator.apply(res.transaction_id, res.request_id)
    assert apply_res.accepted is True
    assert apply_res.transaction_id == res.transaction_id
    assert apply_res.error is None
    assert env.store.state.phase == "PREPARING"
    assert env.store.state.transaction is not None
    assert env.store.state.transaction.stage == "VERIFIED"
    assert env.store.state.transaction.mutation is None

def test_apply_rejects_wrong_ids(tmp_path: Path) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)
    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys)
    res = coordinator.begin(env.envelope_b64)
    assert res.accepted is True

    apply_res = coordinator.apply("wrong-tx", res.request_id)
    assert apply_res.accepted is False
    assert apply_res.error == "PROTOCOL_INVALID"
    assert apply_res.transaction_id is None

    apply_res2 = coordinator.apply(res.transaction_id, "wrong-req")
    assert apply_res2.accepted is False
    assert apply_res2.error == "PROTOCOL_INVALID"
    assert apply_res2.transaction_id is None

@pytest.mark.parametrize("scenario, expected_error", [
    ("missing_file", "ARTIFACT_MISSING"),
    ("corrupt_file", "PACKAGE_INVALID"),
    ("extra_file", "PACKAGE_INVALID"),
    ("extra_directory", "PACKAGE_INVALID"),
    ("expected_is_directory", "PACKAGE_INVALID")
])
def test_exact_incoming_validation_failures(tmp_path: Path, scenario: str, expected_error: str) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)
    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys)
    res = coordinator.begin(env.envelope_b64)
    admitted_tx = env.store.state.transaction
    admitted_candidate = admitted_tx.candidate

    old_committed = env.store.state.committed
    old_previous = env.store.state.previous
    old_highwater = env.store.state.highwater

    env.populate_incoming(res.request_id)

    incoming_dir = env.root / "incoming" / res.request_id

    if scenario == "missing_file":
        (incoming_dir / "launcher.artifact").unlink()
    elif scenario == "corrupt_file":
        (incoming_dir / "launcher.artifact").write_bytes(b"bad")
    elif scenario == "extra_file":
        (incoming_dir / "extra.file").write_bytes(b"extra")
    elif scenario == "extra_directory":
        (incoming_dir / "extra_dir").mkdir()
    elif scenario == "expected_is_directory":
        (incoming_dir / "launcher.artifact").unlink()
        (incoming_dir / "launcher.artifact").mkdir()

    apply_res = coordinator.apply(res.transaction_id, res.request_id)
    assert apply_res.accepted is False
    assert apply_res.transaction_id is None
    assert apply_res.error == expected_error

    assert env.store.state.failed == admitted_candidate.binding
    assert env.store.state.committed == old_committed
    assert env.store.state.previous == old_previous
    assert env.store.state.highwater == old_highwater
    assert not (env.root / "staging").exists()

    _assert_cleanup(env.store.state, admitted_tx, None)

def test_successful_apply_ordering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)
    called_verifier = False

    def mock_build(root, state, keys):
        assert env.store.state == state
        assert state.phase == "PREPARING"
        assert state.transaction.stage == "BUILDING"
        assert state.transaction.mutation is None
        assert state.transaction.staging is not None
        staging_dir = root / "staging" / state.transaction.id
        gen_dir = staging_dir / "generation"
        gen_dir.mkdir(parents=True, exist_ok=True)
        return GenerationBuildResult(
            changed={"launcher": True, "core": True},
            generation_id=f"g-2-{state.transaction.candidate.binding.payload_sha256}",
            generation_dir=gen_dir,
            generation=state.transaction.candidate,
        )

    monkeypatch.setattr(broker, "build_generation", mock_build)

    class MockPublisher:
        def __init__(self, root_dir: Path):
            self.root_dir = root_dir
        def create_staging_area(self, txid: str):
            from neko_launcher.updater.state_models import DirectoryIdentity
            stage = self.root_dir / "staging" / txid
            stage.mkdir(parents=True, exist_ok=True)
            return 999, DirectoryIdentity(0, 0), stage
        def publish_generation(self, staging_dir: Path, gen_id: str):
            dest = self.root_dir / "releases" / gen_id
            dest.mkdir(parents=True, exist_ok=True)
            return dest

    monkeypatch.setattr(broker, "GenerationPublisher", MockPublisher)

    def dummy_verifier(path, gen, envelope):
        nonlocal called_verifier
        called_verifier = True
        seq = env.payload_doc["release_sequence"]
        expected_name = f"g-{seq:020d}-{env.payload_sha}"
        assert path == env.root / "releases" / expected_name
        assert gen == env.candidate
        assert envelope == env.envelope

    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys, dummy_verifier)
    res = coordinator.begin(env.envelope_b64)
    assert env.store.state.transaction.mutation is None
    env.populate_incoming(res.request_id)

    apply_res = coordinator.apply(res.transaction_id, res.request_id)
    assert apply_res.accepted is True
    assert apply_res.transaction_id == res.transaction_id
    assert apply_res.error is None
    assert called_verifier is True
    assert env.store.state.phase == "PREPARING"
    assert env.store.state.transaction.stage == "VERIFIED"
    assert env.store.state.transaction.mutation is None

def test_staging_handle_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)
    closed_handle_value = None

    def mock_close_handle(handle):
        nonlocal closed_handle_value
        if hasattr(handle, "value"):
            closed_handle_value = int(handle.value)
        else:
            closed_handle_value = int(handle)
        return 1

    try:
        monkeypatch.setattr(broker.ctypes.windll.kernel32, "CloseHandle", mock_close_handle)
    except AttributeError:
        monkeypatch.setattr(broker, "_CloseHandle", mock_close_handle)

    class MockPublisher:
        def __init__(self, root_dir: Path):
            self.root_dir = root_dir
        def create_staging_area(self, txid: str):
            from neko_launcher.updater.state_models import DirectoryIdentity
            stage = self.root_dir / "staging" / txid
            stage.mkdir(parents=True, exist_ok=True)
            return 999, DirectoryIdentity(0, 0), stage
        def publish_generation(self, staging_dir: Path, gen_id: str):
            dest = self.root_dir / "releases" / gen_id
            dest.mkdir(parents=True, exist_ok=True)
            return dest

    monkeypatch.setattr(broker, "GenerationPublisher", MockPublisher)
    monkeypatch.setattr(
        broker,
        "build_generation",
        lambda r, s, k: GenerationBuildResult({"launcher": True, "core": True}, "g", tmp_path, s.transaction.candidate),
    )

    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys, lambda p, g, e: None)
    res = coordinator.begin(env.envelope_b64)
    env.populate_incoming(res.request_id)
    coordinator.apply(res.transaction_id, res.request_id)

    assert closed_handle_value == 999

def test_build_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)

    def mock_build(root, state, keys):
        raise GenerationBuildError("IO_FAILED")

    monkeypatch.setattr(broker, "build_generation", mock_build)

    class MockPublisher:
        def __init__(self, root_dir: Path):
            self.root_dir = root_dir
        def create_staging_area(self, txid: str):
            from neko_launcher.updater.state_models import DirectoryIdentity
            stage = self.root_dir / "staging" / txid
            stage.mkdir(parents=True, exist_ok=True)
            return 999, DirectoryIdentity(0, 0), stage
        def publish_generation(self, staging_dir: Path, gen_id: str):
            raise AssertionError("publish_generation must not be called on build failure")

    monkeypatch.setattr(broker, "GenerationPublisher", MockPublisher)

    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys, lambda p, g, e: None)
    res = coordinator.begin(env.envelope_b64)
    admitted_tx = env.store.state.transaction
    admitted_candidate = admitted_tx.candidate

    old_committed = env.store.state.committed
    old_previous = env.store.state.previous
    old_highwater = env.store.state.highwater

    env.populate_incoming(res.request_id)

    apply_res = coordinator.apply(res.transaction_id, res.request_id)
    assert apply_res.accepted is False
    assert apply_res.transaction_id is None
    assert apply_res.error == "IO_FAILED"

    assert env.store.state.failed == admitted_candidate.binding
    assert env.store.state.committed == old_committed
    assert env.store.state.previous == old_previous
    assert env.store.state.highwater == old_highwater

    building_tx = next(s.transaction for s in reversed(env.store.history) if s.transaction and s.transaction.stage == "BUILDING")
    _assert_cleanup(env.store.state, admitted_tx, building_tx.staging)

def test_publish_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)

    def mock_build(root, state, keys):
        staging_dir = root / "staging" / state.transaction.id
        staging_dir.mkdir(parents=True, exist_ok=True)
        return GenerationBuildResult(
            changed={"launcher": True, "core": True},
            generation_id="g-2-x",
            generation_dir=staging_dir / "generation",
            generation=state.transaction.candidate
        )

    monkeypatch.setattr(broker, "build_generation", mock_build)

    class FailingPublisher:
        def __init__(self, root_dir: Path):
            self.root_dir = root_dir
        def create_staging_area(self, txid: str):
            from neko_launcher.updater.state_models import DirectoryIdentity
            stage = self.root_dir / "staging" / txid
            stage.mkdir(parents=True, exist_ok=True)
            return 999, DirectoryIdentity(0, 0), stage
        def publish_generation(self, staging_dir: Path, gen_id: str):
            raise OSError("publish failed")

    monkeypatch.setattr(broker, "GenerationPublisher", FailingPublisher)

    def failing_verifier(p, g, e):
        raise AssertionError("verifier must not be called if publish fails")

    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys, failing_verifier)
    res = coordinator.begin(env.envelope_b64)
    admitted_tx = env.store.state.transaction
    admitted_candidate = admitted_tx.candidate

    old_committed = env.store.state.committed
    old_previous = env.store.state.previous
    old_highwater = env.store.state.highwater

    env.populate_incoming(res.request_id)

    apply_res = coordinator.apply(res.transaction_id, res.request_id)
    assert apply_res.accepted is False
    assert apply_res.transaction_id is None
    assert apply_res.error == "IO_FAILED"

    assert env.store.state.failed == admitted_candidate.binding
    assert env.store.state.committed == old_committed
    assert env.store.state.previous == old_previous
    assert env.store.state.highwater == old_highwater

    building_tx = next(s.transaction for s in reversed(env.store.history) if s.transaction and s.transaction.stage == "BUILDING")
    _assert_cleanup(env.store.state, admitted_tx, building_tx.staging)

def test_verifier_failure_inert_unselected_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import neko_launcher.updater.broker as broker
    env = Env(tmp_path)

    def mock_build(root, state, keys):
        staging_dir = root / "staging" / state.transaction.id
        staging_dir.mkdir(parents=True, exist_ok=True)
        return GenerationBuildResult(
            changed={"launcher": True, "core": True},
            generation_id="g-2-x",
            generation_dir=staging_dir / "generation",
            generation=state.transaction.candidate
        )

    monkeypatch.setattr(broker, "build_generation", mock_build)

    def failing_verifier(p, g, e):
        raise ValueError("Invalid")

    class FakePublisher:
        def __init__(self, root_dir: Path):
            self.root_dir = root_dir
        def create_staging_area(self, txid: str):
            from neko_launcher.updater.state_models import DirectoryIdentity
            stage = self.root_dir / "staging" / txid
            stage.mkdir(parents=True, exist_ok=True)
            return 999, DirectoryIdentity(0, 0), stage
        def publish_generation(self, staging_dir: Path, gen_id: str):
            dest = self.root_dir / "releases" / gen_id
            dest.mkdir(parents=True, exist_ok=True)
            return dest

    monkeypatch.setattr(broker, "GenerationPublisher", FakePublisher)

    coordinator = broker.BrokerCoordinator(tmp_path, env.store, env.keys, failing_verifier)
    res = coordinator.begin(env.envelope_b64)
    admitted_tx = env.store.state.transaction
    admitted_candidate = admitted_tx.candidate

    old_committed = env.store.state.committed
    old_previous = env.store.state.previous
    old_highwater = env.store.state.highwater

    env.populate_incoming(res.request_id)

    apply_res = coordinator.apply(res.transaction_id, res.request_id)
    assert apply_res.accepted is False
    assert apply_res.transaction_id is None

    assert env.store.state.failed == admitted_candidate.binding
    assert env.store.state.committed == old_committed
    assert env.store.state.previous == old_previous
    assert env.store.state.highwater == old_highwater

    orphan_path = tmp_path / "releases" / "g-2-x"
    assert orphan_path.exists()
    assert env.store.state.committed.binding != env.candidate.binding

    building_tx = next(s.transaction for s in reversed(env.store.history) if s.transaction and s.transaction.stage == "BUILDING")
    _assert_cleanup(env.store.state, admitted_tx, building_tx.staging)
