# Closed Beta runbook

```text
CLOSED_BETA_STATUS:          READY
CLOSED_BETA_RUNTIME:         VERIFIED
BETA_TESTER_001:             PASS (RUNNING_TO_NORMAL_STOP_PASS)
BETA_DATABASE_BASELINE:      CLEAN
CUSTOMER_TEST_USERS:         0 before onboarding
BETA_DISTRIBUTION:           SINGLE_EXE_INSTALLER
INSTALLER_VERSION:           1.0.0.1 (1.0.0-beta.1)
INSTALLER_FILE:              NekoFamilyProxy-Beta-Setup.exe
INSTALLER_SHA256:            3fab856f75962ae36cd3946e459ffaa8a9f0f54558101c522dfcb8ea97f17516
INSTALLER_REBUILD:           PENDING
PRODUCTION_HEAD:             6ff9a3de70da34e52088c47eb1cdcfd62fa9f731
LAUNCHER_RUNTIME_AUTHORITY:  bba655b3e6443ebcdf84a266e42cc918bdefe32f
CORE_AUTHORITY:              33f97ae0110075089f39b1e123890f931417d907
LAUNCHER_EXE_SHA256:         a9bd1b18612601420020e2ed2de1d827f81169c9a05b07bdeef58aed703bb42c
RECONNECT_SOURCE_VERSION:    5.0.0a8
RECONNECT_EXE_SHA256:        0daded67ec2a462823aa4316f3910cc0aa631bcbc5de177f57054e502522a299
RECONNECT_LIVE_PROOF:        PASS (SUPPLEMENTAL_ATTEMPT_1)
REOPEN_SOURCE_VERSION:       5.0.0a9
REOPEN_EXISTING_PSO2:        IMPLEMENTED — LIVE PROOF PENDING
REOPEN_EXE_SHA256:           ecaf9b500acf7498f87a3e01fae5ce84ffe6c7113d40f258509f151efa8d8435
REOPEN_FINAL_BUILD:          PASS (re-verified at HEAD a6470bc)
REOPEN_ARTIFACT_SMOKE:       PASS (re-verified at HEAD a6470bc)
REOPEN_LIVE_PROOF:           PENDING
REOPEN_FINAL_SHUTDOWN:       PENDING
REOPEN_GIT_COMMIT:           PENDING
REOPEN_GIT_PUSH:             PENDING
LAST_VERIFIED:               2026-08-26
NEXT_ACTION:                 PROVIDE/INSTALL APPROVED CORE RUNTIME FOR LIVE PROOF
```

## Launcher UI repair source status (2026-08-24)

The CLOSED BETA Launcher source and tests now use the approved `image_11.png`
and `icon_app.ico`, the five functional Settings groups (`Status`, `Program`,
`Account & Subscription`, `PSO2`, `About`), persisted Always-on-top under
`%LOCALAPPDATA%\NEKO FAMILY`, working password visibility controls,
single-flight coupon redemption, PSO2-aware close/logout confirmation, and
truth-preserving unavailable telemetry presentation. A new Launcher EXE was
built from the repaired source. The current Launcher `5.0.0a6` SHA-256 is
`a9bd1b18612601420020e2ed2de1d827f81169c9a05b07bdeef58aed703bb42c`,
verified from a fresh `_MEI` extraction with no embedded ProxyCore/V2Ray files.
No Installer was built, and no Proxy/Core authorization or runtime transport
behavior was changed.

The heartbeat Auth-invalid classification gap was closed in Launcher `5.0.0a7`.
Structured Supabase invalid-JWT and rejected refresh-session errors now return
the Launcher to Login, while timeout, connection, backend 5xx, and unrelated
authorization/entitlement 403 failures retain durable Auth for bounded retry.
Authoritative `heartbeat_session = false` and latest-claim-wins remain
fail-closed.

```text
AUTH_ERROR_CLASSIFICATION:    PASS
REFRESH_TOKEN_REJECTED:       LOGOUT
```

Launcher `5.0.0a8` adds single-flight automatic Proxy reconnect after a
previously healthy RUNNING connection loses Core, V2Ray, local SOCKS, upstream,
or telemetry transport while `pso2.exe` remains alive. Recovery uses bounded
backoff (`1s`, `3s`, `8s`) and the existing fail-closed authorization flow:
runtime-only STOP where an owned Core host remains, then a fresh Core challenge,
exactly one fresh launch permit, and a typed RUNNING verification. No challenge
or permit is reused. A successful RUNNING transition resets the retry budget.

