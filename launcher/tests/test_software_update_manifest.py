import base64
import importlib
import json
import sys
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    canonical_payload_bytes,
    get_test_key_registry,
    noncanonical_base64_spelling,
    signed_envelope,
    valid_release_document,
)

MAX_PAYLOAD_BYTES = 49_152
PRODUCTION_KEY_ID = "neko-update-prod-1"


class IntSubclass(int):
    pass


class StrSubclass(str):
    pass


class BytesSubclass(bytes):
    pass


def load_verifier_api() -> tuple[type[Any], type[ValueError]]:
    try:
        module = importlib.import_module(
            "neko_launcher.infrastructure.software_update_manifest"
        )
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"software update manifest verifier is not implemented: {exc}")

    return module.ReleaseManifestVerifier, module.ManifestVerificationError


def make_verifier(
    key_registry: Mapping[str, object] | None = None,
) -> Any:
    verifier_type, _ = load_verifier_api()
    registry = get_test_key_registry() if key_registry is None else key_registry
    return verifier_type(registry)


def assert_verify_error(
    verifier: Any,
    envelope: object,
    expected_code: str,
    *,
    absent_sentinels: tuple[str | bytes, ...] = (),
) -> None:
    _, error_type = load_verifier_api()

    with pytest.raises(error_type) as caught:
        verifier.verify(envelope)

    exc = caught.value
    assert isinstance(exc, error_type)
    assert exc.code == expected_code
    assert str(exc) == expected_code

    diagnostic = str(exc)
    for sentinel in absent_sentinels:
        if isinstance(sentinel, bytes):
            sentinel = sentinel.decode("utf-8", errors="replace")
        assert sentinel not in diagnostic


def mutate_one_bit(value: bytes, index: int = 0) -> bytes:
    mutated = bytearray(value)
    mutated[index] ^= 0x01
    return bytes(mutated)


def component_mapping(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        component["name"]: component
        for component in payload["components"]
    }


def assert_component_matches(
    result_component: Any,
    input_component: Mapping[str, Any],
) -> None:
    for field_name, expected_value in input_component.items():
        actual_value = getattr(result_component, field_name)
        if isinstance(expected_value, list):
            assert tuple(actual_value) == tuple(expected_value)
        elif isinstance(expected_value, dict):
            assert dict(actual_value) == expected_value
        else:
            assert actual_value == expected_value


def test_valid_signed_release_manifest_is_verified() -> None:
    payload = valid_release_document()
    result = make_verifier().verify(signed_envelope(payload))

    assert result.release_id == "r2-beta-01"
    assert isinstance(result.components, tuple)
    assert tuple(component.name for component in result.components) == (
        "launcher",
        "core",
    )

    expected_components = component_mapping(payload)
    for component in result.components:
        assert_component_matches(component, expected_components[component.name])


@pytest.mark.parametrize(
    "field_name",
    ("envelope_version", "key_id", "payload_b64", "signature_b64"),
)
def test_each_required_envelope_field_is_required(field_name: str) -> None:
    envelope = signed_envelope(valid_release_document())
    del envelope[field_name]

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_ENVELOPE_SCHEMA",
        absent_sentinels=(field_name,),
    )


def test_unknown_envelope_field_is_rejected() -> None:
    envelope = signed_envelope(valid_release_document())
    envelope["unexpected_field"] = "unexpected-value"

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_ENVELOPE_SCHEMA",
        absent_sentinels=("unexpected_field", "unexpected-value"),
    )


@pytest.mark.parametrize(
    "aliases",
    (
        {"version": 1},
        {"payload": "payload"},
        {"signature": "signature"},
        {
            "version": 1,
            "payload": "payload",
            "signature": "signature",
        },
    ),
)
def test_old_envelope_aliases_are_rejected(aliases: dict[str, object]) -> None:
    envelope = signed_envelope(valid_release_document())
    envelope.update(aliases)

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_ENVELOPE_SCHEMA",
        absent_sentinels=tuple(aliases),
    )


@pytest.mark.parametrize("document", (None, [], (), "envelope", 1, True))
def test_non_mapping_envelope_is_rejected(document: object) -> None:
    assert_verify_error(
        make_verifier(),
        document,
        "INVALID_ENVELOPE_TYPE",
        absent_sentinels=("envelope",),
    )


