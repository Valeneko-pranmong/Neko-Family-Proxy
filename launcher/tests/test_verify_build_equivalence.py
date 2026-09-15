from __future__ import annotations

import base64
from pathlib import Path
import subprocess
import sys
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"

for p in (str(_SCRIPTS_DIR), str(_REPO_ROOT), str(_LAUNCHER_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads  # noqa: E402
from verify_build_equivalence import (  # noqa: E402
    PROFILE_ALLOWLIST,
    ContentInventoryEntry,
    EquivalenceResult,
    build_inventory,
    classify_path,
    compare_builds,
    emit_canonical_evidence_json,
    generate_equivalence_evidence,
    validate_allowlist,
)


def _make_keypair() -> tuple[Ed25519PrivateKey, bytes]:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes_raw()
    return priv, pub_bytes


def make_test_profile_envelope(
    *,
    auth_priv: Ed25519PrivateKey,
    auth_key_id: str = "test-auth-key-1",
    profile_id: str = "proof-v512",
    channel: str = "stable",
    owner: str = "Valeneko-pranmong",
    repository: str = "Neko-Family-Proxy-Updates-Proof",
    release_keys: list[dict[str, str]] | None = None,
    corrupt_sig: bool = False,
    envelope_override: dict | None = None,
    payload_override: dict | None = None,
    trailing: bytes = b"\n",
) -> tuple[bytes, dict, bytes]:
    if release_keys is None:
        _, rel_pub = _make_keypair()
        release_keys = [{"key_id": "test-rel-1", "public_key_hex": rel_pub.hex()}]

    payload = {
        "channel": channel,
        "owner": owner,
        "profile_id": profile_id,
        "release_keys": release_keys,
        "repository": repository,
    }
    if payload_override is not None:
        payload.update(payload_override)
    payload_bytes = canonical_json_dumps(payload)
    sig_bytes = auth_priv.sign(payload_bytes)
    if corrupt_sig:
        sig_bytes = bytes([b ^ 0xFF for b in sig_bytes])

    sig_b64 = base64.b64encode(sig_bytes).decode("ascii")

    envelope = {
        "key_id": auth_key_id,
        "payload": payload,
        "schema_version": 1,
        "signature_b64": sig_b64,
    }
    if envelope_override is not None:
        envelope.update(envelope_override)

    raw = canonical_json_dumps(envelope) + trailing
    return raw, envelope, payload_bytes


def make_equivalent_trees(
    tmp_path: Path,
    auth_priv: Ed25519PrivateKey | None = None,
    auth_key_id: str = "test-auth-key-1",
) -> tuple[Path, Path]:
    prod = tmp_path / "production"
    proof = tmp_path / "proof"
    prod.mkdir(parents=True, exist_ok=True)
    proof.mkdir(parents=True, exist_ok=True)

    if auth_priv is None:
        auth_priv = Ed25519PrivateKey.generate()

    profile_raw, _, _ = make_test_profile_envelope(
        auth_priv=auth_priv,
        auth_key_id=auth_key_id,
        profile_id="prod-v512",
        channel="stable",
    )

    for tree in (prod, proof):
        (tree / "NekoUpdater.exe").write_bytes(b"MZ_NEKO_UPDATER_BYTE_EXACT_V512")
        (tree / "NekoLauncher.exe").write_bytes(b"MZ_NEKO_LAUNCHER_EXE_V512")
        (tree / "python311.dll").write_bytes(b"MZ_PYTHON_DLL_BYTES_V512")
        (tree / "Asset").mkdir(parents=True, exist_ok=True)
        (tree / "Asset" / "setting.png").write_bytes(b"PNG_SAMPLE_BYTES")
        (tree / "trust").mkdir(parents=True, exist_ok=True)
        (tree / "trust" / "update-profile-v1.json").write_bytes(profile_raw)

    return prod, proof


# ---------------------------------------------------------------------------
# Step 1: Identical extracted trees pass & inventory is deterministic
# ---------------------------------------------------------------------------


def test_identical_extracted_trees_pass(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    result = compare_builds(prod, proof, allowlist=PROFILE_ALLOWLIST)

    assert isinstance(result, EquivalenceResult)
    assert result.equivalent is True
    assert result.updater_byte_identical is True
    assert result.unexpected_differences == ()
    assert result.allowed_differences == ()
    assert len(result.production_inventory) == 5
    assert len(result.proof_inventory) == 5


def test_inventory_deterministic_sorting_and_fields(tmp_path: Path) -> None:
    root = tmp_path / "inventory_sample"
    root.mkdir(parents=True, exist_ok=True)
    (root / "z_resource.txt").write_bytes(b"res")
    (root / "NekoUpdater.exe").write_bytes(b"updater")
    (root / "sub").mkdir(parents=True, exist_ok=True)
    (root / "sub" / "module.pyc").write_bytes(b"pyc")
    (root / "sub" / "lib.dll").write_bytes(b"dll")
    (root / "trust").mkdir(parents=True, exist_ok=True)
    (root / "trust" / "update-profile-v1.json").write_bytes(b"{}\n")

    inv = build_inventory(root)
    paths = [e.logical_path for e in inv]
    assert paths == sorted(paths)
    assert paths == [
        "NekoUpdater.exe",
        "sub/lib.dll",
        "sub/module.pyc",
        "trust/update-profile-v1.json",
        "z_resource.txt",
    ]

    class_map = {e.logical_path: e.classification for e in inv}
    assert class_map["NekoUpdater.exe"] == "updater"
    assert class_map["sub/lib.dll"] in ("executable", "code_module")
    assert class_map["sub/module.pyc"] == "code_module"
    assert class_map["trust/update-profile-v1.json"] == "trust_profile"
    assert class_map["z_resource.txt"] == "resource"
    assert classify_path("launcher/main.py") == "code_module"
    assert classify_path("release-v2.json") == "manifest"

    for entry in inv:
        assert len(entry.sha256) == 64
        assert entry.size > 0
        assert isinstance(entry, ContentInventoryEntry)


# ---------------------------------------------------------------------------
# Step 2: One allowlisted generated profile-resource difference passes & records evidence
# ---------------------------------------------------------------------------


def test_allowlisted_profile_difference_passes_and_records_evidence(tmp_path: Path) -> None:
    auth_priv, auth_pub = _make_keypair()
    auth_key_id = "test-authority-root-1"
    auth_keys = {auth_key_id: auth_pub}

    prod, proof = make_equivalent_trees(tmp_path, auth_priv=auth_priv, auth_key_id=auth_key_id)

    # Production profile: production endpoint/channel
    prod_profile_raw, _, _ = make_test_profile_envelope(
        auth_priv=auth_priv,
        auth_key_id=auth_key_id,
        profile_id="production",
        channel="stable",
        repository="Neko-Family-Proxy",
    )
    (prod / "trust" / "update-profile-v1.json").write_bytes(prod_profile_raw)

    # Proof profile: proof endpoint/channel with proof release key, same root authority
    proof_profile_raw, _, _ = make_test_profile_envelope(
        auth_priv=auth_priv,
        auth_key_id=auth_key_id,
        profile_id="proof-v512",
        channel="proof",
        repository="Neko-Family-Proxy-Updates-Proof",
    )
    (proof / "trust" / "update-profile-v1.json").write_bytes(proof_profile_raw)

    result = compare_builds(
        prod,
        proof,
        allowlist=PROFILE_ALLOWLIST,
        profile_authority_public_keys=auth_keys,
    )

    assert result.equivalent is True
    assert result.updater_byte_identical is True
    assert result.unexpected_differences == ()
    assert result.allowed_differences == ("trust/update-profile-v1.json",)

    evidence = generate_equivalence_evidence(
        result,
        production_root=prod,
        proof_root=proof,
    )
    assert evidence["schema_version"] == 1
    assert evidence["equivalent"] is True
    assert evidence["updater_byte_identical"] is True
    assert evidence["allowed_differences"] == ["trust/update-profile-v1.json"]
    assert evidence["unexpected_differences"] == []
    assert len(evidence["production_inventory"]) == 5
    assert len(evidence["proof_inventory"]) == 5

    ev_path = tmp_path / "equivalence-evidence.json"
    raw_bytes = emit_canonical_evidence_json(result, ev_path, production_root=prod, proof_root=proof)
    assert ev_path.is_file()
    assert raw_bytes.endswith(b"\n")
    assert not raw_bytes.endswith(b"\r\n")
    assert not raw_bytes.endswith(b"\n\n")

    loaded = canonical_json_loads(raw_bytes[:-1])
    assert loaded["equivalent"] is True
    assert loaded["allowed_differences"] == ["trust/update-profile-v1.json"]


# ---------------------------------------------------------------------------
# Step 3: Non-allowlisted differences, extra/missing files, updater changes, globs fail
# ---------------------------------------------------------------------------


def test_changed_updater_always_fails(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    (proof / "NekoUpdater.exe").write_bytes(b"changed")
    result = compare_builds(prod, proof, allowlist=PROFILE_ALLOWLIST)
    assert not result.equivalent
    assert not result.updater_byte_identical
    assert "NekoUpdater.exe" in result.unexpected_differences


def test_non_allowlisted_code_module_difference_fails(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    (proof / "python311.dll").write_bytes(b"tampered-dll-bytes")
    result = compare_builds(prod, proof, allowlist=PROFILE_ALLOWLIST)
    assert not result.equivalent
    assert result.updater_byte_identical is True
    assert "python311.dll" in result.unexpected_differences


def test_non_allowlisted_resource_difference_fails(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    (proof / "Asset" / "setting.png").write_bytes(b"tampered-png-bytes")
    result = compare_builds(prod, proof, allowlist=PROFILE_ALLOWLIST)
    assert not result.equivalent
    assert "Asset/setting.png" in result.unexpected_differences


def test_extra_file_in_proof_fails(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    (proof / "extra_file.exe").write_bytes(b"extra")
    result = compare_builds(prod, proof, allowlist=PROFILE_ALLOWLIST)
    assert not result.equivalent
    assert "extra_file.exe" in result.unexpected_differences


def test_missing_file_in_proof_fails(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    (proof / "NekoLauncher.exe").unlink()
    result = compare_builds(prod, proof, allowlist=PROFILE_ALLOWLIST)
    assert not result.equivalent
    assert "NekoLauncher.exe" in result.unexpected_differences


def test_missing_updater_fails_byte_identical_and_equivalence(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    (proof / "NekoUpdater.exe").unlink()
    result = compare_builds(prod, proof, allowlist=PROFILE_ALLOWLIST)
    assert not result.equivalent
    assert not result.updater_byte_identical
    assert "NekoUpdater.exe" in result.unexpected_differences


def test_allowlist_rejects_broad_globs(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    for bad_glob in ("*", "*.py", "trust/*", "trust/**", "?", "[a-z]"):
        with pytest.raises(ValueError, match=r"glob|wildcard"):
            validate_allowlist([bad_glob])
        with pytest.raises(ValueError, match=r"glob|wildcard"):
            compare_builds(prod, proof, allowlist=[bad_glob])


def test_allowlist_rejects_code_modules(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    for code_file in ("app.py", "sub/module.pyc", "lib.pyd", "NekoLauncher.exe", "extra.dll"):
        with pytest.raises(ValueError, match=r"Code module|executable"):
            validate_allowlist([code_file])
        with pytest.raises(ValueError, match=r"Code module|executable"):
            compare_builds(prod, proof, allowlist=[code_file])


def test_allowlist_rejects_directories_and_traversal() -> None:
    for bad in ("trust/", "/trust", "", " ", "../outside.json"):
        with pytest.raises(ValueError):
            validate_allowlist([bad])


def test_allowlist_rejects_unauthorized_resources(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    with pytest.raises(ValueError, match=r"Unauthorized allowlist entry"):
        validate_allowlist(["Asset/setting.png"])
    with pytest.raises(ValueError, match=r"Unauthorized allowlist entry"):
        compare_builds(prod, proof, allowlist=["Asset/setting.png"])


def test_profile_tampered_signature_fails_equivalence(tmp_path: Path) -> None:
    auth_priv, auth_pub = _make_keypair()
    auth_key_id = "test-auth-key-1"
    prod, proof = make_equivalent_trees(tmp_path, auth_priv=auth_priv, auth_key_id=auth_key_id)

    bad_profile_raw, _, _ = make_test_profile_envelope(
        auth_priv=auth_priv,
        auth_key_id=auth_key_id,
        profile_id="proof-v512",
        corrupt_sig=True,
    )
    (proof / "trust" / "update-profile-v1.json").write_bytes(bad_profile_raw)

    result = compare_builds(
        prod,
        proof,
        allowlist=PROFILE_ALLOWLIST,
        profile_authority_public_keys={auth_key_id: auth_pub},
    )
    assert not result.equivalent
    assert "trust/update-profile-v1.json" in result.unexpected_differences


def test_profile_different_authority_root_fails_equivalence(tmp_path: Path) -> None:
    auth_priv_prod, auth_pub_prod = _make_keypair()
    auth_priv_proof, auth_pub_proof = _make_keypair()

    prod, proof = make_equivalent_trees(tmp_path, auth_priv=auth_priv_prod, auth_key_id="auth-root-prod")

    proof_profile_raw, _, _ = make_test_profile_envelope(
        auth_priv=auth_priv_proof,
        auth_key_id="auth-root-proof",
        profile_id="proof-v512",
    )
    (proof / "trust" / "update-profile-v1.json").write_bytes(proof_profile_raw)

    all_keys = {
        "auth-root-prod": auth_pub_prod,
        "auth-root-proof": auth_pub_proof,
    }
    result = compare_builds(
        prod,
        proof,
        allowlist=PROFILE_ALLOWLIST,
        profile_authority_public_keys=all_keys,
    )
    assert not result.equivalent
    assert "trust/update-profile-v1.json" in result.unexpected_differences


def test_profile_non_canonical_formatting_fails_equivalence(tmp_path: Path) -> None:
    auth_priv, auth_pub = _make_keypair()
    auth_key_id = "test-auth-key-1"
    prod, proof = make_equivalent_trees(tmp_path, auth_priv=auth_priv, auth_key_id=auth_key_id)

    profile_raw, _, _ = make_test_profile_envelope(
        auth_priv=auth_priv,
        auth_key_id=auth_key_id,
        profile_id="proof-v512",
        trailing=b"\r\n",  # CRLF forbidden
    )
    (proof / "trust" / "update-profile-v1.json").write_bytes(profile_raw)

    result = compare_builds(
        prod,
        proof,
        allowlist=PROFILE_ALLOWLIST,
        profile_authority_public_keys={auth_key_id: auth_pub},
    )
    assert not result.equivalent
    assert "trust/update-profile-v1.json" in result.unexpected_differences


def test_cli_invocation_happy_path_and_failure(tmp_path: Path) -> None:
    prod, proof = make_equivalent_trees(tmp_path)
    ev_out = tmp_path / "cli-evidence.json"

    # Happy path CLI
    proc_ok = subprocess.run(
        [
            sys.executable,
            "-B",
            str(_SCRIPTS_DIR / "verify_build_equivalence.py"),
            "--production-dir",
            str(prod),
            "--proof-dir",
            str(proof),
            "--evidence-out",
            str(ev_out),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_ok.returncode == 0, proc_ok.stderr
    assert "EQUIVALENT: True" in proc_ok.stdout
    assert ev_out.is_file()

    # Tampered CLI -> exit code 1
    (proof / "NekoLauncher.exe").write_bytes(b"tampered")
    proc_fail = subprocess.run(
        [
            sys.executable,
            "-B",
            str(_SCRIPTS_DIR / "verify_build_equivalence.py"),
            "--production-dir",
            str(prod),
            "--proof-dir",
            str(proof),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_fail.returncode == 1
    assert "EQUIVALENT: False" in proc_fail.stdout
