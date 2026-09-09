# NekoProxyCore runtime distribution

**Status:** Current policy — updated September 2026 for Two-Phase Staged-Draft Software Update architecture.

---

## Current Production Release State: v5.1.0a3 (Gate #2 PASS / Gate #3 PASS) — 2026-09-09

- **Production Status**: Production release `v5.1.0a3` is officially published and active. Both Gate #2 (qualification) and Gate #3 (hosted publication and proof) are **PASSED (C0/I0)**.
- **Release Commit vs Post-Release Branch Head Distinction**:
  - **Release Tag & Hosted Artifact Commit**: `6ad9bc9ee8fdcf5b770b73bec7eab2f7f31109bc` (tag `v5.1.0a3`). Shipped binaries and signed manifest payload were built and signed strictly from this release commit.
  - **Post-Release Automation Branch HEAD**: `16dba6e3748e9fe1dc9e3fd7e11309dc1838582e` on `release/5.1` (clean, synced with `origin/release/5.1`). Contains post-release automation fixes discovered during real publication; shipped binaries did NOT come from `16dba6e`.
- **Gate #2 PASS (Normative Order Recovery r6)**:
  - Sequence: 2 / Release ID: `stable-0002` / `minimum_supported_sequence`: 1 / `updater_protocol`: 1..1.
  - *Spent Sequence 1 Invariant*: Sequence 1 (`stable-0001`) was permanently spent-unpublished during rejected run r4 and remains strictly historical.
  - Gate #2 Qualification: Critical 0 / Important 0 (C0/I0) under strict 7-step normative ordering.
  - Gate2-Qualified Hashes and Sizes (bit-for-bit immutable):
    - `NekoLauncher.exe`: 29,904,786 bytes / SHA-256 `41415cb03fd050145f09f77ac16b65ac1eca39ff533477dba21dc93bd1079e35`
    - `NekoUpdater.exe`: 14,342,842 bytes / SHA-256 `44b3900d00a4c30546cd8070871db95d3a9f48dd4ec04aa9338ebef85a1f2320`
    - `NekoProxyCore.zip`: 371,995,837 bytes / SHA-256 `b969512875bd640265af0b01730e0d6c78027dc584bfa04c029c6115a6599ebc`
    - `release-v2.json`: 1,640 bytes / SHA-256 `af110662d76ae124ec313241aa1de8f7d73c7d2b47ab4b0c41f003feecf2b85c`
    - Core Installed Identity: SHA-256 `fcb4f5e9a05831c645a1e4cf7a667ab1e0a8c2c621d7853a9adbd2d81aebf7ad`
- **Gate #3 PASS (Hosted Release Publication & Proof)**:
  - Hosted GitHub Release ID: `385616276`
  - Tag: `v5.1.0a3`
  - Target Release Commit: `6ad9bc9ee8fdcf5b770b73bec7eab2f7f31109bc`
  - Release State: `draft=false`, `prerelease=false`.
  - Latest Pointer: `/releases/latest` resolves to `385616276` (`v5.1.0a3`).
  - Immutable Asset IDs on GitHub:
    - `NekoLauncher.exe`: `552989471`
    - `NekoUpdater.exe`: `552989468`
    - `NekoProxyCore.zip`: `552989467`
    - `release-v2.json`: `552989470`
  - Publication Workflow Run & Operational Recovery: GitHub Actions publication workflow run `34371586108` verified and published the immutable release successfully, but concluded failure only at immediate latest readback due to GitHub API propagation timing. Reviewed operational recovery `gh release edit v5.1.0a3 --latest` corrected the latest pointer; fresh hosted re-review achieved Critical 0 / Important 0 (C0/I0). Workflow run `34371586108` did NOT conclude success directly.
  - Gate 3 Hosted Proof: Fresh download streams by immutable numeric asset ID match exact bytes and SHA-256 digests; production `verify_github_release_assets.py` PASS; public `GitHubLatestReleaseGateway` PASS; production `GitHubReleaseResolver` PASS; GitHub-only Software Update authority confirmed with zero Admin-Supabase update dependency.
