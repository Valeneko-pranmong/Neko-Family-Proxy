# NekoProxyCore runtime distribution

**Status:** Current policy — reviewed 8 August 2026. Production runtime startup
remains blocked by the `NEKO-AUTH-S0` release gates.

`NekoProxyCore` is a separately licensed external runtime. It is never committed
to this repository, published in GitHub Launcher release artifacts, or embedded
in Launcher EXE.

## Controlled delivery contract

1. Store the approved runtime archive in the team's access-controlled delivery
   channel.
2. Publish a SHA-256 checksum and runtime version alongside the archive.
3. Verify the checksum before extraction.
4. Replace external runtime directory with complete approved frozen bundle:

   `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe`

5. Keep customer data, Supabase secret/service-role keys, and private signing
   keys out of the archive.
6. Revoke and replace the archive immediately if its checksum, licensing
   status, or provenance cannot be verified.

Launcher resolves `NekoProxyCore.exe` only from the external runtime path above.
It does not implement bundled-runtime or environment-variable path override.
The Launcher EXE contains no Core runtime payload. Release uses protected
`runtime-settings.nkps`; standalone key and plaintext settings are not released.

Embedding or installing the runtime does not bypass the fail-closed production
authorization gateway.
