# NEKO FAMILY PROXY — Launcher Component Status & Start Here

```text
DOCUMENT:                       docs/current/README.md
STATUS:                         RELEASE_PUBLISHED / GATE_3_PASS (v5.1.0a3)
PRODUCT_BASELINE:               PRODUCTION RELEASE (v5.1.0a3)
CURRENT_WORKSTREAM:             FINAL_RELEASE_LEDGER_DOCS (t_94c2023f)
ACTIVE_BRANCH:                  release/5.1
RELEASE_TAG:                    v5.1.0a3 (at release commit 6ad9bc9ee8fdcf5b770b73bec7eab2f7f31109bc)
POST_RELEASE_BRANCH_HEAD:       16dba6e3748e9fe1dc9e3fd7e11309dc1838582e (clean, synced origin/release/5.1)
GATE_2_STATUS:                  PASS (C0/I0 on recovery r6 / sequence 2 / release_id stable-0002)
GATE_3_STATUS:                  PASS (C0/I0 / GitHub release ID 385616276 / latest verified)
SECURITY_SCAN:                  PASS (0 secrets, fail-closed auth, offline Ed25519 signing)
P0_BLOCKERS:                    0
P1_ISSUES:                      0
LAST_VERIFIED:                  2026-09-09 +07:00 (Asia/Bangkok)
```

> **Current-state rule:** verify Git branch, HEAD, status, and this directory before assigning work. The active feature branch is newer development state than older production/Closed-Beta status blocks. Frozen release evidence remains historical authority for the exact accepted artifacts only.

---

## Current Production Release Status — v5.1.0a3 (Gate #2 PASS / Gate #3 PASS) — 2026-09-09

- **Production Release v5.1.0a3**: Successfully qualified under Gate #2 (C0/I0) and published to GitHub Releases under Gate #3 (C0/I0).
- **Release Commit vs Post-Release Branch Head Distinction**:
  - **Release Tag & Hosted Artifact Commit**: `6ad9bc9ee8fdcf5b770b73bec7eab2f7f31109bc` (tag `v5.1.0a3`). All four shipped binaries and signed manifest payload were built and signed strictly from this release commit.
  - **Post-Release Automation Branch HEAD**: `16dba6e3748e9fe1dc9e3fd7e11309dc1838582e` on `release/5.1` (clean, synced with `origin/release/5.1`). Contains post-release staging and publication automation fixes discovered during live release; shipped binaries did NOT come from `16dba6e`.
- **Gate #2 PASS (Normative Recovery r6)**:
  - Sequence: 2 / Release ID: `stable-0002` / `minimum_supported_sequence`: 1 / `updater_protocol`: 1..1.
  - Note: Sequence 1 (`stable-0001`) is permanently spent-unpublished following rejected run r4 and remains strictly historical.
  - Gate #2 Qualification: Critical 0 / Important 0 (C0/I0) under strict 7-step normative ordering.
  - Gate2-Qualified Hashes and Sizes (bit-for-bit immutable):
    - `NekoLauncher.exe`: 29,904,786 bytes / SHA-256 `41415cb03fd050145f09f77ac16b65ac1eca39ff533477dba21dc93bd1079e35`
    - `NekoUpdater.exe`: 14,342,842 bytes / SHA-256 `44b3900d00a4c30546cd8070871db95d3a9f48dd4ec04aa9338ebef85a1f2320`
    - `NekoProxyCore.zip`: 371,995,837 bytes / SHA-256 `b969512875bd640265af0b01730e0d6c78027dc584bfa04c029c6115a6599ebc`
    - `release-v2.json`: 1,640 bytes / SHA-256 `af110662d76ae124ec313241aa1de8f7d73c7d2b47ab4b0c41f003feecf2b85c`
    - Core Installed Identity: SHA-256 `fcb4f5e9a05831c645a1e4cf7a667ab1e0a8c2c621d7853a9adbd2d81aebf7ad`