- **Post-Release Automation Fixes (Reviewed C0/I0)**:
  - `ecf60837`: import path repair + safe draft discovery in staging tooling
  - `b6a261a8`: remote asset size binding in verification
  - `f23fa0a` + `16dba6e`: explicit latest contract + typed boolean API payload + behavioral retry tests
  - Canonical post-release regression at `16dba6e`: 1,732 passed / 35 skipped / 0 failed; Ruff PASS; safety PASS; YAML PASS; diff clean.
  - Final integrated Sol review C0/I0, safe to push. Branch `release/5.1` was fast-forward pushed to `16dba6e`. Published tag `v5.1.0a3` intentionally remains `6ad9bc9ee8fdcf5b770b73bec7eab2f7f31109bc`; hosted release provenance unchanged.
- **Autonomous Kanban Unblock Policy**: Active throughout publication; release blockers were diagnosed, fixed under strict TDD, and reviewed automatically. At final ledger time, no engineering or release blocker remains.

`NekoProxyCore` is a separately licensed external runtime. It is never committed to this repository's source tree or embedded inside the `NekoLauncher.exe` PE binary.

Under the Owner's GitHub-only architecture decision, `NekoProxyCore.zip` is accepted as an exact fixed product asset published alongside `NekoLauncher.exe` and `NekoUpdater.exe` in fixed GitHub Releases, governed by signed `release-v2.json` authority (public Core accepted).

The historical Supabase private Storage / Admin grant / capability distribution path for Software Update is **SUPERSEDED BY OWNER GITHUB-ONLY ARCHITECTURE DECISION, NOT PASS**. Historical blocker evidence is preserved; unrelated Supabase/Admin/account/recovery/proxy services remain untouched with no update fallback.

---

## 1. Two-Phase Staged-Draft Publication Architecture

Software update release publication is partitioned into two sequential phases across the trust boundary:

1. **Phase 1: Local Operator Environment (Controlled Machine)**:
   - Candidate binaries (`NekoLauncher.exe`, `NekoUpdater.exe`) are compiled and the Core bundle (`NekoProxyCore.zip`) is assembled.
   - Release qualification executes under strict **Gate #2 normative ordering**.
   - Offline Ed25519 signing (`neko-update-prod-1`) generates canonical `release-v2.json` from fresh post-smoke measurements (`channel=stable`, `release_sequence=2`, `minimum_supported_sequence=1`, `release_id=stable-0002`, component versions `5.1.0a3`). Note: initial release sequence 1 / `stable-0001` is historical spent-unpublished authority following rejected Gate #2 run r4.
   - After Gate #2 clearance, the operator pushes the Git commit and tag (`v5.1.0a3`), then stages an unpublished draft release on GitHub using `scripts/stage_draft_release.py`. Before draft creation, the staging tool read-only verifies via the GitHub Git-data API that the canonical remote tag peels to the exact approved target commit.
   - Tooling uploads the exact four candidate assets (`--clobber=false`) and captures the numeric `release_id` and name-to-asset-ID bindings.
2. **Phase 2: Remote CI Authority Gate (GitHub Actions Hosted Runner)**:
   - Final release publication authority belongs **exclusively** to GitHub Actions (`.github/workflows/release.yml`). Direct local workstation publication (e.g. `PATCH draft=false` or `gh release edit --draft=false`) is strictly prohibited.
   - The publication workflow is manually triggered via `workflow_dispatch` with exact parameters: numeric `release_id`, `release_tag=v5.1.0a3`, `expected_target=<SHA>`, and `publish_release=true`.
   - The hosted runner downloads staged assets by immutable numeric `asset_id` as raw binary streams.
   - The runner enforces key binding to in-repo `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']` and verifies cryptographic signatures, canonical JSON formatting, formats, and hashes via `scripts/verify_github_release_assets.py`.
   - The workflow enforces first-release fail-closed parameters (`channel=stable`, `release_sequence=2`, `minimum_supported_sequence=1`, `release_id=stable-0002`, `updater_protocol=1..1`, component versions `5.1.0a3`), re-validates draft state and asset ID bindings immediately before publication to eliminate TOCTOU race conditions, activates the release via `PATCH draft=false`, and verifies public visibility on `/releases/latest`.

---

## 2. Gate #2 Normative Ordering (MUST-Order Sequence)

Gate #2 is the mandatory local release qualification checkpoint. Remote publication actions (Git commit push, tag push, draft release creation, asset upload) are strictly prohibited until Gate #2 is formally passed.

Gate #2 MUST execute in the following exact sequence, with every executable/action command executed through the out-of-band controller task system (`@aikhai task execution`) as an authoritative execution anchor:

