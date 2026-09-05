import dataclasses
import re
import pytest
from dataclasses import FrozenInstanceError

def lazy_import():
    try:
        from neko_launcher.application.software_update_models import (
            ComponentRelease,
            ReleaseSet,
            LocalReleaseIdentity,
            UpdateInvocationReason,
            UpdateState,
            UpdateDiagnosticCode,
            UpdateCheckResult,
            parse_release_set,
        )
        return True, (ComponentRelease, ReleaseSet, LocalReleaseIdentity, UpdateInvocationReason, UpdateState, UpdateDiagnosticCode, UpdateCheckResult, parse_release_set)
    except ImportError:
        return False, None

def valid_release_document():
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
                "version": "1.0.0-rc1",
                "artifact_id": "core-1.0.0-win64",
                "artifact_sha256": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                "artifact_size": 25000000,
                "installed_identity_sha256": "fedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321"
            },
            {
                "name": "launcher",
                "version": "5.1.0a1",
                "artifact_id": "launcher-5.1.0a1-win64",
                "artifact_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                "artifact_size": 15000000,
                "installed_identity_sha256": "0987654321fedcba0987654321fedcba0987654321fedcba0987654321fedcba"
            }
        ]
    }

def test_enums_and_immutability():
    ok, symbols = lazy_import()
    if not ok:
        pytest.fail("Module neko_launcher.application.software_update_models missing or fails to import")
    ComponentRelease, ReleaseSet, LocalReleaseIdentity, UpdateInvocationReason, UpdateState, UpdateDiagnosticCode, UpdateCheckResult, _ = symbols

    assert UpdateInvocationReason.STARTUP == "startup"
    assert UpdateInvocationReason.MANUAL == "manual"

    assert UpdateState.NOT_CHECKED == "not_checked"
    assert UpdateState.CHECKING == "checking"
    assert UpdateState.LATEST == "latest"
    assert UpdateState.AVAILABLE == "available"
    assert UpdateState.MANDATORY == "mandatory"
    assert UpdateState.UNAVAILABLE == "unavailable"
    assert UpdateState.VERIFY_FAILED == "verify_failed"

    assert UpdateDiagnosticCode.DOWNGRADE_REJECTED == "DOWNGRADE_REJECTED"
    assert UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT == "SAME_SEQUENCE_IDENTITY_CONFLICT"

    launcher_c = ComponentRelease("launcher", "1.0", "a_id", "a"*64, 10, "b"*64)
    with pytest.raises(FrozenInstanceError):
        launcher_c.version = "1.1"
    core_c = ComponentRelease("core", "1.0", "c_id", "c"*64, 20, "d"*64)

    r = ReleaseSet(1, "beta", 2, "r2", False, 1, (launcher_c, core_c))
    with pytest.raises(FrozenInstanceError):
        r.release_sequence = 3

    loc_ident = LocalReleaseIdentity(1, "r1", "1.0", "a"*64, "1.0", "b"*64)
    with pytest.raises(FrozenInstanceError):
        loc_ident.release_id = "r2"

    u = UpdateCheckResult(UpdateState.LATEST, UpdateInvocationReason.STARTUP, "r1", 1, ("launcher",), "1.0", "1.0", False, None)
    with pytest.raises(FrozenInstanceError):
        u.state = UpdateState.AVAILABLE

@pytest.mark.parametrize("invalid_diag", ["SOME_OTHER_ERROR", "DOWNGRADE_REJECTED", "SAME_SEQUENCE_IDENTITY_CONFLICT"])
def test_update_check_result_rejects_free_string_diagnostic(invalid_diag):
    ok, symbols = lazy_import()
    if not ok:
        pytest.fail("Module neko_launcher.application.software_update_models missing or fails to import")
    _, _, _, UpdateInvocationReason, UpdateState, _, UpdateCheckResult, _ = symbols

    with pytest.raises(ValueError):
        UpdateCheckResult(UpdateState.VERIFY_FAILED, UpdateInvocationReason.STARTUP, "r1", 1, ("launcher",), "1.0", "1.0", False, invalid_diag)

