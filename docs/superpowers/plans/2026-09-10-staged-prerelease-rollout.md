# Staged Prerelease Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Goal
Implement the staged prerelease to stable rollout architecture for Neko-Family-Proxy v5.1.x, replacing direct-to-stable drafts with a two-phase rollout: prerelease staging and a subsequent metadata-only promotion to stable.

## Architecture
1. **Prerelease Staging:** Candidate is staged as `prerelease=true`, `draft=false`. Hosted verification uses numeric release IDs without querying `/releases/latest`.
2. **Rollout Promotion:** An explicit rollout action flips metadata to `prerelease=false`, `make_latest="true"` after verification and drift checks.

## Tech Stack
- Python 3.12 (Launcher, Release Scripts, Tests)
- GitHub CLI (gh api) and GitHub Actions workflow
- Windows (Powershell)

## Spec Path
`docs/superpowers/specs/2026-09-10-staged-prerelease-rollout-design.md`

## Global Constraints
- Target Commitish and Exact Tag adherence (v5.1.2) must be preserved.
- No retagging, rebuilding, or asset replacement allowed.
- Historic releases (v5.1.0/v5.1.1) and current sequence invariants (seq6 stable-0006) preserved.
- Exact 4 assets preserved.
- `gh_release.json` remains untracked.
- Plan executed and committed to `release/5.1`.

