# NekoProxyCore runtime distribution

**Status:** Feature branch architecture — updated 2026-09-12 for Neko Family 5.1.2 (Two-Repo Role Inversion & Deferred Update Lifecycle). Public production release remains v5.1.0 installer-only; no production backend or release mutation has occurred.

`NekoProxyCore` is a separately licensed external runtime. It is never committed as source to this repository or embedded inside the `NekoLauncher.exe` binary.

## Distribution Architecture (Production Updates & Canonical Main Separation)

Under the Neko Family 5.1.2 architecture (Revision 3.4), distribution responsibilities are separated into distinct repository roles:

1. **Machine-Update Channel (`Valeneko-pranmong/Neko-Family-Proxy-Updates`)**:
   - Production automated machine update channel for existing client installations.
   - Releases on this channel publish the four required signed machine assets:
     - `release-v2.json` (canonical Ed25519-signed manifest authority)
     - `NekoLauncher.exe` (client launcher binary)
     - `NekoUpdater.exe` (transactional updater engine)
     - `NekoProxyCore.zip` (frozen Core runtime bundle payload)
   - Machine updates stage `NekoProxyCore.zip` in the background into durable `UPDATE_PENDING` storage without interrupting active game or proxy sessions.
   - Handoff to `NekoUpdater.exe` occurs only during safe apply (explicit action, normal exit, or next launch).
   - Normal users must not be linked to the machine repository as a download surface.

2. **Human-Facing Installer Surface (`Valeneko-pranmong/Neko-Family-Proxy`)**:
   - The canonical main repository serves as the official human release and download surface.
   - Any historical plan for a separate installer repository is retired; human installer releases land directly on the main repository (`Valeneko-pranmong/Neko-Family-Proxy/releases`).
   - Distributes the standalone setup executable (`NekoFamilyProxy-Installer.exe`) for initial customer installation and manual upgrades.
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
