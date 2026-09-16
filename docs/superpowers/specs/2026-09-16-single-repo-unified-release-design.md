# Neko Family Proxy — Single-Repo Unified Release Architecture

**Date:** 2026-09-16  
**Status:** Design approved in conversation; written-spec review gate pending  
**Board:** `neko-family-5-1-2-revision-3-4` / `ARCH-SR1` (`t_c1bafe84`)  
**Design branch:** `design/single-repo-unified-release`  

## 1. Decision summary

Neko Family Proxy will use one canonical public GitHub repository for source, Human installation, and machine-update release assets:

`Valeneko-pranmong/Neko-Family-Proxy`

The separate `Valeneko-pranmong/Neko-Family-Proxy-Updates` architecture is superseded and must not be created or published to. Source remains public (Owner Option A), but public source/assets must not create a usable portable client. Protected service use remains server-authorized.

Every 5.x GitHub Release is a complete, self-contained release set:

- `NekoFamilyProxy-Installer.exe`
- `release-v2.json`
- `NekoLauncher.exe`
- `NekoUpdater.exe`
- `NekoProxyCore.zip`
- GitHub-generated Source code (zip)
- GitHub-generated Source code (tar.gz)

The Release contains the full set even when only one component changed. Runtime Auto Update may download only the changed Launcher/Core bytes, while the complete Release remains the authoritative reference set for integrity checks, diagnostics, and support.

## 2. Owner decisions frozen by this spec

1. Source stays public.
2. Human Installer and machine-update assets live in the same repository and same version Release.
3. Every 5.x Release publishes the complete asset set listed above.
4. `NekoUpdater.exe` does not self-update during the 5.x major line.
5. Auto Update within 5.x may replace Launcher and Core only.
6. Every newer authenticated 5.x Release is mandatory: no Skip, Later, continue-offline, or use-old-version path.
7. If Updater is missing, corrupt, untrusted, or incompatible, the client fails closed and tells the user to uninstall/reinstall.
8. 5.x -> 6.0.0 is not an in-place upgrade. Users uninstall 5.x and install 6.0.0 fresh.
9. File Check is diagnostic-only until the user explicitly presses Repair.
10. Repair uses the trusted Updater and restores the exact installed Release; Repair is not an implicit version upgrade.
11. If Updater itself is bad, Repair does not repair Updater; uninstall/reinstall is required.
12. A Launcher copied directly from GitHub Assets is not a portable app and must not enter normal login/service flow without an Installer-established installation binding.
13. Copying the entire installed directory to another machine must not produce a usable client.
14. Reinstalling Windows or replacing a disk is user-serviceable: install through Installer and log in again; no admin approval is required.
15. Single-active-session enforcement remains mandatory. A newly accepted session invalidates the old active session for protected service use.

## 3. Goals

### 3.1 Maintenance simplicity

Maintain one public repository and one version Release surface rather than separate Human and machine repositories. A maintainer should be able to answer “what are the exact files for v5.1.3?” by looking at one GitHub Release.

### 3.2 Strong update consistency

A client may use protected service functionality only after startup has reconciled to the current authenticated 5.x Release and post-update integrity checks pass. This prevents long-lived mixtures of old/new Launcher/Core generations.

### 3.3 Public distribution without portable service use

The repository, source, and Release assets may be downloaded by anyone. Security must therefore not depend on hiding binaries or source. Protected service capability depends on backend authentication, entitlement, single-active-session authority, fresh launch permits, and installation/session proof.

### 3.4 Recovery without a second repair executable

Keep the recovery tree intentionally short. File Check can repair Launcher/Core through the existing trusted Updater. If the trusted Updater cannot operate, stop and require reinstall. Do not add `NekoRepair.exe` or an updater-of-the-updater bootstrap in 5.x.

## 4. Non-goals

- No DRM claim that public binaries/source are impossible to reverse engineer.
- No attempt to make `NekoUpdater.exe` self-replacing in 5.x.
- No 5.x -> 6.x in-place protocol migration.
- No silent File Check repair.
- No automatic admin approval workflow for a reinstalled machine.
- No new public repository.
- No public GitHub Release/tag mutation during implementation/review tasks.
- No mutation or reuse of already signed production authority records unless a separately reviewed authority migration explicitly permits it.

## 5. Unified GitHub Release model

