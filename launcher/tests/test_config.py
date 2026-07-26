from pathlib import Path

from neko_launcher.infrastructure.config import LauncherConfig
from neko_launcher.main import application_root


def clear_launcher_environment(monkeypatch: object) -> None:
    for name in (
        "NEKO_PROXY_CORE_PATH",
        "NEKO_PRODUCT_CODE",
        "NEKO_GAME_EXE",
        "NEKO_SUPABASE_URL",
        "NEKO_SUPABASE_PUBLISHABLE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)  # type: ignore[attr-defined]


def test_packaged_runtime_defaults_to_local_app_data(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    clear_launcher_environment(monkeypatch)
    local_app_data = tmp_path / "AppData"
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "LOCALAPPDATA",
        str(local_app_data),
    )

    config = LauncherConfig.from_environment(tmp_path / "bundle")

    assert config.proxy_core_path == (
        local_app_data / "NEKO FAMILY" / "ProxyCore" / "ProxyCore.exe"
    )


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
