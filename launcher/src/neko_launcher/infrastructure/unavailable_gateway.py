from __future__ import annotations

from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.application.ports import AuthGateway, EntitlementGateway
from neko_launcher.domain.models import (
    AuthenticatedUser,
    CouponRedemption,
    RegistrationResult,
    SessionClaim,
    SessionTerminationReason,
)


class AuthorizationPendingProxyGateway:
    """Fail closed until the approved Backend/Core protocol is wired."""

    def has_owned_host(self) -> bool:
        return False

    def start(self) -> None:
        raise RuntimeError("authorization integration is unavailable")

    def stop(self) -> None:
        return

    def shutdown(self) -> None:
        return


class UnavailableSupabaseGateway(AuthGateway, EntitlementGateway):
    """Fallback for a temporary API outage."""

    _MESSAGE = "เชื่อมต่อระบบไม่ได้ชั่วคราว กรุณาตรวจสอบอินเทอร์เน็ตแล้วลองใหม่"

    def sign_up(
        self,
        username: str,
        password: str,
    ) -> RegistrationResult:
        raise LauncherServiceError(self._MESSAGE)

    def sign_in(self, username: str, password: str) -> AuthenticatedUser:
        raise LauncherServiceError(self._MESSAGE)

    def change_password(self, password: str) -> None:
        raise LauncherServiceError(self._MESSAGE)

    def auth_identifier_for_username(self, username: str) -> str:
        raise LauncherServiceError(self._MESSAGE)

    def restore_session(self) -> AuthenticatedUser | None:
        return None

    def sign_out(self) -> None:
        return

    def clear_local_session(self) -> None:
        return

    def claim_session(
        self,
        product_code: str,
        installation_key_hash: str,
        display_name: str,
    ) -> SessionClaim:
        raise LauncherServiceError(self._MESSAGE)

    def heartbeat_session(self, session_id: str) -> bool:
        return False

    def session_termination_reason(
        self, session_id: str
    ) -> SessionTerminationReason:
        return SessionTerminationReason.REVOKED

    def release_session(self, session_id: str) -> bool:
        return False

    def redeem_coupon(self, code: str) -> CouponRedemption:
        raise LauncherServiceError(self._MESSAGE)
