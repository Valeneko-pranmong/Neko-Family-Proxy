# Software Update via GitHub Releases — Design Specification

- Date: 2026-09-08
- Status: OWNER DESIGN APPROVED IN CHAT / FINAL INDEPENDENT RE-REVIEW APPROVED C0/I0 / IMPLEMENTATION NOT STARTED
- Review checkpoint: final independent design/plan re-review is APPROVED — Critical 0 / Important 0. The prior Critical 0 / Important 2 findings were corrected and accepted; this approval does not pass Gate #2 or Gate #3 and grants no production publication authority.
- Baseline: `release/5.1` at `10825bfe3b65fd67ba68524b35d31079db870054`
- Authority: Owner explicitly replaced the Software Update distribution architecture with GitHub Releases only. This is the design approval; no additional architecture gate is invented by this document.
- Design input: completed Sol High read-only audit and the Owner's GitHub-only decision.

> ### Prominent Supersession Note (2026-09-09)
> **NOTICE**: Publication-handoff and workflow-publication details in this specification (specifically Section 8 and related release construction/upload assumptions) are **superseded** by the approved two-phase staged-draft publication design:
> [`docs/superpowers/specs/2026-09-09-software-update-two-phase-staged-draft-design.md`](./2026-09-09-software-update-two-phase-staged-draft-design.md).
>
> All client-side GitHub Releases discovery, transport allowlists, redirect policies, Ed25519 envelope signature verification, canonical JSON enforcement, manifest admission, installed Updater compatibility binding, sequence anti-downgrade, generation construction, and local transaction semantics documented below remain active, authoritative, and unchanged.

## 1. Decision

Software Update discovery and artifact transport use one fixed public GitHub repository:

`Valeneko-pranmong/Neko-Family-Proxy`

Installed clients call GitHub REST for that repository's latest published release, obtain the fixed `release-v2.json` signed-envelope asset, verify it with the embedded Ed25519 trust registry, and download the exact Launcher and Core assets selected from that same release object. The same release also contains the exact Updater product asset used by installer/manual bootstrap compatibility checks. There is no Software Update request to Admin/Vercel and no Software Update object in Supabase Storage.

The signed release-v2 envelope remains the sole cryptographic release authority. GitHub fields, HTTPS, tags, release ordering, asset sizes, and asset URLs are untrusted discovery/transport metadata until checked against the signed envelope. Existing `release_sequence` anti-downgrade, complete-generation construction, local updater transaction, self-test, durable commit, failure suppression, and rollback behavior remain authoritative.

No fallback is allowed to Admin, Supabase, GitHub source archives, `tarball_url`, `zipball_url`, repository contents, raw URLs, latest tags, Actions artifacts, `SHA256SUMS.txt`, or any unsigned checksum.

## 2. Fixed release contract

### 2.1 Repository and REST endpoint

Production configuration contains owner `Valeneko-pranmong` and repository `Neko-Family-Proxy` as constants, not environment overrides. Discovery sends an unauthenticated request to:

`GET https://api.github.com/repos/Valeneko-pranmong/Neko-Family-Proxy/releases/latest`

Request headers are limited to GitHub's JSON media type, a fixed client `User-Agent`, and an API version header. It sends no bearer token, cookie, Supabase credential, distribution capability, JWT, permit, runtime configuration, or proxy credential.

A successful discovery response must be HTTP 200, bounded to 262,144 bytes, strict UTF-8 JSON, and parse to the typed subset below. Redirects are not followed for the API request. HTTP 404, rate limiting, timeout, malformed data, or any other status is update unavailable; the installed version continues.

Required release fields:

- `id`: positive JSON integer, not boolean;
- `tag_name`: ASCII string matching `v[A-Za-z0-9._+-]{1,64}`;
- `draft`: exactly `false`;
- `prerelease`: exactly `false`;
- `assets`: array of 1..64 typed assets.

Required asset fields:

- `id`: positive JSON integer, unique in the release;
- `name`: ASCII `[A-Za-z0-9._+-]{1,128}`, unique by exact and ASCII case-folded form;
- `size`: integer 1..1,073,741,824, not boolean;
- `browser_download_url`: HTTPS URL satisfying the initial GitHub URL policy.

