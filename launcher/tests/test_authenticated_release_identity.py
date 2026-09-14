from __future__ import annotations

from pathlib import Path

import pytest

from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
    DevelopmentReleaseIdentity,
    LocalReleaseIdentity,
)
from neko_launcher.infrastructure.software_release_identity import (
    load_development_release_identity,
)

H_1 = "1" * 64
H_2 = "2" * 64
H_3 = "3" * 64
H_4 = "4" * 64
H_5 = "5" * 64
H_6 = "6" * 64


def test_local_identity_keeps_full_committed_and_high_water_bindings() -> None:
    committed = AuthenticatedReleaseBinding(8, "stable-0008", H_1)
    high_water = AuthenticatedReleaseBinding(9, "stable-0009", H_2)
    failed = high_water
    local = LocalReleaseIdentity(
        committed=committed,
        high_water=high_water,
        observed=high_water,
        failed=failed,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256=H_3,
        updater_version="5.1.2",
        updater_installed_identity_sha256=H_4,
        core_version="5.1.2",
        core_installed_identity_sha256=H_5,
    )
    assert local.release_sequence == 8
    assert local.release_id == "stable-0008"
    assert local.high_water.release_sequence == 9
    assert local.high_water.release_id == "stable-0009"
    assert local.high_water.payload_sha256 == H_2
    assert local.failed == high_water
    assert isinstance(local.high_water, AuthenticatedReleaseBinding)
    assert isinstance(local.committed, AuthenticatedReleaseBinding)
    assert isinstance(local.observed, AuthenticatedReleaseBinding)


@pytest.mark.parametrize(
    "invalid_sequence",
    [0, -1, -100],
)
def test_authenticated_release_binding_rejects_non_positive_sequence(
    invalid_sequence: int,
) -> None:
    with pytest.raises(ValueError, match="release_sequence must be positive"):
        AuthenticatedReleaseBinding(invalid_sequence, "release-1", H_1)


def test_authenticated_release_binding_rejects_bool_sequence() -> None:
    with pytest.raises(ValueError, match="release_sequence must be an int"):
        AuthenticatedReleaseBinding(True, "release-1", H_1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "invalid_hash",
    [
        "1" * 63,
        "1" * 65,
        "G" * 64,
        "A" * 64,  # uppercase
        "not-a-hash",
        "",
    ],
)
def test_authenticated_release_binding_rejects_invalid_payload_sha(
    invalid_hash: str,
) -> None:
    with pytest.raises(ValueError, match="payload_sha256 must be lowercase 64-hex"):
        AuthenticatedReleaseBinding(1, "release-1", invalid_hash)


@pytest.mark.parametrize(
    "invalid_id",
    ["", "   "],
)
def test_authenticated_release_binding_rejects_invalid_release_id(
    invalid_id: str,
) -> None:
    with pytest.raises(ValueError, match="release_id must be a non-empty string"):
        AuthenticatedReleaseBinding(1, invalid_id, H_1)


