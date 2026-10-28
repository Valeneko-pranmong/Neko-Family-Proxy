# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.2.3] - 2026-10-28 (re-released with the updater fix)

### Fixed
- Updater Core verification now accepts the frozen 5.2.0 Core authority manifest schema (`source_commit`, `file_count`, path-to-SHA-256 map) as well as the canonical `rid`/`executable`/`files[]` schema. The 5.2.2 updater rejected the frozen Core with `CORE_INVENTORY_INVALID`, so no in-app update could be applied.
- The updater artifact is pinned for the 5.2.x line so 5.2.3 installations can resolve and apply later releases.
- Discord sign-in no longer fails with "บัญชี Discord นี้ยังไม่ได้เชื่อมกับบัญชี Neko Family" when the identity has no proxy account; the first login provisions a pending account and the launcher displays zero days until a coupon is activated.
- Claim responses without an entitlement (`account_pending`, `license_inactive`, `license_expired`, `identity_not_linked`) are mapped to an empty entitlement instead of a failed sign-in.

### Added
- Proxy self-service sign-in: the launcher accepts a `pending` proxy account and shows zero days instead of failing when the Discord identity has no pre-linked account.
- Coupon redemption through `POST /v1/coupons/redeem` with an idempotency key; a successful redemption updates the displayed expiry and claims a session.

### Changed
- 5.2.3 is a manual clean-install migration: 5.2.2 cannot auto-update because the old updater is rejected before the fix can run. Future 5.2.x updates work after the one-time install.
- This re-release uses sequence 28 (`stable-0028`). The first 5.2.3 publication was withdrawn after the live update test failed with `CORE_INVENTORY_INVALID`.

## [Unreleased]

### Added
- Added always-on structured support diagnostics with machine/runtime context, manual-login and restore timing, sanitized API error metadata, background exception traces, and proxy/game/telemetry/update lifecycle events.
- Added the private `launcher_v2` schema foundation and next-line claim, heartbeat, release, permit, and rate-limit RPCs. These require a bridge-written `web_sessions` allowlist and an active identity link; the migrations are not applied to production.
- Added a reference `supabase/functions/launcher_bridge` that validates the identity RS256/JWKS token, consumes JTI, creates a no-password next-line user, mints a Supabase session, and records the web-session allowlist. It is not deployed.
- Added next-line schema selection: `NEKO_LAUNCHER_SCHEMA=launcher_v2` (default legacy `launcher`) for Launcher RPCs, and server-controlled `app_metadata.auth_line=next` selection in `issue_launch_permit`. Default behavior is unchanged.
- Blocked 5.2.x from non-prerelease stable publication until the preview channel and P4 gates are complete.
- Added preview-channel release-list discovery and prerelease acceptance for `preview` trust profiles; stable 5.1.6 discovery remains on `/releases/latest`.
- Added the signed `update-profile-preview-v1.json` (channel `preview`) and a reproducible profile-signing script; it authorizes only `neko-update-prod-2`.
- Completed the local preview path: release-v2 manifests accept `channel=preview`; 5.2.x release/installer builds require a preview profile and preview manifest; the resolver, pending-update store, publisher, hosted verifier, and stable-rollout workflow enforce the same binding so preview and stable updates cannot cross-load or promote.
- Re-versioned the 5.2 preview candidate as `5.2.0a1` for an alpha test. Alpha/PEP 440 versions are accepted by the release, publisher, verifier, and installer tooling while 5.2.x remains preview-only and blocked from stable publication. That intermediate version was superseded by the `5.2.2a` local alpha; no tag or publication exists.

### Fixed
- Claim responses without an entitlement (`account_pending`, `license_inactive`, `license_expired`, `identity_not_linked`) are mapped to an empty entitlement instead of a failed sign-in.

