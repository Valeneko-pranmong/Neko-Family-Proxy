# Software Update Phase 2 — Slice 1 Trust Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure Launcher trust core for signed release manifests, anti-downgrade decisions, local installed identity, artifact verification, and Owner/build signing tooling without any network or installation behavior.

**Architecture:** Keep signed release models/policy in the application layer and cryptographic/filesystem adapters in infrastructure. The verifier authenticates exact payload bytes before parsing payload JSON; policy compares a signed release set with a locally admitted Launcher/Core identity; artifact verification is streaming size+SHA only.

**Tech Stack:** Python 3.11, dataclasses/enums, `cryptography==50.0.0` Ed25519, hashlib, pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-05-software-update-phase-2-design.md`

## Global Constraints

- Worktree: `E:\Github\worktrees\Neko-Family-Proxy-5.1` on `release/5.1`; do not touch the dirty legacy `stabilize/a42-owner-verified` worktree.
- Current source version is `5.1.0a1`; do not build a materially changed Owner-test binary under that same version.
- Runtime Config v1, production Runtime Config v2, and `issue_launch_permit` v4 are separate and must not change.
- Phase 2 detects/authenticates updates and verifies artifact bytes only. No install, activation, `NekoUpdater.exe`, backup, rollback, or post-update self-test.
- Remote signed manifests use `release_sequence >= 1`; unpublished development uses local sequence `0` / `dev-unpublished`.
- Signed envelope: exact payload bytes, Ed25519, 64 KiB HTTP body, decoded payload <= 49,152 bytes, 64-byte signature, 32-byte public key.
- Key IDs: test `neko-update-test-1`; production reserved `neko-update-prod-1`. The production private key never enters the repo/client/logs.
- Manifest HTTP: HTTPS only, no redirects, 5.0 s timeout. Grant response: HTTPS only, no redirects, 5.0 s timeout, <= 16,384 bytes.
- Launcher artifact maximum 128 MiB; Core artifact maximum 1 GiB.
- Use TDD: a genuine failing assertion/missing-symbol RED before each product implementation. Collection/import errors do not count as RED.
- Launcher focused/final tests run with `PYTHONPATH` pointing at this worktree and `TCL_LIBRARY`/`TK_LIBRARY` removed process-locally. Full Launcher integration uses canonical Core artifact `E:\Github\worktrees\NekoProxyCore-live-update\TestResults\task12\a43-core`.
- Product-code implementation is delegated through Hermes; coordinator performs independent verification before every completion claim.

---

### Task 1: Strict release-set domain models and parser

**Files:**
- Create: `launcher/src/neko_launcher/application/software_update_models.py`
- Create: `launcher/tests/test_software_update_models.py`

**Interfaces:**
- Produces: `ComponentRelease`, `ReleaseSet`, `LocalReleaseIdentity`, `UpdateInvocationReason`, `UpdateState`, `UpdateCheckResult`, `parse_release_set(document: object) -> ReleaseSet`.
- `ComponentRelease` fields: `name`, `version`, `artifact_id`, `artifact_sha256`, `artifact_size`, `installed_identity_sha256`.
- `ReleaseSet` fields: `schema_version`, `channel`, `release_sequence`, `release_id`, `mandatory`, `minimum_supported_sequence`, `components`, an immutable tuple containing exactly the Launcher and Core `ComponentRelease` entries in that order.

- [ ] **Step 1: Write RED tests for an exact valid payload and strict rejection matrix**

```python
def test_parse_release_set_accepts_exact_beta_schema() -> None:
    release = parse_release_set(valid_release_document())
    assert release.release_sequence == 2
    assert tuple(c.name for c in release.components) == ("launcher", "core")

@pytest.mark.parametrize("mutate", [
    lambda d: {**d, "extra": True},
    lambda d: {**d, "channel": "stable"},
    lambda d: {**d, "release_sequence": 0},
    lambda d: {**d, "minimum_supported_sequence": 3},
])
def test_parse_release_set_rejects_non_exact_schema(mutate) -> None:
    with pytest.raises(ValueError):
        parse_release_set(mutate(valid_release_document()))
```

Add explicit cases for: missing/extra component; uppercase/non-64 SHA; artifact id/version/release id grammar; bool-as-int; Launcher size > 134217728; Core size > 1073741824; unknown component field; runtime fields named `credential`, `host`, `port`, or `cipher`.

- [ ] **Step 2: Run the focused file and capture genuine RED**

Run from `launcher`: `python -m pytest -q tests/test_software_update_models.py`
Expected: tests fail because `software_update_models`/symbols do not exist; collection must otherwise succeed.

- [ ] **Step 3: Implement immutable models and exact parser**

```python
class UpdateInvocationReason(str, Enum):
    STARTUP = "startup"
    MANUAL = "manual"

