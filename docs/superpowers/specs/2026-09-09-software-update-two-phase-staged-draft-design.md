# Software Update: Two-Phase Staged-Draft Publication Architecture — Design Specification

- Date: 2026-09-09
- Status: OWNER/USER APPROVED ARCHITECTURAL DESIGN SPECIFICATION (AMENDED: Sequence 1 Burn & Recovery Authority Ruling)
- Baseline: `release/5.1` at `419c69ecbd2d9fdbf8f48179b844e74ecae77b9f` (Engineering baseline at `419a3ec593709b84afdf8e74a70ce737cd7832d9`)
- Supersedes: Publication-handoff, artifact-assembly, and workflow-publication sections of `2026-09-08-software-update-github-releases-design.md` (specifically Section 8 and related single-phase CI release creation assumptions).
- Preserves: All client-side GitHub Releases discovery, unauthenticated endpoint restrictions, transport allowlists, manual redirect policies, Ed25519 envelope verification, canonical JSON enforcement, manifest admission, installed Updater compatibility binding, sequence anti-downgrade, generation construction, and local transaction semantics documented in `2026-09-08-software-update-github-releases-design.md` remain active, authoritative, and unchanged.

---

## 1. Executive Summary and Architectural Principles

This specification defines the authoritative release publication architecture for Neko Family Proxy. It replaces the prior single-phase continuous integration (CI) release creation sketch with a strict **Two-Phase Staged-Draft Publication Architecture**.

