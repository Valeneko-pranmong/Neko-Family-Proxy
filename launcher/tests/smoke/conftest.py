from __future__ import annotations

from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--candidate-dir",
        action="store",
        default=None,
        help="directory containing an explicitly selected packaged candidate",
    )


@pytest.fixture
def candidate_dir(request: pytest.FixtureRequest) -> Path:
    value = request.config.getoption("--candidate-dir")
    if value is None:
        pytest.skip("packaged smoke requires explicit --candidate-dir")
    candidate = Path(value).resolve()
    for name in ("NekoLauncher.exe", "NekoUpdater.exe"):
        assert (candidate / name).is_file(), f"candidate is missing required {name}: {candidate}"
    return candidate
