# Launcher S0 Consumer Connector Handoff

**Work item:** `Launcher-S0-Consumer-01`
**Delivery status:** `DESIGN READY / IMPLEMENTATION PARTIAL`
**Repository:** `D:\Neko-Family-Proxy`
**Branch:** `main`
**Original delivery commit:** `791be353ebaed007147dc634055edf12ccec3b4c`
**Connector correction commit:** `2a305e476b1a863c1e87c34ebdfadf1cffa3b88b`
**Typed-boundary follow-up commit:** `f42f358`
**Working tree:** Clean after the Connector correction commit
**Contract proposal revision:** `launcher-s0-proposal-01`
**Release authorization:** Not granted

> Sanitized handoff. No token, permit, credential, private key, production endpoint, customer identifier, or raw runtime configuration is included.

## 1. Delivered artifacts

### Task A — Launcher-owned S0 proposal

- `docs/LAUNCHER_S0_CONTRACT_PROPOSAL.md`

The proposal marks every value as `PROPOSED`, separates Launcher ownership from Core/Backend/Security decisions, and supplies:

- exact v2 challenge/start/status/stop request and response shapes;
- strict UTF-8, 4-byte big-endian length framing, partial I/O, and rejection policies;
- exact proposed payload, response, correlation, reference, and opaque permit bounds;
- proposed operation deadlines;
- strict case, unknown-field, duplicate-field, and typed-value rules;
- exact Launcher lifecycle and cleanup state machine;
- retry and ambiguous-outcome rules requiring a new challenge and permit;
- opaque `profile-N` / `server-N` reference policy;
- allow-listed typed error-to-Thai-UI mapping;
- proposed Core executable/RID/manifest identity requirements;
- Launcher merge gate, production wiring gate, and cross-repository exit gate.

No proposal value is represented as frozen or production-approved.

### Task B — Contract-independent code and tests

Changed files:

- `launcher/src/neko_launcher/application/authorized_core.py`
- `launcher/src/neko_launcher/main.py`
- `launcher/tests/test_authorized_core.py`
- `launcher/tests/test_main.py`

Implemented or verified:

1. typed `LaunchAccessContext` local fail-fast boundary;
2. mandatory fresh online heartbeat precondition before Core host spawn;
3. same-target recheck after heartbeat and before host spawn;
4. typed `OpaqueStartCommand` accepting only credential-free `profile-[0-9]{1,6}` and `server-[0-9]{1,6}` references;
5. invalid references fail before target, heartbeat, host, challenge, permit, or start side effects;
6. heartbeat false/exception records no new success timestamp; an earlier successful timestamp remains historical evidence only and is never accepted in place of the required fresh probe;
7. cancellation during heartbeat blocks host and permit side effects;
8. target exit after heartbeat blocks host spawn;
9. duplicate start remains single-flight;
10. startup error persistence now writes only `StartupFailed` rather than a traceback;
11. startup UI no longer includes arbitrary `str(exc)`;
12. production composition remains `AuthorizationPendingProxyGateway`.
13. partial host-start failures enter owned-process cleanup;
14. cleanup adapter exceptions cannot replace the sanitized public failure;
15. no alternate `_start_admitted` admission entry remains.
16. adapter-originated typed exceptions are reduced to an allow-listed public message and arbitrary adapter detail is not republished.
17. regression coverage includes heartbeat, process, channel and permit adapter exceptions plus an unstable exception renderer.
18. public errors derive from `AuthorizedCoreErrorCode`; adapter messages/codes are reduced by call-site-owned mappings and cannot impersonate unrelated public conditions.

## 2. TDD and executable evidence

### Observed RED — fresh heartbeat gate

```text
TypeError: AuthorizedCoreOrchestrator.__init__() got an unexpected keyword argument 'launch_precondition'
1 failed
```

### Observed RED — concrete heartbeat precondition

```text
ImportError: cannot import name 'OnlineHeartbeatLaunchPrecondition'
```

### Observed RED — local access context

```text
ImportError: cannot import name 'LaunchAccessContext'
exit code 4
```

### Observed RED — opaque references

```text
ImportError: cannot import name 'OpaqueStartCommand'
exit code 4
```

### Observed RED — sanitized startup reporter

```text
AttributeError: module 'neko_launcher.main' has no attribute '_show_startup_error_message'
1 failed
```

### GREEN focused evidence

```text
5 passed  # invalid opaque references
21 passed # authorized_core file before additional characterization tests
1 passed  # startup secrecy focused test
3 passed  # test_main.py
```

Additional heartbeat cancellation/target-exit tests passed immediately against existing scaffold behavior. They are characterization evidence, not claimed as RED-first implementation evidence.

### Final non-integration unit gate

Command:

```text
uv run --frozen pytest -q -m "not integration"
```

Result:

```text
99 passed, 2 deselected in 0.58s
exit code 0
```

### Ruff

Command:

```text
uv run --frozen ruff check src tests
```

Result:

```text
All checks passed!
exit code 0
```

### Diff hygiene

```text
git diff --check
exit code 0
```

### Focused production-source probes

Observed successful probes:

```text
AD_HOC_PASS fresh heartbeat failure blocked all Core/permit side effects
exit_code=0
```

