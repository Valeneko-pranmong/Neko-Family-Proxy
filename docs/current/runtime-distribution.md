# NekoProxyCore runtime distribution

**Status:** Current policy — updated September 2026 for Two-Phase Staged-Draft Software Update architecture.

`NekoProxyCore` is a separately licensed external runtime. It is never committed to this repository's source tree or embedded inside the `NekoLauncher.exe` PE binary.

Under the Owner's GitHub-only architecture decision, `NekoProxyCore.zip` is accepted as an exact fixed product asset published alongside `NekoLauncher.exe` and `NekoUpdater.exe` in fixed GitHub Releases, governed by signed `release-v2.json` authority (public Core accepted).

The historical Supabase private Storage / Admin grant / capability distribution path for Software Update is **SUPERSEDED BY OWNER GITHUB-ONLY ARCHITECTURE DECISION, NOT PASS**. Historical blocker evidence is preserved; unrelated Supabase/Admin/account/recovery/proxy services remain untouched with no update fallback.

---

## 1. Two-Phase Staged-Draft Publication Architecture

Software update release publication is partitioned into two sequential phases across the trust boundary:

1. **Phase 1: Local Operator Environment (Controlled Machine)**:
   - Candidate binaries (`NekoLauncher.exe`, `NekoUpdater.exe`) are compiled and the Core bundle (`NekoProxyCore.zip`) is assembled.
   - Release qualification executes under strict **Gate #2 normative ordering**.
   - Offline Ed25519 signing (`neko-update-prod-1`) generates canonical `release-v2.json` from fresh post-smoke measurements.
   - After Gate #2 clearance, the operator pushes the Git commit and tag (`v5.1.0a3`), then stages an unpublished draft release on GitHub using `scripts/stage_draft_release.py`.
   - Tooling uploads the exact four candidate assets (`--clobber=false`) and captures the numeric `release_id` and name-to-asset-ID bindings.
2. **Phase 2: Remote CI Authority Gate (GitHub Actions Hosted Runner)**:
   - Final release publication authority belongs **exclusively** to GitHub Actions (`.github/workflows/release.yml`). Direct local workstation publication (e.g. `PATCH draft=false` or `gh release edit --draft=false`) is strictly prohibited.
   - The publication workflow is manually triggered via `workflow_dispatch` with exact parameters: numeric `release_id`, `release_tag=v5.1.0a3`, `expected_target=<SHA>`, and `publish_release=true`.
   - The hosted runner downloads staged assets by immutable numeric `asset_id` as raw binary streams.
   - The runner enforces key binding to in-repo `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']` and verifies cryptographic signatures, canonical JSON formatting, formats, and hashes via `scripts/verify_github_release_assets.py`.
   - The workflow enforces first-release fail-closed parameters, re-validates draft state and asset ID bindings immediately before publication to eliminate TOCTOU race conditions, activates the release via `PATCH draft=false`, and verifies public visibility on `/releases/latest`.

---

## 2. Gate #2 Normative Ordering (MUST-Order Sequence)

Gate #2 is the mandatory local release qualification checkpoint. Remote publication actions (Git commit push, tag push, draft release creation, asset upload) are strictly prohibited until Gate #2 is formally passed.

Gate #2 MUST execute in the following exact sequence:

