from __future__ import annotations

import sys
from pathlib import Path

import pytest

from neko_launcher.infrastructure.config import LauncherConfig


@pytest.fixture(autouse=True)
def clear_proxy_api_environment(monkeypatch) -> None:
    for name in (
        "NEKO_PROXY_API_URL",
        "NEKO_AUTH_BRIDGE_URL",
        "NEKO_WEB_AUTH_ENABLED",
        "NEKO_WEB_AUTH_ONLY",
        "NEKO_IDENTITY_BASE_URL",
        "NEKO_LAUNCHER_SCHEMA",
    ):
        monkeypatch.delenv(name, raising=False)


def test_proxy_api_url_is_disabled_by_default(tmp_path: Path) -> None:
    config = LauncherConfig.from_environment(tmp_path)

    assert config.proxy_api_url == ""
    assert config.proxy_api_enabled is False
    assert config.web_auth_enabled is False
    assert config.web_auth_only is False


def test_frozen_build_pairs_production_proxy_and_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    config = LauncherConfig.from_environment(tmp_path)

    assert config.proxy_api_url == "https://neko-control-room.vercel.app"
    assert config.identity_base_url == "https://neko-network-id.vercel.app"
    assert config.web_auth_bridge_url == ""
    assert config.proxy_api_enabled is True
    assert config.web_auth_only is True


def test_proxy_api_url_alone_enables_web_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NEKO_PROXY_API_URL", "https://proxy.example/")

    config = LauncherConfig.from_environment(tmp_path)

    assert config.proxy_api_url == "https://proxy.example"
    assert config.proxy_api_enabled is True
    assert config.web_auth_enabled is True
    assert config.web_auth_only is True
    assert config.web_auth_bridge_url == ""


def test_proxy_api_url_and_bridge_are_mutually_exclusive(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NEKO_PROXY_API_URL", "https://proxy.example")
    monkeypatch.setenv(
        "NEKO_AUTH_BRIDGE_URL",
        "https://bridge.example/auth/launcher/exchange",
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        LauncherConfig.from_environment(tmp_path)


def test_proxy_api_url_is_rejected_in_frozen_builds(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("NEKO_PROXY_API_URL", "https://proxy.example")

    with pytest.raises(ValueError, match="disabled in frozen builds"):
        LauncherConfig.from_environment(tmp_path)


def test_proxy_api_url_rejects_password_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NEKO_PROXY_API_URL", "https://proxy.example")
    monkeypatch.setenv("NEKO_WEB_AUTH_ONLY", "0")

    with pytest.raises(ValueError, match="requires web-only"):
        LauncherConfig.from_environment(tmp_path)


def test_proxy_api_url_accepts_explicit_web_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NEKO_PROXY_API_URL", "https://proxy.example")
    monkeypatch.setenv("NEKO_WEB_AUTH_ONLY", "1")

    config = LauncherConfig.from_environment(tmp_path)

    assert config.web_auth_only is True


@pytest.mark.parametrize(
    "value",
    [
        "http://proxy.example",
        "https://proxy.example/api",
        "https://user:pass@proxy.example",
    ],
)
def test_proxy_api_url_requires_https_origin(
    monkeypatch,
    tmp_path: Path,
    value: str,
) -> None:
    monkeypatch.setenv("NEKO_PROXY_API_URL", value)

    with pytest.raises(ValueError, match="HTTPS origin"):
        LauncherConfig.from_environment(tmp_path)


def test_legacy_bridge_configuration_still_works_without_proxy_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NEKO_WEB_AUTH_ENABLED", "1")
    monkeypatch.setenv(
        "NEKO_AUTH_BRIDGE_URL",
        "https://bridge.example/auth/launcher/exchange",
    )

    config = LauncherConfig.from_environment(tmp_path)

    assert config.proxy_api_enabled is False
    assert config.web_auth_enabled is True
    assert config.web_auth_only is True
    assert config.web_auth_bridge_url.endswith("/auth/launcher/exchange")
