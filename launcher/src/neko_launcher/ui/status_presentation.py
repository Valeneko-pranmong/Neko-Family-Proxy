from __future__ import annotations

from dataclasses import dataclass

from neko_launcher.domain.models import (
    AppState,
    AuthPhase,
    AuthStatus,
    EntitlementStatus,
    GameStatus,
    ProxyStatus,
    entitlement_is_active,
)
from neko_launcher.domain.telemetry import (
    TelemetryConnectionState,
    TelemetryState,
)


@dataclass(frozen=True)
class CustomerStatus:
    """Presentation-only status translation for the customer dashboard."""

    title: str
    subtitle: str
    role: str  # "success" | "warning" | "danger" | "neutral"
    is_ready: bool = False


AUTH_PROGRESS_TEXT: dict[AuthPhase, str] = {
    AuthPhase.OPENING_BROWSER: "กำลังเปิดเบราว์เซอร์",
    AuthPhase.WAITING_FOR_BROWSER: "กำลังรอการยืนยันจากเบราว์เซอร์",
    AuthPhase.CONNECTING: "ยืนยันแล้ว กำลังเชื่อมต่อบัญชี",
    AuthPhase.CHECKING_ENTITLEMENT: "เชื่อมต่อบัญชีแล้ว กำลังตรวจวันใช้งาน",
}


def describe_auth_progress(phase: AuthPhase) -> str:
    """Return the customer-facing label for a sign-in step."""
    return AUTH_PROGRESS_TEXT.get(phase, "กำลังเข้าสู่ระบบ")