def test_local_identity_validation():
    ok, symbols = lazy_import()
    if not ok:
        pytest.fail("Module neko_launcher.application.software_update_models missing or fails to import")
    _, _, LocalReleaseIdentity, _, _, _, _, _ = symbols

    loc_ident = LocalReleaseIdentity(0, "dev-unpublished", "1.0", "a"*64, "1.0", "b"*64)
    assert loc_ident.release_sequence == 0

    with pytest.raises(ValueError):
        LocalReleaseIdentity(0, "some-other-id", "1.0", "a"*64, "1.0", "b"*64)

    LocalReleaseIdentity(1, "some-other-id", "1.0", "a"*64, "1.0", "b"*64)

def test_parse_release_set_accepts_exact_beta_schema():
    ok, symbols = lazy_import()
    if not ok:
        pytest.fail("Module neko_launcher.application.software_update_models missing or fails to import")
    _, _, _, _, _, _, _, parse_release_set = symbols

    release = parse_release_set(valid_release_document())
    assert release.release_sequence == 2
    assert release.schema_version == 1
    assert release.channel == "beta"
    assert release.release_sequence == 2
    assert release.release_id == "r2-beta-01"
    assert release.mandatory is False
    assert release.minimum_supported_sequence == 1
    assert isinstance(release.components, tuple)
    assert len(release.components) == 2
    assert release.components[0].name == "launcher"
    assert release.components[0].version == "5.1.0a1"
    assert release.components[0].artifact_id == "launcher-5.1.0a1-win64"
    assert release.components[0].artifact_sha256 == "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    assert release.components[0].artifact_size == 15000000
    assert release.components[0].installed_identity_sha256 == "0987654321fedcba0987654321fedcba0987654321fedcba0987654321fedcba"
    assert release.components[1].name == "core"
    assert release.components[1].version == "1.0.0-rc1"
    assert release.components[1].artifact_id == "core-1.0.0-win64"
    assert release.components[1].artifact_sha256 == "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    assert release.components[1].artifact_size == 25000000
    assert release.components[1].installed_identity_sha256 == "fedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321"

@pytest.mark.parametrize("mutate", [
    lambda d: {**d, "extra": True},
    lambda d: {k: v for k, v in d.items() if k != "release_sequence"},
    lambda d: {**d, "schema_version": 2},
    lambda d: {**d, "schema_version": True},
    lambda d: {**d, "schema_version": 1.0},
    lambda d: {**d, "channel": "stable"},
    lambda d: {**d, "channel": "alpha"},
    lambda d: {**d, "release_sequence": 0},
    lambda d: {**d, "release_sequence": -1},
    lambda d: {**d, "release_sequence": 9223372036854775808},
    lambda d: {**d, "release_sequence": True},
    lambda d: {**d, "release_sequence": 2.0},
    lambda d: {**d, "minimum_supported_sequence": 0},
    lambda d: {**d, "minimum_supported_sequence": 3},
    lambda d: {**d, "minimum_supported_sequence": True},
    lambda d: {**d, "minimum_supported_sequence": 1.0},
    lambda d: {**d, "mandatory": 1},
    lambda d: {**d, "mandatory": "False"},
    lambda d: {**d, "release_id": ""},
    lambda d: {**d, "release_id": "r"*65},
    lambda d: {**d, "release_id": "r2 spaces"},
    lambda d: {**d, "release_id": 123},
    lambda d: {**d, "components": {}},
    lambda d: {**d, "components": d["components"] + [{"name": "extra", "version": "1", "artifact_id": "x", "artifact_sha256": "a"*64, "artifact_size": 1, "installed_identity_sha256": "a"*64}]},
    lambda d: {**d, "components": [c for c in d["components"] if c["name"] != "core"]},
    lambda d: {**d, "components": [c for c in d["components"] if c["name"] != "launcher"]},
    lambda d: {**d, "components": [d["components"][0], d["components"][0]]},
    lambda d: {**d, "components": [d["components"][0], "not a dict"]},
    lambda d: {**d, "components": [{k: v for k, v in c.items() if k != "version"} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "extra_field": "x"} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "credential": "x"} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "host": "x"} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "port": "x"} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "cipher": "x"} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "version": ""} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "version": "v"*65} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "version": "v 1"} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "version": True} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_id": ""} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_id": "a"*97} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_id": "a b"} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_id": True} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_sha256": "A"*64} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_sha256": "g"*64} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_sha256": "a"*63} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_sha256": 123} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "installed_identity_sha256": "A"*64} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "installed_identity_sha256": "g"*64} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "installed_identity_sha256": "a"*63} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "installed_identity_sha256": 123} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_size": 0} if c["name"] == "launcher" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_size": -1} if c["name"] == "launcher" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_size": True} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_size": 1.0} if c["name"] == "core" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_size": 134217729} if c["name"] == "launcher" else c for c in d["components"]]},
    lambda d: {**d, "components": [{**c, "artifact_size": 1073741825} if c["name"] == "core" else c for c in d["components"]]},
])
def test_parse_release_set_rejects_non_exact_schema(mutate):
    ok, symbols = lazy_import()
    if not ok:
        pytest.fail("Module neko_launcher.application.software_update_models missing or fails to import")
    _, _, _, _, _, _, _, parse_release_set = symbols

    with pytest.raises(ValueError):
        parse_release_set(mutate(valid_release_document()))

