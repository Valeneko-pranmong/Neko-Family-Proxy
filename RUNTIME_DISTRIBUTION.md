# ProxyCore runtime distribution

`ProxyCore` is a separately licensed runtime and is never included in this
repository, the launcher executable, the installer, or GitHub release
artifacts.

## Controlled delivery contract

1. Store the approved runtime archive in the team's access-controlled delivery
   channel.
2. Publish a SHA-256 checksum and runtime version alongside the archive.
3. Verify the checksum before extraction.
4. Extract the approved runtime to:

   `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\ProxyCore.exe`

5. Keep customer data, Supabase secret/service-role keys, and private signing
   keys out of the archive.
6. Revoke and replace the archive immediately if its checksum, licensing
   status, or provenance cannot be verified.

Developers may override the location with `NEKO_PROXY_CORE_PATH`. The public
release pipeline builds only the launcher and installer and fails if a tracked
`ProxyCore` file is detected.
