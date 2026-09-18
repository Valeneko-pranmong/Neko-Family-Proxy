# Emergency v5.1.3 Clean-Install Hotfix Implementation Plan

## Phase A — Source Candidate

1. Branch from reviewed hotfix source `983f723`.
2. TDD version identity:
   - update `launcher/src/neko_launcher/__init__.py` to `5.1.3`
   - update `launcher/pyproject.toml` project version to `5.1.3`
   - update lock metadata using `uv lock --locked`/minimal lock refresh only if required; reject unrelated dependency drift.
3. Keep root hotfix unchanged: `FOLDERID_LocalAppData\NEKO FAMILY`.
4. Run targeted root/version tests, full launcher suite, Ruff, repository safety, diff check.
5. Independent Gemini Pro source review C0/I0.
6. Merge to main and require GitHub CI + Main Source Acceptance green.

## Phase B — Freeze Components

1. Build Launcher with CPython 3.12 + PyInstaller 6.21.0 from exact committed lock.
2. Verify package archive contains `python312.dll`; reject Python 3.14 build.
3. Reuse exact v5.1.2 Updater bytes only after `--self-check` PASS.
4. Reuse exact v5.1.2 Core ZIP and installed Core manifest identity.
5. Freeze measurements: filename, size, SHA-256, source commit, build environment.

## Phase C — Production Authority

1. Read production ledger under exclusive controller lock.
2. Reserve next sequence; expected seq10/stable-0010 but derive from ledger.
3. Construct unsigned ReleaseSet:
   - version 5.1.3 for all three components
   - channel stable
   - mandatory false
   - minimum_supported_sequence 9
   - updater protocol 1..1
   - exact frozen artifact identities
4. Independent reservation/metadata review C0/I0.
5. Under exact Owner signing authorization, sign with `neko-update-prod-1` through guarded production signer; append SIGNED ledger event.
6. Independent signing/custody review C0/I0.

## Phase D — Installer

1. Create fresh external staging directory.
2. Stage exact signed Launcher/Updater/Core, signed `release-v2.json`, production trust profile, approved .NET 6.0.36 bootstrapper.
3. Expand CoreBundle and verify all `core-manifest.json` files.
4. Build `NekoFamilyProxy-Installer.exe` with `--release-version 5.1.3`.
5. Require all builder gates PASS.
6. Verify Installer metadata/version, embedded signed envelope/profile hashes, and exact component bytes.
7. Perform disposable clean-install/enrollment proof from exact candidate inputs.
8. Independent final five-asset review C0/I0.

## Phase E — Public Release

1. Create Owner gate binding exact source commit, sequence/release_id, signed payload/envelope, five asset SHA-256/size, build record and final review.
2. Under exact Owner public-release authorization:
   - create draft v5.1.3 in canonical repo
   - upload exact five assets
   - authenticated readback and cryptographic verification
   - promote release / create or update tag only within reviewed publisher semantics
   - verify latest=v5.1.3 and tag target exact source
   - finalize PUBLISHED ledger authority
3. Re-download hosted Installer and perform clean-install proof.
4. Mark gate done only if hosted install succeeds without baseline enrollment or Launcher startup failure.

## Stop Conditions

Any Critical/Important review finding, hash drift, sequence mismatch, source/tag mismatch, failed clean-install proof, or unsigned/public mutation outside the exact Owner gate blocks progression. Never repair a published immutable release in place; create a new successor release.
