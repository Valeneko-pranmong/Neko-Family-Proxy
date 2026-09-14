#!/usr/bin/env python3
"""Closed-schema read-only verifier for K1 acceptance JSON, digests, and Git history immutability."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads  # noqa: E402
from neko_launcher.updater.core_manifest_verifier import verify_canonical_core_bundle  # noqa: E402
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2  # noqa: E402
from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS  # noqa: E402
from neko_launcher.updater.trust_profile import verify_update_trust_profile  # noqa: E402
from neko_launcher.updater.zip_extractor import extract_core_bundle  # noqa: E402

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
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

_K1B_CLOSED_FIELDS = frozenset({
    "schema_version",
    "rt1_code_head_sha",
    "authorities",
    "profiles",
    "artifacts",
    "package_evidence",
    "proof_releases",
})

_RT1_SECURITY_PATHS = [
    "scripts/build_update_trust_profile.py",
    "scripts/assemble_release_v2_envelope.py",
    "scripts/verify_v512_k1_acceptance.py",
    "launcher/src/neko_launcher/updater/trust.py",
    "launcher/src/neko_launcher/updater/trust_profile.py",
]

_PROFILE_AUTHORITY_CUSTODY_PATH = Path("E:/Github/authority/v512-update-profile-authority/public-v1.json")
_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH = Path("E:/Github/authority/v512-proof-release-authority/public-v1.json")


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


def validate_k1b_custody_manifest_schema(raw_bytes: bytes) -> dict:
    if not raw_bytes.endswith(b"\n") or raw_bytes.endswith(b"\r\n") or raw_bytes.endswith(b"\n\n"):
        raise ValueError("Manifest must end with exactly one terminal LF without CRLF")

    body = raw_bytes[:-1]
    if body.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Manifest must not contain BOM")

    if body != body.strip(b" \t\r\n"):
        raise ValueError("Manifest must not have leading or trailing whitespace before LF")

    doc = canonical_json_loads(body)
    if canonical_json_dumps(doc) != body:
        raise ValueError("Manifest is not canonical UTF-8 JSON")

    if not isinstance(doc, dict):
        raise ValueError("Manifest must be a JSON object")

    if set(doc.keys()) != _K1B_CLOSED_FIELDS:
        missing = _K1B_CLOSED_FIELDS - set(doc.keys())
        extra = set(doc.keys()) - _K1B_CLOSED_FIELDS
        raise ValueError(f"K1B custody manifest closed fields violation: missing {missing}, extra {extra}")

    if doc["schema_version"] != 1:
        raise ValueError(f"Unsupported schema_version: {doc['schema_version']}")

    if not isinstance(doc["rt1_code_head_sha"], str) or not _HEX40_RE.fullmatch(doc["rt1_code_head_sha"]):
        raise ValueError(f"Invalid rt1_code_head_sha: {doc['rt1_code_head_sha']!r}")

    # Authorities validation
    auth = doc["authorities"]
    if not isinstance(auth, dict) or set(auth.keys()) != {"profile_authority", "proof_release_authority", "production"}:
        raise ValueError("Invalid authorities in K1B manifest")

    for key_name in ("profile_authority", "proof_release_authority"):
        item = auth[key_name]
        if not isinstance(item, dict) or set(item.keys()) != {"key_id", "public_key_sha256", "custody_file_sha256"}:
            raise ValueError(f"Invalid closed fields in authorities.{key_name}")
        if not isinstance(item["key_id"], str) or not _KEY_ID_RE.fullmatch(item["key_id"]):
            raise ValueError(f"Invalid key_id in authorities.{key_name}")
        if not isinstance(item["public_key_sha256"], str) or not _HEX64_RE.fullmatch(item["public_key_sha256"]):
            raise ValueError(f"Invalid public_key_sha256 in authorities.{key_name}")
        if not isinstance(item["custody_file_sha256"], str) or not _HEX64_RE.fullmatch(item["custody_file_sha256"]):
            raise ValueError(f"Invalid custody_file_sha256 in authorities.{key_name}")

    prod_auth = auth["production"]
    if not isinstance(prod_auth, dict) or set(prod_auth.keys()) != {"key_id", "public_key_sha256", "keyset_sha256"}:
        raise ValueError("Invalid closed fields in authorities.production")
    if not isinstance(prod_auth["key_id"], str) or not _KEY_ID_RE.fullmatch(prod_auth["key_id"]):
        raise ValueError("Invalid key_id in authorities.production")
    if not isinstance(prod_auth["public_key_sha256"], str) or not _HEX64_RE.fullmatch(prod_auth["public_key_sha256"]):
        raise ValueError("Invalid public_key_sha256 in authorities.production")
    if not isinstance(prod_auth["keyset_sha256"], str) or not _HEX64_RE.fullmatch(prod_auth["keyset_sha256"]):
        raise ValueError("Invalid keyset_sha256 in authorities.production")

    # Profiles validation
    profs = doc["profiles"]
    if not isinstance(profs, dict) or set(profs.keys()) != {"production", "proof"}:
        raise ValueError("Invalid profiles in K1B manifest")
    for prof_name in ("production", "proof"):
        item = profs[prof_name]
        if not isinstance(item, dict) or set(item.keys()) != {"path", "payload_sha256", "envelope_sha256", "keyset_sha256"}:
            raise ValueError(f"Invalid closed fields in profiles.{prof_name}")
        if not isinstance(item["path"], str) or not item["path"]:
            raise ValueError(f"Invalid path in profiles.{prof_name}")
        for k in ("payload_sha256", "envelope_sha256", "keyset_sha256"):
            if not isinstance(item[k], str) or not _HEX64_RE.fullmatch(item[k]):
                raise ValueError(f"Invalid {k} in profiles.{prof_name}")

    # Artifacts validation
    artifacts = doc["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts.keys()) != {"baseline", "candidate"}:
        raise ValueError("Invalid artifacts in K1B manifest")
    for rel_name in ("baseline", "candidate"):
        rel_artifacts = artifacts[rel_name]
        if not isinstance(rel_artifacts, dict) or set(rel_artifacts.keys()) != {"launcher", "updater", "core"}:
            raise ValueError(f"Invalid components in artifacts.{rel_name}")
        for comp_name in ("launcher", "updater", "core"):
            c = rel_artifacts[comp_name]
            expected_c_keys = {"path", "version", "artifact_id", "artifact_sha256", "artifact_size", "installed_identity_sha256", "artifact_format"}
            if not isinstance(c, dict) or set(c.keys()) != expected_c_keys:
                raise ValueError(f"Invalid closed fields in artifacts.{rel_name}.{comp_name}")
            if not isinstance(c["path"], str) or not c["path"]:
                raise ValueError(f"Invalid path in artifacts.{rel_name}.{comp_name}")
            if not isinstance(c["version"], str) or not c["version"]:
                raise ValueError(f"Invalid version in artifacts.{rel_name}.{comp_name}")
            if not isinstance(c["artifact_id"], str) or not c["artifact_id"]:
                raise ValueError(f"Invalid artifact_id in artifacts.{rel_name}.{comp_name}")
            if not isinstance(c["artifact_sha256"], str) or not _HEX64_RE.fullmatch(c["artifact_sha256"]):
                raise ValueError(f"Invalid artifact_sha256 in artifacts.{rel_name}.{comp_name}")
            if not isinstance(c["artifact_size"], int) or c["artifact_size"] < 0:
                raise ValueError(f"Invalid artifact_size in artifacts.{rel_name}.{comp_name}")
            if not isinstance(c["installed_identity_sha256"], str) or not _HEX64_RE.fullmatch(c["installed_identity_sha256"]):
                raise ValueError(f"Invalid installed_identity_sha256 in artifacts.{rel_name}.{comp_name}")
            if not isinstance(c["artifact_format"], str) or not c["artifact_format"]:
                raise ValueError(f"Invalid artifact_format in artifacts.{rel_name}.{comp_name}")

    # Package evidence validation
    pkg_ev = doc["package_evidence"]
    expected_pkg_keys = {"production_updater_sha256", "proof_updater_sha256", "updater_byte_identical", "baseline_components_sha256", "candidate_components_sha256"}
    if not isinstance(pkg_ev, dict) or set(pkg_ev.keys()) != expected_pkg_keys:
        raise ValueError("Invalid closed fields in package_evidence")
    for k in ("production_updater_sha256", "proof_updater_sha256", "baseline_components_sha256", "candidate_components_sha256"):
        if not isinstance(pkg_ev[k], str) or not _HEX64_RE.fullmatch(pkg_ev[k]):
            raise ValueError(f"Invalid {k} in package_evidence")
    if not isinstance(pkg_ev["updater_byte_identical"], bool):
        raise ValueError("Invalid updater_byte_identical in package_evidence")

    # Proof releases validation
    proof_rels = doc["proof_releases"]
    if not isinstance(proof_rels, dict) or set(proof_rels.keys()) != {"baseline", "candidate"}:
        raise ValueError("Invalid proof_releases in K1B manifest")
    for rel_name in ("baseline", "candidate"):
        r = proof_rels[rel_name]
        expected_r_keys = {"path", "release_sequence", "release_id", "payload_sha256", "envelope_sha256", "key_id"}
        if not isinstance(r, dict) or set(r.keys()) != expected_r_keys:
            raise ValueError(f"Invalid closed fields in proof_releases.{rel_name}")
        if not isinstance(r["path"], str) or not r["path"]:
            raise ValueError(f"Invalid path in proof_releases.{rel_name}")
        if not isinstance(r["release_sequence"], int) or r["release_sequence"] < 1:
            raise ValueError(f"Invalid release_sequence in proof_releases.{rel_name}")
        if not isinstance(r["release_id"], str) or not r["release_id"]:
            raise ValueError(f"Invalid release_id in proof_releases.{rel_name}")
        if not isinstance(r["payload_sha256"], str) or not _HEX64_RE.fullmatch(r["payload_sha256"]):
            raise ValueError(f"Invalid payload_sha256 in proof_releases.{rel_name}")
        if not isinstance(r["envelope_sha256"], str) or not _HEX64_RE.fullmatch(r["envelope_sha256"]):
            raise ValueError(f"Invalid envelope_sha256 in proof_releases.{rel_name}")
        if not isinstance(r["key_id"], str) or not _KEY_ID_RE.fullmatch(r["key_id"]):
            raise ValueError(f"Invalid key_id in proof_releases.{rel_name}")

    return doc


def _validate_authority_custody_file(path: Path) -> tuple[dict, bytes]:
    if not path.is_file():
        raise FileNotFoundError(f"Authority public custody file missing: {path}")
    raw = path.read_bytes()
    if not raw.endswith(b"\n") or raw.endswith(b"\r\n") or raw.endswith(b"\n\n"):
        raise ValueError(f"Authority custody {path} must end with exactly one terminal LF without CRLF")
    body = raw[:-1]
    if body.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"Authority custody {path} must not contain BOM")
    if body != body.strip(b" \t\r\n"):
        raise ValueError(f"Authority custody {path} must not have leading or trailing whitespace before LF")
    doc = canonical_json_loads(body)
    if canonical_json_dumps(doc) != body:
        raise ValueError(f"Authority custody {path} is not canonical UTF-8 JSON")
    if not isinstance(doc, dict) or set(doc.keys()) != {"schema_version", "key_id", "public_key_hex", "public_key_sha256"}:
        raise ValueError(f"Authority custody {path} closed fields violation")
    if doc["schema_version"] != 1:
        raise ValueError(f"Authority custody {path} schema_version != 1")
    if not isinstance(doc["key_id"], str) or not _KEY_ID_RE.fullmatch(doc["key_id"]):
        raise ValueError(f"Authority custody {path} invalid key_id: {doc['key_id']!r}")
    if not isinstance(doc["public_key_hex"], str) or not _HEX64_RE.fullmatch(doc["public_key_hex"]):
        raise ValueError(f"Authority custody {path} invalid public_key_hex: {doc['public_key_hex']!r}")
    expected_pk_sha = hashlib.sha256(bytes.fromhex(doc["public_key_hex"])).hexdigest()
    if doc["public_key_sha256"] != expected_pk_sha:
        raise ValueError(f"Authority custody {path} public_key_sha256 mismatch")
    return doc, raw


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
    # 1. Read and validate acceptance record
    if not acceptance_record_path.is_file():
        raise FileNotFoundError(f"Acceptance record missing: {acceptance_record_path}")
    raw_acceptance = acceptance_record_path.read_bytes()
    acceptance = validate_acceptance_record_schema(raw_acceptance)

    # Bind CLI evidence and k1b paths to acceptance record
    expected_evidence = (repo_root / acceptance["evidence_path"]).resolve()
    if evidence_path.resolve() != expected_evidence:
        raise ValueError(
            f"CLI evidence path binding mismatch: CLI gave {evidence_path.resolve()}, "
            f"acceptance record binds {expected_evidence}"
        )

    expected_k1b = Path(acceptance["k1b_custody_path"]).resolve()
    if k1b_custody_path.resolve() != expected_k1b:
        raise ValueError(
            f"CLI k1b custody path binding mismatch: CLI gave {k1b_custody_path.resolve()}, "
            f"acceptance record binds {expected_k1b}"
        )

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

    # 2. Validate k1b custody manifest schema
    k1b_doc = validate_k1b_custody_manifest_schema(k1b_bytes)

    if k1b_doc["rt1_code_head_sha"] != acceptance["rt1_code_head_sha"]:
        raise ValueError("K1B custody rt1_code_head_sha mismatch with acceptance record")

    # Verify rt1_code_head_sha exists in git repo
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{acceptance['rt1_code_head_sha']}^{{commit}}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            f"rt1_code_head_sha commit {acceptance['rt1_code_head_sha']} does not exist in repo"
        ) from exc

    # 3. Fixed K1A Public Authorities validation
    prof_custody_doc, prof_custody_raw = _validate_authority_custody_file(_PROFILE_AUTHORITY_CUSTODY_PATH)
    proof_custody_doc, proof_custody_raw = _validate_authority_custody_file(_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH)

    actual_prof_custody_sha = hashlib.sha256(prof_custody_raw).hexdigest()
    if actual_prof_custody_sha != acceptance["profile_authority_custody_sha256"]:
        raise ValueError("Profile authority custody file SHA256 mismatch with acceptance record")

    actual_proof_custody_sha = hashlib.sha256(proof_custody_raw).hexdigest()
    if actual_proof_custody_sha != acceptance["proof_release_authority_custody_sha256"]:
        raise ValueError("Proof release authority custody file SHA256 mismatch with acceptance record")

    # Match manifest authority entries
    authorities = k1b_doc["authorities"]
    prof_auth_info = authorities["profile_authority"]
    proof_rel_auth_info = authorities["proof_release_authority"]

    if prof_auth_info["key_id"] != prof_custody_doc["key_id"]:
        raise ValueError("Manifest profile_authority key_id mismatch with public custody")
    if prof_auth_info["public_key_sha256"] != prof_custody_doc["public_key_sha256"]:
        raise ValueError("Manifest profile_authority public_key_sha256 mismatch with public custody")
    if prof_auth_info["custody_file_sha256"] != acceptance["profile_authority_custody_sha256"]:
        raise ValueError("Manifest profile_authority custody_file_sha256 mismatch with acceptance record")

    if proof_rel_auth_info["key_id"] != proof_custody_doc["key_id"]:
        raise ValueError("Manifest proof_release_authority key_id mismatch with public custody")
    if proof_rel_auth_info["public_key_sha256"] != proof_custody_doc["public_key_sha256"]:
        raise ValueError("Manifest proof_release_authority public_key_sha256 mismatch with public custody")
    if proof_rel_auth_info["custody_file_sha256"] != acceptance["proof_release_authority_custody_sha256"]:
        raise ValueError("Manifest proof_release_authority custody_file_sha256 mismatch with acceptance record")

    # Validate production authority binding from trust.py
    if "neko-update-prod-1" not in PRODUCTION_RELEASE_PUBLIC_KEYS:
        raise ValueError("Production release key neko-update-prod-1 missing from trust.py")
    prod_pub_bytes = PRODUCTION_RELEASE_PUBLIC_KEYS["neko-update-prod-1"]
    prod_pub_sha256 = hashlib.sha256(prod_pub_bytes).hexdigest()
    prod_keyset = {
        "release_keys": [{"key_id": "neko-update-prod-1", "public_key_hex": prod_pub_bytes.hex()}]
    }
    prod_keyset_sha256 = hashlib.sha256(canonical_json_dumps(prod_keyset)).hexdigest()

    prod_auth_info = authorities["production"]
    if prod_auth_info["key_id"] != "neko-update-prod-1":
        raise ValueError("Manifest production authority key_id != 'neko-update-prod-1'")
    if prod_auth_info["public_key_sha256"] != prod_pub_sha256:
        raise ValueError("Manifest production authority public_key_sha256 mismatch")
    if prod_auth_info["keyset_sha256"] != prod_keyset_sha256:
        raise ValueError("Manifest production authority keyset_sha256 mismatch")

    # 4. Validate Profiles
    profile_authority_public_keys = {
        prof_custody_doc["key_id"]: bytes.fromhex(prof_custody_doc["public_key_hex"])
    }

    profiles = k1b_doc["profiles"]
    # Production profile
    prod_info = profiles["production"]
    prod_path = Path(prod_info["path"])
    if not prod_path.is_file():
        raise FileNotFoundError(f"Production profile file missing: {prod_path}")
    prod_raw = prod_path.read_bytes()
    if hashlib.sha256(prod_raw).hexdigest() != prod_info["envelope_sha256"]:
        raise ValueError("Production profile envelope_sha256 mismatch")

    prod_prof = verify_update_trust_profile(
        prod_raw,
        profile_authority_public_keys=profile_authority_public_keys,
    )
    if prod_prof.profile_id != "production" or prod_prof.channel != "stable":
        raise ValueError("Production profile routing mismatch")
    if prod_prof.owner != "Valeneko-pranmong" or prod_prof.repository != "Neko-Family-Proxy-Updates":
        raise ValueError("Production profile repository mismatch")
    if prod_prof.release_public_keys != {"neko-update-prod-1": prod_pub_bytes}:
        raise ValueError("Production profile release registry mismatch")
    if prod_prof.keyset_sha256 != prod_info["keyset_sha256"] or prod_prof.keyset_sha256 != prod_keyset_sha256:
        raise ValueError("Production profile keyset_sha256 mismatch")

    # Verify payload hash of production profile
    prod_env_obj = canonical_json_loads(prod_raw[:-1])
    prod_payload_bytes = canonical_json_dumps(prod_env_obj["payload"])
    if hashlib.sha256(prod_payload_bytes).hexdigest() != prod_info["payload_sha256"]:
        raise ValueError("Production profile payload_sha256 mismatch")

    # Proof profile
    proof_info = profiles["proof"]
    proof_path = Path(proof_info["path"])
    if not proof_path.is_file():
        raise FileNotFoundError(f"Proof profile file missing: {proof_path}")
    proof_raw = proof_path.read_bytes()
    if hashlib.sha256(proof_raw).hexdigest() != proof_info["envelope_sha256"]:
        raise ValueError("Proof profile envelope_sha256 mismatch")

    proof_prof = verify_update_trust_profile(
        proof_raw,
        profile_authority_public_keys=profile_authority_public_keys,
    )
    if proof_prof.profile_id != "proof-v512" or proof_prof.channel != "stable":
        raise ValueError("Proof profile routing mismatch")
    if proof_prof.owner != "Valeneko-pranmong" or proof_prof.repository != "Neko-Family-Proxy-Updates-Proof":
        raise ValueError("Proof profile repository mismatch")

    proof_rel_pub_bytes = bytes.fromhex(proof_custody_doc["public_key_hex"])
    if proof_prof.release_public_keys != {proof_custody_doc["key_id"]: proof_rel_pub_bytes}:
        raise ValueError("Proof profile release registry mismatch")
    if proof_prof.keyset_sha256 != proof_info["keyset_sha256"]:
        raise ValueError("Proof profile keyset_sha256 mismatch")

    proof_env_obj = canonical_json_loads(proof_raw[:-1])
    proof_payload_bytes = canonical_json_dumps(proof_env_obj["payload"])
    if hashlib.sha256(proof_payload_bytes).hexdigest() != proof_info["payload_sha256"]:
        raise ValueError("Proof profile payload_sha256 mismatch")

    # 5. Validate Proof Releases and Cross-Trust
    proof_releases = k1b_doc["proof_releases"]
    for rel_name in ("baseline", "candidate"):
        rel_info = proof_releases[rel_name]
        rel_path = Path(rel_info["path"])
        if not rel_path.is_file():
            raise FileNotFoundError(f"Proof release file missing: {rel_path}")
        rel_bytes = rel_path.read_bytes()
        if hashlib.sha256(rel_bytes).hexdigest() != rel_info["envelope_sha256"]:
            raise ValueError(f"Proof release {rel_name} envelope SHA256 mismatch")

        rel_doc = canonical_json_loads(rel_bytes.rstrip(b"\r\n"))

        # Cross-trust rejection: proof envelope MUST fail under production registry
        try:
            verify_release_envelope_v2(rel_doc, prod_prof.release_public_keys)
            raise ValueError(
                f"Cross-trust failure: proof release {rel_name} unexpectedly verified under production registry"
            )
        except ValueError as exc:
            if "Cross-trust failure" in str(exc):
                raise
            pass

        # Verify under proof profile registry
        release_set, returned_payload_sha = verify_release_envelope_v2(rel_doc, proof_prof.release_public_keys)
        if rel_doc["key_id"] != proof_custody_doc["key_id"]:
            raise ValueError(
                f"Proof release {rel_name} key_id mismatch: got {rel_doc['key_id']}, expected {proof_custody_doc['key_id']}"
            )
        if returned_payload_sha != rel_info["payload_sha256"]:
            raise ValueError(
                f"Proof release {rel_name} payload SHA mismatch: got {returned_payload_sha}, expected {rel_info['payload_sha256']}"
            )

        # Release schema contracts
        if release_set.schema_version != 2:
            raise ValueError(f"Proof release {rel_name} schema_version != 2")
        if release_set.channel != "stable":
            raise ValueError(f"Proof release {rel_name} channel != 'stable'")
        if release_set.updater_protocol.minimum != 1 or release_set.updater_protocol.maximum != 1:
            raise ValueError(f"Proof release {rel_name} updater_protocol must be 1..1")

        if rel_name == "baseline":
            if release_set.release_sequence != 1:
                raise ValueError(f"Baseline sequence must be 1, got {release_set.release_sequence}")
            if release_set.release_id != "proof-k1-0001":
                raise ValueError(f"Baseline release_id must be 'proof-k1-0001', got {release_set.release_id}")
            if release_set.mandatory is not False:
                raise ValueError(f"Baseline mandatory must be False, got {release_set.mandatory}")
            if release_set.minimum_supported_sequence != 1:
                raise ValueError(f"Baseline minimum_supported_sequence must be 1, got {release_set.minimum_supported_sequence}")
            for comp in ("launcher", "updater", "core"):
                if release_set.components[comp].version != "5.1.2":
                    raise ValueError(f"Baseline {comp} version must be '5.1.2', got {release_set.components[comp].version}")
        else:  # candidate
            if release_set.release_sequence != 2:
                raise ValueError(f"Candidate sequence must be 2, got {release_set.release_sequence}")
            if release_set.release_id != "proof-k1-0002":
                raise ValueError(f"Candidate release_id must be 'proof-k1-0002', got {release_set.release_id}")
            if release_set.mandatory is not True:
                raise ValueError(f"Candidate mandatory must be True, got {release_set.mandatory}")
            if release_set.minimum_supported_sequence != 2:
                raise ValueError(f"Candidate minimum_supported_sequence must be 2, got {release_set.minimum_supported_sequence}")
            if release_set.components["launcher"].version != "5.1.3-proof":
                raise ValueError(f"Candidate launcher version must be '5.1.3-proof', got {release_set.components['launcher'].version}")
            if release_set.components["core"].version != "5.1.3-proof":
                raise ValueError(f"Candidate core version must be '5.1.3-proof', got {release_set.components['core'].version}")
            if release_set.components["updater"].version != "5.1.2":
                raise ValueError(f"Candidate updater version must be '5.1.2', got {release_set.components['updater'].version}")

        # Canonical artifact IDs and formats
        if release_set.components["launcher"].artifact_id != "NekoLauncher.exe" or release_set.components["launcher"].artifact_format != "raw-pe-v1":
            raise ValueError(f"Proof release {rel_name} launcher artifact contract mismatch")
        if release_set.components["updater"].artifact_id != "NekoUpdater.exe" or release_set.components["updater"].artifact_format != "raw-pe-v1":
            raise ValueError(f"Proof release {rel_name} updater artifact contract mismatch")
        if release_set.components["core"].artifact_id != "NekoProxyCore.zip" or release_set.components["core"].artifact_format != "zip-core-v1":
            raise ValueError(f"Proof release {rel_name} core artifact contract mismatch")

        # Match signed components vs artifact records
        for comp in ("launcher", "updater", "core"):
            sc = release_set.components[comp]
            mc = k1b_doc["artifacts"][rel_name][comp]
            if (
                sc.version != mc["version"]
                or sc.artifact_id != mc["artifact_id"]
                or sc.artifact_sha256 != mc["artifact_sha256"]
                or sc.artifact_size != mc["artifact_size"]
                or sc.installed_identity_sha256 != mc["installed_identity_sha256"]
                or sc.artifact_format != mc["artifact_format"]
            ):
                raise ValueError(f"Signed component {comp} does not match artifact record in {rel_name}")

    # 6. Re-hash every baseline/candidate Launcher/Updater/Core artifact
    artifacts = k1b_doc["artifacts"]
    for rel_name in ("baseline", "candidate"):
        for comp_name in ("launcher", "updater", "core"):
            c_info = artifacts[rel_name][comp_name]
            p = Path(c_info["path"])
            if not p.is_file():
                raise FileNotFoundError(f"Artifact file missing: {p}")
            data = p.read_bytes()
            if len(data) != c_info["artifact_size"]:
                raise ValueError(f"Artifact {rel_name}.{comp_name} size mismatch: got {len(data)}, expected {c_info['artifact_size']}")
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != c_info["artifact_sha256"]:
                raise ValueError(f"Artifact {rel_name}.{comp_name} sha256 mismatch")

            if comp_name in ("launcher", "updater"):
                if c_info["installed_identity_sha256"] != actual_sha:
                    raise ValueError(f"Artifact {rel_name}.{comp_name} installed_identity_sha256 != artifact_sha256")
            elif comp_name == "core":
                with tempfile.TemporaryDirectory() as temp_dir_str:
                    temp_dir = Path(temp_dir_str)
                    try:
                        extract_core_bundle(p, temp_dir)
                    except Exception as exc:
                        raise ValueError(f"Core bundle extraction failed for {rel_name}: {exc}") from exc

                    res = verify_canonical_core_bundle(temp_dir)
                    if not res.valid:
                        raise ValueError(f"Core bundle verification failed for {rel_name}: {res.error}")

                    manifest_file = temp_dir / "core-manifest.json"
                    if not manifest_file.is_file():
                        raise ValueError(f"Core bundle missing core-manifest.json for {rel_name}")
                    actual_manifest_sha = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
                    if actual_manifest_sha != res.manifest_sha256:
                        raise ValueError(f"Core manifest SHA mismatch for {rel_name}")
                    if c_info["installed_identity_sha256"] != res.manifest_sha256:
                        raise ValueError(
                            f"Core installed_identity_sha256 mismatch for {rel_name}: "
                            f"got {c_info['installed_identity_sha256']}, expected {res.manifest_sha256}"
                        )

    # 7. Candidate Updater byte-identical to baseline Updater
    base_upd_bytes = Path(artifacts["baseline"]["updater"]["path"]).read_bytes()
    cand_upd_bytes = Path(artifacts["candidate"]["updater"]["path"]).read_bytes()
    if base_upd_bytes != cand_upd_bytes:
        raise ValueError("Candidate updater is not byte-identical to baseline updater")
    if not k1b_doc["package_evidence"]["updater_byte_identical"]:
        raise ValueError("package_evidence.updater_byte_identical must be True")
    upd_sha = hashlib.sha256(base_upd_bytes).hexdigest()
    if k1b_doc["package_evidence"]["proof_updater_sha256"] != upd_sha:
        raise ValueError("package_evidence.proof_updater_sha256 mismatch")
    if k1b_doc["package_evidence"]["production_updater_sha256"] != upd_sha:
        raise ValueError("package_evidence.production_updater_sha256 mismatch")

    # 8. Recompute package_evidence component digests
    for rel_name in ("baseline", "candidate"):
        comps = {}
        for comp_name in sorted(["core", "launcher", "updater"]):
            mc = artifacts[rel_name][comp_name]
            comps[comp_name] = {
                "artifact_format": mc["artifact_format"],
                "artifact_id": mc["artifact_id"],
                "artifact_sha256": mc["artifact_sha256"],
                "artifact_size": mc["artifact_size"],
                "installed_identity_sha256": mc["installed_identity_sha256"],
                "version": mc["version"],
            }
        expected_comp_sha = hashlib.sha256(canonical_json_dumps({"components": comps})).hexdigest()
        recorded_comp_sha = k1b_doc["package_evidence"][f"{rel_name}_components_sha256"]
        if recorded_comp_sha != expected_comp_sha:
            raise ValueError(
                f"Package evidence {rel_name}_components_sha256 mismatch: got {recorded_comp_sha}, expected {expected_comp_sha}"
            )

    # 9. Verify Git immutability if requested
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
