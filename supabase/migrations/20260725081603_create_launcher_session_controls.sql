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
  if v_user_id is null or p_session_id is null then return false; end if;
  update public.launcher_sessions s
  set last_seen_at = now()
  where s.id = p_session_id and s.user_id = v_user_id and s.revoked_at is null
    and s.last_seen_at > now() - interval '90 seconds'
    and exists (
      select 1 from public.licenses l join public.products p on p.id = l.product_id
      where l.user_id = v_user_id and p.code = 'neko-family-proxy' and p.is_active
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
set search_path = public, launcher, pg_temp
as $$
declare
  v_user_id uuid := auth.uid();
  v_count integer;
begin
  if v_user_id is null or p_session_id is null then return false; end if;
  update public.launcher_sessions set revoked_at = now()
  where id = p_session_id and user_id = v_user_id and revoked_at is null;
  get diagnostics v_count = row_count;
  if v_count > 0 then
    insert into public.audit_events(user_id, event_type, metadata)
    values (v_user_id, 'session_revoked', jsonb_build_object('session_id', p_session_id, 'reason', 'client_release'));
  end if;
  return v_count > 0;
end;
$$;

revoke all on schema launcher from public;
grant usage on schema launcher to authenticated;
revoke all on function launcher.claim_session(text, text, text) from public;
revoke all on function launcher.heartbeat_session(uuid) from public;
revoke all on function launcher.release_session(uuid) from public;
grant execute on function launcher.claim_session(text, text, text) to authenticated;
grant execute on function launcher.heartbeat_session(uuid) to authenticated;
grant execute on function launcher.release_session(uuid) to authenticated;
