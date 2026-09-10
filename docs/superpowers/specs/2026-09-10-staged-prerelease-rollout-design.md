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

*Migration Note:* v5.1.2 adopts this staged rollout architecture. v5.1.1 remains historical.

## 3. Required Lifecycle for Patch Releases

1. **Source Acceptance:** Source commit is approved.
2. **Build Frozen Candidate:** Build process generates exact artifacts.
3. **Gate2:** Metadata validation against artifacts.
4. **Immutable Tag:** Create an exact tag for the source commit.
5. **Exact-Tag CI Gate:** CI builds, tests, and smoke verifies the exact tag.
6. **Staged Prerelease:** Create a GitHub prerelease containing exactly four signed assets.
    - **Visibility Invariant:** This prerelease MUST NOT become `/releases/latest` and MUST NOT be visible to stable clients.
7. **Hosted Verification:** Independent verification using immutable release IDs/asset IDs.
    - **Discovery Invariant:** Prerelease verification cannot rely on `/releases/latest`. It MUST use the immutable numeric release ID, exact tag, and asset IDs.
8. **READY_FOR_ROLLOUT:** Prerelease is fully verified and staged.
9. **Rollout (Promotion):** Explicit rollout action promotes the verified prerelease to stable/latest.
    - **Immutability Invariant:** This step requires NO rebuilding, resigning, retagging, or replacing assets. Hashes must remain identical. Rollout is the activation event for user update discovery.
10. **Rollout Verification:** Final confirmation that `/releases/latest` resolves to the promoted release.

## 4. Ledger States

The release lifecycle tracks these defined ledger states:

- **BUILT:** Frozen candidate artifacts are built.
- **GATE2_PASS:** Artifacts pass Gate2 metadata validation.
- **TAG_CI_PASS:** Exact-tag CI, build, test, and smoke checks pass.
- **STAGED_PRERELEASE:** GitHub prerelease is created with the exact 4 signed assets.
- **HOSTED_VERIFIED_READY_FOR_ROLLOUT:** Staged prerelease independently verified via immutable IDs.
- **ROLLED_OUT_STABLE:** Prerelease promoted to stable (`/releases/latest`).
- **ROLLOUT_GATE3_PASS:** Post-rollout verification confirms client discovery via `/releases/latest`.
- **FAILED / HOLD (variants):** State indicating failure at any step or a deliberate hold (e.g., `PUBLISHED_NOT_ACCEPTED HOLD C0/I1`).

## 5. Client Discovery Behavior
Stable clients poll `/releases/latest` or equivalent stable feeds to discover updates. During the `STAGED_PRERELEASE` phase, clients will not discover the update. Only after transitioning to `ROLLED_OUT_STABLE` does the activation event occur, making the update visible to stable clients.

## 6. Manifest, Signature, and Asset Immutability
All assets, including signatures and update manifests, are frozen at the `STAGED_PRERELEASE` step. Promotion to stable is purely a metadata state change on the GitHub Release object (unchecking the prerelease flag and making it the latest release). Since the release body, tag, and assets are strictly immutable, security and provenance rules are maintained end-to-end.

## 7. Security and Provenance Rules
- No asset is allowed to change hash after `GATE2_PASS`.
- Signatures applied before `STAGED_PRERELEASE` must be verifiable against the final assets.
- Hosted verification strictly targets specific asset IDs ensuring no silent replacement attacks.

## 8. Rollback and Supersession Behavior
If an issue is found in `STAGED_PRERELEASE`, the release transitions to a `FAILED` or `HOLD` variant, and a new sequence is initiated (e.g., moving to the next patch version). Rollbacks from `ROLLED_OUT_STABLE` require issuing a new patch release that supersedes the bad release, following this same staged rollout architecture. Historical releases are never rewritten.
