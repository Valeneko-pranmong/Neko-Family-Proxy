# Neko Family 5.1 — Phase-3 Balanced Security Amendment

**Status: DESIGN AMENDMENT — awaiting user review before implementation plan**

## Scope and compatibility
- This amendment governs only work not already implemented/accepted as of commit `8d9d8fdcbe30d97c903c275dbf450a9048991c9a` (Unit2 generation_builder accepted). Existing accepted modules/tests remain valid and are not to be weakened merely because they exceed the new minimum.
- This is a threat-model reduction, not a rollback of already-delivered security.

## Balanced threat model
Protect against: casual/local non-admin user tampering, accidental file edits/deletes, corrupted/truncated downloads, wrong package/release, unsigned/invalid signed metadata, hash mismatch, downgrade/replay of older release, ZIP traversal/symlink/reparse entries during extraction, interrupted/crashed update, failed startup/self-test after activation.

Explicit non-goals for future NEW orchestration work: malicious local administrator/SYSTEM, kernel/rootkit, malware racing every filesystem operation, deliberate Win32 handle/rename race attacks, exhaustive ADS/hardlink/reparse substitution after already-authenticated staging, process-tree lease survival against hostile local code, forensic same-handle proofs for every leaf, adversarial power-loss proof for every intermediate mutation beyond practical crash-safe checkpoints.

## Preserve secure foundation
Keep and reuse without simplification: signed canonical release envelope/manifest validation, SHA-256 artifact/installed identities, anti-downgrade/highwater semantics already present, canonical Core inventory verification, safe ZIP extraction/path rejection already present, immutable generation naming/building, GenerationPublisher atomic-ish publish behavior, SlotStore/recovery primitives already implemented, rollback/probation helpers already implemented, existing Unit1/Unit2 tests. Do not delete security checks from these modules.

## New minimal update flow for remaining work
Use a straightforward orchestration flow:
1. BEGIN: validate current selected state is usable; authenticate signed release envelope; enforce helper protocol and anti-downgrade; compute changed components from trusted committed generation identity; create request IDs and an incoming directory; persist one practical PREPARING/ADMITTED checkpoint; return fixed request/transaction IDs and changed booleans.
2. Download: Launcher writes only fixed filenames `launcher.artifact` and/or `core.artifact.zip` into its broker-created incoming directory. No child-supplied paths.
3. APPLY: broker validates exact expected filenames, regular files, bounded size and SHA-256. Reject extras/missing. It does NOT need retained-handle lifetime proofs against hostile concurrent local attacker beyond normal safe open/read checks.
4. Build: call accepted `build_generation()` and keep its stronger internal security unchanged.
5. Publish: publish generation through accepted `GenerationPublisher`; verify resulting generation using existing manifest/identity verifier once after publish. Practical crash checkpoint is enough; do not journal every filesystem sub-operation merely to defeat malicious local racing.
6. Activate: later orchestration selects candidate only after publish verification and a bounded Launcher/Core self-test. Existing rollback primitives may be reused. If activation/self-test fails, select last-known-good generation. No need for elaborate nested family-lease hostile-survival proof unless required for actual correctness.
7. Cleanup: remove only paths created by the current known transaction when ordinary filesystem safety checks pass. Unknown roots remain untouched. DirectoryIdentity may be reused where already convenient, but future code is not required to retain every ancestor/leaf handle throughout the entire transaction.

## State durability simplification
- Preserve SlotStore fixed-slot implementation because it already exists and is tested.
- Remaining orchestration should use coarse durable checkpoints only: ADMITTED, BUILT/PUBLISHED-VERIFIED, ACTIVATED/COMMITTED or ABORT/CLEANUP. It may map these to existing State/Transaction fields without introducing new elaborate mutation journals unless a current module requires it.
- Do not create new security machinery solely to prove every intermediate INTENT/DONE ordering against malicious local races.
- Existing state schema may remain richer than the minimum; avoid schema churn unless needed.

## Broker API design target
- Keep `BrokerCoordinator` small and orchestration-focused; reuse `staging_handoff`, `generation_builder`, `generation_publisher`, `precommit_abort`, verifier/state helpers rather than duplicate cryptographic/filesystem logic.
- Public methods target: `begin(envelope_b64) -> RequestReadyResult`, `apply(transaction_id, request_id) -> ApplyResult`, `cancel(transaction_id) -> None` if CANCEL remains useful. Result fields follow existing/wire semantics but tests should focus on user-visible correctness and crash-safe authority, not hostile race proofs.
- Broker must not own network/download logic or process-family supervision.

## main.py target
- `main.py` should be thin process/orchestration glue: startup/recovery, one broker session, invoke existing probation/self-test/rollback helpers, exit codes. Avoid creating a second security framework.

## Testing strategy
For remaining units require: contract tests for signed manifest, anti-downgrade, fixed filenames, missing/extra/corrupt artifacts, build/publish failure, crash/restart at coarse checkpoints, successful Launcher-only/Core-only/Both/metadata-only flows, activation failure rollback. Keep a few realistic Windows path/reparse tests already provided by lower layers. Do NOT require exhaustive hostile local race/ADS/hardlink/DirectoryIdentity lifetime tests at broker/main layer when lower layers already cover them.
- Review gate for new Balanced units: Critical 0 / Important 0 applies only to requirements inside the Balanced threat model; use one focused independent review per unit and iterate only concrete blocker findings that violate in-scope correctness/security. Explicitly, omissions that are listed non-goals (hostile local admin/races/forensic handle proofs etc.) are not findings.

## Acceptance/non-goals
- No weakening of Unit1/Unit2 accepted files.
- No production deployment/signing/publication in this amendment.
- Current untracked 980-line broker test draft is discarded and must not be used as authority.
- New implementation work waits for a separate implementation plan approved from this amendment.

## Migration table (OLD requirement -> NEW handling)

| OLD requirement | NEW handling |
|-----------------|--------------|
| Retained leaf handles | Normal safe open/read operations; no handle retention required across lifecycle merely to defeat local races |
| DirectoryIdentity journaling | Can be reused where convenient, but not required to retain every ancestor/leaf handle through transaction |
| Per-operation INTENT/DONE | Replaced by coarse durable checkpoints: ADMITTED, BUILT/PUBLISHED-VERIFIED, ACTIVATED/COMMITTED or ABORT/CLEANUP |
| Family lease/job survival | No elaborate nested lease tracking unless strictly required for standard crash correctness |
| Exhaustive ADS/hardlink races | Explicit non-goal; no exhaustive tracking for already authenticated staging paths (rely on underlying OS & fixed structures) |
| Fixed slots | Kept (SlotStore already exists and is tested) |
| Signed/hash verification | Kept unchanged; continue using signed canonical envelope and SHA-256 identities |
| Rollback/self-test | Kept unchanged; continue using existing rollback/probation primitives if self-test fails |

**Status: DESIGN AMENDMENT — awaiting user review before implementation plan**