Unknown GitHub response fields are ignored because GitHub owns and evolves the API schema. Required typed fields are not coerced. Duplicate JSON object keys are rejected before mapping construction.

### 2.2 Fixed asset names

The client consumes exactly four required update assets, each present exactly once in the same release:

- `release-v2.json` — signed Ed25519 envelope, maximum 65,536 bytes;
- `NekoLauncher.exe` — Launcher `raw-pe-v1` product artifact;
- `NekoUpdater.exe` — Updater `raw-pe-v1` compatibility/bootstrap product artifact;
- `NekoProxyCore.zip` — Core `zip-core-v1` product artifact.

A release may contain additional human-facing assets such as `SHA256SUMS.txt`. The client ignores every extra asset; extras never become a candidate, fallback, checksum authority, or trust input. Source archives generated by GitHub are not release assets and are never considered. Workflow verification proves that each of the four required names is unique and correctly bound, but does not require the entire release asset set to contain no extras.

The release-v2 signed payload has stable channel and exact closed component keys `{launcher, updater, core}`. Each descriptor carries `version`, `artifact_id`, `artifact_sha256`, `artifact_size`, `installed_identity_sha256`, and `artifact_format`. Their `artifact_id` values are respectively `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip`. Launcher and Updater use `raw-pe-v1`, each is at most 134,217,728 bytes, and each has `artifact_sha256 == installed_identity_sha256`; Core uses `zip-core-v1`, is at most 1,073,741,824 bytes, and retains its inventory-derived installed identity. The signed top-level `updater_protocol.minimum..maximum` range is checked against one authoritative installed Updater protocol constant shared with IPC. The initial implementation does not self-replace a running Updater. An incompatible installed Updater identity or protocol fails closed and requires a separately authenticated installer/manual bootstrap.

The manifest cannot use the product downloader because its signed size/hash are unknown until verification. It has a distinct MANIFEST download operation: select only the exact same-release `release-v2.json` asset, run the same manual HTTPS redirect allowlist, fixed headers, no-cookie/no-auth privacy policy, deadlines, five-hop limit, and safe diagnostics as product downloads, but read only into memory with a hard 65,536-byte maximum and no expected signed hash. Reject overrun immediately and require EOF. The GitHub API-reported size may be compared with the actual byte count as an untrusted consistency check, but it is never authority and must not be required as a pre-known signed value. The operation returns the exact downloaded bytes. Before a release can be returned available, MANIFEST admission must apply the existing canonical outer-envelope byte contract: strict UTF-8 and duplicate-key parsing followed by `canonical_json_dumps(document) == exact_bytes`, equivalently `canonical_json_loads(exact_bytes)`. Only that canonical document proceeds to exact envelope/signature verification. Noncanonical outer JSON is rejected even when semantically equivalent and correctly signed internally. The accepted downloaded bytes are retained unchanged; neither resolver nor apply normalizes, reserializes, or reconstructs them before BEGIN IPC.

PRODUCT artifact download is a separate operation used only for changed Launcher/Core bytes. It requires the exact signed `artifact_size` and `artifact_sha256`, streams to the fixed exclusive destination, and accepts only a complete exact match. The Updater release asset is bound for compatibility/provenance but is not downloaded or self-applied in this scope.

### 2.3 Release, tag, and asset binding

After envelope verification, all of these must hold:

1. `draft` and `prerelease` are false.
2. `tag_name` equals `v` plus the signed Launcher component `version` exactly.
3. Signed channel is `stable` for this initial policy.
4. Signed `artifact_id` for each product equals its fixed asset name.
5. Each fixed asset is found exactly once in the same `assets` array as `release-v2.json`.
6. GitHub asset `size` equals signed `artifact_size` before download for Launcher, Updater, and Core.
7. Downloaded product bytes equal signed size and SHA-256. Installed identities are then verified by the existing generation builder/verifier.
8. The helper's current installed identity and protocol satisfy the signed Updater descriptor before Launcher/Core apply. The Updater release asset is not silently substituted for the running helper.

