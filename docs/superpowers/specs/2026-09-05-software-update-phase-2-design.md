# Neko Family Proxy 5.1 — Software Update Phase 2 Design

**Date:** 2026-09-05
**Status:** OWNER DESIGN APPROVED / SPEC REVIEW PENDING
**Branch:** `release/5.1`
**Baseline:** `e39551bcba9790eb861633109e754d03d242e1c4` / `5.1.0a1`
**Primary owner:** TEAM_LAUNCHER
**Dependencies:** TEAM_WEB / Control Room distribution metadata; TEAM_CORE read-only installed identity only

## 1. Purpose

Phase 2 adds the trust and distribution layer for Neko Family software updates. It detects a newer compatible release set, authenticates the release metadata with Ed25519, prevents downgrade/replay, determines which Launcher/Core components differ from the locally admitted release, and provides safe primitives for artifact grant/download verification.

Phase 2 **does not replace installed files**. `NekoUpdater.exe`, atomic activation, backup/restore, post-update self-test, crash recovery, and customer installation UX remain Phase 3/4 work.

This design specializes the already approved `Project manager/specs/2026-09-04-live-runtime-config-and-software-update-design.md` for the active 5.1 branch. Runtime Config v1 remains a separate trust channel and is unchanged.

## 2. Scope and non-goals

### In scope

- immutable signed release-set schema;
- exact signed-envelope format;
- Ed25519 verification with an embedded public-key allow-list;
- monotonic `release_sequence` anti-downgrade policy;
- `minimum_supported_sequence` and `mandatory` policy evaluation;
- Launcher/Core component identity comparison;
- artifact byte-size and SHA-256 verification primitives;
- HTTPS manifest client with strict size/time limits;
- provider-neutral artifact-grant abstraction;
- one automatic update check per Launcher process startup;
- an application-level explicit manual-check command;
- safe update states and diagnostics;
- Owner/build signing tool contract using custody-provided private key material;
- tests for tampering, downgrade, malformed data, and secret separation.

### Explicitly out of scope

- installing or activating downloaded files;
- overwriting a running Launcher;
- replacing the Core directory;
- `NekoUpdater.exe` implementation;
- backup/rollback/self-test state machine;
- binary delta/bsdiff;
- continuous update polling;
- multi-channel rollout beyond the existing beta channel;
- automatic production publication from Git commits/CI;
- any Runtime Config host/port/cipher/credential field in update metadata;
- changing production Runtime Config v2 or `issue_launch_permit` v4.

## 3. Architectural boundary

The update path is independent from launch authorization and Runtime Config:

```text
Owner/build authority
    |
    | canonical payload bytes + Ed25519 signature
    v
Control Room update metadata endpoint
    |
    | signed envelope (no proxy credential)
    v
Launcher UpdateManifestGateway
    |
    v
ReleaseManifestVerifier
    |
    +--> signature / schema / channel / sequence policy
    +--> component installed-identity comparison
    |
    v
UpdateCheckService
    |
    +--> LATEST
    +--> AVAILABLE
    +--> MANDATORY
    +--> UNAVAILABLE / VERIFY_FAILED

Artifact id from an accepted signed manifest
    |
    v
ArtifactGrantGateway -> HTTPS object storage
    |
    v
ArtifactVerifier (size + SHA-256)

No Phase-2 path activates or installs the verified artifact.
```

The UI must not perform network, signature, hash, or policy work. Application services own policy; infrastructure adapters own HTTP/crypto/filesystem details; bootstrap composition wires them together.

## 4. Signed envelope and canonical payload

To avoid cross-language JSON re-serialization ambiguity, the signature covers the **exact payload bytes delivered by the envelope**. The client does not recreate canonical JSON before signature verification.

Envelope schema:

```json
{
  "envelope_version": 1,
  "key_id": "neko-update-ed25519-1",
  "payload_b64": "<base64 UTF-8 canonical JSON bytes>",
  "signature_b64": "<base64 64-byte Ed25519 signature>"
}
```

Build/signing tooling creates canonical payload bytes with UTF-8 JSON using sorted keys, no insignificant whitespace, and stable separators, then signs those exact bytes. Launcher processing order is:

1. parse only the small outer envelope;
2. validate envelope version, key id, base64 bounds and signature length;
3. select the embedded public verification key by exact `key_id`;
4. verify Ed25519 over decoded `payload_b64` bytes;
5. only after signature success, parse the payload JSON;
6. validate the signed release-set schema and policy.

