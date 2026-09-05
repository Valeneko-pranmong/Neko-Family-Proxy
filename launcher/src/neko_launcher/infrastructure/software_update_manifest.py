from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from neko_launcher.application.software_update_models import (
    ReleaseSet,
    parse_release_set,
)

_ENVELOPE_KEYS = {
    "envelope_version",
    "key_id",
    "payload_b64",
    "signature_b64",
}
_KEY_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
_MAX_PAYLOAD_SIZE = 49_152
_SIGNATURE_SIZE = 64
_PUBLIC_KEY_SIZE = 32


class ManifestVerificationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _error(code: str) -> ManifestVerificationError:
    return ManifestVerificationError(code)


def _decode_base64(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise _error("INVALID_BASE64") from None

    if base64.b64encode(decoded).decode("ascii") != value:
        raise _error("INVALID_BASE64")
    return decoded


class ReleaseManifestVerifier:
    def __init__(self, key_registry: Mapping[str, bytes]) -> None:
        self._key_registry = dict(key_registry)

    def verify(self, document: object) -> ReleaseSet:
        if not isinstance(document, Mapping):
            raise _error("INVALID_ENVELOPE_TYPE")

        if set(document) != _ENVELOPE_KEYS:
            raise _error("INVALID_ENVELOPE_SCHEMA")

        envelope_version = document["envelope_version"]
        if type(envelope_version) is not int:
            raise _error("INVALID_ENVELOPE_SCHEMA")
        if envelope_version != 1:
            raise _error("UNSUPPORTED_ENVELOPE_VERSION")

        key_id = document["key_id"]
        payload_b64 = document["payload_b64"]
        signature_b64 = document["signature_b64"]
        if (
            type(key_id) is not str
            or type(payload_b64) is not str
            or type(signature_b64) is not str
        ):
            raise _error("INVALID_ENVELOPE_SCHEMA")

        if _KEY_ID_PATTERN.fullmatch(key_id) is None:
            raise _error("INVALID_KEY_ID")

        payload_bytes = _decode_base64(payload_b64)
        signature_bytes = _decode_base64(signature_b64)

        if len(payload_bytes) > _MAX_PAYLOAD_SIZE:
            raise _error("PAYLOAD_TOO_LARGE")
        if len(signature_bytes) != _SIGNATURE_SIZE:
            raise _error("INVALID_SIGNATURE_LENGTH")

        if key_id not in self._key_registry:
            raise _error("UNKNOWN_KEY_ID")

        public_key_bytes = self._key_registry[key_id]
        if (
            type(public_key_bytes) is not bytes
            or len(public_key_bytes) != _PUBLIC_KEY_SIZE
        ):
            raise _error("INVALID_PUBLIC_KEY")

        try:
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        except ValueError:
            raise _error("INVALID_PUBLIC_KEY") from None

        try:
            public_key.verify(signature_bytes, payload_bytes)
        except InvalidSignature:
            raise _error("SIGNATURE_INVALID") from None

        try:
            payload_text = payload_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise _error("INVALID_UTF8") from None

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            raise _error("INVALID_JSON") from None

        try:
            return parse_release_set(payload)
        except ValueError:
            raise _error("INVALID_PAYLOAD_SCHEMA") from None
