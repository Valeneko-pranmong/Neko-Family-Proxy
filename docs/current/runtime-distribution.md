# NekoProxyCore runtime distribution

**Status:** Current policy — reviewed 8 August 2026. Production runtime startup
remains blocked by the `NEKO-AUTH-S0` release gates.

`NekoProxyCore` is a separately licensed runtime and is never committed to this
repository or published in GitHub release artifacts. An approved local
distribution build may embed the runtime into a one-file launcher; the runtime
must still be delivered through the team's access-controlled channel.

## Controlled delivery contract

1. Store the approved runtime archive in the team's access-controlled delivery
   channel.
2. Publish a SHA-256 checksum and runtime version alongside the archive.
3. Verify the checksum before extraction.
4. For a separate-runtime installation, extract the approved runtime to:

   `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe`

5. Keep customer data, Supabase secret/service-role keys, and private signing
   keys out of the archive.
6. Revoke and replace the archive immediately if its checksum, licensing
   status, or provenance cannot be verified.

The current launcher resolves a bundled runtime first and then the local path
above. It does not implement an environment-variable path override. The public
release pipeline builds only the launcher and fails if a tracked `ProxyCore`
file is detected.

Embedding or installing the runtime does not bypass the fail-closed production
authorization gateway.
