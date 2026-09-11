def test_expected_assets_list():
    from scripts.build_software_release_v2 import EXPECTED_ASSETS
    assert set(EXPECTED_ASSETS) == {
        "NekoFamilyProxy-Setup.exe",
        "NekoLauncher.exe",
        "NekoUpdater.exe",
        "NekoProxyCore.zip",
        "release-v2.json"
    }

def test_sign_software_release_custody(monkeypatch):
    from scripts.sign_software_release import PRODUCTION_KEY_REF, verify_and_sign
    import pytest
    
    assert PRODUCTION_KEY_REF == "C:/Users/Pranmong/AppData/Local/NekoFamily/release-custody/neko-update-prod-1.pem"
    
    # Remove PYTEST_CURRENT_TEST so the bypass is disabled and we can test the enforcement
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    
    with pytest.raises(ValueError, match="runtime-settings.key is forbidden"):
        verify_and_sign("some-input", "some-output", r"C:\path\to\runtime-settings.key", "some-id")
        
    with pytest.raises(ValueError, match="Custody reference violation"):
        verify_and_sign("some-input", "some-output", r"C:\path\to\wrong-key.pem", "some-id")
