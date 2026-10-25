-- P1 slice 2: next-line entitlement, session, and permit authority.
--
-- Every RPC below requires a live, server-written launcher_v2.web_sessions
-- allowlist row. A normal password session in the shared auth.users pool
-- therefore cannot claim a 5.2.0 Launcher session or obtain a permit.

alter table launcher_v2.audit_events
  drop constraint if exists audit_events_event_type_check;
alter table launcher_v2.audit_events
  add constraint audit_events_event_type_check check (
    event_type in (
      'identity_linked',
      'identity_unlinked',
      'web_session_minted',
      'web_session_revoked',
      'session_claimed',
      'session_revoked',
      'session_rejected',
      'license_rejected',
      'policy_rejected'
    )
  );

create table launcher_v2.products (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check (code = lower(code) and length(code) between 3 and 64),
  name text not null,
  max_devices smallint not null default 1 check (max_devices between 1 and 20),
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

insert into launcher_v2.products (code, name, max_devices)
values ('neko-family-proxy', 'Neko Family Proxy', 1)
on conflict (code) do nothing;

create table launcher_v2.licenses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  product_id uuid not null references launcher_v2.products(id) on delete restrict,
  status text not null default 'active'
    check (status in ('active', 'suspended', 'revoked')),
  valid_from timestamptz not null default now(),
  valid_until timestamptz not null,
  max_devices smallint check (max_devices between 1 and 20),
  created_at timestamptz not null default now(),
  check (valid_until > valid_from)
);

create index licenses_user_product_validity_idx
  on launcher_v2.licenses (user_id, product_id, status, valid_until desc);

create table launcher_v2.installations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  installation_key_hash text not null check (installation_key_hash ~ '^[0-9a-f]{64}$'),
  display_name text,
  last_seen_at timestamptz not null default now(),
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  unique (user_id, installation_key_hash)
);

create index installations_user_last_seen_idx
  on launcher_v2.installations (user_id, last_seen_at desc)
  where revoked_at is null;

create table launcher_v2.sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  installation_id uuid not null references launcher_v2.installations(id) on delete cascade,
  license_id uuid not null references launcher_v2.licenses(id) on delete cascade,
  auth_session_id uuid not null
    references launcher_v2.web_sessions(auth_session_id) on delete cascade,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  revoked_at timestamptz
);

create unique index sessions_one_active_per_user_idx
  on launcher_v2.sessions (user_id)
  where revoked_at is null;
create index sessions_user_created_idx
  on launcher_v2.sessions (user_id, created_at desc);

create table launcher_v2.permit_attempts (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  attempted_at timestamptz not null default now(),
  allowed boolean not null,
  reason text not null check (reason in ('allowed', 'rate_limited', 'not_authorized'))
);

create index permit_attempts_user_attempted_idx
  on launcher_v2.permit_attempts (user_id, attempted_at desc);

alter table launcher_v2.products enable row level security;
alter table launcher_v2.products force row level security;
alter table launcher_v2.licenses enable row level security;
alter table launcher_v2.licenses force row level security;
alter table launcher_v2.installations enable row level security;
alter table launcher_v2.installations force row level security;
alter table launcher_v2.sessions enable row level security;
alter table launcher_v2.sessions force row level security;
alter table launcher_v2.permit_attempts enable row level security;
alter table launcher_v2.permit_attempts force row level security;

revoke all on all tables in schema launcher_v2 from public, anon, authenticated;
revoke all on sequence launcher_v2.permit_attempts_id_seq
  from public, anon, authenticated;
grant all on all tables in schema launcher_v2 to service_role;
grant usage, select on sequence launcher_v2.permit_attempts_id_seq
  to service_role;
grant usage on schema launcher_v2 to authenticated;

