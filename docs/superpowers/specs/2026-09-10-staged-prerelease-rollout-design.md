# Staged Prerelease to Stable Rollout Architecture

**Date:** 2026-09-10  
**Context:** Neko-Family-Proxy 5.1.x Lifecycle  
**Decision:** Approach A (Owner Approved)

## 1. Overview
This architecture separates the readiness of a release candidate from its user rollout. We preserve GitHub-only update authority, ensuring update validation stays centralized. A release progresses through an independent staging and hosted verification phase as a "prerelease". Upon successful verification, an explicit rollout action promotes the prerelease to a stable release. This promotion does not require rebuilding, resigning, retagging, or changing asset hashes, ensuring the exact bytes verified during staging are delivered to end users.

## 2. Version Progression and Migration Note
- **Baseline:** v5.1.0
- **Historical:** v5.1.1 remains a `PUBLISHED_NOT_ACCEPTED HOLD C0/I1` state and must not be rewritten.
- **Current Target:** v5.1.2 sequence 6 stable-0006 at source commit `e867dea`.

*Historical Compatibility Note:* v5.1.0 and v5.1.1 utilized an earlier direct-to-stable release workflow and are considered historical baseline. v5.1.2 adopts this staged rollout architecture. Historical releases are immutable and never rewritten.

### 2.1 Explicit Invariant Table for v5.1.2

| Property | Target Invariant |
| --- | --- |
| version | 5.1.2 |
| tag | v5.1.2 |
| release_sequence | 6 |
| release_id | stable-0006 |
| minimum_supported_sequence | 1 |
| channel | stable |
| mandatory | false |
| updater protocol | 1..1 |
| key id | neko-update-prod-1 |

**Hosted Assets (Exact Component Names):**
1. `NekoLauncher.exe`
2. `NekoUpdater.exe`
3. `NekoProxyCore.zip`
4. `release-v2.json`

## 3. Required Lifecycle for Patch Releases

1. **Source Acceptance:** Source commit is approved.
2. **Build Frozen Candidate:** Build process generates exact artifacts (frozen bytes built first).
3. **Gate2:** Metadata validation measures the exact frozen bytes.
4. **Sign:** `release-v2.json` is signed against those exact bytes before any staged upload. No asset changes are allowed afterward.
5. **Immutable Tag:** Create an exact tag for the source commit.
6. **Exact-Tag CI Gate Acceptance:** CI runs against the exact tag. This requires:
    - Windows canonical non-integration test suite.
    - Build-installer/package jobs.
    - Launcher packaged smoke tests.
    - Updater self-check tests.
    - Core update-preflight/manifest verification as applicable.
    - *Failure Transition:* Failed or skipped required jobs result in immediate `HOLD`. No staged publication occurs.
7. **Staged Prerelease Publication:** Create a GitHub prerelease containing exactly the four signed assets.
    - **Visibility Invariant:** This prerelease MUST NOT become `/releases/latest` and MUST NOT be visible to stable clients.
8. **Staged Hosted Verification:** Independent verification using immutable release IDs. Criteria:
    - Release must be `prerelease=true`, `draft=false`, and NOT returned by `/releases/latest`.
    - Verification uses immutable numeric release ID, exact tag, and exact asset IDs.
    - Run the unmodified verifier, complete signature verification, Core identity/provenance checks, and execute a resolver-equivalent path that does not depend on latest discovery.
9. **READY_FOR_ROLLOUT:** Prerelease is fully verified and staged.
    - *Release-Ready Definition:* `HOSTED_VERIFIED_READY_FOR_ROLLOUT` means "release complete and ready" but NOT user rollout. User rollout requires a separate explicit owner/PM rollout task.
10. **Rollout (Promotion):** Explicit rollout action promotes the verified prerelease to stable/latest.
    - Only a `HOSTED_VERIFIED_READY_FOR_ROLLOUT` release can be promoted.
    - Promotion only flips release metadata needed for stable/latest (`prerelease=false`, `make_latest="true"`).
    - **Immutability Invariant:** This step must re-read immutable asset IDs, hashes, and sizes before and after, rejecting any drift. Hashes must remain identical.
11. **Rollout Verification (Gate3):** Final read-only Gate3 must confirm:
    - `/releases/latest` successfully resolves the release.
    - Production `GitHubLatestReleaseGateway` and `GitHubReleaseResolver` accept the exact same bytes, manifest, and sequence verified during staging.

## 4. Failure and Hold Transitions

Failure at any phase requires transitioning to a terminal `FAILED` or `HOLD` state. A published or tagged failed release is never repaired in place; it must be superseded by the next patch version and sequence number.

- **Gate2 Failure:** Aborts release. Fix code and re-initiate new source commit.
- **Exact-Tag CI Failure:** Any failed or skipped required CI job results in `HOLD`. No staged publication.
- **Staged Publication Failure:** Network or API failure during upload. If partial, tag may be left but must be marked as `HOLD` or `FAILED`.
- **Staged Verification Failure:** If the staged release fails verification (e.g., signature mismatch, missing asset), it is marked `HOLD`.
- **Rollout Promotion Failure:** If the API fails to flip the metadata or drift is detected in asset hashes/IDs, abort immediately to `HOLD`.
- **Post-Rollout Verification (Gate3) Failure:** If production gateways fail to resolve `/releases/latest` or asset hashes differ, manual emergency mitigation is required (e.g. unpublishing) and a new sequence must be prepared.

## 5. Ledger States

The release lifecycle tracks these defined ledger states:

- **BUILT:** Frozen candidate artifacts are built.
- **GATE2_PASS:** Artifacts pass Gate2 metadata validation.
- **TAG_CI_PASS:** Exact-tag CI, build, test, and smoke checks pass.
- **STAGED_PRERELEASE:** GitHub prerelease is created with the exact 4 signed assets.
- **HOSTED_VERIFIED_READY_FOR_ROLLOUT:** Staged prerelease independently verified via immutable IDs. Release complete but not rolled out.
- **ROLLED_OUT_STABLE:** Prerelease promoted to stable (`/releases/latest`).
- **ROLLOUT_GATE3_PASS:** Post-rollout verification confirms client discovery via `/releases/latest` and asset hash/manifest integrity.
- **FAILED / HOLD (variants):** State indicating failure at any step or a deliberate hold.

## 6. Testing

The staging and rollout architecture requires specific test coverage:
- **Predicate Tests:** Unit tests for release-state predicates (e.g., verifying a release is `prerelease=true` and `draft=false`).
- **Verifier Tests:** Workflow and staging verifier tests validating signature and provenance checks on pre-release assets.
- **Negative Discovery Tests:** Tests confirming negative discovery on `/releases/latest` (staged releases must not resolve to latest).
- **Drift Tests:** Immutable-ID drift tests ensuring asset IDs and hashes match exactly before and after promotion.
- **End-to-End Verification:** End-to-end dry-run and read-only verification of the full rollout pipeline.

## 7. Client Discovery Behavior
Stable clients poll `/releases/latest` or equivalent stable feeds to discover updates. During the `STAGED_PRERELEASE` phase, clients will not discover the update. Only after transitioning to `ROLLED_OUT_STABLE` does the activation event occur, making the update visible to stable clients.

## 8. Manifest, Signature, and Asset Immutability
All assets, including signatures and update manifests, are frozen at the `STAGED_PRERELEASE` step. Promotion to stable is purely a metadata state change on the GitHub Release object (unchecking the prerelease flag and making it the latest release). Since the release body, tag, and assets are strictly immutable, security and provenance rules are maintained end-to-end.
