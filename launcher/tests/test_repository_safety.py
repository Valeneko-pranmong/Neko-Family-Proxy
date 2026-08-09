from __future__ import annotations

import importlib.util
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
SAFETY_SCRIPT = REPOSITORY_ROOT / "scripts" / "check_repository_safety.py"


def load_safety_module():
    spec = importlib.util.spec_from_file_location("check_repository_safety", SAFETY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deployable_legacy_email_recovery_is_rejected() -> None:
    safety = load_safety_module()

    errors = safety.validate_repository_contracts()

    assert not any("legacy email recovery" in error for error in errors)