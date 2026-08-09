-- Backfill recovery_email for existing users who were registered before
-- the recovery_email column was added.
update public.profiles p
set
  recovery_email = lower(trim(
    coalesce(
      nullif(trim(u.raw_user_meta_data ->> 'recovery_email'), ''),
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