```text
AD_HOC_PASS typed context failed closed before all activation side effects
temporary_script_removed=true
probe_exit_code=0
```

These are focused evidence only, not full-suite or E2E evidence.

## 3. Proposed contract decisions by owner

### Launcher-owned proposal

- protocol consumer schema and strict parsing;
- 8192-byte JSON payload/response ceiling;
- 32-character lowercase hexadecimal correlation IDs;
- strict `profile-N` / `server-N` references;
- bounded local operation deadlines;
- state machine, retry, ambiguity, and cleanup behavior;
- allow-listed Thai UI mappings;
- artifact-manifest consumer requirements.

All remain `PROPOSED` until required approval.

### Core decisions required

- approve/modify schema, framing, statuses, error taxonomy, and bounds;
- final named-pipe and mutex identities;
- challenge representation and lifecycle;
- final executable basename, RID, complete dependency set, manifest, and fixed arguments;
- current-user-only pipe implementation and typed readiness semantics.

### Backend decisions required

- authenticated permit endpoint/RPC and exact request/response envelope;
- server-side account/entitlement/installation/session/heartbeat checks;
- HTTP body limits, typed errors, rate limits, signer failure, and retry semantics;
- one-permit-per-attempt behavior.

### Security decisions required

- JWT header, claims, issuer, audience, product, scope, TTL, and skew;
- key custody, distribution, rotation, retirement, and revocation;
- canonical configuration encoding/hash and shared fixtures;
- continuous authorization, grace period, and revocation SLA;
- short-lived non-reusable proxy-access architecture;
- code-signing and release identity policy.

## 4. Current boundary classification

| Boundary | Status | Evidence / blocker |
|---|---|---|
| Launcher S0 consumer proposal | `DESIGN READY` | Complete proposal submitted for review; not approved/frozen |
| Local access context | `PASS` unit scaffold | Invalid auth/entitlement/session/install fails before target and side effects |
| Fresh heartbeat gate | `PASS` unit scaffold | False/exception/cancellation blocks host/permit/start |
| Opaque references | `PASS` unit scaffold | Raw endpoint/credential-like values rejected before activation |
| Target loss after heartbeat | `PASS` unit scaffold | No host spawn |
| Startup durable traceback/UI leakage | `PASS` focused | Typed log only; arbitrary exception detail absent |
| Full secrecy sentinel matrix | `PARTIAL` | Startup and orchestration covered; telemetry/crash/minidump/package gates remain |
| Production heartbeat/permit adapter | `BLOCKED` | Backend/Security contract pending |
| Protocol v2 production channel | `BLOCKED` | Core approval and pipe identity pending |
| Core process/artifact adapter | `BLOCKED` | Core manifest/artifact contract pending |
| Production composition | `BLOCKED` | Intentionally remains unavailable gateway |
| Real Launcher → Core E2E | `BLOCKED` | Frozen contract and ship artifacts unavailable |
| Production release | `BLOCKED` | Cross-repository exit gate not satisfied |

## 5. Repository and hygiene state

Original delivery paths were committed in `791be353ebaed007147dc634055edf12ccec3b4c`. The Connector correction changed and committed:

```text
launcher/src/neko_launcher/application/authorized_core.py
launcher/tests/test_authorized_core.py
```

- original delivery and Connector correction are committed;
- no push performed;
- no production wiring enabled;
- no offline/allow-all/local-signing fallback added;
- no permit decoding or persistence added;
- no raw proxy settings added;
- `uv run` lock-file churn was restored and is not part of the handoff.

## 6. Launcher merge gate

Launcher contract-independent changes may merge only after Connector/Core/Security review confirms:

1. proposal is complete enough for Core review without guessing Launcher-owned schema, framing, timeout, or lifecycle behavior;
2. proposed values remain labeled as proposed rather than frozen;
3. invalid local context, heartbeat, target, and reference paths have zero activation side effects;
4. production composition remains fail closed;
5. non-integration unit and Ruff gates pass from the submitted working tree;
6. sanitized documents contain no forbidden material.

## 7. Cross-repository exit gate

Production wiring and release remain blocked until:

1. all teams use one approved contract revision/hash;
2. shared canonical/config/signature/error fixtures are published;
3. Backend authority and Core verification/host implementations pass their negative matrices;
4. approved Core artifact manifest is available and verified by Launcher;
5. ship-path Launcher wiring passes no-target/no-permit/replay/expiry/mismatch tests;
6. valid target + valid online permit produces exactly one typed `Running` runtime;
7. cleanup, sentinel leakage, package extraction, and direct-proxy bypass gates pass;
8. QA and Security sign off.

## 8. Requested Connector decision

```text
Team: Connector
Reviewed proposal revision: launcher-s0-proposal-01
Decision: APPROVED / APPROVED WITH CHANGES / BLOCKED
Requested changes:
Launcher-owned proposal gaps:
Required Core decisions:
Required Backend decisions:
Required Security decisions:
Repository merge gate decision:
Cross-repository exit gate decision:
```

This handoff must not be interpreted as production authorization, gameplay traffic, proxy-path, continuous authorization, or E2E PASS.
