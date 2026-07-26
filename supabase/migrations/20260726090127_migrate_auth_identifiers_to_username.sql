-- Existing accounts in this dedicated project must continue to work after
-- emailless registration is enabled. Replace their Auth email-shaped
-- identifier with the same synthetic identifier used for new accounts.

update auth.users u
set
  email = p.username || '@miikoutrnxsunbndecqh.supabase.co',
  raw_user_meta_data = coalesce(u.raw_user_meta_data, '{}'::jsonb)
    || jsonb_build_object(
      'username', p.username,
      'display_name', coalesce(p.display_name, p.username)
    ),
  email_confirmed_at = coalesce(u.email_confirmed_at, now()),
  updated_at = now()
from public.profiles p
where p.id = u.id
  and p.username is not null
  and u.email not like '%@auth.neko.local';
