from __future__ import annotations

from neko_launcher.domain.events import (
    AuthFailed,
    AuthStarted,
    AuthSucceeded,
    EntitlementLoaded,
    ErrorOccurred,
    LaunchTweakerRequested,
    SessionClaimed,
    SessionRevoked,
    StartProxyRequested,
    StartUsageRequested,
    StopProxyRequested,
)
from neko_launcher.domain.models import (
    AuthStatus,
    CouponRedemption,
    Entitlement,
    EntitlementStatus,
    ProxyStatus,
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

    def sign_up(
        self,
        username: str,
        password: str,
    ) -> RegistrationResult:
        username = username.strip().lower()
        self._validate_username(username, password)
        self._controller.dispatch(AuthStarted(username))
        try:
            result = self._auth_gateway.sign_up(
                username,
                password,
            )
        except LauncherServiceError as exc:
            self._controller.dispatch(AuthFailed(str(exc)))
            raise
        except Exception as exc:
            message = "สมัครสมาชิกไม่สำเร็จ กรุณาลองใหม่"
            self._controller.dispatch(AuthFailed(message))
            raise LauncherServiceError(message) from exc

        if result.user is not None:
            self._controller.dispatch(
                AuthSucceeded(result.user.user_id, result.user.username)
            )
            try:
                self._claim_session(allow_missing=True)
            except LauncherServiceError as exc:
                self._controller.dispatch(ErrorOccurred(str(exc)))
        return result

    def sign_in(self, username: str, password: str) -> None:
        username = username.strip().lower()
        self._validate_login_identifier(username, password)
        self._controller.dispatch(AuthStarted(username))
        try:
            user = self._auth_gateway.sign_in(username, password)
        except LauncherServiceError as exc:
            self._controller.dispatch(AuthFailed(str(exc)))
            raise
        except Exception as exc:
            message = "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่"
            self._controller.dispatch(AuthFailed(message))
            raise LauncherServiceError(message) from exc
        self._controller.dispatch(AuthSucceeded(user.user_id, user.username))
        self._claim_session(allow_missing=True)

    def change_password(self, password: str) -> None:
        """Change the password for the currently authenticated user."""
        if self._controller.state.auth_status is not AuthStatus.AUTHENTICATED:
            raise LauncherServiceError("กรุณาเข้าสู่ระบบก่อนเปลี่ยนรหัสผ่าน")
        self._validate_password(password)
        try:
            self._auth_gateway.change_password(password)
        except LauncherServiceError:
            raise
        except Exception as exc:
            raise LauncherServiceError(
                "เปลี่ยนรหัสผ่านไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"
            ) from exc

    def restore_session(self) -> bool:
        try:
            user = self._auth_gateway.restore_session()
        except Exception:
            return False
        if user is None:
            return False
        self._controller.dispatch(AuthSucceeded(user.user_id, user.username))
        try:
            self._claim_session(allow_missing=True)
        except LauncherServiceError as exc:
            self._controller.dispatch(ErrorOccurred(str(exc)))
        return True

    def sign_out(self) -> None:
        if self._controller.state.proxy_status in {
            ProxyStatus.STARTING,
            ProxyStatus.RUNNING,
        }:
            self._controller.dispatch(StopProxyRequested())
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
        # Update the home screen immediately from the server's redemption
        # result.  The session claim below may still fail (for example when
        # another device is active), but the newly added days are real and
        # should not remain displayed as 0.
        self._controller.dispatch(
            EntitlementLoaded(
                Entitlement(
                    product_code=result.product_code,
                    status=EntitlementStatus.ACTIVE,
                    valid_until=result.valid_until,
                )
            )
        )
        try:
            self._claim_session(allow_missing=False)
        except LauncherServiceError:
            # _claim_session clears the session when it cannot claim one.
            # Keep the redeemed entitlement visible even when launching is
            # temporarily blocked by a device/session constraint.
            self._controller.dispatch(
                EntitlementLoaded(
                    Entitlement(
                        product_code=result.product_code,
                        status=EntitlementStatus.ACTIVE,
                        valid_until=result.valid_until,
                    )
                )
            )
            self._controller.dispatch(
                ErrorOccurred(
                    "เติมคูปองสำเร็จแล้ว แต่ยังเริ่มใช้งานไม่ได้ "
                    "กรุณาออกจากระบบแล้วเข้าสู่ระบบใหม่"
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
                SessionRevoked(
                    "บัญชีนี้กำลังถูกใช้งานจากเครื่องอื่น กรุณาเข้าสู่ระบบใหม่"
                )
            )
        return alive

    def start_proxy(self) -> None:
        self._controller.dispatch(StartProxyRequested())

    def start_usage(self, executable: str) -> None:
        """Start ProxyCore and the configured Tweaker as one user action."""
        self._controller.dispatch(StartUsageRequested(executable))

    def launch_tweaker(self, executable: str) -> None:
        """Launch Tweaker; Auto Connect will start ProxyCore after pso2.exe appears."""
        self._controller.dispatch(LaunchTweakerRequested(executable))

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
    def _validate_username(username: str, password: str) -> None:
        LauncherService._validate_username_format(username)
        LauncherService._validate_password(password)

    @staticmethod
    def _validate_username_format(username: str) -> None:
        if not username:
            raise LauncherServiceError("กรุณากรอกชื่อผู้ใช้")
        if "@" in username or (
            not 3 <= len(username) <= 32
            or any(
                not (char.isascii() and (char.isalnum() or char == "_"))
                for char in username
            )
        ):
            raise LauncherServiceError(
                "ชื่อผู้ใช้ต้องมี 3-32 ตัวอักษร (a-z, 0-9 หรือ _)"
            )

    @staticmethod
    def _validate_login_identifier(identifier: str, password: str) -> None:
        LauncherService._validate_username(identifier, password)

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 8:
            raise LauncherServiceError("รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร")