Automatic reconnect is suppressed after manual STOP, confirmed Logout,
Launcher shutdown, `pso2.exe` exit, invalid Auth, `SessionInactive`, or inactive
entitlement. Exhausting the retry budget leaves a truthful disconnected/error
status and does not force logout unless Auth is authoritatively invalid. The UI
shows `กำลังเชื่อมต่อใหม่...` during recovery and `เชื่อมต่อแล้ว` only after a
typed successful transition.

### Supplemental live reconnect proof (2026-08-24)

The existing `5.0.0a8` EXE with SHA-256
`0daded67ec2a462823aa4316f3910cc0aa631bcbc5de177f57054e502522a299`
passed one supplemental live reconnect proof. The previous observation that
stopped before `pso2.exe` started was not counted as an attempt. The Owner
completed the required elevated Tweaker `Start PSO2` action; no
privilege-crossing automation was used.

`INITIAL_RUNNING` was established with the exact `pso2.exe` alive, Launcher
detection, one Core host, one V2Ray process and local SOCKS listener, a typed
Core `Running` response, one HTTP 200 launch-permit response, ProcessMode
traffic, and truthful live telemetry. The sole disconnect injection was one
Core control-channel runtime-only `STOP`; it retained the same `pso2.exe`, Auth,
session, entitlement, and owned Core host.

Launcher detected the disconnect and displayed `กำลังเชื่อมต่อใหม่...`,
scheduled exactly one reconnect at the first bounded `1s` delay, and performed
one fresh attempt with one new challenge, one new HTTP 200 permit, and one
authorized start. The original Core host remained single; V2Ray exited and one
replacement V2Ray started. No duplicate Core/V2Ray or permit spam was observed.
The typed state returned to `Running`, the UI returned to `เชื่อมต่อแล้ว`, and
real telemetry resumed while the same `pso2.exe` remained alive.

Normal Launcher close used the PSO2-active confirmation path. Launcher, Core,
and V2Ray exited; `pso2.exe` remained alive by policy. The immediate and delayed
orphan scans found no Core/V2Ray, and the Windows Application log contained no
Launcher/Core/V2Ray crash event for the proof window. No source, version, Core,
Launcher EXE, or Installer was changed or rebuilt during the live proof.
Installer rebuild remains pending.

Launcher `5.0.0a9` adds the reopen route after Auth, current-session claim, and
ACTIVE entitlement validation. Before any Tweaker launch, the responsive
background startup probe checks for `pso2.exe`; an existing game suppresses
Tweaker, enters `ตรวจพบ PSO2 ที่กำลังทำงาน — กำลังเชื่อมต่อ...`, and uses the
same exact-target authorization path to obtain a fresh Core challenge and one
fresh launch permit bound to that live PID. `เชื่อมต่อแล้ว` is shown only after
the controller reaches RUNNING. Missing Auth/session/entitlement remains
fail-closed, repeated startup callbacks are single-flight, target exit cancels
the operation, and multiple PSO2 candidates remain ambiguous/fail-closed.

Launcher/Core lifecycle ownership is now explicit for newly started hosts: a
Core child is created directly inside a Launcher-held Windows kill-on-close
Job Object, so the exact Core/V2Ray tree dies with Launcher ownership while
the unrelated `pso2.exe` process is untouched. The Job handle is verified
before a spawned child is accepted and closed on every cleanup path; if the
child cannot be killed during failed-spawn cleanup, closing the owning Job is
the fail-closed fallback. This is process-lifetime ownership only — it does
not claim that `%LOCALAPPDATA%` is immutable against an already-compromised
process running as the same Windows user.
The final Launcher build, packaged-artifact smoke, controlled live reopen proof,
normal final shutdown evidence, commit, and push remain pending. Each ledger
entry above stays `PENDING` until its own evidence is captured; therefore
`REOPEN_EXISTING_PSO2` is not yet marked VERIFIED.

### Final build and packaged-artifact smoke (2026-08-26)

