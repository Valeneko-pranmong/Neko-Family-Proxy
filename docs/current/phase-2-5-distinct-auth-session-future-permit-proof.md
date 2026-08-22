# Phase 2.5 distinct Auth-session future-permit proof

```text
STATUS:                 CLOSED/PASS
PHASE:                  Phase 2.5 — technical security closure
AUTHORITY:              START bba655b3e6443ebcdf84a266e42cc918bdefe32f; CORE 862bfec463d06d57e1bee05c2bc490740eb714d4
SUCCESSOR:              RELEASE/CUTOVER GATE
LAST_UPDATED:           2026-08-22
CLASSIFICATION:         CURRENT_RELEASE_EVIDENCE
UI_WORK_BLOCKER:        NO
PUBLIC_RELEASE_BLOCKER: NO — release/cutover is the successor gate
DATE:                   2026-08-18
```

> [!IMPORTANT]
> **Status: CLOSED/PASS.** The hosted distinct-auth technical security proof completed.
> The next gate is release/cutover; production cutover is not claimed here.

## What it proves

### Verified closure result

- Auth sessions pairwise distinct: **YES**.
- A→B→C→A replacement: **PASS**.
- Old A/B/C heartbeat denial: **PASS**.
- Old A/B/C future permit: **403 `SessionInactive`**.
- Successful permits: **0**; Core starts: **0**; Core challenges: **0**.
- Remembered installation A reused: **YES**; final cleanup: **PASS**.
- Hosted migration `20260821120000_neko_auth_lite_latest_claim_wins` deployed and verified.
- Temporary autotest user/entitlement cleaned up; final active test sessions: **0**.

Original run Edge evidence: **A=MISSING, B=PASS, C=PASS**. Supplemental old-A
Edge evidence: **PASS**. The original run did not contain all three Edge logs.

`HISTORICAL_FORCE_PUSH_VIOLATION = RECORDED` remains unchanged, and
`PROCESS_COMPLIANCE = FAIL` until Owner explicitly waives it. Historical
`FIRST_ACTIVE_WINS` behavior is preserved as superseded history.

One disposable Launcher user obtains three independent normal Supabase Auth
sessions, labelled A, B, and C. The harness reads each JWT `session_id` only
in memory and proves the three values are pairwise different without recording
or displaying any of them.

The required hosted sequence is:

1. Auth A claims installation A.
2. Auth B claims installation B.
3. Old A heartbeat is denied.
4. Old Auth A sends one protocol-valid direct `issue_launch_permit` request and
   must receive Backend Edge HTTP `403` with fixed error `SessionInactive`.
5. Auth C claims installation C.
6. Old B heartbeat is denied.
7. Old Auth B receives the same required Edge denial from one request.
8. Auth A reclaims installation A.
9. Old C heartbeat is denied.
10. Old Auth C receives the same required Edge denial from one request.

`LOCAL_PRECONDITION_DENIAL`, a generic HTTP 403, a transport error, or a
successful permit is a failed proof. The accepted classifier is exactly
`BACKEND_EDGE_SESSION_INACTIVE` and requires the Edge invocation, HTTP 403,
and `SessionInactive` response together.

The direct request has the exact current Edge protocol shape, but is made only
after the old Auth context has already lost Launcher authority. It creates no
Core challenge and never starts Core. A successful response is an immediate
failure and its content is never retained or written to evidence.

Harness uses Lite-v1 adapter call exactly:

```text
issue_launch_permit(
    authenticated_transport,
    correlation_id,
    challenge,
    timeout
)
```

Request body remains exactly `version`, `contractRevision`, `correlationId`, and
`challenge`. Obsolete S0 fields such as `configurationDigest`, `processName`,
`targetPid`, `mode`, `product`, and `scope` are not sent.

## Safety contract

- Auth A, B, and C are three separate `sign_in_with_password` calls backed by
  separate ephemeral stores. Tokens are never cloned, persisted, printed, or
  placed in command-line arguments.
- The harness uses only a publishable client key. It contains no service-role,
  Admin API, forged JWT, or manual `session_id` path.
- Before accepting any manual credential input it checks that `pso2.exe` is
  confirmed closed; an unavailable process observation also fails closed.
- The only expected hosted writes during an authorized run are the four normal
  Launcher session claims and the final release of the final A Launcher
  session. The three old-session permit calls must be rejected before permit
  issuance.
- Cleanup requires zero active Launcher sessions. The three remembered
  installation records must still be available and have zero permanent device
  revocations.

The safe result has only fixed classifications and counts: three Edge denials,
zero successful permits, zero permit retries, zero Core starts, and zero Core
challenges. It never contains a credential, JWT, permit, endpoint, or raw Auth
or Launcher session identifier.

## Offline preparation now

From `D:\Git\Neko-Family-Proxy\launcher`, this command is offline and only
writes a safe readiness manifest to the chosen non-secret location:

```powershell
.\.venv\Scripts\python.exe -m neko_launcher.e2e.distinct_auth_session_future_permit prepare --output <safe-output-path>
```

It performs no Auth login, claim, heartbeat, Edge invocation, Core action, or
database change.

## Operator procedure after a separate explicit authorization

1. Confirm the exact Launcher and Core checkpoints, a clean Launcher worktree,
   the approved disposable account, and a maintenance window. Do not run the
   old `E:\Temp\abca_test.py` script.
2. Close PSO2 completely. The harness checks this before it prompts; if it
   reports `PSO2_CLOSED_REQUIRED`, stop and close the game rather than retrying
   around the check.
3. In one trusted interactive PowerShell session, load the approved Supabase
   URL and publishable key into `NEKO_PHASE25_SUPABASE_URL` and
   `NEKO_PHASE25_SUPABASE_PUBLISHABLE_KEY` without echoing either value or
   placing them in a command history. Do not provide a service-role key.
4. Set `NEKO_LIVE_DISTINCT_AUTH_SESSION_PROOF` to `YES-I-UNDERSTAND`, then run
   `python -m neko_launcher.e2e.distinct_auth_session_future_permit execute
   --live --output <safe-output-path>`. This command prompts separately for
   the username and password with hidden input; do not paste credentials into
   command arguments, files, or chat.
5. Accept completion only when the process prints
   `DISTINCT_AUTH_SESSION_FUTURE_PERMIT_PROOF_VERIFIED` and the safe output
   reports the required three Edge denials and all zero counters. Any other
   fixed result is a stop condition, not a retry instruction.

No production signing key rotation, migration, Core rebuild, or Hosted Positive
+ KP execution belongs to this procedure.
