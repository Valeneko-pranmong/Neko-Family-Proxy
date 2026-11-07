import base64
import ctypes
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from neko_launcher.updater.binary_frame import SlotFrame, pack_slot_frame
from neko_launcher.updater.recovery_engine import RecoveryEngine
from neko_launcher.updater.state_models import (
    Binding,
    Cleanup,
    DirectoryIdentity,
    Generation,
    State,
    Transaction,
    serialize_state,
)
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_v2_release_document,
)
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.win32_directory import get_directory_identity, open_directory_guarded
from tests.updater.test_slot_selector import _make_signed_evidence


def _make_dummy_gen(seq: int) -> tuple[Generation, str, str]:
    binding, p_sha, env_b64 = _make_signed_evidence(seq, f"r-{seq}")
    gen = Generation(
        binding=binding,
        launcher_identity_sha256="3" * 64,
        core_identity_sha256="2" * 64,
    )
    return gen, p_sha, env_b64


def _committed_cleanup_fixture(tmp_path: Path) -> tuple[State, Path, Path]:
    launcher_bytes = b"committed launcher"
    manifest_bytes = b"committed core manifest"
    launcher_sha = hashlib.sha256(launcher_bytes).hexdigest()
    core_sha = hashlib.sha256(manifest_bytes).hexdigest()
    doc = valid_v2_release_document(
        sequence=2, release_id="r-2", channel="stable",
        launcher_sha=launcher_sha, launcher_size=len(launcher_bytes),
        core_installed_sha=core_sha,
    )
    envelope = signed_envelope(doc)
    envelope_bytes = canonical_json_dumps(envelope)
    payload_sha = hashlib.sha256(base64.b64decode(envelope["payload_b64"])).hexdigest()
    committed = Generation(
        binding=Binding(2, "r-2", payload_sha),
        launcher_identity_sha256=launcher_sha, core_identity_sha256=core_sha,
    )
    previous, previous_sha, previous_env = _make_dummy_gen(1)
    generation = tmp_path / "releases" / f"g-{2:020d}-{payload_sha}"
    (generation / "ProxyCore").mkdir(parents=True)
    (generation / "NekoLauncher.exe").write_bytes(launcher_bytes)
    (generation / "ProxyCore" / "core-manifest.json").write_bytes(manifest_bytes)
    (tmp_path / "releases" / f"g-{1:020d}-{previous_sha}").mkdir()
    incoming = tmp_path / "incoming" / ("b" * 32)
    incoming.mkdir(parents=True)
    (incoming / "scratch.tmp").write_bytes(b"owned scratch")
    handle = open_directory_guarded(incoming)
    try:
        identity = get_directory_identity(handle)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    state = State(
        schema_version=1, revision=10, installation_id="1" * 32,
        helper_protocol=1, enrollment_complete=True, phase="CLEANING",
        committed=committed, previous=previous, highwater=committed.binding,
        observed=committed.binding, failed=None, transaction=None,
        cleanup=[Cleanup("a" * 32, "b" * 32, identity, "incoming", "INTENT")],
        rollback=None, last_error=None,
        evidence={payload_sha: base64.b64encode(envelope_bytes).decode("ascii"), previous_sha: previous_env},
    )
    (tmp_path / "state").mkdir()
    packed = pack_slot_frame(SlotFrame(revision=10, format_version=1, body_bytes=serialize_state(state)))
    (tmp_path / "state" / "slot-a.bin").write_bytes(packed)
    return state, generation, incoming


def test_scoped_cleanup_preserves_committed_generation_and_authority(tmp_path: Path) -> None:
    state, generation, incoming = _committed_cleanup_fixture(tmp_path)

    result = RecoveryEngine(tmp_path, {TEST_KEY_ID: TEST_PUBLIC_KEY}).complete_committed_cleanup(
        state.committed, state.installation_id
    )

    assert result.converged and result.final_state.phase == "IDLE"
    assert result.final_state.committed == state.committed
    assert result.final_state.previous == state.previous
    assert result.final_state.highwater == state.highwater
    assert result.final_state.observed == state.observed
    assert result.final_state.failed == state.failed
    assert not incoming.exists()
    assert generation.is_dir()