def test_parse_release_set_positive_boundaries():
    ok, symbols = lazy_import()
    if not ok:
        pytest.fail("Module neko_launcher.application.software_update_models missing or fails to import")
    _, _, _, _, _, _, _, parse_release_set = symbols

    doc = valid_release_document()

    # accept release_sequence == 9223372036854775807 and minimum_supported_sequence == release_sequence
    doc["release_sequence"] = 9223372036854775807
    doc["minimum_supported_sequence"] = 9223372036854775807

    # accept Launcher artifact_size == 134217728 and Core == 1073741824
    for c in doc["components"]:
        if c["name"] == "launcher":
            c["artifact_size"] = 134217728
        elif c["name"] == "core":
            c["artifact_size"] = 1073741824

    # accept release_id exactly 64 chars using allowed uppercase/underscore/dot/hyphen grammar
    doc["release_id"] = "A" * 61 + "_.-"

    # accept version exactly 64 chars including plus sign
    doc["components"][0]["version"] = "a" * 63 + "+"

    # accept artifact_id exactly 96 chars
    doc["components"][0]["artifact_id"] = "b" * 96

    release = parse_release_set(doc)
    assert release.release_sequence == 9223372036854775807
    assert release.minimum_supported_sequence == 9223372036854775807
    assert release.release_id == "A" * 61 + "_.-"
    assert release.components[0].name == "launcher"
    assert release.components[0].artifact_size == 134217728
    assert release.components[1].name == "core"
    assert release.components[1].version == "a" * 63 + "+"
    assert release.components[1].artifact_id == "b" * 96
    assert release.components[1].artifact_size == 1073741824

    # assert both SHA fields are valid lowercase 64 hex in accepted payload
    for c in release.components:
        assert re.fullmatch(r"[a-f0-9]{64}", c.artifact_sha256)
        assert re.fullmatch(r"[a-f0-9]{64}", c.installed_identity_sha256)

def test_parse_release_set_reorders_components():
    ok, symbols = lazy_import()
    if not ok:
        pytest.fail("Module neko_launcher.application.software_update_models missing or fails to import")
    _, _, _, _, _, _, _, parse_release_set = symbols

    doc = valid_release_document()
    # Reverse input order (core, launcher -> core, launcher wait, valid document has core then launcher already)
    # The valid document actually has core then launcher.
    # So we'll pass it, and assert the output is launcher, core.
    assert doc["components"][0]["name"] == "core"
    assert doc["components"][1]["name"] == "launcher"

    release = parse_release_set(doc)
    assert isinstance(release.components, tuple)
    assert release.components[0].name == "launcher"
    assert release.components[1].name == "core"


