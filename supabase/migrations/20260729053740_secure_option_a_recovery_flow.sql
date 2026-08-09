-- Apply the approved Option A forward-fix to the hosted project.
create or replace function launcher.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
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
  if v_username !~ '^[a-z0-9][a-z0-9_]{2,31}$' then
    v_username := 'user_' || left(replace(new.id::text, '-', ''), 27);
  end if;

  v_recovery_email := lower(
    trim(nullif(new.raw_user_meta_data ->> 'recovery_email', ''))
  );

  insert into public.profiles (
    id,
    username,
    display_name,
    recovery_email
  )
  values (
    new.id,
    nullif(v_username, ''),
    nullif(
      left(
        coalesce(new.raw_user_meta_data ->> 'display_name', v_username),
        80
      ),
      ''
    ),
    nullif(v_recovery_email, '')
  )
  on conflict (id) do update
    set username = coalesce(public.profiles.username, excluded.username),
        display_name = coalesce(
          public.profiles.display_name,
          excluded.display_name
        ),
        recovery_email = coalesce(
          public.profiles.recovery_email,
          excluded.recovery_email
        ),
        updated_at = now();

  return new;
end;
$$;

revoke all on function launcher.handle_new_user() from public;
revoke all
  on function launcher.handle_new_user()
  from anon, authenticated, service_role;

drop function if exists launcher.auth_email_for_username(text);
drop function if exists launcher.user_exists(text);
