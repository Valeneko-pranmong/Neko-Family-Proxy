from pathlib import Path

from neko_launcher.infrastructure.config import LauncherConfig
from neko_launcher.bootstrap.app_factory import application_root


def test_packaged_runtime_defaults_to_local_app_data(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    local_app_data = tmp_path / "AppData"
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "LOCALAPPDATA",
        str(local_app_data),
    )

    config = LauncherConfig.from_environment(tmp_path / "bundle")

    assert config.proxy_core_path == (
        local_app_data / "NEKO FAMILY" / "ProxyCore" / "NekoProxyCore.exe"
    )
    assert config.supabase_url == "https://miikoutrnxsunbndecqh.supabase.co"
    assert config.supabase_publishable_key.startswith("sb_publishable_")
    assert config.account_recovery_api_url == "https://neko-control-room.vercel.app"


def test_runtime_ignores_bundled_neko_proxy_core(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    local_app_data = tmp_path / "AppData"
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "LOCALAPPDATA",
        str(local_app_data),
    )
    bundled_proxy = tmp_path / "ProxyCore" / "NekoProxyCore.exe"
    bundled_proxy.parent.mkdir()
    bundled_proxy.touch()

    config = LauncherConfig.from_environment(tmp_path)

    assert config.proxy_core_path == (
        local_app_data / "NEKO FAMILY" / "ProxyCore" / "NekoProxyCore.exe"
    )


def test_debug_mode_can_be_enabled_by_environment(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NEKO_DEBUG_MODE", "1")  # type: ignore[attr-defined]

    config = LauncherConfig.from_environment(tmp_path)
    assert config.debug_mode is True
    assert config.debug_log_dir.parts[-2:] == ("NekoFamilyProxy", "logs")

    monkeypatch.setenv("NEKO_DEBUG_MODE", "0")  # type: ignore[attr-defined]
    config_off = LauncherConfig.from_environment(tmp_path)
    assert config_off.debug_mode is False

    monkeypatch.delenv("NEKO_DEBUG_MODE", raising=False)  # type: ignore[attr-defined]
    config_unset = LauncherConfig.from_environment(tmp_path)
    assert config_unset.debug_mode is False


def test_application_root_uses_pyinstaller_extraction_directory(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("sys.frozen", True, raising=False)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "sys._MEIPASS",
        str(tmp_path),
        raising=False,
    )

    assert application_root() == tmp_path


def test_application_root_resolves_to_repository_root_in_source_mode(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr("sys.frozen", False, raising=False)  # type: ignore[attr-defined]

    root = application_root()

    assert (root / "launcher").is_dir()
    assert (root / "image_11.png").is_file()
    assert (root / "icon_app.ico").is_file()
