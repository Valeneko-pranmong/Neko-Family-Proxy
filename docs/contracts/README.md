# Launcher Contract Artifacts — P0

**Status:** DRAFT FOR CONTRACT SIGN-OFF, not authoritative
**Date:** 2026-10-25
**Repository:** `D:\Neko-Family-Proxy` (Windows launcher, installer, updater, release surface)
**Baseline:** NEKO Unified Platform shared context, contract baseline v0 (locked 2026-10-25)
**Audited revision:** `9f34b1e` (`main`)

This directory contains this repository's side of the P0 contract review. The
future `Neko-Contracts` repository (not created) will be the single authority for
the OpenAPI document, JWT claims, error codes, generated clients, and fixtures.
Nothing here overrides the shared baseline; it records what the Launcher needs
from that baseline and where the current repository conflicts with it.

No runtime code, schema, deployment, tag, or publication is changed by these
documents.

## Scope of this repository's P0 contribution

The new Launcher line:

- calls the identity provider only for browser login, code exchange, token
  refresh, and sign-out;
- calls **Neko Proxy API only** for all proxy-domain reads and writes;
- holds no Supabase URL, key, session, cookie, or direct PostgREST/RPC client;
- never uses a service-role key or an admin service token;
- does not use the `launcher_bridge`, `launcher_v2.web_sessions`,
  `launcher_v2.identity_links`, or any bridge session-minting path.

The frozen `5.1.6` line keeps its existing legacy password/recovery and
Supabase backend until the `5.3.0` cutover. Its code and tests must remain
working.

## Artifacts

| File | Purpose |
| --- | --- |
| [launcher-consumer-contract.md](launcher-consumer-contract.md) | Endpoint-by-endpoint consumer obligations, token lifecycle, permit handling, error mapping, and security invariants for the new Launcher line. |
| [gap-and-conflict-register.md](gap-and-conflict-register.md) | Evidence-backed conflicts between the current repository and contract v0, with severity, owner, and required resolution. |
| [p0-signoff-checklist.md](p0-signoff-checklist.md) | Decisions the contract owner must ratify, P1 entry criteria, proposed implementation slices, and verification gates. |

## Current documents superseded for the new line

The following documents describe the earlier 5.2.0 design (isolated
`launcher_v2` schema in the same Supabase project, `launcher_bridge` session
minting, web-session allowlist). They remain historical/5.1.6 context but are
**not valid for the new Launcher line**:

- `docs/current/web-auth-launcher.md`
- `docs/current/p0-p5-status-audit.md`
- `docs/current/launcher-bridge-staging-runbook.md`
- `docs/superpowers/plans/2026-10-25-web-auth-separation-and-5-3-0-cutover.md`

The shared baseline's non-negotiables (one identity pool; Launcher -> Neko
Proxy API only; no bridge session minting; no synthetic proxy auth users; no
`web_sessions` allowlist) supersede those documents wherever they conflict.
Do not start a new implementation slice from them without reconciling this
register first.

The current replacement direction and slice-1 implementation contract are in
`docs/current/5.3.0-proxy-api-launcher.md` and
`docs/current/proxy-api-launcher-contract.md`.

## Evidence method

- Read-only review of the Launcher source, tests, `supabase/functions`, and
  `supabase/migrations` at `9f34b1e`.
- Read-only review of the identity repository's live launcher token endpoint
  and JWT claims for cross-repo contract context.
- No credential, token, or key material was read, copied, or written.
- No migration, deployment, or production call was made.

## P0 exit statement

P0 is complete only when every blocker in the conflict register has an owner
decision and the contract owner has frozen the additions listed in the
sign-off checklist. The owner has explicitly authorized one limited source/dev
P1 slice 1 (the `NEKO_PROXY_API_URL` account-status preflight described in
`docs/current/5.3.0-proxy-api-launcher.md`) while those decisions remain open.
That exception does not close this register, does not authorize
claim/permit/coupon work, and does not authorize a build, deployment, or
publication. All other P1 work waits for sign-off.