1. **Freeze exact candidate bytes**:
   Isolate candidate files (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`) in a dedicated candidate staging directory. Candidate bytes are locked against further modification.
2. **Execute packaged smoke and self-check on frozen bytes**:
   Run Launcher packaged smoke tests and Updater self-check (`NekoUpdater.exe --self-check`) directly on those exact frozen candidate bytes.
3. **Freshly recompute measurements after smoke**:
   Directly following smoke completion, freshly compute byte sizes and SHA-256 digests for `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip`, and the Core installed identity SHA-256 digest from the canonical sorted inventory of `NekoProxyCore.zip`.
4. **Construct and sign canonical release-v2.json**:
   Using the fresh post-smoke measurements from Step 3, construct the manifest payload (`channel=stable`, `release_sequence=1`, `minimum_supported_sequence=1`, signed string `release_id=stable-0001`, `updater_protocol={"minimum": 1, "maximum": 1}`, component versions `5.1.0a3`) and sign it locally using the offline Ed25519 private key for `neko-update-prod-1` in Vault MASTER.
5. **Locally verify envelope, signature, and component bindings**:
   Locally verify canonical JSON formatting, Ed25519 envelope signature, and exact three component descriptors against the frozen candidate bytes using `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`.
6. **Execute repository safety and scope checks**:
   Run `scripts/check_repository_safety.py` and inspect Git status to verify a clean worktree with no uncommitted modifications, no untracked release debris, and no leaked private authority materials or secrets.
7. **Obtain independent review clearance**:
   Obtain formal independent review approval with Critical 0 and Important 0 (C0/I0) findings.

### Byte Mutation Invalidation Rule
Any byte mutation, file touch, recompilation, or test re-run after the fresh measurement in Step 3 immediately invalidates Gate #2. If any candidate file is altered or re-tested after measurement, the candidate is void and the operator must stage a new candidate and restart the entire qualification sequence from Step 1. If `release-v2.json` was already signed, that `release_sequence` is permanently spent and the subsequent candidate must increment `release_sequence`.

---

## 3. Operator Runbooks: Staging and Publication

### 3.1 Phase 1: Local Draft Staging Runbook
After Gate #2 is passed, the Git commit and release tag (`v5.1.0a3`) are pushed to GitHub. The operator stages the candidate assets:

```cmd
launcher\.venv\Scripts\python.exe scripts\stage_draft_release.py --staging-dir <candidate-staging-dir> --tag v5.1.0a3 --target-commit <40-char-sha>
```

Optional arguments:
- `--dry-run`: Validates preconditions and prints planned commands without mutating GitHub state.
- `--repo Valeneko-pranmong/Neko-Family-Proxy`: Target GitHub repository (defaults to canonical repo).

**Staging Preconditions and Guarantees**:
- The staging directory must contain strictly the exact four required files (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, `release-v2.json`). No extra or untrusted files are permitted in the staging directory.
- The worktree must be clean and the local Git tag must point to the target commit.
- Manifest descriptors must match candidate files bit-for-bit.
- `scripts/stage_draft_release.py` strictly creates an unpublished draft release (`draft=true`, `prerelease=false`) with non-clobbering asset uploads (`--clobber=false`).
- The script captures GitHub's numeric `release_id` and the four numeric `asset_id` bindings, then formats the exact Phase 2 workflow dispatch command.
- **Safety Boundary**: Staging tooling NEVER final-publishes, NEVER signs manifests, NEVER compiles binaries, and NEVER moves tags.

### 3.2 Distinction of Release Identifiers
To prevent operational confusion:
1. **GitHub Draft Release ID** (`release_id` in workflow dispatch / API): An immutable positive integer assigned by GitHub REST API to the draft release object. Used for lookup, asset streaming, pre-publish binding locks, and activation.
2. **Signed Manifest Envelope Release ID** (`release_id` inside `release-v2.json`): A string embedded within the signed JSON payload representing logical update identity (strictly `"stable-0001"` for the initial release).

### 3.3 Phase 2: Remote Publication Workflow Dispatch
The operator triggers final publication in GitHub Actions:

```bash
gh workflow run release.yml \
  --ref v5.1.0a3 \
  -f publish_release=true \
  -f release_id=<NUMERIC_GITHUB_RELEASE_ID> \
  -f release_tag=v5.1.0a3 \
  -f expected_target=<40_CHAR_COMMIT_SHA>
```

`--ref v5.1.0a3` selects the reviewed workflow definition from the approved release tag. `expected_target` remains the exact approved checkout and authority commit; the two values serve distinct bindings and neither may be omitted.

**Remote Publication Gate Execution**:
1. Workflow checks out `expected_target` and validates inputs locally.
2. Draft release object is fetched by numeric `release_id` (verifying `draft=true`, `prerelease=false`, `tag_name=release_tag`, and commit targeting).
3. The four update assets are downloaded as raw octet-streams directly by numeric `asset_id`.
4. The workflow executes `scripts/verify_github_release_assets.py`:
   - Verifies manifest envelope `key_id == "neko-update-prod-1"`.
   - Derives Ed25519 public key strictly from in-repo `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']`.
   - Validates first-release invariants: `channel=stable`, `release_sequence=1`, `minimum_supported_sequence=1`, string `release_id=stable-0001`, `updater_protocol=1..1`, component versions `5.1.0a3`, and tag `v5.1.0a3`.
   - Validates exact component formats (`raw-pe-v1`, `zip-core-v1`), sizes, and SHA-256 digests.
5. Pre-publish TOCTOU lock: re-queries release by numeric `release_id`, asserting release state and all four `name -> asset_id` bindings are unchanged.
6. Publication activation: issues `PATCH /repos/.../releases/:release_id` with `{"draft": false}`.
7. Post-publish validation: confirms `draft=false` and verifies `/releases/latest` resolves to the identical release ID and asset bindings.

---

## 4. Supersession of Obsolete Single-Phase CI Architecture

The previous single-phase CI model—where CI was envisioned to compile binaries, accept local workstation paths, upload assets, and publish in a single workflow—is **OBSOLETE AND SUPERSEDED**:
1. **Hosted runner storage isolation**: Microsoft Azure-hosted GitHub Actions runners cannot access local operator drives (`E:\...`).
2. **PyInstaller non-reproducibility**: PE binaries built by PyInstaller vary across build environments and timestamps. Binaries built in CI will not match offline signed hashes.
3. **Offline private key boundary**: Production release signing keys reside strictly offline in Vault MASTER. Uploading private keys to GitHub Secrets or CI runners is strictly prohibited.
4. **CI build job separation**: The `build-installer` job in `.github/workflows/release.yml` (triggered on tag push) builds test executables for CI diagnostics only. CI-compiled artifacts possess **zero release authority** and are never published as production software update payloads.

---

## 5. Delivery and update contract

1. **Fixed GitHub Releases only**: Current Software Update architecture uses fixed GitHub Releases with latest published stable release discovery.
2. **Four REQUIRED CLIENT ASSETS**: Each stable release must contain exactly one each of `release-v2.json` (signed envelope authority), `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip` (public Core accepted). Permitted human-facing extras (such as checksum files or installers) may exist on the GitHub release, but client update logic ignores them and never trusts them. The local staging directory itself must contain strictly the exact four files.
3. **Signed release-v2 authority**: The Ed25519-signed envelope authenticates the three product descriptors (Launcher, Updater, Core), including signed size, SHA-256, and Core installed identity, and binds the required client assets to the release. Product bytes must match their authenticated descriptors. Unsigned extras confer no authority.
4. **No update fallback**: There is no fallback to Supabase private Storage, Admin distribution endpoints, or Vercel routes. Unrelated Supabase/Admin services remain untouched.
5. **Publish-last verification requirement**: Under separate release authority, release drafting, asset upload, and complete independent verification must precede publication; only fully verified drafts may be published via GitHub Actions authority.
6. **Local destination**: The Updater extracts the approved frozen Core bundle to the external runtime directory:

   `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe`

7. **Secret hygiene**: Customer data, Supabase secret/service-role keys, and private signing keys are never placed in release archives or assets. Standalone keys and plaintext settings are not released.

Launcher resolves `NekoProxyCore.exe` only from the external runtime path above. It does not implement bundled-runtime or environment-variable path override. The Launcher EXE contains no Core runtime payload.

---

## 6. Current Release Gate Status

- **Gate #2 Status**: **NOT PASSED**. Candidate rebuild after latest implementation, fresh post-smoke remeasurement, offline production Ed25519 signing, local verification, and draft creation remain to be executed under separate release authority. Real staging has NOT been executed.
- **Gate #3 Status**: **NOT PASSED**. Remote GitHub Actions publication and `/releases/latest` validation have NOT occurred.
- **Implementation Status**: Two-phase staged-draft publication architecture implementation (`docs/superpowers/plans/2026-09-09-software-update-two-phase-staged-draft-implementation.md`) has completed Tasks 1–4 with per-task C0/I0; Task 5 documentation migration is in progress; Task 6 final branch acceptance has not yet run.
- **Explicit Boundary**: Documentation does not claim production signing, tag creation, draft release, asset upload, publication, merge, push, deployment, live auto-update completion, Gate #2 clearance, or Gate #3 clearance.