Release ID, asset ID, upload timestamp, publication timestamp, release title/body, and GitHub's concept of “latest” are not cryptographic authority. They may be retained only as bounded non-secret diagnostics if needed; they do not enter anti-downgrade decisions. The signed `release_sequence`, signed release identity, signed component identities, and durable local high-water state decide admissibility.

A release that passes GitHub metadata checks but fails signature, binding, sequence, helper compatibility, size, hash, package, self-test, or local transaction checks is rejected without fallback.

## 3. Resolver contract and data flow

One small shared `GitHubReleaseResolver` owns all remote admission semantics; check and apply must not compose discovery, manifest download, verification, binding, or helper compatibility independently.

```python
@dataclass(frozen=True)
class DownloadedManifest:
    exact_bytes: bytes
    document: object
    actual_size: int

@dataclass(frozen=True)
class ResolvedGitHubRelease:
    authenticated_release: ReleaseSet
    authenticated_release_v2: ReleaseSetV2
    envelope_bytes: bytes
    envelope_document: object
    github_release: GitHubRelease
    manifest_asset: GitHubReleaseAsset
    launcher_asset: GitHubReleaseAsset
    updater_asset: GitHubReleaseAsset
    core_asset: GitHubReleaseAsset

class AuthenticatedReleaseGateway(Protocol):
    def resolve(self) -> ResolvedGitHubRelease | None: ...

class GitHubReleaseResolver:
    def __init__(
        self,
        *,
        release_gateway: GitHubLatestReleaseGateway,
        manifest_downloader: GitHubManifestDownloader,
        key_registry: Mapping[str, bytes],
        install_root: Path,
        updater_protocol: int,
    ) -> None: ...
    def resolve(self) -> ResolvedGitHubRelease | None: ...
```

`GitHubManifestDownloader.download(asset: GitHubReleaseAsset) -> DownloadedManifest` is the bounded in-memory MANIFEST operation from section 2.2. It preserves exact bytes and enforces the canonical outer-envelope byte contract with `canonical_json_loads(exact_bytes)` (strict UTF-8, duplicate-key rejection, and canonical reserialization equality); it does not accept expected size/hash arguments. `GitHubAssetDownloader.download(..., expected_size: int, expected_sha256: str) -> DownloadedArtifact` remains the separate PRODUCT file operation.

The resolver performs, in order: latest-release discovery; exact same-release manifest selection; bounded manifest acquisition with canonical outer-envelope admission; envelope Ed25519 verification; new-remote exact-three parser verification; stable channel/tag and exact required-asset binding; signed descriptor/format/size checks; conversion through the existing v2 adapter to `ReleaseSet`; SHA-256 of fixed `install_root / "NekoUpdater.exe"`; and comparison of that hash plus the constructor's single authoritative updater protocol constant against the signed Updater descriptor/range. It returns only after every step succeeds. Missing latest release returns `None`. Closed safe errors are `GITHUB_RELEASE_UNAVAILABLE` for transport/rate-limit/timeout, `RELEASE_MANIFEST_REJECTED` for malformed/oversized/signature/schema/binding failures, and `UPDATER_INCOMPATIBLE` for missing/unreadable/wrong installed helper or protocol mismatch; no exception text, URL, header, or body is exposed.

1. Startup/manual check calls `AuthenticatedReleaseGateway.resolve()` once and applies existing durable identity/sequence policy to `authenticated_release`.
2. User-approved idle apply calls the same resolver again; this mandatory refetch/reverification prevents stale check data from becoming apply authority.
3. Apply sends `envelope_bytes` from the resolved object through existing IPC without reconstructing or canonicalizing the downloaded envelope.
4. Apply downloads only helper-requested changed Launcher/Core assets from that resolved object's typed same-release bindings through the PRODUCT downloader and signed size/hash.
5. Existing broker, generation builder, Core ZIP/inventory verifier, probation/self-test, activation, durable state, and rollback complete or reject the transaction. Updater is compatibility-bound but not replaced.

GitHub is never consulted during local rollback or recovery.

## 4. Trust boundaries

Trusted release authority:

- embedded allowlisted Ed25519 public keys;
- exact signed release-v2 payload bytes;
- signed `release_sequence`, release identity, compatibility fields, product identities, sizes, hashes, and formats;
- validated local durable updater state and installed-generation verification.

Transport/discovery only:

