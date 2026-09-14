# Neko Family Proxy 5.1.2 Baseline / Mandatory Update — Spec Revision 3.4

**Status:** OWNER APPROVED — 2026-09-13  
**Approval:** Critical 0 / Important 0  
**Scope:** Architecture/release contract for v5.1.2 baseline, v5.1.3+ mandatory updates, machine-channel separation, and retirement of the historical installer repository.

This document is the repository copy of the Owner-approved Revision 3.4 contract. It supersedes the 2026-09-12 v5.1.2 architecture wherever the older document conflicts with this one.

## 1. Release topology

- Human-facing source/release repository: `Valeneko-pranmong/Neko-Family-Proxy`.
- Production machine-update channel: `Valeneko-pranmong/Neko-Family-Proxy-Updates`.
- Proof channel: isolated from production, with an explicitly separate proof trust/channel profile.
- Historical `Valeneko-pranmong/Neko-Family-Proxy-Installer`: frozen until retirement gates pass, then DELETE the entire repository.
- GitHub repository/release metadata is transport/discovery metadata, not the cryptographic trust root.
- Signed `release-v2.json` + trusted public key + durable authenticated state are the release authority.

## 2. Human-facing v5.1.2 contract

Canonical `Neko-Family-Proxy` Human Release must:

- use tag/name `v5.1.2`;
- have exactly one custom asset: `NekoFamilyProxy-Installer.exe`;
- contain no custom `NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, or `release-v2.json`;
- use the same presentation shape as v5.1.0:
  - `# Neko Family Proxy v5.1.2`
  - current stable release
  - normal users download Installer ONLY
  - `Highlights | จุดเด่น`
  - `Downloads | ดาวน์โหลด`
  - `Notes | หมายเหตุ`
- be bilingual English/Thai;
- explicitly tell v5.1.0 users to uninstall v5.1.0 and manually install v5.1.2 once; automatic mandatory updating begins from the v5.1.2 baseline for later releases.

GitHub-generated source archives are not custom assets.

## 3. Production sequence custody

A read-only cryptographic audit has already authenticated `stable-0007 / release_sequence=7`. Therefore the provisional next-unused production sequence is 8.

Current provisional allocation:

- final v5.1.2: `stable-0008 / sequence 8`;
- later production v5.1.3: `stable-0009 / sequence 9`.

These numbers are provisional until the pre-reservation/pre-sign audit. Sequence allocation is:

```text
next_unused_sequence =
    max(highest_authenticated_sequence,
        highest_consumed_sequence_in_production_ledger) + 1
```

A sequence becomes permanently consumed once reserved/signed according to the release process. Deleted, failed, rolled-back, or unpublished signed authorities never become reusable.

Maintain a durable append-only **Production Sequence Authority Ledger** with at least sequence, release_id, status, version, channel, payload SHA-256, signed-envelope SHA-256, key_id, source commit, timestamp, and previous-entry digest. Ledger/history divergence is a hard stop requiring reconciliation.

## 4. Separate Project Release-Audit Ledger

The **Project Release-Audit Ledger** is separate from the Production Sequence Authority Ledger. It holds forensic/release/destructive-operation evidence. It must survive deletion of the historical installer repository and must not be stored authoritatively inside that retiring repository.

The release-audit ledger cannot allocate/reuse production sequence numbers. The sequence ledger cannot substitute for forensic custody.

## 5. Baseline identity and enrollment

The final baseline sequence/release_id is whatever next-unused production allocation is established by the release ledger immediately before reservation/signing. Under the current audit it is provisionally seq8/stable-0008.

Production v5.1.2 baseline semantics:

```text
channel                    = stable
release_sequence           = next-unused production sequence
release_id                 = corresponding stable-NNNN id
version                     = 5.1.2
mandatory                   = false
minimum_supported_sequence = baseline sequence
```

Installer/Launcher must never create authenticated baseline state by trusting unsigned compile-time sequence/release_id/version metadata.

The final Installer embeds the **exact production-signed baseline envelope bytes**. Fresh installation enrollment must:

1. read the embedded envelope;
2. validate canonical envelope/schema;
3. verify production signature/trust profile;
4. verify protocol/channel;
5. verify exact installed Launcher identity;
6. verify exact installed NekoUpdater identity;
7. verify exact installed Core identity;
8. only then commit durable baseline state/high-water.

If any identity disagrees with the signed envelope, enrollment fails closed. Because the envelope is embedded, a fresh v5.1.2 install can enroll offline on first run.

