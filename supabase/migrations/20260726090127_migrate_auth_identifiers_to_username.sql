update auth.users u
set
  email = p.username || '@auth.neko.local',
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
