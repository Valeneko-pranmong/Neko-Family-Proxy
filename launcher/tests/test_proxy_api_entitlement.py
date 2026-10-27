from __future__ import annotations

from datetime import UTC, datetime

import pytest

from neko_launcher.application.errors import HeartbeatAuthInvalid, LauncherServiceError
from neko_launcher.domain.models import EntitlementStatus, SessionTerminationReason
from neko_launcher.infrastructure.auth.proxy_api_entitlement import (
    ProxyApiEntitlementGateway,
)
from neko_launcher.infrastructure.auth.proxy_api_gateway import (
    ProxyApiError,
    ProxyHeartbeat,
    ProxyRelease,
    ProxySessionClaim,
)

SESSION_ID = "77777777-7777-4777-8777-777777777777"
INSTALLATION_ID = "22222222-2222-4222-8222-222222222222"
LICENSE_UNTIL = datetime(2026, 11, 4, tzinfo=UTC)


class FakeTokens:
    def __init__(self) -> None:
        self.token = "access-fixture"
        self.refresh_count = 0

    def access_token(self) -> str:
        if self.token is None:
            raise ProxyApiError("invalid_token")
        return self.token

    def refresh_access_token(self) -> str:
        self.refresh_count += 1
        self.token = "refreshed-access-fixture"
        return self.token


class FakeClient:
    def __init__(self) -> None:
        self.claim_error: Exception | None = None
        self.claim_errors: list[Exception] = []
        self.heartbeat_error: Exception | None = None
        self.heartbeat_errors: list[Exception] = []
        self.release_error: Exception | None = None
        self.claim_calls: list[dict[str, object]] = []
        self.heartbeat_calls: list[dict[str, object]] = []
        self.release_calls: list[dict[str, object]] = []
        self.heartbeat_interval = 30

    def claim_session(self, access_token: str, **kwargs):
        self.claim_calls.append({"token": access_token, **kwargs})
        if self.claim_errors:
            raise self.claim_errors.pop(0)
        if self.claim_error is not None:
            raise self.claim_error
        return ProxySessionClaim(
            session_id=SESSION_ID,
            installation_id=INSTALLATION_ID,
            runtime_config_version=42,
            heartbeat_interval_seconds=30,
            license_valid_until=LICENSE_UNTIL,
            server_time=datetime(2026, 10, 25, tzinfo=UTC),
        )

    def heartbeat_session(self, access_token: str, **kwargs):
        self.heartbeat_calls.append({"token": access_token, **kwargs})
        if self.heartbeat_errors:
            raise self.heartbeat_errors.pop(0)
        if self.heartbeat_error is not None:
            raise self.heartbeat_error
        return ProxyHeartbeat(
            session_id=kwargs["session_id"],
            status="active",
            next_heartbeat_seconds=self.heartbeat_interval,
            server_time=datetime(2026, 10, 25, tzinfo=UTC),
        )

    def release_session(self, access_token: str, **kwargs):
        self.release_calls.append({"token": access_token, **kwargs})
        if self.release_error is not None:
            raise self.release_error
        return ProxyRelease(session_id=kwargs["session_id"], released=True)


def _gateway(
    client: FakeClient | None = None,
    tokens: FakeTokens | None = None,
) -> tuple[ProxyApiEntitlementGateway, FakeClient, FakeTokens]:
    client = client or FakeClient()
    tokens = tokens or FakeTokens()
    return (
        ProxyApiEntitlementGateway(
            client,
            tokens,
            idempotency_key_factory=lambda: "idem-claim-fixture",
        ),
        client,
        tokens,
    )


def test_claim_maps_server_session_to_domain_claim() -> None:
    gateway, client, _ = _gateway()

    claim = gateway.claim_session(
        "neko-family-proxy",
        "a" * 64,
        "Office PC",
    )

    assert claim.session_id == SESSION_ID
    assert claim.installation_id == INSTALLATION_ID
    assert claim.runtime_config_version == 42
    assert claim.heartbeat_interval_seconds == 30
    assert claim.entitlement.status is EntitlementStatus.ACTIVE
    assert claim.entitlement.valid_until == LICENSE_UNTIL
    assert gateway.heartbeat_interval_seconds == 30
    assert client.claim_calls == [
        {
            "token": "access-fixture",
            "installation_key_hash": "a" * 64,
            "display_name": "Office PC",
            "idempotency_key": "idem-claim-fixture",
        }
    ]


