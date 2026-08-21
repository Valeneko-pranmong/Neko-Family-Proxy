from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    PermitDiagnosticCode,
)
from neko_launcher.e2e.distinct_auth_session_future_permit import (
    DistinctAuthSessionFuturePermitProofHarness,
    ProofFailure,
    _session_id_from_access_token,
    default_preparation_manifest,
    main,
)


def _token_for(session_id: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"session_id": session_id}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"header.{payload}.signature"


@dataclass
class FakeState:
    active: FakeGateway | None = None
    device_revokes: int = 0
    claim_history: list[str] | None = None
    heartbeat_history: list[tuple[str, str, bool]] | None = None

    def __post_init__(self) -> None:
        self.claim_history = []
        self.heartbeat_history = []


class FakeGateway:
    def __init__(
        self, label: str, session_id: str, user_id: str, state: FakeState
    ) -> None:
        self.label = label
        self._state = state
        self._session_id = session_id
        self._user_id = user_id
        self._signed_in = False
        self._claim_number = 0
        self._launcher_session_id = ""
        self._client = SimpleNamespace(
            proof_gateway=self,
            auth=SimpleNamespace(get_session=self._get_session),
        )
        self.clear_calls = 0

    def _get_session(self) -> object | None:
        if not self._signed_in:
            return None
        return SimpleNamespace(access_token=_token_for(self._session_id))

    def sign_in(self, _username: str, _password: str) -> object:
        self._signed_in = True
        return SimpleNamespace(user_id=self._user_id)

    def claim_session(
        self, _product: str, _installation_key_hash: str, _display_name: str
    ) -> object:
        assert self._signed_in
        self._claim_number += 1
        self._launcher_session_id = f"launcher-{self.label}-{self._claim_number}"
        self._state.active = self
        assert self._state.claim_history is not None
        self._state.claim_history.append(self.label)
        return SimpleNamespace(
            session_id=self._launcher_session_id,
            installation_id=f"installation-{self.label}",
        )

    def heartbeat_session(self, session_id: str) -> bool:
        accepted = self._state.active is self and session_id == self._launcher_session_id
        assert self._state.heartbeat_history is not None
        self._state.heartbeat_history.append((self.label, session_id, accepted))
        return accepted

    def release_session(self, session_id: str) -> bool:
        if self._state.active is not self or session_id != self._launcher_session_id:
            return False
        self._state.active = None
        return True

    def clear_local_session(self) -> None:
        self.clear_calls += 1


class FakePermitRequester:
    def __init__(self, state: FakeState, *, diagnostic: PermitDiagnosticCode) -> None:
        self._state = state
        self._diagnostic = diagnostic
        self.calls: list[str] = []
        self.lite_invocations: list[tuple[str, object, float]] = []

    def issue_launch_permit(
        self,
        authenticated_transport: object,
        correlation_id: str,
        challenge: object,
        timeout: float,
    ) -> object:
        gateway = getattr(authenticated_transport, "proof_gateway", None)
        assert isinstance(gateway, FakeGateway)
        self.calls.append(gateway.label)
        self.lite_invocations.append((correlation_id, challenge, timeout))
        if self._state.active is gateway:
            return object()
        raise AuthorizedCoreError(
            AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE,
            diagnostic_code=self._diagnostic,
            diagnostic_context={
                "function": "issue_launch_permit",
                "stage": "PERMIT_REQUEST",
                "http_status": 403,
            },
        )


def _harness(
    *,
    session_ids: tuple[str, str, str] = (
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
        "00000000-0000-4000-8000-000000000003",
    ),
    user_ids: tuple[str, str, str] = ("same-user", "same-user", "same-user"),
    pso2_running: bool | None = False,
    diagnostic: PermitDiagnosticCode = PermitDiagnosticCode.BACKEND_EDGE_SESSION_INACTIVE,
) -> tuple[
    DistinctAuthSessionFuturePermitProofHarness,
    list[FakeGateway],
    FakePermitRequester,
    FakeState,
]:
    state = FakeState()
    gateways = [
        FakeGateway(label, session_id, user_id, state)
        for label, session_id, user_id in zip(
            ("A", "B", "C"), session_ids, user_ids, strict=True
        )
    ]
    gateway_iterator = iter(gateways)
    requester = FakePermitRequester(state, diagnostic=diagnostic)

    def active_session_count(_gateway: object) -> int:
        return 0 if state.active is None else 1

    def installation_state(_gateway: object, installation_ids: tuple[str, ...]) -> tuple[int, int]:
        assert installation_ids == ("installation-A", "installation-B", "installation-C")
        return 3, state.device_revokes

    harness = DistinctAuthSessionFuturePermitProofHarness(
        gateway_factory=lambda: next(gateway_iterator),  # type: ignore[arg-type]
        permit_requester=requester,
        pso2_running=lambda: pso2_running,
        active_session_count=active_session_count,  # type: ignore[arg-type]
        installation_state=installation_state,  # type: ignore[arg-type]
    )
    return harness, gateways, requester, state


