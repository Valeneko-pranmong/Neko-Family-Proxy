-- NEKO-AUTH-LITE / lite-v1. Forward-only policy migration.
-- Keep existing launcher_sessions schema and its unique active-per-user index.
-- Fresh first session wins. A later caller can recover only a stale session.

create or replace function launcher.claim_session(
  p_product_code text,
  p_installation_key_hash text,
  p_display_name text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := auth.uid();
  v_auth_session_id uuid;
  v_product_id uuid;
  v_license public.licenses%rowtype;
  v_installation public.installations%rowtype;
  v_session public.launcher_sessions%rowtype;
  v_active_session public.launcher_sessions%rowtype;
  v_max_devices smallint;
begin
  begin
    v_auth_session_id := nullif(auth.jwt() ->> 'session_id', '')::uuid;
  exception
    when invalid_text_representation then
      raise exception 'not_authenticated' using errcode = '28000';
  end;

  if v_user_id is null or v_auth_session_id is null then
    raise exception 'not_authenticated' using errcode = '28000';
  end if;
  if not exists (
    select 1
    from auth.sessions a
    where a.id = v_auth_session_id
      and a.user_id = v_user_id
      and (a.not_after is null or a.not_after > now())
  ) then
    raise exception 'not_authenticated' using errcode = '28000';
  end if;
  if p_product_code is null
    or p_product_code <> 'neko-family-proxy'
    or p_product_code <> lower(p_product_code)
  then
    raise exception 'invalid_product';
  end if;
  if p_installation_key_hash is null
    or p_installation_key_hash !~ '^[0-9a-f]{64}$'
  then
    raise exception 'invalid_installation';
  end if;

  -- Claim and permit authorization share this linearization point.
  perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));

  select s.*
  into v_active_session
  from public.launcher_sessions s
  where s.user_id = v_user_id
    and s.revoked_at is null
  order by s.created_at desc
  limit 1
  for update;

  if v_active_session.id is not null then
    if v_active_session.last_seen_at > now() - interval '90 seconds' then
      -- Do not change installation, session, or authority on loser retry.
      raise exception 'SESSION_ALREADY_ACTIVE' using errcode = 'P0001';
    elsif v_active_session.last_seen_at <= now() - interval '90 seconds' then
      update public.launcher_sessions
      set revoked_at = now()
      where id = v_active_session.id
        and revoked_at is null;

      insert into public.audit_events(user_id, event_type, metadata)
      values (
        v_user_id,
        'session_revoked',
        jsonb_build_object('session_id', v_active_session.id, 'reason', 'stale_recovered')
      );
    end if;
  end if;

  perform 1
  from public.profiles p
  where p.id = v_user_id
    and p.status = 'active'
  for share;
  if not found then
    raise exception 'account_restricted';
  end if;

  select p.id
  into v_product_id
  from public.products p
  where p.code = p_product_code
    and p.is_active;
  if v_product_id is null then
    raise exception 'license_invalid';
  end if;

  select l.*
  into v_license
  from public.licenses l
  where l.user_id = v_user_id
    and l.product_id = v_product_id
    and l.status = 'active'
    and l.valid_from <= now()
    and l.valid_until > now()
  order by l.valid_until desc
  limit 1
  for share;
  if v_license.id is null then
    raise exception 'license_invalid';
  end if;

  select i.*
  into v_installation
  from public.installations i
  where i.user_id = v_user_id
    and i.installation_key_hash = p_installation_key_hash
  for update;

  v_max_devices := coalesce(
    v_license.max_devices,
    (select p.max_devices from public.products p where p.id = v_product_id),
    1
  );
  if v_installation.id is null then
    insert into public.installations(user_id, installation_key_hash, display_name)
    values (
      v_user_id,
      p_installation_key_hash,
      nullif(left(p_display_name, 120), '')
    )
    returning * into v_installation;
  else
    update public.installations
    set last_seen_at = now(),
        display_name = coalesce(nullif(left(p_display_name, 120), ''), display_name),
        revoked_at = null
    where id = v_installation.id
    returning * into v_installation;
  end if;

  insert into public.launcher_sessions(user_id, installation_id, license_id)
  values (v_user_id, v_installation.id, v_license.id)
  returning * into v_session;

  insert into public.audit_events(user_id, event_type, metadata)
  values (
    v_user_id,
    'session_claimed',
    jsonb_build_object(
      'session_id', v_session.id,
      'installation_id', v_installation.id,
      'license_id', v_license.id,
      'product_code', p_product_code
    )
  );

  return jsonb_build_object(
    'session_id', v_session.id,
    'installation_id', v_installation.id,
    'license_id', v_license.id,
    'product_code', p_product_code,
    'valid_until', v_license.valid_until,
    'max_devices', v_max_devices
  );