- GitHub REST response and all GitHub metadata;
- GitHub release/tag ordering and `latest` selection;
- GitHub asset URLs, redirects, CDN responses, and TLS;
- optional human-facing checksums.

Separate and untouched authorities:

- Supabase authentication;
- Runtime Config and immutable config ledger;
- launch permits and Core authorization;
- account recovery;
- Admin health/proxy status.

Those services neither select update bytes nor approve release keys/sequences. Removing the Software Update Admin/Supabase path must not remove or alter unrelated service clients or deployments.

## 5. Redirect and download policy

All HTTP behavior is explicit and manual. Automatic redirect handlers are forbidden.

### 5.1 Initial URLs and allowlist

- API discovery origin: exactly `https://api.github.com`, default port only.
- Release asset initial origin: exactly `https://github.com`, default port only, path exactly under `/Valeneko-pranmong/Neko-Family-Proxy/releases/download/`; username, password, fragment, non-HTTPS, encoded host ambiguity, and non-default ports are rejected.
- Redirect targets: HTTPS/default-port only and hostname in the reviewed initial set:
  - `github.com`
  - `objects.githubusercontent.com`
  - `release-assets.githubusercontent.com`

Host matching is exact after lowercase IDNA-safe parsing; no suffix wildcard. Any future GitHub asset hostname requires a reviewed code change and tests.

### 5.2 Redirect execution

- At most five redirects.
- Accept only 301, 302, 303, 307, or 308 with one valid `Location` value.
- Resolve relative redirects against the current URL, then revalidate full scheme/host/port/userinfo/fragment policy at every hop.
- Detect repeated URLs/loops in memory.
- Each request is a new `GET` with only fixed non-sensitive headers. Never forward `Authorization`, `Cookie`, custom caller headers, or response cookies. No cookie jar is used.
- No URL query, `Location`, redirect chain, response header dump, or exception text containing a URL is logged. Diagnostics use closed codes and optional safe host classification only.
- Connect/read deadlines are finite; total redirects and bytes are bounded; no retry or resume in one invocation.
- MANIFEST mode reads only into memory, rejects beyond 65,536 bytes, requires EOF, returns exact bytes and strict duplicate-key-rejected UTF-8 JSON, and accepts no expected signed size/hash. An API-size mismatch may reject as untrusted inconsistency but never establishes authenticity.
- PRODUCT mode creates the fixed destination exclusively, streams while counting and hashing, rejects overrun immediately, requires exact signed size and EOF, flushes/closes, compares signed SHA-256, and deletes only that incomplete fixed destination on failure.

Only the PRODUCT operation has signed exact size and SHA-256 authority. For both modes, GitHub API size, `Content-Length`, ETag, Digest, and TLS never override envelope signature or signed product metadata.

## 6. Stable-only initial policy

The first GitHub-only implementation consumes only GitHub's `/releases/latest` response where `draft=false` and `prerelease=false`, and only a signed payload with channel `stable`. There is no beta channel query, prerelease opt-in, branch channel, rollout percentage, or user-configurable repository/channel.

Draft releases are preparation space and are invisible to installed clients. Prereleases are not eligible. Publishing a stable release is the activation event for discovery, but signature and local anti-downgrade checks still decide acceptance.

Future beta/prerelease support requires a separate reviewed design. It must not be approximated by falling back from stable discovery.

## 7. Compatibility and bridge