def test_enum_member_sequence_and_values():
    ok, symbols = lazy_import()
    if not ok:
        pytest.fail("Module neko_launcher.application.software_update_models missing or fails to import")
    _, _, _, UpdateInvocationReason, UpdateState, UpdateDiagnosticCode, _, _ = symbols

    # assert exact ordered enum member/value sequence including aliases
    assert list(UpdateInvocationReason.__members__.items()) == [("STARTUP", UpdateInvocationReason.STARTUP), ("MANUAL", UpdateInvocationReason.MANUAL)]

    assert list(UpdateState.__members__.items()) == [
        ("NOT_CHECKED", UpdateState.NOT_CHECKED),
        ("CHECKING", UpdateState.CHECKING),
        ("LATEST", UpdateState.LATEST),
        ("AVAILABLE", UpdateState.AVAILABLE),
        ("MANDATORY", UpdateState.MANDATORY),
        ("UNAVAILABLE", UpdateState.UNAVAILABLE),
        ("VERIFY_FAILED", UpdateState.VERIFY_FAILED),
    ]

    assert list(UpdateDiagnosticCode.__members__.items()) == [
        ("DOWNGRADE_REJECTED", UpdateDiagnosticCode.DOWNGRADE_REJECTED),
        ("SAME_SEQUENCE_IDENTITY_CONFLICT", UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT)
    ]

def test_dataclasses_exact_fields():
    ok, symbols = lazy_import()
    if not ok:
        pytest.fail("Module neko_launcher.application.software_update_models missing or fails to import")
    ComponentRelease, ReleaseSet, LocalReleaseIdentity, _, _, _, UpdateCheckResult, _ = symbols

    assert [f.name for f in dataclasses.fields(ComponentRelease)] == [
        "name", "version", "artifact_id", "artifact_sha256", "artifact_size", "installed_identity_sha256"
    ]

    assert [f.name for f in dataclasses.fields(ReleaseSet)] == [
        "schema_version", "channel", "release_sequence", "release_id", "mandatory", "minimum_supported_sequence", "components"
    ]

    assert [f.name for f in dataclasses.fields(LocalReleaseIdentity)] == [
        "release_sequence", "release_id", "launcher_version", "launcher_installed_identity_sha256", "core_version", "core_installed_identity_sha256"
    ]

    assert [f.name for f in dataclasses.fields(UpdateCheckResult)] == [
        "state", "invocation_reason", "release_id", "release_sequence", "changed_components", "launcher_version", "core_version", "mandatory", "diagnostic_code"
    ]

def test_update_check_result_diagnostic_acceptance():
    ok, symbols = lazy_import()
    if not ok:
        pytest.fail("Module neko_launcher.application.software_update_models missing or fails to import")
    _, _, _, UpdateInvocationReason, UpdateState, UpdateDiagnosticCode, UpdateCheckResult, _ = symbols

    # assert UpdateCheckResult accepts diagnostic None and both enum members
    UpdateCheckResult(UpdateState.VERIFY_FAILED, UpdateInvocationReason.STARTUP, "r1", 1, ("launcher",), "1.0", "1.0", False, None)
    UpdateCheckResult(UpdateState.VERIFY_FAILED, UpdateInvocationReason.STARTUP, "r1", 1, ("launcher",), "1.0", "1.0", False, UpdateDiagnosticCode.DOWNGRADE_REJECTED)
    UpdateCheckResult(UpdateState.VERIFY_FAILED, UpdateInvocationReason.STARTUP, "r1", 1, ("launcher",), "1.0", "1.0", False, UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT)
