# Handoff — Neko Family Proxy Launcher

Updated: 2026-09-12 (Neko Family 5.1.2 Deferred Update Architecture)

## Current state
- Active integration branch: `feature/neko-family-5.1.2`
- Base commit: `ed82b885138015e194bbf45db61a7d6899640156` (`origin/main`)
- Distribution Architecture: Two-Repo Role Inversion accepted under Owner standing technical delegation for planned 5.1.2 release.
  - `Valeneko-pranmong/Neko-Family-Proxy` is planned as the permanent machine-update channel for dormant and active clients.
  - Human installer surface is planned to be separated into a dedicated installer repository (e.g. `Valeneko-pranmong/Neko-Family-Proxy-Installer`).
- Deferred Update Lifecycle: Implemented and tested on `feature/neko-family-5.1.2`:
  - Background staging (`SoftwareUpdateStageService`) downloads changed components while sessions remain active.
  - Durable pending store (`PendingUpdateStore`) verifies signed envelopes and reconstructs trust offline.
  - Session activity guard (`SessionActivityGuard`) guarantees updates never forcibly terminate game (`pso2.exe`) or proxy sessions.
  - Safe apply pathways: explicit Update action, normal exit, and next-launch offline bootstrap (`try_apply_pending_on_launch`).
  - Reuses existing `NekoUpdater.exe` transactional engine, probation runner, rollback, and anti-downgrade machinery.
- Bounded Bootstrap Authority: Implemented in `scripts/release_controller.py` to enable initial machine release from `v5.1.0` Attempt-3 signed archive; strictly bounded to `v5.1.0` and auto-disabled for subsequent releases.
- Remediations:
  - Installer Core authority handoff bound dynamically to build authority (`verify-core-install.ps1`).
  - Canonical Launcher title bar version display bound to `neko_launcher.__version__`.
- Status: Tasks 1-9 complete and independently reviewed C0/I0 on `feature/neko-family-5.1.2`. Task 10 branch documentation and full suite acceptance active. Pending R10/Main Source Acceptance/merge/release gates. No production backend/release mutation has occurred.

## User-facing readiness
- Public production release remains `v5.1.0` (installer-only). In-app automatic updates are NOT yet available for production users; public v5.1.0 users continue to use manual installer setup until post-merge release gates are executed.
- Deferred update lifecycle and Two-Repo Role Inversion are implemented and tested strictly on `feature/neko-family-5.1.2` and await R10 review, Main Source Acceptance, merge to `main`, and future release engineering gates before public availability.
- No production backend or release mutation has occurred. The dedicated installer repository and public machine-update backend do not exist publicly yet.

## Next work
1. Complete R10 independent final architecture/security/regression review (card `t_6d0a2950`).
2. Pass G2 C0/I0 gate (`t_b0931a99`).
3. Conduct Main Source Acceptance against exact branch HEAD (`t_ad651015`).
4. Merge accepted branch HEAD to `main` (`t_8fcf4c10`).
5. Run post-merge CI/source acceptance (`t_6638b7d3`).
6. Execute release engineering gates (H1 hosted bootstrap proof, H2 legacy upgrade proof, R13 release acceptance).

## Do not accidentally change
- Do not claim release completion, production readiness, or public availability during local branch acceptance.
- Do not mutate or replace public `v5.1.0` release assets; no production release or backend mutation has occurred.
- Do not bypass fail-closed cryptographic verification of the signed manifest or component digests.
- Do not modify `launcher/tests/test_config.py` to hide pre-existing baseline asset defects.
- Do not expose signing private-key bytes.

## Authoritative reference documents
- Architecture: `docs/superpowers/specs/2026-09-12-neko-family-5-1-2-update-architecture.md`
- Implementation Plan: `docs/superpowers/plans/2026-09-12-neko-family-5-1-2-implementation.md`
- Controller Ledger: `E:\Github\Project manager\current\CONTROLLER_LEDGER_NEKO_FAMILY_5_1_2.md`
- Accepted v5.1.0 archive: `E:\Github\artifacts\v5.1.0-clean-candidate\attempt-3\`

## First checks for a new maintainer
1. `git status --short --branch`
2. `git rev-parse HEAD` and `git rev-parse origin/main`
3. `launcher/.venv/Scripts/python.exe -B scripts/check_repository_safety.py`
4. `cd launcher && .venv/Scripts/ruff.exe check src tests`
5. `cd launcher && .venv/Scripts/pytest.exe -p no:cacheprovider -q --tb=short`
