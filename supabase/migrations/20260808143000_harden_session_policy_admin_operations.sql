-- Harden the single-active-session policy after allowing multiple remembered
-- installations. This forward migration keeps all public Launcher RPC signatures
-- stable, binds heartbeats to the session's selected license, and makes specific
-- installation revocation a single trusted Admin transaction.

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
      'admin_password_reset'
    )
  );

create or replace function launcher.heartbeat_session(p_session_id uuid)
returns boolean
language plpgsql
security definer
set search_path = public, launcher, pg_temp
as $$
declare
  v_user_id uuid := auth.uid();
  v_count integer;
begin
  if v_user_id is null or p_session_id is null then
    return false;
  end if;

  update public.launcher_sessions s
  set last_seen_at = now()
  where s.id = p_session_id
    and s.user_id = v_user_id
    and s.revoked_at is null
    and s.last_seen_at > now() - interval '90 seconds'
    and exists (
      select 1
      from public.licenses l
      join public.products p on p.id = l.product_id
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

create or replace function launcher.admin_revoke_installation(
  p_actor_id uuid,
  p_installation_id uuid
)
returns boolean
language plpgsql
security invoker
set search_path = public, launcher, pg_temp
as $$
declare
  v_user_id uuid;
  v_revoked_at timestamptz;
  v_session_count integer := 0;
begin
  perform launcher.assert_admin_actor(p_actor_id);
  if p_installation_id is null then
    raise exception 'invalid_installation';
  end if;

  select i.user_id, i.revoked_at
  into v_user_id, v_revoked_at
  from public.installations i
  where i.id = p_installation_id
  for update;
  if v_user_id is null then
    raise exception 'installation_not_found';
  end if;

  if v_revoked_at is null then
    v_revoked_at := now();

    update public.installations
    set revoked_at = v_revoked_at
    where id = p_installation_id;

    update public.launcher_sessions
    set revoked_at = v_revoked_at
    where installation_id = p_installation_id
      and revoked_at is null;
    get diagnostics v_session_count = row_count;

    insert into public.audit_events(user_id, event_type, metadata)
    values (
      p_actor_id,
      'admin_installation_revoked',
      jsonb_build_object(
        'target_user_id', v_user_id,
        'installation_id', p_installation_id,
        'scope', 'installation',
        'sessions_revoked', v_session_count
      )
    );
  end if;

  return true;
end;
$$;

revoke all on function launcher.heartbeat_session(uuid) from public;
revoke all on function launcher.heartbeat_session(uuid) from anon;
grant execute on function launcher.heartbeat_session(uuid) to authenticated;

revoke all on function launcher.admin_revoke_installation(uuid, uuid)
  from public, anon, authenticated;
grant execute on function launcher.admin_revoke_installation(uuid, uuid)
  to service_role;

-- Fail deployment if the database no longer has the authoritative unique partial
-- index. Do not remove or weaken launcher_sessions_one_active_per_user_idx.
do $$
declare
  v_index_definition text;
begin
  select pg_get_indexdef(i.indexrelid)
  into v_index_definition
  from pg_index i
  join pg_class c on c.oid = i.indexrelid
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public'
    and c.relname = 'launcher_sessions_one_active_per_user_idx'
    and i.indisunique
    and i.indisvalid;

  if v_index_definition is null
    or position('(user_id)' in lower(v_index_definition)) = 0
    or position('where (revoked_at is null)' in lower(v_index_definition)) = 0
  then
    raise exception 'launcher_sessions_one_active_per_user_idx must remain unique on user_id where revoked_at is null';
  end if;
end;
$$;
