# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