The embedded envelope must be byte-for-byte the same envelope later published to the Production Updates repository. Installer provenance records the envelope SHA-256, payload SHA-256, exact component identities, source SHA, sequence, release_id, and key_id.

## 6. Production machine baseline before Human Release

Final build ordering is:

```text
exact final Launcher/Updater/Core
→ allocate/reserve next-unused sequence
→ generate canonical baseline payload
→ production sign + locally verify exact envelope
→ build final Installer embedding exact envelope + exact components
→ qualify Installer/proof/review
→ publish exact machine baseline to Neko-Family-Proxy-Updates
→ live-read production endpoint
→ production-candidate v5.1.2 resolves itself LATEST / NO UPDATE
→ retirement/tag gates
→ Human Release
```

Mocks/local fixtures do not satisfy production live-readback.

## 7. Authenticated ordering and mandatory semantics

Ordering uses authenticated authority, not semantic version strings.

- Newer candidate: authenticated remote sequence must be greater than authenticated local high-water before admission as a new authority.
- Same sequence + exact same release_id/payload/component binding: idempotent `LATEST / NO UPDATE`.
- Same sequence + conflicting release_id/payload/component binding: fail closed with same-sequence identity conflict.
- Remote sequence lower than local authenticated high-water: downgrade/replay reject.

Committed sequence and high-water have different jobs:

- committed sequence = trusted runtime generation currently in use;
- high-water = highest authenticated authority floor seen, used for anti-replay/rebinding.

Mandatory formula after authentication/ordering:

```text
mandatory_update =
    authenticated_remote.mandatory == true
    OR
    committed_local.release_sequence
        < authenticated_remote.minimum_supported_sequence
```

Do not substitute high-water for committed runtime sequence in the minimum-supported test.

Rollback may produce committed seq8 / high-water seq9; corrected production payload must then use seq10, never reuse seq9.

## 8. Offline/discovery semantics

A discovery outage (network/DNS/GitHub/timeout) must not brick a valid committed installation when there is no authenticated mandatory pending transaction requiring completion.

- No authenticated mandatory authority: committed runtime remains usable offline.
- Mandatory authority authenticated but artifacts incomplete: retain authenticated authority according to state contract, do not fabricate `UPDATE_PENDING`, retry staging when network returns.
- Mandatory authority + fully verified durable pending: apply offline when safe.

Mandatory means eventual update at a safe point. It never grants permission to force-terminate an active game/session.

## 9. Proof/production equivalence

Proof and production 5.1.2 must use the same source commit, dependency lock, PyInstaller specs, updater implementation, packaging code, and toolchain recipe. Differences are restricted to explicit declarative channel/endpoint, trust profile, and profile identifier.

Mechanical evidence must compare extracted packaged inventories/module/resource hashes. Every non-allowlisted content hash must match. Unexpected difference fails the gate.

For first-generation 5.1.2 → 5.1.3-proof, baseline `NekoUpdater.exe` in proof must be byte-identical to production-candidate baseline `NekoUpdater.exe`. No proof-only helper or hidden runtime test switch is permitted in production.

Proof uses separate proof signing authority/channel and does not consume production seq9 or production signing authority.

## 10. Required forced-update proof

Packaged E2E must prove at least:

- offline baseline enrollment from embedded signed envelope;
- production/proof identity verification;
- baseline self-resolution `LATEST / NO UPDATE`;
- newer mandatory detection and mandatory formula;
- download/stage;
- signature, size, hash, and installed-identity checks;
- durable `UPDATE_PENDING`;
- active-game defer/no forced termination;
- safe apply, helper handoff, restart/relaunch;
- probation/self-test and generation commit;
- broken-candidate rollback;
- committed/high-water semantics after rollback;
- same-sequence exact no-op;
- same-sequence conflicting binding fail-closed;
- lower-than-high-water rejection;
- crash/restart recovery across mutation boundaries;
- offline apply of already verified pending;
- discovery outage while safely committed.

Unit/mocked tests support but do not replace packaged E2E evidence.

## 11. Core verifier requirement

`installer/scripts/verify-core-install.ps1` must consume the real Core manifest schema where `files` is an array of objects containing `path`, `size`, and `sha256` (not a property map). It must fail closed for unknown/malformed schema and verify exact declared inventory, source authority, pinned v2ray identity, protected settings, and plaintext-secret/key prohibitions.

The exact final Installer payload must run the verifier with exit code 0 before qualification.

## 12. Security constraints

