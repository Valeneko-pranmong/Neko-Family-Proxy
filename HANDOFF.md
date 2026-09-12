# Handoff — Neko Family Proxy Launcher

Updated: 2026-09-12

## Current state
- Canonical branch: `main`
- Reviewed controller/runtime SHA: `7b4558b0503b5fd948739153dc5a6d5b22133323` (canonical `main` may advance with docs/maintenance commits; verify live before work)
- Public Stable/Latest: `v5.1.0` (release ID `387113854`)
- Public custom asset: `NekoFamilyProxy-Installer.exe`
- Public release is installer-only by owner decision.
- Windows legacy release workflow remains disabled.
- Hermes release poller/runtime is active and pinned to the reviewed controller worktree; release intent remains closed.

## User-facing readiness
Manual install/use through the v5.1.0 Installer is ready. Automatic in-app update is not currently available because the signed update manifest/component assets were removed from the public GitHub Release.

## Next work
Design and implement separate immutable update distribution for:
- `release-v2.json`
- `NekoLauncher.exe`
- `NekoUpdater.exe`
- `NekoProxyCore.zip`

Keep signature/hash/size/provenance verification fail-closed and keep the GitHub release installer-only.

Authoritative detailed handoff:
`E:\Github\Project manager\current\NEXT_WORK_AUTO_UPDATE_BACKEND_HANDOFF.md`

## Do not accidentally change
- Do not publish `v5.1.1` without explicit real user-bug release intent.
- Do not replace the existing v5.1.0 release/tag just to test update backend work.
- Do not expose signing private-key bytes.
- Do not repoint or mutate `E:\Github\worktrees\Neko-Family-Proxy-release-runtime` casually; it is the active release-controller runtime.

## Historical evidence
- Accepted v5.1.0 candidate: `E:\Github\artifacts\v5.1.0-clean-candidate\attempt-3\`
- Retained accepted worktree: `E:\Github\worktrees\v5.1.0-clean-candidate-attempt-3`
- Installer-only public edit audit: `E:\Github\artifacts\v5.1.0-public-installer-only-audit\`

## First checks for a new maintainer
1. `git status --short --branch`
2. `git rev-parse HEAD` and `git rev-parse origin/main`
3. verify public Stable/Latest and current custom assets
4. verify release poller/runtime health before release-controller changes
5. read Project Manager current handoff before creating release work
