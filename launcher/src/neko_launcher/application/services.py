from __future__ import annotations

from neko_launcher.domain.events import (
    AuthFailed,
    AuthStarted,
    AuthSucceeded,
    EntitlementLoaded,
    ErrorOccurred,
    SessionClaimed,
    SessionRevoked,
    StartProxyRequested,
)
from neko_launcher.domain.models import (
    CouponRedemption,
    RegistrationResult,
)

from .controller import ApplicationController
from .errors import EntitlementUnavailable, LauncherServiceError
from .ports import AuthGateway, EntitlementGateway, InstallationIdentity


class LauncherService:
    """Coordinates authentication, entitlement, session, and proxy workflows."""

    def __init__(
        self,
        controller: ApplicationController,
        auth_gateway: AuthGateway,
        entitlement_gateway: EntitlementGateway,
        installation: InstallationIdentity,
        product_code: str,
    ) -> None:
        self._controller = controller
        self._auth_gateway = auth_gateway
        self._entitlement_gateway = entitlement_gateway
        self._installation = installation
        self._product_code = product_code
        self._heartbeat_failures = 0

    def sign_up(self, email: str, password: str) -> RegistrationResult:
        email = email.strip().lower()
        self._validate_credentials(email, password)
        try:
            result = self._auth_gateway.sign_up(email, password)
        except LauncherServiceError:
            raise
        except Exception as exc:
            raise LauncherServiceError("สมัครสมาชิกไม่สำเร็จ กรุณาลองใหม่") from exc

        if result.user is not None:
            self._controller.dispatch(
                AuthSucceeded(result.user.user_id, result.user.email)
            )
            try:
                self._claim_session(allow_missing=True)
            except LauncherServiceError as exc:
                self._controller.dispatch(ErrorOccurred(str(exc)))
        return result

    def sign_in(self, email: str, password: str) -> None:
        email = email.strip().lower()
        self._validate_credentials(email, password)
        self._controller.dispatch(AuthStarted(email))
        try:
            user = self._auth_gateway.sign_in(email, password)
        except LauncherServiceError as exc:
            self._controller.dispatch(AuthFailed(str(exc)))
            raise
        except Exception as exc:
            message = "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่"
            self._controller.dispatch(AuthFailed(message))
            raise LauncherServiceError(message) from exc
        self._controller.dispatch(AuthSucceeded(user.user_id, user.email))
        self._claim_session(allow_missing=True)

    def restore_session(self) -> bool:
        try:
            user = self._auth_gateway.restore_session()
        except Exception:
            return False
        if user is None:
            return False
        self._controller.dispatch(AuthSucceeded(user.user_id, user.email))
        try:
            self._claim_session(allow_missing=True)
        except LauncherServiceError as exc:
            self._controller.dispatch(ErrorOccurred(str(exc)))
        return True

    def sign_out(self) -> None:
        session_id = self._controller.state.session_id
        if session_id:
            try:
                self._entitlement_gateway.release_session(session_id)
            except Exception:
                pass
        try:
            self._auth_gateway.sign_out()
        finally:
            self._controller.sign_out()

    def redeem_coupon(self, code: str) -> CouponRedemption:
        if not code.strip():
            raise LauncherServiceError("กรุณากรอกรหัสคูปอง")
        try:
            result = self._entitlement_gateway.redeem_coupon(code.strip())
        except LauncherServiceError:
            raise
        except Exception as exc:
            raise LauncherServiceError("ใช้คูปองไม่สำเร็จ กรุณาลองใหม่") from exc
        try:
            self._claim_session(allow_missing=False)
        except LauncherServiceError:
            self._controller.dispatch(
                ErrorOccurred(
                    "เติมคูปองสำเร็จ แต่ยังเปิดเซสชันไม่ได้ "
                    "กรุณาลองเข้าสู่ระบบใหม่"
                )
            )
        return result

    def heartbeat(self) -> bool:
        session_id = self._controller.state.session_id
        if not session_id:
            return False
        try:
            alive = self._entitlement_gateway.heartbeat_session(session_id)
        except Exception:
            self._heartbeat_failures += 1
            if self._heartbeat_failures < 3:
                return True
            alive = False
        else:
            self._heartbeat_failures = 0
        if not alive:
            self._controller.dispatch(
                SessionRevoked("เซสชันหมดอายุหรือถูกแทนที่จากอุปกรณ์อื่น")
            )
        return alive

    def start_proxy(self) -> None:
        self._controller.dispatch(StartProxyRequested())

    def shutdown(self) -> None:
        session_id = self._controller.state.session_id
        if session_id:
            try:
                self._entitlement_gateway.release_session(session_id)
            except Exception:
                pass
        self._controller.dispatch(SessionRevoked("ปิดโปรแกรมแล้ว"))

    def _claim_session(self, *, allow_missing: bool) -> None:
        try:
            claim = self._entitlement_gateway.claim_session(
                self._product_code,
                self._installation.key_hash,
                self._installation.display_name,
            )
        except EntitlementUnavailable:
            self._controller.dispatch(EntitlementLoaded(None))
            if not allow_missing:
                raise
        else:
            self._controller.dispatch(EntitlementLoaded(claim.entitlement))
            self._controller.dispatch(SessionClaimed(claim.session_id))

    @staticmethod
    def _validate_credentials(email: str, password: str) -> None:
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise LauncherServiceError("กรุณากรอกอีเมลให้ถูกต้อง")
        if len(password) < 8:
            raise LauncherServiceError("รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร")
