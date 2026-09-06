import pytest

from neko_launcher.updater.precommit_abort import execute_precommit_abort
from neko_launcher.updater.state_models import (
    Binding,
    DirectoryIdentity,
    Generation,
    State,
    Transaction,
)


def test_precommit_abort_preserves_previous_and_active_session() -> None:
    gen0 = Generation(
        binding=Binding(release_sequence=1, release_id="r1", payload_sha256="1" * 64),
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )
    gen1 = Generation(
        binding=Binding(release_sequence=2, release_id="r2", payload_sha256="2" * 64),
        launcher_identity_sha256="c" * 64,
        core_identity_sha256="d" * 64,
    )
    gen2 = Generation(
        binding=Binding(release_sequence=3, release_id="r3", payload_sha256="3" * 64),
        launcher_identity_sha256="e" * 64,
        core_identity_sha256="f" * 64,
    )
    incoming_id = DirectoryIdentity(volume_serial="12345678abcdef01", file_id="1" * 32, parent_file_id="0" * 32)
    tx = Transaction(
        id="a" * 32,
        request_id="b" * 32,
        candidate=gen2,
        old=gen1,
        incoming=incoming_id,
        staging=None,
        stage="ADMITTED",
        mutation=None,
    )
    preparing_state = State(
        schema_version=1,
        revision=5,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PREPARING",
        committed=gen1,
        previous=gen0,  # Prior committed generation N
        highwater=gen1.binding,
        observed=gen2.binding,
        failed=None,
        transaction=tx,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )

    aborted = execute_precommit_abort(preparing_state, "DOWNLOAD_FAILED")
    assert aborted.phase == "CLEANING"
    assert aborted.revision == 6
    assert aborted.committed == gen1
    assert aborted.previous == gen0  # MUST be preserved!
    assert aborted.highwater == gen1.binding
    assert aborted.observed == gen2.binding
    assert aborted.failed == gen2.binding
    assert aborted.transaction is None
    assert aborted.last_error == "DOWNLOAD_FAILED"
    assert aborted.cleanup is not None
    assert len(aborted.cleanup) == 1
    assert aborted.cleanup[0].target == "incoming"


def test_precommit_abort_rejects_non_preparing_phase() -> None:
    gen1 = Generation(
        binding=Binding(release_sequence=1, release_id="r1", payload_sha256="1" * 64),
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )
    idle_state = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen1,
        previous=None,
        highwater=gen1.binding,
        observed=gen1.binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    with pytest.raises(ValueError, match="Precommit abort only valid from PREPARING phase"):
        execute_precommit_abort(idle_state, "USER_CANCELLED")
