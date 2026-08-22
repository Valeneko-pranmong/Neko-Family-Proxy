# Closed Beta runbook

```text
CLOSED_BETA_STATUS:          READY
BETA_DATABASE_BASELINE:      CLEAN
CUSTOMER_TEST_USERS:         0 before onboarding
PRODUCTION_HEAD:             6ff9a3de70da34e52088c47eb1cdcfd62fa9f731
LAUNCHER_RUNTIME_AUTHORITY:  bba655b3e6443ebcdf84a266e42cc918bdefe32f
CORE_AUTHORITY:              862bfec463d06d57e1bee05c2bc490740eb714d4
LAUNCHER_EXE_SHA256:         4ae0aa676a41822033a6b00fdae9dde7ff3b900fc30ae39ca71dea6851411609
LAST_VERIFIED:               2026-08-22
```

This procedure prepares a limited closed beta without changing the approved
Launcher or Core runtime, production security contracts, or Phase 2.5/T10B4
closure.

## Supported distribution and installation

The supported beta delivery is the existing standalone Launcher plus the
separately delivered complete Core runtime. The Launcher EXE does not contain
Core. At the production head there is no tracked customer installer or
bootstrap implementation; the beta uses controlled manual placement rather
than inventing a new packaging path.

A tester needs:

1. Windows x64 with PSO2 JP and PSO2 Tweaker already installed.
2. Microsoft .NET 6 Windows Desktop Runtime x64 for the framework-dependent
   Core runtime.
3. The approved `NekoLauncher.exe`, delivered through the team's controlled
   beta channel. Verify SHA-256 before running:

   ```powershell
   (Get-FileHash .\NekoLauncher.exe -Algorithm SHA256).Hash.ToLowerInvariant()
   ```

   The result must be
   `4ae0aa676a41822033a6b00fdae9dde7ff3b900fc30ae39ca71dea6851411609`.
4. The complete approved Core bundle, delivered through the separate
   access-controlled runtime channel with `core-manifest.json`. Replace the
   complete destination directory; do not mix files from different bundles:

   ```text
   %LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe
   ```

   The manifest `source_commit` must be
   `862bfec463d06d57e1bee05c2bc490740eb714d4`, every declared file hash must
   match, and no plaintext settings or standalone key is distributed.
5. Run `NekoLauncher.exe` directly. No additional Launcher Python environment,
   source checkout, service-role key, proxy credential, or installer is
   required on the tester machine.

## Tester checklist

### Install and start

- [ ] Install PSO2 JP, PSO2 Tweaker, and Microsoft .NET 6 Windows Desktop
      Runtime x64.
- [ ] Verify the Launcher SHA-256 above.
- [ ] Copy the complete verified Core bundle to the exact Local AppData path.
- [ ] Start `NekoLauncher.exe`; do not run a second Launcher instance.

### Register, obtain access, and play

- [ ] Choose **Register**, create a username and password, then sign in.
- [ ] Send only the username to the operator through the approved support
      channel. Never send the password.
- [ ] Receive one beta coupon privately from the operator and redeem it in
      Launcher Settings.
- [ ] Confirm the membership/entitlement status is **ACTIVE** and displays the
      expected validity period.
- [ ] Select the existing `Tweaker.exe` when requested. The Launcher remembers
      this path.
- [ ] Start PSO2 through the normal Tweaker flow. Launcher waits for the exact
      `pso2.exe` process; after detection it starts and authorizes Core
      automatically.
- [ ] Expected behavior: status progresses from waiting for game to Core
      starting/running; local telemetry appears while connected. Closing the
      Launcher explicitly cleans up only the Tweaker/Core processes it owns.
      A second successful login becomes the current session and displaces the
      older Launcher session.

### Report a failure

Report the time, username, Launcher status text, operation attempted, and a
screenshot. Do not send a password, coupon, token, permit, session ID, proxy
configuration, endpoint secret, or unreviewed raw log.

For diagnostic logging, start the approved EXE from a trusted PowerShell window
with `NEKO_DEBUG_MODE=1` set only for that process. Logs are written under:

```text
%LOCALAPPDATA%\NekoFamilyProxy\logs
```

Before sharing, inspect and sanitize the selected Launcher `debug.log` and the
matching Core stdout/stderr attempt logs. Logs may contain local paths and PIDs
even though known credentials are redacted.

## Operator checklist

### Onboard and grant beta entitlement

- [ ] Confirm the production database still has zero customer/test users before
      the first tester registers.
- [ ] Have the tester self-register in the approved Launcher; Admin Web does not
      create customer accounts.
- [ ] In Admin Web **Members**, verify the exact username and active customer
      profile.
- [ ] In **Coupons**, create a one-code beta batch for the existing product and
      intended duration. Copy the plaintext code at creation time and deliver it
      privately; it cannot be retrieved from the database later.
- [ ] After redemption, verify **Licenses** shows effective status **ACTIVE**.
- [ ] After login, verify **Launcher sessions** identifies the current session
      by username and fresh heartbeat. Treat heartbeat age of 120 seconds or
      less as online; do not confuse remembered installations with active
      sessions.

### Revoke, restore, or remove a tester

- Revoke beta access in **Licenses → Revoke**. A later supported grant uses a
  new coupon; **Extend** is available for an existing license.
- End current access in **Launcher sessions → End session**. The remembered
  installation remains and may sign in again if the account and entitlement
  remain active.
- Offboard a tester by ending the current session, revoking the license, and
  setting the customer to **Suspended** or **Banned** in **Members**. Customer
  account deletion is not a supported current Admin action and must not be
  improvised.
- To restore an offboarded tester, set the customer to **Active** and issue a
  new coupon when entitlement is needed.
- Never expose Supabase secret/service-role material, Admin session material,
  recovery HMAC material, proxy credentials, private signing keys, raw coupon
  storage, or Admin UID.

## Rollback baseline

The immutable beta rollback authorities are:

```text
PRODUCTION_HEAD:             6ff9a3de70da34e52088c47eb1cdcfd62fa9f731
LAUNCHER_RUNTIME_AUTHORITY:  bba655b3e6443ebcdf84a266e42cc918bdefe32f
CORE_AUTHORITY:              862bfec463d06d57e1bee05c2bc490740eb714d4
LAUNCHER_EXE_SHA256:         4ae0aa676a41822033a6b00fdae9dde7ff3b900fc30ae39ca71dea6851411609
```

For a beta rollback, stop onboarding, revoke affected beta sessions/licenses
and coupon batches through supported Admin operations, restore the approved
Launcher EXE and complete manifest-verified Core bundle above, and verify no
owned Core process remains after Launcher exit. Do not roll back or modify
production security migrations/contracts as part of this artifact rollback.

## Minimum acceptance monitoring

- [ ] Registration and login succeed.
- [ ] Coupon redemption changes entitlement to **ACTIVE**.
- [ ] Latest-login-wins: a newer successful login becomes current and the old
      session loses authority.
- [ ] Launcher detects the exact `pso2.exe` process.
- [ ] Core progresses through start, running, stop, and cleanup lifecycle.
- [ ] Exiting/ending the game leaves no crashed or orphaned Launcher-owned Core.
- [ ] Sanitized local Launcher/Core logs are available for a reported failure.
- [ ] Admin Web overview/server metrics can check a fresh server sample,
      Shadowsocks service/listener state, ping availability, and packet loss.
- [ ] No password, coupon, token, permit, private key, proxy configuration, or
      Admin UID appears in a beta report.

A failure of the approved artifact hash, Core manifest/hash validation,
authoritative session/entitlement behavior, or runtime lifecycle is a stop
condition for further onboarding.