Unknown key IDs fail closed. Key IDs use `[A-Za-z0-9._-]{1,64}`. The repository test key id is exactly `neko-update-test-1`; it is accepted only by test-injected registries. The production key id is reserved as `neko-update-prod-1`. A production build must contain the Owner-approved public key for that id before any production manifest can be published; if no production public key is provisioned, production update verification remains fail-closed. Production private signing material is never committed, bundled, logged, exported to Project Manager, or accepted from a manifest.

The outer HTTP body is capped at 65,536 bytes and decoded `payload_b64` at 49,152 bytes. Base64 decoding is strict; the Ed25519 signature must decode to exactly 64 bytes and a registered public key to exactly 32 bytes.

The initial implementation will use Python `cryptography` Ed25519 support. `cryptography` must be an explicit Launcher dependency rather than relying on a transitive dependency.

## 5. Release-set payload

Signed payload schema v1:

```json
{
  "schema_version": 1,
  "channel": "beta",
  "release_sequence": 2,
  "release_id": "beta-0002",
  "mandatory": false,
  "minimum_supported_sequence": 1,
  "components": {
    "launcher": {
      "version": "5.1.0a2",
      "artifact_id": "launcher-win-x64-beta-0002",
      "artifact_sha256": "<64 lowercase hex>",
      "artifact_size": 30000000,
      "installed_identity_sha256": "<64 lowercase hex>"
    },
    "core": {
      "version": "core-0002",
      "artifact_id": "core-win-x64-beta-0002",
      "artifact_sha256": "<64 lowercase hex>",
      "artifact_size": 370000000,
      "installed_identity_sha256": "<64 lowercase hex>"
    }
  }
}
```

Validation rules:

- exact `schema_version == 1` and `channel == "beta"`;
- integer `release_sequence` in `1..9223372036854775807`;
- `release_id` matching `[A-Za-z0-9._-]{1,64}`;
- boolean `mandatory`;
- integer `minimum_supported_sequence` in `1..release_sequence`;
- exactly the allow-listed component names `launcher` and `core` for schema v1;
- component `version` matching `[A-Za-z0-9._+-]{1,64}`;
- `artifact_id` matching `[A-Za-z0-9._-]{1,96}`;
- lowercase 64-hex SHA-256 strings;
- Launcher `artifact_size` in `1..134217728` bytes (128 MiB);
- Core `artifact_size` in `1..1073741824` bytes (1 GiB);
- no unknown secret-bearing fields or runtime-proxy fields.

The schema is strict: unknown top-level/component fields are rejected in v1 so a typo cannot silently change policy.

## 6. Local admitted release identity

Unpublished development/test builds use local `release_sequence = 0` and `release_id = "dev-unpublished"`; sequence 0 is never valid in a signed remote manifest and is never published as a release-set identity. The first publicly distributed update-capable 5.1 build establishes the published software-update sequence domain at **sequence 1**. `release_sequence` is independent from semantic Launcher version and Runtime Config `config_version`.

Local identity contains only safe metadata:

```text
release_sequence
release_id
launcher version
launcher installed identity SHA-256
core version/identity label
core installed identity SHA-256
```

For Launcher, installed identity is the admitted packaged executable SHA-256. For Core, installed identity is the cryptographic identity of the admitted Core release inventory/canonical manifest, not the ZIP/package byte hash.

The signed manifest therefore carries both:

- `artifact_sha256` / `artifact_size` — verifies downloaded package bytes;
- `installed_identity_sha256` — compares the signed release component to the locally admitted installed component.

This distinction is required for the multi-file Core bundle, whose archive hash is not the same as its installed directory identity.

The current 5.0 stable client is not retroactively self-updatable; it predates the Phase-2 trust client. The first publicly distributed 5.1 update-capable build is the bootstrap installation for this sequence domain and is assigned sequence 1 during the Owner-controlled release process.

## 7. Anti-downgrade and update decision

After signature and schema validation:

- remote sequence `< local sequence` -> `VERIFY_FAILED/DOWNGRADE_REJECTED`;
- remote sequence `== local sequence` -> only accepted as `LATEST` if the signed installed identities match the local admitted identities; conflicting identities at the same sequence fail closed;
- remote sequence `> local sequence` -> candidate update;
- if local sequence `< minimum_supported_sequence`, the decision is `MANDATORY`;
- otherwise a newer candidate is `AVAILABLE` unless manifest `mandatory == true`, in which case it is `MANDATORY`.