For version `5.x.y`, the canonical Release tag is `v5.x.y` in `Valeneko-pranmong/Neko-Family-Proxy`.

The release publication gate requires the five authored assets as one closed set:

```text
NekoFamilyProxy-Installer.exe
release-v2.json
NekoLauncher.exe
NekoUpdater.exe
NekoProxyCore.zip
```

GitHub adds its source archives automatically. The machine manifest continues to cryptographically authenticate the runtime component set (Launcher/Updater/Core), including exact component version, size, SHA-256, release sequence, release identity, update protocol bounds, and release signature. The release publisher additionally verifies the Installer asset and the hosted Release/tag/commit binding before promotion.

No runtime code may accept a release merely because GitHub labels it `latest`; it must first pass the existing signed-envelope/trust-profile validation and exact repository/tag/asset checks.

For production stable 5.x, the release builder/publisher must reject a payload unless `mandatory == true`. Runtime policy must also derive the gate from authenticated release ordering: any authenticated newer 5.x sequence is mandatory even if a malformed/misconfigured signed payload carries `mandatory == false`. A false flag may produce a diagnostic, but it can never create a Skip/Later/use-old-version path.

## 6. Startup state machine

Normal startup is gated in this order:

```text
START
  -> validate expected installation root + installation binding
  -> validate trusted Updater identity/integrity
  -> resolve authenticated canonical GitHub Release
  -> validate signed release envelope and repository/tag/asset binding
  -> compare local committed release with remote release
       -> same accepted release: continue
       -> newer 5.x: MANDATORY UPDATE
       -> 6.x or incompatible major/protocol: REINSTALL REQUIRED
       -> unavailable/invalid/conflicting authority: FAIL CLOSED
  -> if mandatory update: stage changed Launcher/Core only
  -> apply through trusted Updater
  -> post-update integrity/release-state verification
  -> only then allow normal Login / protected-service flow
```

There is no Skip/Later button for a newer 5.x Release. If network/update execution fails, the UI may offer Retry and diagnostics, but it must not expose normal service use on the stale release.

## 7. Updater lifecycle for 5.x

`NekoUpdater.exe` is an immutable-ish infrastructure helper for the 5.x line.

- It remains present in every 5.x Release so every Release is complete and future File Check/support tooling has canonical reference bytes.
- Auto Update never stages/replaces Updater.
- Startup verifies the installed Updater against authenticated release/trust data before delegating update or repair work.
- Direct Updater execution remains inert except explicitly supported self-check/session protocol paths.
- If the installed Updater does not match the trusted expected bytes or cannot run its protocol, no self-heal is attempted. The user is instructed to uninstall and reinstall.

This intentionally accepts a small recovery inconvenience in exchange for much lower updater-bootstrap, rollback, and self-replacement complexity.

## 8. File Check and Repair

### 8.1 File Check

File Check is explicitly user-invoked and diagnostic-only. It identifies the machine's authenticated installed Release, obtains/verifies the canonical signed metadata for that exact Release, and compares expected installed artifacts with local state. Committed local state must retain enough immutable release identity to resolve that historical Release exactly (for example authenticated release sequence/release id plus the component version/tag, or a verified hosted release id). Historical File Check/Repair must query the exact tag/release identity and must never silently substitute GitHub `latest`.

The result should be per component, for example:

```text
NekoLauncher.exe  OK
NekoUpdater.exe   OK
NekoProxyCore     CORRUPT
```

File Check must not download or overwrite anything by itself.

### 8.2 Repair

If Launcher/Core is missing or corrupt and Updater is trusted, the UI enables an explicit Repair action. After the user presses Repair:

1. re-resolve and authenticate the exact currently installed Release;
2. revalidate Updater integrity;
3. download only the damaged Launcher/Core artifact from that Release;
4. verify expected size + SHA-256 and signed release binding;
5. apply via the normal Updater transaction/rollback path;
6. re-run integrity verification before reporting success.

Repairing v5.1.3 restores v5.1.3. It does not silently upgrade to v5.1.4. If a mandatory newer 5.x Release exists at normal startup, the mandatory-update gate remains separate and takes precedence before normal service use.

If Updater is bad, if the authenticated exact Release cannot be recovered, or if repair authority is ambiguous, the outcome is `REINSTALL REQUIRED` rather than a second repair mechanism.

