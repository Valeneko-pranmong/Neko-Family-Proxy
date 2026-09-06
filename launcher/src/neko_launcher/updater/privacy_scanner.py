"""Diagnostic, log, and process command-line privacy scanner."""
from __future__ import annotations

import re

_URL_QUERY_RE = re.compile(r"https?://[^\s\"'>]+\?[^\s\"'>]+")
_AUTH_HEADER_RE = re.compile(
    r"(?i)(Authorization:\s*(Bearer|NekoDistribution)\s+[^\s]+|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)
_KEY_MARKER_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_SECRET_TOKEN_RE = re.compile(r"(SENTINEL_[A-Z0-9_]*TOKEN|PRIVATE_KEY)")


class PrivacyViolationError(ValueError):
    """Raised when sensitive credentials, tokens, or query strings are detected."""


def scan_for_sensitive_leakage(text: str) -> list[str]:
    """Scan text for credentials, private keys, authorization tokens, or query strings."""
    findings: list[str] = []

    if _URL_QUERY_RE.search(text):
        findings.append("Found URL query parameter which may leak signed credentials")
    if _AUTH_HEADER_RE.search(text):
        findings.append("Found authorization header or JWT token")
    if _KEY_MARKER_RE.search(text):
        findings.append("Found private key header marker")
    if _SECRET_TOKEN_RE.search(text):
        findings.append("Found synthetic secret token marker")

    return findings


def assert_clean_privacy(text: str) -> None:
    """Assert that text contains zero sensitive tokens, keys, or query parameters."""
    findings = scan_for_sensitive_leakage(text)
    if findings:
        raise PrivacyViolationError(f"Privacy scan failed: {', '.join(findings)}")
