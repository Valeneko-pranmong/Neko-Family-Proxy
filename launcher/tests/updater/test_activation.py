import dataclasses
from pathlib import Path

import pytest

from neko_launcher.updater.probation_runner import SelfTestResult
from neko_launcher.updater.slot_selector import SelectionResult, SelectionStatus
from neko_launcher.updater.state_models import (
    Binding,
    DirectoryIdentity,
    Generation,
    State,
    Transaction,
)


class FakeSlotStore:
    def __init__(self, initial_state: State, reject_write_at_call: int = -1):
        self._state = initial_state
        self._write_count = 0
        self.reject_write_at_call = reject_write_at_call
        self.writes = []

    def load(self) -> SelectionResult:
        return SelectionResult(
            status=SelectionStatus.SELECTED,
            state=self._state,
            active_slot="a"
        )

    def write_state(self, state: State) -> SelectionResult:
        self._write_count += 1
        self.writes.append(state)
        if self._write_count == self.reject_write_at_call:
            return SelectionResult(status=SelectionStatus.REPAIR_REQUIRED)
        self._state = state
        return SelectionResult(
            status=SelectionStatus.SELECTED,
            state=state,
            active_slot="a"
        )


@pytest.fixture
def base_state():
    old_binding = Binding(
        release_sequence=1,
        release_id="rel-1",
        payload_sha256="0" * 64,
    )
    old_gen = Generation(
        binding=old_binding,
        launcher_identity_sha256="1" * 64,
        core_identity_sha256="2" * 64,
    )

    cand_binding = Binding(
        release_sequence=2,
        release_id="rel-2",
        payload_sha256="3" * 64,
    )
    cand_gen = Generation(
        binding=cand_binding,
        launcher_identity_sha256="4" * 64,
        core_identity_sha256="5" * 64,
    )

    incoming = DirectoryIdentity(
        volume_serial="a" * 16,
        file_id="b" * 32,
        parent_file_id="c" * 32,
    )
    staging = DirectoryIdentity(
        volume_serial="d" * 16,
        file_id="e" * 32,
        parent_file_id="f" * 32,
    )

    tx = Transaction(
        id="7" * 32,
        request_id="8" * 32,
        candidate=cand_gen,
        old=old_gen,
        incoming=incoming,
        staging=staging,
        stage="VERIFIED",
        mutation=None,
    )

    return State(
        schema_version=1,
        revision=1,
        installation_id="9" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PREPARING",
        committed=old_gen,
        previous=None,
        highwater=old_binding,
        observed=cand_binding,
        failed=None,
        transaction=tx,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={}
    )


def test_activation_rejects_invalid_state(base_state):
    from neko_launcher.updater import activation

    # wrong stage -> PROTOCOL_INVALID
    tx = dataclasses.replace(base_state.transaction, stage="ADMITTED")
    state = dataclasses.replace(base_state, transaction=tx)
    store = FakeSlotStore(state)
    result = activation.activate_verified_generation(Path("/root"), store)
    assert result.committed is False
    assert result.error == "PROTOCOL_INVALID"

    # wrong phase -> PROTOCOL_INVALID
    state2 = dataclasses.replace(base_state, phase="IDLE")
    store2 = FakeSlotStore(state2)
    result2 = activation.activate_verified_generation(Path("/root"), store2)
    assert result2.committed is False
    assert result2.error == "PROTOCOL_INVALID"

    # non-selected -> STATE_CORRUPT
    store3 = FakeSlotStore(base_state)
    def failing_load():
        return SelectionResult(status=SelectionStatus.REPAIR_REQUIRED)
    store3.load = failing_load
    result3 = activation.activate_verified_generation(Path("/root"), store3)
    assert result3.committed is False
    assert result3.error == "STATE_CORRUPT"


def test_activation_self_test_fail(base_state):
    from neko_launcher.updater import activation
    store = FakeSlotStore(base_state)

    def failing_self_test(gen_dir: Path, **kwargs) -> SelfTestResult:
        assert gen_dir == Path(f"/root/releases/g-{base_state.transaction.candidate.binding.release_sequence:020d}-{base_state.transaction.candidate.binding.payload_sha256}")
        return SelfTestResult(passed=False, error_code="SELFTEST_FAILED", reason="boom")

    result = activation.activate_verified_generation(Path("/root"), store, self_test=failing_self_test)

    assert result.committed is False
    assert result.error == "SELFTEST_FAILED"

    final_state = store.writes[-1] if store.writes else store._state
    assert final_state.phase == "CLEANING"
    assert final_state.committed == base_state.committed
    assert final_state.highwater == base_state.highwater
    assert final_state.failed == base_state.transaction.candidate.binding
    assert final_state.transaction is None
    assert final_state.cleanup is not None
    assert len(final_state.cleanup) == 2


def test_activation_pass_commit(base_state):
    from neko_launcher.updater import activation
    store = FakeSlotStore(base_state)

    def passing_self_test(gen_dir: Path, **kwargs) -> SelfTestResult:
        assert store._write_count == 0
        return SelfTestResult(passed=True)

    result = activation.activate_verified_generation(Path("/root"), store, self_test=passing_self_test)

    assert result.committed is True
    assert result.error is None
    assert result.generation == base_state.transaction.candidate

    assert len(store.writes) == 3
    assert store.writes[0].phase == "QUIESCING"
    assert store.writes[1].phase == "PROBATION"
    assert store.writes[2].phase == "CLEANING"

    final_state = store.writes[-1]
    assert final_state.committed == base_state.transaction.candidate
    assert final_state.previous == base_state.committed
    assert final_state.highwater == base_state.transaction.candidate.binding
    assert final_state.observed == base_state.transaction.candidate.binding
    assert final_state.failed is None
    assert final_state.transaction is None
    assert final_state.rollback is None
    assert final_state.last_error is None
    assert final_state.cleanup is not None
    assert len(final_state.cleanup) == 2


def test_activation_fail_quiescing_write(base_state):
    from neko_launcher.updater import activation
    store = FakeSlotStore(base_state, reject_write_at_call=1)

    def passing_self_test(gen_dir: Path, **kwargs) -> SelfTestResult:
        return SelfTestResult(passed=True)

    result = activation.activate_verified_generation(Path("/root"), store, self_test=passing_self_test)

    assert result.committed is False
    assert result.error == "STATE_CORRUPT"
    assert store._state.phase == "PREPARING"
    assert store._state.committed == base_state.committed


def test_activation_fail_cleaning_commit_write(base_state):
    from neko_launcher.updater import activation
    store = FakeSlotStore(base_state, reject_write_at_call=3)

    def passing_self_test(gen_dir: Path, **kwargs) -> SelfTestResult:
        return SelfTestResult(passed=True)

    result = activation.activate_verified_generation(Path("/root"), store, self_test=passing_self_test)

    assert result.committed is False
    assert result.error == "STATE_CORRUPT"
    assert store._state.phase == "PROBATION"
    assert store._state.committed == base_state.committed
