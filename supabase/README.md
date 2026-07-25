# Launcher Supabase database

The migrations in this directory define the server-side foundation for the launcher:

- Supabase Auth users are mirrored into `public.profiles`.
- `public.products` and `public.licenses` define product access and expiry.
- `public.installations` tracks a privacy-preserving installation hash.
- `public.launcher_sessions` enforces one active launcher session per user.
- `launcher.claim_session`, `launcher.heartbeat_session`, and `launcher.release_session` are the only intended client write paths.
- Row-level security is enabled on every public table created here.

The `launcher` schema is included in the Supabase Data API exposed schemas by
`20260725131024_expose_launcher_schema_to_data_api.sql`. The desktop client must
use only a publishable key. A secret/service-role key belongs only in a trusted
admin service or Edge Function.

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
