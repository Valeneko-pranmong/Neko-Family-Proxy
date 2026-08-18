from __future__ import annotations

import inspect

import neko_launcher.domain.telemetry as domain_telemetry
import neko_launcher.infrastructure.core.core_telemetry_client as core_telemetry_client


PROHIBITED_MODULE_PREFIXES = (
    "requests",
    "httpx",
    "urllib.request",
    "supabase",
    "postgrest",
    "gotrue",
    "websockets",
    "discord",
)


def test_telemetry_domain_module_has_zero_network_imports() -> None:
    source = inspect.getsource(domain_telemetry)
    for prohibited in PROHIBITED_MODULE_PREFIXES:
        assert f"import {prohibited}" not in source, f"Found prohibited import: {prohibited}"
        assert f"from {prohibited}" not in source, f"Found prohibited from-import: {prohibited}"


def test_telemetry_client_module_has_zero_network_imports() -> None:
    source = inspect.getsource(core_telemetry_client)
    for prohibited in PROHIBITED_MODULE_PREFIXES:
        assert f"import {prohibited}" not in source, f"Found prohibited import: {prohibited}"
        assert f"from {prohibited}" not in source, f"Found prohibited from-import: {prohibited}"


def test_telemetry_state_not_present_in_heartbeat_gateway() -> None:
    from neko_launcher.infrastructure.auth.supabase_gateway import SupabaseGateway

    source = inspect.getsource(SupabaseGateway.heartbeat_session)
    assert "telemetry" not in source.lower()
    assert "rx_bytes" not in source
    assert "tx_bytes" not in source
    assert "tcp_active" not in source