- **Gate #3 PASS (Hosted Release Publication & Proof)**:
  - Hosted GitHub Release ID: `385616276`
  - Release Tag: `v5.1.0a3`
  - Target Release Commit: `6ad9bc9ee8fdcf5b770b73bec7eab2f7f31109bc`
  - Hosted Release State: `draft=false`, `prerelease=false`.
  - Public Visibility: `/releases/latest` resolves to release ID `385616276` (`v5.1.0a3`).
  - Immutable Asset IDs on GitHub:
    - `NekoLauncher.exe`: `552989471`
    - `NekoUpdater.exe`: `552989468`
    - `NekoProxyCore.zip`: `552989467`
    - `release-v2.json`: `552989470`
  - Publication Workflow Run & Operational Recovery: GitHub Actions publication workflow run `34371586108` verified and published the immutable release successfully, but its postcondition failed because the latest pointer did not update to the new release (hosted `/releases/latest` remained old v5.0.0 across repeated samples for >2 minutes after publish, and an attempted raw API make_latest path did not produce convergence; root cause was not transient propagation timing). Native reviewed operational recovery `gh release edit v5.1.0a3 --latest` immediately corrected hosted discovery; fresh hosted re-review achieved Critical 0 / Important 0 (C0/I0). Workflow run `34371586108` did NOT conclude success directly.
  - Gate 3 Hosted Proof: Fresh download streams by immutable ID match exact bytes and SHA-256 digests; production `verify_github_release_assets.py` PASS; public `GitHubLatestReleaseGateway` PASS; production `GitHubReleaseResolver` PASS; GitHub-only Software Update authority confirmed with zero Admin-Supabase update dependency.
- **Post-Release Automation Fixes (Reviewed C0/I0)**:
  - `ecf60837`: import path repair + safe draft discovery in staging tool
  - `b6a261a8`: remote asset size binding in verification
  - `f23fa0a` + `16dba6e`: explicit latest contract + typed boolean API payload + behavioral retry tests
  - Canonical post-release regression at `16dba6e`: 1,732 passed / 35 skipped / 0 failed; Ruff PASS; safety PASS; YAML PASS; diff clean.
  - Final integrated Sol review C0/I0, safe to push. Branch `release/5.1` was fast-forward pushed to `16dba6e`. Published tag `v5.1.0a3` intentionally remains `6ad9bc9ee8fdcf5b770b73bec7eab2f7f31109bc`; hosted release provenance unchanged.
- **Autonomous Kanban Unblock Policy**: Active and exercised throughout publication; release blockers were diagnosed, remediated under strict TDD, and reviewed automatically. At final ledger time, no engineering or release blocker remains.

---

## 1. What is the Launcher doing now?

The Launcher has **completed the dashboard-redesign stream** on:

```text
feature/dashboard-redesign @ 32b1b68
```

All 6 implementation phases and UI polish gates from [`dashboard-redesign-plan.md`](dashboard-redesign-plan.md) and [`dashboard-redesign-completion.md`](dashboard-redesign-completion.md) are **PASS**.

The branch is closed and prepared for merge into `main`. The next stream (`feature/live-update`) will branch from `main` following merge completion.

---

## 1.1 Software Update Architecture (Two-Phase Staged-Draft Publication)

Software Update on `release/5.1` is governed by the Owner-approved Two-Phase Staged-Draft Publication Architecture:

- **Current Authoritative Architecture**: Software updates follow the Two-Phase Staged-Draft Publication Architecture ([`docs/superpowers/specs/2026-09-09-software-update-two-phase-staged-draft-design.md`](../superpowers/specs/2026-09-09-software-update-two-phase-staged-draft-design.md)).
  - **Phase 1 (Local Operator Environment)**: Candidate binaries (`NekoLauncher.exe`, `NekoUpdater.exe`) and Core bundle (`NekoProxyCore.zip`) are assembled, frozen in a dedicated staging directory, qualified under strict Gate #2 normative ordering, and signed locally using the offline Ed25519 private key (`neko-update-prod-1`) to produce canonical `release-v2.json`. After Gate #2 clearance, the operator pushes the Git tag (`v5.1.0a3`) and stages an unpublished draft release using `scripts/stage_draft_release.py`. Before mutation, staging re-proves the strict Core ZIP, binds its canonical installed identity to the signed manifest, and read-only verifies via the GitHub Git-data API that the canonical remote tag peels to the exact approved target commit. Release creation preserves `--verify-tag --target <exact-target> --draft --prerelease=false`, so the tool cannot create a missing remote tag; upload remains `--clobber=false`. Staging tooling never final-publishes, signs manifests, rebuilds binaries, creates tags, or moves tags.
  - **Phase 2 (Remote Publication Authority Gate)**: Final publication authority belongs exclusively to GitHub Actions (`.github/workflows/release.yml`). Direct local workstation publication is strictly prohibited. Publication is triggered with `gh workflow run release.yml --ref v5.1.0a3 -f publish_release=true -f release_id=<NUMERIC_ID> -f release_tag=v5.1.0a3 -f expected_target=<40_CHAR_SHA>`. `--ref` selects the reviewed workflow definition from the approved release tag, while `expected_target` remains the exact approved checkout and authority commit. The workflow downloads staged assets by numeric `asset_id` as raw binary streams, validates cryptographic signatures and first-release invariants against in-repo `PRODUCTION_RELEASE_PUBLIC_KEYS['neko-update-prod-1']` via `scripts/verify_github_release_assets.py`, re-checks draft state and asset ID bindings to eliminate TOCTOU races, publishes via `PATCH /releases/:release_id` (`draft=false`), and confirms public availability on `/releases/latest`.