def test_run_proves_three_distinct_auth_sessions_and_edge_denials_without_core() -> None:
    harness, remaining_gateways, requester, state = _harness()

    result = harness.run("operator-input", "operator-input")

    assert result.evidence() == {
        "phase": "DISTINCT_AUTH_SESSION_FUTURE_PERMIT_PROOF",
        "auth_session_ids_pairwise_distinct": True,
        "backend_edge_session_inactive_denials": 3,
        "final_authority": "A",
        "remembered_installations": 3,
        "permanent_device_revokes": 0,
        "active_launcher_sessions_after_cleanup": 0,
        "successful_permits": 0,
        "permit_retries": 0,
        "core_starts": 0,
        "core_challenges": 0,
    }
    assert requester.calls == ["A", "B", "C"]
    assert state.claim_history == ["A", "B", "C", "A"]
    assert state.heartbeat_history == [
        ("A", "launcher-A-1", True),
        ("A", "launcher-A-1", False),
        ("B", "launcher-B-1", False),
        ("C", "launcher-C-1", False),
        ("A", "launcher-A-2", True),
    ]
    assert len(requester.lite_invocations) == 3
    for correlation_id, challenge, timeout in requester.lite_invocations:
        assert len(correlation_id) == 32
        assert getattr(challenge, "value", None) is not None
        assert timeout == 10.0
    assert [gateway.clear_calls for gateway in remaining_gateways] == [1, 1, 1]


def test_obsolete_s0_ten_argument_permit_invocation_is_rejected() -> None:
    state = FakeState()
    requester = FakePermitRequester(
        state,
        diagnostic=PermitDiagnosticCode.BACKEND_EDGE_SESSION_INACTIVE,
    )

    with pytest.raises(TypeError):
        requester.issue_launch_permit(  # type: ignore[call-arg]
            object(),
            "0123456789abcdef0123456789abcdef",
            object(),
            "configuration-digest",
            "pso2.exe",
            4242,
            "ProcessMode",
            "neko-family-proxy",
            "proxy:start",
            10.0,
        )


def test_duplicate_auth_session_id_is_rejected_before_c_can_claim() -> None:
    harness, _remaining_gateways, requester, _state = _harness(
        session_ids=(
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
            "00000000-0000-4000-8000-000000000001",
        )
    )

    with pytest.raises(ProofFailure, match="AUTH_SESSION_IDS_NOT_DISTINCT"):
        harness.run("operator-input", "operator-input")

    assert requester.calls == ["A"]


def test_different_authenticated_users_are_not_accepted_for_the_proof() -> None:
    harness, _remaining_gateways, requester, _state = _harness(
        user_ids=("same-user", "different-user", "same-user")
    )

    with pytest.raises(ProofFailure, match="AUTH_CONTEXT_USER_MISMATCH"):
        harness.run("operator-input", "operator-input")

    assert requester.calls == ["A"]


def test_local_precondition_denial_is_not_accepted_as_edge_proof() -> None:
    harness, _remaining_gateways, requester, _state = _harness(
        diagnostic=PermitDiagnosticCode.PERMIT_AUTH_SESSION_UNAVAILABLE
    )

    with pytest.raises(ProofFailure, match="BACKEND_EDGE_SESSION_INACTIVE_REQUIRED"):
        harness.run("operator-input", "operator-input")

    assert requester.calls == ["A"]


@pytest.mark.parametrize("pso2_running", [True, None])
def test_manual_auth_is_fail_closed_until_pso2_is_confirmed_closed(
    pso2_running: bool | None,
) -> None:
    harness, _remaining_gateways, requester, _state = _harness(pso2_running=pso2_running)

    with pytest.raises(ProofFailure, match="PSO2_CLOSED_REQUIRED"):
        harness.run("operator-input", "operator-input")

    assert requester.calls == []


def test_session_id_decoder_keeps_the_value_in_memory_only() -> None:
    session_id = "00000000-0000-4000-8000-000000000001"

    observed = _session_id_from_access_token(_token_for(session_id))

    assert UUID(observed) == UUID(session_id)
    with pytest.raises(ProofFailure, match="AUTH_SESSION_ID_UNAVAILABLE"):
        _session_id_from_access_token("not-a-jwt")


def test_preparation_cli_is_offline_and_writes_only_safe_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_live_action(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("preparation attempted a live action")

    monkeypatch.setattr("socket.create_connection", forbidden_live_action)
    monkeypatch.setattr("subprocess.Popen", forbidden_live_action)
    output = tmp_path / "distinct-auth-proof-preparation.json"

    assert main(["prepare", "--output", str(output)]) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence == default_preparation_manifest()
    rendered = output.read_text(encoding="utf-8").lower()
    assert "access_token" not in rendered
    assert "refresh_token" not in rendered
    assert "00000000-0000-4000-8000-000000000001" not in rendered
