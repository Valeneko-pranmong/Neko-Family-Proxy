from __future__ import annotations

from neko_launcher.domain.models import AppState, GameStatus, ProxyStatus
from neko_launcher.domain.telemetry import CoreHealthSnapshot, TelemetryConnectionState, TelemetryState
from neko_launcher.ui.status_presentation import get_server_status


def telemetry(*, connected: bool = True, stale: bool = False, healthy: bool = True) -> TelemetryState:
    return TelemetryState(
        connection_state=(TelemetryConnectionState.CONNECTED if connected else TelemetryConnectionState.DISCONNECTED),
        is_stale=stale,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            proxy_state="connected",
            v2ray_running=healthy,
            local_socks_running=healthy,
            shadowsocks_connected=healthy,
        ),
    )


def test_server_status_offline_connecting_and_failure() -> None:
    assert get_server_status(AppState()) == ("ออฟไลน์", "neutral")
    assert get_server_status(AppState(proxy_status=ProxyStatus.STARTING)) == ("กำลังเชื่อมต่อ", "warning")
    assert get_server_status(AppState(proxy_status=ProxyStatus.RECONNECTING)) == ("กำลังเชื่อมต่อ", "warning")
    assert get_server_status(AppState(game_process_running=True, proxy_status=ProxyStatus.STOPPED)) == ("กำลังเชื่อมต่อ", "warning")
    assert get_server_status(AppState(proxy_status=ProxyStatus.FAILED)) == ("ขัดข้อง", "danger")
    assert get_server_status(AppState(game_status=GameStatus.FAILED)) == ("ขัดข้อง", "danger")


def test_server_status_online_requires_fresh_complete_runtime_health() -> None:
    running = AppState(proxy_status=ProxyStatus.RUNNING, game_process_running=True)
    assert get_server_status(running, telemetry()) == ("ออนไลน์", "success")
    assert get_server_status(running, None)[1] == "warning"
    assert get_server_status(running, telemetry(connected=False))[1] == "warning"
    assert get_server_status(running, telemetry(stale=True))[1] == "warning"
    assert get_server_status(running, telemetry(healthy=False)) == ("เชื่อมต่อไม่สมบูรณ์", "warning")
