from __future__ import annotations

from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.application.ports import AuthGateway, EntitlementGateway
from neko_launcher.domain.models import (
    AuthenticatedUser,
    CouponRedemption,
    RegistrationResult,
    SessionClaim,
)


class UnavailableSupabaseGateway(AuthGateway, EntitlementGateway):
    """Keeps the UI usable while clearly reporting missing configuration."""

    _MESSAGE = (
        "ยังไม่ได้ตั้งค่า Supabase publishable key ใน "
        "launcher/.env.local หรือ %LOCALAPPDATA%\\NEKO FAMILY\\launcher.env"
    )

    def sign_up(self, email: str, password: str) -> RegistrationResult:
        raise LauncherServiceError(self._MESSAGE)

    def sign_in(self, email: str, password: str) -> AuthenticatedUser:
        raise LauncherServiceError(self._MESSAGE)

    def restore_session(self) -> AuthenticatedUser | None:
        return None

    def sign_out(self) -> None:
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

    def release_session(self, session_id: str) -> bool:
        return False

    def redeem_coupon(self, code: str) -> CouponRedemption:
        raise LauncherServiceError(self._MESSAGE)
