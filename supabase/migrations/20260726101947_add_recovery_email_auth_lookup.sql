-- Store a real recovery email separately from the user-facing username.
-- Auth uses this email for password reset; username remains the login ID.

alter table public.profiles
  add column if not exists recovery_email text;

alter table public.profiles
  drop constraint if exists profiles_recovery_email_format_check;

alter table public.profiles
  add constraint profiles_recovery_email_format_check
  check (
    recovery_email is null
    or recovery_email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'
  );

create unique index if not exists profiles_recovery_email_lower_key
  on public.profiles (lower(recovery_email))
  where recovery_email is not null;

create or replace function launcher.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, launcher, pg_temp
as $$
declare
  v_username text;
  v_recovery_email text;
begin
  v_username := lower(
    left(
      regexp_replace(
        coalesce(
          new.raw_user_meta_data ->> 'username',
          new.raw_user_meta_data ->> 'display_name',
          split_part(coalesce(new.email, ''), '@', 1)
        ),
        '[^a-zA-Z0-9_]',
        '_',
        'g'
      ),
      32
    )
  );
  v_recovery_email := lower(
    nullif(
      coalesce(new.raw_user_meta_data ->> 'recovery_email', new.email),
      ''
    )
  );

  insert into public.profiles (id, username, display_name, recovery_email)
  values (
    new.id,
    nullif(v_username, ''),
    nullif(left(coalesce(new.raw_user_meta_data ->> 'display_name', v_username), 80), ''),
    v_recovery_email
  )
  on conflict (id) do update
    set username = coalesce(public.profiles.username, excluded.username),
        display_name = coalesce(public.profiles.display_name, excluded.display_name),
        recovery_email = coalesce(public.profiles.recovery_email, excluded.recovery_email),
        updated_at = now();
  return new;
end;
$$;

revoke all on function launcher.handle_new_user() from public;

create or replace function launcher.auth_email_for_username(p_username text)
returns text
language sql
stable
security definer
set search_path = public, launcher, pg_temp
as $$
  select recovery_email
  from public.profiles
  where lower(username) = lower(trim(p_username))
    and status = 'active'
  limit 1;
$$;

revoke all on function launcher.auth_email_for_username(text) from public;
grant execute on function launcher.auth_email_for_username(text) to anon, authenticated;
