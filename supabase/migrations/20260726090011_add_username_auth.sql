-- User-facing authentication uses a username.
alter table public.profiles
  add column if not exists username text;

update public.profiles p
set username = lower(
  left(
    regexp_replace(
      coalesce(
        nullif(p.display_name, ''),
        split_part(coalesce(u.email, ''), '@', 1),
        'user_' || replace(p.id::text, '-', '')
      ),
      '[^a-zA-Z0-9_-]',
      '_',
      'g'
    ),
    32
  )
)
from auth.users u
where u.id = p.id
  and p.username is null;

alter table public.profiles
  add constraint profiles_username_format_check
  check (
    username is null
    or username ~ '^[a-zA-Z0-9][a-zA-Z0-9_]{2,31}$'
  );

create unique index if not exists profiles_username_lower_key
  on public.profiles (lower(username))
  where username is not null;

create or replace function launcher.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, launcher, pg_temp
as $$
declare
  v_username text;
begin
  v_username := lower(
    left(
      regexp_replace(
        coalesce(
          new.raw_user_meta_data ->> 'username',
          new.raw_user_meta_data ->> 'display_name',
          split_part(coalesce(new.email, ''), '@', 1)
        ),
        '[^a-zA-Z0-9_-]',
        '_',
        'g'
      ),
      32
    )
  );

  insert into public.profiles (id, username, display_name)
  values (
    new.id,
    nullif(v_username, ''),
    nullif(left(coalesce(new.raw_user_meta_data ->> 'display_name', v_username), 80), '')
  )
  on conflict (id) do update
    set username = coalesce(public.profiles.username, excluded.username),
        display_name = coalesce(public.profiles.display_name, excluded.display_name),
        updated_at = now();
  return new;
end;
$$;

revoke all on function launcher.handle_new_user() from public;
