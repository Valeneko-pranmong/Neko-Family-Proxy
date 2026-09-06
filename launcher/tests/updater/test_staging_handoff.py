import base64
import hashlib
from pathlib import Path

from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.staging_handoff import handle_apply_request, handle_begin_request
from neko_launcher.updater.state_models import Binding, Generation, State
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_release_document,
)


def _make_signed_envelope_b64(seq: int, rel_id: str, launcher_hash: str, core_hash: str) -> str:
    doc = valid_release_document()
    doc["schema_version"] = 2
    doc["channel"] = "beta"
    doc["release_sequence"] = seq
    doc["release_id"] = rel_id
    doc["mandatory"] = False
    doc["minimum_supported_sequence"] = 1
    doc["updater_protocol"] = {"minimum": 1, "maximum": 1}
    doc["components"]["launcher"]["artifact_format"] = "raw-pe-v1"
    doc["components"]["launcher"]["artifact_sha256"] = launcher_hash
    doc["components"]["launcher"]["installed_identity_sha256"] = launcher_hash
    doc["components"]["core"]["artifact_format"] = "zip-core-v1"
    doc["components"]["core"]["artifact_sha256"] = core_hash
    doc["components"]["core"]["installed_identity_sha256"] = core_hash
    env = signed_envelope(doc)
    return base64.b64encode(canonical_json_dumps(env)).decode("ascii")


def test_handle_begin_request_success(tmp_path: Path) -> None:
    # Initial state at sequence 1
    initial_binding = Binding(release_sequence=1, release_id="rel-1", payload_sha256="1" * 64)
    committed_gen = Generation(
        binding=initial_binding,
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )
    current_state = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=committed_gen,
        previous=None,
        highwater=initial_binding,
        observed=initial_binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}
    # Candidate changes both launcher and core
    env_b64 = _make_signed_envelope_b64(2, "rel-2", "2" * 64, "3" * 64)

    ready_res, next_state = handle_begin_request(tmp_path, current_state, env_b64, keys)
    assert ready_res.accepted
    assert ready_res.error is None
    assert ready_res.request_id is not None
    assert ready_res.transaction_id is not None
    assert ready_res.changed == {"launcher": True, "core": True}

    assert next_state is not None
    assert next_state.phase == "PREPARING"
    assert next_state.revision == 2
    assert next_state.transaction is not None
    assert next_state.transaction.stage == "ADMITTED"
    # Directory created on disk
    inc_dir = tmp_path / "incoming" / ready_res.request_id
    assert inc_dir.exists()
    assert inc_dir.is_dir()


def test_handle_begin_rejects_downgrade(tmp_path: Path) -> None:
    initial_binding = Binding(release_sequence=5, release_id="rel-5", payload_sha256="5" * 64)
    committed_gen = Generation(
        binding=initial_binding,
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )
    current_state = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=committed_gen,
        previous=None,
        highwater=initial_binding,
        observed=initial_binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}
    # Sequence 4 is lower than sequence 5
    env_b64 = _make_signed_envelope_b64(4, "rel-4", "2" * 64, "3" * 64)

    ready_res, next_state = handle_begin_request(tmp_path, current_state, env_b64, keys)
    assert not ready_res.accepted
    assert ready_res.error == "DOWNGRADE_REJECTED"
    assert next_state is None


def test_handle_apply_request_verifies_on_disk_artifacts(tmp_path: Path) -> None:
    initial_binding = Binding(release_sequence=1, release_id="rel-1", payload_sha256="1" * 64)
    committed_gen = Generation(
        binding=initial_binding,
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )
    current_state = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=committed_gen,
        previous=None,
        highwater=initial_binding,
        observed=initial_binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}
    launcher_bytes = b"new launcher binary payload"
    core_bytes = b"new core zip package payload"
    launcher_sha = hashlib.sha256(launcher_bytes).hexdigest()
    core_sha = hashlib.sha256(core_bytes).hexdigest()

    env_b64 = _make_signed_envelope_b64(2, "rel-2", launcher_sha, core_sha)
    ready_res, state_admitted = handle_begin_request(tmp_path, current_state, env_b64, keys)
    assert ready_res.accepted and state_admitted is not None

    req_dir = tmp_path / "incoming" / ready_res.request_id
    (req_dir / "launcher.artifact").write_bytes(launcher_bytes)
    (req_dir / "core.artifact.zip").write_bytes(core_bytes)

    apply_res = handle_apply_request(
        tmp_path,
        state_admitted,
        ready_res.transaction_id,
        ready_res.request_id,
    )
    assert apply_res.accepted
    assert apply_res.error is None