def test_claim_refreshes_once_after_401() -> None:
    client = FakeClient()
    client.claim_errors = [ProxyApiError("invalid_token")]
    tokens = FakeTokens()
    keys: list[str] = []

    def next_key() -> str:
        keys.append(f"idem-claim-{len(keys) + 1}")
        return keys[-1]

    gateway = ProxyApiEntitlementGateway(
        client,
        tokens,
        idempotency_key_factory=next_key,
    )

    claim = gateway.claim_session("neko-family-proxy", "a" * 64, "Office PC")

    assert claim.session_id == SESSION_ID
    assert tokens.refresh_count == 1
    assert client.claim_calls[0]["token"] == "access-fixture"
    assert client.claim_calls[1]["token"] == "refreshed-access-fixture"
    assert len(keys) == 1
    assert (
        client.claim_calls[0]["idempotency_key"]
        == client.claim_calls[1]["idempotency_key"]
        == "idem-claim-1"
    )


def test_claim_propagates_session_conflict() -> None:
    client = FakeClient()
    client.claim_error = ProxyApiError("session_conflict")
    gateway, _, _ = _gateway(client)

    with pytest.raises(ProxyApiError) as captured:
        gateway.claim_session("neko-family-proxy", "a" * 64, "Office PC")

    assert captured.value.code == "session_conflict"
    assert "เครื่องอื่น" in str(captured.value)


def test_heartbeat_uses_next_server_interval() -> None:
    client = FakeClient()
    client.heartbeat_interval = 45
    gateway, _, _ = _gateway(client)

    assert gateway.heartbeat_session(SESSION_ID) is True
    assert gateway.heartbeat_interval_seconds == 45
    assert client.heartbeat_calls == [
        {"token": "access-fixture", "session_id": SESSION_ID}
    ]


def test_heartbeat_session_conflict_marks_replaced() -> None:
    client = FakeClient()
    client.heartbeat_error = ProxyApiError("session_conflict")
    gateway, _, _ = _gateway(client)

    assert gateway.heartbeat_session(SESSION_ID) is False
    assert gateway.session_termination_reason(SESSION_ID) is (
        SessionTerminationReason.REPLACED
    )


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("account_suspended", SessionTerminationReason.ACCOUNT_RESTRICTED),
        ("account_closed", SessionTerminationReason.ACCOUNT_RESTRICTED),
        ("license_expired", SessionTerminationReason.LICENSE_UNAVAILABLE),
        ("license_inactive", SessionTerminationReason.LICENSE_UNAVAILABLE),
    ],
)
def test_heartbeat_state_denials_mark_termination_reason(
    code: str,
    expected: SessionTerminationReason,
) -> None:
    client = FakeClient()
    client.heartbeat_error = ProxyApiError(code)
    gateway, _, _ = _gateway(client)

    assert gateway.heartbeat_session(SESSION_ID) is False
    assert gateway.session_termination_reason(SESSION_ID) is expected


def test_heartbeat_auth_failure_raises_heartbeat_auth_invalid() -> None:
    client = FakeClient()
    client.heartbeat_error = ProxyApiError("invalid_token")
    tokens = FakeTokens()
    tokens.token = None
    gateway, _, _ = _gateway(client, tokens)

    with pytest.raises(HeartbeatAuthInvalid, match="เข้าสู่ระบบใหม่"):
        gateway.heartbeat_session(SESSION_ID)


def test_heartbeat_transient_error_is_propagated() -> None:
    client = FakeClient()
    client.heartbeat_error = ProxyApiError("upstream_unavailable")
    gateway, _, _ = _gateway(client)

    with pytest.raises(ProxyApiError) as captured:
        gateway.heartbeat_session(SESSION_ID)

    assert captured.value.code == "upstream_unavailable"


def test_release_is_best_effort() -> None:
    client = FakeClient()
    gateway, _, _ = _gateway(client)

    assert gateway.release_session(SESSION_ID) is True
    client.release_error = ProxyApiError("session_conflict")
    assert gateway.release_session(SESSION_ID) is False


def test_coupon_remains_a_later_slice() -> None:
    gateway, _, _ = _gateway()

    with pytest.raises(LauncherServiceError, match="ขั้นถัดไป"):
        gateway.redeem_coupon("NEKO-fixture")
