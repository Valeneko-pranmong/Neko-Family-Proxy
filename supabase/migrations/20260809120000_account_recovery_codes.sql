-- Forward-only account recovery flow. Recovery codes and sessions are opaque
-- credentials whose HMAC verifiers are computed by the trusted Web API.

alter table public.audit_events
  drop constraint if exists audit_events_event_type_check;

alter table public.audit_events
  add constraint audit_events_event_type_check
  check (
    event_type in (
      'session_claimed',
      'session_revoked',
      'session_rejected',
      'license_rejected',
      'coupon_batch_created',
      'coupon_redeemed',
      'coupon_batch_revoked',
      'coupon_batch_deleted',
      'admin_user_status_changed',
      'admin_license_revoked',
      'admin_license_extended',
      'admin_session_revoked',
      'admin_installation_revoked',
      'admin_password_reset', -- Historical audit rows only; no reset RPC is retained.
      'account_recovery_code_generated',
      'account_recovery_code_revoked',
      'account_recovery_code_locked',
      'account_recovery_verified',
      'account_recovery_auth_failed',
      'account_password_recovered'
    )
  );

create table public.account_recovery_codes (
  id uuid primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  code_verifier text not null unique check (code_verifier ~ '^[0-9a-f]{64}$'),
  created_by_admin uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '5 minutes'),
  used_at timestamptz,
  revoked_at timestamptz,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 5 check (max_attempts between 1 and 20),
  status text not null default 'active'
    check (status in ('active', 'used', 'expired', 'revoked', 'locked')),
  check (expires_at > created_at)
);

create unique index account_recovery_one_active_per_user_idx
  on public.account_recovery_codes(user_id)
  where status = 'active';
create index account_recovery_codes_user_created_idx
  on public.account_recovery_codes(user_id, created_at desc);

create table public.account_recovery_sessions (
  id uuid primary key,
  recovery_id uuid not null unique
    references public.account_recovery_codes(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  token_verifier text not null unique check (token_verifier ~ '^[0-9a-f]{64}$'),
  scope text not null default 'change_password' check (scope = 'change_password'),
  state text not null default 'active'
    check (state in ('active', 'auth_updating', 'retryable', 'completed', 'revoked')),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '10 minutes'),
  password_fingerprint text check (password_fingerprint ~ '^[0-9a-f]{64}$'),
  auth_attempt_count integer not null default 0 check (auth_attempt_count >= 0),
  auth_attempt_started_at timestamptz,
  completed_at timestamptz,
  revoked_at timestamptz,
  failure_code text,
  check (expires_at > created_at)
);
create index account_recovery_sessions_user_created_idx
  on public.account_recovery_sessions(user_id, created_at desc);

create table public.account_recovery_rate_limits (
  requester_verifier text not null check (requester_verifier ~ '^[0-9a-f]{64}$'),
  window_started_at timestamptz not null,
  attempt_count integer not null default 1 check (attempt_count > 0),
  primary key (requester_verifier, window_started_at)
);
create index account_recovery_rate_limits_window_idx
  on public.account_recovery_rate_limits(window_started_at);

alter table public.account_recovery_codes enable row level security;
alter table public.account_recovery_sessions enable row level security;
alter table public.account_recovery_rate_limits enable row level security;

revoke all on table public.account_recovery_codes from public, anon, authenticated;
revoke all on table public.account_recovery_sessions from public, anon, authenticated;
revoke all on table public.account_recovery_rate_limits from public, anon, authenticated;
grant select, insert, update on table public.account_recovery_codes to service_role;
grant select, insert, update on table public.account_recovery_sessions to service_role;
grant select, insert, update, delete on table public.account_recovery_rate_limits to service_role;