def translate_customer_status(
    state: AppState,
    telemetry: TelemetryState | None = None,
) -> CustomerStatus:
    """Map internal domain/controller state into human-friendly customer UI copy.

    Strict Truthfulness Rule:
    - Never claim 'พร้อมใช้งาน' (READY) if there is an active Core failure,
      unauthenticated state, inactive entitlement, or session revocation.
    """
    # 1. Pre-auth / Recovery states
    if state.auth_status is AuthStatus.SIGNED_OUT:
        return CustomerStatus(
            title="ยังไม่ได้เข้าสู่ระบบ",
            subtitle="เข้าสู่ระบบด้วย Discord เพื่อเริ่มใช้งาน",
            role="neutral",
            is_ready=False,
        )
    if state.auth_status is AuthStatus.AUTHENTICATING:
        return CustomerStatus(
            title="กำลังเข้าสู่ระบบ",
            subtitle=describe_auth_progress(state.auth_phase),
            role="neutral",
            is_ready=False,
        )
    if state.auth_status in {
        AuthStatus.RECOVERY_CODE_ENTRY,
        AuthStatus.RECOVERY_VERIFYING,
        AuthStatus.RECOVERY_PASSWORD_CHANGE,
    }:
        return CustomerStatus(
            title="กำลังกู้คืนบัญชี",
            subtitle="ทำตามขั้นตอนบนหน้าจอเพื่อตั้งรหัสผ่านใหม่",
            role="neutral",
            is_ready=False,
        )
    if state.auth_status is AuthStatus.FAILED:
        return CustomerStatus(
            title="เข้าสู่ระบบไม่สำเร็จ",
            subtitle=state.last_error or "กรุณาลองอีกครั้ง หรือติดต่อผู้ดูแล",
            role="danger",
            is_ready=False,
        )

    # 2. Session Revoked / Replaced
    if state.deferred_session_revocation_reason:
        return CustomerStatus(
            title="ถูกตัดการเชื่อมต่อ",
            subtitle=state.deferred_session_revocation_reason,
            role="danger",
            is_ready=False,
        )

    # 3. Entitlement Inactive / Expired
    if not entitlement_is_active(state.entitlement):
        if state.entitlement and state.entitlement.status is EntitlementStatus.EXPIRED:
            return CustomerStatus(
                title="วันใช้งานหมดอายุ",
                subtitle="เติมวันในเมนูการตั้งค่าเพื่อเชื่อมต่ออีกครั้ง",
                role="danger",
                is_ready=False,
            )
        return CustomerStatus(
            title="ยังไม่มีวันใช้งาน",
            subtitle="กรอกรหัสคูปองในเมนูการตั้งค่าเพื่อเริ่มใช้งาน",
            role="danger",
            is_ready=False,
        )

    # 4. Proxy / Core Failures (Strict Truthfulness Check)
    if state.proxy_status is ProxyStatus.RECONNECTING:
        return CustomerStatus(
            title="กำลังเชื่อมต่อใหม่",
            subtitle="การเชื่อมต่อขัดข้องชั่วขณะ ระบบกำลังต่อให้อัตโนมัติ",
            role="warning",
            is_ready=False,
        )
    if state.proxy_status is ProxyStatus.FAILED or state.game_status is GameStatus.FAILED:
        return CustomerStatus(
            title="เชื่อมต่อไม่ได้",
            subtitle="กดเชื่อมต่อใหม่ หรือตรวจดูรายละเอียดในเมนูการตั้งค่า",
            role="danger",
            is_ready=False,
        )

    # 5. Active Proxy / Game In-Progress
    if state.proxy_status is ProxyStatus.RUNNING and state.game_process_running:
        if telemetry and telemetry.connection_state == TelemetryConnectionState.CONNECTED:
            if telemetry.is_stale:
                return CustomerStatus(
                    title="เชื่อมต่อแล้ว",
                    subtitle="เล่นต่อได้ แต่ข้อมูลเครือข่ายอัปเดตช้าชั่วคราว",
                    role="warning",
                    is_ready=False,
                )
            return CustomerStatus(
                title="เชื่อมต่อแล้ว",
                subtitle="เข้าเกมได้แล้ว ระบบเชื่อมต่อให้ครบทุกขั้น",
                role="success",
                is_ready=False,
            )
        return CustomerStatus(
            title="เชื่อมต่อแล้ว",
            subtitle="เล่นต่อได้ แต่ยังอ่านข้อมูลเครือข่ายไม่ได้",
            role="warning",
            is_ready=False,
        )

    # 6. Connecting / Starting States
    if (
        (state.proxy_status in {ProxyStatus.STARTING, ProxyStatus.STOPPING} and state.game_process_running)
        or (state.game_process_running and state.proxy_status is ProxyStatus.STOPPED)
    ):
        return CustomerStatus(
            title="กำลังเชื่อมต่อ",
            subtitle="พบตัวเกมแล้ว กำลังเชื่อมต่อให้",
            role="warning",
            is_ready=False,
        )

    if (
        state.proxy_status in {ProxyStatus.STARTING, ProxyStatus.STOPPING}
    ):
        return CustomerStatus(
            title="กำลังเชื่อมต่อ",
            subtitle="กำลังเตรียมระบบเชื่อมต่อ กรุณารอสักครู่",
            role="warning",
            is_ready=False,
        )

    # 7. Idle / Ready State (Healthy authenticated session with active entitlement, waiting for game)
    return CustomerStatus(
        title="พร้อมใช้งาน",
        subtitle="เปิดตัวเกมแล้วระบบจะเชื่อมต่อให้อัตโนมัติ",
        role="success",
        is_ready=True,
    )


def get_server_status(
    state: AppState,
    telemetry: TelemetryState | None = None,
) -> tuple[str, str]:
    """Map server status according to A18 requirements."""
    if state.proxy_status is ProxyStatus.FAILED or state.game_status is GameStatus.FAILED:
        return "ขัดข้อง", "danger"

    if (
        state.proxy_status in {ProxyStatus.STARTING, ProxyStatus.RECONNECTING}
        or (state.game_process_running and state.proxy_status is ProxyStatus.STOPPED)
    ):
        return "กำลังเชื่อมต่อ", "warning"

    if state.proxy_status is ProxyStatus.RUNNING:
        if (
            telemetry is None
            or telemetry.connection_state != TelemetryConnectionState.CONNECTED
            or telemetry.is_stale
        ):
            return "ตรวจสอบไม่ได้", "warning"

        snap = telemetry.snapshot
        if (
            snap.core_state == "running"
            and snap.v2ray_running
            and snap.local_socks_running
            and snap.shadowsocks_connected
        ):
            return "ปกติ", "success"
        else:
            return "ไม่เสถียร", "warning"

    return "ยังไม่เชื่อมต่อ", "danger"
