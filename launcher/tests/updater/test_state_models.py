import pytest

from neko_launcher.updater.state_models import (
    Binding,
    EnrollmentMarker,
    Generation,
    InstalledReleaseSelector,
    RootIdentity,
    State,
    deserialize_marker,
    deserialize_state,
    migrate_state,
    serialize_marker,
    serialize_state,
)


def sample_valid_state() -> State:
    binding = Binding(release_sequence=1, release_id="rel-1", payload_sha256="a" * 64)
    gen = Generation(binding=binding, launcher_identity_sha256="b" * 64, core_identity_sha256="c" * 64)
    return State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen,
        previous=None,
        highwater=binding,
        observed=binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={"a" * 64: "dGVzdC1lbnZlbG9wZQ=="},
    )


def sample_valid_marker() -> EnrollmentMarker:
    return EnrollmentMarker(
        schema_version=1,
        installation_id="1" * 32,
        root=RootIdentity(volume_serial="12345678abcdef01", file_id="a" * 32),
        helper_sha256="f" * 64,
        helper_protocol=1,
        keyset_sha256="e" * 64,
        bootstrap_payload_sha256="b" * 64,
        enrollment_status="PREPARED",
    )


def test_state_serialization_roundtrip() -> None:
    state = sample_valid_state()
    data = serialize_state(state)
    restored = deserialize_state(data)
    assert restored == state


def test_state_rejects_extra_fields() -> None:
    # Adding unauthorized field
    raw = (
        b'{"cleanup":null,"committed":null,"enrollment_complete":true,'
        b'"evidence":{},"extra_unauthorized":123,"failed":null,"helper_protocol":1,'
        b'"highwater":null,"installation_id":"11111111111111111111111111111111",'
        b'"last_error":null,"observed":null,"phase":"IDLE","previous":null,'
        b'"revision":1,"rollback":null,"schema_version":1,"transaction":null}'
    )
    with pytest.raises(ValueError, match="Unknown field"):
        deserialize_state(raw)


def test_state_rejects_invalid_hash() -> None:
    state_dict = {
        "schema_version": 1,
        "revision": 1,
        "installation_id": "1" * 32,
        "helper_protocol": 1,
        "enrollment_complete": True,
        "phase": "IDLE",
        "committed": {
            "binding": {"release_sequence": 1, "release_id": "rel-1", "payload_sha256": "INVALID_HASH"},
            "launcher_identity_sha256": "b" * 64,
            "core_identity_sha256": "c" * 64,
        },
        "previous": None,
        "highwater": None,
        "observed": None,
        "failed": None,
        "transaction": None,
        "cleanup": None,
        "rollback": None,
        "last_error": None,
        "evidence": {},
    }
    from neko_launcher.updater.canonical_json import canonical_json_dumps
    raw = canonical_json_dumps(state_dict)
    with pytest.raises(ValueError, match="Invalid hash"):
        deserialize_state(raw)


def test_marker_serialization_roundtrip() -> None:
    marker = sample_valid_marker()
    data = serialize_marker(marker)
    restored = deserialize_marker(data)
    assert restored == marker


def test_installed_release_selector_validation() -> None:
    selector = InstalledReleaseSelector(
        sequence=9,
        release_id="stable-0009",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    assert selector.sequence == 9
    assert selector.release_id == "stable-0009"
    assert selector.version == "5.1.3"
    assert selector.tag_name == "v5.1.3"
    assert selector.target_commit == "a" * 40

    with pytest.raises(ValueError, match="sequence"):
        InstalledReleaseSelector(0, "rel-1", "5.1.3", "v5.1.3", "a" * 40)
    with pytest.raises(ValueError, match="sequence"):
        InstalledReleaseSelector(True, "rel-1", "5.1.3", "v5.1.3", "a" * 40)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="release_id"):
        InstalledReleaseSelector(1, "", "5.1.3", "v5.1.3", "a" * 40)
    with pytest.raises(ValueError, match="version"):
        InstalledReleaseSelector(1, "rel-1", "", "v5.1.3", "a" * 40)
    with pytest.raises(ValueError, match="tag_name"):
        InstalledReleaseSelector(1, "rel-1", "5.1.3", "", "a" * 40)
    with pytest.raises(ValueError, match="target_commit"):
        InstalledReleaseSelector(1, "rel-1", "5.1.3", "v5.1.3", "")


