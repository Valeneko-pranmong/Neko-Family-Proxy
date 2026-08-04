# Launcher release candidate — 29 July 2026

> **HISTORICAL RELEASE EVIDENCE — NOT CURRENT.** Artifact hash, test counts,
> deployment IDs, and warnings below describe only the 29 July 2026 candidate.
> See [`../README.md`](../README.md) for current documentation status.

## Artifact

- Path: `launcher/dist/NekoLauncher.exe`
- Size: `132609853` bytes (`126.47 MiB`)
- SHA-256:
  `06A9624E494A268023FA4B4757DED7651FA8090580B7A8E6C85D0AE4C8EE5417`
- Authenticode: not signed
- Build tool: PyInstaller `6.20.0`, Python `3.14.4`

## Password workflow

- Signup accepts Username, Password, and Password confirmation only.
- Launcher contains no Recovery Email input or email-reset request.
- Forgotten-password copy directs customers to the administrator.
- Signed-in customers can change their own password in the Launcher.
- Admin-assisted reset is deployed at
  `https://neko-control-room.vercel.app`.
- Production Admin Tool deployment:
  `dpl_Et3bAJzx4u3WiWEsRCghGFe9GZJg` (commit `89d13f3`).
- Production Supabase migration:
  `add_admin_password_reset_audit_event`.

## Checks completed

- Ruff passed.
- Launcher unit tests passed: `32 passed, 2 deselected`.
- Admin Tool tests and standalone build passed: `5 passed`.
- Admin Tool preview and production health checks returned HTTP 200 with
  `Cache-Control: no-store`.
- Unauthenticated Admin API check returned HTTP 401.
- Vercel runtime error scan found no errors after deployment.
- Supabase constraint verification includes `admin_password_reset`.
- Windows startup smoke test passed: the EXE remained running for 5 seconds.
- No secret/service-role key is present in Launcher or the Admin browser bundle.

## Warnings and remaining release checks

- PyInstaller could not resolve Windows driver dependencies `NDIS.SYS`,
  `fwpkclnt.sys`, and `packet.dll`; verify the selected ProxyCore mode and
  Npcap requirements on a clean Windows machine.
- The EXE is not digitally signed.
- The production disposable-account acceptance script is ready at
  `scripts/e2e-password-reset.mjs` in the Admin Tool repository, but could not
  run from this machine because Vercel returns production secrets as
  `[encrypted]` and no admin login credential was available.
- Do not remove the legacy reset page until old Launcher clients are no longer
  distributed; it is not referenced by this release candidate.
