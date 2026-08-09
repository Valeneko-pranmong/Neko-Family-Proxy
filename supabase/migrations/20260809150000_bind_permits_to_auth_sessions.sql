-- Bind the one authoritative Launcher session to the validated Supabase Auth
-- session that claimed it. Historical rows remain NULL and therefore cannot
-- authorize permits until the Launcher performs a fresh claim.

alter table public.launcher_sessions
  add column auth_session_id uuid;

comment on column public.launcher_sessions.auth_session_id is
  'Validated Supabase Auth session_id that claimed this Launcher session. Required for permit issuance.';

create index launcher_sessions_auth_session_id_idx
  on public.launcher_sessions (auth_session_id)
  where revoked_at is null;

create or replace function launcher.bind_launcher_auth_session()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_auth_session_id uuid;
begin
  begin
    v_auth_session_id := nullif(auth.jwt() ->> 'session_id', '')::uuid;
  exception
    when invalid_text_representation then
      raise exception 'not_authenticated' using errcode = '28000';
  end;

  if auth.uid() is null or v_auth_session_id is null then
    raise exception 'not_authenticated' using errcode = '28000';
  end if;
  if new.user_id <> auth.uid() then
    raise exception 'session_user_mismatch' using errcode = '42501';
  end if;

  new.auth_session_id := v_auth_session_id;
  return new;
end;
$$;

revoke all on function launcher.bind_launcher_auth_session() from public, anon, authenticated;

drop trigger if exists bind_launcher_auth_session_before_insert
  on public.launcher_sessions;
create trigger bind_launcher_auth_session_before_insert
before insert on public.launcher_sessions
for each row execute function launcher.bind_launcher_auth_session();

create table launcher.launch_permit_reservations (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  auth_session_id uuid not null references auth.sessions(id) on delete cascade,
  launcher_session_id uuid not null references public.launcher_sessions(id) on delete cascade,
  challenge text not null check (challenge ~ '^[A-Za-z0-9_-]{43}$'),
  issued_at timestamptz not null default now(),
  unique (auth_session_id, challenge)
);

create index launch_permit_reservations_user_issued_idx
  on launcher.launch_permit_reservations (user_id, issued_at desc);

alter table launcher.launch_permit_reservations enable row level security;
revoke all on table launcher.launch_permit_reservations from public, anon, authenticated;
revoke all on sequence launcher.launch_permit_reservations_id_seq from public, anon, authenticated;

-- Keep rolling per-user rate accounting independent of Auth-session deletion.
-- Account deletion still removes these short-lived events through auth.users.
create table launcher.launch_permit_rate_events (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  issued_at timestamptz not null default now()
);

create index launch_permit_rate_events_user_issued_idx
  on launcher.launch_permit_rate_events (user_id, issued_at desc);

alter table launcher.launch_permit_rate_events enable row level security;
revoke all on table launcher.launch_permit_rate_events from public, anon, authenticated;
revoke all on sequence launcher.launch_permit_rate_events_id_seq from public, anon, authenticated;

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

  -- This is the permit issuance linearization point. It uses the same per-user
  -- transaction lock as claim_session, so replacement cannot interleave with
  -- authorization/reservation for this user.
  perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));

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

revoke all on function launcher.authorize_launch_permit(text, text) from public;
revoke all on function launcher.authorize_launch_permit(text, text) from anon;
grant execute on function launcher.authorize_launch_permit(text, text) to authenticated;

-- Preserve and verify the existing one-active-Launcher-session authority.
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