- **Gate #2 Normative Ordering**: Mandatory 7-step sequence: freeze exact candidate bytes -> Launcher packaged smoke + Updater self-check directly on frozen bytes -> fresh post-smoke recomputation of sizes, SHA-256 digests, and Core installed identity -> construct and sign canonical `release-v2.json` locally with offline `neko-update-prod-1` private key -> local cryptographic and descriptor binding verification -> repository safety and clean worktree checks -> formal independent review clearance (C0/I0).
- **Byte Mutation Invalidation Rule**: Any byte mutation, file touch, recompilation, or test re-run after fresh measurement invalidates Gate #2. If any candidate file is touched or re-tested after measurement, Gate #2 is void and requires restaging, remeasuring, re-signing, or creating a new candidate as applicable.
- **Supersession of Obsolete Single-Phase CI**: Old single-phase CI compilation and local filesystem workflow path inputs are obsolete and superseded. PyInstaller builds are non-byte-reproducible and hosted runners cannot access local operator storage (`E:\...`). The `build-installer` CI tag job is diagnostic-only; its compiled binaries possess zero release authority.
- **Four Trusted Client Update Assets**: Each stable release contains exactly one each of `release-v2.json` (signed envelope authority), `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip`. Local staging directories must contain strictly these four files. Permitted human-facing extras on GitHub Releases (such as checksum files or installers) are ignored by client update logic. Closed 3-component set `{launcher, updater, core}`.
- **Preservation of Unrelated Services**: Historical Supabase private Storage / Admin grant / capability distribution path is **SUPERSEDED BY OWNER GITHUB-ONLY ARCHITECTURE DECISION, NOT PASS**. Unrelated Supabase/Admin/account/recovery/proxy services remain untouched with no update fallback.
- **Engineering and Implementation Status**:
  - Current implementation plan: [`docs/superpowers/plans/2026-09-09-software-update-two-phase-staged-draft-implementation.md`](../superpowers/plans/2026-09-09-software-update-two-phase-staged-draft-implementation.md).
  - Two-phase implementation Tasks 1–6 are COMPLETE with final engineering review PASS (Sol architecture review at HEAD b882ea5: SPEC_COMPLIANCE PASS, ARCHITECTURE_QUALITY PASS, Critical 0, Important 0, FINAL_ENGINEERING_STATUS PASS, TASK6_STATUS COMPLETE).
  - Controller evidence: focused release suite 73 passed / 0 failed; full canonical Launcher with admitted Core fixture 1719 passed / 35 skipped / 0 failed; Ruff PASS; repository safety PASS; all 3 workflow YAML parse PASS; `git diff --check` PASS; worktree clean.
  - Historical pre-release next action (Superseded): Stated "Next phase is formal Gate #2 candidate qualification under normative order." Both Gate #2 and Gate #3 are now formally PASSED and release v5.1.0a3 is published (see Section "Current Production Release Status — v5.1.0a3" above); no qualification remains pending.
  - Historical implementation evidence: Earlier 2026-09-08 plan Tasks 1–7 achieved canonical Launcher suite passing 1673 / skipped 35 / failed 0. Stale operative reviews from that cycle are superseded by the two-phase correction implementation.
