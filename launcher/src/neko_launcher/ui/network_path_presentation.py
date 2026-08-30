from __future__ import annotations

from neko_launcher.domain.models import (
    AppState,
    GameStatus,
    HopConnectionState,
    NetworkHop,
    NetworkHopRole,
    NetworkPath,
    ProxyStatus,
)
from neko_launcher.domain.telemetry import TelemetryConnectionState, TelemetryState


def map_network_path(
    state: AppState, telemetry: TelemetryState | None = None
) -> NetworkPath:
    """Map app/Core state into the frozen privacy-safe four-hop contract.

    The dashboard currently renders only LOCAL_PROXY_ENGINE and REMOTE_PROXY.
    LOCAL_DEVICE and GAME_NETWORK remain in the domain contract for internal
    consistency and future presentation without adding raw endpoint data.
    """

    local_device_state = (
        HopConnectionState.SUCCESS
        if state.game_process_running
        else HopConnectionState.UNAVAILABLE
    )
    local_device_hop = NetworkHop(
        role=NetworkHopRole.LOCAL_DEVICE,
        label="อุปกรณ์ของคุณ",
        location="Local PC",
        connection_state=local_device_state,
    )

    proxy_engine_state = HopConnectionState.UNAVAILABLE
    remote_proxy_state = HopConnectionState.UNAVAILABLE

    telemetry_usable = (
        telemetry is not None
        and telemetry.connection_state is TelemetryConnectionState.CONNECTED
        and not telemetry.is_stale
    )
    if telemetry_usable:
        snapshot = telemetry.snapshot
        if (
            snapshot.core_state == "running"
            and snapshot.v2ray_running
            and snapshot.local_socks_running
        ):
            proxy_engine_state = HopConnectionState.SUCCESS
        elif snapshot.core_state == "stopped" or state.proxy_status is ProxyStatus.STOPPED:
            proxy_engine_state = HopConnectionState.UNAVAILABLE
        else:
            proxy_engine_state = HopConnectionState.CONNECTING

        if snapshot.shadowsocks_connected:
            remote_proxy_state = HopConnectionState.SUCCESS
        elif proxy_engine_state is HopConnectionState.SUCCESS:
            remote_proxy_state = HopConnectionState.CONNECTING
    else:
        if state.proxy_status in (ProxyStatus.STARTING, ProxyStatus.RECONNECTING):
            proxy_engine_state = HopConnectionState.CONNECTING
        elif state.proxy_status is ProxyStatus.RUNNING:
            # Running without fresh telemetry is conservatively still starting.
            proxy_engine_state = HopConnectionState.CONNECTING

    local_proxy_hop = NetworkHop(
        role=NetworkHopRole.LOCAL_PROXY_ENGINE,
        label="Neko Core",
        location="Local Service",
        connection_state=proxy_engine_state,
    )
    remote_proxy_hop = NetworkHop(
        role=NetworkHopRole.REMOTE_PROXY,
        label="Neko Proxy",
        location="Japan, Tokyo",
        connection_state=remote_proxy_state,
    )

    # Internal game-path state only. It is not a server-online claim and is not
    # rendered as a dashboard node in the current two-node UI.
    if state.game_process_running and remote_proxy_state is HopConnectionState.SUCCESS:
        game_network_state = HopConnectionState.SUCCESS
    elif state.game_process_running or state.game_status is GameStatus.STARTING:
        game_network_state = HopConnectionState.CONNECTING
    else:
        game_network_state = HopConnectionState.UNAVAILABLE
    game_network_hop = NetworkHop(
        role=NetworkHopRole.GAME_NETWORK,
        label="PSO2",
        location=None,
        connection_state=game_network_state,
    )

    proxy_rtt_ms: int | None = None
    if telemetry_usable:
        proxy_rtt_ms = telemetry.snapshot.proxy_rtt_ms

    return NetworkPath(
        hops=(
            local_device_hop,
            local_proxy_hop,
            remote_proxy_hop,
            game_network_hop,
        ),
        proxy_rtt_ms=proxy_rtt_ms,
    )