def test_envelope_version_builtin_integer_one_is_accepted() -> None:
    envelope = signed_envelope(valid_release_document())
    envelope["envelope_version"] = 1

    result = make_verifier().verify(envelope)

    assert result.release_id == "r2-beta-01"


@pytest.mark.parametrize("version", (True, 1.0, "1", IntSubclass(1)))
def test_envelope_version_requires_exact_builtin_integer(version: object) -> None:
    envelope = signed_envelope(valid_release_document())
    envelope["envelope_version"] = version

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_ENVELOPE_SCHEMA",
        absent_sentinels=(repr(version),),
    )


def test_unsupported_envelope_version_is_rejected() -> None:
    envelope = signed_envelope(valid_release_document())
    envelope["envelope_version"] = 2

    assert_verify_error(
        make_verifier(),
        envelope,
        "UNSUPPORTED_ENVELOPE_VERSION",
    )


@pytest.mark.parametrize("field_name", ("key_id", "payload_b64", "signature_b64"))
@pytest.mark.parametrize(
    "invalid_value",
    (1, True, b"text", StrSubclass("text")),
    ids=("integer", "boolean", "bytes", "str-subclass"),
)
def test_envelope_string_fields_require_exact_builtin_string(
    field_name: str,
    invalid_value: object,
) -> None:
    envelope = signed_envelope(valid_release_document())
    envelope[field_name] = invalid_value

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_ENVELOPE_SCHEMA",
        absent_sentinels=("text",),
    )


@pytest.mark.parametrize(
    "key_id",
    (
        "a",
        "a" * 64,
        "A_b.c-d9",
    ),
)
def test_valid_key_id_grammar_is_accepted(key_id: str) -> None:
    verifier = make_verifier({key_id: TEST_PUBLIC_KEY})
    envelope = signed_envelope(valid_release_document(), key_id=key_id)

    result = verifier.verify(envelope)

    assert result.release_id == "r2-beta-01"


@pytest.mark.parametrize(
    "key_id",
    (
        "",
        "a" * 65,
        "invalid/key",
        "invalid key",
        "clé",
    ),
)
def test_invalid_key_id_grammar_is_rejected(key_id: str) -> None:
    envelope = signed_envelope(valid_release_document())
    envelope["key_id"] = key_id

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_KEY_ID",
        absent_sentinels=(key_id,) if key_id else (),
    )


@pytest.mark.parametrize("field_name", ("payload_b64", "signature_b64"))
@pytest.mark.parametrize(
    "transform",
    (
        pytest.param(lambda value: "*" + value[1:], id="malformed-alphabet"),
        pytest.param(lambda value: value[:1] + " " + value[1:], id="whitespace"),
        pytest.param(lambda value: value + "=", id="malformed-padding"),
        pytest.param(noncanonical_base64_spelling, id="noncanonical-pad-bits"),
    ),
)
def test_base64_fields_require_canonical_standard_base64(
    field_name: str,
    transform: Callable[[str], str],
) -> None:
    envelope = signed_envelope(valid_release_document())
    canonical_value = envelope[field_name]
    assert isinstance(canonical_value, str)
    assert canonical_value.endswith("=")

    invalid_value = transform(canonical_value)
    assert invalid_value != canonical_value
    envelope[field_name] = invalid_value

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_BASE64",
        absent_sentinels=(invalid_value,),
    )


def test_payload_at_size_limit_reaches_json_validation() -> None:
    raw_payload = b" " * MAX_PAYLOAD_BYTES
    envelope = signed_envelope(raw_payload_bytes=raw_payload)

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_JSON",
        absent_sentinels=(raw_payload,),
    )


def test_payload_above_size_limit_is_rejected() -> None:
    raw_payload = b" " * (MAX_PAYLOAD_BYTES + 1)
    envelope = signed_envelope(raw_payload_bytes=raw_payload)

    assert_verify_error(
        make_verifier(),
        envelope,
        "PAYLOAD_TOO_LARGE",
        absent_sentinels=(raw_payload,),
    )


@pytest.mark.parametrize("signature_length", (63, 65))
def test_signature_must_be_exactly_64_bytes(signature_length: int) -> None:
    envelope = signed_envelope(valid_release_document())
    envelope["signature_b64"] = base64.b64encode(
        b"\xa5" * signature_length
    ).decode("ascii")

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_SIGNATURE_LENGTH",
        absent_sentinels=(str(signature_length),),
    )