The final `5.0.0a9` Launcher EXE was first built from HEAD
`ce6e01d5e3829040056624dd29f3ec473139fb04` (SHA-256
`f24c5f3f05350dcfc6ffa9fbc1370c93e2f457352cb80b382a961565e086874c`,
29,862,857 bytes) with the documented procedure. After the documentation-only
commits `0915c01` and `a6470bc` landed on `main`, the build and smoke were
re-run in full at the new HEAD so the shipped artifact is traceable to current
Git truth: HEAD `a6470bc149d9d6bb83e902b02bad763742c44a7b`, PyInstaller 6.21.0,
Python 3.11.15, `python -m PyInstaller --clean --noconfirm NekoLauncher.spec`.
Pre-build gates at `a6470bc`: `ruff check src tests` clean;
`pytest -q -m "not integration"` = 609 passed, 1 skipped, 5 deselected;
`compileall -q src` clean; a targeted reopen/lifecycle/detector/window/
single-flight set of 243 tests passed. No source file changed between the two
builds (the two commits touch only `.gitignore` and this runbook), so the
version stayed `5.0.0a9`. The build log reported 0 errors and the same benign
tooling warnings (unresolved optional hidden imports such as `tzdata`,
`pycparser.lextab`; an AppKit ctypes-import notice).

```text
REOPEN_FINAL_BUILD:   PASS
BUILD_SOURCE_HEAD:    a6470bc149d9d6bb83e902b02bad763742c44a7b
FINAL_EXE:            launcher\dist\NekoLauncher.exe (29,863,010 bytes)
REOPEN_EXE_SHA256:    ecaf9b500acf7498f87a3e01fae5ce84ffe6c7113d40f258509f151efa8d8435
TARGETED_TESTS:       PASS (243 focused reopen/lifecycle/detector/window/single-flight tests)
```

The packaged EXE built at `a6470bc` (not the source launcher) then passed a
packaged-artifact smoke in a sandboxed fresh context (`TEMP`/`LOCALAPPDATA`
redirected, only the spawned EXE handle/PID tree tracked, `NEKO_DEBUG_MODE=1`).
The debug session header identified `NekoLauncher-5.0.0a9 (Debug)`,
`PACKAGED_VS_SOURCE = PACKAGED`, and a fresh extraction `_MEI172082`. The UI
initialized (debug console enabled, normal WAITING_FOR_GAME poll started) with
no startup crash, and the single-instance mutex correctly blocked a second
launch attempt (duplicate exited immediately). Closing the window via its own
UI path exited both onefile processes (bootloader + tracked child) within
seconds, left no orphan in the exact tracked PID tree, and removed the fresh
`_MEI` directory. The fresh `_MEI` contained only the Python runtime,
dependencies, and declared assets (1,084 entries enumerated; no
`NekoProxyCore.exe`/`.dll`, `v2ray-sn.exe`, `runtime-settings.nkps`, or
`core-manifest.json` entries; both Sarabun fonts present). A full recursive
PyInstaller archive enumeration (1,032 CArchive TOC entries + 1,192 PYZ
modules) listed the declared `image_11.png` and `icon_app.ico` and contained
no external-runtime entry. Finally, the
`neko_launcher.infrastructure.defaults` module was extracted from the packaged
PYZ and inspected: only the Supabase project URL, the control-room URL, and
the intentional publishable key (`sb_publishable_…`) are embedded — no
service-role key, `sb_secret_` material, or private key block.

```text
REOPEN_ARTIFACT_SMOKE: PASS
FRESH_MEI:             PASS (no Core/V2Ray/nkps entries)
EMBEDDED_CORE_CHECK:   PASS (external runtime contract preserved)
SECRET_HYGIENE:        PASS (PYZ-level inspection of defaults module)
```

This artifact smoke does not prove the live Core/reopen authorization path.
This machine currently has no installed Core runtime at
`%LOCALAPPDATA%\NEKO FAMILY\ProxyCore` (directory absent, no
`core-manifest.json`), so the controlled reopen-while-PSO2-alive live proof
remains blocked until the approved Core-33f97ae runtime bundle is installed
through the supported channel.

The unexpected automatic logout defect was fixed in Launcher `5.0.0a6`. The
root cause was the heartbeat exception path treating three consecutive
transport/backend failures as revoked authorization, then calling local Auth
sign-out and clearing Launcher state. Timeouts, offline/connection-refused, and
temporary backend failures now retain durable Auth/session state, display a
reconnecting status, and retry only on the existing bounded heartbeat schedule.
An authoritative rejected heartbeat still immediately invalidates the session,
including latest-claim-wins replacement enforcement.

