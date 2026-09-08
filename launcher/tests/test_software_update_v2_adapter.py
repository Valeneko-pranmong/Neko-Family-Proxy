from __future__ import annotations

from typing import Any

import pytest

from neko_launcher.application.software_update_models import (
    LocalReleaseIdentity,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)
from neko_launcher.application.software_update_policy import evaluate_release
from neko_launcher.application.software_update_service import (
    _VERIFIER_REJECTED_CODES,
    UpdateCheckService,
)

try:
    from tests.software_update_helpers import (
        get_test_key_registry,
        signed_envelope,
        valid_release_document,
    )
except ImportError:
    from software_update_helpers import (  # type: ignore[no-redef]
        get_test_key_registry,
        signed_envelope,
        valid_release_document,
    )


def _get_v2_adapter_cls() -> Any:
    for mod_name in (
        "neko_launcher.infrastructure.software_update_manifest",
        "neko_launcher.infrastructure.software_update_v2_adapter",
        "neko_launcher.infrastructure.software_update_adapter",
    ):
        try:
            mod = __import__(mod_name, fromlist=["V2ReleaseManifestVerifierAdapter"])
            cls = getattr(mod, "V2ReleaseManifestVerifierAdapter", None)
            if cls is not None:
                return cls
        except ImportError:
            pass
    pytest.fail("V2ReleaseManifestVerifierAdapter not implemented", pytrace=False)


def sample_valid_v2_document(
    *,
    sequence: int = 42,
    release_id: str = "r-42-stable",
    mandatory: bool = False,
    minimum_supported_sequence: int = 1,
    proto_min: int = 1,
    proto_max: int = 1,
    launcher_sha: str = "a" * 64,
    launcher_size: int = 1024,
    updater_sha: str = "d" * 64,
    updater_size: int = 1024,
    core_sha: str = "b" * 64,
    core_size: int = 2048,
    core_installed_sha: str = "c" * 64,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "channel": "stable",
        "release_sequence": sequence,
        "release_id": release_id,
        "mandatory": mandatory,
        "minimum_supported_sequence": minimum_supported_sequence,
        "updater_protocol": {"minimum": proto_min, "maximum": proto_max},
        "components": {
            "launcher": {
                "version": "2.0.0",
                "artifact_id": f"launcher-{sequence}",
                "artifact_sha256": launcher_sha,
                "installed_identity_sha256": launcher_sha,
                "artifact_size": launcher_size,
                "artifact_format": "raw-pe-v1",
            },
            "updater": {
                "version": "2.0.0",
                "artifact_id": f"updater-{sequence}",
                "artifact_sha256": updater_sha,
                "installed_identity_sha256": updater_sha,
                "artifact_size": updater_size,
                "artifact_format": "raw-pe-v1",
            },
            "core": {
                "version": "3.0.0",
                "artifact_id": f"core-{sequence}",
                "artifact_sha256": core_sha,
                "installed_identity_sha256": core_installed_sha,
                "artifact_size": core_size,
                "artifact_format": "zip-core-v1",
            },
        },
    }



def test_v2_adapter_maps_valid_signed_release_set_v2_to_application_release_set() -> None:
    adapter_cls = _get_v2_adapter_cls()
    adapter = adapter_cls(get_test_key_registry())
    doc = sample_valid_v2_document(sequence=42, release_id="rel-42", mandatory=True)
    envelope = signed_envelope(doc)

    release_set = adapter.verify(envelope)

    assert release_set.release_sequence == 42
    assert release_set.release_id == "rel-42"
    assert release_set.mandatory is True
    assert release_set.minimum_supported_sequence == 1

    components = {comp.name: comp for comp in release_set.components}
    assert "launcher" in components
    assert "core" in components
    launcher = components["launcher"]
    assert launcher.version == "2.0.0"
    assert launcher.artifact_id == "launcher-42"
    assert launcher.artifact_sha256 == "a" * 64
    assert launcher.installed_identity_sha256 == "a" * 64
    assert launcher.artifact_size == 1024

    core = components["core"]
    assert core.version == "3.0.0"
    assert core.artifact_id == "core-42"
    assert core.artifact_sha256 == "b" * 64
    assert core.installed_identity_sha256 == "c" * 64
    assert core.artifact_size == 2048

    # Verify compatibility with policy evaluation
    local_id = LocalReleaseIdentity(
        release_sequence=41,
        release_id="rel-41",
        launcher_version="1.9.0",
        launcher_installed_identity_sha256="z" * 64,
        core_version="2.9.0",
        core_installed_identity_sha256="y" * 64,
    )
    result = evaluate_release(local_id, release_set, UpdateInvocationReason.MANUAL)
    assert result.state == UpdateState.MANDATORY
    assert result.release_sequence == 42
    assert result.mandatory is True