## 9. Installation binding and anti-portability

Local installation binding is a defense-in-depth anti-portability control, not the ultimate entitlement boundary.

The Installer provisions an installation identity on that Windows machine. Implementation should prefer a generated installation key/credential protected by an OS machine-bound facility (for example Windows CNG/DPAPI machine scope) rather than a hardware fingerprint or a secret stored as a normal copyable file. The installed directory contains only the identifiers/public material needed to locate/use that protected credential.

Consequences:

- Downloading `NekoLauncher.exe` directly and double-clicking it outside a provisioned install fails before normal login/service use and directs the user to `NekoFamilyProxy-Installer.exe`.
- Copying Launcher/Updater/Core/state files to another machine does not copy the machine-protected installation credential, so the destination fails closed and must install normally.
- Reinstalling Windows or replacing a disk creates a fresh installation identity. The user can log in normally; no manual admin approval is required.

Because source is public, modified clients can remove local UI checks. Therefore backend authorization remains authoritative: protected service operations and Core launch permits must require an authenticated/entitled active session plus the expected installation/session proof. No client-only machine check is considered a security boundary by itself.

## 10. Authentication and single-active-session behavior

This architecture must preserve the existing single-active-session contract.

A user may have historical installation identities, and reinstall may create a new identity, but protected service use permits only one active session/authority at a time. When a new session becomes authoritative, an old session must fail closed through the existing session/heartbeat/permit mechanisms: future permit issuance is denied and an already running protected Core loses the authority needed to continue.

The single-repo/update changes must not weaken `SessionInactive`, entitlement, heartbeat, replay, or launch-permit checks.

## 11. Release 5.x and 6.0.0 boundary

All compatible 5.x releases use the stable 5.x Updater protocol and mandatory in-place Launcher/Core update path.

Version 6.0.0 is a hard major boundary. If a 5.x client resolves a 6.x release or a manifest/protocol that the 5.x Updater cannot safely support, it must not experiment with self-migration. It shows a clear “uninstall 5.x and install 6.0.0” path and remains fail closed.

## 12. Publication and authority migration from Revision 3.4

The current Revision 3.4 plans contain dedicated-machine-repository assumptions. Those assumptions are superseded by this spec and must be amended before implementation workers are dispatched.

High-risk existing production evidence must be preserved, not rewritten:

- accepted 5.1.2 source commit remains historical evidence;
- the production sequence ledger is append-only authority evidence;
- the already SIGNED sequence-8 record was produced for the earlier architecture and has not been published;
- no `PUBLISHED` event may be appended for that old binding;
- no controller may reinterpret the old Owner CR7/CR8 authorization text as permission to publish the new single-repo design.

Before any new production signing/publication, the implementation plan must define a ledger-safe supersession path for signed-but-unpublished sequence 8. The old SIGNED bytes are immutable. The current ledger schema explicitly allows `SIGNED -> FAILED`, and `FAILED` is terminal; therefore the implementation plan must evaluate and independently review whether appending a `FAILED` event is the correct supersession mechanism for this architecture change. It must not invent an overwrite/re-sign path. Because the current event schema has no dedicated failure-reason field, any such transition also needs durable external evidence tying the terminal event to this approved architecture supersession. A new payload/signature must use a fresh sequence determined by reconciliation after that terminal event; sequence 8 must not simply be overwritten or re-signed with different repository/release bytes.

Any trust-profile immutability guard that currently binds production to `Neko-Family-Proxy-Updates` must be intentionally reopened through its normal acceptance/review process. Do not patch around the immutability guard.

## 13. Expected implementation areas

The implementation plan is expected to touch, at minimum, these responsibility areas while preserving existing boundaries where possible:

- production update-channel profile/trust enrollment repository binding;
- GitHub Release discovery/download URL binding;
- unified publisher and hosted-release exact asset-set verification;
- release authority migration/supersession for the signed-but-unpublished old binding;
- startup mandatory-update gate before normal login/service flow;
- installation-binding bootstrap/validation;
- File Check diagnostic model/UI;
- user-authorized exact-release Repair path;
- Updater-integrity failure -> reinstall-required path;
- tests/evidence for copied-folder rejection and reinstall behavior;
- existing single-active-session and launch-permit regression coverage.

