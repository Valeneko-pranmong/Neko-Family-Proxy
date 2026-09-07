from __future__ import annotations

import re
import tomllib
from pathlib import Path

import neko_launcher


EXPECTED_PHASE3_CANDIDATE_VERSION = "5.1.0a3"


def test_phase3_product_tree_has_exact_candidate_identity() -> None:
    launcher_root = Path(__file__).resolve().parents[1]
    project = tomllib.loads(
        (launcher_root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["version"] == EXPECTED_PHASE3_CANDIDATE_VERSION, (
        "canonical launcher/pyproject.toml is not the a3 release candidate"
    )
    assert neko_launcher.__version__ == EXPECTED_PHASE3_CANDIDATE_VERSION, (
        "neko_launcher.__version__ is not the a3 release candidate"
    )


def test_phase3_version_is_declared_only_on_canonical_surfaces() -> None:
    launcher_root = Path(__file__).resolve().parents[1]
    declarations: list[str] = []
    patterns = {
        launcher_root / "pyproject.toml": re.compile(r'^version\s*=\s*"5\.1\.0a3"$', re.MULTILINE),
        launcher_root / "src" / "neko_launcher" / "__init__.py": re.compile(
            r'^__version__\s*=\s*"5\.1\.0a3"$', re.MULTILINE
        ),
    }
    for path, pattern in patterns.items():
        if pattern.search(path.read_text(encoding="utf-8")):
            declarations.append(path.relative_to(launcher_root).as_posix())

    assert declarations == ["pyproject.toml", "src/neko_launcher/__init__.py"], (
        "production must declare a3 only in pyproject.toml and neko_launcher.__version__"
    )
