from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from neko_launcher.application.errors import HeartbeatAuthInvalid, LauncherServiceError
from neko_launcher.domain.models import (
    CouponRedemption,
    Entitlement,
    EntitlementStatus,
    SessionClaim,
    SessionTerminationReason,
)

from .proxy_api_gateway import ProxyApiError, ProxyApiGateway
from .proxy_api_session import ProxyApiAccessTokenProvider, call_with_access_token

PENDING_COUPON_MESSAGE = "การเติมคูปองผ่าน Proxy API จะเปิดใช้งานในขั้นถัดไป"
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30

_AUTH_INVALID_CODES = frozenset({"invalid_token", "token_expired", "invalid_grant"})


class ProxyApiEntitlementGateway:
    """Claim/heartbeat/release gateway for the source-only Proxy API line."""

    def __init__(
        self,
        client: ProxyApiGateway,
        tokens: ProxyApiAccessTokenProvider,
        *,
        idempotency_key_factory: Callable[[], str] | None = None,
    ) -> None:
        self._client = client
        self._tokens = tokens
        self._idempotency_key_factory = (
            idempotency_key_factory or (lambda: uuid4().hex)
        )
        self._heartbeat_interval_seconds = DEFAULT_HEARTBEAT_INTERVAL_SECONDS
        self._termination_reason = SessionTerminationReason.REVOKED

    @property
    def heartbeat_interval_seconds(self) -> int:
        return self._heartbeat_interval_seconds

    def claim_session(
        self,
        product_code: str,
        installation_key_hash: str,
        display_name: str,
    ) -> SessionClaim:
        idempotency_key = self._idempotency_key_factory()
        response = call_with_access_token(
            self._tokens,
            lambda token: self._client.claim_session(
                token,
                installation_key_hash=installation_key_hash,
                display_name=display_name,
                idempotency_key=idempotency_key,
            ),
        )
        self._heartbeat_interval_seconds = response.heartbeat_interval_seconds
        self._termination_reason = SessionTerminationReason.REVOKED
        return SessionClaim(
            session_id=response.session_id,
            entitlement=Entitlement(
                product_code=product_code,
                status=EntitlementStatus.ACTIVE,
                valid_until=response.license_valid_until,
            ),
            installation_id=response.installation_id,
            license_id="",
            runtime_config_version=response.runtime_config_version,
            heartbeat_interval_seconds=response.heartbeat_interval_seconds,
            server_time=response.server_time,
        )

    def heartbeat_session(self, session_id: str) -> bool:
        try:
            response = call_with_access_token(
                self._tokens,
                lambda token: self._client.heartbeat_session(
                    token,
                    session_id=session_id,
                ),
            )
        except ProxyApiError as error:
            if error.code in _AUTH_INVALID_CODES:
                raise HeartbeatAuthInvalid(
                    "การเข้าสู่ระบบหมดอายุ กรุณาเข้าสู่ระบบใหม่"
                ) from error
            if error.code == "session_conflict":
                self._termination_reason = SessionTerminationReason.REPLACED
                return False
            if error.code in {"account_suspended", "account_closed"}:
                self._termination_reason = (
                    SessionTerminationReason.ACCOUNT_RESTRICTED
                )
                return False
            if error.code in {"license_expired", "license_inactive"}:
                self._termination_reason = (
                    SessionTerminationReason.LICENSE_UNAVAILABLE
                )
                return False
            raise
        if response.session_id != session_id:
            raise ProxyApiError("invalid_response")
        self._heartbeat_interval_seconds = response.next_heartbeat_seconds
        return True

    def session_termination_reason(
        self, session_id: str
    ) -> SessionTerminationReason:
        return self._termination_reason

    def release_session(self, session_id: str) -> bool:
        try:
            response = call_with_access_token(
                self._tokens,
                lambda token: self._client.release_session(
                    token,
                    session_id=session_id,
                ),
            )
        except ProxyApiError:
            return False
        return response.released

    def redeem_coupon(self, code: str) -> CouponRedemption:
        raise LauncherServiceError(PENDING_COUPON_MESSAGE)