end;
$$;

-- Reassert exact Auth-session ownership. A closed session never revives.
create or replace function launcher.heartbeat_session(p_session_id uuid)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := auth.uid();
  v_auth_session_id uuid;
  v_count integer;
begin
  begin
    v_auth_session_id := nullif(auth.jwt() ->> 'session_id', '')::uuid;
  exception
    when invalid_text_representation then return false;
  end;
  if v_user_id is null or v_auth_session_id is null or p_session_id is null then return false; end if;
  update public.launcher_sessions s
  set last_seen_at = now()
  where s.id = p_session_id
    and s.user_id = v_user_id
    and s.auth_session_id = v_auth_session_id
    and s.revoked_at is null
    and s.last_seen_at > now() - interval '90 seconds'
    and exists (
      select 1 from auth.sessions a
      where a.id = v_auth_session_id
        and a.user_id = v_user_id
        and (a.not_after is null or a.not_after > now())
    )
    and exists (
      select 1 from public.licenses l join public.products p on p.id = l.product_id
      where l.id = s.license_id and l.user_id = s.user_id
        and p.code = 'neko-family-proxy' and p.is_active
        and l.status = 'active' and l.valid_from <= now() and l.valid_until > now()
    );
  get diagnostics v_count = row_count;
  return v_count > 0;
end;
$$;

create or replace function launcher.release_session(p_session_id uuid)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := auth.uid();
  v_auth_session_id uuid;
  v_count integer;
begin
  begin
    v_auth_session_id := nullif(auth.jwt() ->> 'session_id', '')::uuid;
  exception
    when invalid_text_representation then return false;
  end;
  if v_user_id is null or v_auth_session_id is null or p_session_id is null then return false; end if;
  -- Serialize release with claim and permit authorization for this account.
  perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));
  update public.launcher_sessions s
  set revoked_at = now()
  where s.id = p_session_id
    and s.user_id = v_user_id
    and s.auth_session_id = v_auth_session_id
    and s.revoked_at is null
    and exists (
      select 1 from auth.sessions a
      where a.id = v_auth_session_id
        and a.user_id = v_user_id
        and (a.not_after is null or a.not_after > now())
    );
  get diagnostics v_count = row_count;
  if v_count > 0 then
    insert into public.audit_events(user_id, event_type, metadata)
    values (v_user_id, 'session_revoked', jsonb_build_object('session_id', p_session_id, 'reason', 'client_release'));
  end if;
  return v_count > 0;
end;
$$;