@pytest.mark.parametrize("failure", ["missing-storage", "different-installation", "different-generation", "active-transaction", "directory-mismatch"])
def test_scoped_cleanup_refuses_mutation_or_rollback_on_invalid_state(
    tmp_path: Path, failure: str
) -> None:
    state, generation, incoming = _committed_cleanup_fixture(tmp_path)
    expected_generation = state.committed
    expected_installation = state.installation_id
    if failure == "missing-storage":
        generation.rename(generation.with_name("missing-committed-storage"))
    elif failure == "different-installation":
        expected_installation = "2" * 32
    elif failure == "different-generation":
        expected_generation = state.previous
    elif failure == "active-transaction":
        candidate, candidate_sha, candidate_env = _make_dummy_gen(3)
        state = replace(
            state, phase="PREPARING", cleanup=None,
            transaction=Transaction("c" * 32, "b" * 32, candidate, state.committed, state.cleanup[0].directory, None, "ADMITTED", None),
            highwater=candidate.binding, observed=candidate.binding,
            evidence={**state.evidence, candidate_sha: candidate_env},
        )
    elif failure == "directory-mismatch":
        item = state.cleanup[0]
        changed_identity = replace(item.directory, file_id="0" * 32)
        state = replace(state, cleanup=[replace(item, directory=changed_identity)])
    packed = pack_slot_frame(SlotFrame(revision=10, format_version=1, body_bytes=serialize_state(state)))
    slot = tmp_path / "state" / "slot-a.bin"
    slot.write_bytes(packed)
    before = slot.read_bytes()

    result = RecoveryEngine(tmp_path, {TEST_KEY_ID: TEST_PUBLIC_KEY}).complete_committed_cleanup(
        expected_generation, expected_installation
    )

    assert not result.converged
    assert slot.read_bytes() == before
    assert not (tmp_path / "state" / "slot-b.bin").exists()
    assert result.final_state.committed == state.committed
    assert result.final_state.highwater == state.highwater
    assert incoming.is_dir()
    assert (incoming / "scratch.tmp").read_bytes() == b"owned scratch"


def test_recovery_from_idle_converges_and_is_idempotent(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    gen1, p_sha, env_b64 = _make_dummy_gen(1)
    releases_dir = tmp_path / "releases" / f"g-{gen1.binding.release_sequence:020d}-{gen1.binding.payload_sha256}"
    releases_dir.mkdir(parents=True)
    s = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen1,
        previous=None,
        highwater=gen1.binding,
        observed=gen1.binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={p_sha: env_b64},
    )
    frame = pack_slot_frame(SlotFrame(revision=1, format_version=1, body_bytes=serialize_state(s)))
    (state_dir / "slot-a.bin").write_bytes(frame)

    engine = RecoveryEngine(tmp_path, {TEST_KEY_ID: TEST_PUBLIC_KEY})
    res1 = engine.run_recovery()
    assert res1.converged
    assert res1.selected_generation == gen1

    # Idempotence: second recovery performs 0 mutations
    res2 = engine.run_recovery()
    assert res2.converged
    assert res2.mutations_performed == 0
    assert res2.selected_generation == gen1


def test_recovery_from_preparing_aborts_candidate(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    gen1, p_sha1, env_b64_1 = _make_dummy_gen(1)
    releases_dir = tmp_path / "releases" / f"g-{gen1.binding.release_sequence:020d}-{gen1.binding.payload_sha256}"
    releases_dir.mkdir(parents=True)
    gen2, p_sha2, env_b64_2 = _make_dummy_gen(2)

    inc_dir = tmp_path / "incoming" / ("b" * 32)
    inc_dir.mkdir(parents=True)
    (inc_dir / "partial.tmp").write_text("junk")

    tx = Transaction(
        id="a" * 32,
        request_id="b" * 32,
        candidate=gen2,
        old=gen1,
        incoming=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="0" * 32, parent_file_id="0" * 32),
        staging=None,
        stage="ADMITTED",
        mutation=None,
    )
    s = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PREPARING",
        committed=gen1,
        previous=None,
        highwater=gen1.binding,
        observed=gen2.binding,
        failed=None,
        transaction=tx,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={p_sha1: env_b64_1, p_sha2: env_b64_2},
    )
    frame = pack_slot_frame(SlotFrame(revision=1, format_version=1, body_bytes=serialize_state(s)))
    (state_dir / "slot-a.bin").write_bytes(frame)

    engine = RecoveryEngine(tmp_path, {TEST_KEY_ID: TEST_PUBLIC_KEY})
    res = engine.run_recovery()
    assert res.converged
    assert res.selected_generation == gen1
    assert res.final_state is not None
    assert res.final_state.phase == "IDLE"
    assert res.final_state.failed == gen2.binding