Existing safety properties must be reused rather than replaced: canonical signed release envelopes, SHA-256 artifact verification, sequence/replay/downgrade checks, transactional staging/activation, rollback, Updater IPC admission, entitlement/session/heartbeat enforcement, and independent review gates.

### 13.1 Gap inventory from the accepted implementation

The accepted implementation already provides useful pieces that should be preserved rather than rebuilt:

- default GitHub Release discovery already points to `Valeneko-pranmong/Neko-Family-Proxy`;
- the authenticated release resolver already requires and verifies `release-v2.json`, Launcher, Updater, and Core assets;
- staging already filters updates to Launcher/Core and never replaces Updater;
- direct Updater execution is already restricted to self-check or validated IPC session mode;
- transactional updater state already has internal `REPAIR_REQUIRED` outcomes for damaged updater state.

The following are real gaps, not greenfield assumptions:

- the installed production trust profile, K1 acceptance verifier, release controller, publisher tests, and several current docs still bind production routing to `Neko-Family-Proxy-Updates`; reopening that accepted trust contract is required;
- the machine publisher and Human publisher are separate programs with contradictory asset/repository contracts, so unified one-Release publication requires an intentionally reviewed publisher contract rather than a constant-only edit;
- existing `REPAIR_REQUIRED` behavior is updater-state recovery, not the new user-facing exact-release File Check/Repair workflow;
- the current installation ID is generated and persisted in enrollment state, but no DPAPI/CNG machine-bound credential path was found in the accepted Launcher source; copied-folder rejection therefore needs a new machine-protected installation proof rather than relying on the existing installation ID alone;
- production sequence authority already supports terminal `FAILED` after `SIGNED`, which is the candidate safe mechanism for consuming old sequence 8, subject to explicit TDD/review/evidence as described above.

## 14. Required test families

Implementation is not acceptable without automated evidence for at least:

1. canonical repo is `Valeneko-pranmong/Neko-Family-Proxy`; dedicated Updates repo is rejected;
2. every published 5.x Release requires the full authored asset set;
3. runtime downloads only changed Launcher/Core while validating the full Release;
4. any newer authenticated 5.x Release blocks normal use until update succeeds;
5. no Skip/Later/offline-bypass path exists;
6. Updater never self-updates in 5.x;
7. corrupt/missing Updater produces reinstall-required and performs no mutation;
8. File Check never mutates files;
9. Repair requires explicit user action and restores the exact installed Release;
10. Repair rejects unsigned/wrong-hash/wrong-repo/wrong-tag assets;
11. direct standalone Launcher Asset fails without Installer-established binding;
12. copied installation fails on a second machine;
13. legitimate reinstall can establish a new binding and log in;
14. new login preserves single-active-session behavior and invalidates old authority;
15. 5.x -> 6.x refuses in-place update and requests clean reinstall;
16. signed-but-unpublished old production authority cannot be silently rebound/reused;
17. full Launcher/update/release-authority regression suites stay green;
18. independent reviewer returns C0/I0 on every security/release gate required by the board.

## 15. Public mutation gates

Implementation, tests, local simulations, and reviews are local-only until their own gates are accepted. Public GitHub actions remain controller-only and require fresh exact Owner authorization bound to the final reviewed commit, release tag, source commit, signed authority state, and exact asset hashes.

The earlier CR7 gate to create `Neko-Family-Proxy-Updates` is permanently superseded by this design and must never execute.

## 16. Acceptance criteria for this architecture

The architecture is satisfied when a normal 5.x user experiences this behavior:

```text
Install once through Installer
  -> Login
  -> use normally

Later 5.x release appears
  -> Launcher detects authenticated newer release
  -> update is mandatory
  -> trusted Updater changes only needed Launcher/Core bytes
  -> integrity check passes
  -> normal use resumes

User suspects damaged files
  -> presses File Check
  -> sees exact per-file status
  -> presses Repair if needed
  -> trusted Updater restores exact current-release Launcher/Core bytes

Updater is damaged / protocol cannot continue
  -> no nested repair machinery
  -> uninstall + reinstall instruction

6.0.0 arrives
  -> no 5.x self-migration
  -> uninstall 5.x + clean 6.0.0 install
```

Maintenance remains centered on one repository and one complete Release per version, while backend authorization remains the real security boundary for service use.
