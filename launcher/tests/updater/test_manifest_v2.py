import copy
import pytest

from neko_launcher.updater import manifest_v2
from neko_launcher.updater.manifest_v2 import parse_release_v2, verify_release_envelope_v2
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_legacy_v2_release_document,
    valid_v2_release_document,
)


def sample_valid_v2_doc() -> dict[str, object]:
    return valid_v2_release_document()


def test_updater_protocol_version_constant_defined():
    proto = getattr(manifest_v2, "UPDATER_PROTOCOL_VERSION", None)
    assert proto == 1


def test_parse_release_v2_valid_three_component_stable():
    doc = sample_valid_v2_doc()
    parsed = parse_release_v2(doc)
    assert parsed.schema_version == 2
    assert parsed.channel == "stable"
    assert parsed.updater_protocol.minimum == 1
    assert parsed.components["launcher"].artifact_format == "raw-pe-v1"
    assert parsed.components["updater"].artifact_format == "raw-pe-v1"
    assert parsed.components["core"].artifact_format == "zip-core-v1"
    assert parsed.components["launcher"].artifact_sha256 == parsed.components["launcher"].installed_identity_sha256
    assert parsed.components["updater"].artifact_sha256 == parsed.components["updater"].installed_identity_sha256


def test_parse_release_v2_rejects_v1():
    doc = sample_valid_v2_doc()
    doc["schema_version"] = 1
    with pytest.raises(ValueError, match="schema_version must be 2"):
        parse_release_v2(doc)


def test_parse_release_v2_rejects_beta_channel():
    doc = sample_valid_v2_doc()
    doc["channel"] = "beta"
    with pytest.raises(ValueError, match="channel must be 'stable'"):
        parse_release_v2(doc)


def test_parse_release_v2_rejects_legacy_exact_two_components():
    legacy_doc = valid_legacy_v2_release_document(channel="stable")
    with pytest.raises(ValueError, match="components must contain exactly 'launcher', 'updater', and 'core'"):
        parse_release_v2(legacy_doc)


def test_parse_release_v2_updater_raw_pe_validation():
    doc = sample_valid_v2_doc()
    # Updater format must be raw-pe-v1
    doc_bad_fmt = copy.deepcopy(doc)
    doc_bad_fmt["components"]["updater"]["artifact_format"] = "zip-core-v1"
    with pytest.raises(ValueError, match="Updater artifact_format must be 'raw-pe-v1'"):
        parse_release_v2(doc_bad_fmt)

    # Updater size limit <= 128 MiB (134217728)
    doc_oversize = copy.deepcopy(doc)
    doc_oversize["components"]["updater"]["artifact_size"] = 134217728 + 1
    with pytest.raises(ValueError, match="Updater artifact exceeds 128 MiB"):
        parse_release_v2(doc_oversize)

    # Updater artifact_sha256 must equal installed_identity_sha256
    doc_mismatch_sha = copy.deepcopy(doc)
    doc_mismatch_sha["components"]["updater"]["installed_identity_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="Updater artifact_sha256 must equal installed_identity_sha256"):
        parse_release_v2(doc_mismatch_sha)


def test_verify_release_envelope_v2_success():
    doc = sample_valid_v2_doc()
    envelope = signed_envelope(doc)
    release_set, payload_sha = verify_release_envelope_v2(envelope, {TEST_KEY_ID: TEST_PUBLIC_KEY})
    assert release_set.release_sequence == 2
    assert release_set.channel == "stable"
    assert len(payload_sha) == 64
    assert set(release_set.components.keys()) == {"launcher", "updater", "core"}


def test_verify_release_envelope_v2_rejects_legacy_two_component():
    doc = valid_legacy_v2_release_document()
    envelope = signed_envelope(doc)
    with pytest.raises(ValueError):
        verify_release_envelope_v2(envelope, {TEST_KEY_ID: TEST_PUBLIC_KEY})


def test_verify_legacy_recovery_envelope_v2_success():
    verify_legacy = getattr(manifest_v2, "verify_legacy_recovery_envelope_v2", None)
    assert callable(verify_legacy), "verify_legacy_recovery_envelope_v2 must be defined in manifest_v2"

    doc = valid_legacy_v2_release_document(sequence=42, release_id="r42-beta")
    envelope = signed_envelope(doc)
    release_set, payload_sha = verify_legacy(envelope, {TEST_KEY_ID: TEST_PUBLIC_KEY})

    assert release_set.release_sequence == 42
    assert release_set.release_id == "r42-beta"
    assert release_set.channel == "beta"
    assert len(payload_sha) == 64
    # Legacy verifier must contain ONLY launcher and core - no synthesized updater
    assert set(release_set.components.keys()) == {"launcher", "core"}


def test_verify_legacy_recovery_envelope_v2_rejects_invalid_signature():
    verify_legacy = getattr(manifest_v2, "verify_legacy_recovery_envelope_v2", None)
    assert callable(verify_legacy), "verify_legacy_recovery_envelope_v2 must be defined in manifest_v2"

    doc = valid_legacy_v2_release_document()
    envelope = signed_envelope(doc)
    envelope["signature_b64"] = "A" * 86 + "=="
    with pytest.raises(ValueError):
        verify_legacy(envelope, {TEST_KEY_ID: TEST_PUBLIC_KEY})


def test_verify_legacy_recovery_envelope_v2_rejects_three_component():
    verify_legacy = getattr(manifest_v2, "verify_legacy_recovery_envelope_v2", None)
    assert callable(verify_legacy), "verify_legacy_recovery_envelope_v2 must be defined in manifest_v2"

    doc = valid_v2_release_document()
    envelope = signed_envelope(doc)
    with pytest.raises(ValueError):
        verify_legacy(envelope, {TEST_KEY_ID: TEST_PUBLIC_KEY})
