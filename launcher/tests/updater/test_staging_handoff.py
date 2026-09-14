import base64
import hashlib
import inspect
from pathlib import Path

from neko_launcher.updater.canonical_json import canonical_json_dumps
try:
    from neko_launcher.updater.staging_handoff import (
        AuthorityAdmissionResponse,
        handle_authority_admission_request,
    )
except ImportError:
    AuthorityAdmissionResponse = None  # type: ignore[assignment, misc]
    handle_authority_admission_request = None  # type: ignore[assignment]
from neko_launcher.updater.staging_handoff import (
    handle_apply_request,
    handle_begin_request,
)
from neko_launcher.updater.state_models import Binding, Generation, State
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_legacy_v2_release_document,
    valid_v2_release_document,
)


def _make_signed_envelope_b64(
    seq: int,
    rel_id: str,
    launcher_hash: str,
    core_hash: str,
    launcher_size: int = 20480,
    core_size: int = 20480,
) -> str:
    doc = valid_v2_release_document(
        sequence=seq,
        release_id=rel_id,
        launcher_sha=launcher_hash,
        launcher_size=launcher_size,
        core_sha=core_hash,
        core_size=core_size,
        core_installed_sha=core_hash,
        updater_sha="9" * 64,
        updater_size=30000,
    )
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

    env_b64 = _make_signed_envelope_b64(
        2,
        "rel-2",
        launcher_sha,
        core_sha,
        launcher_size=len(launcher_bytes),
        core_size=len(core_bytes),
    )
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
        keys,
    )
    assert apply_res.accepted
    assert apply_res.error is None


def test_handle_begin_request_rejects_legacy_two_component_envelope(tmp_path: Path) -> None:
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

    # Signed legacy 2-component envelope
    doc = valid_legacy_v2_release_document(sequence=2, release_id="rel-2")
    env = signed_envelope(doc)
    env_b64 = base64.b64encode(canonical_json_dumps(env)).decode("ascii")

    ready_res, next_state = handle_begin_request(tmp_path, current_state, env_b64, keys)
    assert not ready_res.accepted
    assert next_state is None


def test_handle_authority_admission_has_no_root_dir_argument() -> None:
    sig = inspect.signature(handle_authority_admission_request)
    assert "root_dir" not in sig.parameters, "handle_authority_admission_request must NOT have root_dir parameter"


def test_handle_authority_admission_valid_newer_binding() -> None:
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
    env_b64 = _make_signed_envelope_b64(2, "rel-2", "2" * 64, "3" * 64)

    res, next_state = handle_authority_admission_request(current_state, env_b64, keys)
    assert res.accepted is True
    assert res.binding is not None
    assert res.binding.release_sequence == 2
    assert res.binding.release_id == "rel-2"
    assert res.changed is True
    assert res.error is None

    assert next_state is not None
    assert next_state.phase == "IDLE"
    assert next_state.revision == 2
    assert next_state.highwater == res.binding
    assert next_state.observed == res.binding
    assert next_state.failed is None
    assert next_state.committed == committed_gen
    assert next_state.previous is None
    assert next_state.transaction is None
    assert next_state.cleanup is None
    assert next_state.rollback is None
    assert res.binding.payload_sha256 in next_state.evidence


def test_handle_authority_admission_idempotent_already_observed() -> None:
    cand_binding = Binding(release_sequence=2, release_id="rel-2", payload_sha256="2" * 64)
    committed_gen = Generation(
        binding=Binding(release_sequence=1, release_id="rel-1", payload_sha256="1" * 64),
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}
    env_b64 = _make_signed_envelope_b64(2, "rel-2", "2" * 64, "3" * 64)

    # Decode payload to get exact payload_sha
    from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
    from neko_launcher.updater.canonical_json import canonical_json_loads
    raw_env = canonical_json_loads(base64.b64decode(env_b64))
    rel_set, payload_sha = verify_release_envelope_v2(raw_env, keys)
    cand_binding = Binding(release_sequence=2, release_id="rel-2", payload_sha256=payload_sha)

    current_state = State(
        schema_version=1,
        revision=5,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=committed_gen,
        previous=None,
        highwater=cand_binding,
        observed=cand_binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={cand_binding.payload_sha256: env_b64},
    )

    res, next_state = handle_authority_admission_request(current_state, env_b64, keys)
    assert res.accepted is True
    assert res.binding == cand_binding
    assert res.changed is False
    assert res.error is None
    assert next_state is None, "Idempotent admission must not produce a new state to write"