def test_helper_produces_valid_64_byte_signature() -> None:
    envelope = signed_envelope(valid_release_document())
    signature = base64.b64decode(envelope["signature_b64"], validate=True)

    assert len(signature) == 64
    result = make_verifier().verify(envelope)
    assert result.release_id == "r2-beta-01"


@pytest.mark.parametrize(
    "public_key",
    (
        b"k" * 31,
        b"k" * 33,
        "k" * 32,
        bytearray(b"k" * 32),
        BytesSubclass(b"k" * 32),
    ),
    ids=("31-bytes", "33-bytes", "str", "bytearray", "bytes-subclass"),
)
def test_registry_public_key_requires_exact_builtin_32_byte_value(
    public_key: object,
) -> None:
    envelope = signed_envelope(valid_release_document())

    assert_verify_error(
        make_verifier({TEST_KEY_ID: public_key}),
        envelope,
        "INVALID_PUBLIC_KEY",
        absent_sentinels=("kkkkkkkk", repr(public_key)),
    )


def test_correct_registry_public_key_is_accepted() -> None:
    result = make_verifier({TEST_KEY_ID: TEST_PUBLIC_KEY}).verify(
        signed_envelope(valid_release_document())
    )

    assert result.release_id == "r2-beta-01"


@pytest.mark.parametrize("key_id", ("unknown-valid-key", PRODUCTION_KEY_ID))
def test_unknown_grammatically_valid_key_is_rejected(key_id: str) -> None:
    envelope = signed_envelope(valid_release_document())
    envelope["key_id"] = key_id

    assert_verify_error(
        make_verifier(),
        envelope,
        "UNKNOWN_KEY_ID",
        absent_sentinels=(key_id,),
    )


def test_production_named_key_is_not_implicitly_embedded() -> None:
    envelope = signed_envelope(
        valid_release_document(),
        key_id=PRODUCTION_KEY_ID,
    )

    assert_verify_error(
        make_verifier(get_test_key_registry()),
        envelope,
        "UNKNOWN_KEY_ID",
        absent_sentinels=(PRODUCTION_KEY_ID,),
    )


def test_explicitly_registered_production_named_key_is_accepted() -> None:
    envelope = signed_envelope(
        valid_release_document(),
        key_id=PRODUCTION_KEY_ID,
    )
    verifier = make_verifier({PRODUCTION_KEY_ID: TEST_PUBLIC_KEY})

    result = verifier.verify(envelope)

    assert result.release_id == "r2-beta-01"


def test_verifier_snapshots_mutable_registry_at_construction() -> None:
    registry = dict(get_test_key_registry())
    verifier = make_verifier(registry)
    envelope = signed_envelope(valid_release_document())

    registry.clear()
    registry[TEST_KEY_ID] = b"x" * 32

    result = verifier.verify(envelope)

    assert result.release_id == "r2-beta-01"


def test_malformed_payload_base64_precedes_unknown_key_lookup() -> None:
    envelope = signed_envelope(valid_release_document())
    envelope["key_id"] = "unknown-valid-key"
    envelope["payload_b64"] = "*invalid*"

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_BASE64",
        absent_sentinels=("*invalid*", "unknown-valid-key"),
    )


def test_malformed_signature_base64_precedes_unknown_key_lookup() -> None:
    envelope = signed_envelope(valid_release_document())
    envelope["key_id"] = "unknown-valid-key"
    envelope["signature_b64"] = "*invalid*"

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_BASE64",
        absent_sentinels=("*invalid*", "unknown-valid-key"),
    )


def test_signature_length_precedes_unknown_key_lookup() -> None:
    envelope = signed_envelope(valid_release_document())
    envelope["key_id"] = "unknown-valid-key"
    envelope["signature_b64"] = base64.b64encode(b"s" * 63).decode("ascii")

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_SIGNATURE_LENGTH",
        absent_sentinels=("unknown-valid-key",),
    )


