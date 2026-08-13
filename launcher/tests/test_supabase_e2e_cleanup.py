from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).parent / "integration" / "test_supabase_e2e.py"
SPEC = importlib.util.spec_from_file_location("test_supabase_e2e_live", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeGateway:
    def __init__(
        self,
        release_result: bool = True,
        release_error: Exception | None = None,
    ) -> None:
        self.release_result = release_result
        self.release_error = release_error
        self.release_calls: list[str] = []
        self.sign_out_calls = 0

    def release_session(self, session_id: str) -> bool:
        self.release_calls.append(session_id)
        if self.release_error is not None:
            raise self.release_error
        return self.release_result

    def sign_out(self) -> None:
        self.sign_out_calls += 1


class FakeFuture:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result_value = result
        self.error = error
        self.result_calls = 0

    def result(self) -> object:
        self.result_calls += 1
        if self.error is not None:
            raise self.error
        return self.result_value


def test_collect_claim_results_consumes_every_future_before_propagating_error() -> None:
    first = FakeFuture(error=RuntimeError("first failed"))
    second = FakeFuture(result=("SUCCESS", SimpleNamespace(session_id="winner")))

    observations, errors = MODULE.collect_claim_results(
        ((FakeGateway(), first), (FakeGateway(), second))
    )

    assert first.result_calls == 1
    assert second.result_calls == 1
    assert len(observations) == 1
    assert observations[0][1:] == (
        "SUCCESS",
        SimpleNamespace(session_id="winner"),
    )
    assert len(errors) == 1
    assert str(errors[0]) == "first failed"


def test_cleanup_attempts_every_release_and_sign_out_before_failing() -> None:
    first = FakeGateway(release_result=False)
    second = FakeGateway(release_result=True)

    with pytest.raises(AssertionError, match="Launcher Session cleanup failed"):
        MODULE.cleanup_gateways(
            (
                (first, SimpleNamespace(session_id="first-session")),
                (second, SimpleNamespace(session_id="second-session")),
            )
        )

    assert first.release_calls == ["first-session"]
    assert second.release_calls == ["second-session"]
    assert first.sign_out_calls == 1
    assert second.sign_out_calls == 1


def test_cleanup_continues_after_release_exception() -> None:
    first = FakeGateway(release_error=RuntimeError("release failed"))
    second = FakeGateway(release_result=True)

    with pytest.raises(AssertionError, match="Launcher Session cleanup failed"):
        MODULE.cleanup_gateways(
            (
                (first, SimpleNamespace(session_id="first-session")),
                (second, SimpleNamespace(session_id="second-session")),
            )
        )

    assert first.release_calls == ["first-session"]
    assert second.release_calls == ["second-session"]
    assert first.sign_out_calls == 1
    assert second.sign_out_calls == 1