create or replace function launcher_v2.claim_session(
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
  v_license launcher_v2.licenses%rowtype;
  v_installation launcher_v2.installations%rowtype;
  v_session launcher_v2.sessions%rowtype;
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
    from launcher_v2.web_sessions w
    join launcher_v2.identity_links il
      on il.id = w.identity_link_id
     and il.user_id = w.user_id
     and il.status = 'active'
    join auth.sessions a on a.id = w.auth_session_id
    where w.auth_session_id = v_auth_session_id
      and w.user_id = v_user_id
      and w.revoked_at is null
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

  perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));

  perform 1
  from launcher_v2.profiles p
  where p.id = v_user_id
    and p.status = 'active'
  for share;
  if not found then
    raise exception 'account_restricted';
  end if;

  select p.id
  into v_product_id
  from launcher_v2.products p
  where p.code = p_product_code
    and p.is_active;
  if v_product_id is null then
    raise exception 'license_invalid';
  end if;

  select l.*
  into v_license
  from launcher_v2.licenses l
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
  from launcher_v2.installations i
  where i.user_id = v_user_id
    and i.installation_key_hash = p_installation_key_hash
  for update;

  v_max_devices := coalesce(
    v_license.max_devices,
    (select p.max_devices from launcher_v2.products p where p.id = v_product_id),
    1
  );
  if v_installation.id is null then
    insert into launcher_v2.installations(user_id, installation_key_hash, display_name)
    values (
      v_user_id,
      p_installation_key_hash,
      nullif(left(p_display_name, 120), '')
    )
    returning * into v_installation;
  else
    update launcher_v2.installations
    set last_seen_at = now(),
        display_name = coalesce(nullif(left(p_display_name, 120), ''), display_name),
        revoked_at = null
    where id = v_installation.id
    returning * into v_installation;
  end if;

  with revoked_sessions as (
    update launcher_v2.sessions
    set revoked_at = now()
    where user_id = v_user_id
      and revoked_at is null
    returning id
  )
  insert into launcher_v2.audit_events(user_id, event_type, metadata)
  select
    v_user_id,
    'session_revoked',
    jsonb_build_object(
      'session_id', id,
      'reason', 'replaced_by_new_session',
      'replacement_installation_id', v_installation.id
    )
  from revoked_sessions;

  insert into launcher_v2.sessions(
    user_id,
    installation_id,
    license_id,
    auth_session_id
  )
  values (
    v_user_id,
    v_installation.id,
    v_license.id,
    v_auth_session_id
  )
  returning * into v_session;

  insert into launcher_v2.audit_events(user_id, event_type, metadata)
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

create or replace function launcher_v2.heartbeat_session(p_session_id uuid)
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

  if v_user_id is null or v_auth_session_id is null or p_session_id is null then
    return false;
  end if;

  update launcher_v2.sessions s
  set last_seen_at = now()
  where s.id = p_session_id
    and s.user_id = v_user_id
    and s.auth_session_id = v_auth_session_id
    and s.revoked_at is null
    and s.last_seen_at > now() - interval '90 seconds'
    and exists (
      select 1
      from launcher_v2.web_sessions w
      join launcher_v2.identity_links il
        on il.id = w.identity_link_id
       and il.user_id = w.user_id
       and il.status = 'active'
      join auth.sessions a on a.id = w.auth_session_id
      where w.auth_session_id = v_auth_session_id
        and w.user_id = v_user_id
        and w.revoked_at is null
        and a.user_id = v_user_id
        and (a.not_after is null or a.not_after > now())
    )
    and exists (
      select 1
      from launcher_v2.licenses l
      join launcher_v2.products p on p.id = l.product_id
      where l.id = s.license_id
        and l.user_id = s.user_id
        and p.code = 'neko-family-proxy'
        and p.is_active
        and l.status = 'active'
        and l.valid_from <= now()
        and l.valid_until > now()
    );

  get diagnostics v_count = row_count;
  return v_count > 0;
end;
$$;

create or replace function launcher_v2.release_session(p_session_id uuid)
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

  if v_user_id is null or v_auth_session_id is null or p_session_id is null then
    return false;
  end if;

  perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));

  update launcher_v2.sessions s
  set revoked_at = now()
  where s.id = p_session_id
    and s.user_id = v_user_id
    and s.auth_session_id = v_auth_session_id
    and s.revoked_at is null
    and exists (
      select 1
      from launcher_v2.web_sessions w
      join auth.sessions a on a.id = w.auth_session_id
      where w.auth_session_id = v_auth_session_id
        and w.user_id = v_user_id
        and w.revoked_at is null
        and a.user_id = v_user_id
        and (a.not_after is null or a.not_after > now())
    );

  get diagnostics v_count = row_count;
  if v_count > 0 then
    insert into launcher_v2.audit_events(user_id, event_type, metadata)
    values (
      v_user_id,
      'session_revoked',
      jsonb_build_object(
        'session_id', p_session_id,
        'reason', 'client_release'
      )
    );
  end if;

  return v_count > 0;
end;
$$;

