from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytest

from neko_launcher.application.errors import LauncherServiceError, SessionAlreadyActive
from neko_launcher.domain.models import SessionClaim
from neko_launcher.infrastructure.auth.supabase_gateway import SupabaseGateway


@dataclass
class MemoryStore:
    values: dict[str, str] = field(default_factory=dict)

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def required_environment() -> tuple[str, str, str, str]:
    names = (
        "NEKO_INTEGRATION_SUPABASE_URL",
        "NEKO_INTEGRATION_SUPABASE_PUBLISHABLE_KEY",
        "NEKO_INTEGRATION_USERNAME",
        "NEKO_INTEGRATION_PASSWORD",
    )
    values = tuple(os.getenv(name, "").strip() for name in names)
    if not all(values):
        pytest.skip("Disposable Supabase integration credentials are not configured")
    return values  # type: ignore[return-value]


def gateway(url: str, publishable_key: str) -> SupabaseGateway:
    return SupabaseGateway(url, publishable_key, MemoryStore())


def active_sessions(client: SupabaseGateway) -> list[dict[str, object]]:
    response = (
        client._client.schema("public")  # noqa: SLF001 - live contract assertion
        .table("launcher_sessions")
        .select("id,installation_id,revoked_at")
        .is_("revoked_at", "null")
        .execute()
    )
    return list(response.data or [])


@pytest.mark.integration
def test_fresh_active_session_blocks_later_claim_end_to_end() -> None:
    url, publishable_key, username, password = required_environment()
    first = gateway(url, publishable_key)
    second = gateway(url, publishable_key)
    first_installation_hash = "a" * 64
    second_installation_hash = "b" * 64

    first_claim = None
    try:
        first.sign_in(username, password)
        first_claim = first.claim_session(
            "neko-family-proxy",
            first_installation_hash,
            "Integration test runner A",
        )
        assert active_sessions(first) == [
            {
                "id": first_claim.session_id,
                "installation_id": first_claim.installation_id,
                "revoked_at": None,
            }
        ]

        second.sign_in(username, password)
        for _attempt in range(3):
            with pytest.raises(SessionAlreadyActive, match="SESSION_ALREADY_ACTIVE"):
                second.claim_session(
                    "neko-family-proxy",
                    second_installation_hash,
                    "Integration test runner B",
                )

        assert first.heartbeat_session(first_claim.session_id) is True
        assert active_sessions(first) == [
            {
                "id": first_claim.session_id,
                "installation_id": first_claim.installation_id,
                "revoked_at": None,
            }
        ]
    finally:
        if first_claim is not None:
            first.release_session(first_claim.session_id)
        first.sign_out()
        second.sign_out()


@pytest.mark.integration
def test_concurrent_claims_leave_exactly_one_live_session() -> None:
    url, publishable_key, username, password = required_environment()
    first = gateway(url, publishable_key)
    second = gateway(url, publishable_key)
    first.sign_in(username, password)
    second.sign_in(username, password)

    def claim_or_active(
        gateway: SupabaseGateway,
        installation_hash: str,
    ) -> tuple[str, SessionClaim | None]:
        try:
            claim = gateway.claim_session(
                "neko-family-proxy",
                installation_hash,
                "Concurrent Lite runner",
            )
        except SessionAlreadyActive:
            return "SESSION_ALREADY_ACTIVE", None
        return "SUCCESS", claim

    first_claim = None
    second_claim = None
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                claim_or_active,
                first,
                "c" * 64,
            )
            second_future = executor.submit(
                claim_or_active,
                second,
                "d" * 64,
            )
            first_outcome, first_claim = first_future.result()
            second_outcome, second_claim = second_future.result()

        outcomes = [first_outcome, second_outcome]
        assert outcomes.count("SUCCESS") == 1
        assert outcomes.count("SESSION_ALREADY_ACTIVE") == 1
        assert len(active_sessions(first)) == 1
    finally:
        if first_claim is not None:
            first.release_session(first_claim.session_id)
        if second_claim is not None:
            second.release_session(second_claim.session_id)
        first.sign_out()
        second.sign_out()


@pytest.mark.integration
def test_coupon_can_be_redeemed_only_once_end_to_end() -> None:
    url, publishable_key, username, password = required_environment()
    coupon = os.getenv("NEKO_INTEGRATION_COUPON", "").strip()
    if not coupon:
        pytest.skip("A fresh disposable coupon was not supplied")

    client = gateway(url, publishable_key)
    client.sign_in(username, password)
    try:
        result = client.redeem_coupon(coupon)
        assert result.days_added > 0
        with pytest.raises(LauncherServiceError, match="ถูกใช้"):
            client.redeem_coupon(coupon)
    finally:
        client.sign_out()
