# Phase 2 Staging / Crypto / Deployment Integration Report

Status: **BLOCKED — NOT APPROVED FOR PRODUCTION DEPLOYMENT**  
Evidence date: **9 August 2026**  
Production deployment approval status: **Pending separate explicit approval**

This report records current local and disposable-environment evidence. It does not authorize production deployment. Mandatory hosted-staging, approved-key, positive-Core, and full Windows replacement gates remain open.

## Source provenance

| Component | Repository / branch | Verified revision | State |
| --- | --- | --- | --- |
| Launcher + Backend | `Neko-Family-Proxy`, `main` | `3149bd0badc69b0cc6446070298952d089cc1f47` | `HEAD == origin/main`; reviewed changes are uncommitted |
| Released Core | `NekoProxyCore`, `feature/neko-headless` | `ac9f5018d5f4183e4d5e7a0deced85e753c9482b` | clean; `HEAD == origin/feature/neko-headless` |

Current Launcher/Backend source changes are an overlay on the recorded base revision. The base SHA does not contain them.

## Gate results

| Gate | Result | Evidence |
| --- | --- | --- |
| Complete clean migration replay | **VERIFIED PASS** | All 31 repository migrations applied unchanged to two independent disposable PostgreSQL 16.3 clusters |
| Database authorization denials | **VERIFIED PASS** | Old session, wrong user, wrong installation, revoked session, stale heartbeat, expired license, inactive profile, and wrong product were denied in the disposable real database |
| A → B → C → A database replacement | **VERIFIED PASS** | Exactly one active Launcher session; three remembered installations; A could become authoritative again |
| Concurrent claims | **VERIFIED PASS** | Concurrent claims completed with one final active session; per-user advisory lock and unique partial index preserved the invariant |
| Auth-session-bound session controls | **VERIFIED PASS** | Same-user/different-Auth-session heartbeat and release were denied on both disposable clusters; exact claiming session heartbeat succeeded; expired Auth session was denied |
| Permit-ledger retention | **VERIFIED PASS** | Per-user cleanup removed only rows older than ten minutes, preserved recent replay/rate state, and retained the one-minute rate boundary; global retention indexes exist |
| Catalog/RLS/grants/RPC hardening | **VERIFIED PASS** | `SECURITY DEFINER`, empty `search_path`, ownership, RLS, restricted ACLs, retention indexes, and active-session index checked against live catalogs |
| Backend permit tests | **VERIFIED PASS** | Deno format/check succeeded; 42 tests passed, 0 failed |
| Independent Backend rereview | **VERIFIED PASS** | No high/medium defect remained after Auth-session control and ledger-retention hardening; the sole LOW static-test scoping gap was closed with per-function mutation coverage |
| Released Core tests | **VERIFIED PASS** | 112 passed, 0 failed at the pinned Core revision |
| Launcher authorization/non-GUI tests | **VERIFIED PASS** | 277 passed, 3 integration tests deselected |
| Launcher Tk UI module | **ENVIRONMENT-UNSTABLE** | Latest isolated run: 3 passed, 1 setup error (`tcl_findLibrary`) caused by the local UV Tcl/Tk distribution; previous isolated run passed 4/4. This is not classified as an authorization-code failure |
| Focused Launcher/Core contract tests | **VERIFIED PASS** | 30 control-channel tests passed; combined production-authorization/process/control tests passed 22/22 before the final test-only matrix expansion |
| Lint / diff hygiene | **VERIFIED PASS** | Focused Ruff checks and `git diff --check` passed |
| Real released-Core negative smoke | **VERIFIED PASS** | Real published Core returned a 43-character challenge and rejected an invalid permit with `AuthorizationInvalid` while remaining fail closed |
| Named-pipe peer authentication | **VERIFIED PASS** | Launcher authenticates each exact opened handle with `GetNamedPipeServerProcessId` before any challenge/start/permit/stop bytes; PID must equal the still-live owned Core child |
| Named-pipe attack regression | **VERIFIED PASS** | PID mismatch produced adapter failure with zero bytes written; real-process smoke reported mismatch denied and invalid permit rejected |
| Independent post-fix review | **VERIFIED PASS** | No high/critical finding, stale-PID bypass, TOCTOU path, or additional high/critical mismatch against Core `ac9f5018…` |
| Approved signing key ↔ Core pinned key | **BLOCKED** | Approved `RS256_PRIVATE_KEY` and `RS256_KID` were unavailable; generating a substitute key would not satisfy custody/provenance requirements |
| Hosted non-production Supabase authentication and issuance | **BLOCKED** | No approved staging project/configuration or staging access token/URL was available; production was not used |
| Positive RS256 permit accepted by exact Core | **BLOCKED** | Requires the approved signing key and hosted non-production issuer |
| Full Windows Launcher E2E to `CoreStatus.RUNNING` | **BLOCKED** | Requires the positive permit path |
| Real A → B → C → A Launcher/Core runtime replacement | **BLOCKED** | Database replacement is proven, but the complete live multi-Launcher runtime sequence requires hosted issuance and positive Core authorization |

