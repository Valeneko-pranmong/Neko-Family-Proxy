-- Bind Launcher session controls to the exact live Supabase Auth session that
-- claimed the Launcher session. Also bound permit-ledger growth without
-- weakening the 30-second replay or one-minute rate windows.

create index launch_permit_reservations_issued_at_idx
  on launcher.launch_permit_reservations (issued_at);

create index launch_permit_rate_events_issued_at_idx
  on launcher.launch_permit_rate_events (issued_at);

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
    when invalid_text_representation then
      return false;
  end;

  if v_user_id is null or v_auth_session_id is null or p_session_id is null then
    return false;
  end if;

  update public.launcher_sessions s
  set last_seen_at = now()
  where s.id = p_session_id
    and s.user_id = v_user_id
    and s.auth_session_id = v_auth_session_id
    and s.revoked_at is null
    and s.last_seen_at > now() - interval '90 seconds'
    and exists (
      select 1
      from auth.sessions a
      where a.id = v_auth_session_id
        and a.user_id = v_user_id
        and (a.not_after is null or a.not_after > now())
    )
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
    when invalid_text_representation then
      return false;
  end;

  if v_user_id is null or v_auth_session_id is null or p_session_id is null then
    return false;
  end if;

  update public.launcher_sessions s
  set revoked_at = now()
  where s.id = p_session_id
    and s.user_id = v_user_id
    and s.auth_session_id = v_auth_session_id
    and s.revoked_at is null
    and exists (
      select 1
      from auth.sessions a
      where a.id = v_auth_session_id
        and a.user_id = v_user_id
        and (a.not_after is null or a.not_after > now())
    );

  get diagnostics v_count = row_count;
  if v_count > 0 then
    insert into public.audit_events(user_id, event_type, metadata)
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

-- Recreate permit authorization with bounded per-user cleanup inside the same
-- per-user transaction lock as claiming and issuance. Ten minutes is
-- deliberately longer than both the strict 30-second permit/challenge lifetime
-- and the one-minute rolling rate window. Active users therefore retain at most
-- a bounded tail while dormant users retain only their last bounded issuance
-- window. The global issued_at indexes also support controlled operator cleanup.
create or replace function launcher.authorize_launch_permit(
  p_product_code text,
  p_challenge text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := auth.uid();
  v_auth_session_id uuid;
  v_result jsonb;
  v_launcher_session_id uuid;
  v_recent_issuances integer;
begin
  begin
    v_auth_session_id := nullif(auth.jwt() ->> 'session_id', '')::uuid;
  exception
    when invalid_text_representation then
      return null;
  end;

  if v_user_id is null or v_auth_session_id is null then
    return null;
  end if;
  if p_product_code <> 'neko-family-proxy' then
    return null;
  end if;
  if p_challenge is null or p_challenge !~ '^[A-Za-z0-9_-]{43}$' then
    return null;
  end if;

  perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));

  delete from launcher.launch_permit_reservations
  where user_id = v_user_id
    and issued_at < now() - interval '10 minutes';

  delete from launcher.launch_permit_rate_events
  where user_id = v_user_id
    and issued_at < now() - interval '10 minutes';

  if exists (
    select 1
    from launcher.launch_permit_reservations r
    where r.auth_session_id = v_auth_session_id
      and r.challenge = p_challenge
  ) then
    return null;
  end if;

  select count(*)
  into v_recent_issuances
  from launcher.launch_permit_rate_events r
  where r.user_id = v_user_id
    and r.issued_at > now() - interval '1 minute';
  if v_recent_issuances >= 10 then
    return null;
  end if;

  select jsonb_build_object(
    'user_id', s.user_id,
    'auth_session_id', s.auth_session_id,
    'session_id', s.id,
    'installation_id', s.installation_id,
    'license_id', s.license_id,
    'product_code', p.code
  )
  into v_result
  from public.launcher_sessions s
  join auth.sessions a on a.id = v_auth_session_id
  join public.profiles pr on pr.id = s.user_id
  join public.installations i on i.id = s.installation_id
  join public.licenses l on l.id = s.license_id
  join public.products p on p.id = l.product_id
  where s.user_id = v_user_id
    and s.auth_session_id = v_auth_session_id
    and a.user_id = v_user_id
    and (a.not_after is null or a.not_after > now())
    and s.revoked_at is null
    and s.last_seen_at > now() - interval '90 seconds'
    and pr.status = 'active'
    and i.user_id = s.user_id
    and l.user_id = s.user_id
    and l.status = 'active'
    and l.valid_from <= now()
    and l.valid_until > now()
    and p.code = p_product_code
    and p.is_active
  limit 1;

  if v_result is null then
    return null;
  end if;

  v_launcher_session_id := (v_result ->> 'session_id')::uuid;
  insert into launcher.launch_permit_reservations(
    user_id,
    auth_session_id,
    launcher_session_id,
    challenge
  )
  values (
    v_user_id,
    v_auth_session_id,
    v_launcher_session_id,
    p_challenge
  );

  insert into launcher.launch_permit_rate_events(user_id)
  values (v_user_id);

  return v_result;
end;
$$;

revoke all on function launcher.heartbeat_session(uuid) from public, anon;
grant execute on function launcher.heartbeat_session(uuid) to authenticated;

revoke all on function launcher.release_session(uuid) from public, anon;
grant execute on function launcher.release_session(uuid) to authenticated;

revoke all on function launcher.authorize_launch_permit(text, text)
  from public, anon;
grant execute on function launcher.authorize_launch_permit(text, text)
  to authenticated;

revoke all on table launcher.launch_permit_reservations
  from public, anon, authenticated;
revoke all on sequence launcher.launch_permit_reservations_id_seq
  from public, anon, authenticated;
revoke all on table launcher.launch_permit_rate_events
  from public, anon, authenticated;
revoke all on sequence launcher.launch_permit_rate_events_id_seq
  from public, anon, authenticated;
