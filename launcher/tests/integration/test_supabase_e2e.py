from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

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


def collect_claim_results(
    pending: tuple[
        tuple[SupabaseGateway, Future[tuple[str, SessionClaim | None]]],
        ...,
    ],
) -> tuple[
    list[tuple[SupabaseGateway, str, SessionClaim | None]],
    list[BaseException],
]:
    observations: list[tuple[SupabaseGateway, str, SessionClaim | None]] = []
    errors: list[BaseException] = []
    for client, future in pending:
        try:
            outcome, claim = future.result()
        except BaseException as exc:  # retain every worker result before failing
            errors.append(exc)
        else:
            observations.append((client, outcome, claim))
    return observations, errors


def cleanup_gateways(
    sessions: tuple[tuple[Any, SessionClaim | Any | None], ...],
) -> None:
    release_failed = False
    try:
        for client, claim in sessions:
            if claim is None:
                continue
            try:
                released = client.release_session(claim.session_id)
            except Exception:
                release_failed = True
                continue
            if released is not True:
                release_failed = True
    finally:
        for client, _claim in sessions:
            try:
                client.sign_out()
            except Exception:
                release_failed = True
    if release_failed:
        raise AssertionError("Launcher Session cleanup failed")


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
        cleanup_gateways(((first, first_claim), (second, None)))


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
    observations: list[tuple[SupabaseGateway, str, SessionClaim | None]] = []
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
            observations, errors = collect_claim_results(
                ((first, first_future), (second, second_future))
            )

        claims_by_client = {client: claim for client, _outcome, claim in observations}
        first_claim = claims_by_client.get(first)
        second_claim = claims_by_client.get(second)
        if errors:
            raise errors[0]

        outcomes = [outcome for _client, outcome, _claim in observations]
        assert outcomes.count("SUCCESS") == 1
        assert outcomes.count("SESSION_ALREADY_ACTIVE") == 1
        winner = first_claim or second_claim
        assert winner is not None
        active = active_sessions(first)
        assert active == [
            {
                "id": winner.session_id,
                "installation_id": winner.installation_id,
                "revoked_at": None,
            }
        ]
    finally:
        cleanup_gateways(((first, first_claim), (second, second_claim)))


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
