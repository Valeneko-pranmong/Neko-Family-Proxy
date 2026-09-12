# Project Context — Neko Family Proxy Launcher

Updated: 2026-09-12

## Purpose
This repository is the Windows Launcher/client tier for Neko Family Proxy. It owns user-facing launch/session orchestration, authentication/permit flow integration, installer/updater code, release-controller automation, Supabase client/backend contracts and related tests.

## Canonical repository state
- Repository: `Valeneko-pranmong/Neko-Family-Proxy`
- Canonical branch: `main`
- Current canonical SHA at cleanup: `7b4558b0503b5fd948739153dc5a6d5b22133323`
- Active release-runtime worktree: `E:\Github\worktrees\Neko-Family-Proxy-release-runtime`
- Runtime worktree is detached/pinned to the reviewed controller SHA above.

## Current production release
- Stable/Latest: `v5.1.0`
- GitHub Release ID: `387113854`
- Stable tag source: `0b71f03ee4ed69176da2682fdd1cfb4e5cce971c`
- User-facing asset: `NekoFamilyProxy-Installer.exe`
- Public release is intentionally installer-only.

## Important limitation
Automatic in-app update is currently unavailable because `release-v2.json`, `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip` were intentionally removed from the public v5.1.0 GitHub Release. Manual install/update through the Installer remains available.

The next architecture task is to move those signed update payloads to separate immutable backend/storage while keeping GitHub user-facing and installer-only.

## Related projects
- `E:\Github\NekoProxyCore` — low-level Core/driver/runtime used by the Launcher.
- `E:\Github\Neko-Family-Proxy-admin-tool` — operator Control Room / web admin.
- `E:\Github\Neko-Core AWS` — production server/infrastructure workspace.
- `E:\Github\Project manager` — cross-project authority, handoff and history.

## Security / release boundaries
- Client code must not contain service-role/admin secrets.
- Do not read, print, copy or export production signing private-key bytes.
- `v5.1.1` must not be created merely for infrastructure/testing work; it requires a real explicit `user_bug` release intent.
- Failed release attempts do not consume SemVer.
- Exact SHA/run-id/idempotency and independent review gates remain release invariants.
- Release intent is currently closed.

## Validation entry points
- Repository safety: `python scripts/check_repository_safety.py`
- Launcher lint/tests: see `launcher/pyproject.toml` and README development section.
- Release-control tests live under repository `tests/` and Launcher tests.

## Read next
1. `README.md`
2. `HANDOFF.md`
3. `E:\Github\Project manager\current\NEXT_WORK_AUTO_UPDATE_BACKEND_HANDOFF.md`
4. `E:\Github\Project manager\current\CONTROLLER_LEDGER_MAIN_AUTO_RELEASE.md` when release-controller history is required.

Always verify live GitHub/runtime state before acting; prose can become stale.