Component selection is identity-based. A component is marked changed only when its signed `installed_identity_sha256` differs from the corresponding locally admitted identity. Phase 2 can therefore prove that a future downloader need not fetch unchanged components.

No manifest can lower the locally admitted sequence. Persisting/committing a newly installed sequence belongs to Phase 3 after atomic activation and health acceptance.

## 8. Manifest and artifact distribution contract

### Manifest endpoint

Control Room exposes this public, non-secret metadata endpoint:

```text
GET /api/software-update/manifest?channel=beta
```

The endpoint returns only the signed envelope for the active immutable release set, or a typed no-release response. It never returns Proxy runtime credentials, permits, service-role material, private signing material, or arbitrary storage paths.

Launcher client requirements:

- HTTPS only;
- redirects are rejected for the manifest endpoint;
- request timeout is 5.0 seconds;
- maximum response body is 65,536 bytes;
- strict JSON/content validation;
- no token/query-secret logging;
- no retry loop beyond the explicit startup/manual invocation.

The Ed25519 signature, not HTTPS or Vercel, is the release integrity authority.

### Artifact grant abstraction

Application code depends on `ArtifactGrantGateway(artifact_id)` rather than a storage-provider URL. The initial Control Room contract is:

```text
POST /api/software-update/artifact-grant
Content-Type: application/json

{ "artifact_id": "launcher-win-x64-beta-0002" }

200 -> { "url": "https://...", "expires_at": "<RFC3339 UTC>" }
```

The route is public because update discovery occurs before login and software artifacts contain no live Proxy secret. It accepts only an artifact id present in the active immutable release record, rejects unknown fields/ids, rejects non-POST methods, returns HTTPS only, rejects redirects at the Launcher grant client, uses a 5.0-second client timeout, and caps the JSON response body at 16,384 bytes. The server may implement the returned URL as a public immutable object URL or a short-lived signed URL; provider choice is not part of the signed manifest schema.

An artifact grant is transport authorization only. It cannot change component hash, size, release sequence, install identity, component type, or destination.

Signed URL query values are treated as sensitive operational data and must not be written to support/debug logs.

## 9. Artifact verification primitive

Phase 2 provides a streaming verifier for an artifact already downloaded to the product-controlled update staging area or supplied by a test fixture. It:

1. checks the exact byte length against signed `artifact_size`;
2. computes SHA-256 while streaming;
3. compares to signed `artifact_sha256` using exact normalized hex;
4. returns safe verified component metadata only after both checks pass.

A mismatch rejects/quarantines the staged candidate while leaving the current installation untouched. Phase 2 does not activate the file.

The verifier enforces the signed-schema maximums before/while streaming: 128 MiB for Launcher artifacts and 1 GiB for Core artifacts. These limits are constants covered by tests and can change only in a reviewed future software release.

## 10. Launcher check lifecycle

`UpdateCheckService` supports two invocation reasons:

- `STARTUP` — at most once per Launcher process;
- `MANUAL` — one explicit caller action per request.

Startup check is asynchronous and must not block Tk startup, login/session restoration, public proxy-status one-shot behavior, or an already-authorized active game session.

Phase-2 application states:

```text
NOT_CHECKED
CHECKING
LATEST
AVAILABLE
MANDATORY
UNAVAILABLE
VERIFY_FAILED
```

Safe `UpdateCheckResult` metadata is limited to: state, invocation reason, release id, release sequence, tuple of changed component names, component version labels, mandatory flag, and one allow-listed diagnostic code. It must never include raw envelope bytes, signatures, artifact grant URLs, JWTs, permits, Runtime Config envelopes, or Proxy credentials.

Phase 2 exposes a manual-check application command; the customer-facing button/presentation polish remains Phase 4 so trust logic is not coupled to a specific UI layout.

A `MANDATORY` result records policy state but Phase 2 does not yet perform installation. The later Phase-3/4 integration will enforce START blocking only after the install path is available and acceptance-tested; Phase 2 must not create a dead-end mandatory block with no updater.

## 11. Failure semantics

