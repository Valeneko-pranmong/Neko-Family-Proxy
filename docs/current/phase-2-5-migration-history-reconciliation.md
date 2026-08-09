# Phase 2.5-R migration history reconciliation

> **Status: CURRENT FORENSIC RECORD — 10 August 2026.** This document records a
> repository-only reconciliation against Supabase project
> `miikoutrnxsunbndecqh`. It does not authorize or record hosted DDL, migration
> repair, Edge Function deployment, or signing-secret changes.

## Evidence boundary

- Repository base: `6f23bce894901f9be8d4c8512543822924643284`.
- Hosted applied history: 28 rows through
  `20260809133000_remove_permanent_installation_lock`.
- Hosted `supabase_migrations.schema_migrations` was queried in a read-only
  transaction. Version, name, ordered `statements`, and safe SHA-256 values were
  compared with every repository migration.
- No hosted migration-history row or hosted schema object was modified.
- The two later authorization migrations remain unapplied and outside this
  reconciliation.

The `statements` arrays for `20260809120000_account_recovery_codes` and
`20260809124500_fix_recovery_verify_column_ambiguity` are empty in hosted
history. Their non-empty repository SQL was therefore preserved rather than
replaced by missing evidence. Their current effect is verified from the live
catalog and disposable full-chain replay.

## Canonical timestamp and SQL mapping

`Exact` means the same executed SQL apart from newline serialization.
`Equivalent` means text or comments differ but the executable SQL operation
stream is identical. `Different` means the old repository file did not
accurately represent the individual hosted migration, so the canonical file
was reconstructed from the exact hosted statement.

| Old repository file | Hosted canonical file | Old file SHA-256 | Hosted exact statement SHA-256 | Result |
| --- | --- | --- | --- | --- |
| `20260726090200_fix_username_normalization.sql` | `20260726090357_fix_username_normalization.sql` | `d26c4a8bd58601e95f35992d347fe44eeb00c33eb3207a23e237f169e3b183d4` | `07b758f717fa09d9b4545f975a739b69af8c27f60dfdef130cb395aa07a8f788` | **Equivalent**; comment-only drift |
| `20260726100000_add_username_lookup_rpc.sql` | `20260726091945_add_username_lookup_rpc.sql` | `8a5f7858c26e29cbf88b85c7d9a598db7a5e1abacca1409d9da28cab1f53a91e` | `a5a879479dd1f9f720a8b178350ffebaa0f08cb62b67d4427b193d74e0327539` | **Equivalent**; comment whitespace only |
| `20260726103000_migrate_synthetic_auth_domain.sql` | `20260726093019_migrate_synthetic_auth_domain.sql` | `08c7172ed9bd1d222b20128a1e0cabd5efea6af34afe301383260f99dccad419` | `b10619f2acab4dd70129d1d12ac91cef5f43b9478c72bff49c041fad42f69c8c` | **Different**; hosted moved `.local` to `.family`, then the next hosted migration moved `.family` to the project domain |
| `20260726103500_use_project_auth_domain.sql` | `20260726093232_use_project_auth_domain.sql` | `0bb137cb560583ac25331e8eddac49a188533ac57956ad1737539083befc1f28` | `0e184db365943856d3281b7a11a397bbf6e72fa757621c20c2ffe0a0a6ae3527` | **Exact** after newline normalization |
| `20260726112000_add_recovery_email_auth_lookup.sql` | `20260726101947_add_recovery_email_auth_lookup.sql` | `0e18bb2383c4302d873c2aca857aae2f127bf12ad1e131fe36783b264fab26af` | `c452009241b902b4a179bd79ad7dc496e8771590f6d31a4e2f1ba7bd6801725e` | **Exact** after newline normalization |
| `20260727200000_backfill_recovery_email.sql` | `20260727132751_backfill_recovery_email.sql` | `09766cb01c0b80c55fa28345edffd692f0e6fd755abbbe1d95013d2c9a62e868` | `f1645723b0ce1640b27e887ccc271a48a455e829980fbf02ab0ec4430efe2b50` | **Equivalent**; comments only |
| `20260728150000_fix_pgcrypto_search_path.sql` | `20260728145033_fix_pgcrypto_search_path.sql` | `1df33b3d25b36d944f7a514676097b2164e6aebb49665f75ea64cf92ce773e03` | `d6c1ee8331c1d0ad1dbcecf81b4b00f6a2821aca2654b30566eac8d0c62fe516` | **Exact** after newline normalization |
| `20260728145445_delete_coupon_batch.sql` | `20260728145651_delete_coupon_batch.sql` | `4ffd42e5d1b9ab2deefa07448c87a5a4ed5a964520976b1f9084f6a216a68b47` | `e67b357bf3723dcc8b2cf122656edd40676825a884c94a0992152c12c3124932` | **Exact** after newline normalization; hosted order preserved |
| `20260728150550_disposable_coupons.sql` | `20260728150821_disposable_coupons.sql` | `95c102bf9522fa12b013345f69ddb1be8962cce90ed11a20f784bb777fb05e61` | `b026a6eec11023e73f42b447b1acb43496da92788c4879857ec274c7bd265dea` | **Exact** after newline normalization; hosted order preserved |
| `20260729120000_secure_option_a_recovery_flow.sql` | `20260729053740_secure_option_a_recovery_flow.sql` | `b42097954f1cca2b8e7c33182ecb1e0b4b1876de2930f93f0283be34d29e4cbc` | `0020928075127bec7864d0770215130ab4593223750d7380f5f4bb5cb0418276` | **Equivalent**; comments only |

