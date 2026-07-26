from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest

from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.infrastructure.supabase_gateway import SupabaseGateway


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
        "NEKO_INTEGRATION_EMAIL",
        "NEKO_INTEGRATION_PASSWORD",
    )
    values = tuple(os.getenv(name, "").strip() for name in names)
    if not all(values):
        pytest.skip("Disposable Supabase integration credentials are not configured")
    return values  # type: ignore[return-value]


def gateway(url: str, publishable_key: str) -> SupabaseGateway:
    return SupabaseGateway(url, publishable_key, MemoryStore())


@pytest.mark.integration
def test_auth_entitlement_and_single_launcher_session_end_to_end() -> None:
    url, publishable_key, email, password = required_environment()
    first = gateway(url, publishable_key)
    second = gateway(url, publishable_key)
    installation_hash = "a" * 64

    first.sign_in(email, password)
    first_claim = first.claim_session(
        "neko-family-proxy",
        installation_hash,
        "Integration test runner",
    )

    second.sign_in(email, password)
    second_claim = second.claim_session(
        "neko-family-proxy",
        installation_hash,
        "Integration test runner",
    )

    try:
        assert first_claim.session_id != second_claim.session_id
        assert first.heartbeat_session(first_claim.session_id) is False
        assert second.heartbeat_session(second_claim.session_id) is True
    finally:
        second.release_session(second_claim.session_id)
        first.sign_out()
        second.sign_out()


@pytest.mark.integration
def test_coupon_can_be_redeemed_only_once_end_to_end() -> None:
    url, publishable_key, email, password = required_environment()
    coupon = os.getenv("NEKO_INTEGRATION_COUPON", "").strip()
    if not coupon:
        pytest.skip("A fresh disposable coupon was not supplied")

    client = gateway(url, publishable_key)
    client.sign_in(email, password)
    try:
        result = client.redeem_coupon(coupon)
        assert result.days_added > 0
        with pytest.raises(LauncherServiceError, match="ถูกใช้"):
            client.redeem_coupon(coupon)
    finally:
        client.sign_out()