- No credential-restoring curl shim.
- No secret-redaction bypass.
- No private signing-key output/readout in worker/reviewer logs.
- No token printed or passed in visible subprocess argv.
- No signature bypass.
- No hidden proof/test switch in production binary.
- Hermes implementers/reviewers must not possess production private signing key material.
- Production signing is a controlled boundary; tooling should exchange canonical payload/digests and signed envelopes without exposing private key bytes.

## 13. Canonical v5.1.2 tag authority

Current historical `v5.1.2` tag cannot silently become final authority if the approved source SHA changes.

Worker/implementer/reviewer must never force-move/delete/recreate the canonical tag. Exact tag mutation is an Owner-approved controller operation.

Before repository retirement:

1. establish approved final source SHA;
2. G15 captures current tag and validates the intended mutation without mutation;
3. G16 obtains Owner approval for the exact tag mutation;
4. G17 executes only that authorized tag action;
5. live-read and peel the tag as needed;
6. require `refs/tags/v5.1.2^{commit} == approved final source SHA`.

Failure blocks retirement/Human Release.

## 14. Historical Installer repository retirement — Owner final disposition

Owner decision is final: `Valeneko-pranmong/Neko-Family-Proxy-Installer` is to be retired and the **entire repository deleted**, not merely archived or stripped of releases. Do not ask preserve-vs-delete again.

Deletion remains conditional on the gates below; any new blocker stops execution.

### 14.1 Complete forensic scope

Capture a deterministic complete inventory, including:

- repository numeric ID and node_id;
- exact owner/name;
- visibility/state;
- default branch and exact default-head SHA;
- created/updated metadata;
- ALL releases (including draft/prerelease metadata exposed by API);
- ALL custom assets of ALL releases;
- ALL tag refs and peeled commits;
- branch-head refs included in the forensic scope;
- release target_commitish and resolved commit identity.

Canonical deterministic inventories produce repository/release/asset/ref digests plus one complete forensic inventory SHA-256.

### 14.2 Exact broken v5.1.2 asset custody

Custody the exact bytes of historical broken `NekoFamilyProxy-Installer.exe` outside the retiring repository and bind repository ID/node_id, release ID/tag, asset ID/name, size, SHA-256, capture timestamp, custody identifier/path, and known-broken evidence.

Historical expected identity to cross-check (not to trust without rereading bytes):

```text
size   = 212293271
sha256 = e069aa2b268d134ca16d038bef58c176d237e01201e638c63e07f5832803e3f7
```

Unavailable bytes or unexplained hash mismatch blocks retirement.

### 14.3 Dependency-audit snapshot

Audit source/runtime, config, package/build metadata, CI/workflows, installer/release scripts, release controller/publisher, production-capable fixtures, docs, hard-coded URLs, split owner/repo constants, and generated configuration for operational dependency on the retiring repo.

The audit result must bind the exact approved source/config/tooling/docs snapshot and produce input/result digests. Historical references are allowed only if explicitly non-runtime/non-production and not consumed by tooling.

Before DELETE, controller recaptures the current dependency-input snapshot. Any change yields:

```text
RETIREMENT_BLOCKED / DEPENDENCY_AUDIT_STALE
```

and requires re-audit + superseding release-audit-ledger entry.

### 14.4 Replacement readiness

Before the final retirement-evidence record:

- `Neko-Family-Proxy` is ready as source + Human Release destination;
- `Neko-Family-Proxy-Updates` is ready as production machine channel;
- machine baseline is live and self-resolution passes;
- deletion will not break fresh install, updater discovery, release/build tooling, or normal-user docs.

### 14.5 G14f semantics

The durable Project Release-Audit Ledger event is named `RETIREMENT_EVIDENCE_READY` (or equivalent `RETIREMENT_PRECONDITIONS_RECORDED`). It records evidence only. It is **not DELETE authorization** and must never be treated as a reusable capability token.

DELETE authority exists only when G19 fresh checks pass in the current controller execution session.

### 14.6 Fresh pre-delete forensic comparison

Immediately before DELETE, controller fresh-captures immutable repository identity plus the complete release/asset/ref inventory and recomputes the same canonical digests. All must match the ledger-approved forensic snapshot.

Any delta yields:

```text
RETIREMENT_BLOCKED / FORENSIC_STATE_CHANGED
```

The controller stops, explains the delta, recaptures, updates custody/audits as needed, appends a superseding ledger record, and repeats fresh checks. Existing evidence entries are append-only and not overwritten.

