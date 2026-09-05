import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TEST_KEY_ID = "neko-update-test-1"

# Deterministic 32-byte seed for the test private key.
_TEST_SEED = b"test-only-deterministic-key-0000"
_TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_TEST_SEED)

TEST_PUBLIC_KEY: bytes = _TEST_PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw
)


def get_test_key_registry() -> dict[str, bytes]:
    return {TEST_KEY_ID: TEST_PUBLIC_KEY}


def valid_release_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "channel": "beta",
        "release_sequence": 2,
        "release_id": "r2-beta-01",
        "mandatory": False,
        "minimum_supported_sequence": 1,
        "components": [
            {
                "name": "core",
                "version": "1.0.0",
                "artifact_id": "core-1.0.0-bin",
                "artifact_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
                "artifact_size": 102400,
                "installed_identity_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
            },
            {
                "name": "launcher",
                "version": "1.0.0",
                "artifact_id": "launcher-1.0.0-bin",
                "artifact_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
                "artifact_size": 20480,
                "installed_identity_sha256": "4444444444444444444444444444444444444444444444444444444444444444",
            },
        ],
    }


def canonical_payload_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True
    ).encode("utf-8")


def signed_envelope(
    payload: dict[str, object] | None = None,
    *,
    raw_payload_bytes: bytes | None = None,
    key_id: str = TEST_KEY_ID,
    envelope_version: object = 1,
    private_key: Ed25519PrivateKey | None = None
) -> dict[str, object]:
    if (payload is None) == (raw_payload_bytes is None):
        raise ValueError("Exactly one of payload or raw_payload_bytes must be provided")

    if raw_payload_bytes is not None:
        payload_bytes = raw_payload_bytes
    else:
        payload_bytes = canonical_payload_bytes(payload)  # type: ignore

    if private_key is None:
        private_key = _TEST_PRIVATE_KEY

    signature = private_key.sign(payload_bytes)

    return {
        "envelope_version": envelope_version,
        "key_id": key_id,
        "payload_b64": base64.standard_b64encode(payload_bytes).decode("ascii"),
        "signature_b64": base64.standard_b64encode(signature).decode("ascii"),
    }


def noncanonical_base64_spelling(canonical: str) -> str:
    if not canonical.endswith("="):
        raise ValueError("No padding in base64 string; cannot create noncanonical spelling.")

    b64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    chars = list(canonical)

    target_idx = -3 if canonical.endswith("==") else -2

    char_val = b64_chars.index(chars[target_idx])
    new_char_val = char_val ^ 1
    chars[target_idx] = b64_chars[new_char_val]

    return "".join(chars)