class UpdateState(str, Enum):
    NOT_CHECKED = "not_checked"
    CHECKING = "checking"
    LATEST = "latest"
    AVAILABLE = "available"
    MANDATORY = "mandatory"
    UNAVAILABLE = "unavailable"
    VERIFY_FAILED = "verify_failed"

@dataclass(frozen=True)
class ComponentRelease:
    name: str
    version: str
    artifact_id: str
    artifact_sha256: str
    artifact_size: int
    installed_identity_sha256: str
```

Implement exact-field checks and regexes from the spec. Sort returned components into fixed `(launcher, core)` order; never preserve arbitrary server order.

- [ ] **Step 4: Run focused tests and Ruff**

Run: `python -m pytest -q tests/test_software_update_models.py` and `python -m ruff check src/neko_launcher/application/software_update_models.py tests/test_software_update_models.py`.
Expected: PASS.

- [ ] **Step 5: Commit**

`git add launcher/src/neko_launcher/application/software_update_models.py launcher/tests/test_software_update_models.py && git commit -m "feat: define signed software release model"`

### Task 2: Exact-byte Ed25519 envelope verifier

**Files:**
- Modify: `launcher/pyproject.toml`
- Create: `launcher/src/neko_launcher/infrastructure/software_update_manifest.py`
- Create: `launcher/tests/software_update_helpers.py`
- Create: `launcher/tests/test_software_update_manifest.py`

**Interfaces:**
- Produces: `ReleaseManifestVerifier(key_registry: Mapping[str, bytes])`; method `verify(document: object) -> ReleaseSet`.
- Test helper produces `signed_envelope(payload: dict) -> dict[str, object]` using key id `neko-update-test-1`.

- [ ] **Step 1: Write RED tests for valid signature and fail-closed envelope handling**

```python
def test_valid_test_key_envelope_verifies_exact_payload_bytes() -> None:
    verifier = ReleaseManifestVerifier({TEST_KEY_ID: TEST_PUBLIC_KEY})
    assert verifier.verify(signed_envelope(valid_release_document())).release_id == "beta-0002"

def test_one_bit_payload_change_is_rejected() -> None:
    envelope = signed_envelope(valid_release_document())
    raw = bytearray(base64.b64decode(envelope["payload_b64"]))
    raw[-2] ^= 1
    envelope["payload_b64"] = base64.b64encode(raw).decode("ascii")
    with pytest.raises(ManifestVerificationError, match="SIGNATURE_INVALID"):
        verifier.verify(envelope)
```

Also test exact outer fields, envelope version, key-id grammar, unknown key, strict base64, payload > 49152, signature length != 64, invalid UTF-8/JSON, and that payload parsing is not called before signature success.

- [ ] **Step 2: Run focused tests and capture RED**

Run: `python -m pytest -q tests/test_software_update_manifest.py`.
Expected: missing verifier symbols, not a collection failure unrelated to the feature.

- [ ] **Step 3: Add explicit cryptography dependency and verifier**

In `pyproject.toml` dependencies add exactly `"cryptography==50.0.0"`. Implement:

```python
class ManifestVerificationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

class ReleaseManifestVerifier:
    def __init__(self, key_registry: Mapping[str, bytes]) -> None:
        self._keys = dict(key_registry)

    def verify(self, document: object) -> ReleaseSet:
        # strict outer schema -> strict base64 -> key lookup -> Ed25519 verify
        # -> UTF-8 JSON -> parse_release_set
```

Do not define or bundle a production private key. Do not silently accept `neko-update-prod-1` without an explicitly provisioned public key.

- [ ] **Step 4: Run focused tests, dependency metadata check, Ruff**

Run the manifest/model tests plus `python -c "import cryptography; print(cryptography.__version__)"`; expected `50.0.0`. Run Ruff on changed Python files.

- [ ] **Step 5: Commit**

`git add launcher/pyproject.toml launcher/src/neko_launcher/infrastructure/software_update_manifest.py launcher/tests/software_update_helpers.py launcher/tests/test_software_update_manifest.py && git commit -m "feat: verify signed software manifests"`

### Task 3: Anti-downgrade/update-decision policy

**Files:**
- Create: `launcher/src/neko_launcher/application/software_update_policy.py`
- Create: `launcher/tests/test_software_update_policy.py`

**Interfaces:**
- Produces: `evaluate_release(local: LocalReleaseIdentity, remote: ReleaseSet, reason: UpdateInvocationReason) -> UpdateCheckResult`.
- Diagnostic codes are closed constants: `DOWNGRADE_REJECTED`, `SAME_SEQUENCE_IDENTITY_CONFLICT`; successful decisions use no diagnostic code.

- [ ] **Step 1: Write RED decision-table tests**

```python
@pytest.mark.parametrize(("remote_seq", "mandatory", "minimum", "expected"), [
    (1, False, 1, UpdateState.LATEST),
    (2, False, 1, UpdateState.AVAILABLE),
    (2, True, 1, UpdateState.MANDATORY),
    (2, False, 2, UpdateState.MANDATORY),
])
def test_update_decision_table(remote_seq, mandatory, minimum, expected):
    result = evaluate_release(local_identity(sequence=1), remote_release(remote_seq, mandatory, minimum), UpdateInvocationReason.STARTUP)
    assert result.state is expected