- **Release Gates & Explicit Boundary (Historical Pre-Release Checkpoint — SUPERSEDED)**: Gate #2 and Gate #3 are **PASSED** (see Section "Current Production Release Status — v5.1.0a3" above). Historically prior to publication, this section noted: Gate #2 remained NOT PASSED, Gate #3 remained NOT PASSED, and no production signing/push/publication had yet occurred. Those steps are now fully completed, verified, and closed.


---

## 2. Evidence-aligned dashboard semantics

The four-node visual flow from the mockup is preserved, but it is a **service/status path**, not a fabricated physical traceroute:

```text
เครื่องของคุณ
  -> NEKO Proxy Engine (local Core/Redirector/SOCKS/V2Ray stack)
  -> Tokyo Proxy (remote selected/canonical proxy role)
  -> PSO2 JP (semantic game network destination)
```

Important corrections from the earlier draft:

- There is no verified separate **Bangkok remote proxy** hop in the proven data path.
- Raw local/proxy/game IP fields are not part of the redesign display contract.
- Current headless telemetry does not provide ping/RTT or per-hop latency.
- Legacy Netch contains `Server.PingAsync()` for selected proxy RTT, but this is a dormant capability, not current production telemetry authority.
- Numeric latency must remain `—` until a separately reviewed and tested local measurement path exists.

---

## 3. Non-regression contracts

The redesign may change presentation, but it must preserve these product/security contracts:

- External Core topology is intentional; do not embed ProxyCore back into the Launcher one-file EXE.
- One active Launcher session per user; latest claim wins.
- Auth/session/entitlement failures remain fail-closed.
- Deep client telemetry remains local-only; do not upload PID/process lists/DNS/flow details/raw Core logs/proxy credentials.
- Close, logout, reconnect, and reopen recovery must never kill `pso2.exe`.
- Customer-visible telemetry must be truthful. Unknown measurements use `—` / unavailable, never fake `0 ms` or mockup values.
- Raw proxy/server hostname, IP, port, credentials, and destination history are not customer-dashboard fields.
- Source changes that produce a new Launcher build must follow the current versioning/release rule and must be tested using the new artifact.
- Artifact SHA-256 mismatch is a hard stop.
- Authority-vault updates remain a separate Owner-gated release operation after exact-artifact evidence and required smoke.

---

## 4. Phase 1 engineering status (2026-08-29)

Phase 1 is **ENGINEERING PASS (uncommitted) / PHASE 2 NEXT**. Source/test/version changes exist on `feature/dashboard-redesign @ 0fc836d` and have NOT been committed. This is not a release/artifact pass — no build, no live proof, no authority update. Plan version remains v1.2; the Phase 1 contract is unchanged.

Allowed Phase 1 source scope (unchanged from locked plan):

```text
launcher/src/neko_launcher/domain/models.py
launcher/src/neko_launcher/ui/theme.py
launcher/tests/test_network_hop_model.py
launcher/tests/ui/test_palette_tokens.py
```

Explicitly out of scope for Phase 1 (unchanged):

```text
launcher/src/neko_launcher/domain/telemetry.py
NekoProxyCore/*
installer/*
Admin/*
authority/*
```

### 4.1 Implemented Phase 1 contract (matches plan §4.2 / §4.4)

- `NetworkHopRole` (str + Enum): `LOCAL_DEVICE`, `LOCAL_PROXY_ENGINE`, `REMOTE_PROXY`, `GAME_NETWORK`.
- `HopConnectionState` (str + Enum): `SUCCESS`, `CONNECTING`, `UNAVAILABLE`.
- `NetworkHop` and `NetworkPath` are frozen/immutable dataclasses.
- `NetworkPath.proxy_rtt_ms` accepts `None`, `0`, and positive integers; rejects negative with `ValueError`.
- No `ip` / `hostname` / `port` / `bangkok` / `per_hop_latency_ms` field in either dataclass.
- 8 semantic `PinkPalette` node tokens: `node_local`, `node_local_surface`, `node_engine`, `node_engine_surface`, `node_remote`, `node_remote_surface`, `node_game`, `node_game_surface` (strict `#RRGGBB`, semantic role names).

