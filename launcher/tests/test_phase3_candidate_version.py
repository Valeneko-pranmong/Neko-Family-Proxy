from __future__ import annotations

import re
import tomllib
from pathlib import Path

import neko_launcher


EXPECTED_PRODUCT_VERSION = "5.2.0a1"


def test_phase3_product_tree_has_exact_alpha_identity() -> None:
    launcher_root = Path(__file__).resolve().parents[1]
    project = tomllib.loads(
        (launcher_root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["version"] == EXPECTED_PRODUCT_VERSION, (
        f"canonical launcher/pyproject.toml is not {EXPECTED_PRODUCT_VERSION}"
    )
    assert neko_launcher.__version__ == EXPECTED_PRODUCT_VERSION, (
        f"neko_launcher.__version__ is not {EXPECTED_PRODUCT_VERSION}"
    )


def test_product_version_is_declared_only_on_canonical_surfaces() -> None:
    launcher_root = Path(__file__).resolve().parents[1]
    declarations: list[str] = []
    escaped_version = re.escape(EXPECTED_PRODUCT_VERSION)
    patterns = {
        launcher_root / "pyproject.toml": re.compile(
            rf'^version\s*=\s*"{escaped_version}"$', re.MULTILINE
        ),
        launcher_root / "src" / "neko_launcher" / "__init__.py": re.compile(
            rf'^__version__\s*=\s*"{escaped_version}"$', re.MULTILINE
        ),
    }
    for path, pattern in patterns.items():
        if pattern.search(path.read_text(encoding="utf-8")):
            declarations.append(path.relative_to(launcher_root).as_posix())

    assert declarations == ["pyproject.toml", "src/neko_launcher/__init__.py"], (
        "production must declare "
        f"{EXPECTED_PRODUCT_VERSION} only in pyproject.toml and "
        "neko_launcher.__version__"
    )
