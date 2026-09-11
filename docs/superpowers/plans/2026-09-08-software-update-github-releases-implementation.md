# Software Update via GitHub Releases — Implementation Plan

> For agentic workers: execute one task at a time with Superpowers executing-plans or subagent-driven-development. Before every Hermes dispatch, inspect active `--oneshot` processes and `E:\Github\Project manager\TASK_REGISTRY.md` plus session history. One objective has one active worker; reuse the completed Sol High audit and completed reviews rather than rerunning them.

**Goal:** Replace only Software Update discovery/transport with a fixed GitHub Releases stable channel while retaining signed release-v2 authority and the existing local updater transaction, generation, self-test, activation, and rollback system.

**Architecture:** The Launcher reads the latest published non-draft/non-prerelease release from fixed repository `Valeneko-pranmong/Neko-Family-Proxy`, downloads fixed `release-v2.json`, binds fixed Launcher/Updater/Core assets from that same typed release, and downloads product bytes through a manual bounded HTTPS redirect client. Signed sizes/SHA-256 and release sequence remain authoritative. Admin grants, Supabase Software Update storage, and the distribution capability are removed from client composition. Other Admin/Supabase features remain untouched.

**Tech stack:** Python 3.11/3.12, urllib, dataclasses, pytest 8.3.5, Ruff 0.11.2, PyInstaller 6.21.0, GitHub Actions PowerShell and `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-09-08-software-update-github-releases-design.md` (Owner design approved in chat; final independent design/plan re-review APPROVED Critical 0 / Important 0; implementation not started; Gate #2 and Gate #3 remain NOT PASSED; production signing and final publication remain Owner notification boundaries).

## Global execution rules

- Start from `release/5.1` baseline `10825bfe3b65fd67ba68524b35d31079db870054`; preserve unrelated work and re-read HEAD/status before implementation.
- Backend product implementation, TDD tests, deterministic verification, and workflow engineering are the authorized current next phase under Owner delegation. They do not authorize production signing, any real GitHub release mutation/publication, deployment, merge, or push.
- TDD per task: tests-only change, collected assertion-level RED, minimal GREEN, focused tests, relevant full tests, Ruff, `git diff --check`, narrow review at Critical/Important only. Missing-module collection errors are not accepted RED; use dynamic import or failing behavior assertions where a new module is planned.
- No production signing key use, production manifest, tag, release creation/upload/publication, deployment, Supabase mutation, Vercel mutation, Admin runtime mutation, merge, or push unless separately authorized.
- Keep the fixed repository/channel/constants non-configurable. Do not add a hidden environment override.
- Do not change existing updater state, broker, generation, Core inventory, activation, self-test, or rollback semantics unless a focused regression proves a necessary adapter defect.
- Do not delete historical specs/plans. Mark them superseded in current documentation only.
- Use no placeholder tokens or invented expected counts. Record actual test totals from authoritative summaries during execution.
- Dependency order is `Task 1 → Task 3 → Task 2 → Tasks 4–8`: the shared bounded MANIFEST/PRODUCT transport must exist before `GitHubReleaseResolver` reaches GREEN. Task numbers group concerns; this explicit dependency order controls execution.

## Task 1 — Typed GitHub latest-release discovery

**Files**

- Create: `launcher/src/neko_launcher/infrastructure/github_release.py`
- Create: `launcher/tests/test_github_release.py`

**Interfaces**

```python
GITHUB_RELEASE_OWNER = "Valeneko-pranmong"
GITHUB_RELEASE_REPOSITORY = "Neko-Family-Proxy"
GITHUB_RELEASE_API_URL = (
    "https://api.github.com/repos/Valeneko-pranmong/"
    "Neko-Family-Proxy/releases/latest"
)

@dataclass(frozen=True)
class GitHubReleaseAsset:
    id: int
    name: str
    size: int
    browser_download_url: str

@dataclass(frozen=True)
class GitHubRelease:
    id: int
    tag_name: str
    draft: bool
    prerelease: bool
    assets: tuple[GitHubReleaseAsset, ...]

class GitHubReleaseDiscoveryError(ValueError):
    code: str

class GitHubLatestReleaseGateway:
    def __init__(self, timeout: float = 5.0) -> None: ...
    def fetch(self) -> GitHubRelease | None: ...

def parse_github_release(document: object) -> GitHubRelease: ...
```

Closed safe discovery codes: `GITHUB_RELEASE_UNAVAILABLE`, `GITHUB_RELEASE_RESPONSE_INVALID`, `GITHUB_RELEASE_INELIGIBLE`.

**Behavior**

- API request is exact fixed URL, GET, default HTTPS port, no redirect, maximum 262,144 bytes, no auth/cookies, fixed `Accept`, `User-Agent`, and `X-GitHub-Api-Version` headers.
- HTTP 404 returns `None`; all other non-200/network/timeouts return unavailable.
- Strict UTF-8 JSON uses duplicate-key rejection. Parse required typed subset while ignoring unrelated GitHub fields.
- Reject bool-as-int, non-positive IDs, invalid tag grammar, draft/prerelease true, asset count outside 1..64, duplicate IDs, exact/case-folded names, invalid names/sizes/URLs, and source-archive fields as candidates.
- Asset initial URLs must be `https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/...` with no userinfo, fragment, or non-default port.

**TDD**

1. Add parser/gateway tests using fake bounded responses and a no-redirect opener. Include valid unknown fields, duplicate JSON keys, malformed types, oversized body, 404, rate limit, timeout, API redirect, wrong repository URL, duplicate assets, and draft/prerelease.
2. Run RED:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_github_release.py -q
```

Expected RED: collected assertions fail because the GitHub release API/interfaces do not exist; zero collection errors.
3. Implement the minimum module with a private no-redirect opener and bounded reader.
4. Run GREEN and lint:

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_github_release.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/infrastructure/github_release.py tests/test_github_release.py
```

5. Review only discovery correctness/privacy at Critical/Important; do not review hostile-local races.

**Boundary:** No apply/download/composition/workflow changes in Task 1.

## Task 2 — Signed same-release binding and Updater compatibility

**Files**

- Create: `launcher/src/neko_launcher/infrastructure/github_release_binding.py`
- Create: `launcher/tests/test_github_release_binding.py`
- Modify: `launcher/src/neko_launcher/updater/manifest_v2.py`
- Modify: `launcher/src/neko_launcher/updater/slot_selector.py`
- Modify: `launcher/tests/updater/test_slot_selector.py`
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_v2.py`
- Modify: `launcher/src/neko_launcher/application/software_update_models.py`
- Modify: `launcher/tests/updater/test_manifest_v2.py`
- Modify: `launcher/tests/test_software_update_v2_adapter.py`
- Modify: `launcher/tests/software_update_helpers.py`
- Modify: `scripts/build_software_release_v2.py`
- Modify: `launcher/tests/test_build_software_release_v2.py`

**Interfaces**

```python
RELEASE_MANIFEST_ASSET_NAME = "release-v2.json"
LAUNCHER_ASSET_NAME = "NekoLauncher.exe"
UPDATER_ASSET_NAME = "NekoUpdater.exe"
CORE_ASSET_NAME = "NekoProxyCore.zip"

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

Create `GitHubReleaseResolver` in `github_release_binding.py` rather than a stateful verifier split across call sites. It owns discovery → exact manifest selection → bounded MANIFEST acquisition → envelope verification → same-release binding → v2 adapter conversion → installed Updater identity/protocol compatibility. It hashes only fixed `install_root / "NekoUpdater.exe"`; `updater_protocol` is supplied from one authoritative constant shared with updater IPC, replacing the private `_HELPER_PROTOCOL_VERSION` duplicate in `software_update_v2.py`.

For new admission, migrate `parse_release_v2()` from exact two components to exact `{launcher, updater, core}` and channel from `beta` to `stable`. Updater uses `raw-pe-v1`, maximum 128 MiB, and requires artifact SHA-256 equal installed-identity SHA-256, matching Launcher raw-PE identity rules. Core keeps `zip-core-v1` and its inventory installed identity. Legacy two-component remote payloads fail closed.

Add one deliberately named compatibility interface in `manifest_v2.py`, `verify_legacy_recovery_envelope_v2(envelope, key_registry)` (internally using an exact `parse_legacy_recovery_release_v2` schema). It must preserve canonical outer-envelope parsing by the caller, exact Ed25519 verification, payload hash/release identity, and `release_sequence`; it accepts only the prior exact `{launcher, core}` schema. Wire it only in `slot_selector.py` for authenticated evidence belonging to an already committed generation. Do not use it from resolver/discovery/check, `staging_handoff.py` BEGIN or APPLY, `broker.py`, `enrollment.py`, adapters/builders, or transaction creation. Those paths continue through `verify_release_envelope_v2()` and the exact-three new parser. Do not infer or synthesize an Updater descriptor for legacy evidence.

Update `build_software_release_v2.py` to require `updater_artifact: Path | str` and CLI `--updater-artifact`. It must bind hashes/sizes for all three artifacts, validate the exact three-component stable payload before signing, sign with only an explicitly supplied key file, verify with the separately supplied public key, then re-read and re-hash all three files before exclusive output creation. Engineering tests generate ephemeral Ed25519 authority and must never default to or silently use production signing.

Closed resolver codes: `GITHUB_RELEASE_UNAVAILABLE`, `RELEASE_MANIFEST_REJECTED`, `UPDATER_INCOMPATIBLE`.

**Behavior**

- Envelope bytes come only from the exact same-release manifest asset through the bounded MANIFEST operation. Before resolver availability, require `canonical_json_loads(exact_bytes)` (strict UTF-8, duplicate-key rejection, and `canonical_json_dumps(document) == exact_bytes`), then exact-byte Ed25519 verification and exact-three parsing. Preserve and return those same bytes unchanged.
- Require signed channel `stable`, GitHub tag `v{signed launcher.version}`, and exactly one of each four required client assets. Extra release assets are ignored, never rejected merely for being extra, and never trusted.
- Require all three signed product artifact IDs/formats and compare GitHub API sizes to signed sizes only for Launcher/Updater/Core. GitHub size for the manifest is not signed authority.
- Installed Updater hash and the one authoritative protocol constant must satisfy the signed descriptor before either check returns availability or apply starts. Do not download/self-replace Updater.
- Reject legacy two-component remote payloads in every resolver/check/BEGIN/apply/new-transaction path. The sole compatibility path is `slot_selector.py` reading already committed authenticated state evidence; do not rewrite durable history or weaken signature/sequence checks.

**TDD**

1. Add tests for stable exact-three parsing; updater raw-PE format/size/identity rules; old two-component rejection; wrong tag/channel; missing/duplicate/cross-release required assets; accepted ignored extra asset; wrong product ID/format/size; forged envelope; missing/unreadable/wrong installed helper; protocol mismatch; and valid resolution.
2. Add a real recovery regression in `tests/updater/test_slot_selector.py`: construct/sign a canonical legacy exact-two `{launcher, core}` envelope and durable committed-generation evidence using existing state/slot fixtures, then prove post-migration slot selection succeeds and preserves signature, payload hash/release identity, and `release_sequence` checks. Feed the exact same envelope bytes to `GitHubReleaseResolver` and to staging-handoff BEGIN/new transaction tests and prove rejection before availability/apply. Add source/import guards proving the legacy verifier name appears only in `manifest_v2.py`, `slot_selector.py`, and its focused tests—not resolver, check, apply, staging handoff, broker, enrollment, adapter, or builder.
3. Add builder tests first for required `--updater-artifact`, exact three components, all-three identity binding and post-sign re-read, changed-during-build rejection for each component, stable-only payload, and ephemeral/test signing authority only.
4. RED:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_github_release_binding.py tests/updater/test_manifest_v2.py tests/updater/test_slot_selector.py tests/updater/test_staging_handoff.py tests/test_software_update_v2_adapter.py tests/test_build_software_release_v2.py -q
```

Expected RED: resolver, stable three-component schema, recovery-boundary, remote rejection, and Updater builder assertions fail with zero collection errors.
5. Implement minimal model/parser/adapter/resolver/builder changes and the slot-selector-only compatibility path without changing signature verification order or sequence policy.
6. GREEN/lint:

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_github_release_binding.py tests/updater/test_manifest_v2.py tests/updater/test_slot_selector.py tests/updater/test_staging_handoff.py tests/test_software_update_v2_adapter.py tests/test_build_software_release_v2.py tests/test_software_update_policy.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/application/software_update_models.py src/neko_launcher/infrastructure/github_release_binding.py src/neko_launcher/infrastructure/software_update_v2.py src/neko_launcher/updater/manifest_v2.py src/neko_launcher/updater/slot_selector.py tests/test_github_release_binding.py tests/updater/test_manifest_v2.py tests/updater/test_slot_selector.py tests/updater/test_staging_handoff.py tests/test_software_update_v2_adapter.py tests/software_update_helpers.py tests/test_build_software_release_v2.py ../scripts/build_software_release_v2.py
```

7. Review signature-before-interpretation, exact-three new admission, slot-selector-only legacy recovery, helper compatibility, and anti-downgrade only.

**Boundary:** No HTTP product downloader or production composition change.

## Task 3 — Bounded manual GitHub manifest and product redirect downloads

**Files**

- Create: `launcher/src/neko_launcher/infrastructure/github_asset_downloader.py`
- Create: `launcher/tests/test_github_asset_downloader.py`
- Modify: `launcher/tests/test_software_update_privacy.py`

**Interfaces**

```python
MANIFEST_MAX_BYTES = 65_536

@dataclass(frozen=True)
class DownloadedManifest:
    exact_bytes: bytes
    document: object
    actual_size: int

@dataclass(frozen=True)
class DownloadedArtifact:
    size: int
    sha256: str

class GitHubAssetDownloadError(ValueError):
    code: str

class GitHubManifestDownloader:
    def __init__(
        self,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        maximum_redirects: int = 5,
    ) -> None: ...
    def download(self, asset: GitHubReleaseAsset) -> DownloadedManifest: ...

class GitHubAssetDownloader:
    def __init__(
        self,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        maximum_redirects: int = 5,
    ) -> None: ...

    def download(
        self,
        *,
        initial_url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
    ) -> DownloadedArtifact: ...
```

Closed codes: `DOWNLOAD_UNAVAILABLE`, `DOWNLOAD_REDIRECT_INVALID`, `MANIFEST_TOO_LARGE`, `MANIFEST_RESPONSE_INVALID`, `DOWNLOAD_SIZE_MISMATCH`, `DOWNLOAD_HASH_MISMATCH`, `DOWNLOAD_WRITE_FAILED`.

**Behavior**

- Share one private manual redirect/URL/header/privacy transport implementation between MANIFEST and PRODUCT operations; do not duplicate trust logic.
- MANIFEST accepts only an already-selected exact `release-v2.json` asset, performs no product destination write and takes no expected signed size/hash, reads at most 65,536 bytes plus one overrun byte, and requires EOF. Run `canonical_json_loads(exact_bytes)` so strict UTF-8, duplicate-key rejection, and `canonical_json_dumps(document) == exact_bytes` are all enforced before returning exact bytes/document. Noncanonical whitespace or key order is rejected even when semantically valid; never normalize or rewrite bytes. API-reported size is at most an untrusted optional consistency check and never authority.
- PRODUCT requires signed expected size/SHA-256 and is used only for Launcher/Core changed artifacts.
- Disable automatic redirects. Manually accept 301/302/303/307/308, at most five hops, detect loops, resolve relative `Location`, and validate every URL.
- Initial host/path is exact repository release-download path on `github.com`. Redirect hosts are exact `github.com`, `objects.githubusercontent.com`, or `release-assets.githubusercontent.com`; HTTPS/default port only; no userinfo/fragment.
- Every hop creates a fresh GET with fixed non-sensitive headers. No Authorization, Cookie, cookie jar, response-cookie replay, or caller header map.
- Do not log or expose query strings, `Location`, redirect chain, response headers, or URL-bearing exceptions.
- Destination parent must already be helper-created. Open destination with `xb`, stream in 1 MiB chunks, enforce signed maximum/exact size while hashing, require EOF, flush/close, verify lower-case SHA-256, and remove only incomplete destination on failure.
- Ignore `Content-Length`, ETag, Digest, and GitHub API size as final authority.

**TDD**

1. Add deterministic fake-transport tests shared across both modes for direct 200, every allowed redirect status, relative redirect, five hops, sixth hop, loop, missing/multiple/invalid Location, each denied host/scheme/port/userinfo/fragment, query-bearing allowed CDN URL without logging, and header/cookie non-forwarding. Add MANIFEST-specific exact-65,536 pass, 65,537 reject, no expected hash/size parameter, EOF, strict UTF-8, duplicate-key rejection, untrusted API-size mismatch, and exact canonical-byte preservation tests. Include a canonical envelope that passes and a byte-different noncanonical but semantically identical envelope (whitespace/key-order change) that is rejected rather than normalized. Add PRODUCT overrun/underrun/hash mismatch/timeout/write failure/exclusive-create collision tests.
2. Add privacy sentinels to ensure URL query/Location/cookie/auth values never appear in `repr`, exception string, or diagnostics sink.
3. RED:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_github_asset_downloader.py tests/test_software_update_privacy.py -q
```

4. Implement and run GREEN/lint:

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_github_asset_downloader.py tests/test_software_update_privacy.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/infrastructure/github_asset_downloader.py tests/test_github_asset_downloader.py tests/test_software_update_privacy.py
```

5. Review redirect allowlist, forwarding, bounds, and diagnostics at Critical/Important.

**Boundary:** No grant compatibility shim and no generic arbitrary-host downloader.

## Task 4 — Apply, check, composition, and config migration

**Files**

- Modify: `launcher/src/neko_launcher/application/software_update_service.py`
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_apply.py`
- Modify: `launcher/src/neko_launcher/updater/staging_handoff.py` only if test exposure is needed; do not change its exact-three verifier/canonical contract
- Modify: `launcher/tests/updater/test_staging_handoff.py`
- Modify: `launcher/src/neko_launcher/bootstrap/app_factory.py`
- Modify: `launcher/src/neko_launcher/infrastructure/config.py`
- Modify: `launcher/src/neko_launcher/infrastructure/defaults.py`
- Modify: `launcher/tests/test_software_update_service.py`
- Modify: `launcher/tests/test_software_update_apply.py`
- Modify: `launcher/tests/test_software_update_composition.py`
- Modify: `launcher/tests/test_config.py`
- Modify: `launcher/tests/ui/test_software_update_one_shot.py`

**Interfaces/composition**

Minimally replace the current `manifest_gateway.fetch() -> document` plus `verifier.verify(document) -> ReleaseSet` pair with one authenticated gateway. Do not retain an ad hoc or stateful verifier:

```python
class AuthenticatedReleaseGateway(Protocol):
    def resolve(self) -> ResolvedGitHubRelease | None: ...

class UpdateCheckService:
    def __init__(
        self,
        release_gateway: AuthenticatedReleaseGateway,
        local_identity_provider: Callable[[], LocalReleaseIdentity],
    ) -> None: ...

def SoftwareUpdateApplyService.__init__(
    self,
    root_dir: Path,
    release_gateway: AuthenticatedReleaseGateway,
    asset_downloader: GitHubAssetDownloader,
    spawner: Callable[..., subprocess.Popen[bytes]] | None = None,
    channel_factory: Callable[..., FramedIpcChannel] | None = None,
) -> None: ...
```

`app_factory.py` creates one `GitHubReleaseResolver` with `GitHubLatestReleaseGateway`, `GitHubManifestDownloader`, `PRODUCTION_RELEASE_PUBLIC_KEYS`, the fixed install root, and the one authoritative Updater IPC protocol constant; that same resolver instance/semantics is injected into check and apply. Resolver reads `root_dir / "NekoUpdater.exe"` SHA-256 itself. Apply receives no separate key registry/binder and cannot bypass/reforge resolver results.

- Remove `manifest_gateway`, separate verifier, `grant_gateway`, `distribution_capability_provider`, `DefaultDownloader`, `_validate_grant`, and `_download_and_verify` grant behavior from composition.
- Remove `software_update_api_url` and `SOFTWARE_UPDATE_API_URL` only. Preserve `supabase_url`, `supabase_publishable_key`, `account_recovery_api_url`, and `proxy_status_api_url` exactly.

**Behavior**

- Check: call resolver once, map `None`/closed resolver errors safely, then run existing update decision policy on `resolved.authenticated_release` while preserving startup single-flight/manual semantics.
- Apply: call the same resolver again. Only after successful resolution, send its exact downloaded canonical envelope bytes unchanged—no parse/dump normalization—to fixed-helper BEGIN, use helper `changed` response, and PRODUCT-download changed Launcher/Core assets selected from that resolved release only. Updater compatibility has already failed closed in the common resolver.
- Preserve fixed incoming paths, IPC, abort/release order, idle-only UI behavior, startup single-flight check, safe unavailable behavior, and all local updater logic.
- No grant request, capability read, Admin Software Update URL, Supabase object URL, fallback, auth header, or cookie.

**TDD**

1. Change tests first to prove the exact two-argument `UpdateCheckService(release_gateway, local_identity_provider)` contract, one resolver call per manual check, startup single-flight cache, same resolved model and binding/helper-compatibility decisions for check and apply, mandatory apply refetch, exact envelope-byte IPC handoff, changed-only PRODUCT downloads, metadata-only no product download, installed fixed-root Updater hash/protocol mismatch rejection on both paths, no separate verifier/binder in either consumer, no Admin/grant/capability calls, config field removal, and unrelated service constants unchanged. Add one cross-boundary regression using a canonical envelope: resolver returns the exact downloaded object bytes; apply sends byte-identical bytes; `staging_handoff` BEGIN accepts those same bytes. Its noncanonical-but-semantically-valid variant must make check unavailable/rejected and prove the helper spawner/channel/BEGIN is never invoked.
2. Add source-level guard assertion that `app_factory.py`, `software_update_apply.py`, and Software Update config contain none of `HttpArtifactGrantGateway`, `get_distribution_capability`, `/api/software-update`, or `software_update_api_url`.
3. RED:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_service.py tests/test_software_update_apply.py tests/test_software_update_composition.py tests/test_config.py tests/ui/test_software_update_one_shot.py -q
```

4. Implement minimal migration. Do not edit auth, Runtime Config, permits, account recovery, health/proxy status, Core process, updater broker, activation, or rollback.
5. GREEN/lint:

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_github_release.py tests/test_github_release_binding.py tests/test_github_asset_downloader.py tests/test_software_update_service.py tests/test_software_update_apply.py tests/test_software_update_composition.py tests/test_config.py tests/ui/test_software_update_one_shot.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/application/software_update_service.py src/neko_launcher/infrastructure/software_update_apply.py src/neko_launcher/bootstrap/app_factory.py src/neko_launcher/infrastructure/config.py src/neko_launcher/infrastructure/defaults.py tests/test_software_update_service.py tests/test_software_update_apply.py tests/test_software_update_composition.py tests/test_config.py tests/ui/test_software_update_one_shot.py
```

6. Review only cross-service isolation, same-release binding, no fallback, and preservation of local updater behavior.

**Boundary:** Keep the obsolete credential module until Task 5 so deletion has an explicit RED and repository scan.

## Task 5 — Remove obsolete distribution credential and grant client

**Files**

- Delete: `launcher/src/neko_launcher/infrastructure/distribution_credential.py`
- Delete: `launcher/tests/test_distribution_credential.py`
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_client.py`
- Modify: `launcher/tests/test_software_update_client.py`
- Modify: `launcher/tests/test_software_update_privacy.py`
- Modify: `scripts/check_repository_safety.py`
- Modify: `launcher/tests/test_repository_safety.py`

**Behavior**

- Remove `ArtifactGrant`, `HttpArtifactGrantGateway`, Core capability grammar/header handling, grant endpoint constants, and obsolete grant tests.
- Retain `software_update_client.py` only if another non-obsolete client remains after Task 4; otherwise delete the file and update imports/tests in the same task.
- Repository safety scans production source/workflow/current docs for obsolete Software Update authority strings: `NEKO-FAMILY/SoftwareUpdateDistribution/v1`, `NekoDistribution`, `/api/software-update/artifact-grant`, `SOFTWARE_UPDATE_ACTIVE_RELEASE_JSON`, Supabase Software Update bucket/object names, and Admin Software Update manifest route. Allow occurrences only in `docs/archive/**` and dated superseded `docs/superpowers/**` history.
- Add guards against `zipball_url`, `tarball_url`, `/archive/refs/`, `raw.githubusercontent.com`, and unsigned `SHA256SUMS.txt` consumption in Software Update code.
- Do not delete OS credentials or mutate Credential Manager in implementation. Obsolete credential cleanup means removing product code/tests/config and documenting optional manual cleanup; no runtime secret readback.

**TDD**

1. Add repository-safety assertions before deletion so they fail on current grant/capability source.
2. RED:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_repository_safety.py tests/test_software_update_client.py tests/test_software_update_privacy.py -q
```

3. Remove obsolete code/tests and update allowlisted historical paths only.
4. GREEN/lint/safety:

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_repository_safety.py tests/test_software_update_privacy.py -q
.venv\Scripts\ruff.exe check src tests scripts/check_repository_safety.py
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1
launcher\.venv\Scripts\python.exe -B scripts\check_repository_safety.py
```

5. Review for accidental removal of unrelated Supabase/Admin service code.

**Boundary:** No provider-side cleanup/deployment and no Credential Manager mutation.

## Task 6 — Release workflow: draft, complete upload, verify, publish last

**Files**

- Modify: `.github/workflows/release.yml`
- Modify: `launcher/tests/test_release_workflow_publication_gate.py`
- Create: `launcher/tests/test_release_workflow_github_assets.py`
- Create: `scripts/verify_github_release_assets.py`
- Create: `launcher/tests/test_verify_github_release_assets.py`
- Modify: `scripts/check_repository_safety.py`

**Workflow contract**

- Ordinary `build-installer` retains `contents: read` and cannot publish.
- Build/stage exact fixed names `NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`, and externally signed `release-v2.json`. The Core ZIP and signed manifest must come from explicit approved workflow inputs/artifact provenance; never build a fake/synthetic Core or sign with a repository secret silently.
- Publication job has `contents: write`, manual `workflow_dispatch`, explicit intended tag/target verification, and environment protection if configured.
- Under publication authorization, use this order: create draft release; upload the four required update assets with clobber disabled; run local signed verification; read back draft by release ID; prove each required name is present exactly once with a unique ID while ignoring permitted human-facing extras; bounded-read/verify the manifest; verify all three product sizes/SHA-256 and envelope signature/tag/sequence/binding; only then `gh release edit <tag> --draft=false`.
- Any failure leaves the release draft. No cleanup path publishes. No `push.tags` publication path and no `gh release create` without `--draft`.
- Final post-publication readback is a separate last verification step, not a substitute for pre-publication verification.
- This task implements logic/tests only when authorized; it must not execute the publication job.

**Verifier CLI**

```text
python scripts/verify_github_release_assets.py \
  --release-json <release.json> \
  --download-dir <directory> \
  --public-key-file <approved-public-key-file> \
  --expected-tag <v-version> \
  --expected-target <commit-sha> \
  --require-draft
```

The script imports existing release-v2 verification code, emits safe success/failure text only, and never accepts an unsigned checksum as authority.

**TDD**

1. Extend workflow static tests to assert permissions, trigger isolation, draft creation, each of the four required names exactly once, permitted extra human assets ignored, no-clobber upload, verifier before publish, publish as final state-changing step, and no source archives/fallback.
2. Add verifier tests with ephemeral in-memory signing keys and local files for valid required set with/without a human-facing extra, missing/duplicate required name, wrong tag/target/draft, size/hash mismatch, forged envelope, and wrong three-product binding.
3. RED:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_release_workflow_publication_gate.py tests/test_release_workflow_github_assets.py tests/test_verify_github_release_assets.py -q
```

4. Implement workflow and script without running release commands.
5. GREEN/lint/workflow syntax:

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_release_workflow_publication_gate.py tests/test_release_workflow_github_assets.py tests/test_verify_github_release_assets.py -q
.venv\Scripts\ruff.exe check tests/test_release_workflow_publication_gate.py tests/test_release_workflow_github_assets.py tests/test_verify_github_release_assets.py ..\scripts\verify_github_release_assets.py ..\scripts\check_repository_safety.py
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1
git diff --check -- .github/workflows/release.yml scripts/verify_github_release_assets.py launcher/tests
```

6. Validate YAML using the repository's existing workflow parser/test; do not install or invoke a release publisher for validation.
7. Review publication ordering, least privilege, asset completeness, and signing custody at Critical/Important.

**Boundary:** No real tag, draft, asset upload, or publication.

## Task 7 — Deterministic E2E simulation and optional disposable GitHub proof

**Files**

- Create: `launcher/tests/e2e/test_github_release_update_e2e.py`
- Modify: `launcher/tests/e2e/test_live_update_balanced_e2e.py`
- Modify: `launcher/tests/test_software_update_privacy.py`
- Create only if separately authorized: `scripts/prove_disposable_github_release.py`
- Create only with that script: `launcher/tests/test_prove_disposable_github_release.py`

**Mandatory local simulation**

- Use a local HTTP/TLS transport fake at the interface boundary, not Admin/Supabase and not a public network dependency.
- Create ephemeral Ed25519 test keys in memory, stable release N+1 typed JSON, fixed manifest/Launcher/Updater/Core assets, and manual redirect chain to an allowlisted-host transport fake.
- Exercise actual discovery parser, envelope verifier, binder, downloader, `SoftwareUpdateApplyService`, existing helper/broker/generation builder, Core inventory verifier, self-test/activation, and durable state.
- Prove N to N+1 commit, exact changed-only assets, high-water sequence, installed identities, restart, and no grant/capability/Admin/Supabase requests.
- Prove signed broken N+2 reaches candidate self-test/activation failure and automatically restores runnable N+1 while preserving sequence/failure floors.
- Failure matrix: GitHub unavailable, malformed release, wrong tag, missing/duplicate asset, redirect denial, overrun/underrun/hash mismatch, helper incompatibility, busy session. Old generation remains selected/runnable.
- Run recovery twice after convergence and assert second pass does not change selected authority.

**Optional disposable GitHub proof**

- Execute only under separate explicit authorization and only against a named disposable non-production repository owned for testing.
- Script must require repository, target commit, and confirmation flag; create a unique draft release, upload synthetic non-product files under fixed names, verify discovery/download redirect behavior, and delete the draft/tag in `finally` with readback.
- Never use production keys, Core, release sequence, product repository, or publish (`draft=false`). Never make this proof a prerequisite for deterministic CI.
- If no authorization/repository exists, record `NOT RUN / OPTIONAL`; this is not a blocker.

**TDD and verification**

1. Add mandatory E2E tests and run RED on old Admin/grant composition.
2. GREEN:

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher
set PYTHONDONTWRITEBYTECODE=1
set NEKO_FINAL_CORE_ARTIFACT_PATH=E:\Github\worktrees\NekoProxyCore-live-update\TestResults\task12\a43-core
.venv\Scripts\python.exe -B -m pytest tests/e2e/test_github_release_update_e2e.py tests/e2e/test_live_update_balanced_e2e.py -q
```

3. Full Launcher canonical gate:

```cmd
.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=no
.venv\Scripts\ruff.exe check src tests
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1
git diff --check
```

4. Build `NekoLauncher.exe` and `NekoUpdater.exe` only if the implementation execution authority includes a new candidate build; use a new prerelease identity and run existing packaged smoke. Do not overwrite accepted artifacts.
5. Independent final implementation review: Critical 0 / Important 0 against the new spec. Reuse completed architecture audit; do not rerun it.

**Boundary:** No production network proof, publication, or deployment.

## Offline three-component construction command

Engineering verification uses an ephemeral/test Ed25519 keypair and stable exact-three metadata; production signing authority must not be selected unless separately authorized:

Example engineering command after the test fixture has generated the listed ephemeral keypair and three artifacts:

```cmd
launcher\.venv\Scripts\python.exe scripts\build_software_release_v2.py --input TestResults\github-release-engineering\stable-release-metadata.json --launcher-artifact TestResults\github-release-engineering\NekoLauncher.exe --updater-artifact TestResults\github-release-engineering\NekoUpdater.exe --core-artifact TestResults\github-release-engineering\NekoProxyCore.zip --private-key-file TestResults\github-release-engineering\ephemeral-private.key --key-id ephemeral-release-test-1 --public-key-file TestResults\github-release-engineering\ephemeral-public.key --output TestResults\github-release-engineering\release-v2.json
```

## Task 8 — Documentation migration and historical supersession

**Files**

- Modify: `docs/current/runtime-distribution.md`
- Modify: `docs/current/README.md`
- Modify: `docs/README.md`
- Modify: `README.md` only if it currently states the obsolete Software Update distribution path
- Modify: `SECURITY.md` only if it currently states the obsolete Software Update distribution path
- Modify: `E:\Github\Project manager\CURRENT_STATUS.md`
- Modify: `E:\Github\Project manager\TASK_REGISTRY.md`
- Modify: `E:\Github\Project manager\E3_OPERATOR_HANDOFF.md`
- Modify: `E:\Github\Project manager\OWNER_GATE_2_PRODUCTION_PACKAGE.md`

**Behavior**

- Current repo docs say Software Update uses fixed GitHub Releases, stable-only latest published release, signed release-v2 authority, fixed product assets, public Core accepted, no fallback, and publish-last process.
- Historical Phase 2/Phase 3 specs/plans remain unchanged and are labelled superseded by current indexes/status, not rewritten as completed.
- Project Manager docs state the old Supabase private Storage/Admin grant/capability/Vercel Software Update E3 and Gate #2 requirements are `SUPERSEDED BY OWNER GITHUB-ONLY ARCHITECTURE DECISION`, not PASS. Preserve the historical blocker evidence.
- Gate #2 remains not passed until the replacement GitHub release package criteria are executed under separate authority. Gate #3 remains not passed.
- Explicit dedup rule: before every Hermes dispatch check active `--oneshot` processes, registry, and session history; one objective equals one active worker; wait/reuse matching active work and reuse completed audit/review sessions.
- State that unrelated Supabase/Admin services remain untouched.

**Verification**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-5.1
launcher\.venv\Scripts\python.exe -B scripts\check_repository_safety.py
git diff --check -- docs README.md SECURITY.md
cd /d E:\Github\Project manager
git diff --check -- CURRENT_STATUS.md TASK_REGISTRY.md E3_OPERATOR_HANDOFF.md OWNER_GATE_2_PRODUCTION_PACKAGE.md
```

If `E:\Github\Project manager` is not a Git repository, run the root repository diff check that owns those files; if untracked by Git, inspect exact changed files and report that limitation rather than claiming a Git check.

**Boundary:** Documentation does not claim implementation, production signing, draft creation, tag, upload, publication, Gate #2, Gate #3, or live auto-update completion.

## Final acceptance gate

After Tasks 1–8 implementation, but before any release action:

1. Confirm exact changed-file scope and no unrelated Admin/Supabase service changes.
2. Run focused GitHub discovery/binding/downloader/apply/workflow/E2E suites.
3. Run canonical full Launcher tests with the admitted Core fixture, authoritative test summary, full Ruff, repository safety, workflow tests, and `git diff --check`.
4. Build/smoke only under candidate-build authority; record exact version/hash/size without overwriting prior artifacts.
5. Independent review returns Critical 0 / Important 0.
6. Status may become `GITHUB_DISTRIBUTION_ENGINEERING_PASS / RELEASE_EXECUTION_NOT_AUTHORIZED`.
7. Stop. Production signing, tag creation, draft release creation, upload, publish, final release, merge, push, deployment, Supabase/Vercel mutation, and Admin runtime mutation remain separately controlled.
