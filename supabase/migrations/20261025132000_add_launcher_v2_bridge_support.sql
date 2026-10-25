-- P1 bridge support. All functions and tables here are service_role-only.
-- The Edge Function bridge calls them after validating the identity JWT.

create table launcher_v2.bridge_jti_replays (
  jti text primary key check (length(jti) between 1 and 200),
  identity_sub text not null check (length(identity_sub) between 1 and 255),
  expires_at timestamptz not null,
  consumed_at timestamptz not null default now()
);

create index bridge_jti_replays_expires_idx
  on launcher_v2.bridge_jti_replays (expires_at);

alter table launcher_v2.bridge_jti_replays enable row level security;
alter table launcher_v2.bridge_jti_replays force row level security;
revoke all on launcher_v2.bridge_jti_replays from public, anon, authenticated;
grant select, insert, delete on launcher_v2.bridge_jti_replays to service_role;

create or replace function launcher_v2.consume_bridge_jti(
  p_jti text,
  p_identity_sub text,
  p_expires_at timestamptz
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_count integer;
begin
  if p_jti is null or length(p_jti) not between 1 and 200
    or p_identity_sub is null or length(p_identity_sub) not between 1 and 255
    or p_expires_at is null
  then
    return false;
  end if;

  delete from launcher_v2.bridge_jti_replays
  where expires_at < now() - interval '1 hour';

  insert into launcher_v2.bridge_jti_replays(jti, identity_sub, expires_at)
  values (p_jti, p_identity_sub, p_expires_at)
  on conflict (jti) do nothing;
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

create or replace function launcher_v2.bridge_find_user_by_identity_sub(
  p_identity_sub text
)
returns uuid
language sql
security definer
set search_path = ''
as $$
  select u.id
  from auth.users u
  where u.raw_app_meta_data ->> 'identity_sub' = p_identity_sub
    and u.raw_app_meta_data ->> 'auth_line' = 'next'
  limit 1;
$$;

create or replace function launcher_v2.bridge_link_identity(
  p_identity_sub text,
  p_user_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_link launcher_v2.identity_links%rowtype;
begin
  if p_identity_sub is null or length(p_identity_sub) not between 1 and 255
    or p_user_id is null
  then
    raise exception 'invalid_identity_link';
  end if;
  if not exists (
    select 1
    from auth.users u
    where u.id = p_user_id
      and u.raw_app_meta_data ->> 'auth_line' = 'next'
      and u.raw_app_meta_data ->> 'identity_sub' = p_identity_sub
  ) then
    raise exception 'invalid_next_line_user';
  end if;
  if exists (
    select 1
    from launcher_v2.identity_links
    where user_id = p_user_id
      and identity_sub <> p_identity_sub
  ) then
    raise exception 'identity_user_conflict';
  end if;

  insert into launcher_v2.identity_links(identity_sub, user_id)
  values (p_identity_sub, p_user_id)
  on conflict (identity_sub) do nothing;

  select *
  into v_link
  from launcher_v2.identity_links
  where identity_sub = p_identity_sub
  for update;

  if v_link.id is null or v_link.user_id <> p_user_id then
    raise exception 'identity_link_conflict';
  end if;

  update launcher_v2.identity_links
  set status = 'active',
      last_login_at = now()
  where id = v_link.id
  returning * into v_link;

  return jsonb_build_object(
    'identity_link_id', v_link.id,
    'user_id', v_link.user_id
  );
end;
$$;

create or replace function launcher_v2.bridge_record_web_session(
  p_auth_session_id uuid,
  p_user_id uuid,
  p_identity_link_id uuid
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_count integer;
begin
  if p_auth_session_id is null or p_user_id is null or p_identity_link_id is null then
    return false;
  end if;
  if not exists (
    select 1
    from auth.sessions a
    where a.id = p_auth_session_id
      and a.user_id = p_user_id
      and (a.not_after is null or a.not_after > now())
  ) then
    return false;
  end if;
  if not exists (
    select 1
    from launcher_v2.identity_links il
    where il.id = p_identity_link_id
      and il.user_id = p_user_id
      and il.status = 'active'
  ) then
    return false;
  end if;
  if exists (
    select 1
    from launcher_v2.web_sessions w
    where w.auth_session_id = p_auth_session_id
      and w.user_id <> p_user_id
  ) then
    return false;
  end if;

  insert into launcher_v2.web_sessions(
    auth_session_id,
    user_id,
    identity_link_id
  )
  values (
    p_auth_session_id,
    p_user_id,
    p_identity_link_id
  )
  on conflict (auth_session_id) do update
  set last_seen_at = now(),
      revoked_at = null;
  get diagnostics v_count = row_count;
  return v_count > 0;
end;
$$;

revoke all on function launcher_v2.consume_bridge_jti(text, text, timestamptz)
  from public, anon, authenticated;
revoke all on function launcher_v2.bridge_find_user_by_identity_sub(text)
  from public, anon, authenticated;
revoke all on function launcher_v2.bridge_link_identity(text, uuid)
  from public, anon, authenticated;
revoke all on function launcher_v2.bridge_record_web_session(uuid, uuid, uuid)
  from public, anon, authenticated;

grant execute on function launcher_v2.consume_bridge_jti(text, text, timestamptz)
  to service_role;
grant execute on function launcher_v2.bridge_find_user_by_identity_sub(text)
  to service_role;
grant execute on function launcher_v2.bridge_link_identity(text, uuid)
  to service_role;
grant execute on function launcher_v2.bridge_record_web_session(uuid, uuid, uuid)
  to service_role;
