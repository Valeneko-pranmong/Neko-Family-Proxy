from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_LAUNCHER_DIR = _REPO_ROOT / "launcher"
_LAUNCHER_SRC = _LAUNCHER_DIR / "src"

for p in (str(_REPO_ROOT), str(_SCRIPTS_DIR), str(_LAUNCHER_SRC), str(_LAUNCHER_DIR)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from neko_launcher.updater.canonical_json import (  # noqa: E402
    canonical_json_dumps,
)
from verify_v512_proof_evidence import (  # noqa: E402
    generate_proof_evidence,
    main,
    validate_proof_evidence_schema,
    validate_ra9_acceptance_record,
    verify_proof_evidence,
)

_K1_ACCEPTANCE_PATH = _REPO_ROOT / "docs" / "superpowers" / "evidence" / "v512-k1-acceptance.json"
_K1B_CUSTODY_PATH = Path("E:/Github/artifacts/v512-k1-proof-fixtures/k1b-custody-v1.json")
_BASELINE_ENVELOPE_PATH = Path("E:/Github/artifacts/v512-k1-proof-fixtures/baseline/release-v2.json")
_CANDIDATE_ENVELOPE_PATH = Path("E:/Github/artifacts/v512-k1-proof-fixtures/candidate/release-v2.json")


@pytest.fixture
def k1_docs() -> tuple[dict[str, Any], dict[str, Any]]:
    k1_acc = json.loads(_K1_ACCEPTANCE_PATH.read_text(encoding="utf-8"))
    k1b = json.loads(_K1B_CUSTODY_PATH.read_text(encoding="utf-8"))
    return k1_acc, k1b


@pytest.fixture
def valid_evidence_setup(k1_docs: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    k1_acc, k1b = k1_docs

    baseline_env_bytes = _BASELINE_ENVELOPE_PATH.read_bytes()
    baseline_env_sha = hashlib.sha256(baseline_env_bytes).hexdigest()
    baseline_env_doc = json.loads(baseline_env_bytes.decode("utf-8"))

    candidate_env_bytes = _CANDIDATE_ENVELOPE_PATH.read_bytes()
    candidate_env_sha = hashlib.sha256(candidate_env_bytes).hexdigest()
    candidate_env_doc = json.loads(candidate_env_bytes.decode("utf-8"))

    base_comps = k1b["artifacts"]["baseline"]
    cand_comps = k1b["artifacts"]["candidate"]

    def _format_comp_set(c: dict[str, Any]) -> dict[str, Any]:
        return {
            name: {
                "artifact_format": c[name]["artifact_format"],
                "artifact_id": c[name]["artifact_id"],
                "artifact_sha256": c[name]["artifact_sha256"],
                "artifact_size": c[name]["artifact_size"],
                "installed_identity_sha256": c[name]["installed_identity_sha256"],
                "version": c[name]["version"],
            }
            for name in ("launcher", "updater", "core")
        }

    comp_identities = {
        "production_baseline": _format_comp_set(base_comps),
        "proof_baseline": _format_comp_set(base_comps),
        "proof_candidate": _format_comp_set(cand_comps),
    }

    trust_profiles = {
        "production_baseline": {
            "keyset_sha256": k1b["profiles"]["production"]["keyset_sha256"],
            "profile_authority_key_id": k1b["authorities"]["profile_authority"]["key_id"],
            "profile_authority_public_key_sha256": k1b["authorities"]["profile_authority"]["public_key_sha256"],
            "profile_envelope_sha256": k1b["profiles"]["production"]["envelope_sha256"],
            "profile_id": "production",
        },
        "proof_baseline": {
            "keyset_sha256": k1b["profiles"]["proof"]["keyset_sha256"],
            "profile_authority_key_id": k1b["authorities"]["profile_authority"]["key_id"],
            "profile_authority_public_key_sha256": k1b["authorities"]["profile_authority"]["public_key_sha256"],
            "profile_envelope_sha256": k1b["profiles"]["proof"]["envelope_sha256"],
            "profile_id": "proof-v512",
        },
    }

    # Public keys
    prod_pub_hex = "c98941b472a01967a54e4f1cb215f71a479cf187ebdd0fa37f4ee9a5693fe9cf"
    proof_pub_hex = "731750af805a9632f948e428341a705ccc915bba7b6d7e032546a12dbfa53ff3"

    release_authorities = {
        "production": {
            "key_id": k1b["authorities"]["production"]["key_id"],
            "public_key_hex": prod_pub_hex,
            "public_key_sha256": k1b["authorities"]["production"]["public_key_sha256"],
        },
        "proof": {
            "key_id": k1b["authorities"]["proof_release_authority"]["key_id"],
            "public_key_hex": proof_pub_hex,
            "public_key_sha256": k1b["authorities"]["proof_release_authority"]["public_key_sha256"],
        },
    }

    proof_releases = [
        {
            "envelope_b64": base64.b64encode(baseline_env_bytes).decode("ascii"),
            "envelope_sha256": baseline_env_sha,
            "key_id": baseline_env_doc["key_id"],
            "payload_sha256": k1b["proof_releases"]["baseline"]["payload_sha256"],
            "release_id": k1b["proof_releases"]["baseline"]["release_id"],
            "release_sequence": k1b["proof_releases"]["baseline"]["release_sequence"],
            "role": "baseline",
        },
        {
            "envelope_b64": base64.b64encode(candidate_env_bytes).decode("ascii"),
            "envelope_sha256": candidate_env_sha,
            "key_id": candidate_env_doc["key_id"],
            "payload_sha256": k1b["proof_releases"]["candidate"]["payload_sha256"],
            "release_id": k1b["proof_releases"]["candidate"]["release_id"],
            "release_sequence": k1b["proof_releases"]["candidate"]["release_sequence"],
            "role": "candidate",
        },
    ]

    base_binding = {
        "payload_sha256": k1b["proof_releases"]["baseline"]["payload_sha256"],
        "release_id": k1b["proof_releases"]["baseline"]["release_id"],
        "release_sequence": k1b["proof_releases"]["baseline"]["release_sequence"],
    }
    cand_binding = {
        "payload_sha256": k1b["proof_releases"]["candidate"]["payload_sha256"],
        "release_id": k1b["proof_releases"]["candidate"]["release_id"],
        "release_sequence": k1b["proof_releases"]["candidate"]["release_sequence"],
    }

    state_before = {
        "committed": base_binding,
        "failed": None,
        "high_water": base_binding,
        "observed": base_binding,
        "pending_release_sequence": None,
    }
    state_after = {
        "committed": cand_binding,
        "failed": None,
        "high_water": cand_binding,
        "observed": cand_binding,
        "pending_release_sequence": None,
    }

    scenarios = [
        {
            "after": state_before,
            "before": state_before,
            "diagnostic_code": None,
            "release_envelope_sha256s": [baseline_env_sha],
            "result": "PASS",
            "scenario_id": "SCENARIO_01_BASELINE_ENROLLMENT",
        },
        {
            "after": state_after,
            "before": state_before,
            "diagnostic_code": None,
            "release_envelope_sha256s": [candidate_env_sha],
            "result": "PASS",
            "scenario_id": "SCENARIO_02_MANDATORY_UPGRADE",
        },
    ]

    doc = {
        "baseline_updater_sha256": base_comps["updater"]["artifact_sha256"],
        "component_identities": comp_identities,
        "final_bindings": state_after,
        "k1b_custody_sha256": k1_acc["k1b_custody_sha256"],
        "proof_releases": proof_releases,
        "release_authorities": release_authorities,
        "scenarios": scenarios,
        "schema_version": 1,
        "source_sha": "5fe4ce7454aa5d538134c80de7e40d665fde1712",
        "trust_profiles": trust_profiles,
        "updater_byte_identical": True,
    }
    return doc


def _encode_doc(doc: dict[str, Any]) -> bytes:
    # Ensure evidence_sha256 is populated for scenarios
    for sc in doc.get("scenarios", []):
        body = {
            "after": sc["after"],
            "before": sc["before"],
            "diagnostic_code": sc.get("diagnostic_code"),
            "release_envelope_sha256s": sc["release_envelope_sha256s"],
            "result": sc["result"],
            "scenario_id": sc["scenario_id"],
        }
        sc["evidence_sha256"] = hashlib.sha256(canonical_json_dumps(body)).hexdigest()
    return canonical_json_dumps(doc) + b"\n"


def test_valid_proof_evidence_passes(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    raw = _encode_doc(valid_evidence_setup)
    res = validate_proof_evidence_schema(raw, k1_acceptance=k1_acc, k1b_custody=k1b)
    assert res["schema_version"] == 1
    assert res["updater_byte_identical"] is True


def test_red_missing_extra_proof_releases(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["proof_releases"] = []
    with pytest.raises(ValueError, match="proof_releases must be a non-empty list"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_zero_or_multiple_baseline_or_candidate_roles(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    # Zero baseline
    doc = copy.deepcopy(valid_evidence_setup)
    doc["proof_releases"][0]["role"] = "scenario_auxiliary"
    with pytest.raises(ValueError, match="exactly one role='baseline'"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)

    # Multiple candidate
    doc2 = copy.deepcopy(valid_evidence_setup)
    extra_cand = copy.deepcopy(doc2["proof_releases"][1])
    extra_cand["release_sequence"] = 3
    extra_cand["release_id"] = "proof-k1-0003"
    doc2["proof_releases"].append(extra_cand)
    with pytest.raises(ValueError, match="exactly one role='candidate'"):
        validate_proof_evidence_schema(_encode_doc(doc2), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_baseline_candidate_signed_component_mismatch(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["component_identities"]["production_baseline"]["launcher"]["version"] = "9.9.9"
    doc["component_identities"]["proof_baseline"]["launcher"]["version"] = "9.9.9"
    with pytest.raises(ValueError, match="do not match component_identities.proof_baseline"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_production_proof_baseline_component_divergence(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["component_identities"]["production_baseline"]["launcher"]["artifact_size"] = 123
    with pytest.raises(ValueError, match="must equal proof_baseline exactly"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_bad_component_metadata(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    # Bad artifact id
    doc = copy.deepcopy(valid_evidence_setup)
    doc["component_identities"]["proof_candidate"]["launcher"]["artifact_id"] = "Wrong.exe"
    with pytest.raises(ValueError, match="Invalid launcher artifact_id"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)

    # Negative size
    doc2 = copy.deepcopy(valid_evidence_setup)
    doc2["component_identities"]["proof_candidate"]["core"]["artifact_size"] = -1
    with pytest.raises(ValueError, match="artifact_size must be int > 0"):
        validate_proof_evidence_schema(_encode_doc(doc2), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_baseline_updater_sha256_mismatch(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["baseline_updater_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="does not match baseline updater component sha256"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_state_binding_with_no_matching_proof_release(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["scenarios"][0]["before"]["committed"]["release_sequence"] = 999
    with pytest.raises(ValueError, match="does not match any verified proof release"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_pending_sequence_absent_from_proof_releases(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["scenarios"][0]["after"]["pending_release_sequence"] = 999
    with pytest.raises(ValueError, match="absent from proof releases"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_invalid_public_key_hex_and_sha(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    # Wrong length
    doc = copy.deepcopy(valid_evidence_setup)
    doc["release_authorities"]["proof"]["public_key_hex"] = "abcd"
    with pytest.raises(ValueError, match="public_key_hex"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)

    # Public key SHA mismatch
    doc2 = copy.deepcopy(valid_evidence_setup)
    doc2["release_authorities"]["proof"]["public_key_sha256"] = "1" * 64
    with pytest.raises(ValueError, match="public_key_sha256 mismatch"):
        validate_proof_evidence_schema(_encode_doc(doc2), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_k1_authority_key_id_mismatch(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["release_authorities"]["proof"]["key_id"] = "tampered-proof-id"
    with pytest.raises(ValueError, match="Proof authority key_id must be 'neko-update-proof-v512-1'"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_recomputed_keyset_sha_mismatch(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["trust_profiles"]["proof_baseline"]["keyset_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="keyset_sha256 mismatch"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_invalid_non_canonical_base64_and_envelope(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["proof_releases"][0]["envelope_b64"] = "not base64!"
    with pytest.raises(ValueError, match="Invalid proof_releases.*envelope_b64"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_envelope_sha_mismatch(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["proof_releases"][0]["envelope_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="does not equal envelope_sha256"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_payload_sha_mismatch(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    doc["proof_releases"][0]["payload_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="payload_sha256 mismatch"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_unknown_and_unsorted_scenario_envelope_references(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    # Unknown envelope reference
    doc = copy.deepcopy(valid_evidence_setup)
    doc["scenarios"][0]["release_envelope_sha256s"] = ["1" * 64]
    with pytest.raises(ValueError, match="references unknown envelope_sha256"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_evidence_sha_mismatch_and_stale_digest(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    raw = _encode_doc(doc)
    doc_decoded = json.loads(raw.decode("utf-8"))
    doc_decoded["scenarios"][0]["evidence_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="evidence_sha256 recomputation mismatch"):
        validate_proof_evidence_schema(canonical_json_dumps(doc_decoded) + b"\n", k1_acceptance=k1_acc, k1b_custody=k1b)


def test_red_orphaned_proof_release(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = copy.deepcopy(valid_evidence_setup)
    # Scenario 2 no longer references candidate envelope
    doc["scenarios"][1]["release_envelope_sha256s"] = []
    with pytest.raises(ValueError, match="Proof releases present but not referenced by any scenario"):
        validate_proof_evidence_schema(_encode_doc(doc), k1_acceptance=k1_acc, k1b_custody=k1b)


def test_verify_proof_evidence_file_paths_and_acceptance(
    tmp_path: Path,
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    ev_bytes = _encode_doc(valid_evidence_setup)
    ev_path = tmp_path / "v512-v513-proof-evidence.json"
    ev_path.write_bytes(ev_bytes)

    # 1. Missing files
    with pytest.raises(FileNotFoundError):
        verify_proof_evidence(
            repo_root=_REPO_ROOT,
            evidence_path=tmp_path / "missing.json",
            k1_acceptance_record_path=_K1_ACCEPTANCE_PATH,
            k1b_custody_path=_K1B_CUSTODY_PATH,
        )

    # 2. Custody digest mismatch
    bad_custody = tmp_path / "bad-k1b.json"
    bad_custody.write_bytes(b"{}")
    with pytest.raises(ValueError, match="K1B custody file sha256"):
        verify_proof_evidence(
            repo_root=_REPO_ROOT,
            evidence_path=ev_path,
            k1_acceptance_record_path=_K1_ACCEPTANCE_PATH,
            k1b_custody_path=bad_custody,
        )

    # 3. Path mismatch with K1 acceptance record
    k1b_copy = tmp_path / "k1b-custody-v1.json"
    k1b_copy.write_bytes(_K1B_CUSTODY_PATH.read_bytes())
    with pytest.raises(ValueError, match="K1B custody path"):
        verify_proof_evidence(
            repo_root=_REPO_ROOT,
            evidence_path=ev_path,
            k1_acceptance_record_path=_K1_ACCEPTANCE_PATH,
            k1b_custody_path=k1b_copy,
        )

    # 4. Valid standalone verification passes
    res = verify_proof_evidence(
        repo_root=_REPO_ROOT,
        evidence_path=ev_path,
        k1_acceptance_record_path=_K1_ACCEPTANCE_PATH,
        k1b_custody_path=_K1B_CUSTODY_PATH,
    )
    assert res["schema_version"] == 1


def test_ra9_acceptance_record_schema() -> None:
    acc_doc = {
        "critical_count": 0,
        "important_count": 0,
        "proof_custody_path": "E:/Github/artifacts/v512-release-proof-evidence/v512-v513-proof-evidence.json",
        "proof_evidence_sha256": "1" * 64,
        "ra9_code_head_sha": "5fe4ce7454aa5d538134c80de7e40d665fde1712",
        "reviewed_at": "2026-09-15T11:30:00Z",
        "reviewer_model": "ag/gemini-pro-agent",
        "schema_version": 1,
        "task_id": "RA9",
    }
    raw = canonical_json_dumps(acc_doc) + b"\n"
    res = validate_ra9_acceptance_record(raw)
    assert res["task_id"] == "RA9"

    # Schema error on non-zero critical count
    bad = copy.deepcopy(acc_doc)
    bad["critical_count"] = 1
    with pytest.raises(ValueError, match="critical_count == 0"):
        validate_ra9_acceptance_record(canonical_json_dumps(bad) + b"\n")


def test_cli_main(tmp_path: Path, valid_evidence_setup: dict[str, Any]) -> None:
    ev_bytes = _encode_doc(valid_evidence_setup)
    ev_path = tmp_path / "v512-v513-proof-evidence.json"
    ev_path.write_bytes(ev_bytes)

    ret = main([
        "--repo-root", str(_REPO_ROOT),
        "--evidence", str(ev_path),
        "--k1-acceptance-record", str(_K1_ACCEPTANCE_PATH),
        "--k1b-custody", str(_K1B_CUSTODY_PATH),
    ])
    assert ret == 0


def test_generate_proof_evidence_roundtrip(
    valid_evidence_setup: dict[str, Any],
    k1_docs: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    k1_acc, k1b = k1_docs
    doc = valid_evidence_setup
    raw, sha = generate_proof_evidence(
        source_sha=doc["source_sha"],
        k1b_custody_sha256=doc["k1b_custody_sha256"],
        baseline_updater_sha256=doc["baseline_updater_sha256"],
        trust_profiles=doc["trust_profiles"],
        release_authorities=doc["release_authorities"],
        component_identities=doc["component_identities"],
        proof_releases=doc["proof_releases"],
        scenarios=doc["scenarios"],
        final_bindings=doc["final_bindings"],
    )
    assert hashlib.sha256(raw).hexdigest() == sha
    res = validate_proof_evidence_schema(raw, k1_acceptance=k1_acc, k1b_custody=k1b)
    assert res["schema_version"] == 1

