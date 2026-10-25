from __future__ import annotations

from pathlib import Path


RUNBOOK = Path(__file__).parents[1] / "docs" / "current" / "5.3.0-cutover-runbook.md"


def runbook_text() -> str:
    return RUNBOOK.read_text(encoding="utf-8").lower()


def test_cutover_runbook_keeps_critical_gates() -> None:
    text = runbook_text()

    assert "do not proceed if any item is open" in text
    assert "control room admin web auth" in text
    assert "account recovery api" in text
    assert "iscc" in text
    assert "session_id" in text
    assert "owner approves" in text


def test_cutover_runbook_preserves_no_transfer_and_rollback_rules() -> None:
    text = runbook_text()

    assert "do not transfer 5.1.6 days or unused coupons" in text
    assert "do not silently revoke paid days" in text
    assert "last active legacy term" in text
    assert "rollback window" in text
    assert "do not delete active legacy terms" in text
