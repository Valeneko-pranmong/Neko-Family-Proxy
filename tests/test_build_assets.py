from pathlib import Path


def test_expected_assets_list():
    from scripts.build_software_release_v2 import EXPECTED_ASSETS
    assert set(EXPECTED_ASSETS) == {
        "NekoFamilyProxy-Installer.exe",
        "NekoLauncher.exe",
        "NekoUpdater.exe",
        "NekoProxyCore.zip",
        "release-v2.json"
    }

def test_sign_software_release_custody(monkeypatch, tmp_path):
    import pytest
    from scripts.sign_software_release import (
        production_key_reference,
        verify_and_sign,
    )

    custody_key = tmp_path / "custody" / "neko-update-prod-1.pem"
    monkeypatch.setenv("NEKO_RELEASE_KEY_REF", str(custody_key))
    assert "neko-update-prod-1.pem" in production_key_reference()

    # Remove PYTEST_CURRENT_TEST so the bypass is disabled and we can test the enforcement
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    with pytest.raises(ValueError, match="runtime-settings.key is forbidden"):
        verify_and_sign("some-input", "some-output", r"C:\path\to\runtime-settings.key", "some-id")

    with pytest.raises(ValueError, match="Custody reference violation"):
        verify_and_sign("some-input", "some-output", r"C:\path\to\wrong-key.pem", "some-id")

    repo_key = Path(__file__).resolve().parents[1] / "release-key.pem"
    monkeypatch.setenv("NEKO_RELEASE_KEY_REF", str(repo_key))
    with pytest.raises(ValueError, match="Custody reference violation"):
        verify_and_sign("some-input", "some-output", repo_key, "some-id")


def test_sign_software_release_default_key_reference_is_not_personal(monkeypatch, tmp_path):
    from scripts.sign_software_release import production_key_reference

    monkeypatch.delenv("NEKO_RELEASE_KEY_REF", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    reference = production_key_reference()

    assert "nekofamily" in reference.lower()
    assert "neko-update-prod-3.pem" in reference
    assert "pranmong" not in reference.lower().replace(str(tmp_path).lower(), "")