### Changed
- Startup keeps the update splash visible until session restore resolves (bounded by a force-close timeout) and now starts restore before building the window, so automatic sign-in no longer flashes the login screen first. Splash hold/close and startup restore time are recorded in the support log.
- Kept the login status row pinned at the top, vertically centered the remaining login content, and made the pending-login panel float without moving the controls.
- Settings now disables CustomTkinter's titlebar withdraw/re-map and reveals the first fully rendered frame in one paint.
- 2026-10-26: Rotated the update trust anchors to release key `neko-update-prod-3` and profile authority `neko-update-profile-v520-2` because the prior private custody material was unavailable. Rebuilt the frozen Launcher/Updater, re-signed the preview and stable profiles and the `preview-0015` envelope, and built the unsigned 5.2.0 preview installer. Corrected the post-install Core verifier to accept the Core authority's path-to-SHA-256 manifest map, and made uninstall remove updater release slots, launcher logs, and the credential-vault target. Silent install, reinstall, uninstall, and 5.1.6 rollback pass; interactive Discord login/Core start remains pending.
- 2026-10-25: **5.2.0 is designated the first usable release of the unified Proxy API line** (preview/manual channel, clean uninstall-first). `5.3.0` is not a release label. Release preparation is blocked on staging deployment/E2E, an approved `NEKO_PROXY_API_URL` origin, installer payload/prerequisites, signing, and the install matrix; see `docs/current/5.2.0-release-notes.md`, `docs/current/5.2.0-release-runbook.md`, and `docs/current/5.2.0-release-preparation-record.md`.
- 5.2.0 was planned as a separate bridge/web-auth preview line. That plan is superseded by the unified Proxy API line: 5.1.6 remains public stable, 5.2.0 is preview/manual and clean uninstall-first, and `5.3.0` is not a release label.
- Locked P0 decisions: isolated schema/RPC namespace in the existing Supabase project, dedicated preview channel, same AppId with a hard uninstall/process guard, clean-start uninstall, new-accounts-only 5.2.0, no legacy day/coupon transfer, Control Room admin-only web auth, gate-based sunset, and preview-only auto-updates. The shared-auth consumer audit is recorded; P0 is complete.

## [5.2.2a] - 2026-10-27

### Added
- Local alpha build (revision 6) of the 5.2.2 source-preparation changes: schema-2 support diagnostics, pinned-status login layout, one-frame Settings rendering, and a startup splash that waits for session restore.
- Release and installer tooling now accepts `5.x.ya` alpha versions while keeping 5.2.x on the preview channel.

### Changed
- Lifted the login content block 24 px so the pending panel has room below the help text and the card does not look top-heavy.
- Settings now pre-lays out every page at the full content-area size and switches sections by stacking, so pages appear fully rendered instead of collapsing/loading on each click.

### Fixed
- Restored the login card's bottom border and clamped the pending-login panel inside the card so it cannot be clipped or cover the border.
- Prevented stale update evidence from rejecting a third update; pruned evidence at begin/commit/abort/rollback and relaxed the authenticated-evidence subset check.
- Streamed large Core hashing and extended updater IPC deadlines so a 1 GiB Core update no longer exhausts RAM or fails after 5 s.
- Removed scratch/update directories and launcher backup files on uninstall; the installer now also rejects undeclared Core files and path-traversal entries.
- Hardened the elevated netfilter2 helper to hash and execute the same in-memory script bytes from an admin-owned stage, and to read the manifest once.
- Fixed worker-thread Tk access, event-pump shutdown, toast clearing by background polls, and tray Exit after a declined close.

### Build
- Launcher and Updater built with Python 3.12.10 / Tk 8.6 / PyInstaller 6.21.0.
- Signed envelope `preview-0023` (sequence 23, `minimum_supported_sequence = 23`, key `neko-update-prod-3`).
- Installer `NekoFamilyProxy-Installer.exe` 201,007,176 bytes, SHA-256 `1745856872d7b194daea3fc0b902c30b89f820f06c81ee600bc7d22871de4e5b`; unsigned and not published.
- Launcher `1837c270…` 21,629,808 bytes; Updater `c3411b95…` 11,281,237 bytes (Supabase/pydantic and Tcl/Tk removed from frozen builds).
- Fixed the elevated netfilter2 command quoting that made the driver step fail with `FAIL: invalid pinned nfdriver.sha256`; the installer was rebuilt and the source line is covered by a regression test.