- Existing installed update-capable 5.1 clients currently point at the Admin Software Update API. The implementation release that switches discovery must be delivered through the approved main release/install flow or another separately authorized bridge. This design does not claim already-installed old clients can discover the new architecture before receiving bridge-capable code.
- Existing release-v2 cryptographic verification, durable state, sequence floors, generation construction, Core package/inventory verification, self-test, transaction, activation, and rollback are reused.
- The parser boundary is explicit and narrow. `parse_release_v2()` becomes the new-release parser and accepts only exact stable `{launcher, updater, core}` payloads. Add `parse_legacy_recovery_release_v2()` (or an equivalently explicit `STORED_RECOVERY_LEGACY` parse mode) for exact legacy `{launcher, core}` payloads. The legacy entry point is private to authenticated durable state-evidence recovery and must be called only by `updater/slot_selector.py` while selecting/verifying an already committed generation. It is not exported to or reachable from GitHub discovery, `GitHubReleaseResolver`, check, BEGIN/apply, release building, enrollment, staging handoff, broker publication verification, or any new transaction.
- Stored recovery still performs `canonical_json_loads(envelope_bytes)`, Ed25519 signature verification over the original signed payload, exact legacy schema parsing, payload/release identity binding, and existing `release_sequence`/state checks before a slot can be selected. Compatibility changes schema dispatch only; they do not accept unsigned evidence, relax canonical bytes, skip signature verification, synthesize an Updater descriptor, or weaken sequence/high-water/failure floors.
- The same byte-identical legacy two-component envelope that succeeds through the stored-recovery-only path must be rejected by `GitHubReleaseResolver` and therefore can never be returned available or begin a new transaction. All newly admitted GitHub releases and all BEGIN/apply transactions require exact stable three-component payloads.
- The stable helper does not self-update in the initial design. A release requiring a different helper identity/protocol is shown as requiring installer/manual update and cannot partially apply Launcher/Core.
- Existing sequence-zero development identity remains source/test behavior only. Production installed identity must continue to come from durable updater state.
- Owner's GitHub-only decision explicitly accepts public Core distribution. Historical `controlled-core`, private Storage, capability, grant, and anonymous-denial requirements are superseded for Software Update; they are not marked completed.

## 8. Release construction and publication order

The approved main release workflow must separate preparation from activation:

1. Build the exact Launcher, Updater, and Core product artifacts from the approved source/input authorities.
2. Compute their sizes, SHA-256 values, installed identities, formats, versions, and next authorized `release_sequence`.
3. Build and externally sign `release-v2.json`; verify it with the repository/client public key and re-verify all referenced local artifacts.
4. Create the GitHub Release as a draft for the exact intended tag/target commit. Tag creation/final tag policy remains separately authorized.
5. Upload all four fixed assets without clobbering an existing asset.
6. Read back the draft release by immutable release ID; verify draft/prerelease state and target/tag binding; prove each of the four required update assets is present exactly once with a unique asset ID; ignore permitted human-facing extras; bounded-download and verify the manifest; then verify all three product bytes against the signed envelope.
7. Run repository safety/privacy checks and optional disposable proof where authorized.
8. Publish the release last in one explicit job/step. Never publish first and fill assets later.
9. Read back `/releases/latest` and the final release only after publication authorization, then prove they resolve to the intended complete signed release.

This task authorizes documentation only. It does not authorize creating a tag, draft release, signing a production manifest, uploading assets, or publishing a release.

## 9. Failure behavior

- Discovery unavailable/rate-limited/malformed: show update unavailable for that check; Launcher, auth, and Proxy operation continue.
- No eligible stable release: current installation continues.
- Duplicate/missing/wrong-name assets, tag mismatch, prerelease/draft response, unsigned helper, or metadata disagreement: reject as manifest/release binding failure.
- Signature/key/schema/sequence conflict: fail closed using existing safe diagnostics; never try another distribution authority.
- Redirect/host/TLS/timeout/size/hash failure: abort preparation, remove only incomplete incoming file, preserve old committed generation.
- Updater identity/protocol mismatch: do not download/apply product updates; show installer/manual-update requirement.
- Busy game/Core session: preserve current idle-safe behavior; never interrupt an active session.
- Candidate package, self-test, activation, or restart failure: existing rollback restores the previous complete generation and preserves anti-downgrade/failure floors.
- GitHub outage never impairs local recovery, normal authentication, runtime configuration, launch permits, account recovery, or proxy health/status.

No raw URLs, query strings, redirect `Location`, response bodies, cookies, headers, signature bytes, tokens, capabilities, credentials, or upstream exception text enter support diagnostics.

## 10. User-visible behavior

- Startup performs the existing single-flight background check without blocking normal Launcher use.
- A stable newer authenticated release appears as the existing available/mandatory update state.
- “Update now” remains enabled only at an idle-safe point. Applying closes Launcher only after preparation succeeds and hands off to the existing Updater.
- Network or GitHub failures produce a sanitized retry-later message; they do not log the user out or prevent game/Proxy use.
- Helper incompatibility produces a clear installer/manual-update-required message rather than a partial update attempt.
- Successful update and rollback behavior remain as already designed; no new channel selector or advanced release UI is added.