### 4.2 TDD evidence (corrective pass)

- First RED attempt was REJECTED because pytest stopped during collection with an `ImportError` (collection / test-framework error, not a valid failing-test signal).
- Test import shape repaired: tests now import only the stable module and resolve Phase 1 symbols via `getattr` + `pytest.fail(...)` so a missing symbol becomes an assertion failure, not a collection error. All plan §1.3 behavioural coverage preserved.
- VALID RED after temporary baseline restoration: 47 failed, 8 passed, 0 collection errors.
- GREEN after reapplying minimal production implementation: 55 passed.

### 4.3 Phase 2 first action (next gate)

Phase 2 owns reusable presentation components. Before any Phase 2 implementation, perform a **read-only audit** of existing UI / component conventions and exact file paths, then create RED tests first. Phase 2 remains pure presentation with no network IO and no telemetry probing.

Before changing source, re-verify current version. After the Phase 1 bump the current Launcher source version is `5.0.0a11`; the next source-build target under the existing versioning rule would be `5.0.0a12` once Phase 2 source changes are ready.

---

## 5. Phase 1 engineering evidence (2026-08-29)

```text
Python                       = 3.11.15
Launcher source version      = 5.0.0a11 (5.0.0a10 -> 5.0.0a11, uncommitted)
Branch                       = feature/dashboard-redesign
HEAD                         = 0fc836d
P1 suites                    = 55 passed
Focused baseline             = 13 passed, 1 skipped (display-dependent dashboard test)
RUFF                         = All checks passed
COMPILEALL                   = clean
Canonical non-integration    = 674 passed, 1 skipped, 5 deselected, 0 failed
git diff --check             = PASS (benign LF/CRLF note on uv.lock only)
```

**Canonical non-integration test-run method on this host:** run with `env -u TCL_LIBRARY -u TK_LIBRARY .venv/Scripts/python.exe -m pytest -q -m "not integration"` (process-local env removal only). The host's persistent user/system environment is not modified. The contamination source is an external `Khai-Hub/_internal/_tcl_data` toolchain install that pins Tcl 8.6.15 against the system's Tcl 8.6.12, polluting the Tk init path. **Product source was NOT changed to work around this.** This run method must be carried forward into Phase 2-6 runs on the same machine.

**Phase 1 TDD order followed:**

1. Read existing patterns in `models.py` and `theme.py` (no edits).
2. Created the two new test files first; tests failed at collection because Phase 1 symbols were missing — that RED was REJECTED as a collection error.
3. Repaired test import shape (module import + missing-symbol `pytest.fail`).
4. Temporarily restored production/version files to baseline (no git reset/checkout/stash/clean) to capture valid RED: 47 failed, 8 passed, 0 collection errors.
5. Reapplied the minimal Phase 1 production contract exactly as plan §4.2 / §4.4 defines.
6. Reapplied the version bump `5.0.0a10 -> 5.0.0a11` across all three metadata files.
7. Re-ran P1 suites → 55 passed (GREEN).

Build/live proof/authority = NOT performed in this pass; Phase 6 owns packaged integration smoke. `COMMIT = NOT_CREATED`, `PUSH = NOT_REQUESTED`.

---

## 6. Active Launcher documentation (`docs/current/`)

