from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytest

from neko_launcher.application.errors import LauncherServiceError
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


@pytest.mark.integration
def test_auth_entitlement_and_single_launcher_session_end_to_end() -> None:
    url, publishable_key, username, password = required_environment()
    first = gateway(url, publishable_key)
    second = gateway(url, publishable_key)
    first_installation_hash = "a" * 64
    second_installation_hash = "b" * 64

    first_claim = None
    second_claim = None
    replacement_claim = None
    try:
        first.sign_in(username, password)
        first_claim = first.claim_session(
            "neko-family-proxy",
            first_installation_hash,
            "Integration test runner A",
        )

        second.sign_in(username, password)
        second_claim = second.claim_session(
            "neko-family-proxy",
            second_installation_hash,
            "Integration test runner B",
        )

        assert first_claim.session_id != second_claim.session_id
        assert first.heartbeat_session(first_claim.session_id) is False
        assert second.heartbeat_session(second_claim.session_id) is True

        replacement_claim = first.claim_session(
            "neko-family-proxy",
            first_installation_hash,
            "Integration test runner A",
        )
        assert replacement_claim.installation_id == first_claim.installation_id
        assert second.heartbeat_session(second_claim.session_id) is False
        assert first.heartbeat_session(replacement_claim.session_id) is True
    finally:
        if replacement_claim is not None:
            first.release_session(replacement_claim.session_id)
        elif second_claim is not None:
            second.release_session(second_claim.session_id)
        elif first_claim is not None:
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

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                first.claim_session,
                "neko-family-proxy",
                "c" * 64,
                "Concurrent runner C",
            )
            second_future = executor.submit(
                second.claim_session,
                "neko-family-proxy",
                "d" * 64,
                "Concurrent runner D",
            )
            first_claim = first_future.result()
            second_claim = second_future.result()

        heartbeat_results = (
            first.heartbeat_session(first_claim.session_id),
            second.heartbeat_session(second_claim.session_id),
        )
        assert heartbeat_results.count(True) == 1
        assert heartbeat_results.count(False) == 1
    finally:
        if "first_claim" in locals():
            first.release_session(first_claim.session_id)
        if "second_claim" in locals():
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