## 11. Scope exclusions

This design does not:

- implement or deploy anything in this documentation task;
- create, push, or publish tags/releases/assets;
- use Supabase Storage, Admin Software Update routes, Vercel Software Update configuration, grants, or distribution capabilities;
- change unrelated Supabase/Admin services;
- add a fallback distribution source;
- trust GitHub source archives or unsigned checksums;
- add authentication to public GitHub downloads;
- add beta/prerelease channels, staged rollout, delta updates, resumable downloads, mirrors, or configurable repositories;
- self-update the running Updater;
- redesign existing local transactions, rollback, self-test, Core authorization, Runtime Config, permits, or UI;
- claim protection against a hostile local administrator/kernel or overengineer local races outside the accepted Balanced Security model.

## 12. Acceptance criteria

Implementation is acceptable only when all applicable criteria pass:

1. Production Software Update code contains no Admin/Vercel Software Update endpoint, artifact-grant call, Supabase Storage path, distribution capability read, or fallback.
2. Fixed GitHub repository and exact latest-release API are not environment/user configurable.
3. Typed discovery rejects non-200, redirects, oversized/malformed JSON, duplicate keys, draft/prerelease, duplicate required assets, invalid URLs, and out-of-range values; unrelated extra release assets are ignored.
4. The shared resolver is the only check/apply admission path. Its MANIFEST operation selects exact same-release `release-v2.json`, enforces 65,536 bytes without pre-known signed size/hash, requires canonical outer-envelope bytes via `canonical_json_loads`/exact reserialization equality, preserves those exact bytes, and rejects invalid UTF-8, duplicate keys, or noncanonical-but-semantically-valid JSON before availability.
5. Exact same-release binding proves tag, stable channel, exact `{launcher, updater, core}` schema, four unique required assets, signed product artifact IDs/formats/sizes, fixed-root installed Updater SHA-256, and one authoritative updater protocol constant before check availability or apply. No legacy two-component parser is reachable from remote admission or any new transaction.
6. Exact signed envelope verification occurs before trusting payload fields; existing `release_sequence` downgrade/conflict/failure suppression remains effective. A real legacy two-component stored-evidence fixture selects its already committed slot through the dedicated authenticated recovery path after migration, while the exact same envelope is rejected by `GitHubReleaseResolver` as a new candidate. Canonical manifest bytes returned by the resolver are byte-identical to those sent to and accepted by staging-handoff BEGIN; a noncanonical outer envelope is rejected during check and starts no apply.
7. Manual bounded redirect tests cover both MANIFEST and PRODUCT operations, every accepted status, relative redirects, five-hop maximum, sixth-hop/loop rejection, each disallowed host/scheme/port/userinfo/fragment, and header/cookie non-forwarding.
8. PRODUCT download tests prove overrun, underrun, wrong hash, timeout, malformed redirects, and write failure preserve the old install; exact signed bytes pass.
9. Existing updater broker/generation/Core inventory/probation/activation/rollback tests remain green. Genuine local E2E proves stable N to N+1 and signed broken N+2 rollback without Admin/Supabase dependencies.
10. Release workflow tests/static checks prove draft creation, unique correct binding of each of the four required assets while ignoring permitted extras, signed/local/readback verification, publish-last ordering, least privilege, and no tag/release publication from ordinary build jobs.
11. Repository safety/privacy scans reject credentials, capability targets/values, private endpoints, signed/query URL logging, source-archive fallback, accidental Core omission, and trust in extra assets.
12. Optional disposable GitHub proof, if separately authorized, uses a non-production repository/release, cleans it up, and is supplementary; deterministic local simulation is mandatory.
13. Current docs mark old Software Update Gate #2/E3 private-storage/Admin requirements superseded rather than passed, while preserving their history.
14. Full authoritative test summaries, Ruff, workflow validation, and `git diff --check` pass; independent review reports Critical 0 and Important 0.
15. No implementation completion permits production signing, tag creation, release upload, or publication without the separate release authority in force at that time.
