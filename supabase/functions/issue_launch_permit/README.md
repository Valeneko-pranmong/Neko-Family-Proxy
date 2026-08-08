# `issue_launch_permit` prototype

> **Status: EXPERIMENTAL / PRODUCTION BLOCKED — reviewed 8 August 2026.**
> Do not deploy this function as a production permit issuer. Production Core
> startup must remain fail closed under the
> [`NEKO-AUTH-S0` release gates](../../../docs/blocked/neko-auth-s0-production-handoff.md).

The adjacent [`index.ts`](index.ts) is a development prototype for constructing
and signing an RS256 launch permit. It is kept beside the function so its
limitations cannot be separated from the code.

## What the prototype demonstrates

- Reading an RS256 private key and key ID from environment variables.
- Parsing a launch-permit request.
- Producing a compact RS256-signed JWT response.
- Returning sanitized HTTP errors for basic malformed requests.

## Security work still required

The current function checks only that the `Authorization` header starts with
`Bearer `. It does **not** validate the Supabase access token or derive trusted
identity, session, installation, license, product, scope, target process, or
configuration claims from authoritative server-side state.

Before production use, the implementation must satisfy the approved contract
and at minimum:

1. Verify the Supabase access token and reject expired, malformed, or wrong-
   project tokens.
2. Derive every security-sensitive claim from trusted server-side data instead
   of accepting it from the request body.
3. Validate entitlement, active launcher session, installation binding,
   challenge format, target process rules, and configuration digest.
4. Enforce permit lifetime, issuer, audience, key rotation, replay controls,
   rate limits, and sanitized audit logging.
5. Add negative-path, integration, and cross-repository tests against the exact
   Core verifier contract.
6. Complete Security, Launcher, Core, and Release acceptance gates.

## Development-only execution

Run the function only against a disposable local Supabase environment:

```powershell
Set-Location supabase
supabase start
supabase functions serve issue_launch_permit --env-file .env.local
```

Keep `.env.local`, private keys, access tokens, and generated permits out of
Git, terminal transcripts, screenshots, and documentation. Use synthetic test
identities and keys only. Secret provisioning and production deployment are
intentionally omitted until the release gates are approved.