def test_local_identity_requires_committed_sequence_le_high_water() -> None:
    committed = AuthenticatedReleaseBinding(10, "rel-10", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    with pytest.raises(
        ValueError,
        match="committed release_sequence cannot exceed high_water release_sequence",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=high_water,
            failed=None,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_3,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_4,
            core_version="5.1.2",
            core_installed_identity_sha256=H_5,
        )


def test_local_identity_requires_observed_equals_high_water() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    mismatched_observed = AuthenticatedReleaseBinding(10, "rel-10", H_3)
    with pytest.raises(
        ValueError,
        match="observed binding must equal high_water binding",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=mismatched_observed,
            failed=None,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_3,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_4,
            core_version="5.1.2",
            core_installed_identity_sha256=H_5,
        )


def test_local_identity_requires_failed_sequence_le_high_water() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    excess_failed = AuthenticatedReleaseBinding(10, "rel-10", H_3)
    with pytest.raises(
        ValueError,
        match="failed release_sequence cannot exceed high_water release_sequence",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=high_water,
            failed=excess_failed,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_3,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_4,
            core_version="5.1.2",
            core_installed_identity_sha256=H_5,
        )


def test_pairwise_conflict_committed_and_high_water_same_sequence_different_binding() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8-a", H_1)
    high_water = AuthenticatedReleaseBinding(8, "rel-8-b", H_2)
    with pytest.raises(
        ValueError,
        match="Pairwise binding conflict: same sequence with different binding",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=high_water,
            failed=None,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_3,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_4,
            core_version="5.1.2",
            core_installed_identity_sha256=H_5,
        )


def test_pairwise_conflict_high_water_and_failed_same_sequence_different_binding() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9-a", H_2)
    failed = AuthenticatedReleaseBinding(9, "rel-9-b", H_3)
    with pytest.raises(
        ValueError,
        match="Pairwise binding conflict: same sequence with different binding",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=high_water,
            failed=failed,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_4,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_5,
            core_version="5.1.2",
            core_installed_identity_sha256=H_6,
        )


def test_pairwise_conflict_committed_and_failed_same_sequence_different_binding() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8-a", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    failed = AuthenticatedReleaseBinding(8, "rel-8-b", H_3)
    with pytest.raises(
        ValueError,
        match="Pairwise binding conflict: same sequence with different binding",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=high_water,
            failed=failed,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_4,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_5,
            core_version="5.1.2",
            core_installed_identity_sha256=H_6,
        )


def test_valid_pairwise_same_sequence_matches_exactly() -> None:
    binding_8 = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    local = LocalReleaseIdentity(
        committed=binding_8,
        high_water=binding_8,
        observed=binding_8,
        failed=None,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256=H_2,
        updater_version="5.1.2",
        updater_installed_identity_sha256=H_3,
        core_version="5.1.2",
        core_installed_identity_sha256=H_4,
    )
    assert local.release_sequence == 8
    assert local.high_water == binding_8


def test_valid_enrolled_state_resumable_incomplete_authority() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    local = LocalReleaseIdentity(
        committed=committed,
        high_water=high_water,
        observed=high_water,
        failed=None,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256=H_3,
        updater_version="5.1.2",
        updater_installed_identity_sha256=H_4,
        core_version="5.1.2",
        core_installed_identity_sha256=H_5,
    )
    assert local.committed != local.high_water
    assert local.failed is None


def test_valid_enrolled_state_failed_matching_committed() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    local = LocalReleaseIdentity(
        committed=committed,
        high_water=high_water,
        observed=high_water,
        failed=committed,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256=H_3,
        updater_version="5.1.2",
        updater_installed_identity_sha256=H_4,
        core_version="5.1.2",
        core_installed_identity_sha256=H_5,
    )
    assert local.failed == committed


@pytest.mark.parametrize(
    "field_name,invalid_hash",
    [
        ("launcher_installed_identity_sha256", "not-hex" * 8),
        ("launcher_installed_identity_sha256", "A" * 64),
        ("updater_installed_identity_sha256", "B" * 64),
        ("updater_installed_identity_sha256", "1" * 63),
        ("core_installed_identity_sha256", "C" * 64),
        ("core_installed_identity_sha256", "1" * 65),
    ],
)
def test_local_identity_rejects_invalid_installed_identity_hashes(
    field_name: str,
    invalid_hash: str,
) -> None:
    binding = AuthenticatedReleaseBinding(1, "rel-1", H_1)
    kwargs = {
        "committed": binding,
        "high_water": binding,
        "observed": binding,
        "failed": None,
        "launcher_version": "5.1.2",
        "launcher_installed_identity_sha256": H_2,
        "updater_version": "5.1.2",
        "updater_installed_identity_sha256": H_3,
        "core_version": "5.1.2",
        "core_installed_identity_sha256": H_4,
    }
    kwargs[field_name] = invalid_hash
    with pytest.raises(ValueError, match="must be lowercase 64-hex"):
        LocalReleaseIdentity(**kwargs)  # type: ignore[arg-type]


def test_development_release_identity_contract() -> None:
    dev = DevelopmentReleaseIdentity(
        release_sequence=0,
        release_id="dev-unpublished",
        launcher_version="5.1.0-dev",
        launcher_installed_identity_sha256=H_1,
        core_version="1.0.0-dev",
        core_installed_identity_sha256=H_2,
    )
    assert dev.release_sequence == 0
    assert dev.release_id == "dev-unpublished"
    assert dev.launcher_version == "5.1.0-dev"
    assert dev.core_version == "1.0.0-dev"
    assert dev.launcher_installed_identity_sha256 == H_1
    assert dev.core_installed_identity_sha256 == H_2


def test_development_release_identity_rejects_nonzero_sequence() -> None:
    with pytest.raises(ValueError, match="release_sequence must be 0"):
        DevelopmentReleaseIdentity(
            release_sequence=1,  # type: ignore[arg-type]
            release_id="dev-unpublished",
            launcher_version="5.1.0-dev",
            launcher_installed_identity_sha256=H_1,
            core_version="1.0.0-dev",
            core_installed_identity_sha256=H_2,
        )


def test_development_release_identity_rejects_wrong_release_id() -> None:
    with pytest.raises(ValueError, match="release_id must be 'dev-unpublished'"):
        DevelopmentReleaseIdentity(
            release_sequence=0,
            release_id="prod-1",  # type: ignore[arg-type]
            launcher_version="5.1.0-dev",
            launcher_installed_identity_sha256=H_1,
            core_version="1.0.0-dev",
            core_installed_identity_sha256=H_2,
        )


def test_development_release_identity_rejects_invalid_hash() -> None:
    with pytest.raises(ValueError, match="must be lowercase 64-hex"):
        DevelopmentReleaseIdentity(
            release_sequence=0,
            release_id="dev-unpublished",
            launcher_version="5.1.0-dev",
            launcher_installed_identity_sha256="A" * 64,
            core_version="1.0.0-dev",
            core_installed_identity_sha256=H_2,
        )


def test_load_development_release_identity_returns_development_type(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "launcher.exe"
    core = tmp_path / "core-manifest.json"
    launcher.write_bytes(b"launcher")
    core.write_bytes(b"core")

    result = load_development_release_identity(
        launcher_version="5.1.0-dev",
        launcher_executable=launcher,
        core_version="1.0.0-dev",
        core_manifest=core,
    )
    assert isinstance(result, DevelopmentReleaseIdentity)
    assert not isinstance(result, LocalReleaseIdentity)
    assert result.release_sequence == 0
    assert result.release_id == "dev-unpublished"
