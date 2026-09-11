# Software Update: Two-Phase Staged-Draft Publication Architecture — Implementation Plan

> For agentic workers: execute one task at a time with Superpowers executing-plans or subagent-driven-development. Before every Hermes dispatch, inspect active `--oneshot` processes and `E:\Github\Project manager\TASK_REGISTRY.md` plus session history. One objective has one active worker; reuse the completed Sol High audit and completed reviews rather than rerunning them.

**Goal:** Implement the Two-Phase Staged-Draft Publication Architecture for Neko Family Proxy software updates, establishing local offline candidate freezing and Ed25519 signing (Phase 1) and independent remote GitHub Actions publication authority (Phase 2), replacing the single-phase CI release creation model.

**Architecture:** Candidate compilation, packaged smoke verification, fresh measurement, and canonical `release-v2.json` signing occur exclusively on the controlled local machine under strict Gate #2 normative ordering. The local machine uploads candidate files to an unpublished GitHub Draft release (`draft=true`, `prerelease=false`, `--clobber=false`) and captures the immutable numeric GitHub `release_id` and four `name -> asset_id` bindings. Final publication (`draft=false`) is authorized exclusively by a GitHub Actions `workflow_dispatch` authority gate that accepts only numeric `release_id`, `release_tag`, and `expected_target`. The workflow downloads assets as raw binary streams by immutable `asset_id`, validates cryptographic signatures and first-release invariants against in-repo `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`, re-checks draft state and asset ID bindings to eliminate TOCTOU races, publishes via `PATCH /releases/:release_id` (`draft=false`), and confirms public availability on `/releases/latest`.

**Tech stack:** Python 3.11/3.12, PyInstaller 6.21.0, pytest 9.1.1, Ruff 0.11.2, cryptography 44.0.2, GitHub Actions PowerShell (`pwsh`), GitHub CLI (`gh`).

