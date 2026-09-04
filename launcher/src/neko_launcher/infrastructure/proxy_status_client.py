from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


_ALLOWED_HOST_STATUSES = frozenset({"ONLINE", "DEGRADED", "STALE", "UNKNOWN", "OFFLINE"})
_ALLOWED_LOAD_LEVELS = frozenset({"light", "moderate", "heavy", "full", "unknown"})


@dataclass(frozen=True)
class PublicProxyStatus:
    host_status: str = "UNKNOWN"
    load_level: str = "unknown"
    avg_rx_bps: int = 0
    avg_tx_bps: int = 0
    sample_count: int = 0
    covered_minutes: int = 0
    observed_at: str | None = None
    age_seconds: int | None = None

    @property
    def load_label(self) -> str:
        return {
            "light": "เบาบาง",
            "moderate": "ปานกลาง",
            "heavy": "หนาแน่น",
            "full": "เต็ม",
        }.get(self.load_level, "ยังไม่มีข้อมูล")


class PublicProxyStatusClient:
    """Read-only public aggregate status client.

    No authentication material is sent. The endpoint is deliberately aggregate
    and contains no client identity, credentials, raw proxy endpoint, or packet
    data. Failures are isolated from Launcher/Core operation.
    """

    _MAX_RESPONSE_BYTES = 64 * 1024

    def __init__(self, url: str, *, timeout: float = 4.0) -> None:
        self._url = url.strip()
        self._timeout = timeout

    @staticmethod
    def _non_negative_int(value: object, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        try:
            number = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return default
        return max(0, number)

    @classmethod
    def parse(cls, document: object) -> PublicProxyStatus:
        if not isinstance(document, dict) or document.get("ok") is not True:
            raise ValueError("invalid public proxy status response")
        proxy = document.get("proxy")
        if not isinstance(proxy, dict):
            raise ValueError("missing public proxy status payload")
        average = proxy.get("average_30m")
        if not isinstance(average, dict):
            average = {}

        host_status = str(proxy.get("status", "UNKNOWN")).upper()
        if host_status not in _ALLOWED_HOST_STATUSES:
            host_status = "UNKNOWN"
        load_level = str(proxy.get("load_level", "unknown")).lower()
        if load_level not in _ALLOWED_LOAD_LEVELS:
            load_level = "unknown"

        observed_at = proxy.get("observed_at")
        if observed_at is not None and not isinstance(observed_at, str):
            observed_at = None
        raw_age = proxy.get("age_seconds")
        age_seconds = None if raw_age is None else cls._non_negative_int(raw_age)

        return PublicProxyStatus(
            host_status=host_status,
            load_level=load_level,
            avg_rx_bps=cls._non_negative_int(average.get("rx_bps")),
            avg_tx_bps=cls._non_negative_int(average.get("tx_bps")),
            sample_count=cls._non_negative_int(average.get("sample_count")),
            covered_minutes=min(30, cls._non_negative_int(average.get("covered_minutes"))),
            observed_at=observed_at,
            age_seconds=age_seconds,
        )

    def fetch(self) -> PublicProxyStatus:
        if not self._url.startswith("https://"):
            raise ValueError("public proxy status URL must use HTTPS")
        request = urllib.request.Request(
            self._url,
            headers={"Accept": "application/json", "User-Agent": "NekoLauncher-Support/1"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = response.read(self._MAX_RESPONSE_BYTES + 1)
                if len(payload) > self._MAX_RESPONSE_BYTES:
                    raise ValueError("public proxy status response too large")
                if not 200 <= response.status < 300:
                    raise ValueError("public proxy status request failed")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ConnectionError("public proxy status unavailable") from exc
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid public proxy status JSON") from exc
        return self.parse(document)


def format_bps(bits_per_second: int) -> str:
    value = max(0, int(bits_per_second))
    if value < 1000:
        return f"{value} bps"
    if value < 1_000_000:
        return f"{value / 1000:.1f} Kbps"
    if value < 1_000_000_000:
        return f"{value / 1_000_000:.2f} Mbps"
    return f"{value / 1_000_000_000:.2f} Gbps"
