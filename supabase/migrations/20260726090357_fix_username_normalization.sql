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
        '[^a-zA-Z0-9_]',
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
