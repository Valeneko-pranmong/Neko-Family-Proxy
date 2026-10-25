# Launcher Web Auth — Implementation Status

**Status:** Launcher-side loopback/PKCE/token/bridge adapter implemented on 2026-10-25. Gated off by default. Identity endpoints are live on staging. A reference proxy bridge is implemented in `supabase/functions/launcher_bridge/` (identity JWT/JWKS validation, JTI replay, identity link, session mint, web-session allowlist) but is not deployed; identity→proxy mapping and E2E are not complete. **Policy decision (2026-10-25):** 5.2.0 is a new-accounts-only web-auth line using an isolated schema in the same Supabase project; 5.1.6 remains on legacy password/recovery until the 5.3.0 cutover; there is no day/coupon transfer. See the separation plan.

## Live identity contract

```text
Authorize: GET https://neko-network-id.vercel.app/launcher/authorize
Token:     POST https://neko-network-id.vercel.app/api/launcher/token
JWKS:      GET https://neko-network-id.vercel.app/.well-known/jwks.json
Client:    neko-launcher
Redirect:  http://127.0.0.1:53682/auth/callback (exact)
```

- PKCE `S256` is mandatory; `plain` is not accepted.
- `state` is 43–128 characters and validated by exact comparison.
- Authorization code is opaque, single-use, and expires after 60 seconds.
- Callback success: `?code=...&state=...`
- Callback failure: `?error=access_denied|server_error&error_description=...&state=...`
- Identity token: custom RS256 JWT, 5-minute lifetime, `aud=neko-launcher-bridge`, `scope=launcher:login`, `jti` for bridge replay protection. It is not a Supabase session.

## Launcher implementation

- [`web_auth.py`](file:///D:/Neko-Family-Proxy/launcher/src/neko_launcher/infrastructure/auth/web_auth.py): PKCE/state generation, one-use loopback HTTP receiver bound to `127.0.0.1`, identity token exchange, bridge session exchange, bounded HTTPS JSON transport, and user-safe error mapping.
- `SupabaseGateway.sign_in_with_web()`: adopts the bridge-returned Supabase access/refresh tokens with `set_session()` and resolves the existing authenticated user.
- `LauncherService.sign_in_with_web()`: runs the session claim and entitlement flow using the same `claim_session` / `issue_launch_permit` path as password login.
- `AuthView` / `AppWindow`: optional “เข้าสู่ระบบด้วย Discord” button during development. The 5.2.0 release target removes password/recovery from the product; 5.1.6 retains them on the separate legacy line.
- The identity token is kept only in memory for the bridge exchange. Only the resulting Supabase session is persisted through the existing Windows Credential Manager store.
- The loopback server suppresses request logging, validates the exact path and `Host`, rejects duplicate query keys, applies no-store/no-referrer-style response headers, and closes after the first valid callback.

## Configuration

```text
NEKO_WEB_AUTH_ENABLED=1
NEKO_AUTH_BRIDGE_URL=https://<proxy-backend>/auth/launcher/exchange
NEKO_IDENTITY_BASE_URL=https://neko-network-id.vercel.app   # optional override
```

The web button is hidden unless both the enable flag and a non-empty bridge URL are present. There is no remote identity-side feature flag; the Launcher flag is the rollout gate.

## Bridge contract required from the proxy backend

```text
POST https://<proxy-backend>/auth/launcher/exchange
Authorization: Bearer <identity access_token>
```

The bridge must:

1. Validate RS256 through the identity JWKS (`kid`, `iss`, `aud`, `exp`, `nbf`).
2. Reject a reused `jti` with `409 token_replayed`.
3. Resolve `sub` through `launcher.identity_links`; missing mapping returns `409 identity_not_linked`.
4. Mint a real Supabase session for the mapped proxy user (the agreed design uses `generateLink({type:'magiclink'})` then `verifyOtp`).
5. Return `token_type`, `access_token`, `refresh_token`, `expires_in`, with no-store semantics.
6. Never log the identity token.

The Launcher maps `401 invalid_token`, `409 token_replayed`, `409 identity_not_linked`, `429 rate_limited`, and `503 upstream_unavailable` to fixed user-facing messages.

## Remaining blockers before E2E

- The reference bridge is not deployed to staging; use [launcher-bridge-staging-runbook.md](launcher-bridge-staging-runbook.md) for the deployment/E2E sequence.
- `launcher_v2.identity_links` migrations exist but are not applied and no test mapping exists.
- Discord test account and proxy test account with entitlement are not available.
- The one-time link/claim flow is agreed in principle but `/launcher/link` and the bridge-side create/consume operations are not implemented.
- Product decisions remain for new users without a proxy account, unlink, Discord ban, and legacy password recovery.
- A decision is needed on whether unlinked users see a link-code flow or a support/manual path.

## Rollout and line separation

- Do not enable the web button in production or publish a release containing the enabled path until the bridge, mapping, claim flow, and staging E2E pass.
- 5.1.6 remains the public stable line with password/recovery on the legacy backend; do not force it to 5.2.0.
- 5.2.0 is a new-accounts-only preview line using an isolated schema in the same Supabase project. It is web-auth-only at release, must not retain password/recovery fallback, must not be installed over or alongside 5.1.6, and must not become the latest stable update for 5.1.6.
- 5.2.0 uses a dedicated preview channel and a clean local start; legacy 5.1.6 users stay on their existing term and receive no day/coupon transfer.
- 5.3.0 is the cutover release after the bridge, mapping, link/claim, Control Room admin web auth, and E2E are complete; legacy shutdown is gate-based and waits for the last active term or an explicit cutoff.
- No release/tag/publish is authorized by this document. The authoritative development sequence is [`../superpowers/plans/2026-10-25-web-auth-separation-and-5-3-0-cutover.md`](../superpowers/plans/2026-10-25-web-auth-separation-and-5-3-0-cutover.md).
