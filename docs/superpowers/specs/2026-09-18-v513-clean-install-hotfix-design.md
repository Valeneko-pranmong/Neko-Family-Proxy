# Emergency v5.1.3 Clean-Install Hotfix Design

## 1. Incident

Public v5.1.2 `stable-0009` installs to `%LOCALAPPDATA%\NEKO FAMILY`, while the shipped Launcher/Updater trust root validator resolves `FOLDERID_UserProgramFiles\NEKO FAMILY` (`%LOCALAPPDATA%\Programs\NEKO FAMILY`). On clean install, Installer invokes `NekoLauncher.exe --enroll-baseline`, which cannot find the staged trust profile/baseline at the wrong root and exits 1; normal Launcher startup then also fails.

The source fix is commit `983f72384c168a5c698021a787295b3f2407f61a`, independently reviewed SPEC PASS / QUALITY PASS with Critical=0, Important=0, and GitHub CI + Main Source Acceptance green.

## 2. Release Strategy

Do not mutate or replace published v5.1.2 / stable-0009 assets, tag, signed envelope, or ledger history. Ship a successor stable release:
- version/tag: `5.1.3` / `v5.1.3`
- next production sequence: reserve the next available sequence from the production ledger (expected `10`; never hard-code if ledger disagrees)
- release_id: derived from reserved sequence (expected `stable-0010`)
- channel: `stable`
- mandatory: `false`
- minimum_supported_sequence: `9`
- updater protocol: `1..1`
- signing key: `neko-update-prod-1`

Why minimum_supported_sequence=9: stable-0009 is the current published authenticated baseline. Existing healthy v5.1.2 installations remain supported and may update normally; older authenticated sequences remain below the compatibility floor. This hotfix fixes clean installation and does not require forcibly interrupting healthy seq9 clients.

## 3. Component Policy

- Launcher: rebuild from exact reviewed source containing the LocalAppData root fix; internal/UI package version must be `5.1.3`.
- Updater: reuse the exact v5.1.2 production bytes if no source change is required and self-check still passes.
- Core: reuse the exact v5.1.2 production Core ZIP / installed identity if unchanged.
- Installer: rebuild from the exact signed v5.1.3 envelope, production trust profile, v5.1.3 Launcher, reused Updater/Core, and pinned .NET Desktop Runtime 6.0.36.
- Public release contains exactly five authored assets:
  `NekoFamilyProxy-Installer.exe`, `release-v2.json`, `NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`.

## 4. Root Security Contract

Production install root is exactly `FOLDERID_LocalAppData\NEKO FAMILY`, matching Inno Setup `DefaultDirName={localappdata}\NEKO FAMILY`.
- Resolve via Windows KnownFolder API.
- Environment fallback is allowed only if `SHGetKnownFolderPath` fails, retaining existing fail-closed behavior when LOCALAPPDATA is absent.
- No user/config/CLI arbitrary root override.
- Existing unelevated-token rejection and NTFS validation remain unchanged.
- Installer enrollment, normal Launcher composition, updater session, trust-profile loading, pending update storage and credential provider all use the same resolved root.

## 5. Version/Identity Contract

The Launcher source/package identity shown to users must be `5.1.3`. Signed release component metadata for launcher/updater/core is `5.1.3`, even when Updater/Core bytes are byte-identical to v5.1.2. Installed identities and artifact SHA-256/size bind exact bytes, not version labels alone.

## 6. Build Reproducibility

Launcher is built with:
- CPython 3.12.x Windows x64 (same major/minor as v5.1.2 production Launcher)
- PyInstaller 6.21.0
- dependencies resolved from committed `launcher/uv.lock` with `--locked`
- explicit machine Tcl/Tk paths only for build environment setup

A Python 3.14 scratch build is non-release evidence and must never enter release staging.

## 7. Acceptance

Before signing:
1. RED/GREEN contract tests bind root validator to Installer `{localappdata}\NEKO FAMILY`.
2. Full Launcher non-integration suite passes.
3. Ruff, repository safety, and `git diff --check` pass.
4. GitHub CI and Main Source Acceptance pass for exact release source commit.
5. Frozen Launcher/Updater/Core bytes are measured after smoke.
6. Launcher packaged archive contains Python 3.12 runtime and no embedded Core/V2Ray.
7. Updater `--self-check` passes.
8. A disposable install-layout test using the exact frozen components + signed candidate envelope completes baseline enrollment and creates authenticated state.
9. Installer build gates all pass and its embedded envelope/profile are byte-identical to signed production custody.
10. Independent Gemini Pro review returns SPEC PASS + QUALITY PASS, Critical=0, Important=0.

## 8. Authority Gates

Production sequence reservation/signing and public GitHub release/tag/ref mutation remain Owner gates. No authorization for those actions is inferred from source implementation, CI, local builds, or review. Exact Owner authorization must bind the specific gate/task and candidate identities before each production authority action.

## 9. Publication Verification

After authorized publication:
- authenticated re-download all five hosted assets and compare SHA-256/size
- verify signed envelope under production trust profile
- verify tag target equals exact approved source commit
- verify GitHub latest resolves to v5.1.3
- run clean-install proof on the hosted Installer; baseline enrollment must succeed and Launcher must start without `StartupFailed`
- append/finalize publication authority using the reviewed single-repo publisher semantics
