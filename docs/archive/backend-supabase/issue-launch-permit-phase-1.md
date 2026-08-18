# Backend/Supabase Phase 1 — `issue_launch_permit`

**Workspace:** `E:\Github\Neko-Family-Proxy-backend`
**Branch:** `backend/production-permit`
**Base:** `072ea6e4801debfaa55e03c89213a75e13cbca58`
**Hosted project:** `miikoutrnxsunbndecqh`
**Production mutation:** none

## Authority model

Supabase Auth validates the caller and supplies `auth.uid()` plus the validated
JWT `session_id`. `public.launcher_sessions` remains the only current Launcher
authority and retains its unique partial index on `user_id where revoked_at is
null`. `claim_session` still transactionally replaces the prior active session.
Products/licenses/profiles/installations retain their existing meanings; there
is no permanent installation lock.

The Phase 1 migration binds each newly claimed Launcher session to the Auth
session that performed the claim. The permit RPC requires both user and Auth
session to match, verifies that the Auth session still exists and is unexpired
in `auth.sessions`, and checks active profile/product/license, ownership joins,
an unrevoked Launcher session, and heartbeat freshness within 90 seconds.
Historical rows without an Auth-session binding fail closed and become eligible
only after the normal Launcher reclaims a session.

Permit authorization and challenge reservation run under the same per-user
transaction advisory lock as `claim_session`, defining the issuance
linearization point and preventing replacement from interleaving with the
current decision. Reusing an Auth-session/challenge pair is rejected. A separate
per-user rate ledger survives Auth-session deletion and limits each user to 10
reservations per rolling minute. Once signed, the permit
is an intentionally non-retractable 30-second capability; subsequent revocation
controls later issuance rather than retroactively invalidating that snapshot.

## Trust boundaries

The client supplies only the exact `s0-rc1` transaction body. The Backend derives
`sub`, `sid`, `iid`, `lid`, `iss`, `aud`, timestamps, lifetime, `jti`, and `kid`.
Unknown fields, including attempts to supply those identity claims, are rejected.
The function uses a caller-scoped publishable-key Supabase client; it does not
use or expose a service-role key and does not weaken table RLS.

## Core contract confirmation

Inspected `E:\Github\NekoProxyCore` on `feature/neko-headless` at
`ac9f5018d5f4183e4d5e7a0deced85e753c9482b`:

- `StrictLaunchPermitVerifier.cs` requires exact 3-segment RS256 JWT; exact
  header/claim sets; `typ=neko-launch+jwt`; `iss=neko-backend`;
  `aud=neko-proxy-core`; product/scope/mode/binding claims; `exp=iat+30`; and
  2-second clock skew.
- Core validates 43-character unpadded base64url challenges, canonical config
  digest, target PID, exact known `kid`, and atomically consumes JTI replay state.
- `ProductionPublicKeys.cs` and the bundled manifest pin
  `kid=neko-prod-key-2` and one immutable RSA public key. The old
  `neko-prod-key-1` contract is PRE-LAUNCH RETIRED and rejected.

The Phase 1 signing blocker was operational. Phase 2.5-K provisions generation 2
under approved custody and requires proof that configured `RS256_PRIVATE_KEY`
matches the bundled Core public key; only public fingerprints may be recorded.

## Deployment gates

Before production deployment:

1. Preserve the already-closed database migration and authorization gates.
2. Prove under approved key custody that `RS256_KID=neko-prod-key-2` and the
   backend private key signs a permit accepted by the exact released Core public
   key; do not export the private key as evidence.
3. Run real Launcher → hosted function → released Core integration.
4. Obtain Backend Security/Core/Launcher review. Continuous renewal and S1 remain
   separate release gates documented by the central handoff.

No production database, Edge Function, secret, migration history, Launcher
source, Core source, remote branch, or deployment was modified in Phase 1.
