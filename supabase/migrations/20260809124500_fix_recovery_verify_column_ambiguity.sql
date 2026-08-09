-- Forward-fix for PL/pgSQL output-column ambiguity in verify_recovery_code.
-- Qualify relations whose columns overlap RETURNS TABLE output names.
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

  delete from public.account_recovery_rate_limits as rate_limit
  where rate_limit.window_started_at < now() - interval '1 day';

  insert into public.account_recovery_rate_limits(
    requester_verifier, window_started_at, attempt_count
  ) values (p_requester_verifier, v_window, 1)
  on conflict (requester_verifier, window_started_at)
  do update set attempt_count = public.account_recovery_rate_limits.attempt_count + 1
  returning public.account_recovery_rate_limits.attempt_count into v_rate_count;
  if v_rate_count > 10 then
    return query select false, 'recovery_rate_limited', null::uuid, null::uuid, null::timestamptz;
    return;
  end if;

  select profile.id into v_user_id
  from public.profiles as profile
  where lower(profile.username) = lower(trim(p_username))
    and profile.role = 'customer'
    and profile.status = 'active';

  select recovery_code.* into v_code
  from public.account_recovery_codes as recovery_code
  where recovery_code.user_id = v_user_id
    and recovery_code.status = 'active'
  for update;
  if not found then
    return query select false, 'recovery_invalid', null::uuid, null::uuid, null::timestamptz;
    return;
  end if;
  if v_code.expires_at <= now() then
    update public.account_recovery_codes as recovery_code
    set status = 'expired'
    where recovery_code.id = v_code.id;
    return query select false, 'recovery_invalid', null::uuid, null::uuid, null::timestamptz;
    return;
  end if;
  if v_code.code_verifier <> p_code_verifier then
    update public.account_recovery_codes as recovery_code
    set attempt_count = recovery_code.attempt_count + 1,
        status = case
          when recovery_code.attempt_count + 1 >= recovery_code.max_attempts
          then 'locked'
          else recovery_code.status
        end
    where recovery_code.id = v_code.id
    returning recovery_code.* into v_code;
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

  update public.account_recovery_codes as recovery_code
  set status = 'used', used_at = now()
  where recovery_code.id = v_code.id
    and recovery_code.status = 'active';
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

revoke all on function launcher.verify_recovery_code(text, text, uuid, text, text)
  from public, anon, authenticated;
grant execute on function launcher.verify_recovery_code(text, text, uuid, text, text)
  to service_role;