- manifest network unavailable -> `UNAVAILABLE`; current admitted software remains usable; no rapid retry;
- malformed envelope/base64/schema -> `VERIFY_FAILED`;
- unknown key/signature mismatch -> `VERIFY_FAILED` security diagnostic;
- downgrade/same-sequence identity conflict -> `VERIFY_FAILED`;
- artifact size/hash mismatch -> reject staged artifact; current installation untouched;
- unsupported channel/schema/component -> fail closed;
- manual check failure does not mutate startup single-flight state;
- no failure path falls back to unsigned GitHub "latest release" metadata or legacy Netch updater behavior.

Diagnostics are closed, sanitized codes. Raw signed payloads, grant URLs and secrets are excluded from retained logs.

## 12. Signing tool boundary

Owner/build tooling is separate from Launcher runtime code. The signer:

- accepts a validated release-set input;
- canonicalizes it once;
- loads an Ed25519 private key only from Owner/build custody at invocation time;
- signs exact payload bytes;
- emits the public signed envelope and safe fingerprints/metadata;
- refuses to overwrite an existing immutable release id/artifact id in publication workflows;
- never writes or prints the production private key.

Repository tests may contain a test-only private key fixture under a test key id that cannot be mistaken for the production key id. Production publication remains an explicit Owner release action and is not performed by ordinary CI.

## 13. Component responsibilities

### TEAM_LAUNCHER

- release/update domain models and strict schema validation;
- signature/sequence/identity policy;
- artifact verification primitive;
- update check application service/ports;
- manifest/grant infrastructure clients;
- bootstrap one-shot composition;
- safe diagnostics and tests.

### TEAM_WEB / Control Room

- immutable active release metadata source;
- signed-envelope response route;
- artifact-id allow-list/grant abstraction;
- no software-update endpoint may expose Runtime Config authority or secrets.

### TEAM_CORE

No new updater behavior in Phase 2. Core contributes only its existing admitted installed identity. Core package replacement remains Phase 3.

## 14. Implementation slices

### Slice 1 — Trust Core

- release-set/envelope models;
- exact validation;
- explicit `cryptography` dependency;
- embedded verification-key registry;
- Ed25519 verifier;
- anti-downgrade/update-decision policy;
- local release identity model;
- artifact size/SHA verification primitive;
- test-only signing fixture/tool helpers.

### Slice 2 — Distribution Contract

- HTTPS manifest gateway;
- safe bounded response handling;
- artifact-grant port and initial control-plane route/service;
- provider-neutral immutable artifact mapping;
- negative route/security tests proving no Runtime Config/secret coupling.

### Slice 3 — Launcher Integration

- startup single-flight `UpdateCheckService` wiring;
- explicit manual-check application command;
- safe state/diagnostic integration;
- concurrency/error isolation from existing startup/session/proxy-status flows;
- full regression suite.

Phase 3 may begin only after all three slices are green and Phase 2 is checkpointed.

## 15. Test and acceptance matrix

Minimum Phase-2 automated acceptance:

- valid test-key signed envelope accepted;
- one-bit payload modification rejected;
- invalid signature rejected;
- unknown key id rejected;
- malformed/oversized base64 rejected;
- wrong schema/channel rejected;
- unknown fields/components rejected;
- downgrade rejected;
- same sequence + identity mismatch rejected;
- same sequence + identical identities -> latest;
- newer optional release -> available;
- mandatory/minimum-supported policy -> mandatory decision;
- changed component selection is identity-based;
- exact artifact size/hash accepted;
- wrong size rejected;
- wrong SHA rejected;
- oversized artifact rejected;
- manifest endpoint timeout/bad status/oversized body handled safely;
- only one automatic check per Launcher process;
- manual check remains separately invokable;
- update failure does not break login/session restoration/public proxy-status/game lifecycle;
- raw envelope/signature/grant URL/token/permit/Runtime Config/Proxy credential sentinel absent from support/debug/update logs/state;
- production signing private key absent from repo/client/build outputs;
- full existing Launcher suite and repository-safety checks remain green.

Phase-2 completion means a 5.1 Launcher can safely decide and authenticate update availability and verify candidate artifact bytes **without installing them**.

## 16. Release and safety gates

- No production manifest publication during implementation without a separate explicit Owner release action.
- No object-storage production promotion merely because tests pass.
- No merge of Draft PR #5 until the 5.1 acceptance/release gates are complete.
- Phase 2 must not mutate Runtime Config production state.
- Any product-affecting manual-test binary after `5.1.0a1` gets a new prerelease version read from source and deliberately bumped; never reuse the same version for materially different binaries.
- Phase 3 starts only from an accepted Phase-2 checkpoint.
