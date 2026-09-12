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
LEGACY_EMAIL_RECOVERY_PATTERNS = {
    "PASSWORD_RECOVERY": re.compile(r"\bPASSWORD_RECOVERY\b"),
    "Supabase recovery-code exchange": re.compile(r"\bexchangeCodeForSession\b"),
    "Supabase email reset sender": re.compile(r"\bresetPasswordForEmail\b"),
}
OBSOLETE_UPDATE_AUTHORITY_PATTERNS = {
    "obsolete distribution credential target": re.compile(
        r"NEKO-FAMILY/SoftwareUpdateDistribution/v1"
    ),
    "obsolete distribution authorization authority": re.compile(
        r"\bNekoDistribution\b"
    ),
    "obsolete artifact grant route": re.compile(
        r"/api/software-update/artifact-grant"
    ),
    "obsolete software update active release env": re.compile(
        r"\bSOFTWARE_UPDATE_ACTIVE_RELEASE_JSON\b"
    ),
    "obsolete software update manifest route": re.compile(
        r"/api/software-update/manifest"
    ),
    "obsolete Supabase software update bucket identity": re.compile(
        r"\bsoftware[-_]update(?:s)?[-_]bucket\b"
    ),
}
SOFTWARE_UPDATE_UNTRUSTED_SOURCE_PATTERNS = {
    "GitHub zipball source archive": re.compile(r"\bzipball_url\b"),
    "GitHub tarball source archive": re.compile(r"\btarball_url\b"),
    "GitHub source archive ref": re.compile(r"/archive/refs/"),
    "GitHub raw content endpoint": re.compile(r"\braw\.githubusercontent\.com\b"),
    "unsigned checksum file": re.compile(r"\bSHA256SUMS\.txt\b"),
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


def is_allowlisted_history_doc(relative: Path) -> bool:
    parts = relative.parts
    if len(parts) >= 2 and parts[0] == "docs" and parts[1] in {"archive", "superpowers"}:
        return True
    return False


def is_test_path(relative: Path) -> bool:
    return any(part in {"tests", "test"} for part in relative.parts)


def is_software_update_production_code(relative: Path) -> bool:
    if is_test_path(relative):
        return False
    parts = relative.parts
    if (
        len(parts) >= 3
        and parts[0] == "launcher"
        and parts[1] == "src"
        and parts[2] == "neko_launcher"
    ):
        return True
    if relative.as_posix() in {
        "scripts/verify_github_release_assets.py",
        "scripts/release_controller.py",
        ".github/workflows/release.yml",
    }:
        return True
    return False


def validate_software_update_authority(path: Path) -> list[str]:
    relative = path.relative_to(REPOSITORY_ROOT)
    if (
        is_allowlisted_history_doc(relative)
        or is_test_path(relative)
        or relative.as_posix() == "scripts/check_repository_safety.py"
    ):
        return []
    if path.suffix.lower() in {".ico", ".png", ".ttf"}:
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    errors: list[str] = []
    for label, pattern in OBSOLETE_UPDATE_AUTHORITY_PATTERNS.items():
        if label == "obsolete distribution authorization authority":
            if relative.as_posix() == "launcher/src/neko_launcher/updater/privacy_scanner.py":
                continue
        if pattern.search(content):
            errors.append(
                f"obsolete software update authority ({label}) found in tracked file: {relative}"
            )
    return errors


def validate_software_update_untrusted_sources(path: Path) -> list[str]:
    relative = path.relative_to(REPOSITORY_ROOT)
    if not is_software_update_production_code(relative):
        return []
    if path.suffix.lower() not in {".py", ".yml", ".yaml"}:
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    errors: list[str] = []
    for label, pattern in SOFTWARE_UPDATE_UNTRUSTED_SOURCE_PATTERNS.items():
        if pattern.search(content):
            errors.append(
                f"untrusted software update source ({label}) found in production code: {relative}"
            )
    return errors


def validate_repository_contracts() -> list[str]:
    errors: list[str] = []
    deployable_docs = REPOSITORY_ROOT / "docs"
    legacy_route = deployable_docs / "reset-password"
    if legacy_route.exists():
        errors.append(
            "deployable legacy email recovery directory is present: "
            "docs/reset-password"
        )

    vercel_config = deployable_docs / "vercel.json"
    if vercel_config.exists() and "/reset-password/" in vercel_config.read_text(
        encoding="utf-8"
    ):
        errors.append(
            "deployable legacy email recovery route is configured: docs/vercel.json"
        )

    for path in deployable_docs.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".html", ".js", ".json"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(REPOSITORY_ROOT)
        for label, pattern in LEGACY_EMAIL_RECOVERY_PATTERNS.items():
            if pattern.search(content):
                errors.append(
                    f"deployable legacy email recovery implementation ({label}): "
                    f"{relative}"
                )
    return errors


def main() -> int:
    errors: list[str] = []
    for path in repository_files():
        errors.extend(validate_path(path))
        errors.extend(validate_content(path))
        errors.extend(validate_software_update_authority(path))
        errors.extend(validate_software_update_untrusted_sources(path))
    errors.extend(validate_repository_contracts())
    if errors:
        print("Repository safety check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Repository safety check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
