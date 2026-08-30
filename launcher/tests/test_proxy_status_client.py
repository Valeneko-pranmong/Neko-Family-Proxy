from __future__ import annotations

from neko_launcher.infrastructure.proxy_status_client import (
    PublicProxyStatusClient,
    format_bps,
)


def test_public_proxy_status_parse_maps_safe_aggregate_fields() -> None:
    status = PublicProxyStatusClient.parse(
        {
            "ok": True,
            "proxy": {
                "status": "ONLINE",
                "load_level": "moderate",
                "average_30m": {
                    "rx_bps": 113_250,
                    "tx_bps": 11_480,
                    "sample_count": 30,
                    "covered_minutes": 30,
                },
                "observed_at": "2026-08-30T12:00:00.000Z",
                "age_seconds": 4,
            },
        }
    )
    assert status.host_status == "ONLINE"
    assert status.load_level == "moderate"
    assert status.load_label == "ปานกลาง"
    assert status.avg_rx_bps == 113_250
    assert status.avg_tx_bps == 11_480
    assert status.sample_count == 30
    assert status.covered_minutes == 30
    assert status.age_seconds == 4


def test_public_proxy_status_parse_degrades_unknown_values_safely() -> None:
    status = PublicProxyStatusClient.parse(
        {
            "ok": True,
            "proxy": {
                "status": "something-new",
                "load_level": "mystery",
                "average_30m": {"rx_bps": -1, "tx_bps": "bad"},
            },
        }
    )
    assert status.host_status == "UNKNOWN"
    assert status.load_level == "unknown"
    assert status.load_label == "ยังไม่มีข้อมูล"
    assert status.avg_rx_bps == 0
    assert status.avg_tx_bps == 0


def test_format_bps_uses_network_bit_rate_units() -> None:
    assert format_bps(0) == "0 bps"
    assert format_bps(1_000) == "1.0 Kbps"
    assert format_bps(113_250) == "113.2 Kbps"
    assert format_bps(2_500_000) == "2.50 Mbps"
