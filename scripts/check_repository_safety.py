from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BLOCKED_DIRECTORY_NAMES = {
    ".next",
    ".venv",
    "__pycache__",
    "node_modules",
    "proxycore",
}
BLOCKED_SUFFIXES = {
    ".dll",
    ".env",
    ".exe",
    ".pfx",
    ".p12",
    ".pem",
    ".rar",
}
SECRET_PATTERNS = {
    "Supabase secret key": re.compile(r"\bsb_secret_[A-Za-z0-9_-]{16,}\b"),
    "Supabase service-role JWT": re.compile(
        r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"
    ),
}


def repository_files() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    return [
        REPOSITORY_ROOT / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    ]


def validate_path(path: Path) -> list[str]:
    relative = path.relative_to(REPOSITORY_ROOT)
    errors: list[str] = []
    lowered_parts = {part.lower() for part in relative.parts}
    if lowered_parts & BLOCKED_DIRECTORY_NAMES:
        errors.append(f"blocked generated/runtime directory is tracked: {relative}")
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        if path.name not in {".env.example"}:
            errors.append(f"blocked binary/secret file is tracked: {relative}")
    return errors


def validate_content(path: Path) -> list[str]:
    if path.suffix.lower() in {".ico", ".png"}:
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    relative = path.relative_to(REPOSITORY_ROOT)
    return [
        f"{label} found in tracked file: {relative}"
        for label, pattern in SECRET_PATTERNS.items()
        if pattern.search(content)
    ]


def main() -> int:
    errors: list[str] = []
    for path in repository_files():
        errors.extend(validate_path(path))
        errors.extend(validate_content(path))
    if errors:
        print("Repository safety check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Repository safety check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