def test_payload_size_precedes_unknown_key_lookup() -> None:
    envelope = signed_envelope(
        raw_payload_bytes=b" " * (MAX_PAYLOAD_BYTES + 1),
    )
    envelope["key_id"] = "unknown-valid-key"

    assert_verify_error(
        make_verifier(),
        envelope,
        "PAYLOAD_TOO_LARGE",
        absent_sentinels=("unknown-valid-key",),
    )


def parser_guard_cases() -> tuple[tuple[str, object, Mapping[str, object], str], ...]:
    valid_envelope = signed_envelope(valid_release_document())

    missing_field = dict(valid_envelope)
    del missing_field["signature_b64"]

    unknown_field = dict(valid_envelope)
    unknown_field["extra"] = "sentinel-extra"

    wrong_type = dict(valid_envelope)
    wrong_type["key_id"] = StrSubclass(TEST_KEY_ID)

    unsupported_version = dict(valid_envelope)
    unsupported_version["envelope_version"] = 2

    invalid_key = dict(valid_envelope)
    invalid_key["key_id"] = "invalid/key"

    malformed_payload = dict(valid_envelope)
    malformed_payload["payload_b64"] = "*invalid*"

    malformed_signature = dict(valid_envelope)
    malformed_signature["signature_b64"] = "*invalid*"

    noncanonical_payload = dict(valid_envelope)
    noncanonical_payload["payload_b64"] = noncanonical_base64_spelling(
        valid_envelope["payload_b64"]
    )

    noncanonical_signature = dict(valid_envelope)
    noncanonical_signature["signature_b64"] = noncanonical_base64_spelling(
        valid_envelope["signature_b64"]
    )

    oversized_payload = signed_envelope(
        raw_payload_bytes=b" " * (MAX_PAYLOAD_BYTES + 1)
    )

    wrong_signature_length = dict(valid_envelope)
    wrong_signature_length["signature_b64"] = base64.b64encode(
        b"s" * 63
    ).decode("ascii")

    unknown_key = dict(valid_envelope)
    unknown_key["key_id"] = "unknown-valid-key"

    invalid_public_key = valid_envelope

    tampered_signature = dict(valid_envelope)
    signature = base64.b64decode(
        tampered_signature["signature_b64"],
        validate=True,
    )
    tampered_signature["signature_b64"] = base64.b64encode(
        mutate_one_bit(signature)
    ).decode("ascii")

    return (
        (
            "non-mapping",
            [],
            get_test_key_registry(),
            "INVALID_ENVELOPE_TYPE",
        ),
        (
            "missing-field",
            missing_field,
            get_test_key_registry(),
            "INVALID_ENVELOPE_SCHEMA",
        ),
        (
            "unknown-field",
            unknown_field,
            get_test_key_registry(),
            "INVALID_ENVELOPE_SCHEMA",
        ),
        (
            "wrong-exact-type",
            wrong_type,
            get_test_key_registry(),
            "INVALID_ENVELOPE_SCHEMA",
        ),
        (
            "unsupported-version",
            unsupported_version,
            get_test_key_registry(),
            "UNSUPPORTED_ENVELOPE_VERSION",
        ),
        (
            "invalid-key-grammar",
            invalid_key,
            get_test_key_registry(),
            "INVALID_KEY_ID",
        ),
        (
            "malformed-payload-base64",
            malformed_payload,
            get_test_key_registry(),
            "INVALID_BASE64",
        ),
        (
            "malformed-signature-base64",
            malformed_signature,
            get_test_key_registry(),
            "INVALID_BASE64",
        ),
        (
            "noncanonical-payload-base64",
            noncanonical_payload,
            get_test_key_registry(),
            "INVALID_BASE64",
        ),
        (
            "noncanonical-signature-base64",
            noncanonical_signature,
            get_test_key_registry(),
            "INVALID_BASE64",
        ),
        (
            "payload-too-large",
            oversized_payload,
            get_test_key_registry(),
            "PAYLOAD_TOO_LARGE",
        ),
        (
            "signature-wrong-length",
            wrong_signature_length,
            get_test_key_registry(),
            "INVALID_SIGNATURE_LENGTH",
        ),
        (
            "unknown-key",
            unknown_key,
            get_test_key_registry(),
            "UNKNOWN_KEY_ID",
        ),
        (
            "invalid-public-key",
            invalid_public_key,
            {TEST_KEY_ID: b"k" * 31},
            "INVALID_PUBLIC_KEY",
        ),
        (
            "signature-tamper",
            tampered_signature,
            get_test_key_registry(),
            "SIGNATURE_INVALID",
        ),
    )


