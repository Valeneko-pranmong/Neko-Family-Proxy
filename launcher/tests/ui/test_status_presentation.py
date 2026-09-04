from __future__ import annotations

from datetime import datetime, timedelta, timezone
from neko_launcher.domain.models import (
    AppState,
    AuthStatus,
    Entitlement,
    EntitlementStatus,
    GameStatus,
    ProxyStatus,
)
from neko_launcher.domain.telemetry import (
    CoreHealthSnapshot,
    TelemetryConnectionState,
    TelemetryState,
)
from neko_launcher.ui.status_presentation import (
    translate_customer_status,
)


def test_status_signed_out() -> None:
    state = AppState(auth_status=AuthStatus.SIGNED_OUT)
    status = translate_customer_status(state)
    assert status.title == "ยังไม่ได้เข้าสู่ระบบ"
    assert status.role == "neutral"
    assert status.is_ready is False


def test_status_authenticating() -> None:
    state = AppState(auth_status=AuthStatus.AUTHENTICATING)
    status = translate_customer_status(state)
    assert "กำลังเข้าสู่ระบบ" in status.title
    assert status.role == "neutral"
    assert status.is_ready is False


def test_status_auth_failed() -> None:
    state = AppState(
        auth_status=AuthStatus.FAILED,
        last_error="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง",
    )
    status = translate_customer_status(state)
    assert "เข้าสู่ระบบไม่สำเร็จ" in status.title
    assert status.subtitle == "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
    assert status.role == "danger"
    assert status.is_ready is False


def test_status_recovery() -> None:
    for recovery_auth in (
        AuthStatus.RECOVERY_CODE_ENTRY,
        AuthStatus.RECOVERY_VERIFYING,
        AuthStatus.RECOVERY_PASSWORD_CHANGE,
    ):
        state = AppState(auth_status=recovery_auth)
        status = translate_customer_status(state)
        assert status.title == "กู้คืนบัญชี"
        assert status.role == "neutral"
        assert status.is_ready is False


def test_status_session_revocation() -> None:
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        deferred_session_revocation_reason="เซสชันถูกแทนที่จากเครื่องอื่น",
    )
    status = translate_customer_status(state)
    assert status.title == "เซสชันหมดอายุ"
    assert status.subtitle == "เซสชันถูกแทนที่จากเครื่องอื่น"
    assert status.role == "danger"
    assert status.is_ready is False


def test_status_expired_entitlement() -> None:
    past = datetime.now(timezone.utc) - timedelta(days=1)
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("pso2-proxy", EntitlementStatus.EXPIRED, past),
    )
    status = translate_customer_status(state)
    assert status.title == "วันใช้งานหมดอายุ"
    assert status.role == "danger"
    assert status.is_ready is False


def test_status_core_failure_never_reports_ready() -> None:
    future = datetime.now(timezone.utc) + timedelta(days=30)
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("pso2-proxy", EntitlementStatus.ACTIVE, future),
        proxy_status=ProxyStatus.FAILED,
        game_process_running=False,
    )
    status = translate_customer_status(state)
    assert status.title == "เชื่อมต่อไม่ได้"
    assert status.role == "danger"
    assert status.is_ready is False


def test_status_game_detected_connecting() -> None:
    future = datetime.now(timezone.utc) + timedelta(days=30)
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("pso2-proxy", EntitlementStatus.ACTIVE, future),
        proxy_status=ProxyStatus.STARTING,
        game_process_running=True,
    )
    status = translate_customer_status(state)
    assert status.title == "กำลังเชื่อมต่อ"
    assert status.subtitle == "พบ pso2.exe แล้ว กำลังเชื่อมต่อ Neko Core"
    assert status.role == "warning"
    assert status.is_ready is False


def test_status_reconnecting_is_truthful_and_actionable() -> None:
    future = datetime.now(timezone.utc) + timedelta(days=30)
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("pso2-proxy", EntitlementStatus.ACTIVE, future),
        session_id="session-id",
        proxy_status=ProxyStatus.RECONNECTING,
        game_process_running=True,
    )

    status = translate_customer_status(state)

    assert status.title == "กำลังเชื่อมต่อใหม่"
    assert "อัตโนมัติ" in status.subtitle
    assert status.role == "warning"
    assert status.is_ready is False


def test_status_connected_running_healthy() -> None:
    future = datetime.now(timezone.utc) + timedelta(days=30)
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("pso2-proxy", EntitlementStatus.ACTIVE, future),
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(core_state="running", proxy_state="connected"),
        is_stale=False,
    )
    status = translate_customer_status(state, telemetry)
    assert status.title == "เชื่อมต่อแล้ว"
    assert status.subtitle == "Neko Core และ Neko Proxy ทำงานอย่างสมบูรณ์ Enjoy!"
    assert status.role == "success"
    assert status.is_ready is False


def test_status_connected_stale_telemetry() -> None:
    future = datetime.now(timezone.utc) + timedelta(days=30)
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("pso2-proxy", EntitlementStatus.ACTIVE, future),
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        snapshot=CoreHealthSnapshot(core_state="running", proxy_state="connected"),
        is_stale=True,
    )
    status = translate_customer_status(state, telemetry)
    assert status.title == "เชื่อมต่อแล้ว"
    assert "อัปเดตช้าชั่วคราว" in status.subtitle
    assert status.role == "warning"


def test_status_ready_healthy_idle() -> None:
    future = datetime.now(timezone.utc) + timedelta(days=30)
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("pso2-proxy", EntitlementStatus.ACTIVE, future),
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.STOPPED,
        game_process_running=False,
    )
    status = translate_customer_status(state)
    assert status.title == "กำลังรอ PSO2"
    assert "กำลังรอ pso2.exe" in status.subtitle
    assert status.role == "success"
    assert status.is_ready is True

def test_tweaker_starting_alone_does_not_report_connecting_status() -> None:
    future = datetime.now(timezone.utc) + timedelta(days=30)
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("pso2-proxy", EntitlementStatus.ACTIVE, future),
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.STARTING,
        game_process_running=False,
    )
    status = translate_customer_status(state)
    assert status.title == "กำลังรอ PSO2"
    assert status.role == "success"
    assert status.is_ready is True

def test_tweaker_starting_alone_does_not_report_server_connecting_status() -> None:
    future = datetime.now(timezone.utc) + timedelta(days=30)
    state = AppState(
        auth_status=AuthStatus.AUTHENTICATED,
        entitlement=Entitlement("pso2-proxy", EntitlementStatus.ACTIVE, future),
        proxy_status=ProxyStatus.STOPPED,
        game_status=GameStatus.STARTING,
        game_process_running=False,
    )
    from neko_launcher.ui.status_presentation import get_server_status
    text, role = get_server_status(state)
    assert text == "OFFLINE"
    assert role == "danger"