**Spec:** `docs/superpowers/specs/2026-09-09-software-update-two-phase-staged-draft-design.md` (Owner approved; Gate #2 remains NOT PASSED; production signing and remote publication remain prohibited during implementation tasks).

---

## Global Constraints and Invariants

1. **Baseline Commit & Worktree**: Start strictly from `release/5.1` at commit `a58188fcb4f7dc0804e7c032db996fb688b39314`. Work exclusively in `E:\Github\worktrees\Neko-Family-Proxy-5.1`. Preserve unrelated work and re-read git status before each task.
2. **Final Publication Authority**: Publication authority belongs exclusively to GitHub Actions. Direct local workstation activation (`PATCH draft=false` or `gh release edit --draft=false`) is strictly prohibited.
3. **Local Staging Authority**: The local operator machine may create a draft release and upload assets only after passing Gate #2 in strict normative sequence.
4. **Publication Workflow Role**: The publication workflow is an independent verification authority gate, not an artifact creation authority. It contains no PyInstaller builds, accepts no local workstation file paths (`core_artifact_path`, `signed_manifest_path`, `release_public_key_path`), and uploads no update payloads.
5. **Exact Four Trusted Assets**: The release asset set consists strictly of four files: `NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, and `release-v2.json`. Permitted human-facing extra assets (such as `SHA256SUMS.txt` or installers) are ignored during update asset binding.
6. **Exact Signed Component Set**: The signed manifest dictionary consists strictly of `{launcher, updater, core}`.
7. **First-Release Normative Parameters (Operative Recovery Authority)**: For release `v5.1.0a3`, publication authority rejects unless:
   - `channel == "stable"`
   - `release_sequence == 2` (operative recovery sequence; sequence 1 spent-unpublished in rejected Gate #2 r4)
   - `minimum_supported_sequence == 1` (client compatibility floor remains 1; sequence burn does not advance client high-water mark)
   - `release_id == "stable-0002"` (signed string identifier; historical `stable-0001` spent-unpublished; distinguished from numeric GitHub release ID)
   - `updater_protocol == {"minimum": 1, "maximum": 1}`
   - `components['launcher'].version == "5.1.0a3"`
   - `components['updater'].version == "5.1.0a3"`
   - `components['core'].version == "5.1.0a3"`
   - `key_id == "neko-update-prod-1"`
   - `expected_tag == "v5.1.0a3"` (matching `"v" + components['launcher'].version`)
   *Historical Note*: Sequence 1 / `stable-0001` was signed once during local Gate #2 run `r4`, which was subsequently rejected for missing retained Step 2 audit evidence. Sequence 1 is permanently spent and unpublished; no remote release side effects occurred. `minimum_supported_sequence` remains 1 because it is client compatibility / mandatory floor; sequence burn does not revoke compatibility or advance any client high-water mark. No architecture, schema, or client-policy changes are introduced; this is strictly release-parameter + evidence-contract correction.
8. **Candidate Byte Freezing & Measurement**: Candidate bytes must be frozen in a dedicated staging directory, smoke-tested, and freshly measured immediately after smoke completion before manifest construction and signing. Any byte mutation after measurement invalidates Gate #2.
9. **Private Key Isolation**: The Ed25519 private signing key remains offline in Vault MASTER. It must never touch GitHub Secrets, CI runner environments, or repository history.
10. **Public Key Binding**: Verification must resolve strictly through `neko_launcher.updater.trust.PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`. No manifest-supplied or unvetted key registration is permitted.
11. **TOCTOU Elimination**: The publication workflow downloads assets by numeric `asset_id`, verifies raw binary streams, and re-validates draft state and asset ID equality immediately prior to issuing `PATCH draft=false`.
12. **Threat Model Scope**: Mitigations focus strictly on Critical and Important threats per spec Section 9; hostile local administrator and kernel attacks are explicit non-goals.
13. **TDD Discipline**: Follow strict TDD for all code changes: failing test assertions first (RED), minimal implementation (GREEN), regression validation, linting, diff-checking, and narrow review at Critical 0 / Important 0.
14. **No Remote Publication During Implementation**: Implementation tasks establish contracts, verifiers, workflows, and tests. Candidate compilation, offline signing, Gate #2 execution, draft creation, and publication occur strictly after implementation clearance.
15. **Out-of-Band Contemporaneous Evidence Anchor**: For every Gate #2 executable/action command (copy/provenance ceremony, Launcher smoke, Updater self-check, post-smoke measurement/Core proof, signing, local verifier, repository safety), execution MUST occur through the out-of-band controller task system (`@aikhai task execution`). Each command receives a unique controller task ID created at execution time; controller records are external to candidate/worktree and serve as authoritative execution anchors. Candidate evidence event index binds each controller task ID to candidate ID, event number, expected argv/cwd, copied stdout/stderr file hashes, exit code, and start/end timestamps. Candidate-local copies are secondary convenience evidence; independent review retrieves and validates controller task records directly. A local event hash chain provides defense-in-depth, but the external controller record is the contemporaneous anti-reconstruction anchor. Strict ordering is preserved; zero remote Git or release side effects before Gate #2.

---

## Dependency Order and Execution Graph

```
Task 1: Verifier First-Release Authority & Key Binding (Initial sequence 1 impl)
  │
  ▼
Task 2: Publication Workflow Contract & CI Build Decoupling
  │
  ▼
Task 3: Phase-2 Remote Verification & Publish-by-ID
  │
  ▼
Task 4: Local Controlled Draft Staging Tooling (stage_draft_release.py)
  │
  ▼
Task 5: Documentation & Operator Runbook Migration
  │
  ▼
Task 6: Final End-to-End Acceptance & Quality Gate (Completed at HEAD 419a3ec)
  │
  ▼
══════════════════════════════════════════════════════════════════════════════
RECOVERY AMENDMENT (Post-Gate #2 Sequence-1 Burn & Rejection)
══════════════════════════════════════════════════════════════════════════════
  │
  ▼
Task R1: Recovery Parameter Code & Test Updates (sequence 2, stable-0002, min_seq 1) [PENDING]
  │
  ▼
Task R2: Independent Sol Review Clearance (C0/I0; initial review C0/I1, Round 1 fix pending re-review) [PENDING]
  │
  ▼
Task R3: Fresh Candidate Reuse & Provenance Copy Proof (via out-of-band controller task system) [PENDING]
  │
  ▼
Task R4: Gate #2 Ceremony Sequence 2 Execution under Durable Evidence Contract (out-of-band anchored) [PENDING]
```

---

## Task 1 — Verifier First-Release Authority and Exact Key-ID Binding

*(Completed in initial implementation at HEAD 419a3ec; sequence 1 / stable-0001 spent-unpublished in rejected Gate #2 r4; superseded by Task R1 for operative sequence 2 / stable-0002)*

### Goal
Upgrade `scripts/verify_github_release_assets.py` to enforce the exact production key ID `neko-update-prod-1` bound strictly to `neko_launcher.updater.trust.PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`, and validate all first-release normative invariants (initial values: `channel=stable`, `release_sequence=1`, `minimum_supported_sequence=1`, `release_id=stable-0001`, `updater_protocol=1..1`, component versions `5.1.0a3`, tag `v5.1.0a3`; amended to sequence 2 / stable-0002 in Task R1).

### Files
- Modify: `scripts/verify_github_release_assets.py`
- Modify: `launcher/tests/test_verify_github_release_assets.py`

### Interfaces

```python
# scripts/verify_github_release_assets.py

EXPECTED_PRODUCTION_KEY_ID: str = "neko-update-prod-1"
FIRST_RELEASE_EXPECTED_TAG: str = "v5.1.0a3"
FIRST_RELEASE_EXPECTED_CHANNEL: str = "stable"
# Note: Initial implementation values; amended in Task R1 to SEQUENCE = 2 and RELEASE_ID = "stable-0002"
FIRST_RELEASE_EXPECTED_SEQUENCE: int = 1
FIRST_RELEASE_EXPECTED_MIN_SEQUENCE: int = 1
FIRST_RELEASE_EXPECTED_RELEASE_ID: str = "stable-0001"
FIRST_RELEASE_EXPECTED_COMPONENT_VERSION: str = "5.1.0a3"
FIRST_RELEASE_EXPECTED_PROTOCOL_MIN: int = 1
FIRST_RELEASE_EXPECTED_PROTOCOL_MAX: int = 1

def verify_github_release_assets(
    *,
    release_json_path: Path | str,
    download_dir: Path | str,
    public_key_file: Path | str | None = None,
    expected_tag: str,
    expected_target: str,
    require_draft: bool = False,
    expected_key_id: str = EXPECTED_PRODUCTION_KEY_ID,
    enforce_first_release: bool = True,
    trusted_public_keys: Mapping[str, bytes] | None = None,
) -> None: ...
```

CLI arguments:
```text
python scripts/verify_github_release_assets.py \
  --release-json <path> \
  --download-dir <path> \
  [--public-key-file <path>] \
  [--trusted-key-id <key_id>] \
  --expected-tag <tag> \
  --expected-target <sha> \
  --require-draft \
  [--no-enforce-first-release]
```

### Fail-Closed Behavior
1. **Key ID Enforcement**: If manifest envelope `key_id != expected_key_id`, raise `GitHubReleaseAssetsVerificationError("Manifest key_id mismatch")`.
2. **Key Derivation & Verification**:
   - If `trusted_public_keys` is provided (e.g. unit test harness), look up `trusted_public_keys[expected_key_id]`.
   - If `public_key_file` is provided and `expected_key_id == EXPECTED_PRODUCTION_KEY_ID`, assert file bytes match `PRODUCTION_RELEASE_PUBLIC_KEYS[EXPECTED_PRODUCTION_KEY_ID]`. Any byte discrepancy raises `GitHubReleaseAssetsVerificationError("Public key file does not match in-repo production key registry")`.
   - If `public_key_file` is omitted, derive key bytes directly from `PRODUCTION_RELEASE_PUBLIC_KEYS[expected_key_id]`.
   - Cryptographic envelope verification must use `{expected_key_id: key_bytes}` so manifest-supplied arbitrary keys cannot pass verification.
3. **First-Release Normative Invariants** (when `enforce_first_release=True`; initial implementation values; amended in Task R1 to sequence 2 / stable-0002):
   - `release_set_v2.channel == "stable"`
   - `release_set_v2.release_sequence == 1` (amended to 2 in Task R1)
   - `release_set_v2.minimum_supported_sequence == 1`
   - `release_set_v2.release_id == "stable-0001"` (amended to "stable-0002" in Task R1)
   - `release_set_v2.updater_protocol.minimum == 1` and `release_set_v2.updater_protocol.maximum == 1`
   - `release_set_v2.components['launcher'].version == "5.1.0a3"`
   - `release_set_v2.components['updater'].version == "5.1.0a3"`
   - `release_set_v2.components['core'].version == "5.1.0a3"`
   - `expected_tag == "v5.1.0a3"` and `expected_tag == "v" + release_set_v2.components['launcher'].version`

### Steps
- [ ] 1. Update test helper bundle generator in `launcher/tests/test_verify_github_release_assets.py` to support first-release default parameters (`v5.1.0a3`, `stable-0001`, sequence `1`, min sequence `1`, protocol `1..1`, component versions `5.1.0a3`, key ID `neko-update-prod-1`).
- [ ] 2. Add test cases to `launcher/tests/test_verify_github_release_assets.py`:
  - `test_verify_assets_succeeds_with_in_repo_production_key_omitting_public_key_file`
  - `test_verify_assets_fails_when_envelope_key_id_mismatches_expected`
  - `test_verify_assets_fails_when_public_key_file_differs_from_in_repo_registry`
  - `test_verify_assets_fails_when_release_sequence_is_not_one`
  - `test_verify_assets_fails_when_minimum_supported_sequence_is_not_one`
  - `test_verify_assets_fails_when_string_release_id_is_not_stable_0001`
  - `test_verify_assets_fails_when_updater_protocol_is_not_1_to_1`
  - `test_verify_assets_fails_when_launcher_version_is_not_5_1_0a3`
  - `test_verify_assets_fails_when_updater_version_is_not_5_1_0a3`
  - `test_verify_assets_fails_when_core_version_is_not_5_1_0a3`
  - `test_verify_assets_fails_when_tag_is_not_v5_1_0a3`
- [ ] 3. Run RED verification:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
  .venv\Scripts\python.exe -B -m pytest tests/test_verify_github_release_assets.py -k "test_verify_assets_fails_when_envelope_key_id or test_verify_assets_fails_when_release_sequence" -q
  ```
  Expected failure: assertions fail because `verify_github_release_assets.py` does not yet reject unapproved key IDs or validate first-release invariants.
- [ ] 4. Implement changes in `scripts/verify_github_release_assets.py`:
  - Import `PRODUCTION_RELEASE_PUBLIC_KEYS` from `neko_launcher.updater.trust`.
  - Define first-release constants.
  - Implement strict key-ID matching and registry binding.
  - Implement first-release invariant checks.
  - Make `--public-key-file` optional in CLI parser; add `--trusted-key-id` and `--no-enforce-first-release` flags.
- [ ] 5. Run GREEN verification:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
  .venv\Scripts\python.exe -B -m pytest tests/test_verify_github_release_assets.py -q
  launcher\.venv\Scripts\ruff.exe check ..\scripts\verify_github_release_assets.py tests/test_verify_github_release_assets.py
  ```
- [ ] 6. Review checkpoint: Verify fail-closed behavior for unapproved key IDs and parameter deviations. Critical 0 / Important 0.
- [ ] 7. Commit changes:
  ```cmd
  git add scripts/verify_github_release_assets.py launcher/tests/test_verify_github_release_assets.py
  git commit -m "feat(verifier): enforce first-release authority and production key binding"
  ```

---

## Task 2 — Publication Workflow Contract and Decoupling from CI Builds

### Goal
Decouple release publication authority from CI artifact builds in `.github/workflows/release.yml`. Remove local filesystem inputs (`core_artifact_path`, `signed_manifest_path`, `release_public_key_path`), configure `workflow_dispatch` to take strictly immutable draft `release_id`, `release_tag`, and `expected_target`, ensure `publish-release` does not depend on `build-installer`, and eliminate PyInstaller rebuilds, artifact downloads, and release uploads from the publication job.

### Files
- Modify: `.github/workflows/release.yml`
- Modify: `launcher/tests/test_release_workflow_publication_gate.py`

### Workflow Interface Contract

```yaml
name: Windows release

on:
  workflow_dispatch:
    inputs:
      publish_release:
        description: Authorize publication of the verified draft release
        required: true
        type: boolean
        default: false
      release_id:
        description: Immutable numeric GitHub draft release ID
        required: true
        type: string
      release_tag:
        description: Expected release Git tag (strictly v5.1.0a3 for first release)
        required: true
        type: string
      expected_target:
        description: Expected 40-character commit SHA of target_commitish
        required: true
        type: string
  push:
    tags:
      - "v*"

permissions:
  contents: read

jobs:
  build-installer:
    if: github.event_name == 'push'
    runs-on: windows-latest
    permissions:
      contents: read
    # Diagnostic CI build and smoke test steps retained...

  publish-release:
    if: github.event_name == 'workflow_dispatch' && inputs.publish_release == true
    runs-on: windows-latest
    permissions:
      contents: write
    # Remote verification and publication authority steps...
```

### Behavioral Invariants
1. **Input Exclusivity**: `workflow_dispatch` accepts ONLY `publish_release`, `release_id`, `release_tag`, `expected_target`. No file path parameters are permitted.
2. **Job Isolation**: `publish-release` has NO `needs: build-installer` relationship. It executes independently on `workflow_dispatch`.
3. **No CI Binary Compilation**: `publish-release` contains no PyInstaller invocations, no `.spec` references, and no executable compilation.
4. **No Artifact Hand-off**: `publish-release` contains no `actions/download-artifact` step.
5. **No Release Creation/Upload in Publication Job**: `publish-release` does not execute `gh release create` or `gh release upload` (assets were staged locally in Phase 1).
6. **Checkout at Expected Target**: `publish-release` executes `actions/checkout@v6` with `ref: ${{ inputs.expected_target }}`.

### Steps
- [ ] 1. Update `launcher/tests/test_release_workflow_publication_gate.py`:
  - Assert `workflow_dispatch` inputs match exact set `{"publish_release", "release_id", "release_tag", "expected_target"}`.
  - Assert prohibited inputs `{"core_artifact_path", "signed_manifest_path", "release_public_key_path"}` are absent.
  - Assert `publish-release` does not contain `needs: build-installer`.
  - Assert `publish-release` does not contain `actions/download-artifact`.
  - Assert `publish-release` does not contain `gh release create` or `gh release upload`.
  - Assert `publish-release` checks out `inputs.expected_target`.
  - Assert `build-installer` retains `contents: read` and runs only on tag push events.
- [ ] 2. Run RED verification:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
  .venv\Scripts\python.exe -B -m pytest tests/test_release_workflow_publication_gate.py -q
  ```
  Expected failure: tests fail because `release.yml` still contains obsolete inputs, `needs: build-installer`, and artifact download steps.
- [ ] 3. Update `.github/workflows/release.yml`:
  - Update `workflow_dispatch` inputs contract.
  - Set `if: github.event_name == 'push'` on `build-installer`.
  - Remove `needs: build-installer` from `publish-release`.
  - Remove `actions/download-artifact`, `Stage approved update assets`, `Create draft GitHub release`, and `Upload required update assets` steps from `publish-release`.
  - Configure checkout step in `publish-release` to use `ref: ${{ inputs.expected_target }}`.
- [ ] 4. Run GREEN verification:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
  .venv\Scripts\python.exe -B -m pytest tests/test_release_workflow_publication_gate.py -q
  launcher\.venv\Scripts\ruff.exe check tests/test_release_workflow_publication_gate.py
  ```
- [ ] 5. Review checkpoint: Confirm zero CI build or artifact creation authority exists in `publish-release`. Critical 0 / Important 0.
- [ ] 6. Commit changes:
  ```cmd
  git add .github/workflows/release.yml launcher/tests/test_release_workflow_publication_gate.py
  git commit -m "feat(workflow): decouple publication authority from CI artifact builds"
  ```

---

## Task 3 — Phase-2 Remote Verification and Publish-by-ID

### Goal
Implement Phase 2 remote gate verification and publication activation by immutable ID in `.github/workflows/release.yml`. The job queries the staged draft release by numeric `release_id`, downloads required assets as raw binary streams via `/releases/assets/:asset_id`, runs `verify_github_release_assets.py` using in-repo trust authority, re-validates draft state and asset IDs to lock bindings, activates the release via `PATCH draft=false`, and asserts availability on `/releases/latest`.

### Files
- Modify: `.github/workflows/release.yml`
- Modify: `launcher/tests/test_release_workflow_github_assets.py`

### Publication Job Step Sequence

1. **Checkout Target Commit**:
   `actions/checkout@v6` with `ref: ${{ inputs.expected_target }}`
2. **Setup Python Runtime**:
   `actions/setup-python@v6` with Python 3.12, pip cache.
3. **Install Verifier Runtime**:
   `python -m pip install -e ".\launcher[release]"`
4. **Validate Dispatch Parameters and Target Commit**:
   PowerShell step asserting:
   - `$env:RELEASE_ID -match '^\d+$'`
   - `$env:RELEASE_TAG -match '^v[A-Za-z0-9._+-]{1,64}$'`
   - `$env:RELEASE_TAG -ceq 'v5.1.0a3'`
   - `$env:EXPECTED_TARGET -match '^[0-9a-fA-F]{40}$'`
   - `$env:EXPECTED_TARGET.ToLower() -eq '${{ github.sha }}'.ToLower()`
5. **Fetch Staged Draft Release Object by Numeric ID**:
   - Query `gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID"`
   - Assert `[string]$release.id -eq [string]$env:RELEASE_ID`
   - Assert `$release.draft -eq $true`
   - Assert `$release.prerelease -eq $false`
   - Assert `$release.tag_name -ceq $env:RELEASE_TAG`
   - Assert `$release.target_commitish.ToLower() -eq $env:EXPECTED_TARGET.ToLower()`
   - Save response to `release/metadata/draft-release.json`.
6. **Download Staged Assets by Asset ID as Raw Binary Streams**:
   - For each required asset (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, `release-v2.json`):
     - Assert asset exists in `$release.assets` exactly once with positive integer ID.
     - Record `$initialAssetBindings[$name] = $asset.id`.
     - Stream raw binary bytes via `gh api "repos/$env:GH_REPO/releases/assets/$assetId" -H "Accept: application/octet-stream"` directly to file stream at `release/remote-verification/$name`.
     - Check exit code and verify non-empty file.
7. **Verify Staged Assets and Envelope Authority**:
   Execute verifier CLI:
   ```powershell
   python scripts/verify_github_release_assets.py `
     --release-json release/metadata/draft-release.json `
     --download-dir release/remote-verification `
     --expected-tag "$env:RELEASE_TAG" `
     --expected-target "$env:EXPECTED_TARGET" `
     --require-draft
   ```
   (Derives Ed25519 public key strictly from in-repo `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']` and enforces first-release invariants).
8. **Pre-Publish Revalidation and Atomic Binding Lock**:
   - Re-query `gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID"`
   - Assert `[string]$current.id -eq [string]$env:RELEASE_ID`
   - Assert `$current.draft -eq $true`
   - Assert `$current.prerelease -eq $false`
   - Assert `$current.tag_name -ceq $env:RELEASE_TAG`
   - Assert `$current.target_commitish.ToLower() -eq $env:EXPECTED_TARGET.ToLower()`
   - Assert for all four required assets: `$currentMatches[0].id -eq $initialAssetBindings[$requiredName]`.
   - Any mismatch terminates immediately; release remains draft.
9. **Publish Release by Immutable ID**:
   `gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID" --method PATCH -f draft=false`
10. **Post-Publish Verification and Latest Endpoint Resolution**:
    - Re-query `gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID"`:
      - Assert `$published.draft -eq $false`
      - Assert `$published.prerelease -eq $false`
      - Assert `$published.tag_name -ceq $env:RELEASE_TAG`
      - Assert all four asset IDs remain identical.
    - Query public unauthenticated endpoint: `gh api "repos/$env:GH_REPO/releases/latest"`:
      - Assert `[string]$latest.id -eq [string]$env:RELEASE_ID`
      - Assert `$latest.tag_name -ceq $env:RELEASE_TAG`
      - Assert all four required assets are present with identical IDs and sizes.

### Steps
- [ ] 1. Update `launcher/tests/test_release_workflow_github_assets.py`:
  - Assert download step queries draft release by numeric `$env:RELEASE_ID`.
  - Assert download step records initial name-to-asset-ID bindings.
  - Assert verifier step does not pass an external public key path input parameter.
  - Assert verifier step passes `--require-draft`.
  - Assert pre-publish revalidation asserts draft state and asset ID equality against initial bindings.
  - Assert publication step executes `gh api repos/$env:GH_REPO/releases/$env:RELEASE_ID --method PATCH -f draft=false`.
  - Assert post-publish step verifies both `/releases/$env:RELEASE_ID` (`draft == false`) and `/releases/latest` resolving to same release ID and tag.
- [ ] 2. Run RED verification:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
  .venv\Scripts\python.exe -B -m pytest tests/test_release_workflow_github_assets.py -q
  ```
  Expected failure: tests fail because `release.yml` does not yet match the Phase 2 remote gate verification and `/releases/latest` validation sequence.
- [ ] 3. Update `.github/workflows/release.yml` with steps 4-10.
- [ ] 4. Run GREEN verification:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
  .venv\Scripts\python.exe -B -m pytest tests/test_release_workflow_github_assets.py tests/test_release_workflow_publication_gate.py -q
  launcher\.venv\Scripts\ruff.exe check tests/test_release_workflow_github_assets.py
  ```
- [ ] 5. Review checkpoint: Verify TOCTOU protection, raw binary stream integrity, and `/releases/latest` post-publish proof. Critical 0 / Important 0.
- [ ] 6. Commit changes:
  ```cmd
  git add .github/workflows/release.yml launcher/tests/test_release_workflow_github_assets.py
  git commit -m "feat(workflow): implement remote verification and atomic publish by ID"
  ```

---

## Task 4 — Local Controlled Draft Staging Tooling

### Goal
Implement `scripts/stage_draft_release.py` to provide the authorized local operator with a safe, validated, non-clobbering CLI tool to stage an offline-signed candidate release as a GitHub draft post-Gate #2. The tool validates the clean worktree, commit targeting, tag binding, exact four frozen candidate assets, and canonical `release-v2.json` descriptors; creates the draft (`draft=true`, `prerelease=false`); uploads files without clobber; captures the immutable numeric `release_id` and four `asset_id` bindings; and outputs the exact `gh workflow run` dispatch command. It provides a complete dry-run / command-runner seam for comprehensive unit testing.

### Files
- Create: `scripts/stage_draft_release.py`
- Create: `launcher/tests/test_stage_draft_release.py`

### Interfaces

```python
# scripts/stage_draft_release.py

REQUIRED_STAGE_ASSETS: tuple[str, ...] = (
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
    "release-v2.json",
)

class StageDraftReleaseError(Exception):
    """Raised when staging validation or execution fails."""

@dataclass(frozen=True)
class StagedDraftEvidence:
    release_id: int
    tag_name: str
    target_commit: str
    assets: dict[str, int]  # asset name -> numeric asset_id
    dispatch_command: str

class CommandExecutor(Protocol):
    def run(self, args: list[str], *, capture_output: bool = True) -> subprocess.CompletedProcess[str]: ...

def validate_staging_preconditions(
    *,
    staging_dir: Path,
    tag: str,
    target_commit: str,
    repo_root: Path,
    executor: CommandExecutor,
) -> dict[str, Path]: ...

def stage_draft_release(
    *,
    staging_dir: Path,
    tag: str,
    target_commit: str,
    repo: str = "Valeneko-pranmong/Neko-Family-Proxy",
    title: str | None = None,
    notes: str | None = None,
    dry_run: bool = False,
    executor: CommandExecutor | None = None,
) -> StagedDraftEvidence | None: ...

def main(argv: Sequence[str] | None = None) -> int: ...
```

CLI arguments:
```text
python scripts/stage_draft_release.py \
  --staging-dir <path> \
  --tag <v-tag> \
  --target-commit <40-char-sha> \
  [--repo <owner/repo>] \
  [--title <title>] \
  [--notes <notes>] \
  [--dry-run]
```

### Safety Constraints (MUST NEVER)
1. **MUST NEVER Sign**: Staging tooling never invokes signing keys or generates manifests; `release-v2.json` must already exist, signed offline during Gate #2 Step 4.
2. **MUST NEVER Rebuild**: Staging tooling never compiles code or invokes PyInstaller.
3. **MUST NEVER Move Tags**: Staging tooling never mutates, force-creates, or moves Git tags.
4. **MUST NEVER Publish**: Staging tooling strictly creates releases with `--draft` and never sets `draft=false`.
5. **MUST NEVER Clobber**: File uploads strictly enforce `--clobber=false`.

### Steps
- [ ] 1. Create `launcher/tests/test_stage_draft_release.py`:
  - Test argument parsing (tag, commit, staging-dir, dry-run).
  - Test validation fails when worktree has uncommitted modifications.
  - Test validation fails when target commit is not 40-character hex.
  - Test validation fails when local tag does not point to target commit.
  - Test validation fails when any required asset is missing from staging directory.
  - Test validation fails when staging directory contains unexpected/untrusted files.
  - Test validation fails when any candidate asset is zero-byte.
  - Test validation fails when `release-v2.json` exceeds 65,536 bytes or fails canonical JSON roundtrip.
  - Test validation fails when manifest component sizes or hashes mismatch candidate files.
  - Test dry-run mode validates all preconditions, prints planned commands, and executes zero GitHub mutations.
  - Test execution mode with mock `CommandExecutor`:
    - Asserts `gh release create <tag> --target <commit> --draft` is called.
    - Asserts `gh release upload <tag> ... --clobber=false` is called.
    - Asserts draft readback parses numeric `release_id` and four `asset_id` bindings.
    - Asserts formatted evidence and `gh workflow run` dispatch command are produced.
- [ ] 2. Run RED verification:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
  .venv\Scripts\python.exe -B -m pytest tests/test_stage_draft_release.py -q
  ```
  Expected failure: `ModuleNotFoundError` or collection failure because `scripts/stage_draft_release.py` does not exist.
- [ ] 3. Implement `scripts/stage_draft_release.py`:
  - Implement CLI argument parsing with `--staging-dir`, `--tag`, `--target-commit`, `--repo`, `--dry-run`.
  - Implement `validate_staging_preconditions`: git status check, tag peeling check, directory inspection, manifest validation against candidate bytes.
  - Implement `stage_draft_release`: draft creation, no-clobber upload, draft readback by tag, evidence serialization.
  - Implement `main` CLI entrypoint with sanitized error reporting.
- [ ] 4. Run GREEN verification:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
  .venv\Scripts\python.exe -B -m pytest tests/test_stage_draft_release.py -q
  launcher\.venv\Scripts\ruff.exe check ..\scripts\stage_draft_release.py tests/test_stage_draft_release.py
  ```
- [ ] 5. Review checkpoint: Verify staging tooling cannot publish, sign, rebuild, or clobber. Critical 0 / Important 0.
- [ ] 6. Commit changes:
  ```cmd
  git add scripts/stage_draft_release.py launcher/tests/test_stage_draft_release.py
  git commit -m "feat(tooling): add post-gate-2 draft staging script with dry-run seam"
  ```

---

## Task 5 — Documentation and Operator Runbook Migration

### Goal
Update operational runbooks and repository documentation to reflect the Two-Phase Staged-Draft Publication Architecture, document the strict Gate #2 normative sequence and byte mutation invalidation rule, supersede obsolete single-phase CI documentation, and provide clear operator execution instructions for Phase 1 and Phase 2.

### Files
- Modify: `docs/current/runtime-distribution.md`
- Modify: `docs/current/README.md`
- Modify: `docs/README.md`

### Documentation Updates
1. **Two-Phase Architecture Summary**:
   - Document Phase 1 (local candidate freeze, smoke on frozen bytes, fresh measurements, offline Ed25519 signing, local verification, Gate #2 clearance, draft creation via `scripts/stage_draft_release.py`).
   - Document Phase 2 (remote publication authority gate in Actions, binary download by asset ID, in-repo key verification, TOCTOU binding lock, activation via `PATCH draft=false`, `/releases/latest` validation).
2. **Gate #2 Normative Ordering**:
   Explicitly document the MUST-order sequence:
   1. Freeze candidate bytes in local candidate staging directory.
   2. Execute Launcher packaged smoke and Updater self-check on those exact frozen bytes.
   3. Freshly recompute Launcher/Updater/Core sizes+SHA-256 and Core installed identity after smoke.
   4. Construct and sign canonical `release-v2.json` using fresh measurements and offline `neko-update-prod-1` private key.
   5. Locally verify envelope, signature, and exact 3 component bindings against frozen bytes using `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`.
   6. Execute repository safety and clean worktree checks (`scripts/check_repository_safety.py`).
   7. Formal independent review approval (Critical 0 / Important 0).
   *State the Byte Mutation Invalidation Rule*: Any file touch, recompilation, or re-run after measurement invalidates Gate #2.
3. **Draft Staging and Workflow Dispatch Runbook**:
   - Document `python scripts/stage_draft_release.py --staging-dir <dir> --tag v5.1.0a3 --target-commit <sha>`.
   - Document capturing numeric `release_id` and four `asset_id` values.
   - Document triggering publication: `gh workflow run release.yml -f publish_release=true -f release_id=<ID> -f release_tag=v5.1.0a3 -f expected_target=<SHA>`.
4. **Supersession of Obsolete Single-Phase CI References**:
   - Mark single-phase CI compilation and local filesystem workflow inputs as obsolete/superseded.
   - Reaffirm that no Supabase or Admin service changes are introduced.

### Steps
- [ ] 1. Update `docs/current/runtime-distribution.md`.
- [ ] 2. Update `docs/current/README.md`.
- [ ] 3. Update `docs/README.md`.
- [ ] 4. Verify documentation links, code snippets, and terminology consistency.
- [ ] 5. Run safety check:
  ```cmd
  launcher\.venv\Scripts\python.exe scripts\check_repository_safety.py
  ```
- [ ] 6. Review checkpoint: Verify documentation matches spec without obsolete single-phase CI assumptions. Critical 0 / Important 0.
- [ ] 7. Commit changes:
  ```cmd
  git add docs/current/runtime-distribution.md docs/current/README.md docs/README.md
  git commit -m "docs(release): document two-phase staged draft publication and gate-2 ordering"
  ```

---

## Task 6 — Final End-to-End Acceptance and Quality Gate

### Goal
Execute comprehensive validation across all unit, workflow, and security test suites, run full canonical Launcher tests, verify repository safety, validate workflow YAML syntax, and perform an independent Sol High architecture review (C0/I0) confirming complete conformance with `docs/superpowers/specs/2026-09-09-software-update-two-phase-staged-draft-design.md`.

### Execution Steps
- [ ] 1. Run focused release test suites:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
  .venv\Scripts\python.exe -B -m pytest tests/test_verify_github_release_assets.py tests/test_release_workflow_publication_gate.py tests/test_release_workflow_github_assets.py tests/test_stage_draft_release.py -q
  ```
  Expected: All focused tests pass with zero failures.
- [ ] 2. Run full canonical Launcher test suite:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
  .venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=no
  ```
  Expected: Full suite passes; record authoritative summary counts.
- [ ] 3. Run Ruff code quality check across codebase:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1
  launcher\.venv\Scripts\ruff.exe check launcher/src launcher/tests scripts
  ```
  Expected: Zero lint or syntax warnings.
- [ ] 4. Run repository safety verification:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1
  launcher\.venv\Scripts\python.exe scripts/check_repository_safety.py
  ```
  Expected: `Repository safety check passed.`
- [ ] 5. Validate workflow YAML schema and syntax:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1
  launcher\.venv\Scripts\python.exe -c "import yaml, pathlib; [yaml.safe_load(p.read_text(encoding='utf-8')) for p in pathlib.Path('.github/workflows').glob('*.yml')]; print('YAML syntax valid')"
  ```
  Expected: `YAML syntax valid`.
- [ ] 6. Verify clean git diff:
  ```cmd
  cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1
  git diff --check
  ```
  Expected: Clean diff with zero whitespace or line-ending errors.
- [ ] 7. Perform independent Sol High architecture review:
  - Critical findings: 0
  - Important findings: 0
  - Confirm conformance against all 12 acceptance criteria in spec Section 12.
- [ ] 8. Operational Boundary Verification:
  - Confirm Gate #2 remains NOT PASSED (candidate rebuild, fresh measurements, offline signing, local verification, and draft creation remain to be executed by authorized operator).
  - Confirm remote publication was NOT triggered during implementation.

---

## Recovery Correction Task Chain (Pre-Gate #2 Sequence 2)

Following an independent Sol recovery ruling (Critical 0 / Important 0) after Gate #2 run `r4` sequence 1 burn and rejection, and subsequent recovery amendment review finding Critical 0 / Important 1 (C0/I1) for evidence anti-reconstruction (finding that local ceremony log/hash-chain/evidence index alone can be reconstructed retroactively without contemporaneous external anchoring), the following task chain MUST be executed in strict sequence before any new Gate #2 attempt. **None of these implementation corrections are claimed done yet.**

### Task R1 — Recovery Parameter Updates in Code and Tests [PENDING]
- **Goal**: Update publication authority verifier constants, staging preconditions, and test suites to enforce operative first-public-release values (`release_sequence=2`, `release_id="stable-0002"`, `minimum_supported_sequence=1`), ensuring sequence 1 and `stable-0001` fail closed.
- **Files**:
  - Modify: `scripts/verify_github_release_assets.py` (`FIRST_RELEASE_EXPECTED_SEQUENCE = 2`, `FIRST_RELEASE_EXPECTED_RELEASE_ID = "stable-0002"`, `FIRST_RELEASE_EXPECTED_MIN_SEQUENCE = 1`)
  - Modify: `scripts/stage_draft_release.py` (manifest precondition check for sequence `2` and `stable-0002`)
  - Modify: `launcher/tests/test_verify_github_release_assets.py` (update fixtures and assertions to sequence 2, stable-0002, and add negative tests asserting rejection of sequence 1 / stable-0001)
  - Modify: `launcher/tests/test_stage_draft_release.py` (update fixtures and assertions to sequence 2, stable-0002)
  - Modify: `launcher/tests/test_release_workflow_publication_gate.py`
  - Modify: `launcher/tests/test_release_workflow_github_assets.py`
- **Discipline**: Strict TDD: failing assertions first (RED), update constants/logic (GREEN), Ruff check, safety verification.
- **Status**: **PENDING** — Not yet implemented.

### Task R2 — Independent Sol Review Clearance (C0/I0) [PENDING]
- **Goal**: Perform an independent Sol architecture review of the recovery parameter code changes, test suite updates, and out-of-band controller task evidence anchoring specification.
- **Scope**: Confirm that:
  - `release_sequence == 2`, `release_id == "stable-0002"`, `minimum_supported_sequence == 1` are strictly enforced.
  - Manifests specifying sequence 1 or `stable-0001` fail closed unconditionally.
  - Every Gate #2 executable/action command is required to execute through the out-of-band controller task system (`@aikhai task execution`).
  - Candidate evidence index binds each controller task ID, and independent review retrieves and validates controller records directly.
  - Local event hash chaining is specified as defense-in-depth with external controller records as contemporaneous anchors.
  - Zero architecture, schema, or client-policy changes were introduced.
  - Independent review verdict reaches Critical 0 / Important 0 (C0/I0).
- **Status**: **PENDING** — Re-review pending following Round 1 fix.

### Task R3 — Fresh Candidate Staging and Provenance Copy Proof [PENDING]
- **Goal**: Establish a fresh candidate staging directory and mathematically prove byte-identical reuse of candidate executables and Core bundle from run r4 via out-of-band controller task execution.
- **Protocol**:
  - Create dedicated fresh directory (e.g. `candidate-release-5.1.0a3-r5` / candidate r5).
  - Execute copy and provenance verification ceremony through the out-of-band controller task system (`@aikhai task execution`), generating a unique controller task ID and external execution record.
  - Copy `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip` byte-identically from r4.
  - Measure source file sizes and SHA-256 digests; measure destination file sizes and SHA-256 digests; assert bit-for-bit equality.
  - Record provenance manifest (`provenance_manifest.json`) capturing source paths, destination paths, sizes, digests, copy timestamp, controller task ID, and operator identity.
  - Verify that run r4 directory remains quarantined and labeled `rejected/incomplete`.
- **Status**: **PENDING** — Not yet executed.

### Task R4 — Gate #2 Ceremony Sequence 2 Execution Under Durable Evidence Contract [PENDING]
- **Goal**: Execute a complete restart of the Gate #2 local release qualification ceremony for sequence 2 from Step 1 in strict normative order under the Durable Recovery Gate #2 Evidence Contract with out-of-band controller task anchoring.
- **Requirements**:
  - Every Gate #2 executable/action command MUST execute through the out-of-band controller task system (`@aikhai task execution`):
    1. Copy and provenance verification ceremony (Step 1).
    2. Launcher packaged smoke tests (Step 2).
    3. Updater self-check (`NekoUpdater.exe --self-check`) (Step 2).
    4. Post-smoke fresh measurement and Core proof (Step 3).
    5. Canonical manifest construction and Ed25519 signing (Step 4).
    6. Local envelope, signature, and 3-component verification (Step 5).
    7. Repository safety and clean worktree checks (Step 6).
  - Each command generates a unique controller task ID assigned at execution time. External controller records (`task_id`, system-recorded `started_at`, finished state, `exit_code`, `argv`, `cwd`, `stdout`/`stderr`) are authoritative contemporaneous execution anchors outside candidate directory and worktree.
  - Candidate evidence event log and index (`evidence_index.json` / `ceremony.log`) binds each exact controller task ID to: candidate ID (e.g. `candidate-r5`), event sequence number, expected argv/cwd, copied stdout/stderr hashes, exit code 0, start/end timestamps.
  - Candidate-local copies and transcripts are secondary convenience evidence, never sole authority.
  - Local event hash chain: Each event record includes `previous_event_hash` (pointing to previous canonical event hash, with genesis string for event 1) and canonical `event_hash` as defense-in-depth. External controller task records are the contemporaneous anti-reconstruction anchor; hash chain alone is explicitly insufficient.
  - Step 2 Smoke & self-check: Separate retained stdout and stderr files (even if zero bytes). Pre-smoke and post-smoke candidate SHA-256 hashes and sizes verified equal.
  - Step 3: Fresh measurement strictly after both Step 2 end times. No executables run after Step 3 measurement.
  - Step 4: Manifest constructed with `channel=stable`, `release_sequence=2`, `minimum_supported_sequence=1`, `release_id=stable-0002`, `updater_protocol=1..1`, component versions `5.1.0a3`, key ID `neko-update-prod-1` using offline private key in Vault MASTER.
  - Step 5: Locally verify canonical envelope, Ed25519 signature, and 3-component bindings against candidate bytes using `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`.
  - Step 6: Repository safety check (`check_repository_safety.py`) and clean worktree verification.
  - Step 7: Independent review clearance (C0/I0). Independent reviewer MUST retrieve and confirm referenced controller task results directly from the controller task execution system (or controller-provided immutable result view) and compare task ID, argv, cwd, times, exit, and stdout/stderr hashes to candidate evidence index. Fabricated transcripts with no matching controller task ID fail Gate #2.
  - Zero remote Git or release side effects before Gate #2 clearance. PM/evidence-process infrastructure, not product architecture or client security-policy change.
- **Status**: **PENDING** — Not yet executed.
