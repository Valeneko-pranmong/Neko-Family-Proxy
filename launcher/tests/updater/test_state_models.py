import pytest

from neko_launcher.updater.state_models import (
    Binding,
    EnrollmentMarker,
    Generation,
    RootIdentity,
    State,
    deserialize_marker,
    deserialize_state,
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
