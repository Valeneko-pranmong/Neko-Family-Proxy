-- A newly generated Recovery Code is a per-user recovery generation boundary.
-- Preserve completed history, but revoke every unfinished Recovery Session from
-- an earlier generation in the same transaction that creates the new code.
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

  -- This target-profile row lock is the per-user generation linearization point.
  -- Competing Admin transactions cannot cross this boundary concurrently.
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

  -- Supersede the active code first. Its row lock synchronizes with concurrent
  -- verification, which also locks that code before consuming it and creating a
  -- Recovery Session. Only after that boundary can the session scan be complete.
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

  -- Revoke derivative authority from every earlier unfinished generation.
  -- Completed and already-revoked rows remain unchanged as historical evidence.
  update public.account_recovery_sessions
  set state = 'revoked',
      revoked_at = coalesce(revoked_at, now()),
      failure_code = 'superseded'
  where user_id = p_user_id
    and state in ('active', 'auth_updating', 'retryable');

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

revoke all on function launcher.admin_generate_recovery_code(uuid, uuid, text, uuid, text)
  from public, anon, authenticated;
grant execute on function launcher.admin_generate_recovery_code(uuid, uuid, text, uuid, text)
  to service_role;