1. **Freeze exact candidate bytes and provenance proof**:
   Isolate candidate files (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`) in a dedicated candidate staging directory. Candidate bytes are locked against further modification. If reusing binaries from candidate r4, copy and byte-equality provenance verification is executed through the out-of-band controller task system.
2. **Execute packaged smoke and self-check on frozen bytes**:
   Run Launcher packaged smoke tests and Updater self-check (`NekoUpdater.exe --self-check`) directly on those exact frozen candidate bytes through the out-of-band controller task system, capturing separate stdout/stderr files and execution timing.
3. **Freshly recompute measurements after smoke**:
   Directly following smoke completion, freshly compute byte sizes and SHA-256 digests for `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip`, and the Core installed identity SHA-256 digest from the canonical sorted inventory of `NekoProxyCore.zip` through the out-of-band controller task system.
4. **Construct and sign canonical release-v2.json**:
   Using the fresh post-smoke measurements from Step 3, construct the manifest payload (`channel=stable`, `release_sequence=2`, `minimum_supported_sequence=1`, signed string `release_id=stable-0002`, `updater_protocol={"minimum": 1, "maximum": 1}`, component versions `5.1.0a3`) and sign it locally using the offline Ed25519 private key for `neko-update-prod-1` in Vault MASTER through the out-of-band controller task system.
   *Compatibility Floor Invariant*: `minimum_supported_sequence` remains `1` because it is the monotonic floor for client compatibility and mandatory updates. The internal spending of sequence 1 during an uncompleted, rejected Gate #2 run does not revoke client compatibility or advance any installed client's high-water mark, as sequence 1 was never published to or observed by clients.
   *No Architecture/Schema Changes*: No architecture, schema, or client-policy changes are introduced; this is strictly a release-parameter and evidence-contract correction.
5. **Locally verify envelope, signature, and component bindings**:
   Locally verify canonical JSON formatting, Ed25519 envelope signature, and exact three component descriptors against the frozen candidate bytes using `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']` through the out-of-band controller task system.
6. **Execute repository safety and scope checks**:
   Run `scripts/check_repository_safety.py` and inspect Git status to verify a clean worktree with no uncommitted modifications, no untracked release debris, and no leaked private authority materials or secrets through the out-of-band controller task system.
7. **Obtain independent review clearance**:
   Obtain formal independent review approval with Critical 0 and Important 0 (C0/I0) findings. The independent reviewer MUST retrieve and confirm referenced controller task results directly from the controller task system (or controller-provided immutable result view) and compare task ID, argv, cwd, times, exit code, and stdout/stderr hashes to the candidate evidence index and local event hash chain. A locally fabricated transcript with no matching controller task ID fails Gate #2.

### Byte Mutation Invalidation Rule
Any byte mutation, file touch, recompilation, or test re-run after the fresh measurement in Step 3 immediately invalidates Gate #2. If any candidate file is altered or re-tested after measurement, the candidate is void and the operator must stage a new candidate and restart the entire qualification sequence from Step 1. If `release-v2.json` was already signed, that `release_sequence` is permanently spent and the subsequent candidate must increment `release_sequence`.

### Durable Recovery Gate #2 Evidence Contract
Following the sequence 1 burn and rejection of Gate #2 run `r4` for missing retained Step 2 audit evidence, and the subsequent recovery amendment review finding (Critical 0 / Important 1, C0/I1) regarding the risk of retroactive local evidence reconstruction, any subsequent Gate #2 qualification attempt MUST execute under the following strict durable evidence contract:

1. **Fresh Candidate ID and Path Isolation**:
   - The qualification attempt MUST use a fresh, distinct candidate staging directory and candidate identifier (e.g. `candidate-r5` at `E:\Github\candidate-release-5.1.0a3-r5`).
   - The candidate staging directory must contain strictly the candidate files being qualified.
2. **Provenance and Byte-Equality Verification**:
   - When reusing binaries from candidate r4, provenance must be mathematically proven before Step 2 begins: source file paths, source file sizes and SHA-256 digests, destination file sizes and SHA-256 digests, and bit-for-bit byte equality must be validated and recorded in a retained provenance manifest (`provenance_manifest.json`). Binary reuse is permitted ONLY byte-identically.
   - The copy and provenance verification ceremony is executed through the out-of-band controller task system.
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
9. **Out-of-Band Controller Task Execution Anchor (@aikhai task execution)**:
   - For every Gate #2 executable/action command (copy/provenance ceremony, Launcher smoke, Updater self-check, post-smoke measurement/Core proof, signing, local verifier, repository safety), execution MUST occur through the out-of-band controller task system (`@aikhai task execution`).
   - Each command must have a unique controller task ID created at execution time.
   - The controller system records `task_id`, system-recorded `started_at`, finished state, `exit_code`, `argv`, `cwd`, and `stdout`/`stderr` streams externally, outside the candidate directory and worktree.
   - These external controller records are the authoritative contemporaneous execution anchors against retroactive synthesis.
10. **Candidate Evidence Event Index Binding and Secondary Local Evidence**:
    - The candidate evidence event records and index (`evidence_index.json` / `ceremony.log`) MUST reference each exact controller task ID and bind it to:
      - candidate ID (e.g. `candidate-r5`)
      - event sequence number
      - expected `argv` and `cwd`
      - copied stdout and stderr file SHA-256 hashes
      - process exit code (must be `0`)
      - start and end timestamps.
    - Candidate-local copies and transcripts are secondary convenience evidence, never the sole authority.
11. **Independent Gate #2 Review Task Retrieval and Direct Verification**:
    - Independent Gate #2 review (Step 7) MUST retrieve and confirm the referenced controller task results directly from the controller/task system (or controller-provided immutable result view).
    - The reviewer MUST compare controller task ID, `argv`, `cwd`, start/end timestamps, exit code, and stdout/stderr hashes to the candidate evidence index.
    - A locally fabricated transcript with no matching controller task ID fails Gate #2 unconditionally.
12. **Local Event Hash Chain as Defense-in-Depth**:
    - As defense-in-depth, each event record includes `previous_event_hash` (pointing to the canonical hash of the preceding event, with a defined genesis string for event 1) and its own canonical `event_hash`.
    - *Anti-Reconstruction Invariant*: The external controller task record is the contemporaneous anti-reconstruction anchor. The local hash chain alone is explicitly insufficient to prevent retroactive synthesis.
13. **Strict Normative Ordering and Zero Remote Pre-Gate-2 Side Effects**:
    - Strict sequential ordering across all 7 steps is strictly preserved.
    - Zero remote Git or release side effects before Gate #2 clearance: no remote git commit push, no tag push, no GitHub draft release creation, no asset upload, no TSA (timestamp authority) calls, and no new external public services.
    - This is PM/evidence-process infrastructure, not product architecture or client security-policy change.
14. **Quarantine of Rejected Run r4 Evidence**:
    - The rejected run `r4` evidence must remain quarantined in its own separate directory (e.g. `candidate-release-5.1.0a3-r4-REJECTED/`), explicitly labeled as rejected/incomplete, and never mixed with recovery candidate evidence.

---

## 3. Operator Runbooks: Staging and Publication

### 3.1 Phase 1: Local Draft Staging Runbook
After Gate #2 is passed, the Git commit and release tag (`v5.1.0a3`) are pushed to GitHub. The operator stages the candidate assets:

```cmd
launcher\.venv\Scripts\python.exe scripts\stage_draft_release.py --staging-dir <candidate-staging-dir> --tag v5.1.0a3 --target-commit <40-char-sha>
```

Optional arguments:
- `--dry-run`: Validates preconditions and prints planned commands without mutating GitHub state.

The production staging repository is fixed to `Valeneko-pranmong/Neko-Family-Proxy`. It is non-configurable: the CLI accepts no repository-selection argument, and every GitHub CLI command and API path uses that canonical repository.

**Staging Preconditions and Guarantees**:
- The staging directory must contain strictly the exact four required files (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, `release-v2.json`). No extra or untrusted files are permitted in the staging directory.
- The worktree must be clean and the local Git tag must point to the target commit.
- Manifest descriptors must match candidate files bit-for-bit. Before any GitHub mutation, the script strictly extracts `NekoProxyCore.zip`, verifies its canonical bundle, and binds the verified canonical-manifest SHA-256 to the signed Core installed identity.
- Before draft creation, `scripts/stage_draft_release.py` uses the read-only GitHub Git-data API to verify that the release tag on the fixed canonical repository peels exactly to the approved target commit. It also preserves `gh release create --verify-tag --target <exact-target> --draft`, creates only an unpublished non-prerelease release, and uploads without clobbering (`--clobber=false`). It has no tag-creation or tag-mutation authority.
- The script captures GitHub's numeric `release_id` and the four numeric `asset_id` bindings, then formats the exact Phase 2 workflow dispatch command.
- **Safety Boundary**: Staging tooling NEVER final-publishes, NEVER signs manifests, NEVER compiles binaries, and NEVER moves tags.

### 3.2 Distinction of Release Identifiers
To prevent operational confusion:
1. **GitHub Draft Release ID** (`release_id` in workflow dispatch / API): An immutable positive integer assigned by GitHub REST API to the draft release object. Used for lookup, asset streaming, pre-publish binding locks, and activation.
2. **Signed Manifest Envelope Release ID** (`release_id` inside `release-v2.json`): A string embedded within the signed JSON payload representing logical update identity (strictly `"stable-0002"` for this operative first-public-release; historical `"stable-0001"` is permanently spent-unpublished).

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
   - Validates first-release invariants: `channel=stable`, `release_sequence=2`, `minimum_supported_sequence=1`, string `release_id=stable-0002`, `updater_protocol=1..1`, component versions `5.1.0a3`, and tag `v5.1.0a3` (rejects spent sequence 1 / stable-0001).
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

## 6. Release Gate Status (Current: Gate #2 PASS / Gate #3 PASS)

- **Gate #2 Status**: **PASSED** (Critical 0 / Important 0 [C0/I0] on recovery r6 / sequence 2 / release_id `stable-0002` / `minimum_supported_sequence` 1 / `updater_protocol` 1..1). All 7 normative steps verified with controller execution anchors and hash chain.
- **Gate #3 Status**: **PASSED** (Critical 0 / Important 0 [C0/I0]). Hosted GitHub release ID `385616276`, tag `v5.1.0a3` at target commit `6ad9bc9ee8fdcf5b770b73bec7eab2f7f31109bc`, `draft=false`, `prerelease=false`, `/releases/latest` verified. Immutable asset IDs: Launcher `552989471`, Updater `552989468`, Core `552989467`, release-v2 `552989470`.
- **Publication Workflow & Recovery**: Workflow run `34371586108` verified and published the immutable release successfully, but concluded failure only at immediate latest readback. Reviewed operational recovery `gh release edit v5.1.0a3 --latest` corrected latest pointer; fresh hosted re-review C0/I0.
- **Hosted Proof**: Exact download streams by immutable ID match candidate hashes/sizes bit-for-bit. Production `verify_github_release_assets.py` PASS; public `GitHubLatestReleaseGateway` PASS; production `GitHubReleaseResolver` PASS; zero Admin-Supabase update dependency.
- **Post-Release Automation Fixes**: Fixes `ecf60837`, `b6a261a8`, `f23fa0a`, and `16dba6e` reviewed C0/I0; canonical regression 1732 passed / 35 skipped / 0 failed; fast-forward pushed to `16dba6e`. Tag `v5.1.0a3` remains `6ad9bc9`.
- **Engineering / Blocker Status**: 0 blockers remain. Autonomous Kanban unblock policy resolved all issues autonomously.

### Historical Pre-Release Gate Status (Superseeded)

The following paragraphs represent the historical state prior to recovery r6 qualification and publication:
- *Historical Gate #2 Pre-Release Checkpoint*: Operational Gate #2 qualification run `r4` was REJECTED for audit-evidence retention (failure to capture and persist separate stdout/stderr transcripts and timing metadata for Launcher smoke and Updater self-check). Sequence 1 / `stable-0001` was signed once during run r4 and is PERMANENTLY SPENT-UNPUBLISHED. It must never be published or regenerated. Subsequent recovery amendment review recorded Critical 0 / Important 1 (C0/I1) for evidence anti-reconstruction (finding that local ceremony log/hash-chain/evidence index alone can be reconstructed retroactively without contemporaneous external anchoring). Recovery Amendment Fix Round 1 anchored all Gate #2 executable/action commands through the out-of-band controller task system (@aikhai task execution) and added an event hash chain as defense-in-depth. This was superseded by successful Gate #2 PASS on recovery r6 (sequence 2).
- *Historical Gate #3 Pre-Release Checkpoint*: Workflow dispatch, remote publication, and `/releases/latest` validation had not occurred at that time. Superseded by Gate #3 PASS (Release ID 385616276).