def test_v2_adapter_rejects_bad_signature_with_manifest_rejected_code() -> None:
    adapter_cls = _get_v2_adapter_cls()
    adapter = adapter_cls(get_test_key_registry())
    doc = sample_valid_v2_document()
    envelope = signed_envelope(doc)
    # Corrupt the signature
    envelope["signature_b64"] = "A" * 86 + "=="

    with pytest.raises(Exception) as exc_info:
        adapter.verify(envelope)

    code = getattr(exc_info.value, "code", None)
    assert code in _VERIFIER_REJECTED_CODES
    diag = UpdateCheckService._verifier_exception_result(
        UpdateInvocationReason.MANUAL,
        exc_info.value,
    )
    assert diag.state == UpdateState.VERIFY_FAILED
    assert diag.diagnostic_code == UpdateDiagnosticCode.MANIFEST_REJECTED


def test_v2_adapter_rejects_invalid_v2_schema_or_unsupported_protocol() -> None:
    adapter_cls = _get_v2_adapter_cls()
    adapter = adapter_cls(get_test_key_registry())

    # Invalid protocol range (min > max)
    invalid_proto_doc = sample_valid_v2_document(proto_min=5, proto_max=2)
    envelope_bad_proto = signed_envelope(invalid_proto_doc)

    with pytest.raises(Exception) as exc_proto:
        adapter.verify(envelope_bad_proto)

    code_proto = getattr(exc_proto.value, "code", None)
    assert code_proto in _VERIFIER_REJECTED_CODES
    diag_proto = UpdateCheckService._verifier_exception_result(
        UpdateInvocationReason.MANUAL,
        exc_proto.value,
    )
    assert diag_proto.state == UpdateState.VERIFY_FAILED
    assert diag_proto.diagnostic_code == UpdateDiagnosticCode.MANIFEST_REJECTED

    # Invalid component field / bad schema
    bad_schema_doc = sample_valid_v2_document()
    del bad_schema_doc["components"]["launcher"]["artifact_format"]
    envelope_bad_schema = signed_envelope(bad_schema_doc)

    with pytest.raises(Exception) as exc_schema:
        adapter.verify(envelope_bad_schema)

    code_schema = getattr(exc_schema.value, "code", None)
    assert code_schema in _VERIFIER_REJECTED_CODES


def test_v2_adapter_rejects_legacy_schema_v1_envelope() -> None:
    adapter_cls = _get_v2_adapter_cls()
    adapter = adapter_cls(get_test_key_registry())

    # Valid schema v1 envelope
    v1_doc = valid_release_document()
    assert v1_doc["schema_version"] == 1
    envelope_v1 = signed_envelope(v1_doc)

    with pytest.raises(Exception) as exc_v1:
        adapter.verify(envelope_v1)

    code_v1 = getattr(exc_v1.value, "code", None)
    assert code_v1 in _VERIFIER_REJECTED_CODES
    diag_v1 = UpdateCheckService._verifier_exception_result(
        UpdateInvocationReason.MANUAL,
        exc_v1.value,
    )
    assert diag_v1.state == UpdateState.VERIFY_FAILED
    assert diag_v1.diagnostic_code == UpdateDiagnosticCode.MANIFEST_REJECTED


def test_v2_adapter_rejects_legacy_two_component_beta_envelope() -> None:
    from tests.software_update_helpers import valid_legacy_v2_release_document

    adapter_cls = _get_v2_adapter_cls()
    adapter = adapter_cls(get_test_key_registry())

    # Valid legacy 2-component envelope must be rejected by V2ReleaseManifestVerifierAdapter
    legacy_doc = valid_legacy_v2_release_document()
    envelope_legacy = signed_envelope(legacy_doc)

    with pytest.raises(Exception) as exc_legacy:
        adapter.verify(envelope_legacy)

    code_legacy = getattr(exc_legacy.value, "code", None)
    assert code_legacy in _VERIFIER_REJECTED_CODES


def test_v2_adapter_has_no_private_helper_protocol_version() -> None:
    import neko_launcher.infrastructure.software_update_v2 as su_v2
    # The private duplicate _HELPER_PROTOCOL_VERSION must be removed
    assert not hasattr(su_v2, "_HELPER_PROTOCOL_VERSION"), (
        "_HELPER_PROTOCOL_VERSION must be replaced by authoritative shared constant"
    )