@pytest.mark.parametrize(
    ("case_name", "envelope", "registry", "expected_code"),
    parser_guard_cases(),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_parser_is_not_called_before_authenticated_payload_parsing(
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
    envelope: object,
    registry: Mapping[str, object],
    expected_code: str,
) -> None:
    parser_module = importlib.import_module(
        "neko_launcher.application.software_update_models"
    )
    verifier_module_name = (
        "neko_launcher.infrastructure.software_update_manifest"
    )
    called = False

    def forbidden_parser(document: object) -> object:
        nonlocal called
        called = True
        raise AssertionError(
            f"parser called for pre-parser failure case {case_name}: {document!r}"
        )

    with monkeypatch.context() as patch_context:
        patch_context.setattr(parser_module, "parse_release_set", forbidden_parser)
        if verifier_module_name in sys.modules:
            verifier_module = importlib.reload(sys.modules[verifier_module_name])
        else:
            verifier_module = importlib.import_module(verifier_module_name)

        verifier = verifier_module.ReleaseManifestVerifier(registry)
        assert_verify_error(verifier, envelope, expected_code)
        assert called is False

    importlib.reload(verifier_module)


def test_authenticated_noncanonical_json_bytes_are_authoritative() -> None:
    payload = valid_release_document()
    raw_payload = json.dumps(
        payload,
        indent=2,
        sort_keys=False,
        ensure_ascii=False,
    ).encode("utf-8")

    assert raw_payload != canonical_payload_bytes(payload)

    result = make_verifier().verify(
        signed_envelope(raw_payload_bytes=raw_payload)
    )

    assert result.release_id == "r2-beta-01"
    assert tuple(component.name for component in result.components) == (
        "launcher",
        "core",
    )


def test_one_bit_payload_tamper_invalidates_signature() -> None:
    raw_payload = canonical_payload_bytes(valid_release_document())
    envelope = signed_envelope(raw_payload_bytes=raw_payload)
    tampered_payload = mutate_one_bit(raw_payload)
    envelope["payload_b64"] = base64.b64encode(tampered_payload).decode("ascii")

    assert_verify_error(
        make_verifier(),
        envelope,
        "SIGNATURE_INVALID",
        absent_sentinels=(tampered_payload,),
    )


def test_one_bit_signature_tamper_invalidates_signature() -> None:
    envelope = signed_envelope(valid_release_document())
    signature = base64.b64decode(envelope["signature_b64"], validate=True)
    tampered_signature = mutate_one_bit(signature)
    envelope["signature_b64"] = base64.b64encode(tampered_signature).decode(
        "ascii"
    )

    assert_verify_error(
        make_verifier(),
        envelope,
        "SIGNATURE_INVALID",
        absent_sentinels=(tampered_signature,),
    )


def test_authenticated_invalid_utf8_is_rejected() -> None:
    raw_payload = b"\xff\xfeinvalid-utf8-sentinel"
    envelope = signed_envelope(raw_payload_bytes=raw_payload)

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_UTF8",
        absent_sentinels=(
            raw_payload,
            "invalid-utf8-sentinel",
            "'utf-8' codec",
        ),
    )


def test_authenticated_valid_utf8_invalid_json_is_rejected() -> None:
    raw_payload = b"valid-utf8-invalid-json-sentinel"
    envelope = signed_envelope(raw_payload_bytes=raw_payload)

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_JSON",
        absent_sentinels=(
            raw_payload,
            "valid-utf8-invalid-json-sentinel",
            "Expecting value",
        ),
    )


def test_authenticated_task_one_schema_violation_is_rejected() -> None:
    raw_payload = json.dumps(
        {"schema_sentinel_secret": "not-a-release-set"},
        separators=(",", ":"),
    ).encode("utf-8")
    envelope = signed_envelope(raw_payload_bytes=raw_payload)

    assert_verify_error(
        make_verifier(),
        envelope,
        "INVALID_PAYLOAD_SCHEMA",
        absent_sentinels=(
            raw_payload,
            "schema_sentinel_secret",
            "not-a-release-set",
        ),
    )
