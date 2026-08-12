# Final Windows A → B → C → A E2E harness

> **Status: PREPARATION READY — FINAL EXECUTION BLOCKED.** This runbook prepares
> deterministic evidence collection only. It does not authorize a hosted permit,
> a production Core START, or the final A → B → C → A sequence.

## Required open gates

The final run must not begin until all three gates are true:

1. historical PSO2 ProcessMode source has been recovered and provisioned through
   the approved Core-owned path;
2. the Core runtime catalog returns exactly one valid candidate, and validation
   freezes that exact candidate;
3. the hosted Core `RUNNING` KP gate has passed for the exact artifacts below.

The preparation CLI deliberately has no hosted Backend, named-pipe, process-spawn,
or authorized Core START adapter. It can only validate the offline contract and
write a secret-safe manifest:

```powershell
uv run --frozen python -m neko_launcher.e2e.final_windows_harness prepare `
  --output <temporary-evidence-root>\preparation-manifest.json
```

## Execution topology

Use **three separate Windows VMs**. Each VM has one dedicated Windows user, one
Launcher, one credential vault, isolated `%LOCALAPPDATA%`, isolated debug logs,
an isolated temporary runtime root, and an exact-owned-Core PID ledger. Run at
most one production Core host in each Windows user/session.

Production identities remain unchanged:

- Launcher mutex: `Local\NekoFamilyProxyLauncher`
- Core pipe: `NekoProxyCoreControl`

Do not add instance suffixes, bypass the mutex, weaken Core singleton handling,
or emulate installations with only an in-memory variable. The production
installation secret must be generated and persisted in that VM user's Windows
credential vault. A's second login must reuse A's same persisted installation
identity.

A carefully sequenced single-context model may be used only if it provides the
same demonstrable vault, local-state, log, temp, and process isolation and never
runs competing Core hosts. The three-VM topology is the chosen default.

## Final transition contract

Execute only this explicit user-driven sequence:

1. A claims; A heartbeat succeeds.
2. B claims; B heartbeat succeeds; A heartbeat fails; A cannot obtain a **new**
   permit.
3. C claims; C heartbeat succeeds; B heartbeat fails; B cannot obtain a **new**
   permit.
4. A claims again with A's remembered installation; A heartbeat succeeds; C
   heartbeat fails; C cannot obtain a **new** permit.

A, B, and C may remain remembered installations. No assertion may state that a
machine owns the account permanently, cannot return, requires transfer, or is
permanently locked. The newest successful Launcher session is the only authority.

## Safe backend evidence

Create one random salt per final run and keep it only in the temporary evidence
root. Convert raw UUIDs immediately into salted opaque references such as
`launcher_session_<16 hex>` and `installation_<16 hex>`. Record only:

- instance label;
- salted Launcher-session reference;
- salted installation reference;
- authority state (`AUTHORITATIVE` or `INACTIVE`);
- heartbeat accepted/rejected;
- future permit eligibility accepted/rejected;
- authority replacement timestamp and old-Launcher detection timestamp;
- exact-owned Core lifecycle timestamps and PIDs;
- typed failure classification;
- sanitized Launcher stage trace.

Never record access/refresh tokens, Authorization headers, JWTs, service-role
material, passwords, signing keys, raw permits, or raw UUIDs in final evidence.

An already-issued permit is a separate, short-lived capability with a maximum
30-second lifetime. Session replacement blocks **future** permit issuance; it
does not require retroactive Core revocation. Record only its issuance/expiry
window, never the permit value.

## Authority-loss and ownership measurements

For each displaced Launcher that owns Core, record UTC timestamps:

- `AUTHORITY_REPLACED_AT`
- `OLD_LAUNCHER_DETECTED_AT`
- `SHUTDOWN_REQUESTED_AT`
- `CORE_EXITED_AT`

Calculate:

- replacement → authority invalidation;
- authority invalidation → exact-owned-Core exit;
- shutdown request → exact-owned-Core exit.

A graceful PASS requires all of the following:

- Launcher-owned Core PID is positive and retained from the child handle;
- `GetNamedPipeServerProcessId` equals that exact PID;
- shutdown request and observed exit bind to that exact PID;
- no wildcard or image-name `taskkill` is used;
- unrelated Core PIDs are unchanged;
- no owned Core remains orphaned;
- Core singleton is released;
- no emergency exact-child kill is counted as graceful PASS.

The emergency fallback may be reported separately as containment evidence, but
it is not graceful shutdown evidence.

## Required successful stage trace

Capture these stages in order, allowing repeated observational entries but no
missing or reordered required entry:

1. `GAME_PROCESS_DETECTED`
2. `PROXY_START_REQUESTED`
3. `COMMAND_VALIDATE`
4. `ACCESS_CONTEXT_VALIDATE`
5. `TARGET_WAIT`
6. `HOST_START`
7. `CONTROL_CHANNEL_WAIT`
8. `RUNTIME_CONFIG_CATALOG`
9. `RUNTIME_CONFIG_VALIDATE`
10. `TARGET_RECHECK`
11. `CHALLENGE_REQUEST`
12. `TARGET_BIND`
13. `PERMIT_REQUEST`
14. `AUTHORIZED_START`
15. `RUNNING_VERIFY`
16. final `CoreStatus.RUNNING`

## Runtime configuration gate

- `EMPTY` → `RUNTIME_CONFIGURATION_UNAVAILABLE` → zero permit calls.
- `UNIQUE` → validate exact candidate → freeze exact validated pair → continue.
- `MULTIPLE` → `RUNTIME_CONFIGURATION_SELECTION_REQUIRED` → zero permit calls.

Never choose first, any, lowest, last, cached, or random candidate.

## Synthetic data plan

Use one disposable synthetic account unless a later approved architecture
requires otherwise. Create it through public Auth, provision one product/license
entitlement through the supported Admin path, and let the three real isolated
Launcher contexts create installations A/B/C through `claim_session`. Do not
insert identity/session rows manually. Do not create hosted state during this
preparation phase.

## Cleanup order

Install a bounded cleanup path before creating final hosted state. Scope every
operation to retained synthetic IDs:

1. gracefully shut down exact owned Core processes;
2. release known Launcher sessions;
3. clear each instance's local Auth state;
4. delete synthetic recovery/session records where applicable;
5. delete synthetic Launcher sessions;
6. delete synthetic installations;
7. revoke the synthetic entitlement through the supported path;
8. delete the disposable Auth user so owned rows cascade as designed;
9. remove temporary instance state and exact PID ledgers;
10. remove sanitized test logs and the per-run salt.

Never run broad table deletes, truncate tables, clean real users, wildcard-kill
processes, or delete shared runtime directories.

## Failure matrix

Keep these classifications distinct from generic `RUNNING_NOT_REACHED`:

| Condition | Launcher classification | Domain |
| --- | --- | --- |
| old A after B claim | `SESSION_INACTIVE` | authority |
| old B after C claim | `SESSION_INACTIVE` | authority |
| old C after A reclaim | `SESSION_INACTIVE` | authority |
| `SessionInactive` | `SESSION_INACTIVE` | authority |
| `HeartbeatStale` | `HEARTBEAT_STALE` | authority |
| `EntitlementInactive` | `ENTITLEMENT_INACTIVE` | authority |
| `AuthorizationInvalid` | `AUTHORIZATION_INVALID` | authorization |
| `ConfigurationMismatch` | `CONFIGURATION_MISMATCH` | configuration |
| runtime config EMPTY | `RUNTIME_CONFIGURATION_UNAVAILABLE` | configuration |
| runtime config MULTIPLE | `RUNTIME_CONFIGURATION_SELECTION_REQUIRED` | configuration |

## Artifact identity

Before final mutation, capture and then revalidate bytes immediately before the
run:

- full Launcher commit SHA;
- Launcher EXE SHA-256;
- full Core commit SHA;
- Core artifact-manifest SHA-256;
- Core EXE SHA-256;
- SHA-256 for exactly these five critical DLLs:
  - `NekoProxyCore.dll`
  - `NekoProxyCore.Core.dll`
  - `NekoProxyCore.Legacy.dll`
  - `NekoProxyCore.Windows.dll`
  - `Netch.dll`

A path or directory name is never artifact identity. Abort if any captured byte
hash changes.

The concrete provenance boundary is production-composed from
`WindowsCoreProcessAdapter` and `NamedPipeCoreControlChannel`. Every
manifest-controlled artifact file is canonicalized, guarded against write/delete
sharing, and hashed under its guard. The admitted executable is spawned from its
exact canonical path and then bound through the retained child handle to
`QueryFullProcessImageNameW`, Windows volume/file identity, and post-spawn hashes
of the guarded artifact inventory before any claim driver operation can continue.
The guards remain retained for the exact child lifetime and are released only
when that child exits or exact-handle cleanup completes; any unavailable or
mismatched observation fails closed and cleans up only the exact retained child.

## Packaging classification

`nfdriver.sys` imports `NDIS.SYS`, `fwpkclnt.sys`, and `ntoskrnl.exe`. On the
verified Windows host, both unresolved names are Microsoft Windows kernel-mode
network drivers under `%WINDIR%\System32\drivers`:

- `NDIS.SYS`: Network Driver Interface Specification, kernel subsystem;
- `fwpkclnt.sys`: FWP/IPsec Kernel-Mode API, kernel subsystem.

They are **SYSTEM_DRIVER_DEPENDENCY_ONLY**, not distributable Launcher payload.
Do not copy them into `ProxyCore` or the one-file Launcher merely to silence a
scanner. The current `NekoProxyCore.deps.json` declares 41 managed runtime assets
and zero native assets; every declared managed asset is present, and the existing
Launcher archive contains all 248 files from the controlled `ProxyCore` input.

This packaging audit does not replace the blocked positive historical-PSO2 / host
RUNNING E2E gate.
