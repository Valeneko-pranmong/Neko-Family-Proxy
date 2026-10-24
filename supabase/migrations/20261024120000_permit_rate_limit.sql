-- Server-side rate limit for issue_launch_permit.
-- The table is not directly readable or writable by clients; the
-- SECURITY DEFINER function is the only authenticated entry point.

create table if not exists launcher.permit_attempts (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  attempted_at timestamptz not null default now(),
  allowed boolean not null,
  reason text not null check (reason in ('allowed', 'rate_limited'))
);

create index if not exists permit_attempts_user_attempted_idx
  on launcher.permit_attempts (user_id, attempted_at desc);

alter table launcher.permit_attempts enable row level security;
alter table launcher.permit_attempts force row level security;
revoke all on launcher.permit_attempts from public, anon, authenticated;

create or replace function launcher.consume_permit_attempt(
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
  v_attempt_count integer;
  v_allowed boolean;
begin
  if v_user_id is null then
    return jsonb_build_object(
      'allowed', false,
      'remaining', 0,
      'reason', 'not_authenticated'
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

  delete from launcher.permit_attempts
  where user_id = v_user_id
    and attempted_at < now() - interval '1 day';

  select count(*) into v_attempt_count
  from launcher.permit_attempts
  where user_id = v_user_id
    and attempted_at > now() - make_interval(secs => p_window_seconds);

  v_allowed := v_attempt_count < p_limit;

  insert into launcher.permit_attempts (user_id, allowed, reason)
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

revoke all on function launcher.consume_permit_attempt(integer, integer)
  from public, anon;
grant execute on function launcher.consume_permit_attempt(integer, integer)
  to authenticated;
