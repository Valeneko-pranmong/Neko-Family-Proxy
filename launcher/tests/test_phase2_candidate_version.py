from __future__ import annotations

import tomllib
from pathlib import Path

import neko_launcher


EXPECTED_PHASE2_CANDIDATE_VERSION = "5.1.0a2"


def test_live_product_tree_has_advanced_beyond_phase2_candidate() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]

    assert project["version"] == neko_launcher.__version__
    assert project["version"] != EXPECTED_PHASE2_CANDIDATE_VERSION
    assert neko_launcher.__version__ != EXPECTED_PHASE2_CANDIDATE_VERSION