Two files already had the hosted version and name but contained later local
rewrites. They were also reconstructed from hosted statements:

| File | Old file SHA-256 | Hosted exact statement SHA-256 | Historical difference |
| --- | --- | --- | --- |
| `20260726090011_add_username_auth.sql` | `28a9fa98f6483d849e86a2b43b10fe2f01465839814cf6194c85d4ea31e1ce73` | `36f206df348cc4df680c30a3c3b32c0800b4f70b713d2d83af5c550cbad81027` | Hosted normalization initially allowed hyphens; the later fix migration tightened the format |
| `20260726090127_migrate_auth_identifiers_to_username.sql` | `dfa2921cd479f679decfd8d277ab42c0ab86d6e6f379de0302c5b10ca4c72cba` | `6143e3970256bb5e5230af87ce44df26584c4d52bbad9438815c5b3b24043551` | Hosted first used `@auth.neko.local`; later hosted migrations performed the two-step domain transition |

## Local-only recovery migration

`20260727141009_remove_recovery_email.sql` was not applied to the hosted
project. Its old file SHA-256 was
`f9945d2a4dd2144a8933a5d5dd9ae10c9873ff108a15b4a81abc719db4e5930c`.
It was an undeployed local experiment and is removed from the canonical active
migration directory. Its intended security effect is independently present in
hosted `20260729053740_secure_option_a_recovery_flow`, which drops
`launcher.auth_email_for_username(text)` and `launcher.user_exists(text)` while
retaining nullable historical `profiles.recovery_email` schema.

## Recovery history classification

| Migration | Historical classification | Current classification |
| --- | --- | --- |
| `20260726101947_add_recovery_email_auth_lookup` | Historically applied | Superseded; email lookup RPC is inactive and absent |
| `20260727132751_backfill_recovery_email` | Historically applied data migration | Superseded; retained data/schema is not recovery authority |
| `20260727141009_remove_recovery_email` | Historical local-only experiment; never hosted | Superseded by the independently applied hosted security fix; removed from canonical applied history |
| `20260729053740_secure_option_a_recovery_flow` | Historically applied | Its removal of unsafe lookup RPCs remains an active security boundary; its email-oriented recovery design is superseded |
| `20260729065703_add_admin_password_reset_audit_event` | Historically applied | Historical audit event compatibility only; no password-reset RPC is active |
| `20260809120000_account_recovery_codes` | Historically applied | Currently active and authoritative recovery architecture |
| `20260809124500_fix_recovery_verify_column_ambiguity` | Historically applied | Currently active forward fix for Recovery Code verification |

## Current recovery architecture

The authoritative architecture is an Admin-generated temporary Recovery Code,
not password-reset email. The live structural fingerprint confirms:

- `account_recovery_codes`, `account_recovery_sessions`, and
  `account_recovery_rate_limits` exist;
- all five Recovery Code lifecycle RPCs exist;
- `launcher.auth_email_for_username(text)` is absent;
- `profiles.recovery_email` remains historical, nullable schema and does not
  control current recovery authorization.

The migration contract enforces approximately five-minute, one-active,
single-use Recovery Codes with attempt lockout and approximately ten-minute
Recovery Sessions scoped to `change_password`. Completion revokes existing
Launcher sessions. Email reset is neither required nor a current product
recovery authority. Legacy `docs/reset-password/` browser artifacts and hosted
`reset-password` version 4 remain preserved, but no current Launcher call or
live database RPC initiates that flow; this reconciliation did not modify or
deploy them.

## Verification results

- Two independently recreated PostgreSQL clusters each applied exactly 28
  migrations through `20260809133000`; explicit guards excluded
  `20260809150000` and `20260809233000`.
- Fresh replay and hosted state matched across 14 relations, 92 columns, 68
  constraints, 39 indexes, 20 Launcher functions (including definitions,
  security-definer flags, and `search_path` configuration), six RLS policies,
  effective table/function grants, and the Auth user-creation trigger.
- The disposable Recovery Code behavioral matrix passed generation,
  one-active-code replacement, approximately five-minute expiry, five-attempt
  lockout, one-time consumption, approximately ten-minute `change_password`
  session creation, expired-session rejection, and Launcher-session revocation.
- The official linked migration list aligned all 28 applied versions. The
  official `db push --dry-run` listed only:
  - `20260809150000_bind_permits_to_auth_sessions.sql`
  - `20260809233000_bind_session_controls_and_bound_permit_ledgers.sql`
- Backend permit/migration/runtime tests passed 42/42; Deno check and format
  validation passed. Focused Launcher migration/recovery tests passed 14/14.
- Repository safety and Ruff passed. The canonical Launcher non-integration
  suite passed 281 tests with three integration tests deselected in a clean
  disposable Python 3.11.15 environment.
- `git diff --check` and the changed-content secret scan passed.

No hosted apply, migration repair, schema mutation, Edge Function deployment,
or signing-secret change was performed.