from pathlib import Path

from neko_launcher.infrastructure.config import LauncherConfig
from neko_launcher.main import application_root


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


def test_packaged_runtime_uses_bundled_neko_proxy_core(tmp_path: Path) -> None:
    bundled_proxy = tmp_path / "ProxyCore" / "NekoProxyCore.exe"
    bundled_proxy.parent.mkdir()
    bundled_proxy.touch()

    config = LauncherConfig.from_environment(tmp_path)

    assert config.proxy_core_path == bundled_proxy


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