## File-Structure Map
- **Modified:** `launcher/src/neko_launcher/infrastructure/github_release.py` (Add `fetch_by_id` responsibility)
- **Modified:** `launcher/tests/test_github_release.py` (Tests for `fetch_by_id`)
- **Modified:** `scripts/verify_github_release_assets.py` (Add `--require-prerelease` verification logic)
- **Modified:** `launcher/tests/test_verify_github_release_assets.py` (Tests for `--require-prerelease`)
- **Modified:** `scripts/stage_draft_release.py` (Extend with `--as-prerelease` flag. Rename is unnecessary/risky because it breaks downstream/historical caller references in existing CI/developer muscle memory. We backwards-compatibly extend the existing tool.)
- **Modified:** `launcher/tests/test_stage_draft_release.py` (Tests for the script's new prerelease capability)
- **Modified:** `.github/workflows/release.yml` (Modify `publish-release` to `staged-verification`, add `rollout-stable` job with metadata-only promotion and Gate3 latest-resolver validation)

---

## Task Decomposition

### 1. Staged-Release State/Predicate and Tooling Semantics
**Files:** `launcher/src/neko_launcher/infrastructure/github_release.py`, `launcher/tests/test_github_release.py`, `scripts/verify_github_release_assets.py`, `launcher/tests/test_verify_github_release_assets.py`
**Interfaces Consumes/Produces:** Python API and CLI arguments. Consumes `GitHubRelease` JSON schema. Produces updated `--require-prerelease` verification logic.

- [ ] Step 1.1: Add failing test `test_gateway_exact_get_by_id_accepts_prerelease_not_draft` in `launcher/tests/test_github_release.py`.
  - **Command:** `cd launcher && python -m pytest tests/test_github_release.py -k test_gateway_exact_get_by_id`
  - **Expected RED:** `AttributeError: 'GitHubReleaseGateway' object has no attribute 'fetch_by_id'`
- [ ] Step 1.2: Implement `fetch_by_id(release_id: int) -> GitHubRelease | None` in `GitHubReleaseGateway` within `github_release.py` to explicitly resolve staged prereleases. 
  - **GREEN Command:** `cd launcher && python -m pytest tests/test_github_release.py -k test_gateway_exact_get_by_id`
- [ ] Step 1.3: Add failing tests `test_verify_assets_fails_when_require_prerelease_and_prerelease_is_false` and `test_verify_assets_fails_when_require_prerelease_and_draft_is_true` in `launcher/tests/test_verify_github_release_assets.py`. Test that passing `--require-prerelease` correctly asserts `prerelease=True, draft=False`.
  - **Command:** `cd launcher && python -m pytest tests/test_verify_github_release_assets.py -k "test_verify_assets_fails_when_require_prerelease"`
  - **Expected RED:** Missing argument or unexpected success.
- [ ] Step 1.4: Update `scripts/verify_github_release_assets.py` to add `--require-prerelease`. Adjust logic: if `--require-prerelease` is passed, assert `prerelease` is true and `draft` is false.
  - **GREEN Command:** `cd launcher && python -m pytest tests/test_verify_github_release_assets.py`
- [ ] Step 1.5: Run canonical regression commands for `test_github_release.py` and `test_verify_github_release_assets.py`.
  - **Command:** `cd launcher && python -m pytest tests/test_github_release.py tests/test_verify_github_release_assets.py -q` (Expected: 84 passed)
- [ ] Step 1.6: Review diff (`git diff`) and commit.
  - **Commit Command:** `git commit -am "feat(release): Add staged-release state predicates and prerelease verification support"`

### 2. Workflow Publication Changes for Exact-Tag Staged Prerelease
**Files:** `scripts/stage_draft_release.py`, `launcher/tests/test_stage_draft_release.py`
**Interfaces Consumes/Produces:** Modifies `gh release create` call and ID discovery loop. Produces a prerelease instead of a draft when flagged.

- [ ] Step 2.1: Add failing tests `test_execution_stages_prerelease_and_returns_immutable_evidence` and `test_prerelease_discovery_requires_prerelease_not_draft` in `launcher/tests/test_stage_draft_release.py`.
  - **Command:** `cd launcher && python -m pytest tests/test_stage_draft_release.py -k prerelease`
  - **Expected RED:** `AssertionError` or tests failing because script doesn't support prerelease.
- [ ] Step 2.2: Modify `scripts/stage_draft_release.py`. Add `--as-prerelease` flag. When set, replace `--draft` with `--prerelease=true` in `gh release create`. Update ID discovery to assert `prerelease=True` and `draft=False` when flag is set. Adjust dispatch output to explicitly set `rollout_release=true`.
  - **GREEN Command:** `cd launcher && python -m pytest tests/test_stage_draft_release.py`
- [ ] Step 2.3: Run canonical regression commands.
  - **Command:** `cd launcher && python -m pytest tests/test_stage_draft_release.py -q` (Expected: 33 passed, plus 2 new = 35 passed)
- [ ] Step 2.4: Review diff and commit.
  - **Commit Command:** `git commit -am "feat(release): Change candidate staging to prerelease mode with exact-tag enforcement via backwards-compatible flag"`

### 3. Staged Hosted Verification by Immutable Numeric IDs
**Files:** `.github/workflows/release.yml`
**Interfaces Consumes/Produces:** Modifies `publish-release` job. Consumes numeric ID and staged assets. Produces verification output `HOSTED_VERIFIED_READY_FOR_ROLLOUT`.

- [ ] Step 3.1: Rename `publish-release` job in `.github/workflows/release.yml` to `staged-verification`. Remove the inline `gh api ... --method PATCH` promotion step (both Revalidate bindings and Verify published steps).
- [ ] Step 3.2: In `staged-verification` job, update "Fetch staged draft and download required assets by immutable IDs" step: assert `$release.draft -eq $false` and `$release.prerelease -eq $true`. Verify negative cases for draft=true, prerelease=false during staging, and release-id mismatch. Also enforce exact-tag CI gate.
- [ ] Step 3.3: In "Verify staged assets and signed envelope authority" step, replace `--require-draft` with `--require-prerelease`. Add numeric-ID hosted verification with `/latest` negative check ensuring `/latest` does not resolve to the staged numeric ID yet.
- [ ] Step 3.4: Add a concluding step that echoes `HOSTED_VERIFIED_READY_FOR_ROLLOUT` marker.
- [ ] Step 3.5: Verify repository safety checks.
  - **Command:** `python scripts/check_repository_safety.py`
- [ ] Step 3.6: Review diff and commit.
  - **Commit Command:** `git commit -am "ci(release): Implement staged hosted verification for prerelease candidates"`

### 4. Metadata-only Rollout Promotion Path
**Files:** `.github/workflows/release.yml`
**Interfaces Consumes/Produces:** Adds `rollout-stable` job. Consumes verified numeric ID. Produces published stable release.

- [ ] Step 4.1: Add a new workflow input `rollout_release` to `workflow_dispatch` in `.github/workflows/release.yml` with type boolean and default false.
- [ ] Step 4.2: Add new job `rollout-stable` that executes on `if: github.event_name == 'workflow_dispatch' && inputs.rollout_release == true`.
- [ ] Step 4.3: In `rollout-stable`, fetch immutable `release_id` via `gh api` and assert it is still `prerelease=true`, `draft=false`. Verify negative cases: release-id mismatch, draft=true, prerelease=false, attempted rollout before readiness, or skipped required CI job.
- [ ] Step 4.4: In `rollout-stable`, read asset bindings from staging (or verify current asset sizes and IDs against expected 4 exact assets). Check for asset-ID/hash/size drift ensuring pre/post immutable asset bindings are identical.
- [ ] Step 4.5: Promote via `gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID" --method PATCH -F prerelease=false -f make_latest=true`.
- [ ] Step 4.6: Add post-promotion check reading back release ID to assert `prerelease=false, draft=false, make_latest=true` and exact asset hashes/IDs.
- [ ] Step 4.7: Verify YAML syntax and repository safety.
  - **Command:** `python scripts/check_repository_safety.py`
- [ ] Step 4.8: Review diff and commit.
  - **Commit Command:** `git commit -am "ci(release): Add metadata-only rollout promotion path with asset drift checks"`

### 5. Post-Rollout Gate3 (Latest Resolver Validation)
**Files:** `.github/workflows/release.yml`
**Interfaces Consumes/Produces:** Appends Gate3 checks to `rollout-stable` job. Consumes `/releases/latest`. Produces final verification success.

- [ ] Step 5.1: In `rollout-stable` (or a downstream job), use a bounded retry script in PowerShell to poll `/releases/latest`. Verify negative cases: latest resolving wrong ID, and skipped required CI job logic.
- [ ] Step 5.2: Assert the returned `id` matches `RELEASE_ID` and the tag matches `v5.1.2`.
- [ ] Step 5.3: Assert asset IDs map identically to the staged `initial-asset-bindings.json` and sizes match exactly for the 4 expected assets.
- [ ] Step 5.4: Review the entire `release.yml` to ensure exact 4 assets are maintained and numeric-ID hosted verification with `/latest` negative checks are covered comprehensively.
- [ ] Step 5.5: Run safety check.
  - **Command:** `python scripts/check_repository_safety.py`
- [ ] Step 5.6: Review diff and commit.
  - **Commit Command:** `git commit -am "ci(release): Implement post-rollout Gate3 verification against production resolver"`
