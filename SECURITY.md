# Security & Privacy Policy

## Data Collection & Privacy Policy

**We do not collect any user data.**

Neko Family Proxy respects user privacy with a strict zero-telemetry policy:
- **No Telemetry or Tracking**: We do not collect, transmit, track, or store any usage statistics, analytics, or behavioral data.
- **No Traffic Monitoring**: We do not inspect, log, or store proxy traffic.
- **Strictly Operational Authentication**: Any data exchanged with our backend (Supabase) is strictly limited to cryptographic authentication, session validation, and entitlement checks required for operation. No personal tracking data is retained.

## Supported Versions

Only the latest stable release of Neko Family Proxy receives active security fixes and updates.

| Version | Supported          | Status |
| ------- | ------------------ | ------ |
| 5.2.0   | :white_check_mark: | Current release line; existing 5.1.6 users must install manually |
| 5.1.6   | :warning:          | Previous release; supported for migration only, no auto-update to 5.2.0 |
| 5.1.5 and earlier | :x:     | Superseded; upgrade to 5.2.0 |
| < 5.1.0 | :x:                | Unsupported |

## Security Architecture Principles

- **Fail-Closed Execution**: External Core startup and proxy activation fail closed unless authentication, single active launcher-session ownership, valid entitlement, exact target identity, and fresh challenge/permit authorization are cryptographically and policy verified.
- **Credential Separation**: The client launcher only ever contains publishable client configuration (such as Supabase URL and publishable anon key). Service-role keys, raw signing secrets, and elevated database administrative credentials are strictly forbidden in client distributions and repository sources.
- **Bound Authority**: Launch permits and session controls are bound to distinct, verified sessions to prevent permit replay and credential reuse.
- **Cryptographic Machine-Update Integrity**: Machine-update discovery strictly validates canonical Ed25519 signatures on `release-v2.json`. Staged update artifacts (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`) must match exact signed byte sizes, SHA-256 hashes, and canonical Core manifest identities before promotion or apply.
- **Trust-Anchor Rotation (v5.2.0)**: The v5.2.0 installer replaces the installed update trust profile with one signed by the current profile authority and authorizing only the `neko-update-prod-3` release key (rotated 2026-10-26 under `neko-update-profile-v520-2` because the prior custody material was unavailable). Historical public keys remain in the client for verification, but the installed profile does not authorize them for new releases. Because the prior custody material is unavailable, v5.1.6 clients cannot receive this rotation automatically; the signed installer must be run manually.
- **Offline Trust Reconstruction for Staged Payloads**: The durable `PendingUpdateStore` treats all on-disk staging as untrusted until cryptographically re-verified against the signed envelope and file hashes on every load. Downgrade attempts and same-sequence conflicts fail closed.

## Reporting a Vulnerability

We take the security and integrity of Neko Family Proxy and our users seriously. If you discover or suspect a security vulnerability, please do **NOT** open a public issue.

### Reporting Process

1. **Private Disclosure**: Please report vulnerabilities confidentially using GitHub Private Vulnerability Reporting on this repository if enabled, otherwise contact the repository owner/maintainers privately.
2. **Information to Include**:
   - Detailed description of the vulnerability and its potential impact.
   - Step-by-step instructions or minimal proof-of-concept to reproduce the behavior safely.
   - Component affected (e.g., Launcher Client, Runtime Config RPCs, Edge Functions).
   - Any proposed mitigations or remediation patches if available.
3. **Private Coordination**:
   - Reports will be reviewed privately and handled through direct coordination with the reporter.
   - Status updates will be provided as investigation and remediation progress through testing and verification.
4. **Coordinated Disclosure**:
   - We kindly request that you give us adequate time to investigate, remediate, and issue a release before publicly disclosing any details.
