from neko_launcher.domain.models import AppState, GameStatus, ProxyStatus, NetworkHopRole, HopConnectionState
from neko_launcher.domain.telemetry import TelemetryState, TelemetryConnectionState, CoreHealthSnapshot
from neko_launcher.ui.network_path_presentation import map_network_path

def test_disconnected_no_telemetry():
    state = AppState(
        game_process_running=False,
        game_status=GameStatus.STOPPED,
        proxy_status=ProxyStatus.STOPPED,
    )
    path = map_network_path(state, telemetry=None)
    
    assert len(path.hops) == 4
    assert path.proxy_rtt_ms is None
    
    roles = {hop.role: hop.connection_state for hop in path.hops}
    assert roles[NetworkHopRole.LOCAL_DEVICE] == HopConnectionState.UNAVAILABLE
    assert roles[NetworkHopRole.LOCAL_PROXY_ENGINE] == HopConnectionState.UNAVAILABLE
    assert roles[NetworkHopRole.REMOTE_PROXY] == HopConnectionState.UNAVAILABLE
    assert roles[NetworkHopRole.GAME_NETWORK] == HopConnectionState.UNAVAILABLE


def test_game_running_only():
    state = AppState(
        game_process_running=True,
        game_status=GameStatus.RUNNING,
        proxy_status=ProxyStatus.STOPPED,
    )
    path = map_network_path(state, telemetry=None)
    
    roles = {hop.role: hop.connection_state for hop in path.hops}
    assert roles[NetworkHopRole.LOCAL_DEVICE] == HopConnectionState.SUCCESS
    # Game network needs SUCCESS but actually, it requires GAME_NETWORK logic:
    # A running game without a connected remote proxy is not a ready game path.
    assert roles[NetworkHopRole.GAME_NETWORK] == HopConnectionState.CONNECTING
    assert roles[NetworkHopRole.LOCAL_PROXY_ENGINE] == HopConnectionState.UNAVAILABLE


def test_proxy_reconnecting_without_telemetry():
    state = AppState(proxy_status=ProxyStatus.RECONNECTING)
    path = map_network_path(state, telemetry=None)
    
    roles = {hop.role: hop.connection_state for hop in path.hops}
    assert roles[NetworkHopRole.LOCAL_PROXY_ENGINE] == HopConnectionState.CONNECTING
    assert roles[NetworkHopRole.REMOTE_PROXY] == HopConnectionState.UNAVAILABLE


def test_stale_telemetry_degrades_to_connecting():
    state = AppState(proxy_status=ProxyStatus.RUNNING)
    telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        is_stale=True,
    )
    path = map_network_path(state, telemetry)
    
    roles = {hop.role: hop.connection_state for hop in path.hops}
    assert roles[NetworkHopRole.LOCAL_PROXY_ENGINE] == HopConnectionState.CONNECTING
    assert roles[NetworkHopRole.REMOTE_PROXY] == HopConnectionState.UNAVAILABLE


def test_local_core_running_but_remote_not_connected():
    state = AppState(proxy_status=ProxyStatus.RUNNING)
    telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        is_stale=False,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=False,
        )
    )
    path = map_network_path(state, telemetry)
    
    roles = {hop.role: hop.connection_state for hop in path.hops}
    assert roles[NetworkHopRole.LOCAL_PROXY_ENGINE] == HopConnectionState.SUCCESS
    assert roles[NetworkHopRole.REMOTE_PROXY] == HopConnectionState.CONNECTING


def test_remote_connected():
    state = AppState(proxy_status=ProxyStatus.RUNNING)
    telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        is_stale=False,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
        )
    )
    path = map_network_path(state, telemetry)
    
    roles = {hop.role: hop.connection_state for hop in path.hops}
    assert roles[NetworkHopRole.LOCAL_PROXY_ENGINE] == HopConnectionState.SUCCESS
    assert roles[NetworkHopRole.REMOTE_PROXY] == HopConnectionState.SUCCESS


def test_full_connected_semantic_path():
    state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
        game_status=GameStatus.RUNNING,
    )
    telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        is_stale=False,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
        ),
    )
    path = map_network_path(state, telemetry)
    
    assert len(path.hops) == 4
    # ensure exact four roles in correct order
    assert path.hops[0].role == NetworkHopRole.LOCAL_DEVICE
    assert path.hops[1].role == NetworkHopRole.LOCAL_PROXY_ENGINE
    assert path.hops[2].role == NetworkHopRole.REMOTE_PROXY
    assert path.hops[3].role == NetworkHopRole.GAME_NETWORK

    assert path.hops[0].connection_state == HopConnectionState.SUCCESS
    assert path.hops[1].connection_state == HopConnectionState.SUCCESS
    assert path.hops[2].connection_state == HopConnectionState.SUCCESS
    assert path.hops[3].connection_state == HopConnectionState.SUCCESS
    
    assert path.proxy_rtt_ms is None


def test_map_network_path_flows_proxy_rtt_ms_when_fresh():
    state = AppState(
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
        game_status=GameStatus.RUNNING,
    )
    telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        is_stale=False,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
            proxy_rtt_ms=45,
        ),
    )
    path = map_network_path(state, telemetry)
    assert path.proxy_rtt_ms == 45
    # semantic hops remain intact
    assert len(path.hops) == 4
    assert path.hops[2].role == NetworkHopRole.REMOTE_PROXY
    assert path.hops[2].connection_state == HopConnectionState.SUCCESS


def test_map_network_path_proxy_rtt_ms_none_when_stale_or_disconnected_or_null():
    state = AppState(proxy_status=ProxyStatus.RUNNING)
    
    # 1. Stale telemetry with positive rtt -> None
    stale_telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        is_stale=True,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
            proxy_rtt_ms=50,
        ),
    )
    path_stale = map_network_path(state, stale_telemetry)
    assert path_stale.proxy_rtt_ms is None

    # 2. Disconnected telemetry -> None
    disconnected_telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.DISCONNECTED,
        is_stale=False,
        snapshot=CoreHealthSnapshot(proxy_rtt_ms=50),
    )
    path_disc = map_network_path(state, disconnected_telemetry)
    assert path_disc.proxy_rtt_ms is None

    # 3. None telemetry -> None
    path_none = map_network_path(state, None)
    assert path_none.proxy_rtt_ms is None

    # 4. Fresh connected telemetry with null rtt -> None
    null_rtt_telemetry = TelemetryState(
        connection_state=TelemetryConnectionState.CONNECTED,
        is_stale=False,
        snapshot=CoreHealthSnapshot(
            core_state="running",
            v2ray_running=True,
            local_socks_running=True,
            shadowsocks_connected=True,
            proxy_rtt_ms=None,
        ),
    )
    path_null = map_network_path(state, null_rtt_telemetry)
    assert path_null.proxy_rtt_ms is None
