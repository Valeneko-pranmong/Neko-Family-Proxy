# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- Upgraded Pillow from 12.2.0 to 13.0.0 to remediate known image-parsing CVEs.

### Changed
- Reduced the packaged Launcher from ~35 MB to ~27 MB by excluding unused Pillow plugins, the httpx CLI, rich/pygments, and interactive REPL modules.
- Disabled UPX in the Launcher build for deterministic output and fewer antivirus false positives.

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