## [5.2.1] - 2026-10-26

### Added
- Warm-up requests for the identity token, account preflight, and session-claim endpoints while the Discord browser step is in progress, reducing cold-start sign-in latency.
- Regression coverage for the 5.2.1 -> 5.2.2 mandatory-update path and for active-game update deferral without stopping the proxy.

### Changed
- Login now reads "ล็อคอินด้วย Neko Family Network ID", shows the Discord icon, and links the support text to the Neko Family Discord.
- The main window is fixed at 500x640; maximize and resize are disabled on every view.
- The Settings window is rendered off-screen and shown only after layout completes, so all text appears in one frame.
- The 5.2.1 release envelope uses `minimum_supported_sequence = 16`; later 5.2.x releases must use their own sequence so installed 5.2.1 clients are forced to update on the next launch.
- Uninstall now refuses to run while `NekoLauncher`, `NekoProxyCore`, or `NekoUpdater` is running, matching the install-time process guard.

### Upgrade
- 5.2.1 keeps the 5.2.0 external Core bundle and trust profile. The installer still requires a clean uninstall of 5.2.0 before installation; in-place and side-by-side installation remain unsupported.

## [5.2.0] - 2026-10-24

### Added
- Refreshed launcher, authentication, dashboard, and Settings presentation with the new rose/plum visual system; all existing flows and status semantics are preserved.
- Rotated the production release authority to `neko-update-prod-2` and the profile authority to `neko-update-profile-v520-1`; the signed v5.2.0 trust profile authorizes only the current release key.
- Added bilingual 5.2.0 release notes and a separation guide for existing 5.1.6 users.
- Added regression coverage for historical trust anchors, editable trusted-key registries, and 5.2.0 minor-release intent parsing.
- Added the Launcher-side Discord browser login flow with exact loopback callback, PKCE S256, state validation, identity token exchange, and bridge session adoption. It is hidden unless `NEKO_WEB_AUTH_ENABLED=1` and `NEKO_AUTH_BRIDGE_URL` are configured. At this checkpoint password login remained the fallback; the 2026-10-25 policy now requires removing it from 5.2.0.
- Added sanitized Core diagnostics for tolerated and exceeded permit clock skew.

### Security
- Upgraded Pillow from 12.2.0 to 13.0.0 to remediate known image-parsing CVEs.
- Pinned all GitHub Actions to full commit SHAs and disabled credential persistence in checkout steps.
- Pinned the Core manifest, `Redirector.bin`, and `nfdriver.sys` during elevated driver registration and load the verified redirector from an admin-only staging directory.
- Added a per-user 10-attempt/60-second rate limit to `issue_launch_permit`; exhausted requests receive HTTP 429 `RateLimited`.
- Removed personal operator and private-key paths from release tooling; staging, key, trust-profile, and bootstrapper paths are environment-configurable.
- Core telemetry and control named pipes are bound to the CurrentUserOnly ACL and the exact Launcher process ID.
- Core still enforces exact 2-second/30-second permit timing on a healthy clock, but tolerates up to 10 minutes of wall-clock disagreement only while a fresh one-use challenge remains the freshness authority; larger skew fails closed.
- Launcher web auth keeps the 5-minute identity token in memory only; the bridge-returned Supabase session is persisted through the existing Windows Credential Manager store.

### Changed
- Reduced the packaged Launcher from ~35 MB to ~27 MB by excluding unused Pillow plugins, the httpx CLI, rich/pygments, and interactive REPL modules.
- Disabled UPX in the Launcher build for deterministic output and fewer antivirus false positives.
- Self-sync now stages the committed executable in a verified temp file and replaces the running launcher with atomic renames plus rollback.
- Support logging keeps line-buffered file handles open instead of reopening three files for every line.
- The duplicate startup update-check callback is now one-shot; the manual check remains independent.
- The release intent parser now accepts a single patch increment or a `.0` minor release from the accepted source base; the installer version gate accepts stable 5.1.x and 5.2.x.