```

Add downgrade and same-sequence identity conflict rejection, same-sequence exact identity -> LATEST, and changed-components tuple determined only by `installed_identity_sha256`.

- [ ] **Step 2: Run focused tests and capture RED**

- [ ] **Step 3: Implement pure policy with no network/filesystem**

`VERIFY_FAILED` results must carry only safe metadata/closed diagnostic codes. For same sequence, every component identity must match. For remote sequence > local, compute changed components in fixed Launcher/Core order.

- [ ] **Step 4: Run models+manifest+policy tests and Ruff**

- [ ] **Step 5: Commit**

`git commit -m "feat: enforce software update anti-downgrade policy"` with only policy/tests staged.

### Task 4: Local installed release identity

**Files:**
- Create: `launcher/src/neko_launcher/infrastructure/software_release_identity.py`
- Create: `launcher/tests/test_software_release_identity.py`

**Interfaces:**
- Produces: `load_local_release_identity(*, release_sequence: int, release_id: str, launcher_version: str, launcher_executable: Path, core_version: str, core_manifest: Path) -> LocalReleaseIdentity`.
- Produces: `sha256_file(path: Path) -> str` with streaming 1 MiB reads.

- [ ] **Step 1: RED tests** proving exact SHA-256 for a fake Launcher file and Core canonical-manifest file, missing/non-file input fails closed, and sequence 0 is allowed only with release id exactly `dev-unpublished`.

- [ ] **Step 2: Run focused tests and capture RED**

- [ ] **Step 3: Implement streaming identity loader**

```python
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

Do not persist identity state and do not hash arbitrary directories. Core identity is the canonical manifest file hash.

- [ ] **Step 4: Run focused tests and Ruff**

- [ ] **Step 5: Commit** `feat: read admitted software release identity`.

### Task 5: Streaming artifact verifier

**Files:**
- Create: `launcher/src/neko_launcher/infrastructure/software_update_artifact.py`
- Create: `launcher/tests/test_software_update_artifact.py`

**Interfaces:**
- Produces: `VerifiedArtifact(component: str, path: Path, sha256: str, size: int)` and `verify_artifact(path: Path, component: ComponentRelease) -> VerifiedArtifact`.
- Errors use closed codes `ARTIFACT_MISSING`, `ARTIFACT_TOO_LARGE`, `ARTIFACT_SIZE_MISMATCH`, `ARTIFACT_HASH_MISMATCH`.

- [ ] **Step 1: RED tests** for exact bytes, wrong size, wrong hash, Launcher >128 MiB policy rejection without allocating a giant buffer (sparse/truncated test file), Core >1 GiB metadata rejection before reading, and current file remains unmodified.

- [ ] **Step 2: Run focused tests and capture RED**

- [ ] **Step 3: Implement size gate + streaming SHA**; open read-only; never chmod/move/delete the input.

- [ ] **Step 4: Run focused trust-core tests and Ruff**

- [ ] **Step 5: Commit** `feat: verify software update artifacts`.

### Task 6: Owner/build testable signing tool

**Files:**
- Create: `scripts/sign_software_release.py`
- Create: `launcher/tests/test_sign_software_release.py`

**Interfaces:**
- CLI: `python scripts/sign_software_release.py --input <release.json> --private-key-file <raw32-or-pem> --key-id <id> --output <envelope.json>`.
- Output outer envelope uses exact keys `envelope_version`, `key_id`, `payload_b64`, `signature_b64`.

- [ ] **Step 1: RED test** invokes the script with the test key in a temporary file, setting `PYTHONPATH` to `E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher\src` in the child-process environment so the repo script imports the current worktree package. Verify deterministic canonical payload bytes (`json.dumps(release_document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`), verify output with `ReleaseManifestVerifier`, and assert captured stdout/stderr never contain private-key hex/base64.

- [ ] **Step 2: Run focused test and capture RED**

- [ ] **Step 3: Implement signer** that first calls `parse_release_set`, rejects production key material from command-line text (key must be file input), writes output with restrictive normal file semantics, prints only safe key id/release id/sequence/output path, and never publishes.

- [ ] **Step 4: Run all Slice-1 tests + full Ruff**

Run: `python -m pytest -q tests/test_software_update_models.py tests/test_software_update_manifest.py tests/test_software_update_policy.py tests/test_software_release_identity.py tests/test_software_update_artifact.py tests/test_sign_software_release.py` and `python -m ruff check src tests ../../scripts/sign_software_release.py`.

- [ ] **Step 5: Slice-1 regression checkpoint**

Run the full existing Launcher suite with canonical Core artifact. Expected existing baseline plus new tests, zero failures. Do not bump Launcher version or build an Owner artifact yet.