Exact owner/name + repository numeric ID + node_id must all match the forensic target. Name/URL is never a fallback for immutable-ID mismatch.

### 14.7 Controller-only deletion

Actual repository deletion is a Project Controller-only destructive operation. Never delegate DELETE to Hermes implementer, Hermes reviewer, coding worker, or generic release worker.

G19 current-session freshness authorization must be followed by G20 DELETE without unrelated state-changing work in between. If session/state becomes stale, rerun G18/G19.

### 14.8 Post-delete verification and result custody

After DELETE, fresh-read GitHub and prove the old repository/release/tag/asset namespace can no longer act as public authority and production source/config/tooling/docs have zero operational dependency.

If verification cannot be completed, Human Release remains blocked.

After post-delete verification passes, append/read-back a durable Project Release-Audit Ledger event:

```text
INSTALLER_REPOSITORY_DELETED
result = VERIFIED_DELETED
```

including immutable target identity, pre-delete evidence/inventory digests, dependency/replacement digests, delete execution timestamp/result, and post-delete verification digests.

Human Release remains blocked until this result event is durably read back.

## 15. Mutation-free Human preflight and draft publication

G15 is strictly mutation-free with respect to the final Human GitHub Release. Before old-repo deletion it may prepare notes/hash/size/expected asset set/API payload locally, capture the current canonical tag, and validate the intended tag mutation. It must not create even a draft Human Release or upload the final asset.

Only after G22 deletion-result ledger readback may G23 begin:

```text
create canonical v5.1.2 as draft/non-public
→ upload exact qualified NekoFamilyProxy-Installer.exe
→ live-validate while still draft:
   tag/source, draft=true, prerelease=false,
   approved bilingual body,
   exact one-asset set,
   remote asset size + SHA-256 == qualified local Installer
→ if validation fails: STOP, do not publish
→ if validation passes: set draft=false
→ fresh public live-readback
```

Malformed/incorrect draft must never be promoted and “publish then fix” is forbidden.

## 16. Retirement/Human promotion gate chain

```text
G14a complete forensic capture
G14b exact broken-installer external custody
G14c dependency audit PASS bound to exact snapshot
G14d replacement readiness PASS
G14e construct final retirement evidence package
G14f append/read-back RETIREMENT_EVIDENCE_READY (evidence only)
G15 mutation-free Human preflight + current-tag/intended-mutation validation
G16 Owner approval for exact canonical v5.1.2 tag mutation
G17 execute exact authorized tag action + live exact-SHA readback
G18 controller fresh-captures complete retiring-repo state + dependency-input snapshot
G19 current-session DELETE authorization: immutable identity + inventory equality + audit freshness + tag/custody/ledger checks
G20 controller-only DELETE entire historical Installer repository
G21 post-delete live verification + zero operational dependency
G22 append/read-back INSTALLER_REPOSITORY_DELETED / VERIFIED_DELETED
G23 create draft Human v5.1.2 → upload exact Installer → validate draft → publish only on PASS → final public readback
G24 production v5.1.3 requires separate explicit Owner authorization
```

## 17. Human Release final readback

G23 passes only when the public live state proves:

- main canonical repository;
- release/tag/name `v5.1.2`;
- tag resolves approved final source SHA;
- exactly one custom asset `NekoFamilyProxy-Installer.exe`;
- remote asset size/SHA-256 equals qualified Installer;
- approved bilingual v5.1.0-style body and migration notice;
- machine assets absent;
- historical Installer repository remains unavailable as public authority.

## 18. Promotion gates before retirement

Before G14, source/build/proof gates must already demonstrate:

- source correctness/security and Production Updates endpoint split;
- production local identity from authenticated committed state;
- Core verifier schema fix;
- secret-safe release tooling;
- proof/production mechanical equivalence;
- fresh final component set and production-signed baseline;
- final Installer embedding exact signed envelope;
- verifier exit 0, clean-install/offline enrollment/uninstall-reinstall/manual v5.1.0→v5.1.2 migration qualification;
- full packaged 5.1.2→isolated 5.1.3-proof E2E;
- independent review Critical 0 / Important 0;
- Production Updates publication + live-readback + production candidate self-resolution `LATEST / NO UPDATE`.

## 19. Worker/controller boundary

Implementation and review workers may implement/test tooling with fakes/dry-runs, but must not perform production signing, create/delete public repositories, move the canonical tag, create final GitHub Releases, upload production assets, or delete the historical Installer repository.

Public/destructive release execution remains with the Project Controller under the explicit gates above.