### Upgrade
- v5.1.6 remains public stable and must stay usable during 5.2.0 development. v5.2.0 is a separate web-auth-only preview and cannot auto-update 5.1.6 because the old installed trust profile authorizes only `neko-update-prod-1`, whose custody material is unavailable. A user who wants 5.2.0 must uninstall 5.1.6 first; in-place and side-by-side installation are not supported. There is no legacy day/coupon transfer; 5.1.6 remains usable until its existing term expires or an approved cutoff, and 5.3.0 is the planned legacy cutover.

## [5.1.6] - 2026-09-21

### Added
- Startup update-check splash window before entering the main program, with automatic apply when no game session is active.
- In-app update progress dialog and windowless updater helper.
- Committed-generation self-sync at launch.
- Version check in the Settings window.
- Baseline enrollment supports an install root taken from the working directory.

### Changed
- Update notifications and the apply action now reflect the verified pending update state consistently.

## [5.1.5] - 2026-09-20

### Added
- Native `ensure-netfilter2.cmd` dispatcher with `%SystemRoot%\Sysnative` detection so elevated driver registration runs under 64-bit PowerShell on all Windows versions.
- Inno Setup result-file polling guard to ensure driver registration completes before state verification.

## [5.1.4] - 2026-09-20

### Fixed
- 64-bit WOW64 redirection guard in the elevated driver installer (`PSExePath`) resolving `0x8007000B` on clean machine installs.
- Non-BOM ASCII logging in `ensure-netfilter2.ps1` to prevent Thai character corruption in installer dialogs.

## [5.1.3] - 2026-09-18

### Added
- Deferred update lifecycle from the 5.1.2 architecture: background staging, durable `UPDATE_PENDING` storage, session activity guard, and safe offline apply.
- Two-Repo Role Inversion: canonical main repository for human installer releases and a dedicated machine-update channel.
- Canonical Launcher title-bar version binding and dynamic installer authority propagation.
- Installed-file integrity verification and automated repair from Settings.
- Clean uninstaller and state cleanup on reinstallation.
- Machine installation credential provisioning during baseline enrollment.

### Changed
- Refined update notifications and settings-window focus management.

## [5.1.0] - 2026-09-11

### Added
- Runtime Config v1, single-active-session control, bound launch permits, and one-click installer packaging as the stable baseline.

## [5.0.0] - 2026-09-05

### Added
- **Production GA**: Official v5.0.0 stable release for Neko Family Proxy desktop launcher and backend services.
- **Runtime Config v1**: Owner-live accepted dynamic runtime proxy configuration system (`runtime_proxy_config_v1`).
- **Owner-Live Configuration Control**: Live publishing, validation, and coalescing RPCs (`fix_runtime_proxy_config_publish_coalesce`, ASCII character set validation) for real-time proxy endpoints.
- **NEKO-AUTH-LITE Production Hardening**: First-active-session and latest-claim-wins session arbitration with cryptographically bound launch permits.
- **Commercial UI/UX Finalization**: Design freeze including polished dashboard status indicators, Sarabun typography integration, and real-time connectivity telemetry.
- **Automated Repository Safety Gate**: Pre-flight verification scripts (`check_repository_safety.py`) preventing credential leaks and verifying test suites (878 passed, 3 skipped).

### Changed
- Replaced transitional launcher pre-release contracts (`5.0.0a9`) with final stable v5.0.0 architecture.
- Modularized architecture separating Launcher, external Core runtime, and Control Room management.
- Streamlined credential requirements: desktop client operates strictly with publishable anon tokens.

### Fixed
- Fixed runtime proxy configuration publish coalesce edge cases in database migrations.
- Fixed ASCII boundary and whitespace validation rules in runtime proxy endpoint configurations.
- Revoked obsolete coupon RPC access and reinforced search-path safety across database extensions.

## [5.0.0a9] - 2026-08-25

### Added
- Alpha testing milestone implementing existing-PSO2 reopen recovery and initial single-active-session locks.

## [Historical Releases]

- Pre-5.0 iterations and experimental migration history are archived under `docs/archive/`.
