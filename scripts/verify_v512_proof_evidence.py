#!/usr/bin/env python3
"""Closed-schema read-only verifier for RA9 v5.1.2 proof evidence, authority bindings, and Git immutability."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from neko_launcher.updater.canonical_json import (  # noqa: E402
    canonical_json_dumps,
    canonical_json_loads,
)
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2  # noqa: E402

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

_EVIDENCE_CLOSED_FIELDS = frozenset({
    "schema_version",
    "source_sha",
    "k1b_custody_sha256",
    "trust_profiles",
    "release_authorities",
    "baseline_updater_sha256",
    "updater_byte_identical",
    "component_identities",
    "proof_releases",
    "scenarios",
    "final_bindings",
})

_ACCEPTANCE_CLOSED_FIELDS = frozenset({
    "schema_version",
    "task_id",
    "ra9_code_head_sha",
    "proof_custody_path",
    "proof_evidence_sha256",
    "reviewer_model",
    "critical_count",
    "important_count",
    "reviewed_at",
})

_K1_ACCEPTANCE_CLOSED_FIELDS = frozenset({
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

_RA9_CLOSED_PATHS = (
    "scripts/verify_v512_proof_evidence.py",
    "launcher/tests/e2e/test_v512_to_v513_proof_e2e.py",
    "launcher/tests/test_verify_v512_proof_evidence.py",
)

_COMPONENT_NAMES = ("launcher", "updater", "core")
_COMPONENT_CLOSED_FIELDS = frozenset({
    "version",
    "artifact_id",
    "artifact_sha256",
    "artifact_size",
    "installed_identity_sha256",
    "artifact_format",
})
_TRUST_PROFILE_CLOSED_FIELDS = frozenset({
    "profile_id",
    "profile_authority_key_id",
    "profile_authority_public_key_sha256",
    "profile_envelope_sha256",
    "keyset_sha256",
})
_RELEASE_AUTHORITY_CLOSED_FIELDS = frozenset({
    "key_id",
    "public_key_hex",
    "public_key_sha256",
})
_PROOF_RELEASE_CLOSED_FIELDS = frozenset({
    "role",
    "release_sequence",
    "release_id",
    "payload_sha256",
    "envelope_sha256",
    "key_id",
    "envelope_b64",
})
_SCENARIO_CLOSED_FIELDS = frozenset({
    "scenario_id",
    "result",
    "diagnostic_code",
    "before",
    "after",
    "release_envelope_sha256s",
    "evidence_sha256",
})
_AUTHORITY_STATE_CLOSED_FIELDS = frozenset({
    "committed",
    "high_water",
    "observed",
    "failed",
    "pending_release_sequence",
})
_BINDING_CLOSED_FIELDS = frozenset({
    "release_sequence",
    "release_id",
    "payload_sha256",
})


def _validate_raw_canonical_json(raw_bytes: bytes, desc: str) -> dict[str, Any]:
    if not raw_bytes.endswith(b"\n") or raw_bytes.endswith(b"\r\n") or raw_bytes.endswith(b"\n\n"):
        raise ValueError(f"{desc} must end with exactly one terminal LF without CRLF")

    body = raw_bytes[:-1]
    if body.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{desc} must not contain BOM")

    if body != body.strip(b" \t\r\n"):
        raise ValueError(f"{desc} must not have leading or trailing whitespace before LF")

    doc = canonical_json_loads(body)
    if canonical_json_dumps(doc) != body:
        raise ValueError(f"{desc} is not canonical UTF-8 JSON")

    if not isinstance(doc, dict):
        raise ValueError(f"{desc} must be a JSON object")

    return doc


def validate_k1_acceptance_record(raw_bytes: bytes) -> dict[str, Any]:
    doc = _validate_raw_canonical_json(raw_bytes, "K1 acceptance record")
    if set(doc.keys()) != _K1_ACCEPTANCE_CLOSED_FIELDS:
        missing = _K1_ACCEPTANCE_CLOSED_FIELDS - set(doc.keys())
        extra = set(doc.keys()) - _K1_ACCEPTANCE_CLOSED_FIELDS
        raise ValueError(f"K1 acceptance record closed fields violation: missing {missing}, extra {extra}")

    if doc["schema_version"] != 1 or doc["task_id"] != "RT1-K1":
        raise ValueError("Invalid K1 acceptance record schema_version or task_id")

    for k in ("profile_authority_custody_sha256", "proof_release_authority_custody_sha256", "k1b_custody_sha256", "evidence_sha256"):
        if not isinstance(doc[k], str) or not _HEX64_RE.fullmatch(doc[k]):
            raise ValueError(f"Invalid {k} in K1 acceptance record")

    if doc["critical_count"] != 0 or doc["important_count"] != 0:
        raise ValueError("K1 acceptance requires critical_count == 0 and important_count == 0")

    return doc


def validate_ra9_acceptance_record(raw_bytes: bytes) -> dict[str, Any]:
    doc = _validate_raw_canonical_json(raw_bytes, "RA9 acceptance record")
    if set(doc.keys()) != _ACCEPTANCE_CLOSED_FIELDS:
        missing = _ACCEPTANCE_CLOSED_FIELDS - set(doc.keys())
        extra = set(doc.keys()) - _ACCEPTANCE_CLOSED_FIELDS
        raise ValueError(f"RA9 acceptance record closed fields violation: missing {missing}, extra {extra}")

    if doc["schema_version"] != 1:
        raise ValueError(f"Unsupported RA9 acceptance schema_version: {doc['schema_version']}")
    if doc["task_id"] != "RA9":
        raise ValueError(f"Invalid task_id in RA9 acceptance record: {doc['task_id']!r}")

    if not isinstance(doc["ra9_code_head_sha"], str) or not _HEX40_RE.fullmatch(doc["ra9_code_head_sha"]):
        raise ValueError(f"Invalid ra9_code_head_sha: {doc['ra9_code_head_sha']!r}")

    if not isinstance(doc["proof_evidence_sha256"], str) or not _HEX64_RE.fullmatch(doc["proof_evidence_sha256"]):
        raise ValueError(f"Invalid proof_evidence_sha256: {doc['proof_evidence_sha256']!r}")

    if not isinstance(doc["proof_custody_path"], str) or not doc["proof_custody_path"]:
        raise ValueError("Empty proof_custody_path in RA9 acceptance record")

    if doc["reviewer_model"] != "ag/gemini-pro-agent":
        raise ValueError(f"Invalid reviewer_model: {doc['reviewer_model']!r}")

    if doc["critical_count"] != 0 or doc["important_count"] != 0:
        raise ValueError("RA9 acceptance requires critical_count == 0 and important_count == 0")

    if not isinstance(doc["reviewed_at"], str) or not _RFC3339_RE.fullmatch(doc["reviewed_at"]):
        raise ValueError(f"Invalid reviewed_at timestamp: {doc['reviewed_at']!r}")

    return doc


def verify_ra9_acceptance_git_immutability(repo_root: Path, acceptance_record_path: Path, code_head_sha: str) -> None:
    try:
        rel_acc = acceptance_record_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        rel_acc = acceptance_record_path

    rel_str = rel_acc.as_posix()
    cs = subprocess.check_output(["git", "log", "--format=%H", "--", rel_str], cwd=repo_root, text=True).splitlines()
    if len(cs) != 1:
        raise ValueError(f"RA9 acceptance record history is not single-introduction (found {len(cs)} commits)")

    intro_commit = cs[0]
    subprocess.run(["git", "diff", "--exit-code", intro_commit, "--", rel_str], cwd=repo_root, check=True)

    ancestor_res = subprocess.run(["git", "merge-base", "--is-ancestor", code_head_sha, "HEAD"], cwd=repo_root)
    if ancestor_res.returncode != 0:
        raise ValueError(f"ra9_code_head_sha {code_head_sha} is not an ancestor of HEAD")

    late = subprocess.check_output(["git", "log", "--format=%H", f"{code_head_sha}..HEAD", "--", *_RA9_CLOSED_PATHS], cwd=repo_root, text=True).splitlines()
    if late:
        raise ValueError("RA9 evidence paths changed after accepted RA9_CODE_HEAD")

    subprocess.run(["git", "diff", "--exit-code", code_head_sha, "--", *_RA9_CLOSED_PATHS], cwd=repo_root, check=True)


def _validate_binding(b: Any, field_name: str, valid_bindings: set[tuple[int, str, str]] | None = None) -> tuple[int, str, str]:
    if not isinstance(b, dict):
        raise ValueError(f"{field_name} must be an object")
    if set(b.keys()) != _BINDING_CLOSED_FIELDS:
        missing = _BINDING_CLOSED_FIELDS - set(b.keys())
        extra = set(b.keys()) - _BINDING_CLOSED_FIELDS
        raise ValueError(f"{field_name} closed fields violation: missing {missing}, extra {extra}")

    seq = b["release_sequence"]
    rel_id = b["release_id"]
    sha = b["payload_sha256"]

    if not isinstance(seq, int) or seq < 1:
        raise ValueError(f"{field_name}.release_sequence must be int >= 1")
    if not isinstance(rel_id, str) or not _RELEASE_ID_RE.fullmatch(rel_id):
        raise ValueError(f"Invalid {field_name}.release_id: {rel_id!r}")
    if not isinstance(sha, str) or not _HEX64_RE.fullmatch(sha):
        raise ValueError(f"Invalid {field_name}.payload_sha256: {sha!r}")

    triple = (seq, rel_id, sha)
    if valid_bindings is not None and triple not in valid_bindings:
        raise ValueError(f"{field_name} binding {triple} does not match any verified proof release")

    return triple


def _validate_authority_state(
    state: Any,
    field_name: str,
    valid_bindings: set[tuple[int, str, str]],
    valid_sequences: set[int],
) -> None:
    if not isinstance(state, dict):
        raise ValueError(f"{field_name} must be an object")
    if set(state.keys()) != _AUTHORITY_STATE_CLOSED_FIELDS:
        missing = _AUTHORITY_STATE_CLOSED_FIELDS - set(state.keys())
        extra = set(state.keys()) - _AUTHORITY_STATE_CLOSED_FIELDS
        raise ValueError(f"{field_name} closed fields violation: missing {missing}, extra {extra}")

    comm = _validate_binding(state["committed"], f"{field_name}.committed", valid_bindings)
    hw = _validate_binding(state["high_water"], f"{field_name}.high_water", valid_bindings)
    obs = _validate_binding(state["observed"], f"{field_name}.observed", valid_bindings)

    if comm[0] > hw[0]:
        raise ValueError(f"{field_name}: committed sequence cannot exceed high_water sequence")
    if obs[0] > hw[0]:
        raise ValueError(f"{field_name}: observed sequence cannot exceed high_water sequence")

    if state["failed"] is not None:
        _validate_binding(state["failed"], f"{field_name}.failed", valid_bindings)

    pending_seq = state["pending_release_sequence"]
    if pending_seq is not None:
        if not isinstance(pending_seq, int) or pending_seq < 1:
            raise ValueError(f"{field_name}.pending_release_sequence must be int >= 1 or null")
        if pending_seq not in valid_sequences:
            raise ValueError(f"{field_name}.pending_release_sequence {pending_seq} absent from proof releases")


def _validate_component_set(cset: Any, set_name: str) -> None:
    if not isinstance(cset, dict):
        raise ValueError(f"{set_name} must be an object")
    if set(cset.keys()) != set(_COMPONENT_NAMES):
        missing = set(_COMPONENT_NAMES) - set(cset.keys())
        extra = set(cset.keys()) - set(_COMPONENT_NAMES)
        raise ValueError(f"{set_name} components violation: missing {missing}, extra {extra}")

    for comp_name, comp_data in cset.items():
        field_prefix = f"{set_name}.{comp_name}"
        if not isinstance(comp_data, dict):
            raise ValueError(f"{field_prefix} must be an object")
        if set(comp_data.keys()) != _COMPONENT_CLOSED_FIELDS:
            missing = _COMPONENT_CLOSED_FIELDS - set(comp_data.keys())
            extra = set(comp_data.keys()) - _COMPONENT_CLOSED_FIELDS
            raise ValueError(f"{field_prefix} closed fields violation: missing {missing}, extra {extra}")

        ver = comp_data["version"]
        art_id = comp_data["artifact_id"]
        art_sha = comp_data["artifact_sha256"]
        art_size = comp_data["artifact_size"]
        inst_sha = comp_data["installed_identity_sha256"]
        art_fmt = comp_data["artifact_format"]

        if not isinstance(ver, str) or not ver:
            raise ValueError(f"Empty {field_prefix}.version")
        if not isinstance(art_sha, str) or not _HEX64_RE.fullmatch(art_sha):
            raise ValueError(f"Invalid {field_prefix}.artifact_sha256: {art_sha!r}")
        if not isinstance(inst_sha, str) or not _HEX64_RE.fullmatch(inst_sha):
            raise ValueError(f"Invalid {field_prefix}.installed_identity_sha256: {inst_sha!r}")
        if not isinstance(art_size, int) or art_size <= 0:
            raise ValueError(f"{field_prefix}.artifact_size must be int > 0")

        if comp_name == "launcher":
            if art_id != "NekoLauncher.exe":
                raise ValueError(f"Invalid launcher artifact_id: {art_id!r}")
            if art_fmt != "raw-pe-v1":
                raise ValueError(f"Invalid launcher artifact_format: {art_fmt!r}")
            if inst_sha != art_sha:
                raise ValueError("Launcher artifact_sha256 must equal installed_identity_sha256")
        elif comp_name == "updater":
            if art_id != "NekoUpdater.exe":
                raise ValueError(f"Invalid updater artifact_id: {art_id!r}")
            if art_fmt != "raw-pe-v1":
                raise ValueError(f"Invalid updater artifact_format: {art_fmt!r}")
            if inst_sha != art_sha:
                raise ValueError("Updater artifact_sha256 must equal installed_identity_sha256")
        elif comp_name == "core":
            if art_id != "NekoProxyCore.zip":
                raise ValueError(f"Invalid core artifact_id: {art_id!r}")
            if art_fmt != "zip-core-v1":
                raise ValueError(f"Invalid core artifact_format: {art_fmt!r}")


def validate_proof_evidence_schema(
    evidence_bytes: bytes,
    *,
    k1_acceptance: dict[str, Any],
    k1b_custody: dict[str, Any],
) -> dict[str, Any]:
    doc = _validate_raw_canonical_json(evidence_bytes, "Proof evidence")
    if set(doc.keys()) != _EVIDENCE_CLOSED_FIELDS:
        missing = _EVIDENCE_CLOSED_FIELDS - set(doc.keys())
        extra = set(doc.keys()) - _EVIDENCE_CLOSED_FIELDS
        raise ValueError(f"Proof evidence closed fields violation: missing {missing}, extra {extra}")

    if doc["schema_version"] != 1:
        raise ValueError(f"Unsupported evidence schema_version: {doc['schema_version']}")

    if not isinstance(doc["source_sha"], str) or not _HEX40_RE.fullmatch(doc["source_sha"]):
        raise ValueError(f"Invalid source_sha in proof evidence: {doc['source_sha']!r}")

    k1b_sha = doc["k1b_custody_sha256"]
    if not isinstance(k1b_sha, str) or not _HEX64_RE.fullmatch(k1b_sha):
        raise ValueError(f"Invalid k1b_custody_sha256: {k1b_sha!r}")
    if k1b_sha != k1_acceptance["k1b_custody_sha256"]:
        raise ValueError("Evidence k1b_custody_sha256 does not match K1 acceptance record")

    if doc["updater_byte_identical"] is not True:
        raise ValueError("Evidence updater_byte_identical must be true")

    base_updater_sha = doc["baseline_updater_sha256"]
    if not isinstance(base_updater_sha, str) or not _HEX64_RE.fullmatch(base_updater_sha):
        raise ValueError(f"Invalid baseline_updater_sha256: {base_updater_sha!r}")

    # 1. Release authorities
    rel_auth = doc["release_authorities"]
    if not isinstance(rel_auth, dict) or set(rel_auth.keys()) != {"production", "proof"}:
        raise ValueError("release_authorities must be an object with exactly 'production' and 'proof'")

    for role, auth_doc in rel_auth.items():
        if not isinstance(auth_doc, dict) or set(auth_doc.keys()) != _RELEASE_AUTHORITY_CLOSED_FIELDS:
            raise ValueError(f"release_authorities.{role} closed fields violation")

        key_id = auth_doc["key_id"]
        pub_hex = auth_doc["public_key_hex"]
        pub_sha = auth_doc["public_key_sha256"]

        if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
            raise ValueError(f"Invalid {role} authority key_id: {key_id!r}")
        if not isinstance(pub_hex, str) or len(pub_hex) != 64 or not _HEX64_RE.fullmatch(pub_hex):
            raise ValueError(f"Invalid {role} authority public_key_hex (must be 64 lowercase hex): {pub_hex!r}")
        if not isinstance(pub_sha, str) or not _HEX64_RE.fullmatch(pub_sha):
            raise ValueError(f"Invalid {role} authority public_key_sha256: {pub_sha!r}")

        raw_pub = bytes.fromhex(pub_hex)
        if len(raw_pub) != 32:
            raise ValueError(f"{role} authority public key must decode to exactly 32 bytes")
        recomputed_pub_sha = hashlib.sha256(raw_pub).hexdigest()
        if recomputed_pub_sha != pub_sha:
            raise ValueError(f"{role} authority public_key_sha256 mismatch")

        # Compare to K1B custody authorities
        if role == "production":
            expected_auth = k1b_custody["authorities"]["production"]
            if key_id != "neko-update-prod-1":
                raise ValueError(f"Production authority key_id must be 'neko-update-prod-1', got {key_id!r}")
            if pub_sha != "63f58cb26a02be41ab99c2bec4d30d8f28eac7018fe949caf2bd02657d46ef50":
                raise ValueError("Production authority public_key_sha256 does not match authenticated prod-1 public key")
        else:
            expected_auth = k1b_custody["authorities"]["proof_release_authority"]
            if key_id != "neko-update-proof-v512-1":
                raise ValueError(f"Proof authority key_id must be 'neko-update-proof-v512-1', got {key_id!r}")
            if pub_sha != "fc5a3ecb30951fb9ff0dc28e67ae322901a4a311b3c4c747ed820d290f80f316":
                raise ValueError("Proof authority public_key_sha256 does not match K1A Proof Release Authority in K1B custody")

        if key_id != expected_auth["key_id"] or pub_sha != expected_auth["public_key_sha256"]:
            raise ValueError(f"{role} authority does not match K1B custody authority binding")

    # 2. Trust profiles
    profiles = doc["trust_profiles"]
    if not isinstance(profiles, dict) or set(profiles.keys()) != {"production_baseline", "proof_baseline"}:
        raise ValueError("trust_profiles must be an object with exactly 'production_baseline' and 'proof_baseline'")

    for p_role, p_doc in profiles.items():
        if not isinstance(p_doc, dict) or set(p_doc.keys()) != _TRUST_PROFILE_CLOSED_FIELDS:
            raise ValueError(f"trust_profiles.{p_role} closed fields violation")

        pid = p_doc["profile_id"]
        pa_id = p_doc["profile_authority_key_id"]
        pa_sha = p_doc["profile_authority_public_key_sha256"]
        penv_sha = p_doc["profile_envelope_sha256"]
        keyset_sha = p_doc["keyset_sha256"]

        if not isinstance(pid, str) or not pid:
            raise ValueError(f"Empty {p_role} profile_id")
        if not isinstance(pa_id, str) or not _KEY_ID_RE.fullmatch(pa_id):
            raise ValueError(f"Invalid {p_role} profile_authority_key_id: {pa_id!r}")
        for k_name, k_val in (("profile_authority_public_key_sha256", pa_sha), ("profile_envelope_sha256", penv_sha), ("keyset_sha256", keyset_sha)):
            if not isinstance(k_val, str) or not _HEX64_RE.fullmatch(k_val):
                raise ValueError(f"Invalid {p_role} {k_name}: {k_val!r}")

        expected_k1_prof = k1b_custody["profiles"]["production" if p_role == "production_baseline" else "proof"]
        if penv_sha != expected_k1_prof["envelope_sha256"]:
            raise ValueError(f"{p_role} profile_envelope_sha256 mismatch with K1B custody")
        if keyset_sha != expected_k1_prof["keyset_sha256"]:
            raise ValueError(f"{p_role} keyset_sha256 mismatch with K1B custody")

        # Verify one-key keyset hash recomputation matches
        matching_auth = rel_auth["production" if p_role == "production_baseline" else "proof"]
        recomputed_keyset = hashlib.sha256(canonical_json_dumps({
            "release_keys": [{
                "key_id": matching_auth["key_id"],
                "public_key_hex": matching_auth["public_key_hex"],
            }],
        })).hexdigest()
        if recomputed_keyset != keyset_sha:
            raise ValueError(f"{p_role} recomputed keyset SHA {recomputed_keyset} != keyset_sha256 {keyset_sha}")

    if profiles["production_baseline"]["profile_id"] == profiles["proof_baseline"]["profile_id"]:
        raise ValueError("production_baseline and proof_baseline profile_id must be distinct")
    if profiles["production_baseline"]["keyset_sha256"] == profiles["proof_baseline"]["keyset_sha256"]:
        raise ValueError("production_baseline and proof_baseline keyset_sha256 must be distinct")
    if profiles["production_baseline"]["profile_authority_key_id"] != profiles["proof_baseline"]["profile_authority_key_id"]:
        raise ValueError("Common Profile Authority key_id required between production and proof")
    if profiles["production_baseline"]["profile_authority_public_key_sha256"] != profiles["proof_baseline"]["profile_authority_public_key_sha256"]:
        raise ValueError("Common Profile Authority public_key_sha256 required between production and proof")

    # 3. Component identities
    comp_idents = doc["component_identities"]
    if not isinstance(comp_idents, dict) or set(comp_idents.keys()) != {"production_baseline", "proof_baseline", "proof_candidate"}:
        raise ValueError("component_identities must have exactly 'production_baseline', 'proof_baseline', and 'proof_candidate'")

    for set_name in ("production_baseline", "proof_baseline", "proof_candidate"):
        _validate_component_set(comp_idents[set_name], set_name)

    if comp_idents["production_baseline"] != comp_idents["proof_baseline"]:
        raise ValueError("component_identities.production_baseline must equal proof_baseline exactly")

    prod_upd_sha = comp_idents["production_baseline"]["updater"]["artifact_sha256"]
    proof_upd_sha = comp_idents["proof_baseline"]["updater"]["artifact_sha256"]
    if base_updater_sha != prod_upd_sha or base_updater_sha != proof_upd_sha:
        raise ValueError(f"baseline_updater_sha256 {base_updater_sha} does not match baseline updater component sha256 {prod_upd_sha}")

    # 4. Proof releases
    p_releases = doc["proof_releases"]
    if not isinstance(p_releases, list) or len(p_releases) == 0:
        raise ValueError("proof_releases must be a non-empty list")

    proof_key_id = rel_auth["proof"]["key_id"]
    proof_pub_bytes = bytes.fromhex(rel_auth["proof"]["public_key_hex"])
    proof_key_registry = {proof_key_id: proof_pub_bytes}

    baseline_count = sum(1 for r in p_releases if isinstance(r, dict) and r.get("role") == "baseline")
    candidate_count = sum(1 for r in p_releases if isinstance(r, dict) and r.get("role") == "candidate")
    if baseline_count != 1:
        raise ValueError(f"proof_releases must have exactly one role='baseline', found {baseline_count}")
    if candidate_count != 1:
        raise ValueError(f"proof_releases must have exactly one role='candidate', found {candidate_count}")

    verified_bindings: set[tuple[int, str, str]] = set()
    verified_sequences: set[int] = set()
    verified_envelopes: set[str] = set()
    release_sort_keys = []

    for idx, r_entry in enumerate(p_releases):
        field_prefix = f"proof_releases[{idx}]"
        if not isinstance(r_entry, dict) or set(r_entry.keys()) != _PROOF_RELEASE_CLOSED_FIELDS:
            raise ValueError(f"{field_prefix} closed fields violation")

        role = r_entry["role"]
        if role not in ("baseline", "candidate", "scenario_auxiliary"):
            raise ValueError(f"Invalid {field_prefix}.role: {role!r}")
        if role == "baseline":
            baseline_count += 1
        elif role == "candidate":
            candidate_count += 1

        seq = r_entry["release_sequence"]
        if not isinstance(seq, int) or seq < 1:
            raise ValueError(f"{field_prefix}.release_sequence must be int >= 1")

        rel_id = r_entry["release_id"]
        if not isinstance(rel_id, str) or not _RELEASE_ID_RE.fullmatch(rel_id):
            raise ValueError(f"Invalid {field_prefix}.release_id: {rel_id!r}")

        payload_sha = r_entry["payload_sha256"]
        env_sha = r_entry["envelope_sha256"]
        if not isinstance(payload_sha, str) or not _HEX64_RE.fullmatch(payload_sha):
            raise ValueError(f"Invalid {field_prefix}.payload_sha256: {payload_sha!r}")
        if not isinstance(env_sha, str) or not _HEX64_RE.fullmatch(env_sha):
            raise ValueError(f"Invalid {field_prefix}.envelope_sha256: {env_sha!r}")

        if env_sha in verified_envelopes:
            raise ValueError(f"Duplicate envelope_sha256 in proof_releases: {env_sha}")
        verified_envelopes.add(env_sha)

        key_id = r_entry["key_id"]
        if key_id != proof_key_id:
            raise ValueError(f"{field_prefix}.key_id must equal proof release authority key_id {proof_key_id!r}, got {key_id!r}")

        env_b64 = r_entry["envelope_b64"]
        if not isinstance(env_b64, str):
            raise ValueError(f"{field_prefix}.envelope_b64 must be str")

        try:
            raw_env = base64.b64decode(env_b64, validate=True)
            if base64.b64encode(raw_env).decode("ascii") != env_b64:
                raise ValueError("Non-canonical base64 encoding")
        except Exception as err:
            raise ValueError(f"Invalid {field_prefix}.envelope_b64: {err}") from err

        if hashlib.sha256(raw_env).hexdigest() != env_sha:
            raise ValueError(f"{field_prefix} envelope_b64 hash does not equal envelope_sha256")

        env_doc = _validate_raw_canonical_json(raw_env, f"{field_prefix} decoded envelope")

        try:
            verified_release_set, recomputed_payload_sha = verify_release_envelope_v2(
                env_doc,
                proof_key_registry,
            )
        except Exception as err:
            raise ValueError(f"{field_prefix} signature/schema verification failed: {err}") from err

        if recomputed_payload_sha != payload_sha:
            raise ValueError(f"{field_prefix} payload_sha256 mismatch")
        if verified_release_set.release_sequence != seq:
            raise ValueError(f"{field_prefix} release_sequence mismatch")
        if verified_release_set.release_id != rel_id:
            raise ValueError(f"{field_prefix} release_id mismatch")
        if env_doc.get("key_id") != key_id:
            raise ValueError(f"{field_prefix} envelope key_id mismatch")

        # Check components for baseline / candidate roles
        signed_comps = {}
        for cname in _COMPONENT_NAMES:
            cobj = verified_release_set.components.get(cname)
            if cobj is None:
                raise ValueError(f"{field_prefix} missing signed component {cname}")
            signed_comps[cname] = {
                "artifact_format": cobj.artifact_format,
                "artifact_id": cobj.artifact_id,
                "artifact_sha256": cobj.artifact_sha256,
                "artifact_size": cobj.artifact_size,
                "installed_identity_sha256": cobj.installed_identity_sha256,
                "version": cobj.version,
            }

        if role == "baseline":
            if signed_comps != comp_idents["proof_baseline"]:
                raise ValueError("proof_releases baseline signed components do not match component_identities.proof_baseline")
        elif role == "candidate":
            if signed_comps != comp_idents["proof_candidate"]:
                raise ValueError("proof_releases candidate signed components do not match component_identities.proof_candidate")

        verified_bindings.add((seq, rel_id, payload_sha))
        verified_sequences.add(seq)
        release_sort_keys.append((seq, env_sha))

    if release_sort_keys != sorted(release_sort_keys):
        raise ValueError("proof_releases must be strictly sorted by (release_sequence, envelope_sha256)")

    # 5. Scenarios
    scenarios = doc["scenarios"]
    if not isinstance(scenarios, list) or len(scenarios) == 0:
        raise ValueError("scenarios must be a non-empty list")

    scenario_ids = []
    referenced_envelopes: set[str] = set()

    for idx, sc in enumerate(scenarios):
        field_prefix = f"scenarios[{idx}]"
        if not isinstance(sc, dict) or set(sc.keys()) != _SCENARIO_CLOSED_FIELDS:
            raise ValueError(f"{field_prefix} closed fields violation")

        sc_id = sc["scenario_id"]
        if not isinstance(sc_id, str) or not sc_id:
            raise ValueError(f"Empty {field_prefix}.scenario_id")
        scenario_ids.append(sc_id)

        if sc["result"] != "PASS":
            raise ValueError(f"{field_prefix}.result must be 'PASS', got {sc['result']!r}")

        diag = sc["diagnostic_code"]
        if diag is not None and (not isinstance(diag, str) or not diag):
            raise ValueError(f"Invalid {field_prefix}.diagnostic_code: {diag!r}")

        _validate_authority_state(sc["before"], f"{field_prefix}.before", verified_bindings, verified_sequences)
        _validate_authority_state(sc["after"], f"{field_prefix}.after", verified_bindings, verified_sequences)

        env_refs = sc["release_envelope_sha256s"]
        if not isinstance(env_refs, list):
            raise ValueError(f"{field_prefix}.release_envelope_sha256s must be a list")

        for ref_idx, h in enumerate(env_refs):
            if not isinstance(h, str) or not _HEX64_RE.fullmatch(h):
                raise ValueError(f"Invalid {field_prefix}.release_envelope_sha256s[{ref_idx}]: {h!r}")
            if h not in verified_envelopes:
                raise ValueError(f"{field_prefix} references unknown envelope_sha256 {h}")

        if env_refs != sorted(set(env_refs)):
            raise ValueError(f"{field_prefix}.release_envelope_sha256s must be strictly sorted unique")

        referenced_envelopes.update(env_refs)

        ev_sha = sc["evidence_sha256"]
        if not isinstance(ev_sha, str) or not _HEX64_RE.fullmatch(ev_sha):
            raise ValueError(f"Invalid {field_prefix}.evidence_sha256: {ev_sha!r}")

        expected_scenario_body = {
            "after": sc["after"],
            "before": sc["before"],
            "diagnostic_code": sc["diagnostic_code"],
            "release_envelope_sha256s": sc["release_envelope_sha256s"],
            "result": sc["result"],
            "scenario_id": sc["scenario_id"],
        }
        recomputed_ev_sha = hashlib.sha256(canonical_json_dumps(expected_scenario_body)).hexdigest()
        if recomputed_ev_sha != ev_sha:
            raise ValueError(f"{field_prefix} evidence_sha256 recomputation mismatch: {recomputed_ev_sha} != {ev_sha}")

    if scenario_ids != sorted(set(scenario_ids)):
        raise ValueError("scenarios must be strictly sorted unique by scenario_id")

    orphaned = verified_envelopes - referenced_envelopes
    if orphaned:
        raise ValueError(f"Proof releases present but not referenced by any scenario: {orphaned}")

    # 6. final_bindings
    _validate_authority_state(doc["final_bindings"], "final_bindings", verified_bindings, verified_sequences)

    return doc


def generate_proof_evidence(
    *,
    source_sha: str,
    k1b_custody_sha256: str,
    baseline_updater_sha256: str,
    trust_profiles: dict[str, Any],
    release_authorities: dict[str, Any],
    component_identities: dict[str, Any],
    proof_releases: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
    final_bindings: dict[str, Any],
) -> tuple[bytes, str]:
    # Sort proof releases by (release_sequence, envelope_sha256)
    sorted_releases = sorted(
        proof_releases,
        key=lambda r: (r["release_sequence"], r["envelope_sha256"]),
    )

    # Recompute scenario evidence_sha256 and sort scenarios by scenario_id
    prepared_scenarios = []
    for sc in scenarios:
        sc_copy = copy.deepcopy(sc)
        sc_copy["release_envelope_sha256s"] = sorted(set(sc_copy.get("release_envelope_sha256s", [])))
        body = {
            "after": sc_copy["after"],
            "before": sc_copy["before"],
            "diagnostic_code": sc_copy.get("diagnostic_code"),
            "release_envelope_sha256s": sc_copy["release_envelope_sha256s"],
            "result": sc_copy["result"],
            "scenario_id": sc_copy["scenario_id"],
        }
        sc_copy["evidence_sha256"] = hashlib.sha256(canonical_json_dumps(body)).hexdigest()
        prepared_scenarios.append(sc_copy)

    sorted_scenarios = sorted(prepared_scenarios, key=lambda sc: sc["scenario_id"])

    evidence_doc = {
        "baseline_updater_sha256": baseline_updater_sha256,
        "component_identities": component_identities,
        "final_bindings": final_bindings,
        "k1b_custody_sha256": k1b_custody_sha256,
        "proof_releases": sorted_releases,
        "release_authorities": release_authorities,
        "scenarios": sorted_scenarios,
        "schema_version": 1,
        "source_sha": source_sha,
        "trust_profiles": trust_profiles,
        "updater_byte_identical": True,
    }

    raw_bytes = canonical_json_dumps(evidence_doc) + b"\n"
    evidence_sha = hashlib.sha256(raw_bytes).hexdigest()
    return raw_bytes, evidence_sha


def verify_proof_evidence(
    *,
    repo_root: Path,
    evidence_path: Path,
    k1_acceptance_record_path: Path,
    k1b_custody_path: Path,
    acceptance_record_path: Path | None = None,
) -> dict[str, Any]:
    # 1. Load and validate K1 acceptance record
    if not k1_acceptance_record_path.is_file():
        raise FileNotFoundError(f"K1 acceptance record not found: {k1_acceptance_record_path}")
    k1_acc_bytes = k1_acceptance_record_path.read_bytes()
    k1_acceptance = validate_k1_acceptance_record(k1_acc_bytes)

    # 2. Load and validate K1B custody bytes
    if not k1b_custody_path.is_file():
        raise FileNotFoundError(f"K1B custody not found: {k1b_custody_path}")
    k1b_bytes = k1b_custody_path.read_bytes()
    k1b_sha = hashlib.sha256(k1b_bytes).hexdigest()
    if k1b_sha != k1_acceptance["k1b_custody_sha256"]:
        raise ValueError(f"K1B custody file sha256 {k1b_sha} != K1 acceptance record k1b_custody_sha256 {k1_acceptance['k1b_custody_sha256']}")

    # Check path match
    expected_path_normalized = Path(k1_acceptance["k1b_custody_path"]).resolve()
    actual_path_normalized = k1b_custody_path.resolve()
    if expected_path_normalized != actual_path_normalized:
        raise ValueError(f"K1B custody path {actual_path_normalized} does not match K1 acceptance record {expected_path_normalized}")

    k1b_custody = _validate_raw_canonical_json(k1b_bytes, "K1B custody")

    # 3. Load and validate proof evidence bytes
    if not evidence_path.is_file():
        raise FileNotFoundError(f"Proof evidence not found: {evidence_path}")
    evidence_bytes = evidence_path.read_bytes()
    evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()

    evidence_doc = validate_proof_evidence_schema(
        evidence_bytes,
        k1_acceptance=k1_acceptance,
        k1b_custody=k1b_custody,
    )

    # 4. If acceptance record path is provided, validate acceptance record and compare digests
    if acceptance_record_path is not None:
        if not acceptance_record_path.is_file():
            raise FileNotFoundError(f"RA9 acceptance record not found: {acceptance_record_path}")
        acc_bytes = acceptance_record_path.read_bytes()
        acceptance_doc = validate_ra9_acceptance_record(acc_bytes)

        if evidence_doc["source_sha"] != acceptance_doc["ra9_code_head_sha"]:
            raise ValueError(f"Evidence source_sha {evidence_doc['source_sha']} != acceptance ra9_code_head_sha {acceptance_doc['ra9_code_head_sha']}")

        if evidence_sha != acceptance_doc["proof_evidence_sha256"]:
            raise ValueError(f"Evidence actual sha256 {evidence_sha} != acceptance expected proof_evidence_sha256 {acceptance_doc['proof_evidence_sha256']}")

        # Enforce Git immutability guard
        verify_ra9_acceptance_git_immutability(repo_root, acceptance_record_path, acceptance_doc["ra9_code_head_sha"])

    return evidence_doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify RA9 proof evidence against K1 acceptance and RA9 acceptance records.",
        argument_default=argparse.SUPPRESS,
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Path to Git repository root")
    parser.add_argument("--acceptance-record", type=Path, default=None, help="Path to v512-ra9-proof-acceptance.json")
    parser.add_argument("--evidence", required=True, type=Path, help="Path to v512-v513-proof-evidence.json")
    parser.add_argument("--k1-acceptance-record", required=True, type=Path, help="Path to v512-k1-acceptance.json")
    parser.add_argument("--k1b-custody", required=True, type=Path, help="Path to k1b-custody-v1.json")

    args = parser.parse_args(argv)
    repo_root = getattr(args, "repo_root", Path("."))
    acceptance_record = getattr(args, "acceptance_record", None)
    evidence = args.evidence
    k1_acceptance = args.k1_acceptance_record
    k1b_custody = args.k1b_custody

    try:
        verify_proof_evidence(
            repo_root=repo_root,
            evidence_path=evidence,
            k1_acceptance_record_path=k1_acceptance,
            k1b_custody_path=k1b_custody,
            acceptance_record_path=acceptance_record,
        )
        print("RA9_PROOF_EVIDENCE_VERIFIED_OK")
        return 0
    except Exception as err:
        sys.stderr.write(f"RA9_PROOF_EVIDENCE_VERIFY_ERROR: {err}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