-- Lite removes S0 replay and rate ledgers. Core owns challenge use. This RPC
-- remains serialized against claim/release state and returns only server facts.
drop function if exists launcher.authorize_launch_permit(text, text);
create or replace function launcher.authorize_launch_permit(p_challenge text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := auth.uid();
  v_auth_session_id uuid;
  v_state jsonb;
begin
  begin
    v_auth_session_id := nullif(auth.jwt() ->> 'session_id', '')::uuid;
  exception
    when invalid_text_representation then
      return jsonb_build_object('error', 'AuthorizationInvalid');
  end;
  if v_user_id is null or v_auth_session_id is null then
    return jsonb_build_object('error', 'AuthorizationRequired');
  end if;
  if p_challenge is null or p_challenge !~ '^[A-Za-z0-9_-]{43}$' then
    return jsonb_build_object('error', 'AuthorizationInvalid');
  end if;

  perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));

  if not exists (
    select 1 from auth.sessions a
    where a.id = v_auth_session_id
      and a.user_id = v_user_id
      and (a.not_after is null or a.not_after > now())
  ) then
    return jsonb_build_object('error', 'AuthorizationInvalid');
  end if;
  if not exists (select 1 from public.profiles pr where pr.id = v_user_id and pr.status = 'active') then
    return jsonb_build_object('error', 'AuthorizationInvalid');
  end if;
  if exists (
    select 1 from public.launcher_sessions s
    where s.user_id = v_user_id and s.revoked_at is null and s.auth_session_id <> v_auth_session_id
  ) then
    return jsonb_build_object('error', 'SessionMismatch');
  end if;

  select jsonb_build_object(
    'user_id', s.user_id,
    'auth_session_id', s.auth_session_id,
    'session_id', s.id,
    'product_code', p.code
  ) into v_state
  from public.launcher_sessions s
  join public.licenses l on l.id = s.license_id
  join public.products p on p.id = l.product_id
  where s.user_id = v_user_id
    and s.auth_session_id = v_auth_session_id
    and s.revoked_at is null
    and s.last_seen_at > now() - interval '90 seconds'
    and l.user_id = s.user_id
    and p.code = 'neko-family-proxy'
    and p.is_active
    and l.status = 'active'
    and l.valid_from <= now()
    and l.valid_until > now()
  limit 1;

  if v_state is null then
    if exists (
      select 1 from public.launcher_sessions s
      where s.user_id = v_user_id and s.auth_session_id = v_auth_session_id and s.revoked_at is null
    ) then
      if exists (
        select 1 from public.launcher_sessions s
        where s.user_id = v_user_id and s.auth_session_id = v_auth_session_id
          and s.revoked_at is null and s.last_seen_at <= now() - interval '90 seconds'
      ) then return jsonb_build_object('error', 'HeartbeatStale'); end if;
      return jsonb_build_object('error', 'EntitlementInactive');
    end if;
    return jsonb_build_object('error', 'SessionInactive');
  end if;
  if exists (
    select 1 from public.launcher_sessions s
    where s.id = (v_state ->> 'session_id')::uuid
      and s.last_seen_at <= now() - interval '90 seconds'
  ) then
    return jsonb_build_object('error', 'HeartbeatStale');
  end if;
  return v_state;
end;
$$;

revoke all on function launcher.claim_session(text, text, text) from public, anon;
grant execute on function launcher.claim_session(text, text, text) to authenticated;
revoke all on function launcher.heartbeat_session(uuid) from public, anon;
grant execute on function launcher.heartbeat_session(uuid) to authenticated;
revoke all on function launcher.release_session(uuid) from public, anon;
grant execute on function launcher.release_session(uuid) to authenticated;
revoke all on function launcher.authorize_launch_permit(text) from public, anon;
grant execute on function launcher.authorize_launch_permit(text) to authenticated;

-- Schema invariant stays database-enforced after every policy rewrite.
do $$
declare v_index_definition text;
begin
  select pg_get_indexdef(i.indexrelid) into v_index_definition
  from pg_index i join pg_class c on c.oid = i.indexrelid join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public' and c.relname = 'launcher_sessions_one_active_per_user_idx'
    and i.indisunique and i.indisvalid;
  if v_index_definition is null
    or position('(user_id)' in lower(v_index_definition)) = 0
    or position('where (revoked_at is null)' in lower(v_index_definition)) = 0
  then raise exception 'launcher_sessions_one_active_per_user_idx must remain unique on user_id where revoked_at is null'; end if;
end;
$$;
