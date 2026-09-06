import pytest

from neko_launcher.updater.privacy_scanner import (
    PrivacyViolationError,
    assert_clean_privacy,
    scan_for_sensitive_leakage,
)


def test_clean_text_passes() -> None:
    text = "Starting NekoLauncher version 5.1.0a3 with generation gen-001"
    assert scan_for_sensitive_leakage(text) == []
    assert_clean_privacy(text)


def test_detects_url_query_parameters() -> None:
    text = "Downloading artifact from https://storage.googleapis.com/bucket/file.zip?signature=secret123"
    findings = scan_for_sensitive_leakage(text)
    assert len(findings) > 0
    assert any("URL query" in f for f in findings)
    with pytest.raises(PrivacyViolationError):
        assert_clean_privacy(text)


def test_detects_authorization_headers() -> None:
    text = "Sending Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    findings = scan_for_sensitive_leakage(text)
    assert len(findings) > 0
    with pytest.raises(PrivacyViolationError):
        assert_clean_privacy(text)


def test_detects_private_key_markers() -> None:
    text = "-----BEGIN PRIVATE KEY-----\nMIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwdwIBAQQg"
    findings = scan_for_sensitive_leakage(text)
    assert len(findings) > 0
    with pytest.raises(PrivacyViolationError):
        assert_clean_privacy(text)
