# Launcher Supabase database

The migrations in this directory define the server-side foundation for the launcher:

- Supabase Auth users are mirrored into `public.profiles`.
- `public.products` and `public.licenses` define product access and expiry.
- `public.installations` tracks a privacy-preserving installation hash.
- `public.launcher_sessions` enforces one active launcher session per user.
- `launcher.claim_session`, `launcher.heartbeat_session`, and `launcher.release_session` are the only intended client write paths.
- Row-level security is enabled on every public table created here.

The `launcher` schema must be added to the Supabase Data API exposed schemas before the desktop client calls these RPCs. The desktop client must use only a publishable/anon key. A service-role key belongs only in a trusted admin service or Edge Function.

The current database project is the dedicated `Neko-Family-Proxy` project.
The core/auth/session migrations through
`20260725081929_link_launcher_sessions_to_licenses.sql` have been prepared for
that project. The coupon migration
`20260725091805_create_coupon_redemption.sql` is currently local/pending and
must be verified and applied through an authorized Supabase workflow before
the coupon UI is enabled.
