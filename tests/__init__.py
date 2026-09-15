from pathlib import Path

_launcher_tests_dir = str(Path(__file__).resolve().parents[1] / "launcher" / "tests")
if _launcher_tests_dir not in __path__:  # type: ignore[name-defined]
    __path__.append(_launcher_tests_dir)  # type: ignore[name-defined]
