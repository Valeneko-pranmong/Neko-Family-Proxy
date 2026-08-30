# NEKO FAMILY PROXY — Launcher Component Status & Start Here

```text
DOCUMENT:                       docs/current/README.md
STATUS:                         ACTIVE DEVELOPMENT
PRODUCT_BASELINE:               CLOSED BETA ACCEPTED
CURRENT_WORKSTREAM:             DASHBOARD REDESIGN
ACTIVE_DEV_BRANCH:              feature/dashboard-redesign
ACTIVE_DEV_HEAD:                0fc836d15399ddfd5dd9abc4661b0ba84d072571
MAIN_HEAD:                      bde8389 (origin/main)
BETA_HEAD:                      c9ab125 (origin/beta; accepted Closed Beta baseline)
CORE_AUTHORITY_BRANCH:          feature/neko-auth-lite-v1-core
CORE_HEAD:                      33f97ae0110075089f39b1e123890f931417d907
PHASE_2_5_TECHNICAL_GATE:       CLOSED / PASS
| DASHBOARD_PLAN:                 v1.2 / PHASE 1 ENGINEERING PASS (uncommitted) / PHASE 2 NEXT |
| NEXT_ACTION:                    PHASE 2 READ-ONLY AUDIT OF EXISTING UI/COMPONENT CONVENTIONS BEFORE ANY PHASE 2 IMPLEMENTATION |
LAST_VERIFIED:                  2026-08-29 +07:00 (Asia/Bangkok)
```

> **Current-state rule:** verify Git branch, HEAD, status, and this directory before assigning work. The active feature branch is newer development state than older production/Closed-Beta status blocks. Frozen release evidence remains historical authority for the exact accepted artifacts only.

---

## 1. What is the Launcher doing now?

The Launcher is in **post-Closed-Beta product development** on:

```text
feature/dashboard-redesign @ 0fc836d
```

The current implementation authority is [`dashboard-redesign-plan.md`](dashboard-redesign-plan.md) **v1.2**, reconciled against NekoProxyCore, legacy Netch runtime evidence, current telemetry, and the Owner mockup.

Six phases remain:

1. Foundation — semantic network models and theme tokens
2. Reusable presentation components
3. Dashboard layout restructure / window sizing
4. Connection diagram, runtime mapping, and latency capability gate
5. Statistics and visual polish
6. Integration, packaged build, and smoke verification

`main` remains at `bde8389`. `beta` remains at accepted Closed Beta baseline `c9ab125`. Dashboard work is not a new release identity until implementation, tests, packaged proof, and release gates complete.

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
| **[`dashboard-redesign-plan.md`](dashboard-redesign-plan.md)** | Evidence-aligned six-phase dashboard redesign plan v1.2 | `CURRENT_PLAN` |
| **[`t10-commercial-ui-ux-design-freeze.md`](t10-commercial-ui-ux-design-freeze.md)** | Previous commercial UI/UX architecture and non-regression constraints | `CURRENT_CONTRACT / HISTORICAL_FREEZE` |
| **[`launcher-architecture.md`](launcher-architecture.md)** | Desktop application layered architecture, IPC, and controllers | `CURRENT_CONTRACT` |
| **[`neko-auth-lite.md`](neko-auth-lite.md)** | NEKO-AUTH-LITE authentication, challenge-response, and permit flow | `CURRENT_CONTRACT` |
| **[`final-windows-e2e-harness.md`](final-windows-e2e-harness.md)** | Windows E2E integration harness and binary admission gates | `CURRENT_CONTRACT` |
| **[`phase-2-5-distinct-auth-session-future-permit-proof.md`](phase-2-5-distinct-auth-session-future-permit-proof.md)** | Closed security proof/evidence | `CURRENT_RELEASE_EVIDENCE` |
| **[`build-windows-executable.md`](build-windows-executable.md)** | PyInstaller packaging and secret-hygiene build instructions | `CURRENT_OPERATIONAL` |
| **[`debug-console.md`](debug-console.md)** | Windows debug console, runtime logging, and IPC troubleshooting | `CURRENT_OPERATIONAL` |
| **[`repository-layout.md`](repository-layout.md)** | File organization and component dependency layout | `CURRENT_OPERATIONAL` |
| **[`runtime-distribution.md`](runtime-distribution.md)** | External Core runtime distribution policy | `CURRENT_OPERATIONAL` |
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
