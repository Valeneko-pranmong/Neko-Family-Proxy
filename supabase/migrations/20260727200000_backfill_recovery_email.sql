-- Backfill recovery_email for existing users who were registered before
-- the recovery_email column was added (migration 20260726112000).
--
-- Strategy:
--   1. If auth.users.email is NOT a synthetic address (@*.supabase.co),
--      use that as recovery_email.
--   2. If auth.users has raw_user_meta_data->>'recovery_email' set,
--      use that.
--   3. Otherwise, leave NULL — the user will be prompted to add one
--      via the UI when they next open the app.

update public.profiles p
set
  recovery_email = lower(trim(
    coalesce(
      -- Prefer explicitly stored recovery_email in metadata
      nullif(trim(u.raw_user_meta_data ->> 'recovery_email'), ''),
      -- Fall back to auth email if it looks like a real address
      case
        when u.email is not null
          and u.email !~ '@[a-z0-9]+\.supabase\.co$'
          and u.email !~ '@auth\.neko\.local$'
          and u.email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'
        then u.email
        else null
      end
    )
  )),
  updated_at = now()
from auth.users u
where u.id = p.id
  and p.recovery_email is null;