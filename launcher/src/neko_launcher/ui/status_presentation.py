from __future__ import annotations

from dataclasses import dataclass
from neko_launcher.domain.models import (
    AppState,
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
            subtitle="กรุณาเข้าสู่ระบบเพื่อเริ่มใช้งาน",
            role="neutral",
            is_ready=False,
        )
    if state.auth_status is AuthStatus.AUTHENTICATING:
        return CustomerStatus(
            title="กำลังเข้าสู่ระบบ...",
            subtitle="กำลังตรวจสอบข้อมูลผู้ใช้",
            role="neutral",
            is_ready=False,
        )
    if state.auth_status in {
        AuthStatus.RECOVERY_CODE_ENTRY,
        AuthStatus.RECOVERY_VERIFYING,
        AuthStatus.RECOVERY_PASSWORD_CHANGE,
    }:
        return CustomerStatus(
            title="กู้คืนบัญชี",
            subtitle="กำลังอยู่ในขั้นตอนการกู้รหัสผ่าน",
            role="neutral",
            is_ready=False,
        )
    if state.auth_status is AuthStatus.FAILED:
        return CustomerStatus(
            title="เข้าสู่ระบบไม่สำเร็จ",
            subtitle=state.last_error or "กรุณาตรวจสอบชื่อผู้ใช้และรหัสผ่าน",
            role="danger",
            is_ready=False,
        )

    # 2. Session Revoked / Replaced
    if state.deferred_session_revocation_reason:
        return CustomerStatus(
            title="เซสชันหมดอายุ",
            subtitle=state.deferred_session_revocation_reason,
            role="danger",
            is_ready=False,
        )

    # 3. Entitlement Inactive / Expired
    if not entitlement_is_active(state.entitlement):
        if state.entitlement and state.entitlement.status is EntitlementStatus.EXPIRED:
            subtitle = "วันใช้งานหมดอายุแล้ว กรุณาเติมวันในเมนูการตั้งค่า"
        else:
            subtitle = "ยังไม่มีวันใช้งาน กรุณาเติมวันด้วยคูปองในเมนูการตั้งค่า"
        return CustomerStatus(
            title="วันใช้งานหมดอายุ",
            subtitle=subtitle,
            role="danger",
            is_ready=False,
        )

    # 4. Proxy / Core Failures (Strict Truthfulness Check)
    if state.proxy_status is ProxyStatus.RECONNECTING:
        return CustomerStatus(
            title="กำลังเชื่อมต่อใหม่",
            subtitle="การเชื่อมต่อสะดุดนิดหน่อย กำลังต่อให้ใหม่อัตโนมัติ",
            role="warning",
            is_ready=False,
        )
    if state.proxy_status is ProxyStatus.FAILED or state.game_status is GameStatus.FAILED:
        return CustomerStatus(
            title="เชื่อมต่อไม่ได้",
            subtitle="ลองใหม่อีกครั้ง หรือดูรายละเอียดที่ Settings > Status",
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
                subtitle="Neko Core และ Neko Proxy ทำงานอย่างสมบูรณ์ Enjoy!",
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
            subtitle="พบ pso2.exe แล้ว กำลังเชื่อมต่อ Neko Core",
            role="warning",
            is_ready=False,
        )

    if (
        state.proxy_status in {ProxyStatus.STARTING, ProxyStatus.STOPPING}
    ):
        return CustomerStatus(
            title="กำลังเชื่อมต่อ",
            subtitle="กำลังเริ่มทำงาน",
            role="warning",
            is_ready=False,
        )

    # 7. Idle / Ready State (Healthy authenticated session with active entitlement, waiting for game)
    return CustomerStatus(
        title="กำลังรอ PSO2",
        subtitle="กำลังรอ pso2.exe",
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
            return "ข้อมูลสถานะไม่พร้อม", "warning"

        snap = telemetry.snapshot
        if (
            snap.core_state == "running"
            and snap.v2ray_running
            and snap.local_socks_running
            and snap.shadowsocks_connected
        ):
            return "ONLINE", "success"
        else:
            return "เชื่อมต่อไม่สมบูรณ์", "warning"

    return "OFFLINE", "danger"
