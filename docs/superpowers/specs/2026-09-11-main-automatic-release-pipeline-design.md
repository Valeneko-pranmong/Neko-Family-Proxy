# MAIN RELEASE PIPELINE SPECIFICATION: FINAL CANDIDATE

**Provenance Note**: The architecture detailed in this specification was approved by the Owner on 2026-09-11 (C0/I0 review result).

## 1. Goal
Establish a fully automated, `main`-branch-driven patch release pipeline utilizing the smallest zero-click model. This pipeline safely increments versions, builds assets, and publishes updates while strictly adhering to local signing custody and maintaining 100% backward compatibility for existing 5.1.x clients. 
The pipeline operates with **zero per-release owner clicks**.

## 2. One-Time Repository Migration & Setup Gate
Before enabling the main-based automatic release controller, the following one-time migration and setup steps are required:
- **Migration Strategy:** Reconcile `release/5.1` into `main` through a reviewed merge/cherry-pick strategy that preserves production 5.1 updater/installer/release tooling and history. Do NOT delete `release/5.1` until main parity and acceptance are proven.
- **Migration Acceptance Gate:** `main` must contain the required 5.1 production code/tooling, pass full tests and security checks, and show no unintended history rewrite or v5.1.3 promotion. Only after parity is proven does `release/5.1` become read-only/historical.
- **Setup Gates:** One-time initial setup gates (e.g., verifying controller readiness and repo state) must be passed before the automatic release controller is enabled.

## 3. Zero-Click Architecture: Local Build & Sign Model
The architecture abandons the "Remote Build -> Local Sign" model in favor of a **Source Acceptance -> Local Build, Sign & Publish** model. 

### Phase 1: Remote Source Acceptance (GitHub Actions)
- **Trigger:** GitHub Actions runs on product-impacting pushes/merges to `main`. Trigger classification must be robust for nested tests/docs and mixed commits. Release CI must **not** auto-release for docs/test/CI-only changes.
- **Responsibility:** Performs source acceptance, test, and security checks ONLY.
- **Output:** Emits an immutable commit/run identity upon success.
- **Restriction:** GitHub CI must NOT create release tags or allocate versions.

### Phase 2: Local Controller Execution (Hermes)
- **Mechanism:** A persistent local Hermes release controller observes successful, accepted `main` commits.
- **Serialization & Offline Queueing:** The Hermes Kanban DB acts as the durable local release queue and final version/tag allocator to prevent races. If the controller is offline, a thin adapter idempotently creates Kanban tasks from accepted CI commits which queue up and are processed later in order. No manual intervention or secondary bespoke queue system is needed.
- **Explicit Target Version Allocation:** The controller strictly uses the version target defined in `release_target.json`. Failed attempts retry on the same target. The target becomes immutable only upon successful USER Stable acceptance. Subsequent patches require an explicit PM user-bug intent update to the target file; the automatic skip-occupied-tags behavior is superseded and disabled.
- **Local Build & Acceptance Tests:** The controller builds the exact one-click installer + current updater artifacts using the trusted canonical pipeline, and immediately runs acceptance tests on the built artifacts to ensure correctness before signing.

### Phase 3: Custody, Verification & Publication
- **Local Signing:** The controller signs ONLY the software-update release envelope using the existing production software-update key.
- **Verification:** Independently verifies all bindings.
- **Tagging:** Creates an immutable tag at the exact accepted `main` SHA.
- **Publication:** Publishes one unified Stable/Latest GitHub Release.
- **Failure & Fix-Forward:** In case of failure or partial publication, the pipeline enforces a fix-forward strategy. History is immutable; broken releases are abandoned, and a new `main` commit must trigger the next version allocation.
- **Post-Publication:** Runs the post-publication resolver/Gate3.

## 4. Asset Contracts and Legacy 5.1.x Compatibility
During the legacy compatibility phase, the unified release must contain exactly these 5 assets. A clean single-asset public page is deferred until a separately designed migration proves legacy clients cannot be stranded.
1. `NekoFamilyProxy-Setup.exe`
2. `NekoLauncher.exe`
3. `NekoUpdater.exe`
4. `NekoProxyCore.zip`
5. `release-v2.json`

## 5. Security & Key Custody Reference
- **Production Key Custody:** The correct key custody reference is `C:\Users\Pranmong\AppData\Local\NekoFamily\release-custody\neko-update-prod-1.pem`. This is a reference only; the key contents must NEVER be read or printed.
- **Forbidden Authority:** The file `runtime-settings.key` is strictly unrelated and forbidden in the Core package. It MUST NEVER be treated as a release signing authority.
