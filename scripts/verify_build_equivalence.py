#!/usr/bin/env python3
"""Deterministic mechanical verifier for proof-vs-production build equivalence."""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from neko_launcher.updater.canonical_json import canonical_json_dumps  # noqa: E402
from neko_launcher.updater.trust import PROFILE_AUTHORITY_PUBLIC_KEYS  # noqa: E402
from neko_launcher.updater.trust_profile import verify_update_trust_profile  # noqa: E402

PROFILE_ALLOWLIST: tuple[str, ...] = ("trust/update-profile-v1.json",)

_FORBIDDEN_GLOB_CHARS = frozenset("*?[]")
_CODE_EXTENSIONS = frozenset({
    ".py",
    ".pyc",
    ".pyd",
    ".pyo",
    ".so",
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".ps1",
})


@dataclass(frozen=True)
class ContentInventoryEntry:
    logical_path: str
    sha256: str
    size: int
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "logical_path": self.logical_path,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class EquivalenceResult:
    equivalent: bool
    unexpected_differences: tuple[str, ...]
    updater_byte_identical: bool
    allowed_differences: tuple[str, ...] = ()
    production_inventory: tuple[ContentInventoryEntry, ...] = ()
    proof_inventory: tuple[ContentInventoryEntry, ...] = ()


def classify_path(logical_path: str) -> str:
    """Classify a relative logical path into a structural category."""
    norm = logical_path.replace("\\", "/").strip("/")
    low = norm.lower()
    if norm == "trust/update-profile-v1.json" or norm.startswith("trust/"):
        return "trust_profile"
    if low == "nekoupdater.exe" or low.endswith("/nekoupdater.exe"):
        return "updater"
    if low.endswith(".exe") or low.endswith(".dll"):
        return "executable"
    if low.endswith((".py", ".pyc", ".pyd", ".pyo", ".so")):
        return "code_module"
    if low.endswith("release-v2.json") or low.endswith("build-record.json") or low.endswith("manifest.json"):
        return "manifest"
    return "resource"


def validate_allowlist(
    allowlist: Iterable[str],
    *,
    strict_profile_only: bool = True,
) -> tuple[str, ...]:
    """
    Validate that allowlist contains only permitted relative resource paths.
    Rejects broad globs, directory wildcards, and code modules.
    """
    validated: list[str] = []
    for raw_entry in allowlist:
        if not isinstance(raw_entry, str) or not raw_entry.strip():
            raise ValueError(f"Allowlist entry must be a non-empty string: {raw_entry!r}")

        entry = raw_entry.strip()
        if any(char in _FORBIDDEN_GLOB_CHARS for char in entry):
            raise ValueError(f"Broad glob or wildcard pattern forbidden in allowlist: {entry!r}")

        if entry.endswith("/") or entry.endswith("\\") or entry.startswith("/") or entry.startswith("\\"):
            raise ValueError(f"Directory pattern forbidden in allowlist: {entry!r}")

        norm = entry.replace("\\", "/")
        parts = norm.split("/")
        if any(p in ("", ".", "..") for p in parts):
            raise ValueError(f"Invalid path traversal or empty component in allowlist: {entry!r}")

        low = norm.lower()
        if any(low.endswith(ext) for ext in _CODE_EXTENSIONS) or classify_path(norm) in {
            "code_module",
            "executable",
            "updater",
        }:
            raise ValueError(f"Code module or executable cannot be allowlisted: {entry!r}")

        if strict_profile_only and norm != "trust/update-profile-v1.json":
            raise ValueError(
                f"Unauthorized allowlist entry {entry!r}; "
                f"only 'trust/update-profile-v1.json' is permitted for proof/production build equivalence"
            )

        validated.append(norm)

    return tuple(sorted(set(validated)))


def build_inventory(root: Path | str) -> tuple[ContentInventoryEntry, ...]:
    """Scan root recursively and return deterministic sorted ContentInventoryEntry tuple."""
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {root_path}")

    entries: list[ContentInventoryEntry] = []
    for file_path in sorted(root_path.rglob("*")):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(root_path).as_posix()
        hasher = hashlib.sha256()
        with file_path.open("rb") as stream:
            while chunk := stream.read(65536):
                hasher.update(chunk)
        digest = hasher.hexdigest().lower()
        size = file_path.stat().st_size
        classification = classify_path(rel)
        entries.append(
            ContentInventoryEntry(
                logical_path=rel,
                sha256=digest,
                size=size,
                classification=classification,
            )
        )

    entries.sort(key=lambda e: e.logical_path)
    return tuple(entries)


def verify_profile_equivalence(
    prod_raw: bytes,
    proof_raw: bytes,
    *,
    profile_authority_public_keys: Mapping[str, bytes] | None = None,
) -> bool:
    """Verify that both raw profiles are authentic and share the exact same Profile Authority root."""
    keys = profile_authority_public_keys or PROFILE_AUTHORITY_PUBLIC_KEYS
    try:
        prod_verified = verify_update_trust_profile(
            prod_raw,
            profile_authority_public_keys=keys,
        )
        proof_verified = verify_update_trust_profile(
            proof_raw,
            profile_authority_public_keys=keys,
        )
    except Exception:
        return False

    if prod_verified.profile_authority_key_id != proof_verified.profile_authority_key_id:
        return False

    if (
        prod_verified.profile_authority_public_key_sha256
        != proof_verified.profile_authority_public_key_sha256
    ):
        return False

    return True