create or replace function launcher.admin_generate_recovery_code(
  p_actor_id uuid,
  p_user_id uuid,
  p_confirm_username text,
  p_recovery_id uuid,
  p_code_verifier text
)
returns table(recovery_id uuid, username text, expires_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_target public.profiles%rowtype;
  v_old_id uuid;
  v_expires_at timestamptz := now() + interval '5 minutes';
begin
  perform launcher.assert_admin_actor(p_actor_id);
  if p_actor_id = p_user_id then
    raise exception 'cannot_recover_current_admin';
  end if;
  if p_recovery_id is null or p_code_verifier !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid_recovery_request';
  end if;

  select * into v_target
  from public.profiles
  where id = p_user_id
  for update;
  if not found then
    raise exception 'target_user_not_found';
  end if;
  if v_target.role <> 'customer' or v_target.status <> 'active' then
    raise exception 'target_not_customer';
  end if;
  if lower(trim(v_target.username)) is distinct from lower(trim(p_confirm_username)) then
    raise exception 'target_username_mismatch';
  end if;

  update public.account_recovery_codes
  set status = 'revoked', revoked_at = now()
  where user_id = p_user_id and status = 'active'
  returning id into v_old_id;
  if v_old_id is not null then
    insert into public.audit_events(user_id, event_type, metadata)
    values (p_actor_id, 'account_recovery_code_revoked', jsonb_build_object(
      'target_user_id', p_user_id,
      'recovery_id', v_old_id,
      'reason', 'superseded'
    ));
  end if;

  insert into public.account_recovery_codes(
    id, user_id, code_verifier, created_by_admin, expires_at
  ) values (
    p_recovery_id, p_user_id, p_code_verifier, p_actor_id, v_expires_at
  )
  on conflict (id) do nothing;
  if not found then
    raise exception 'recovery_id_conflict';
  end if;

  insert into public.audit_events(user_id, event_type, metadata)
  values (p_actor_id, 'account_recovery_code_generated', jsonb_build_object(
    'target_user_id', p_user_id,
    'recovery_id', p_recovery_id,
    'expires_at', v_expires_at
  ));
  return query select p_recovery_id, v_target.username, v_expires_at;
end;
$$;

create or replace function launcher.verify_recovery_code(
  p_username text,
  p_code_verifier text,
  p_session_id uuid,
  p_token_verifier text,
  p_requester_verifier text
)
returns table(
  ok boolean,
  error_code text,
  recovery_session_id uuid,
  user_id uuid,
  expires_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_window timestamptz := date_trunc('minute', now())
    - make_interval(mins => mod(extract(minute from now())::integer, 5));
  v_rate_count integer;
  v_user_id uuid;
  v_code public.account_recovery_codes%rowtype;
  v_session_expires timestamptz := now() + interval '10 minutes';
begin
  if p_username is null or p_code_verifier !~ '^[0-9a-f]{64}$'
     or p_session_id is null or p_token_verifier !~ '^[0-9a-f]{64}$'
     or p_requester_verifier !~ '^[0-9a-f]{64}$' then
    return query select false, 'recovery_invalid', null::uuid, null::uuid, null::timestamptz;
    return;
  end if;

  delete from public.account_recovery_rate_limits
  where window_started_at < now() - interval '1 day';

  insert into public.account_recovery_rate_limits(
    requester_verifier, window_started_at, attempt_count
  ) values (p_requester_verifier, v_window, 1)
  on conflict (requester_verifier, window_started_at)
  do update set attempt_count = public.account_recovery_rate_limits.attempt_count + 1
  returning attempt_count into v_rate_count;
  if v_rate_count > 10 then
    return query select false, 'recovery_rate_limited', null::uuid, null::uuid, null::timestamptz;
    return;
  end if;

  select id into v_user_id
  from public.profiles
  where lower(username) = lower(trim(p_username))
    and role = 'customer'
    and status = 'active';

  select * into v_code
  from public.account_recovery_codes
  where user_id = v_user_id and status = 'active'
  for update;
  if not found then
    return query select false, 'recovery_invalid', null::uuid, null::uuid, null::timestamptz;
    return;
  end if;
  if v_code.expires_at <= now() then
    update public.account_recovery_codes
    set status = 'expired'
    where id = v_code.id;
    return query select false, 'recovery_invalid', null::uuid, null::uuid, null::timestamptz;
    return;
  end if;
  if v_code.code_verifier <> p_code_verifier then
    update public.account_recovery_codes
    set attempt_count = attempt_count + 1,
        status = case when attempt_count + 1 >= max_attempts then 'locked' else status end
    where id = v_code.id
    returning * into v_code;
    if v_code.status = 'locked' then
      insert into public.audit_events(user_id, event_type, metadata)
      values (v_code.user_id, 'account_recovery_code_locked', jsonb_build_object(
        'target_user_id', v_code.user_id,
        'recovery_id', v_code.id,
        'attempt_count', v_code.attempt_count
      ));
    end if;
    return query select false, 'recovery_invalid', null::uuid, null::uuid, null::timestamptz;
    return;
  end if;

  update public.account_recovery_codes
  set status = 'used', used_at = now()
  where id = v_code.id and status = 'active';
  if not found then
    return query select false, 'recovery_invalid', null::uuid, null::uuid, null::timestamptz;
    return;
  end if;

  insert into public.account_recovery_sessions(
    id, recovery_id, user_id, token_verifier, expires_at
  ) values (
    p_session_id, v_code.id, v_code.user_id, p_token_verifier, v_session_expires
  );
  insert into public.audit_events(user_id, event_type, metadata)
  values (v_code.user_id, 'account_recovery_verified', jsonb_build_object(
    'target_user_id', v_code.user_id,
    'recovery_id', v_code.id,
    'recovery_session_id', p_session_id
  ));
  return query select true, null::text, p_session_id, v_code.user_id, v_session_expires;
end;
$$;

create or replace function launcher.claim_recovery_password_change(
  p_token_verifier text,
  p_password_fingerprint text
)
returns table(user_id uuid, recovery_id uuid, already_completed boolean)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_session public.account_recovery_sessions%rowtype;
begin
  if p_token_verifier !~ '^[0-9a-f]{64}$'
     or p_password_fingerprint !~ '^[0-9a-f]{64}$' then
    raise exception 'recovery_session_invalid';
  end if;
  select * into v_session
  from public.account_recovery_sessions
  where token_verifier = p_token_verifier and scope = 'change_password'
  for update;
  if not found then
    raise exception 'recovery_session_invalid';
  end if;
  if v_session.password_fingerprint is not null
     and v_session.password_fingerprint is distinct from p_password_fingerprint then
    raise exception 'password_fingerprint_mismatch';
  end if;
  if v_session.state = 'completed' then
    return query select v_session.user_id, v_session.recovery_id, true;
    return;
  end if;
  if v_session.expires_at <= now() or v_session.revoked_at is not null then
    raise exception 'recovery_session_invalid';
  end if;
  if v_session.state = 'auth_updating'
     and v_session.auth_attempt_started_at > now() - interval '2 minutes' then
    raise exception 'auth_update_in_progress';
  end if;
  if v_session.state not in ('active', 'retryable', 'auth_updating') then
    raise exception 'recovery_session_invalid';
  end if;

  update public.account_recovery_sessions
  set state = 'auth_updating',
      password_fingerprint = p_password_fingerprint,
      auth_attempt_count = auth_attempt_count + 1,
      auth_attempt_started_at = now(),
      failure_code = null
  where id = v_session.id;
  return query select v_session.user_id, v_session.recovery_id, false;
end;
$$;

create or replace function launcher.release_recovery_password_change(
  p_token_verifier text,
  p_password_fingerprint text,
  p_failure_code text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_session public.account_recovery_sessions%rowtype;
begin
  if p_token_verifier !~ '^[0-9a-f]{64}$'
     or p_password_fingerprint !~ '^[0-9a-f]{64}$' then
    raise exception 'recovery_session_invalid';
  end if;
  select * into v_session
  from public.account_recovery_sessions
  where token_verifier = p_token_verifier and scope = 'change_password'
  for update;
  if not found
     or v_session.password_fingerprint is distinct from p_password_fingerprint
     or v_session.state <> 'auth_updating' then
    raise exception 'recovery_session_invalid';
  end if;
  update public.account_recovery_sessions
  set state = 'retryable', failure_code = left(coalesce(p_failure_code, 'auth_failed'), 80)
  where id = v_session.id;
  insert into public.audit_events(user_id, event_type, metadata)
  values (v_session.user_id, 'account_recovery_auth_failed', jsonb_build_object(
    'target_user_id', v_session.user_id,
    'recovery_id', v_session.recovery_id,
    'recovery_session_id', v_session.id,
    'failure_code', left(coalesce(p_failure_code, 'auth_failed'), 80)
  ));
  return true;
end;
$$;

create or replace function launcher.complete_recovery_password_change(
  p_token_verifier text,
  p_password_fingerprint text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_session public.account_recovery_sessions%rowtype;
  v_sessions_revoked integer := 0;
begin
  if p_token_verifier !~ '^[0-9a-f]{64}$'
     or p_password_fingerprint !~ '^[0-9a-f]{64}$' then
    raise exception 'recovery_session_invalid';
  end if;
  select * into v_session
  from public.account_recovery_sessions
  where token_verifier = p_token_verifier and scope = 'change_password'
  for update;
  if not found
     or v_session.password_fingerprint is distinct from p_password_fingerprint then
    raise exception 'recovery_session_invalid';
  end if;
  if v_session.state = 'completed' then
    return true;
  end if;
  if v_session.state <> 'auth_updating' then
    raise exception 'recovery_session_invalid';
  end if;

  update public.launcher_sessions
  set revoked_at = coalesce(revoked_at, now())
  where user_id = v_session.user_id and revoked_at is null;
  get diagnostics v_sessions_revoked = row_count;

  update public.account_recovery_sessions
  set state = 'completed', completed_at = now(), revoked_at = now(), failure_code = null
  where id = v_session.id;
  insert into public.audit_events(user_id, event_type, metadata)
  values (v_session.user_id, 'account_password_recovered', jsonb_build_object(
    'target_user_id', v_session.user_id,
    'recovery_id', v_session.recovery_id,
    'recovery_session_id', v_session.id,
    'sessions_revoked', v_sessions_revoked
  ));
  return true;
end;
$$;

revoke all on function launcher.admin_generate_recovery_code(uuid, uuid, text, uuid, text)
  from public, anon, authenticated;
revoke all on function launcher.verify_recovery_code(text, text, uuid, text, text)
  from public, anon, authenticated;
revoke all on function launcher.claim_recovery_password_change(text, text)
  from public, anon, authenticated;
revoke all on function launcher.release_recovery_password_change(text, text, text)
  from public, anon, authenticated;
revoke all on function launcher.complete_recovery_password_change(text, text)
  from public, anon, authenticated;

grant execute on function launcher.admin_generate_recovery_code(uuid, uuid, text, uuid, text)
  to service_role;
grant execute on function launcher.verify_recovery_code(text, text, uuid, text, text)
  to service_role;
grant execute on function launcher.claim_recovery_password_change(text, text)
  to service_role;
grant execute on function launcher.release_recovery_password_change(text, text, text)
  to service_role;
grant execute on function launcher.complete_recovery_password_change(text, text)
  to service_role;