create or replace function launcher_v2.authorize_launch_permit(p_challenge text)
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
    select 1
    from launcher_v2.web_sessions w
    join launcher_v2.identity_links il
      on il.id = w.identity_link_id
     and il.user_id = w.user_id
     and il.status = 'active'
    join auth.sessions a on a.id = w.auth_session_id
    where w.auth_session_id = v_auth_session_id
      and w.user_id = v_user_id
      and w.revoked_at is null
      and a.user_id = v_user_id
      and (a.not_after is null or a.not_after > now())
  ) then
    return jsonb_build_object('error', 'AuthorizationInvalid');
  end if;
  if not exists (
    select 1
    from launcher_v2.profiles pr
    where pr.id = v_user_id
      and pr.status = 'active'
  ) then
    return jsonb_build_object('error', 'AuthorizationInvalid');
  end if;
  if exists (
    select 1
    from launcher_v2.sessions s
    where s.user_id = v_user_id
      and s.revoked_at is null
      and s.auth_session_id <> v_auth_session_id
  ) then
    return jsonb_build_object('error', 'SessionMismatch');
  end if;

  select jsonb_build_object(
    'user_id', s.user_id,
    'auth_session_id', s.auth_session_id,
    'session_id', s.id,
    'product_code', p.code
  )
  into v_state
  from launcher_v2.sessions s
  join launcher_v2.licenses l on l.id = s.license_id
  join launcher_v2.products p on p.id = l.product_id
  join launcher_v2.web_sessions w
    on w.auth_session_id = s.auth_session_id
   and w.user_id = s.user_id
   and w.revoked_at is null
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
      select 1
      from launcher_v2.sessions s
      where s.user_id = v_user_id
        and s.auth_session_id = v_auth_session_id
        and s.revoked_at is null
    ) then
      if exists (
        select 1
        from launcher_v2.sessions s
        where s.user_id = v_user_id
          and s.auth_session_id = v_auth_session_id
          and s.revoked_at is null
          and s.last_seen_at <= now() - interval '90 seconds'
      ) then
        return jsonb_build_object('error', 'HeartbeatStale');
      end if;
      return jsonb_build_object('error', 'EntitlementInactive');
    end if;
    return jsonb_build_object('error', 'SessionInactive');
  end if;

  return v_state;
end;
$$;

create or replace function launcher_v2.consume_permit_attempt(
  p_limit integer default 10,
  p_window_seconds integer default 60
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := auth.uid();
  v_auth_session_id uuid;
  v_attempt_count integer;
  v_allowed boolean;
begin
  begin
    v_auth_session_id := nullif(auth.jwt() ->> 'session_id', '')::uuid;
  exception
    when invalid_text_representation then
      return jsonb_build_object(
        'allowed', false,
        'remaining', 0,
        'reason', 'not_authorized'
      );
  end;

  if v_user_id is null or v_auth_session_id is null then
    return jsonb_build_object(
      'allowed', false,
      'remaining', 0,
      'reason', 'not_authorized'
    );
  end if;
  if not exists (
    select 1
    from launcher_v2.web_sessions w
    where w.auth_session_id = v_auth_session_id
      and w.user_id = v_user_id
      and w.revoked_at is null
  ) then
    return jsonb_build_object(
      'allowed', false,
      'remaining', 0,
      'reason', 'not_authorized'
    );
  end if;
  if p_limit < 1 or p_limit > 100
    or p_window_seconds < 1 or p_window_seconds > 3600
  then
    raise exception 'invalid permit rate limit parameters';
  end if;

  perform pg_advisory_xact_lock(
    hashtextextended('permit-rate:' || v_user_id::text, 0)
  );

  delete from launcher_v2.permit_attempts
  where user_id = v_user_id
    and attempted_at < now() - interval '1 day';

  select count(*)
  into v_attempt_count
  from launcher_v2.permit_attempts
  where user_id = v_user_id
    and attempted_at > now() - make_interval(secs => p_window_seconds);

  v_allowed := v_attempt_count < p_limit;

  insert into launcher_v2.permit_attempts (user_id, allowed, reason)
  values (
    v_user_id,
    v_allowed,
    case when v_allowed then 'allowed' else 'rate_limited' end
  );

  return jsonb_build_object(
    'allowed', v_allowed,
    'remaining', greatest(p_limit - v_attempt_count - 1, 0)
  );
end;
$$;

revoke all on function launcher_v2.claim_session(text, text, text)
  from public, anon;
grant execute on function launcher_v2.claim_session(text, text, text)
  to authenticated;

revoke all on function launcher_v2.heartbeat_session(uuid)
  from public, anon;
grant execute on function launcher_v2.heartbeat_session(uuid)
  to authenticated;

revoke all on function launcher_v2.release_session(uuid)
  from public, anon;
grant execute on function launcher_v2.release_session(uuid)
  to authenticated;

revoke all on function launcher_v2.authorize_launch_permit(text)
  from public, anon;
grant execute on function launcher_v2.authorize_launch_permit(text)
  to authenticated;

revoke all on function launcher_v2.consume_permit_attempt(integer, integer)
  from public, anon;
grant execute on function launcher_v2.consume_permit_attempt(integer, integer)
  to authenticated;