The core tenets of this architecture are:
1. **Local Candidate Freezing & Offline Signing**: Binary compilation, Core assembly, smoke verification, candidate byte freezing, and Ed25519 cryptographic signing occur exclusively on an authorized, controlled local operator machine. The production private release signing key remains offline; it never touches GitHub, CI runners, or repository history.
2. **Local Gate #2 Normative Ordering**: Before any remote Git push, tag push, or GitHub draft creation occurs, local qualification MUST execute in strict normative sequence: freeze exact candidate bytes; execute Launcher packaged smoke and Updater self-check directly on those exact frozen bytes; freshly recompute Launcher/Updater/Core sizes+SHA-256 and Core installed identity after smoke; construct and sign canonical `release-v2.json` using those fresh measurements; locally verify canonical envelope/signature/exact three component bindings against those same frozen bytes; run repository safety and scope checks; and obtain independent review approval (Critical 0 / Important 0). Any byte mutation after fresh measurement invalidates Gate #2 and requires staging a new candidate and resequencing as applicable.
3. **Draft Staging on GitHub**: The authorized operator pushes the approved commit/tag and uploads the frozen candidate assets to an unpublished GitHub **DRAFT** release targeting the exact commit. Asset names, sizes, and binary contents are immutable once signed; no re-compilation, re-signing, or asset clobbering is permitted.
4. **Remote Publication as an Independent Authority Gate**: Final publication (`draft=false`) MUST occur in GitHub Actions, never directly from a local workstation. The publication workflow does NOT compile binaries, upload update payloads, or accept local filesystem paths. Instead, it acts strictly as an **independent remote authority gate**: it accepts the immutable numeric GitHub draft release ID (strictly distinguished from the signed manifest's string `release_id`), enforces envelope `key_id == neko-update-prod-1` bound strictly to in-repo `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`, downloads the staged assets as raw binary streams, verifies the assets against the signed manifest using `verify_github_release_assets.py`, enforces first-release fail-closed parameters, re-checks draft state and asset ID bindings immediately before publishing, and activates the release via GitHub REST API (`PATCH draft=false`).
5. **Fail-Closed Guarantee**: Any mismatch in hashes, byte sizes, canonical formatting, Ed25519 signatures, draft/prerelease state, commit targeting, asset identity, key ID binding, or first-release expected parameters causes immediate workflow abortion. The draft release remains unpublished and completely invisible to client update discovery.

### 1.1 Sequence 1 Burn and Recovery Authority Ruling
Following an independent Sol recovery ruling (Critical 0 / Important 0):
During local qualification run `r4`, canonical `release-v2.json` was signed once with `release_sequence: 1` and `release_id: stable-0001`. Gate #2 was subsequently **REJECTED** due to missing retained Step 2 audit evidence (specifically failure to persist command transcripts, separate stdout/stderr files, and execution timestamps for Launcher smoke and Updater self-check).
Under the strict Byte Mutation Invalidation and Monotonic Sequence Rules (Section 4.2 and Section 11.1), `release_sequence: 1` and `release_id: stable-0001` are **HISTORICAL SPENT-UNPUBLISHED AUTHORITY**. They must never be published, staged to GitHub, or regenerated. No remote release side effects occurred (no remote commit push, tag push, draft release, or asset upload).

The operative first-public-release publication contract is amended to:
- `release_sequence`: `2`
- `release_id`: `stable-0002`
- `minimum_supported_sequence`: `1`
- `release_tag`: `v5.1.0a3`
- Component versions: `5.1.0a3` (`launcher`, `updater`, `core`)
- Channel: `stable`
- Updater protocol: `1..1` (`minimum: 1, maximum: 1`)
- Envelope signing key ID: `neko-update-prod-1` bound to `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`

**Why minimum_supported_sequence Remains 1**:
`minimum_supported_sequence` remains `1` because it defines the monotonic client compatibility floor and mandatory update boundary for installed clients. The internal spending of sequence 1 during an incomplete, uncompleted local Gate #2 run does not revoke client compatibility or advance any installed client's high-water mark, as sequence 1 was never published to or observed by clients.

**No Architecture, Schema, or Client-Policy Change**:
This amendment introduces zero changes to architecture, envelope schema, client update protocol, or security boundaries. It is strictly a release-parameter update (`sequence=2`, `release_id=stable-0002`) and a durable Gate #2 audit-evidence contract specification.

**Binary Reuse Policy**:
PyInstaller PE executables (`NekoLauncher.exe`, `NekoUpdater.exe`) and Core bundle (`NekoProxyCore.zip`) from candidate r4 may be reused only byte-identically into a fresh candidate staging directory (e.g. candidate r5), backed by cryptographic provenance proof (source/destination SHA-256 and byte equality) and a complete restart of the Gate #2 qualification sequence from Step 1.

---

## 2. Invalidation of Single-Phase CI Publication Model

The initial implementation sketch assumed GitHub Actions could compile the client binaries (`NekoLauncher.exe`, `NekoUpdater.exe`), accept local filesystem paths to external assets (`NekoProxyCore.zip`, `release-v2.json`), upload them to a GitHub release, and publish the release in one continuous workflow run. That model is architecturally invalid for three fundamental reasons:

### 2.1 Hosted Runner Inaccessibility of Local Storage
Hosted GitHub Actions runners (`windows-latest`) execute in isolated, ephemeral Microsoft Azure virtual machines. They have no network or filesystem access to the operator's workstation storage (such as `E:\...` paths). Passing local workstation paths as workflow dispatch inputs is physically impossible to execute on hosted runners.

### 2.2 PyInstaller Non-Determinism and Binary Non-Reproducibility
Executables generated by PyInstaller are demonstrably non-byte-reproducible across different machines, build environments, and invocation timestamps, even when product source inputs, compiler flags, and build specifications are identical. PyInstaller embeds build-time timestamps, file system ordering artifacts, and internal metadata into the generated portable executable (PE) headers and archive structures.
Consequently, an executable compiled on a GitHub Actions hosted runner will possess a different SHA-256 digest from an executable compiled and tested locally on the operator's machine.

### 2.3 Strict Offline Cryptographic Signature Authority
The Software Update architecture relies on an Ed25519 signature in `release-v2.json` as the sole cryptographic release authority. This signature commits to the exact SHA-256 digests and byte counts of `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip`.
- If CI re-compiles the binaries, the resulting hashes will not match the signed manifest, causing client verification to fail closed.
- If CI were tasked with signing the newly compiled binaries, the offline Ed25519 private key would have to be uploaded to GitHub Secrets or exposed to CI runners. This would fatally violate the project's offline security boundary, exposing the master signing capability to supply-chain attacks, workflow injection, and platform compromise.
- Therefore, the exact bytes that are signed offline on the local machine MUST be the exact bytes uploaded and published to clients.

### 2.4 Structural Realignment: CI as Authority Gate, Not Artifact Authority
GitHub Actions is not an artifact creation authority for production releases. GitHub Actions functions strictly as a remote **publication authority gate**:
- It does not build update binaries in the publication path.
- It does not sign release manifests.
- It enforces independent remote verification over the staged draft release assets before transitioning the draft to public status.

---

## 3. Two-Phase Architecture Overview

The release lifecycle is strictly partitioned into two sequential phases across the trust boundary:

```
[ PHASE 1: LOCAL OPERATOR ENVIRONMENT (Controlled Machine) ]
  1. Build candidate PE executables (NekoLauncher.exe, NekoUpdater.exe)
  2. Assemble candidate Core bundle (NekoProxyCore.zip) & verify inventory identity
  3. Gate #2 normative sequence (MUST execute in exact order):
     a. Freeze exact candidate bytes in local candidate staging directory
     b. Execute Launcher packaged smoke & Updater self-check on those exact frozen bytes
     c. Freshly recompute Launcher/Updater/Core sizes+SHA-256 & Core installed identity
     d. Construct & sign canonical release-v2.json using fresh measurements (offline key)
     e. Locally verify canonical envelope, signature, and 3-component bindings
     f. Execute repository safety and clean worktree checks
     g. Obtain independent review approval (Critical 0 / Important 0)
  4. Git commit & tag push to GitHub (v5.1.0a3 -> approved commit)
  5. Create GitHub DRAFT release targeted at exact commit (draft=true, prerelease=false)
  6. Upload exact four assets (clobber=false)
  7. Capture immutable numeric GitHub release_id and four name->asset_id bindings
                     │
═════════════════════╪══════════════════════════════════════════════════════════
                     │ Trust Boundary (Network / GitHub API)
═════════════════════╪══════════════════════════════════════════════════════════
                     ▼
[ PHASE 2: REMOTE CI AUTHORITY GATE (GitHub Actions Hosted Runner) ]
  8. Operator triggers workflow_dispatch with numeric release_id, release_tag, expected_target
  9. Runner checks out exact approved target commit
 10. Enforce key binding: require envelope key_id == neko-update-prod-1 from in-repo
     PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']
 11. Fetch draft release object by numeric release_id (require draft=true, prerelease=false)
 12. Download exact four assets by asset_id as raw binary streams
 13. Run verify_github_release_assets.py:
     - Canonical JSON outer envelope check
     - Ed25519 envelope signature verification via PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']
     - Release tag (v5.1.0a3) and channel (stable) binding
     - Fail-closed first-release value checks (sequence=2, min_seq=1, string release_id=stable-0002,
       protocol=1..1, component versions=5.1.0a3; sequence 1 / stable-0001 spent-unpublished)
     - Exact file names, formats, sizes, and SHA-256 hashes against signed manifest
 14. Pre-publish revalidation: re-read release by numeric release_id, assert state & asset_ids unchanged
 15. Publish release: PATCH /repos/.../releases/:release_id with draft=false
 16. Post-publish verification: re-read numeric release_id (draft=false) and check /releases/latest
```

---

## 4. Phase 1: Local Candidate Freeze, Offline Signing, Gate #2, and Draft Staging

All actions in Phase 1 take place on the controlled local operator machine.

### 4.1 Candidate Construction and Staging Isolation
1. The operator builds `NekoLauncher.exe` and `NekoUpdater.exe` using clean PyInstaller specifications from an audited, clean repository tree.
2. The operator packages `NekoProxyCore.zip` from approved Core binary distributions, calculating the installed identity digest from the sorted canonical inventory.
3. Candidate files (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`) are placed into an isolated local candidate staging directory.

### 4.2 Gate #2 Normative Ordering (MUST-Order Sequence)
Gate #2 is the mandatory local release qualification checkpoint. Remote publication actions (Git commit push, tag push, draft release creation, asset upload) are strictly prohibited until Gate #2 is passed.
Gate #2 is not merely an operator checklist; it MUST execute in the following strict normative order:

1. **Freeze Exact Candidate Bytes**:
   Candidate files are isolated in the dedicated candidate staging directory. From this point forward, candidate files are frozen: no edits, no re-compilations, and no file touch operations are permitted.
2. **Execute Packaged Smoke and Self-Check on Frozen Bytes**:
   Execute Launcher packaged smoke tests and Updater self-check directly on those exact frozen candidate bytes within their staging environment.
3. **Freshly Recompute Measurements After Smoke**:
   Directly following the successful completion of smoke tests and self-check, freshly recompute:
   - Byte sizes and SHA-256 digests for `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip`.
   - Core installed identity SHA-256 digest from the canonical inventory of the frozen `NekoProxyCore.zip`.
   These fresh post-smoke measurements become the authoritative candidate descriptors.
4. **Construct and Sign Canonical Manifest (release-v2.json)**:
   The production private signing key resides exclusively in the operator's secure local authority (Vault MASTER / secure local keystore) and is never transferred to any remote system. An authorized local tool constructs the `release-v2` payload using the fresh measurements from Step 3:
   - `channel`: `stable`
   - `release_sequence`: `2` (operative recovery sequence; sequence 1 is spent-unpublished)
   - `minimum_supported_sequence`: `1` (client compatibility floor remains 1; sequence burn does not advance client high-water mark)
   - `release_id`: `stable-0002` (signed string identifier; historical `stable-0001` is spent-unpublished; see Section 4.5 for distinction from GitHub numeric release ID)
   - `key_id`: `neko-update-prod-1`
   - `updater_protocol`: `{"minimum": 1, "maximum": 1}`
   - Closed component dictionary for `{launcher, updater, core}` containing exact versions (`5.1.0a3`), formats (`raw-pe-v1`, `zip-core-v1`), artifact IDs, artifact sizes, artifact SHA-256 digests, and installed identity SHA-256 digests.
   The manifest is signed using the offline Ed25519 private key corresponding to `neko-update-prod-1`. The resulting `release-v2.json` is serialized strictly in canonical JSON (`canonical_json_dumps`) and must not exceed 65,536 bytes.
5. **Locally Verify Envelope, Signature, and Component Bindings**:
   Locally execute cryptographic verification (`verify_release_envelope_v2`) using the public key bound to `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`. Verify that:
   - The signed envelope parses, canonical JSON round-trip succeeds, and signature is valid.
   - The signed `key_id` is exactly `neko-update-prod-1`.
   - The signed `artifact_size`, `artifact_sha256`, and `installed_identity_sha256` descriptors match the frozen candidate bytes bit-for-bit and byte-for-byte.
   - The candidate `NekoProxyCore.zip` passes Core bundle proof (ZIP integrity, file layout, permissions, canonical inventory installed identity match).
6. **Execute Repository Safety and Scope Checks**:
   Execute `scripts/check_repository_safety.py` and inspect Git status. Verify that the repository tree is clean, no uncommitted modifications exist, no untracked release debris remains, and no leaked private authority materials or secrets are present.
7. **Obtain Independent Review Clearance**:
   Formal independent review passes with Critical 0 and Important 0 (C0/I0) findings.

**Prerequisite Rule for Remote Operations**: Only after all seven steps above have been completed successfully in this exact sequence may remote push, Git tag push, draft release creation, and asset upload occur.

**Byte Mutation Invalidation Rule**: Any byte mutation, file touch, compiler re-execution, or smoke test re-run after the fresh measurement in Step 3 immediately invalidates Gate #2. If any candidate file is altered or re-tested after measurement, the candidate is void, and the operator must stage a new candidate and restart the entire qualification sequence from Step 1. If `release-v2.json` was already signed, that `release_sequence` is permanently spent and the subsequent candidate must increment `release_sequence`.

### 4.2.1 Durable Recovery Gate #2 Evidence Contract
To satisfy complete operational auditability and prevent recurrence of the Step 2 evidence retention failure from rejected run r4, any Gate #2 qualification attempt MUST adhere to the following durable evidence contract:

1. **Fresh Candidate ID and Path Isolation**:
   - The qualification attempt MUST use a fresh, distinct candidate staging directory and candidate identifier (e.g. `candidate-r5` at `E:\Github\candidate-release-5.1.0a3-r5`).
   - The candidate staging directory must contain strictly the candidate files being qualified.
2. **Provenance and Byte-Equality Verification**:
   - When reusing binaries from candidate r4, provenance must be mathematically proven before Step 2 begins: source file paths, source file sizes and SHA-256 digests, destination file sizes and SHA-256 digests, and bit-for-bit byte equality must be validated and recorded in a retained provenance manifest (`provenance_manifest.json`).
3. **Execution Transcripts and Exit Codes for Step 2**:
   - For both Launcher packaged smoke tests and Updater self-check (`NekoUpdater.exe --self-check`), the audit log must capture:
     - Exact `argv` command invocation
     - Exact `cwd` (working directory)
     - UTC ISO-8601 start timestamp
     - UTC ISO-8601 end timestamp
     - Elapsed duration in seconds
     - Process exit code (must be `0`)
4. **Separate Retained Stdout and Stderr Streams**:
   - For every Step 2 command, stdout and stderr MUST be captured into separate retained files (e.g. `launcher_smoke.stdout.log`, `launcher_smoke.stderr.log`, `updater_self_check.stdout.log`, `updater_self_check.stderr.log`), even if a stream is zero bytes. Zero-byte files must be retained as explicit proof of clean stderr.
5. **Candidate Byte Stability (Pre-Smoke vs Post-Smoke Hash Equality)**:
   - Candidate byte sizes and SHA-256 digests must be measured immediately prior to smoke testing (pre-smoke) and immediately following smoke completion (post-smoke).
   - Pre-smoke and post-smoke sizes and SHA-256 digests MUST match bit-for-bit, proving that running the binaries did not mutate candidate bytes on disk.
6. **Normative Sequence Timing Guard**:
   - Step 3 (fresh post-smoke measurement) MUST have a recorded start timestamp that is strictly later than the recorded end timestamps of BOTH Step 2 executions (Launcher smoke and Updater self-check).
7. **No Executable Runs After Step 3 Measurement**:
   - Once Step 3 fresh measurement commences, no candidate executable (`NekoLauncher.exe`, `NekoUpdater.exe`) may be executed or touched again in that candidate directory. Any execution after Step 3 measurement voids the candidate immediately.
8. **Retention of All Ceremony Commands and Results**:
   - Retained evidence files must capture exact commands, inputs, transcripts, and outputs for:
     - Step 4: canonical manifest construction and Ed25519 signing.
     - Step 5: local envelope, signature, and 3-component verification against candidate bytes.
     - Step 6: repository safety checks (`check_repository_safety.py`) and git clean worktree verification.
     - Step 7: independent review clearance (C0/I0).
9. **Strict Ordered Ceremony Log**:
   - A single, chronologically ordered ceremony log (`ceremony.log` / `gate2_execution_audit.log`) must record each step's transition, timestamps, and outcomes in strict normative order.
10. **Evidence Index with Cryptographic Digests**:
    - An authoritative evidence index file (`evidence_index.sha256` / `EVIDENCE_MANIFEST.json`) must enumerate and SHA-256 hash every retained log, transcript, output file, and candidate artifact.
11. **Quarantine of Rejected Run r4 Evidence**:
    - The rejected run `r4` evidence must remain quarantined in its own separate directory (e.g. `candidate-release-5.1.0a3-r4-REJECTED/`), explicitly labeled as rejected/incomplete, and never mixed with recovery candidate evidence.

### 4.3 Git Push and Staged Draft Release Creation
Once Gate #2 is formally passed:
1. The approved release commit is pushed to the canonical remote repository (`Valeneko-pranmong/Neko-Family-Proxy`).
2. The release Git tag (`v5.1.0a3`) pointing to the approved commit is pushed to the remote repository.
3. The operator creates a GitHub release via the GitHub REST API or CLI (`gh release create`) with the following strict parameters:
   - Tag: the approved release tag (`v5.1.0a3`).
   - Target: the approved Git commit SHA (`target_commitish`).
   - Draft: `true` (mandatory; the release must NOT be published).
   - Prerelease: `false`.
   - Title and release notes: matching the release identity.

### 4.4 Asset Upload and Immutable Binding Capture
1. The operator uploads exactly four trusted assets to the newly created draft release:
   - `NekoLauncher.exe`
   - `NekoUpdater.exe`
   - `NekoProxyCore.zip`
   - `release-v2.json`
2. Uploads must use non-clobbering semantics (`--clobber=false`).
3. The operator captures from GitHub API:
   - The immutable positive integer `release_id` assigned by GitHub to the draft release.
   - The four immutable positive integer `asset_id` values bound to each of the four uploaded asset names.
4. The draft release is now staged and awaiting Phase 2 remote gate verification.

### 4.5 Explicit Distinction of Release Identifiers
To prevent operational or architectural confusion, this specification strictly distinguishes two distinct concepts that share the name "release ID":
1. **Signed Manifest Envelope Release ID** (`manifest_doc['release_id']`):
   A string value embedded inside the cryptographically signed `release-v2.json` envelope that uniquely designates the logical release identity within the application update protocol (for this operative first-public-release, strictly `"stable-0002"`; historical `"stable-0001"` is permanently spent-unpublished).
2. **GitHub Draft Release ID** (`github_release_id` / workflow input `release_id`):
   An immutable positive 64-bit integer assigned by GitHub's REST API to the staged release object upon creation. It is used solely by the publication workflow for REST API draft lookup, asset streaming, pre-publish TOCTOU validation, and `PATCH draft=false` activation.

---

## 5. Phase 2: Remote Publication Authority Gate (GitHub Actions)

Final release publication is performed exclusively by GitHub Actions workflow execution.

### 5.1 Workflow Dispatch Interface Contract
The publication workflow is triggered manually via `workflow_dispatch`. Its input contract is strictly constrained:

- `release_id` (required, string/integer): The immutable numeric identifier assigned by GitHub to the existing draft release (distinct from the signed envelope string `release_id`).
- `release_tag` (required, string): The expected Git tag (must match `^v[A-Za-z0-9._+-]{1,64}$`; for this first release, strictly `v5.1.0a3`).
- `expected_target` (required, string): The expected full 40-character Git commit SHA.
- `publish_release` (required, boolean): Must be explicitly set to `true` to authorize publication.

**Explicit Input Prohibitions**:
- No local filesystem paths (e.g. `core_artifact_path`, `signed_manifest_path`) are accepted.
- No public key file path input (`release_public_key_path`) or inline key material is accepted.
- No binary file uploads or CI compilation inputs are accepted in the publication path.

### 5.2 Production Key-ID Binding and Public Key Derivation
The workflow executes on `windows-latest` (or `ubuntu-latest`). It checks out the repository at `expected_target`.
To eliminate any risk of public key substitution, key forgery, or arbitrary key-ID bypass:
1. **No External Key Inputs**: The workflow does NOT accept an external public key path parameter or arbitrary key payload.
2. **Exact Production Key ID Requirement**: For this production release, the signed envelope `key_id` MUST be exactly `neko-update-prod-1`. Any other key ID fails closed immediately.
3. **Exact Registry Binding**: Verification MUST resolve strictly through the registry binding `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']` defined in `neko_launcher.updater.trust`. It is cryptographically and architecturally **insufficient** to take the 32-byte public key and register it in a verifier keyring under an arbitrary or manifest-supplied key ID dictionary (e.g. `{manifest['key_id']: key_bytes}`), as doing so would allow manifests with unapproved key IDs to pass verification.
4. **Verifier CLI Integration Bridge**: If materializing a temporary public-key file for the current verifier CLI (`scripts/verify_github_release_assets.py --public-key-file`):
   - The workflow MUST separately and explicitly assert that the manifest envelope `key_id` is exactly `neko-update-prod-1`.
   - The workflow MUST source the 32 public key bytes exclusively from the fixed `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']` registry entry at the checked-out commit.
   - Alternatively, the verifier CLI must be invoked or adapted to verify directly through the in-repo `PRODUCTION_RELEASE_PUBLIC_KEYS` registry binding.
   - Any manifest specifying any other `key_id` fails closed.

### 5.3 Remote Asset Acquisition by Immutable Asset ID
To guarantee that the files verified are the exact files published:
1. The workflow queries GitHub REST API: `GET /repos/:owner/:repo/releases/:release_id` using the provided immutable GitHub numeric `release_id`.
2. The workflow verifies the release metadata:
   - `id` matches the numeric `release_id`.
   - `draft` is strictly `true`.
   - `prerelease` is strictly `false`.
   - `tag_name` strictly matches `release_tag`.
   - `target_commitish` strictly matches `expected_target`.
3. The workflow inspects the `assets` array and ensures:
   - Each of the four required update assets (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, `release-v2.json`) exists exactly once.
   - Asset IDs are unique positive integers.
   - Permitted human-facing extra assets (such as `SHA256SUMS.txt`) are ignored.
4. For each of the four required assets, the workflow downloads the file content directly by its numeric `asset_id`:
   - Endpoint: `GET /repos/:owner/:repo/releases/assets/:asset_id`
   - Header: `Accept: application/octet-stream`
   - The response is streamed as raw binary bytes directly to disk in an isolated verification directory.

### 5.4 Remote Verification Gate (verify_github_release_assets.py)
The workflow executes `scripts/verify_github_release_assets.py` against the downloaded files and draft release metadata:
```text
python scripts/verify_github_release_assets.py \
  --release-json release/metadata/draft-release.json \
  --download-dir release/remote-verification \
  --public-key-file "$KEY_PATH" \
  --expected-tag "$RELEASE_TAG" \
  --expected-target "$EXPECTED_TARGET" \
  --require-draft
```

The verifier and publication authority enforce the following checks:
1. **Draft Enforcement**: Fails if `draft` is false or `prerelease` is true.
2. **Commit & Tag Binding**: Fails if `tag_name` or `target_commitish` deviate from expected values.
3. **Manifest Size & Canonical JSON**: Fails if `release-v2.json` exceeds 65,536 bytes, contains duplicate keys, or fails canonical byte round-trip:
   `canonical_json_dumps(json.loads(manifest_bytes)) == manifest_bytes`.
4. **Key-ID & Cryptographic Envelope Verification**:
   - Fails if the manifest envelope `key_id` is not strictly `neko-update-prod-1`.
   - Fails if `verify_release_envelope_v2()` fails against `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`.
5. **First-Release Fail-Closed Parameters (Normative for v5.1.0a3)**:
   For THIS first public release `v5.1.0a3`, Phase 2 publication authority MUST reject unless the signed envelope satisfies:
   - `channel` is strictly `stable`.
   - `release_sequence` is strictly `2` (sequence `1` spent-unpublished in rejected Gate #2 r4).
   - `minimum_supported_sequence` is strictly `1` (client compatibility floor remains 1; sequence burn does not advance client high-water mark).
   - Signed string `release_id` is strictly `stable-0002` (clearly distinguished from GitHub's numeric release ID; historical `stable-0001` spent-unpublished).
   - `updater_protocol` range has `minimum` equal to `1` and `maximum` equal to `1`.
   - Component versions are all strictly `5.1.0a3`:
     - `components['launcher'].version == "5.1.0a3"`
     - `components['updater'].version == "5.1.0a3"`
     - `components['core'].version == "5.1.0a3"`
   - Key and tag binding remains `v5.1.0a3`: `expected_tag` equals `v5.1.0a3` and matches `"v" + launcher.version`.
   *Future releases may generalize expected values only through reviewed release input/authority rules; do not hard-code unrelated future policy in this spec.*
6. **Descriptor & Asset Format Checks**:
   - `launcher`: artifact ID `NekoLauncher.exe`, format `raw-pe-v1`.
   - `updater`: artifact ID `NekoUpdater.exe`, format `raw-pe-v1`.
   - `core`: artifact ID `NekoProxyCore.zip`, format `zip-core-v1`.
7. **Byte-Level Hash & Size Equality**:
   - Local downloaded file size must equal the manifest's signed `artifact_size`.
   - GitHub asset metadata `size` must equal the manifest's signed `artifact_size`.
   - Local downloaded file SHA-256 digest must match the signed `artifact_sha256` exactly.

### 5.5 Pre-Publish State Revalidation and Atomic Binding Lock
Before making the mutating API call to publish the release, the workflow must protect against time-of-check to time-of-use (TOCTOU) tampering:
1. The workflow re-queries `GET /repos/:owner/:repo/releases/:release_id` using the numeric `release_id`.
2. The workflow verifies:
   - Release `id` is unchanged.
   - `draft` is still `true`.
   - `prerelease` is still `false`.
   - `tag_name` is unchanged.
   - `target_commitish` is unchanged.
   - For all four required asset names, the `asset_id` in the current release object is identical to the `asset_id` that was downloaded and verified in step 5.3.
3. If any field or asset ID has changed, the workflow aborts immediately with a fatal error.

### 5.6 Publication Activation via Immutable ID
Only after all checks in Section 5.4 and Section 5.5 pass unconditionally:
1. The workflow executes:
   - `PATCH /repos/:owner/:repo/releases/:release_id`
   - Payload: `{"draft": false}`
2. The call is addressed strictly by the immutable numeric `release_id`.
3. The release is now formally published on GitHub.

### 5.7 Post-Publish Readback and `/releases/latest` Resolution
Immediately following the PATCH request:
1. The workflow re-reads `GET /repos/:owner/:repo/releases/:release_id` and asserts:
   - `draft == false`
   - `prerelease == false`
   - `tag_name == release_tag`
   - All four `name -> asset_id` bindings remain identical.
2. The workflow queries the public unauthenticated latest endpoint:
   - `GET /repos/:owner/:repo/releases/latest`
3. The workflow asserts:
   - Returned release `id` equals numeric `release_id`.
   - Returned `tag_name` equals `release_tag`.
   - All four required assets are present and report the identical `asset_id` and `size`.

### 5.8 Fail-Closed Rules and Immutable Invariants
The following rules are non-negotiable and fail-closed:
1. **Never Regenerate Manifest Under Same Sequence**: If a release attempt is rejected after signing, the `release_sequence` number used is dead. A subsequent release candidate must use a strictly higher `release_sequence`.
2. **Never Clobber Verified Assets**: Uploading with `--clobber=true` or replacing an asset after verification is prohibited.
3. **Never Substitute CI-Built Binaries**: No binary built by CI may ever be substituted into a candidate release.
4. **Draft Remains Unpublished on Any Failure**: If any step of Phase 2 fails, the workflow terminates with non-zero exit code. The draft release remains unpublished and invisible to clients.
5. **Strict Key ID Enforcement**: If the signed envelope specifies any `key_id` other than `neko-update-prod-1` or fails verification against `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`, the workflow terminates immediately.
6. **First-Release Parameter Invariance**: For this initial public release `v5.1.0a3`, any discrepancy in channel (`stable`), release sequence (`2`), minimum supported sequence (`1`), signed envelope release ID (`stable-0002`), updater protocol (`1..1`), or component versions (`5.1.0a3`) causes immediate publication abortion. Sequence `1` / `stable-0001` was spent-unpublished in rejected Gate #2 r4 and must never be published or regenerated.

---

## 6. Separation of CI Build Jobs from Release Authority

GitHub Actions workflows in the repository may include automated build jobs (e.g. compiling executables, running unit tests, or packaging artifacts on tag pushes):
1. **CI Builds are Diagnostic Only**: Binaries produced by automated CI jobs on push or pull request events are strictly CI diagnostics and testing artifacts.
2. **CI Artifacts Possess No Release Authority**: CI-built artifacts must never be treated as candidate release binaries. They must not be automatically uploaded to releases or published to users.
3. **Separate Future Redesign Required**: If a future architecture introduces hosted reproducible builds or online HSM signing, that must be designed and approved in a separate specification. Under this specification, release authority belongs exclusively to locally frozen, offline-signed candidate binaries.

---

## 7. First-Release Concrete Parameters (Normative Contract)

For THIS first public release `v5.1.0a3`, Phase 2 publication authority MUST reject unless the signed envelope satisfies every exact parameter in the following normative contract:

| Parameter | Value | Definition / Authority |
|---|---|---|
| Release Channel | `stable` | Production stable distribution channel |
| Release Tag | `v5.1.0a3` | Git tag matching `v` + signed Launcher version |
| Release Sequence | `2` | Monotonic anti-downgrade counter (operative first public release; sequence 1 spent-unpublished in rejected Gate #2 r4) |
| Minimum Supported Sequence | `1` | Monotonic floor for client compatibility (sequence burn does not advance client high-water mark) |
| Signed Envelope Release Identifier | `stable-0002` | Unique release envelope identity string in manifest (`stable-0001` spent-unpublished) |
| GitHub Draft Release Identifier | Immutable positive integer | Assigned dynamically by GitHub API upon draft creation (distinct from envelope string `release_id`) |
| Envelope Signing Key ID | `neko-update-prod-1` | Bound strictly to `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']` |
| Updater Protocol Range | `1..1` | Compatible with installed Updater protocol `1` (`minimum: 1, maximum: 1`) |
| Component: `launcher` | Version `5.1.0a3`, format `raw-pe-v1`, artifact `NekoLauncher.exe` | Exact component descriptor |
| Component: `updater` | Version `5.1.0a3`, format `raw-pe-v1`, artifact `NekoUpdater.exe` | Exact component descriptor |
| Component: `core` | Version `5.1.0a3`, format `zip-core-v1`, artifact `NekoProxyCore.zip` | Exact component descriptor |
| Signed Components Set | Exact closed set: `{launcher, updater, core}` | Closed 3-component dictionary |
| GitHub Release Assets | Exact closed set: `{NekoLauncher.exe, NekoUpdater.exe, NekoProxyCore.zip, release-v2.json}` | Exact 4 trusted release assets |

**Future Release Generalization Rule**:
Future releases may generalize expected values only through reviewed release input and authority rules; do not hard-code unrelated future policy in this spec.

---

## 8. Candidate Evidence: Informative vs Normative Separation

### 8.1 Informative Candidate Baseline
During candidate preparation on branch `release/5.1` at commit `419c69ecbd2d9fdbf8f48179b844e74ecae77b9f`, local qualification run `r3` produced the following candidate measurements:

- **Target Commit**: `419c69ecbd2d9fdbf8f48179b844e74ecae77b9f` (HEAD)
- **NekoLauncher.exe**:
  - Size: `29,903,888` bytes
  - SHA-256: `3dc04ec749a4bb1eb6ab708d360a5b59c7f1f3b81fe020db25f4be0a5ff0cc45`
- **NekoUpdater.exe**:
  - Size: `14,343,670` bytes
  - SHA-256: `4cc0bf6db13695d40fd94a0b567a704850ad80c066b166ae97ef2f7fefe9b499`
- **NekoProxyCore.zip**:
  - Size: `371,995,837` bytes
  - Artifact SHA-256: `b969512875bd640265af0b01730e0d6c78027dc584bfa04c029c6115a6599ebc`
  - Installed Identity SHA-256: `fcb4f5e9a05831c645a1e4cf7a667ab1e0a8c2c621d7853a9adbd2d81aebf7ad`

### 8.2 Normative Execution Requirement
The values recorded in Section 8.1 are **informative reference data** illustrating candidate state. They are **not normative release authority**.
When the authorized operator executes the formal release ceremony, Gate #2 MUST be executed in exact normative order:
1. Freeze exact candidate bytes in the local candidate staging directory.
2. Execute Launcher packaged smoke and Updater self-check on those exact frozen bytes.
3. Freshly recompute Launcher/Updater/Core sizes+SHA-256 and Core installed identity after smoke execution.
4. Construct and sign canonical `release-v2.json` using those fresh measurements and the offline Ed25519 key.
5. Locally verify canonical envelope, signature, and exact three component bindings against those same frozen bytes.
6. Run repository safety and clean worktree checks (`scripts/check_repository_safety.py`).
7. Obtain independent review approval (Critical 0 / Important 0).

No pre-recorded or hardcoded candidate hashes from prior documentation runs may be substituted for live measurements. Any byte mutation after fresh measurement invalidates Gate #2 and requires a new candidate and resequencing as applicable.

### 8.3 Historical Spent Authority: Gate #2 Run r4
During local Gate #2 qualification run `r4`, candidate executables were compiled, frozen, and smoke-tested. Canonical `release-v2.json` was signed once using the offline production key under `release_sequence: 1` and `release_id: stable-0001`.
Following completion of the signing step, Gate #2 was formally **REJECTED** due to missing retained Step 2 audit evidence (specifically failure to capture and persist separate stdout/stderr transcripts and timing metadata for Launcher smoke and Updater self-check).
In accordance with the project's fail-closed security policy, `release_sequence: 1` and `release_id: stable-0001` are permanently spent and unpublished. Run `r4` evidence is quarantined and labeled `rejected/incomplete`. The candidate binaries from `r4` remain byte-identical valid artifacts eligible for byte-identical reuse into a fresh candidate directory (run `r5`) with full provenance proof and a complete restart of Gate #2.

---

## 9. Threat and Failure Model (Critical and Important Only)

### 9.1 Critical Threats and Mitigations

#### T-CRIT-1: Compromise of Hosted CI Runner
- **Threat**: An attacker compromises the GitHub Actions hosted runner environment (e.g. via compromised dependency or GitHub platform issue) to inject malicious binaries into a release.
- **Mitigation**: The CI runner does not possess the Ed25519 private signing key. It cannot forge or resign `release-v2.json`. The workflow downloads staged assets and validates their SHA-256 digests against the locally signed manifest using the in-repo public key. Furthermore, installed clients independently verify the Ed25519 signature before accepting any update.

#### T-CRIT-2: TOCTOU Asset Substitution Race Condition
- **Threat**: An attacker or errant script replaces an uploaded asset on the draft release between the moment the verification step finishes and the publication step executes.
- **Mitigation**: GitHub assigns an immutable numeric `asset_id` to each uploaded file. The pre-publish step immediately re-queries GitHub API and enforces that the four `name -> asset_id` bindings are bit-for-bit identical to those downloaded and verified. Any replacement of an asset generates a new `asset_id`, triggering immediate workflow failure before publication.

#### T-CRIT-3: Exfiltration of Private Signing Key
- **Threat**: Attackers attempt to extract private signing keys via compromised CI logs, environment dumps, or workflow outputs.
- **Mitigation**: The private signing key never reaches GitHub. It is never stored in GitHub Secrets, never passed as an input, and never loaded onto any CI runner. Offline signing occurs entirely on the operator machine.

#### T-CRIT-4: Sequence Downgrade / Replay Attack
- **Threat**: An attacker publishes or replays an older signed release with a lower `release_sequence` to roll back security fixes.
- **Mitigation**: The client updater enforces durable local high-water marks and rejects any release where `release_sequence <= current_sequence`. The workflow also validates that `release_sequence` matches the expected sequence (`2` for this operative first public release; sequence `1` spent-unpublished).

### 9.2 Important Threats and Mitigations

#### T-IMP-1: PyInstaller Non-Reproducibility Discrepancy
- **Threat**: Binaries compiled in CI differ from locally tested binaries, resulting in verification failures or unverified code publication.
- **Mitigation**: CI binary compilation is completely removed from the publication path. Only the frozen candidate binaries built, smoke-tested, freshly measured, and signed locally are uploaded and verified.

#### T-IMP-2: Parameter Injection via Workflow Dispatch Inputs
- **Threat**: An operator or compromised token passes malicious URLs, local filesystem paths, or alternate public key paths into workflow dispatch inputs.
- **Mitigation**: The workflow accepts only a numeric `release_id`, a strictly formatted `release_tag`, an `expected_target` commit SHA, and a boolean. It rejects file paths and URLs. The release verification public key is materialized solely from the in-repo `PRODUCTION_RELEASE_PUBLIC_KEYS` registry at the target commit.

#### T-IMP-3: Premature or Incomplete Release Exposure
- **Threat**: A release is published before all four assets are completely uploaded, or client discovery detects a partial release.
- **Mitigation**: The release is staged as `draft=true`. GitHub hides draft releases completely from unauthenticated public API queries (`/releases/latest`). Publication occurs strictly via `PATCH draft=false` after all four assets are proven present, unique, and verified.

#### T-IMP-4: Public Key ID Substitution / Registry Decoupling
- **Threat**: A release envelope is presented with an arbitrary key ID, or the verifier registers raw key bytes under an unvetted, manifest-supplied key ID rather than enforcing the repository trust registry binding.
- **Mitigation**: Phase 2 publication authority strictly requires envelope `key_id == neko-update-prod-1` and validates that the Ed25519 signature verifies through `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`. Any other key ID fails closed immediately.

#### T-IMP-5: Post-Smoke Candidate Mutation
- **Threat**: Candidate binaries or packages are modified, touched, or recompiled after measurement or smoke testing, invalidating the verified test baseline.
- **Mitigation**: Strict Gate #2 normative ordering requires freezing candidate bytes first, testing those frozen bytes, freshly measuring descriptors after smoke completion, and invalidating Gate #2 if any mutation occurs after fresh measurement.

### 9.3 Explicit Non-Goals
In accordance with the project's Balanced Security Model:
1. **No Hostile Local Admin/Kernel Defense**: We do not defend against an attacker who has root/administrator privileges or kernel-level control over the client machine.
2. **No Automated In-CI Private Key Signing**: We explicitly reject online signing keys in GitHub Actions.
3. **No Multi-Channel Rollout**: This specification covers stable-channel releases only. Prerelease and beta channels are deferred.

---

## 10. Operator Responsibilities and Operational Checklist

### 10.1 Local Operator Responsibilities
The local operator MUST execute the release qualification process in strict normative sequence:
- [ ] Build candidate PE executables (`NekoLauncher.exe`, `NekoUpdater.exe`) and assemble candidate Core bundle (`NekoProxyCore.zip`) from audited clean worktree.
- [ ] **Gate #2 Step 1 (Freeze & Provenance)**: Isolate candidate files in dedicated local candidate staging directory; lock candidate files against any further compilation or editing; verify byte-identical provenance if reusing prior built binaries.
- [ ] **Gate #2 Step 2 (Smoke & Transcript Retention)**: Execute Launcher packaged smoke tests and Updater self-check directly on those exact frozen bytes, capturing exact command, cwd, start/end timestamps, elapsed duration, exit code 0, and separate stdout/stderr files (even if empty). Verify pre-smoke and post-smoke SHA-256 hashes match.
- [ ] **Gate #2 Step 3 (Fresh Measurement)**: Freshly recompute Launcher/Updater/Core sizes+SHA-256 digests and Core installed identity SHA-256 strictly after smoke completion (timestamp strictly after Step 2 ends). No executables run after Step 3.
- [ ] **Gate #2 Step 4 (Sign)**: Construct and sign canonical `release-v2.json` using fresh measurements and offline Ed25519 private key (`key_id: neko-update-prod-1`, sequence `2`, minimum sequence `1`, string `release_id: stable-0002`, protocol range `1..1`, component versions `5.1.0a3`; sequence 1 / stable-0001 is spent-unpublished).
- [ ] **Gate #2 Step 5 (Local Verify)**: Locally verify canonical envelope serialization, Ed25519 signature validity, and exact three component bindings against those same frozen candidate bytes using `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`.
- [ ] **Gate #2 Step 6 (Safety Checks)**: Execute repository safety and scope checks (`scripts/check_repository_safety.py`, clean Git status, no untracked release debris or secret leaks).
- [ ] **Gate #2 Step 7 (Review Approval & Index)**: Obtain formal independent review approval with Critical 0 and Important 0 (C0/I0) findings; generate authoritative evidence index hashing all retained logs and transcripts.
- [ ] Push approved Git commit and tag (`v5.1.0a3`) to GitHub remote.
- [ ] Create GitHub draft release targeting the exact commit (`draft=true`, `prerelease=false`).
- [ ] Upload exactly four assets (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, `release-v2.json`) with `--clobber=false`.
- [ ] Capture immutable numeric GitHub `release_id` (distinguished from envelope string `release_id`) and four `asset_id` bindings.
- [ ] Trigger Phase 2 publication workflow dispatch via GitHub Actions with captured numeric `release_id`, `release_tag=v5.1.0a3`, and `expected_target`.

### 10.2 Remote CI Workflow Responsibilities
- [ ] Check out repository at exact `expected_target` commit.
- [ ] Enforce key ID binding: assert envelope `key_id == neko-update-prod-1` and source Ed25519 public key strictly from in-repo `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`.
- [ ] Query draft release by numeric `release_id`; verify `draft=true`, `prerelease=false`, `tag_name == release_tag` (`v5.1.0a3`), and target commit.
- [ ] Download exact four assets by numeric `asset_id` as raw binary streams.
- [ ] Execute `verify_github_release_assets.py` to cryptographically verify assets, envelope, formats, sizes, and digests.
- [ ] Enforce first-release fail-closed parameter validation: `channel=stable`, `release_sequence=2`, `minimum_supported_sequence=1`, signed string `release_id=stable-0002`, `updater_protocol` minimum=1 maximum=1, component versions `launcher/updater/core=5.1.0a3`, and key/tag binding remains `v5.1.0a3` (reject spent sequence 1 / stable-0001).
- [ ] Re-read release by numeric `release_id` immediately prior to publication; assert unchanged release metadata and `asset_id` bindings.
- [ ] Activate release via `PATCH /repos/.../releases/:release_id` with `draft=false`.
- [ ] Read back published release by numeric `release_id` and `/releases/latest` to confirm public visibility and integrity.

---

## 11. Migration, Rollback, and Recovery

### 11.1 Aborting an Unapproved or Failed Staged Draft
If verification fails at any point in Phase 1 or Phase 2:
1. The staged release remains in `draft=true` state. It is never visible to installed clients.
2. The operator can safely delete the draft release via GitHub API or CLI (`gh release delete "$GITHUB_RELEASE_ID"` using the numeric release ID).
3. If `release-v2.json` was already signed with `release_sequence=N`, that sequence number must be considered spent. The next candidate must use `release_sequence=N+1` to guarantee strict monotonicity.

### 11.2 Rollback of a Published Release
If a published release exhibits unforeseen regressions on client machines:
1. **Client-Side Self-Contained Rollback**: Installed clients utilize their existing rollback architecture. If an update fails probation or self-test, the local updater automatically rolls back to the previous committed generation and sets durable failure suppression.
2. **Roll-Forward Authority**: To push a fix to clients, the operator must assemble and sign a new release with an incremented `release_sequence` (e.g. `release_sequence=2`). Clients with durable high-water mark `1` will accept the new sequence `2`.
3. **No Retroactive Clobbering**: Published releases on GitHub are never mutated, overwritten, or re-signed.

### 11.3 Recovery from Sequence 1 Burn (Rejected Gate #2 Run r4)
When Gate #2 run `r4` was rejected for missing retained Step 2 audit evidence, canonical `release-v2.json` had already been signed with `release_sequence: 1`. Under Section 4.2 and Section 11.1:
1. Sequence `1` is permanently spent. It can never be published, reused, or regenerated.
2. The operative recovery release sequence is `2`, with signed envelope string `release_id: stable-0002`.
3. `minimum_supported_sequence` remains `1` because sequence 1 was never published; installed clients have never seen sequence 1, so the compatibility floor remains sequence 1.
4. No remote release side effects occurred during run r4 (no git push, no tag push, no draft release created, no assets uploaded).
5. Binaries from run r4 may be reused byte-identically into a fresh candidate staging directory (e.g. `candidate-r5`) provided that provenance is cryptographically verified (source and destination sizes and SHA-256 hashes match bit-for-bit) and the full Gate #2 qualification sequence is restarted from Step 1 under the Durable Recovery Gate #2 Evidence Contract.

---

## 12. Verification and Acceptance Criteria

Implementation of this specification is acceptable only when all of the following criteria are met:

1. **Workflow Input Contract and ID Distinction**: The publication workflow accepts only immutable numeric `release_id`, `release_tag`, `expected_target`, and `publish_release=true`. It accepts no local filesystem paths or external public key paths. The numeric GitHub release ID is strictly distinguished from the signed manifest's envelope string `release_id`.
2. **Elimination of CI Build from Publication Path**: The publication workflow contains no PyInstaller build steps and does not upload binary artifacts.
3. **Exact Production Key-ID Binding and Derivation**: The verifier runtime requires envelope `key_id` to be exactly `neko-update-prod-1` and derives the Ed25519 public key strictly from `neko_launcher.updater.trust.PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`. It rejects any manifest-supplied arbitrary key ID. If a temporary public-key file is used for the verifier CLI, the workflow explicitly asserts `key_id == neko-update-prod-1` and sources bytes solely from this fixed registry entry, or the verifier validates directly through the registry binding. Any other `key_id` fails closed.
4. **Gate #2 Normative Ordering**: Gate #2 is enforced as a strict MUST-order sequence: candidate byte freeze -> smoke & self-check on frozen bytes -> fresh recomputation of sizes+SHA-256 and Core installed identity -> construct/sign release-v2 -> verify envelope/signature/bindings -> repository safety/scope checks -> independent review approval (C0/I0) before any Git push, tag push, draft creation, or upload. Any byte mutation after fresh measurement invalidates Gate #2.
5. **First-Release Fail-Closed Invariants**: For this first public release `v5.1.0a3`, Phase 2 publication authority MUST reject unless the signed envelope has `channel=stable`, `release_sequence=2`, `minimum_supported_sequence=1`, signed string `release_id=stable-0002`, `updater_protocol` minimum=1 maximum=1, launcher/updater/core versions all `5.1.0a3`, and key/tag binding remains `v5.1.0a3`. Sequence `1` / `stable-0001` is historical spent-unpublished authority and must fail closed. Future releases may generalize expected values only through reviewed release input/authority rules.
6. **Binary Stream Download by Asset ID**: Required release assets are downloaded directly via `/releases/assets/:asset_id` as octet-streams, not by filename scraping.
7. **Rigorous Asset Verification**: All four required assets are verified against the signed manifest using `verify_github_release_assets.py`, enforcing draft state, canonical JSON, Ed25519 signature validity under `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`, component formats, exact sizes, and exact SHA-256 digests.
8. **Pre-Publish Binding Lock**: The workflow re-checks draft state and asserts that all four `name -> asset_id` bindings are identical immediately before issuing the publication PATCH.
9. **Atomic Activation by ID**: Publication is executed exclusively by `PATCH /repos/.../releases/:release_id` setting `draft=false`.
10. **Post-Publish Verification**: The workflow verifies `/releases/:release_id` is published (`draft=false`) and confirms that `/releases/latest` resolves to the identical release ID and asset bindings.
11. **Fail-Closed Operation**: All synthetic error conditions (hash mismatch, corrupted JSON, invalid signature, modified asset ID, tag mismatch, unexpected key ID, unexpected sequence/protocol/version) cause immediate workflow failure with the draft remaining unpublished.
12. **Documentation Consistency**: The specification contains no placeholders, TODOs, or TBDs, and cleanly supersedes the publication-handoff sections of `2026-09-08-software-update-github-releases-design.md`.
