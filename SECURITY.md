# Security Policy

## Supported Versions

Only the latest stable release of Neko Family Proxy receives active security fixes and updates.

| Version | Supported          | Status |
| ------- | ------------------ | ------ |
| 5.1.0   | :white_check_mark: | Active production release (installer-only) |
| 5.1.2   | :white_check_mark: | Active feature branch (`feature/neko-family-5.1.2`) |
| 5.0.x   | :white_check_mark: | Legacy supported baseline |
| < 5.0   | :x:                | Unsupported |

## Security Architecture Principles

- **Fail-Closed Execution**: External Core startup and proxy activation fail closed unless authentication, single active launcher-session ownership, valid entitlement, exact target identity, and fresh challenge/permit authorization are cryptographically and policy verified.
- **Credential Separation**: The client launcher only ever contains publishable client configuration (such as Supabase URL and publishable anon key). Service-role keys, raw signing secrets, and elevated database administrative credentials are strictly forbidden in client distributions and repository sources.
- **Bound Authority**: Launch permits and session controls are bound to distinct, verified sessions to prevent permit replay and credential reuse.
- **Cryptographic Machine-Update Integrity**: Machine-update discovery strictly validates canonical Ed25519 signatures on `release-v2.json`. Staged update artifacts (`NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`) must match exact signed byte sizes, SHA-256 hashes, and canonical Core manifest identities before promotion or apply.
- **Offline Trust Reconstruction for Staged Payloads**: The durable `PendingUpdateStore` treats all on-disk staging as untrusted until cryptographically re-verified against the signed envelope and file hashes on every load. Downgrade attempts and same-sequence conflicts fail closed.
- **Bounded Bootstrap Override Security**: Initial machine-release bootstrap from `v5.1.0` is strictly restricted to the immutable signed Attempt-3 archive with full production Ed25519 signature, channel, size, hash, and installed identity verification. Arbitrary local fallback is rejected, and the override is disabled once a newer machine release exists.

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
