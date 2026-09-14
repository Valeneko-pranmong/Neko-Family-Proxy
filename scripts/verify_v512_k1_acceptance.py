#!/usr/bin/env python3
"""Closed-schema read-only verifier for K1 acceptance JSON, digests, and Git history immutability."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads  # noqa: E402
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2  # noqa: E402
from neko_launcher.updater.trust_profile import verify_update_trust_profile  # noqa: E402

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

_ACCEPTANCE_CLOSED_FIELDS = frozenset({
    "schema_version",
    "task_id",
    "rt1_code_head_sha",
    "profile_authority_custody_sha256",
    "proof_release_authority_custody_sha256",
    "k1b_custody_path",
    "k1b_custody_sha256",
    "evidence_path",
    "evidence_sha256",
    "reviewer_model",
    "critical_count",
    "important_count",
    "reviewed_at",
})

_RT1_SECURITY_PATHS = [
    "scripts/build_update_trust_profile.py",
    "scripts/assemble_release_v2_envelope.py",
    "scripts/verify_v512_k1_acceptance.py",
    "launcher/src/neko_launcher/updater/trust.py",
    "launcher/src/neko_launcher/updater/trust_profile.py",
]


def validate_acceptance_record_schema(raw_bytes: bytes) -> dict:
    if not raw_bytes.endswith(b"\n") or raw_bytes.endswith(b"\r\n") or raw_bytes.endswith(b"\n\n"):
        raise ValueError("Acceptance record must end with exactly one terminal LF without CRLF")

    body = raw_bytes[:-1]
    if body.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Acceptance record must not contain BOM")

    if body != body.strip(b" \t\r\n"):
        raise ValueError("Acceptance record must not have leading or trailing whitespace before LF")

    doc = canonical_json_loads(body)
    if canonical_json_dumps(doc) != body:
        raise ValueError("Acceptance record is not canonical UTF-8 JSON")

    if not isinstance(doc, dict):
        raise ValueError("Acceptance record must be a JSON object")

    if set(doc.keys()) != _ACCEPTANCE_CLOSED_FIELDS:
        missing = _ACCEPTANCE_CLOSED_FIELDS - set(doc.keys())
        extra = set(doc.keys()) - _ACCEPTANCE_CLOSED_FIELDS
        raise ValueError(f"Acceptance record closed fields violation: missing {missing}, extra {extra}")

    if doc["schema_version"] != 1:
        raise ValueError(f"Unsupported schema_version: {doc['schema_version']}")

    if doc["task_id"] != "RT1-K1":
        raise ValueError(f"Invalid task_id: {doc['task_id']!r}")

    if not isinstance(doc["rt1_code_head_sha"], str) or not _HEX40_RE.fullmatch(doc["rt1_code_head_sha"]):
        raise ValueError(f"Invalid rt1_code_head_sha: {doc['rt1_code_head_sha']!r}")

    for hash_key in (
        "profile_authority_custody_sha256",
        "proof_release_authority_custody_sha256",
        "k1b_custody_sha256",
        "evidence_sha256",
    ):
        val = doc[hash_key]
        if not isinstance(val, str) or not _HEX64_RE.fullmatch(val):
            raise ValueError(f"Invalid {hash_key}: {val!r}")

    if doc["reviewer_model"] != "ag/gemini-pro-agent":
        raise ValueError(f"Invalid reviewer_model: {doc['reviewer_model']!r}")

    if doc["critical_count"] != 0 or doc["important_count"] != 0:
        raise ValueError("Acceptance requires critical_count == 0 and important_count == 0")

    if not isinstance(doc["reviewed_at"], str) or not _RFC3339_RE.fullmatch(doc["reviewed_at"]):
        raise ValueError(f"Invalid reviewed_at RFC3339 UTC timestamp: {doc['reviewed_at']!r}")

    return doc


def verify_git_immutability(repo_root: Path, acceptance_record_rel_path: str) -> str:
    # 1. Log commits for acceptance record
    p = acceptance_record_rel_path.replace("\\", "/")
    cs = subprocess.check_output(
        ["git", "log", "--format=%H", "--", p],
        cwd=repo_root,
        text=True,
    ).splitlines()

    if len(cs) != 1:
        raise ValueError(f"K1 acceptance record history is not single-introduction (found {len(cs)} commits)")

    intro_commit = cs[0]

    # 2. Check no unstaged or diff against introduction commit
    subprocess.run(
        ["git", "diff", "--exit-code", intro_commit, "--", p],
        cwd=repo_root,
        check=True,
    )

    # 3. Read rt1_code_head_sha from committed record
    committed_raw = subprocess.check_output(
        ["git", "show", f"{intro_commit}:{p}"],
        cwd=repo_root,
        text=True,
    )
    record = json.loads(committed_raw)
    h = record["rt1_code_head_sha"]

    # 4. Require h to be ancestor of HEAD
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", h, "HEAD"],
        cwd=repo_root,
        check=True,
    )

    # 5. Check no commits touched security paths between h and HEAD
    late = subprocess.check_output(
        ["git", "log", "--format=%H", f"{h}..HEAD", "--", *_RT1_SECURITY_PATHS],
        cwd=repo_root,
        text=True,
    ).splitlines()
    if late:
        raise ValueError("RT1 security paths changed after accepted RT1_CODE_HEAD")

    # 6. Check diff against h on security paths is clean
    subprocess.run(
        ["git", "diff", "--exit-code", h, "--", *_RT1_SECURITY_PATHS],
        cwd=repo_root,
        check=True,
    )

    return f"RT1_SECURITY_TOOL_GUARD_OK {intro_commit} {h}"


def verify_k1_acceptance(
    *,
    repo_root: Path,
    acceptance_record_path: Path,
    evidence_path: Path,
    k1b_custody_path: Path,
    require_git_immutability: bool = False,
) -> None:
    # Read and validate acceptance record
    raw_acceptance = acceptance_record_path.read_bytes()
    acceptance = validate_acceptance_record_schema(raw_acceptance)

    # Validate evidence hash
    if not evidence_path.is_file():
        raise FileNotFoundError(f"Evidence file missing: {evidence_path}")
    evidence_bytes = evidence_path.read_bytes()
    actual_evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
    if actual_evidence_sha != acceptance["evidence_sha256"]:
        raise ValueError(
            f"Evidence SHA256 mismatch: got {actual_evidence_sha}, expected {acceptance['evidence_sha256']}"
        )

    # Validate k1b custody manifest hash
    if not k1b_custody_path.is_file():
        raise FileNotFoundError(f"K1B custody manifest missing: {k1b_custody_path}")
    k1b_bytes = k1b_custody_path.read_bytes()
    actual_k1b_sha = hashlib.sha256(k1b_bytes).hexdigest()
    if actual_k1b_sha != acceptance["k1b_custody_sha256"]:
        raise ValueError(
            f"K1B custody manifest SHA256 mismatch: got {actual_k1b_sha}, expected {acceptance['k1b_custody_sha256']}"
        )

    # Validate k1b custody structure
    k1b_doc = canonical_json_loads(k1b_bytes)
    k1b_closed_keys = {"schema_version", "rt1_code_head_sha", "authorities", "profiles", "artifacts", "package_evidence", "proof_releases"}
    if set(k1b_doc.keys()) != k1b_closed_keys:
        raise ValueError(f"K1B custody manifest invalid keys: {set(k1b_doc.keys())}")

    if k1b_doc["schema_version"] != 1:
        raise ValueError(f"Unsupported K1B custody schema_version: {k1b_doc['schema_version']}")

    if k1b_doc["rt1_code_head_sha"] != acceptance["rt1_code_head_sha"]:
        raise ValueError("K1B custody rt1_code_head_sha mismatch with acceptance record")

    # Authorities validation
    authorities = k1b_doc["authorities"]
    prof_auth_info = authorities["profile_authority"]
    proof_rel_auth_info = authorities["proof_release_authority"]

    if prof_auth_info["custody_file_sha256"] != acceptance["profile_authority_custody_sha256"]:
        raise ValueError("Profile authority custody file SHA256 mismatch")
    if proof_rel_auth_info["custody_file_sha256"] != acceptance["proof_release_authority_custody_sha256"]:
        raise ValueError("Proof release authority custody file SHA256 mismatch")

    # Validate profiles
    profiles = k1b_doc["profiles"]
    # Verify production profile
    prod_info = profiles["production"]
    prod_raw = Path(prod_info["path"]).read_bytes()
    prod_prof = verify_update_trust_profile(
        prod_raw,
        profile_authority_public_keys={prof_auth_info["key_id"]: bytes.fromhex(prof_auth_info["public_key_hex"])},
    )
    if prod_prof.profile_id != "production" or prod_prof.channel != "stable":
        raise ValueError("Production profile routing mismatch")
    if prod_prof.owner != "Valeneko-pranmong" or prod_prof.repository != "Neko-Family-Proxy-Updates":
        raise ValueError("Production profile repository mismatch")

    # Verify proof profile
    proof_info = profiles["proof"]
    proof_raw = Path(proof_info["path"]).read_bytes()
    proof_prof = verify_update_trust_profile(
        proof_raw,
        profile_authority_public_keys={prof_auth_info["key_id"]: bytes.fromhex(prof_auth_info["public_key_hex"])},
    )
    if proof_prof.profile_id != "proof-v512" or proof_prof.channel != "stable":
        raise ValueError("Proof profile routing mismatch")
    if proof_prof.owner != "Valeneko-pranmong" or proof_prof.repository != "Neko-Family-Proxy-Updates-Proof":
        raise ValueError("Proof profile repository mismatch")

    # Verify proof releases
    proof_releases = k1b_doc["proof_releases"]
    for rel_name in ("baseline", "candidate"):
        rel_info = proof_releases[rel_name]
        rel_bytes = Path(rel_info["path"]).read_bytes()
        rel_doc = json.loads(rel_bytes.decode("utf-8"))
        release_set, returned_payload_sha = verify_release_envelope_v2(rel_doc, proof_prof.release_public_keys)
        if rel_doc["key_id"] != proof_rel_auth_info["key_id"]:
            raise ValueError(f"Proof release {rel_name} key_id mismatch")
        if returned_payload_sha != rel_info["payload_sha256"]:
            raise ValueError(f"Proof release {rel_name} payload SHA mismatch")

    # Verify candidate Updater byte-identical to baseline Updater
    artifacts = k1b_doc["artifacts"]
    base_upd_bytes = Path(artifacts["baseline"]["updater"]["path"]).read_bytes()
    cand_upd_bytes = Path(artifacts["candidate"]["updater"]["path"]).read_bytes()
    if base_upd_bytes != cand_upd_bytes:
        raise ValueError("Candidate updater is not byte-identical to baseline updater")

    # Verify Git immutability if requested
    if require_git_immutability:
        rel_acc_path = str(acceptance_record_path.resolve().relative_to(repo_root.resolve()))
        msg = verify_git_immutability(repo_root, rel_acc_path)
        print(msg)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Closed-schema read-only verifier for K1 acceptance JSON and Git immutability",
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Path to Git repository root")
    parser.add_argument("--acceptance-record", required=True, type=Path, help="Path to v512-k1-acceptance.json")
    parser.add_argument("--evidence", required=True, type=Path, help="Path to v512-updater-trust-feasibility.md")
    parser.add_argument("--k1b-custody", required=True, type=Path, help="Path to k1b-custody-v1.json")
    parser.add_argument("--require-git-immutability", action="store_true", help="Enforce Git single-introduction immutability guard")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        verify_k1_acceptance(
            repo_root=args.repo_root,
            acceptance_record_path=args.acceptance_record,
            evidence_path=args.evidence,
            k1b_custody_path=args.k1b_custody,
            require_git_immutability=args.require_git_immutability,
        )
        print("K1_ACCEPTANCE_VERIFIED_OK")
        return 0
    except Exception as exc:
        print(f"K1_ACCEPTANCE_VERIFICATION_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