def test_generation_selector_cross_validation() -> None:
    binding = Binding(release_sequence=9, release_id="stable-0009", payload_sha256="a" * 64)
    selector = InstalledReleaseSelector(
        sequence=9,
        release_id="stable-0009",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    gen = Generation(
        binding=binding,
        launcher_identity_sha256="b" * 64,
        core_identity_sha256="c" * 64,
        selector=selector,
    )
    assert gen.selector == selector

    # Sequence mismatch
    mismatched_seq_sel = InstalledReleaseSelector(
        sequence=8,
        release_id="stable-0009",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    with pytest.raises(ValueError, match="sequence"):
        Generation(
            binding=binding,
            launcher_identity_sha256="b" * 64,
            core_identity_sha256="c" * 64,
            selector=mismatched_seq_sel,
        )

    # Release ID mismatch
    mismatched_id_sel = InstalledReleaseSelector(
        sequence=9,
        release_id="other-id",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    with pytest.raises(ValueError, match="release_id"):
        Generation(
            binding=binding,
            launcher_identity_sha256="b" * 64,
            core_identity_sha256="c" * 64,
            selector=mismatched_id_sel,
        )


def test_state_serialization_roundtrip_with_selector() -> None:
    binding = Binding(release_sequence=9, release_id="stable-0009", payload_sha256="a" * 64)
    selector = InstalledReleaseSelector(
        sequence=9,
        release_id="stable-0009",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    gen = Generation(
        binding=binding,
        launcher_identity_sha256="b" * 64,
        core_identity_sha256="c" * 64,
        selector=selector,
    )
    state = State(
        schema_version=1,
        revision=2,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen,
        previous=None,
        highwater=binding,
        observed=binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={"a" * 64: "dGVzdC1lbnZlbG9wZQ=="},
    )
    data = serialize_state(state)
    restored = deserialize_state(data)
    assert restored == state
    assert restored.committed is not None
    assert restored.committed.selector == selector


def test_migrate_state_deterministic_commit_and_evidence() -> None:
    import base64
    from neko_launcher.updater.canonical_json import canonical_json_dumps
    from tests.software_update_helpers import valid_v2_release_document

    doc = valid_v2_release_document(
        sequence=9,
        release_id="stable-0009",
        launcher_version="5.1.3",
    )
    payload_sha = "a" * 64
    env_doc = {"payload": doc}
    env_b64 = base64.b64encode(canonical_json_dumps(env_doc)).decode("ascii")

    binding = Binding(release_sequence=9, release_id="stable-0009", payload_sha256=payload_sha)
    old_gen = Generation(
        binding=binding,
        launcher_identity_sha256="b" * 64,
        core_identity_sha256="c" * 64,
        selector=None,
    )
    old_state = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=old_gen,
        previous=None,
        highwater=binding,
        observed=binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={payload_sha: env_b64},
    )

    migrated = migrate_state(old_state, deterministic_commit="c" * 40)
    assert migrated.committed is not None
    assert migrated.committed.selector is not None
    assert migrated.committed.selector.sequence == 9
    assert migrated.committed.selector.release_id == "stable-0009"
    assert migrated.committed.selector.version == "5.1.3"
    assert migrated.committed.selector.tag_name == "v5.1.3"
    assert migrated.committed.selector.target_commit == "c" * 40


def test_migrate_state_deterministic_selector() -> None:
    binding = Binding(release_sequence=9, release_id="stable-0009", payload_sha256="a" * 64)
    old_gen = Generation(
        binding=binding,
        launcher_identity_sha256="b" * 64,
        core_identity_sha256="c" * 64,
        selector=None,
    )
    old_state = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=old_gen,
        previous=None,
        highwater=binding,
        observed=binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={"a" * 64: "dGVzdA=="},
    )

    selector = InstalledReleaseSelector(
        sequence=9,
        release_id="stable-0009",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="d" * 40,
    )
    migrated = migrate_state(old_state, deterministic_selector=selector)
    assert migrated.committed is not None
    assert migrated.committed.selector == selector


def test_migrate_state_ambiguous_historical_state_fails_closed() -> None:
    binding = Binding(release_sequence=9, release_id="stable-0009", payload_sha256="a" * 64)
    old_gen = Generation(
        binding=binding,
        launcher_identity_sha256="b" * 64,
        core_identity_sha256="c" * 64,
        selector=None,
    )
    old_state = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=old_gen,
        previous=None,
        highwater=binding,
        observed=binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    # Ambiguous: no deterministic commit or selector provided -> fails closed, never guesses!
    with pytest.raises(ValueError, match="ambiguous historical state"):
        migrate_state(old_state)


def test_migrate_state_mismatched_selector_fails_closed() -> None:
    binding = Binding(release_sequence=9, release_id="stable-0009", payload_sha256="a" * 64)
    old_gen = Generation(
        binding=binding,
        launcher_identity_sha256="b" * 64,
        core_identity_sha256="c" * 64,
        selector=None,
    )
    old_state = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=old_gen,
        previous=None,
        highwater=binding,
        observed=binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    mismatched_selector = InstalledReleaseSelector(
        sequence=10,  # mismatch with 9
        release_id="stable-0009",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="d" * 40,
    )
    with pytest.raises(ValueError, match="sequence"):
        migrate_state(old_state, deterministic_selector=mismatched_selector)