def compare_builds(
    production_root: Path | str,
    proof_root: Path | str,
    *,
    allowlist: Iterable[str] = PROFILE_ALLOWLIST,
    profile_authority_public_keys: Mapping[str, bytes] | None = None,
    require_updater: bool = True,
    strict_profile_only: bool = True,
) -> EquivalenceResult:
    """
    Compare production and proof build directories.
    Requires byte-identical content across all non-allowlisted files and byte-identical NekoUpdater.exe.
    """
    valid_allowlist = validate_allowlist(allowlist, strict_profile_only=strict_profile_only)
    allowlist_set = set(valid_allowlist)

    prod_path = Path(production_root)
    proof_path = Path(proof_root)

    prod_inventory = build_inventory(prod_path)
    proof_inventory = build_inventory(proof_path)

    prod_map = {e.logical_path: e for e in prod_inventory}
    proof_map = {e.logical_path: e for e in proof_inventory}

    unexpected_diffs: list[str] = []
    allowed_diffs: list[str] = []

    # Verify NekoUpdater.exe byte identity
    updater_logical = "NekoUpdater.exe"
    prod_updater = prod_map.get(updater_logical)
    proof_updater = proof_map.get(updater_logical)

    if prod_updater is not None and proof_updater is not None:
        updater_byte_identical = prod_updater.sha256 == proof_updater.sha256
    else:
        if require_updater:
            updater_byte_identical = False
        else:
            updater_byte_identical = True

    all_paths = sorted(set(prod_map.keys()) | set(proof_map.keys()))
    for path in all_paths:
        in_prod = path in prod_map
        in_proof = path in proof_map

        if not in_prod or not in_proof:
            unexpected_diffs.append(path)
            continue

        prod_entry = prod_map[path]
        proof_entry = proof_map[path]

        if prod_entry.sha256 == proof_entry.sha256:
            continue

        if path in allowlist_set:
            if path == "trust/update-profile-v1.json":
                prod_bytes = (prod_path / path).read_bytes()
                proof_bytes = (proof_path / path).read_bytes()
                if verify_profile_equivalence(
                    prod_bytes,
                    proof_bytes,
                    profile_authority_public_keys=profile_authority_public_keys,
                ):
                    allowed_diffs.append(path)
                else:
                    unexpected_diffs.append(path)
            else:
                allowed_diffs.append(path)
        else:
            unexpected_diffs.append(path)

    equivalent = len(unexpected_diffs) == 0 and updater_byte_identical

    return EquivalenceResult(
        equivalent=equivalent,
        unexpected_differences=tuple(unexpected_diffs),
        updater_byte_identical=updater_byte_identical,
        allowed_differences=tuple(allowed_diffs),
        production_inventory=prod_inventory,
        proof_inventory=proof_inventory,
    )


def generate_equivalence_evidence(
    result: EquivalenceResult,
    *,
    production_root: Path | str | None = None,
    proof_root: Path | str | None = None,
) -> dict[str, Any]:
    """Generate deterministic dictionary evidence conforming to release authority contract."""
    evidence: dict[str, Any] = {
        "allowed_differences": list(result.allowed_differences),
        "equivalent": result.equivalent,
        "production_inventory": [e.to_dict() for e in result.production_inventory],
        "proof_inventory": [e.to_dict() for e in result.proof_inventory],
        "schema_version": 1,
        "unexpected_differences": list(result.unexpected_differences),
        "updater_byte_identical": result.updater_byte_identical,
    }
    if production_root is not None:
        evidence["production_root"] = str(production_root)
    if proof_root is not None:
        evidence["proof_root"] = str(proof_root)
    return evidence


def emit_canonical_evidence_json(
    result: EquivalenceResult,
    out_path: Path | str,
    *,
    production_root: Path | str | None = None,
    proof_root: Path | str | None = None,
) -> bytes:
    """Serialize and write canonical JSON evidence ending in exactly one LF."""
    evidence_dict = generate_equivalence_evidence(
        result,
        production_root=production_root,
        proof_root=proof_root,
    )
    raw = canonical_json_dumps(evidence_dict) + b"\n"
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify proof/production build equivalence for Neko Family Proxy v5.1.2."
    )
    parser.add_argument(
        "--production-dir",
        "--prod-dir",
        required=True,
        type=Path,
        help="Path to production build directory.",
    )
    parser.add_argument(
        "--proof-dir",
        required=True,
        type=Path,
        help="Path to proof build directory.",
    )
    parser.add_argument(
        "--allowlist",
        action="append",
        default=None,
        help="Allowlist relative resource (default: trust/update-profile-v1.json).",
    )
    parser.add_argument(
        "--evidence-out",
        type=Path,
        default=None,
        help="Optional path to emit canonical JSON evidence.",
    )
    parser.add_argument(
        "--allow-missing-updater",
        action="store_true",
        help="Do not fail if NekoUpdater.exe is absent.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    allowlist = args.allowlist or PROFILE_ALLOWLIST
    try:
        result = compare_builds(
            production_root=args.production_dir,
            proof_root=args.proof_dir,
            allowlist=allowlist,
            require_updater=not args.allow_missing_updater,
        )
    except Exception as exc:
        print(f"ERROR: Equivalence check failed with exception: {exc}", file=sys.stderr)
        return 2

    if args.evidence_out is not None:
        emit_canonical_evidence_json(
            result,
            args.evidence_out,
            production_root=args.production_dir,
            proof_root=args.proof_dir,
        )
        print(f"Evidence written to {args.evidence_out}")

    print(f"EQUIVALENT: {result.equivalent}")
    print(f"UPDATER_BYTE_IDENTICAL: {result.updater_byte_identical}")
    print(f"ALLOWED_DIFFERENCES: {list(result.allowed_differences)}")
    print(f"UNEXPECTED_DIFFERENCES: {list(result.unexpected_differences)}")

    return 0 if result.equivalent else 1


if __name__ == "__main__":
    sys.exit(main())
