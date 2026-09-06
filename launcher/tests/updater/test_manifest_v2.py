import pytest

from neko_launcher.updater.manifest_v2 import parse_release_v2, verify_release_envelope_v2
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_release_document,
)


def sample_valid_v2_doc() -> dict[str, object]:
    doc = valid_release_document()
    doc["schema_version"] = 2
    doc["channel"] = "beta"
    doc["release_sequence"] = 2
    doc["release_id"] = "r2-beta"
    doc["mandatory"] = False
    doc["minimum_supported_sequence"] = 1
    doc["updater_protocol"] = {"minimum": 1, "maximum": 1}
    doc["components"]["launcher"]["artifact_format"] = "raw-pe-v1"
    doc["components"]["launcher"]["installed_identity_sha256"] = doc["components"]["launcher"]["artifact_sha256"]
    doc["components"]["core"]["artifact_format"] = "zip-core-v1"
    return doc


def test_parse_release_v2_valid():
    doc = sample_valid_v2_doc()
    parsed = parse_release_v2(doc)
    assert parsed.schema_version == 2
    assert parsed.channel == "beta"
    assert parsed.updater_protocol.minimum == 1
    assert parsed.components["launcher"].artifact_format == "raw-pe-v1"
    assert parsed.components["core"].artifact_format == "zip-core-v1"


def test_parse_release_v2_rejects_v1():
    doc = sample_valid_v2_doc()
    doc["schema_version"] = 1
    with pytest.raises(ValueError, match="schema_version must be 2"):
        parse_release_v2(doc)


def test_verify_release_envelope_v2_success():
    doc = sample_valid_v2_doc()
    envelope = signed_envelope(doc)
    release_set, payload_sha = verify_release_envelope_v2(envelope, {TEST_KEY_ID: TEST_PUBLIC_KEY})
    assert release_set.release_sequence == 2
    assert len(payload_sha) == 64
