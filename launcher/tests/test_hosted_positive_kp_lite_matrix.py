from __future__ import annotations

from pathlib import Path


HARNESS = (
    Path(__file__).parents[1]
    / "src"
    / "neko_launcher"
    / "e2e"
    / "hosted_positive_kp.py"
)


def test_lite_kp_matrix_excludes_retired_s0_configuration_binding_cases() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert "KP-2: Wrong Target PID" not in source
    assert "KP-3: Wrong Configuration" not in source
    assert 'evidence["kp_executions"] == 3' not in source
    assert 'evidence["same_permit_new_challenge_denied"] = "PASS"' in source
    assert 'evidence["tampered_permit_denied"] = "PASS"' in source
    assert 'evidence["expired_permit_denied"] = "PASS"' in source
