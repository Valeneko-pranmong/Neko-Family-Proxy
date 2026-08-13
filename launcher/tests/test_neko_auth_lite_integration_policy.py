from __future__ import annotations

from pathlib import Path


INTEGRATION_TEST = Path(__file__).parent / "integration" / "test_supabase_e2e.py"


def test_live_supabase_suite_asserts_first_active_session_wins() -> None:
    source = INTEGRATION_TEST.read_text(encoding="utf-8")

    assert "SessionAlreadyActive" in source
    assert "test_fresh_active_session_blocks_later_claim_end_to_end" in source
    assert 'outcomes.count("SUCCESS") == 1' in source
    assert 'outcomes.count("SESSION_ALREADY_ACTIVE") == 1' in source
