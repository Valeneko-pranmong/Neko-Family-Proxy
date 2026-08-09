-- Let the launcher ask the API whether a username exists before attempting
-- password authentication. Only a boolean is returned; no profile data is
-- exposed to the client.

create or replace function launcher.user_exists(p_username text)
returns boolean
language sql
security definer
set search_path = public, launcher, pg_temp
as $$
  select case
    when p_username is null
      or length(trim(p_username)) not between 3 and 32
      or trim(p_username) !~ '^[a-zA-Z0-9][a-zA-Z0-9_]{2,31}$'
    then false
    else exists (
      select 1
      from public.profiles
      where lower(username) = lower(trim(p_username))
    )
  end;
$$;

revoke all on function launcher.user_exists(text) from public;
grant usage on schema launcher to anon;
grant execute on function launcher.user_exists(text) to anon, authenticated;

notify pgrst, 'reload config';
