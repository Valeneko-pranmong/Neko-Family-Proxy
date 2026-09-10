# agentic-worker
goal: Implement the staged prerelease to stable rollout architecture for Neko-Family-Proxy v5.1.x
assignee: release
review-status: [ ] Self-Reviewed

## Architecture
The new release architecture shifts from direct-to-stable drafts to a two-phase rollout:
1. **Prerelease Staging:** Candidate is staged as `prerelease=true`, `draft=false`. Hosted verification uses numeric release IDs without querying `/releases/latest`.
2. **Rollout Promotion:** An explicit rollout action flips metadata to `prerelease=false`, `make_latest="true"` after verification and drift checks.

## Tech Stack
- Python 3.12 (Launcher, Release Scripts, Tests)
- GitHub CLI (gh api) and GitHub Actions workflow
- Windows (Powershell)

## Spec and Global Constraints
- Target Commitish and Exact Tag adherence (v5.1.2) must be preserved.
- No retagging, rebuilding, or asset replacement allowed.
- Historic releases (v5.1.0/v5.1.1) and current sequence invariants (stable-0006) preserved.
- `gh_release.json` remains untracked.
- Plan committed to `release/5.1`.

## Task Decomposition

### 1. Staged-Release State/Predicate and Tooling Semantics
**Goal:** Enable release models and verification tools to distinguish prerelease readiness from stable activation.
- **`launcher/src/neko_launcher/infrastructure/github_release.py`:**
  - Add `GitHubReleaseGateway.fetch_by_id(release_id: int) -> GitHubRelease | None` to explicitly resolve staged prereleases (since `GitHubLatestReleaseGateway` correctly rejects prereleases and drafts).
- **`launcher/tests/test_github_release.py`:**
  - Test `fetch_by_id` accepts `prerelease=True, draft=False`.
- **`scripts/verify_github_release_assets.py`:**
  - Add `--require-prerelease` argument. Remove `draft=True` constraint if this flag is passed, and instead assert `prerelease=True, draft=False`.
- **`launcher/tests/test_verify_github_release_assets.py`:**
  - Validate new negative/positive enforcement of `--require-prerelease`.
- **Commit boundary:** `feat(release): Add staged-release state predicates and prerelease verification support`

### 2. Workflow Publication Changes for Exact-Tag Staged Prerelease
**Goal:** Ensure v5.1.2 is created as a prerelease (and only after exact-tag checks).
- **`scripts/stage_draft_release.py` -> rename/refactor to `scripts/stage_prerelease.py`:**
  - Remove `--draft` from `gh release create`, replace with `--prerelease=true`.
  - Update ID discovery loop and readback to assert `prerelease=True` and `draft=False`.
  - Rename `StageDraftReleaseError` to `StagePrereleaseError`.
  - Adjust dispatch output to point to a new/updated workflow job (`rollout_release=true`).
- **`launcher/tests/test_stage_draft_release.py` -> rename to `test_stage_prerelease.py`:**
  - Update executor assertions: `["gh", "release", "create", TAG, "--target", TARGET, "--verify-tag", "--prerelease=true"]`.
  - Test validation fails if GitHub readback reflects `draft=True`.
- **Commit boundary:** `feat(release): Change candidate staging to prerelease mode with exact-tag enforcement`

### 3. Staged Hosted Verification by Immutable Numeric IDs
**Goal:** Verifier targets immutable release IDs without hitting `/releases/latest`.
- **`.github/workflows/release.yml` - `publish-release` job modifications:**
  - Rename job from `publish-release` to `staged-verification`.
  - Pass `--require-prerelease` instead of `--require-draft` to `verify_github_release_assets.py`.
  - The powershell fetch checks should enforce `$release.draft -eq $false` and `$release.prerelease -eq $true`.
  - Remove the inline `gh api ... --method PATCH` promotion step. Instead, the job concludes with `HOSTED_VERIFIED_READY_FOR_ROLLOUT` marker (via output or text evidence).
- **Commit boundary:** `ci(release): Implement staged hosted verification for prerelease candidates`

### 4. Metadata-only Rollout Promotion Path
**Goal:** Explicit promotion of a verified prerelease to stable/latest with drift checks.
- **`.github/workflows/release.yml`:**
  - Add new job `rollout-stable` that executes on `workflow_dispatch: inputs.rollout_release == true`.
  - Re-fetches immutable `release_id` and asserts it is still `prerelease=true`, `draft=false`.
  - Reads asset bindings from staging (or verifies current asset sizes and IDs).
  - Promotes via `gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID" --method PATCH -F prerelease=false -f make_latest=true`.
  - Post-promotion check reads back release ID to assert `prerelease=false, draft=false, make_latest=true` and exact asset hashes/IDs.
- **Commit boundary:** `ci(release): Add metadata-only rollout promotion path with asset drift checks`

### 5. Post-Rollout Gate3 (Latest Resolver Validation)
**Goal:** Production gateways confirm `/releases/latest` is now active and identically formed.
- **`.github/workflows/release.yml` - within `rollout-stable` (or downstream job):**
  - Use `GitHubLatestReleaseGateway` or equivalent bounded retry script to poll `/releases/latest`.
  - Assert the returned `id` matches `RELEASE_ID` and the tag matches `v5.1.2`.
  - Assert asset IDs map identically to the staged `initial-asset-bindings.json`.
- **Commit boundary:** `ci(release): Implement post-rollout Gate3 verification against production resolver`
