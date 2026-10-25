# NekoProxyCore runtime distribution

**Status:** Active — updated 2026-10-24 for the 5.2.0 release line. `v5.2.0` is the current source release line; `v5.1.6` remains the last published stable until 5.2.0 publication. Existing 5.1.6 clients must run the 5.2.0 installer manually because the release trust anchors were rotated.

`NekoProxyCore` is a separately licensed external runtime. It is never committed as source to this repository or embedded inside the `NekoLauncher.exe` binary.

## Distribution Architecture (Production Updates & Canonical Main Separation)

Under the active architecture, unified canonical releases are the only 5.x distribution surface:

1. **Canonical Machine-Update Channel (`Valeneko-pranmong/Neko-Family-Proxy`)**:
   - Production automated machine update channel for existing client installations.
   - Releases on this channel publish the unified signed assets:
     - `release-v2.json` (canonical Ed25519-signed manifest authority)
     - `NekoLauncher.exe` (client launcher binary)
     - `NekoUpdater.exe` (transactional updater engine)
     - `NekoProxyCore.zip` (frozen Core runtime bundle payload)
     - `NekoFamilyProxy-Installer.exe` (human-facing setup executable)
   - Machine updates stage `NekoProxyCore.zip` in the background into durable `UPDATE_PENDING` storage without interrupting active game or proxy sessions.
   - Handoff to `NekoUpdater.exe` occurs only during safe apply (explicit action, normal exit, or next launch).

2. **Human-Facing Download Surface**:
   - The canonical repository releases page (`Valeneko-pranmong/Neko-Family-Proxy/releases`) serves both automated updates and manual installer downloads.
   - The historical `Neko-Family-Proxy-Updates` repository identity is superseded and rejected by the updater trust profile.
   - The standalone setup executable (`NekoFamilyProxy-Installer.exe`) is required for initial installation and for the v5.1.6 → v5.2.0 trust-anchor rotation.
   - Post-install Core verification (`verify-core-install.ps1`) is dynamically parameterized by the build-approved `--core-authority` passed at compile time, eliminating stale hardcoded commit constants.

## Controlled Delivery and Verification Contract

1. **Approved Core Payload Packaging**: The Core bundle is delivered as `NekoProxyCore.zip`, matching the canonical Core bundle manifest (`core-manifest.json`).
2. **Cryptographic & Identity Verification**:
   - Machine update downloads verify byte size and SHA-256 strictly against the signed `release-v2.json` envelope before staging.
   - Core bundle extraction and installed-identity checks verify canonical files, hash trees, and manifest matching prior to transactional commit.
3. **Local Installed Path**:
   - Core runtime extracts to the external runtime directory:
     `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe`
4. **Offline & Durable Pending Staging**:
   - Staged payloads persist in `PendingUpdateStore` under `%LOCALAPPDATA%\NEKO FAMILY\update-pending\` and are fully re-verified on every load before promotion or apply.
5. **Bounded Bootstrap Authority Override**:
   - For the initial machine release following v5.1.0 (which was published installer-only without machine assets), the release controller resolves Core authority from the bounded, cryptographically verified Attempt-3 archived signed envelope.
   - This override is strictly single-use for `v5.1.0` bootstrap and is automatically disabled once a subsequent public machine release exists.
6. **Credential & Secret Isolation**:
   - The Core archive and release payloads contain no Supabase service-role keys, private signing keys, or user credentials.
   - Client runtime settings remain protected under `runtime-settings.nkps`.

Launcher resolves `NekoProxyCore.exe` strictly from the external runtime path above. It does not implement bundled-runtime or environment-variable path overrides. Embedding or installing the runtime does not bypass the fail-closed production authorization gateway.
