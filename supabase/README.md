# Launcher Supabase database

The migrations in this directory define the server-side foundation for the launcher:

- Supabase Auth users are mirrored into `public.profiles`.
- `public.products` and `public.licenses` define product access and expiry.
- `public.installations` tracks a privacy-preserving installation hash.
- `public.launcher_sessions` enforces one active launcher session per user.
- `launcher.claim_session`, `launcher.heartbeat_session`, and `launcher.release_session` are the only intended client write paths.
- Row-level security is enabled on every public table created here.
- Customer registration uses a username, password, and recovery email. The
  username is the login identifier; the email is stored only for password
  reset and is not confirmed during registration.

The `launcher` schema is included in the Supabase Data API exposed schemas by
`20260725131024_expose_launcher_schema_to_data_api.sql`. The desktop client must
use only a publishable key. A secret/service-role key belongs only in a trusted
admin service or Edge Function.

The launcher resolves a username to the current `auth.users.email` through
`launcher.auth_email_for_username(text)` before calling Supabase Auth. The
lookup joins by the stable user UUID, so the Launcher keeps working before and
after a trusted Auth Admin API email migration. The older boolean
`launcher.user_exists(text)` preflight is intentionally revoked from public
clients because it is redundant and creates an account-enumeration endpoint.
Session, entitlement, and coupon RPCs remain authenticated-only.

The current database project is the dedicated `Neko-Family-Proxy` project.
The core/auth/session migrations through
`20260725081929_link_launcher_sessions_to_licenses.sql` and the coupon migration
`20260725110225_create_coupon_redemption.sql` are applied to that project.
The follow-up migration
`20260725130737_harden_coupon_concurrency_and_privileges.sql` is also applied;
it serializes license updates across concurrent coupon redemptions, removes
direct client table-write privileges, and adds the missing coupon-attempt
foreign-key index.
The legacy coupon RPC access revocation
`20260725160000_revoke_legacy_coupon_rpc_access.sql` removes authenticated
client access to the superseded Admin functions; the Admin console uses only
the actor-checked `admin_*` RPCs.
The recovery email column and username-to-email lookup
`20260726112000_add_recovery_email_auth_lookup.sql` are applied in production.
The local follow-up
`20260729002946_restore_recovery_email_auth_flow.sql` restores the RPC after the
later removal migration, pins function search paths, and narrows execution
privileges. Inspect production migration history before applying it; do not
replay older migrations blindly.
Before enabling the coupon UI, run the security and concurrency test plan
against test accounts and confirm that the `launcher` schema is exposed through
the Data API.

The required test cases are documented in
[`SECURITY_TEST_PLAN.md`](SECURITY_TEST_PLAN.md).

The repository also includes an environment-gated live client test for Auth,
Coupon replay, and launcher-session takeover. Run the manual
`Supabase integration` GitHub Actions workflow with disposable credentials.
The coupon replay case runs only when a fresh `NEKO_INTEGRATION_COUPON` secret
is supplied and consumes that coupon.

## Auth and database cleanup

For local Supabase, `config.toml` disables email confirmation. For the hosted
`miikoutrnxsunbndecqh` project, **Confirm email** is disabled under
Authentication → Sign In / Providers and must remain disabled because the
launcher intentionally does not require email confirmation during signup.
Password recovery still sends a normal Auth reset link to the stored email.

The live schema audit on 2026-07-26 found nine public tables. Every table is
referenced by an Auth trigger, an entitlement/session RPC, a coupon RPC, or a
foreign key. No unused table was removed; deleting any of them would break an
active flow. The username migration adds `profiles.username` and a
case-insensitive unique index while preserving existing accounts.
