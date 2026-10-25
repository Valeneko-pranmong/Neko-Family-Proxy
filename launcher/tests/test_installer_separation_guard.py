from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
ISS = REPO_ROOT / "installer" / "beta.iss"


def installer_source() -> str:
    return ISS.read_text(encoding="utf-8")


def test_installer_keeps_single_app_id_and_clean_start_policy() -> None:
    source = installer_source()

    assert "AppId={{D4A7C182-6B3E-4F19-9C05-2E8AF7B31D64}" in source
    assert "DefaultDirName={localappdata}\\NEKO FAMILY" in source
    assert "UsePreviousAppDir=no" in source
    assert "Type: filesandordirs; Name: \"{app}\\state\"" in source
    assert "Type: filesandordirs; Name: \"{app}\\trust\"" in source
    assert "Type: filesandordirs; Name: \"{app}\\ProxyCore\"" in source


def test_installer_blocks_a_different_installed_version() -> None:
    source = installer_source()

    assert "UninstallKey = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{D4A7C182-6B3E-4F19-9C05-2E8AF7B31D64}_is1'" in source
    assert "function ExistingInstallVersion(): String;" in source
    assert "RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion'" in source
    assert "InstalledVersion <> '{#MyAppVersion}'" in source
    assert "5.2.0 ต้องติดตั้งแยกจาก 5.1.6" in source
    assert "An existing NEKO FAMILY PROXY ' + InstalledVersion" in source
    assert "Result := False;" in source


def test_installer_blocks_running_launcher_core_and_updater() -> None:
    source = installer_source()

    assert "function ProcessesAreRunning(): Boolean;" in source
    assert "Get-Process -Name ''NekoLauncher'',''NekoProxyCore'',''NekoUpdater''" in source
    assert "ewWaitUntilTerminated" in source
    assert "if ProcessesAreRunning() then" in source
    assert "Exit;" in source


def test_installer_guard_runs_before_copying_or_deleting_files() -> None:
    source = installer_source()
    init_at = source.index("function InitializeSetup(): Boolean;")
    postinstall_at = source.index("procedure CurStepChanged(CurStep: TSetupStep);")

    assert init_at < postinstall_at
    guard = source[init_at:postinstall_at]
    assert "ExistingInstallVersion" in guard
    assert "ProcessesAreRunning" in guard
    assert "Result := True;" in guard