def test_handle_authority_admission_exact_failed_suppressed() -> None:
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}
    env_b64 = _make_signed_envelope_b64(2, "rel-2", "2" * 64, "3" * 64)

    from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
    from neko_launcher.updater.canonical_json import canonical_json_loads
    raw_env = canonical_json_loads(base64.b64decode(env_b64))
    _, payload_sha = verify_release_envelope_v2(raw_env, keys)
    cand_binding = Binding(release_sequence=2, release_id="rel-2", payload_sha256=payload_sha)

    current_state = State(
        schema_version=1,
        revision=5,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=Generation(Binding(1, "rel-1", "1" * 64), "a" * 64, "b" * 64),
        previous=None,
        highwater=cand_binding,
        observed=cand_binding,
        failed=cand_binding,  # Failed!
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )

    res, next_state = handle_authority_admission_request(current_state, env_b64, keys)
    assert res.accepted is False
    assert res.binding is None
    assert res.changed is False
    assert res.error == "CANDIDATE_SUPPRESSED"
    assert next_state is None


def test_handle_authority_admission_same_sequence_conflict() -> None:
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}
    env_b64 = _make_signed_envelope_b64(2, "rel-2-conflict", "2" * 64, "3" * 64)

    existing_binding = Binding(release_sequence=2, release_id="rel-2-original", payload_sha256="f" * 64)

    current_state = State(
        schema_version=1,
        revision=5,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=Generation(Binding(1, "rel-1", "1" * 64), "a" * 64, "b" * 64),
        previous=None,
        highwater=existing_binding,
        observed=existing_binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )

    res, next_state = handle_authority_admission_request(current_state, env_b64, keys)
    assert res.accepted is False
    assert res.binding is None
    assert res.changed is False
    assert res.error == "SAME_SEQUENCE_CONFLICT"
    assert next_state is None


def test_handle_authority_admission_downgrade_rejected() -> None:
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}
    env_b64 = _make_signed_envelope_b64(2, "rel-2", "2" * 64, "3" * 64)

    higher_binding = Binding(release_sequence=3, release_id="rel-3", payload_sha256="3" * 64)

    current_state = State(
        schema_version=1,
        revision=5,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=Generation(higher_binding, "a" * 64, "b" * 64),
        previous=None,
        highwater=higher_binding,
        observed=higher_binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )

    res, next_state = handle_authority_admission_request(current_state, env_b64, keys)
    assert res.accepted is False
    assert res.binding is None
    assert res.changed is False
    assert res.error == "DOWNGRADE_REJECTED"
    assert next_state is None


def test_handle_authority_admission_lock_busy_when_not_idle() -> None:
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}
    env_b64 = _make_signed_envelope_b64(2, "rel-2", "2" * 64, "3" * 64)

    b1 = Binding(release_sequence=1, release_id="rel-1", payload_sha256="1" * 64)
    current_state = State(
        schema_version=1,
        revision=5,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PREPARING",  # Not IDLE
        committed=Generation(b1, "a" * 64, "b" * 64),
        previous=None,
        highwater=b1,
        observed=b1,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )

    res, next_state = handle_authority_admission_request(current_state, env_b64, keys)
    assert res.accepted is False
    assert res.binding is None
    assert res.changed is False
    assert res.error == "LOCK_BUSY"
    assert next_state is None