## Launcher/Core security finding closure

The initial independent review found that a same-user impostor could win the fixed named-pipe name, receive an opaque permit, and spoof `Running`. The Launcher-owned fix was developed regression-first:

1. A failing test proved that a mismatched server PID was not rejected before request bytes.
2. `NamedPipeCoreControlChannel` was changed to require an expected-PID provider and invoke Windows `GetNamedPipeServerProcessId` on the exact connected handle before serialization or write.
3. `WindowsCoreProcessAdapter.owned_process_id()` returns a PID only while its retained child remains live.
4. Production composition passes that bound provider into the channel.
5. Early child exit now fails immediately instead of waiting for or trusting a stale fixed-name pipe.
6. Real-process and zero-byte negative tests passed.
7. An independent post-fix review found no high/critical issue or bypass.

The released error-code allow-list is now covered exactly, obsolete generic `Timeout` is rejected, duplicate-field and contradictory-success tests use otherwise-valid released response schemas, and the Launcher release metadata is pinned to `NEKO-AUTH-S0 / s0-rc1`.

## Runtime replacement boundary

The database linearization point immediately prevents issuance of new permits to a replaced session. Runtime shutdown is heartbeat-driven rather than a database push: the old Launcher observes a failed heartbeat, requests a Core stop, and terminates its owned Core if graceful shutdown fails. A permit already issued before replacement remains a signed capability for its strict maximum 30-second lifetime. This boundary is accepted as the implemented design but still requires the blocked live A → B → C → A runtime gate.

## Artifact and secret-safety evidence

Exact locally published Core artifact hashes:

- `NekoProxyCore.exe` SHA-256: `1b9b0ba313ac1f8c879f07f678a2f01e5b334c29fc17323533017aed2cbffcfe`
- `NekoProxyCore.Core.dll` SHA-256: `a501534eea129577eebdb93a2c4fe3ee5d69c36a6502a3c6db6d4f11662a03b6`
- Core TRX evidence: `E:\Temp\neko-phase2\TestResults\phase2-final.trx`

The reviewed Git diff contained no private-key, bearer-token, or JWT value pattern. A broad path-only local scan identified markers in source/tests and bundled PostgreSQL/pgAdmin packages. It also identified ignored, untracked `docs/.env.local`; that local credential/configuration file was not read, modified, or included as evidence. No raw permit, signing private key, access/refresh token, service-role key, password, or connection string is included in this report.

## Production-change record

- Production migration applied: **NO**
- Production Edge Function deployed: **NO**
- Production signing secret created, replaced, or modified: **NO**
- Production Supabase data/configuration mutated: **NO**
- Commit created: **NO**
- Push performed: **NO**

## Non-executed deployment and rollback plan

The exact controlled sequence is maintained in [`../current/phase-2-production-deployment-plan.md`](../current/phase-2-production-deployment-plan.md). It is explicitly marked **NOT AUTHORIZED FOR EXECUTION** and requires a separate production deployment approval after every blocked gate above is closed.

## Required evidence to unblock

1. Provision or approve an isolated non-production Supabase project and provide authorized staging access without exposing credentials.
2. Inside approved key custody, prove that the deployment private key derives the public key pinned by the exact released Core under the expected KID; record fingerprints and pass/fail only.
3. Apply the complete migration chain and deploy `issue_launch_permit` only to that approved non-production target.
4. Exercise hosted Gateway JWT validation, current-session binding, all entitlement denials, permit issuance, replay/rate behavior, and sanitized logs.
5. Feed a genuinely hosted, approved-key-signed permit to the exact released Core and obtain positive authorization.
6. Run the Windows Launcher chain through `AUTHORIZED_START → RUNNING_VERIFY → CoreStatus.RUNNING`.
7. Run live A → B → C → A replacement and prove old Launchers lose authority and stop their owned Core within the documented heartbeat/capability boundary.
8. Re-run all canonical suites and independent review against the exact source/artifact revisions proposed for approval.

BLOCKED — approved signing-key compatibility, hosted non-production Supabase issuance, positive exact-Core authorization, full Windows Launcher E2E, and live A → B → C → A runtime replacement remain unverified