The following CLOSED BETA verification remains explicitly **OPEN**:

- one controlled live proof of reopening Launcher `5.0.0a9` while the same
  `pso2.exe` remains alive, including fresh challenge/permit and duplicate-count
  evidence.

This procedure prepares a limited closed beta without changing the approved
Launcher or Core runtime, production security contracts, or Phase 2.5/T10B4
closure.

## Supported distribution and installation

`BETA_DISTRIBUTION = SINGLE_EXE_INSTALLER`. The supported beta delivery is the
single-file installer `NekoFamilyProxy-Beta-Setup.exe`, built from the tracked
source under `installer/` in this repository. After installation the Launcher
and Core remain separate: `NekoLauncher.exe` sits at
`%LOCALAPPDATA%\NEKO FAMILY\NekoLauncher.exe` and resolves the external
`%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe` runtime; Core is
never embedded in the Launcher EXE.

Installer facts:

- Installer version `1.0.0.1 (1.0.0-beta.1)`, SHA-256 and size are recorded in
  the build record produced by `installer/scripts/build_beta_installer.py`
  (`D:\Build\NekoBetaInstaller\out\build-record.json` on the build machine).
- The build fails closed unless the staged payload matches the approved
  Launcher SHA-256, the Core manifest authority commit, every declared Core
  file hash, the pinned `v2ray-sn.exe` SHA-256, and secret-hygiene checks.
- After copying files, setup verifies the installed Core against
  `core-manifest.json` (authority commit, all file hashes, `v2ray-sn.exe`,
  presence of `runtime-settings.nkps`, absence of any plaintext settings or
  key) and shows a clear failure with the optional launch suppressed when
  verification fails.
- Driver-install policy: netfilter2 is prepared through the existing supported
  path — copy `bin\nfdriver.sys` to `System32\drivers\netfilter2.sys` and
  register via the proven `Redirector.bin!aio_register("netfilter2")`
  entry point (exactly what NekoProxyCore's own NFController does). An already
  valid running driver is verified only without elevation; elevation is
  requested only when registration is actually required; a running driver
  whose bytes differ from the approved bundle is never silently overwritten.
- Uninstall policy: the netfilter2 driver is treated as a shared machine
  prerequisite and is intentionally PRESERVED on uninstall. The uninstaller
  removes only the program files it installed, shortcuts, and its own
  uninstall registry entries; pre-existing user state (`logs\`, `tweaker.path`)
  and runtime logs are left untouched.

A tester needs:

1. Windows x64 with PSO2 JP and PSO2 Tweaker already installed.
2. Microsoft .NET 6 Windows Desktop Runtime x64 for the framework-dependent
   Core runtime.
3. The approved beta installer `NekoFamilyProxy-Beta-Setup.exe`, delivered
   through the team's controlled beta channel. Verify SHA-256 before running:

   ```powershell
   (Get-FileHash .\NekoFamilyProxy-Beta-Setup.exe -Algorithm SHA256).Hash.ToLowerInvariant()
   ```

   The result must be
   `3fab856f75962ae36cd3946e459ffaa8a9f0f54558101c522dfcb8ea97f17516`.
4. Run the installer. It deploys the approved Launcher and the complete
   manifest-verified Core bundle to the exact Local AppData paths, verifies
   the Core installation against `core-manifest.json` (authority commit
   `33f97ae0110075089f39b1e123890f931417d907`, every declared file hash,
   `v2ray-sn.exe`, `runtime-settings.nkps` present, no plaintext settings or
   standalone key), and prepares the netfilter2 driver (asking for admin
   approval only when registration is actually required). No plaintext
   settings, key, service-role material, or proxy credential is contained in
   or displayed by the installer.
5. Run `NekoLauncher.exe`. No additional Launcher Python environment,
   source checkout, service-role key, proxy credential, or manual file
   placement is required on the tester machine.

## Tester checklist

### Install and start

- [ ] Install PSO2 JP, PSO2 Tweaker, and Microsoft .NET 6 Windows Desktop
      Runtime x64.
- [ ] Verify the installer SHA-256 above, then run it and let it finish.
- [ ] If the installer reports a Core verification or driver failure, stop and
      report; do not run the Launcher.
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