| Document | Role / Content | Authority level |
| :--- | :--- | :--- |
| **[`README.md`](README.md)** | Current Launcher component status and start-here orientation | `CURRENT_STATUS` |
| **[`dashboard-redesign-completion.md`](dashboard-redesign-completion.md)** | Dashboard redesign completion, validation evidence, and merge readiness | `FEATURE_COMPLETION_RECORD` |
| **[`dashboard-redesign-plan.md`](dashboard-redesign-plan.md)** | Evidence-aligned six-phase dashboard redesign plan v1.2 | `HISTORICAL_PLAN / COMPLETED` |
| **[`t10-commercial-ui-ux-design-freeze.md`](t10-commercial-ui-ux-design-freeze.md)** | Previous commercial UI/UX architecture and non-regression constraints | `CURRENT_CONTRACT / HISTORICAL_FREEZE` |
| **[`launcher-architecture.md`](launcher-architecture.md)** | Desktop application layered architecture, IPC, and controllers | `CURRENT_CONTRACT` |
| **[`neko-auth-lite.md`](neko-auth-lite.md)** | NEKO-AUTH-LITE authentication, challenge-response, and permit flow | `CURRENT_CONTRACT` |
| **[`final-windows-e2e-harness.md`](final-windows-e2e-harness.md)** | Windows E2E integration harness and binary admission gates | `CURRENT_CONTRACT` |
| **[`phase-2-5-distinct-auth-session-future-permit-proof.md`](phase-2-5-distinct-auth-session-future-permit-proof.md)** | Closed security proof/evidence | `CURRENT_RELEASE_EVIDENCE` |
| **[`build-windows-executable.md`](build-windows-executable.md)** | PyInstaller packaging and secret-hygiene build instructions | `CURRENT_OPERATIONAL` |
| **[`debug-console.md`](debug-console.md)** | Windows debug console, runtime logging, and IPC troubleshooting | `CURRENT_OPERATIONAL` |
| **[`repository-layout.md`](repository-layout.md)** | File organization and component dependency layout | `CURRENT_OPERATIONAL` |
| **[`runtime-distribution.md`](runtime-distribution.md)** | External Core runtime distribution policy (Two-Phase Staged-Draft GitHub Releases architecture, public Core accepted) | `CURRENT_OPERATIONAL` |
| **[`../superpowers/specs/2026-09-09-software-update-two-phase-staged-draft-design.md`](../superpowers/specs/2026-09-09-software-update-two-phase-staged-draft-design.md)** | Two-Phase Staged-Draft publication architecture design specification | `CURRENT_SPEC` |
| **[`../superpowers/plans/2026-09-09-software-update-two-phase-staged-draft-implementation.md`](../superpowers/plans/2026-09-09-software-update-two-phase-staged-draft-implementation.md)** | Two-Phase Staged-Draft publication architecture implementation plan | `CURRENT_PLAN` |
| **[`../superpowers/specs/2026-09-08-software-update-github-releases-design.md`](../superpowers/specs/2026-09-08-software-update-github-releases-design.md)** | Software Update GitHub Releases design specification (authority for discovery/trust/rollback; publication handoff superseded by 2026-09-09 spec) | `HISTORICAL_SPEC / PARTIALLY_SUPERSEDED` |
| **[`../superpowers/plans/2026-09-08-software-update-github-releases-implementation.md`](../superpowers/plans/2026-09-08-software-update-github-releases-implementation.md)** | Historical Software Update GitHub Releases implementation plan (superseded by 2026-09-09 plan) | `HISTORICAL_PLAN / SUPERSEDED` |
| **[`closed-beta-runbook.md`](closed-beta-runbook.md)** | Closed-Beta distribution and accepted artifact evidence | `CURRENT_OPERATIONAL / RELEASE_HISTORY` |

---

## 7. Cross-repository orientation

Discover repository folders by name, then verify `.git`, branch, HEAD, remote, and expected project markers. Do not hard-code workstation drive letters into permanent instructions.

| Component | Folder name | Current verified branch / HEAD |
|---|---|---|
| Launcher | `Neko-Family-Proxy` | `feature/dashboard-redesign` @ `0fc836d`; `main` @ `bde8389` |
| Core | `NekoProxyCore` | `feature/neko-auth-lite-v1-core` @ `33f97ae` |
| Admin | `Neko-Family-Proxy-admin-tool` | `main` @ `f240d44` |
| Project manager | `Project manager` | read `CURRENT_STATUS.md` first |

---

## 8. Closed-Beta / production history that remains valid

Infrastructure/security work through Phase 2.5 was closed and verified before this redesign stream. T1-T9 production operations, NEKO-AUTH-LITE, telemetry privacy, Core lifecycle, Closed-Beta installer work, reconnect/reopen proof, and accepted Beta artifact records remain preserved in detailed runbooks/history.

```text
accepted beta artifact/history != current development branch
```

New distribution authority can only be created after source -> tests -> build -> exact-artifact smoke/live proof -> authority sequence.

---

## 9. Historical archive

Historical proposals, superseded prompts, completed milestone evidence, blocked investigations, and scratch notes are preserved under `docs/archive/`. Do not rewrite historical failures into PASS and do not use archived artifact identifiers as current authority without re-verification.
