-- P1 foundation for the 5.2.0 web-auth line.
--
-- This migration intentionally creates only the server-controlled identity and
-- web-session allowlist. Entitlement/session RPCs are a later P1 slice.
-- New 5.2.0 users are created by the bridge with
-- app_metadata.auth_line = 'next' and no password. Users cannot set
-- app_metadata themselves.

create schema if not exists launcher_v2;

create table launcher_v2.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  status text not null default 'active'
    check (status in ('active', 'suspended', 'banned')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table launcher_v2.identity_links (
  id uuid primary key default gen_random_uuid(),
  identity_sub text not null unique
    check (length(identity_sub) between 1 and 255),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  status text not null default 'active'
    check (status in ('active', 'unlinked')),
  linked_at timestamptz not null default now(),
  last_login_at timestamptz
);

create index identity_links_active_user_idx
  on launcher_v2.identity_links (user_id)
  where status = 'active';

create table launcher_v2.web_sessions (
  auth_session_id uuid primary key references auth.sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  identity_link_id uuid not null
    references launcher_v2.identity_links(id) on delete cascade,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  revoked_at timestamptz
);

create index web_sessions_user_active_idx
  on launcher_v2.web_sessions (user_id)
  where revoked_at is null;

create table launcher_v2.audit_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  event_type text not null check (
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
  ),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index audit_events_user_created_idx
  on launcher_v2.audit_events (user_id, created_at desc);

alter table launcher_v2.profiles enable row level security;
alter table launcher_v2.profiles force row level security;
alter table launcher_v2.identity_links enable row level security;
alter table launcher_v2.identity_links force row level security;
alter table launcher_v2.web_sessions enable row level security;
alter table launcher_v2.web_sessions force row level security;
alter table launcher_v2.audit_events enable row level security;
alter table launcher_v2.audit_events force row level security;

-- No client has direct access in this slice. The bridge uses service_role;
-- authenticated RPC grants arrive with the claim/permit slice.
revoke all on schema launcher_v2 from public, anon, authenticated;
revoke all on all tables in schema launcher_v2 from public, anon, authenticated;
grant usage on schema launcher_v2 to service_role;
grant all on all tables in schema launcher_v2 to service_role;

alter role authenticator
  set pgrst.db_schemas = 'public, graphql_public, launcher, launcher_v2';
notify pgrst, 'reload config';

-- Route only server-controlled app_metadata to the next-line profile. The
-- default remains the legacy public profile, so 5.1.6 signup behavior is
-- unchanged.
create or replace function launcher.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_auth_line text := coalesce(new.raw_app_meta_data ->> 'auth_line', 'legacy');
begin
  if v_auth_line = 'next' then
    insert into launcher_v2.profiles (id, display_name)
    values (
      new.id,
      nullif(
        left(
          coalesce(
            new.raw_user_meta_data ->> 'display_name',
            split_part(coalesce(new.email, ''), '@', 1)
          ),
          80
        ),
        ''
      )
    )
    on conflict (id) do nothing;
  else
    insert into public.profiles (id, display_name)
    values (
      new.id,
      nullif(
        left(
          coalesce(
            new.raw_user_meta_data ->> 'display_name',
            split_part(coalesce(new.email, ''), '@', 1)
          ),
          80
        ),
        ''
      )
    )
    on conflict (id) do nothing;
  end if;
  return new;
end;
$$;

revoke all on function launcher.handle_new_user() from public;
