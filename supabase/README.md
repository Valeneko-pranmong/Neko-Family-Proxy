# Launcher Supabase database

> **Status: CURRENT — reviewed 8 August 2026.** Production permit issuance is
> separate and remains blocked; see the prototype warning under
> [`functions/issue_launch_permit/README.md`](functions/issue_launch_permit/README.md).

The migrations in this directory define the server-side foundation for the launcher:

- Supabase Auth users are mirrored into `public.profiles`.
- `public.products` and `public.licenses` define product access and expiry.
- `public.installations` tracks a privacy-preserving installation hash.
- `public.launcher_sessions` enforces one active launcher session per user.
- `launcher.claim_session`, `launcher.heartbeat_session`, and `launcher.release_session` are the only intended client write paths.
- Row-level security is enabled on every public table created here.
- Customer registration uses only a username and password. The username is
  converted to a deterministic internal Auth identifier by the Launcher.

The `launcher` schema is included in the Supabase Data API exposed schemas by
`20260725131024_expose_launcher_schema_to_data_api.sql`. The desktop client must
use only a publishable key. A secret/service-role key belongs only in a trusted
admin service or Edge Function.

The launcher derives a deterministic, non-PII Auth identifier from the
normalized username and the Supabase project hostname before calling Supabase
Auth. It never queries a public RPC for `auth.users.email`, and the real
historical `public.profiles.recovery_email` column remains nullable during the
rollback window but new Launcher versions do not write it. The legacy
`auth_email_for_username(text)` and
`user_exists(text)` functions must remain absent (or have no client execute
privilege) because either endpoint would create an account-enumeration or PII
disclosure risk. Session, entitlement, and coupon RPCs remain
authenticated-only.

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
`20260725142015_revoke_legacy_coupon_rpc_access.sql` removes authenticated
client access to the superseded Admin functions; the Admin console uses only
the actor-checked `admin_*` RPCs.
The recovery email column from
`20260726101947_add_recovery_email_auth_lookup.sql` exists in the historical
schema. The local forward-fix
`20260729053740_secure_option_a_recovery_flow.sql` removes the unsafe lookup
functions and canonicalizes the trigger for internal Auth identifiers. The
intermediate migration is archived at
`supabase/blocked_migrations/20260729002946_restore_recovery_email_auth_flow.sql.blocked`.
It is intentionally outside the active migration directory and must not be
renamed, applied, or replayed against hosted production.
Before enabling the coupon UI, run the security and concurrency test plan
against test accounts and confirm that the `launcher` schema is exposed through
the Data API.

The required test cases are documented in
[`security-test-plan.md`](security-test-plan.md).

The repository also includes an environment-gated live client test for Auth,
Coupon replay, and launcher-session takeover. Run the manual
`Supabase integration` GitHub Actions workflow with disposable credentials.
The coupon replay case runs only when a fresh `NEKO_INTEGRATION_COUPON` secret
is supplied and consumes that coupon.

The forward migration
`20260809133000_remove_permanent_installation_lock.sql` completes the transition
to remembered installation history plus one active Launcher session. It clears
legacy `installations.revoked_at` values without changing accounts, licenses, or
historical sessions; removes installation revocation from `claim_session`; and
removes the obsolete Admin installation-revocation RPC. Apply it to staging
first and compare the live function definitions, grants, RLS, and unique partial
session index before production approval; this repository change does not
modify production.

## Auth and database cleanup

For local Supabase, `config.toml` disables email confirmation. For the hosted
`miikoutrnxsunbndecqh` project, **Confirm email** is disabled under
Authentication → Sign In / Providers because the launcher does not require
email confirmation during signup. Forgotten passwords use the server-side,
Admin-generated temporary Recovery Code flow from
`20260809120000_account_recovery_codes.sql`. Recovery Codes are
single-use, expire after approximately five minutes, enforce failed-attempt
lockout, and create a temporary `change_password` Recovery Session. Completing
recovery revokes active Launcher sessions. The historical recovery-email column
is not recovery authority, and password-reset email is not an active product
flow.

The live schema audit on 2026-07-26 found nine public tables. Every table is
referenced by an Auth trigger, an entitlement/session RPC, a coupon RPC, or a
foreign key. No unused table was removed; deleting any of them would break an
active flow. The username migration adds `profiles.username` and a
case-insensitive unique index while preserving existing accounts.
