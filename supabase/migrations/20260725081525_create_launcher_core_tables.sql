create extension if not exists pgcrypto;
create schema if not exists launcher;

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  role text not null default 'customer' check (role in ('customer', 'admin')),
  status text not null default 'active' check (status in ('active', 'suspended', 'banned')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.products (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check (code = lower(code) and length(code) between 3 and 64),
  name text not null,
  max_devices smallint not null default 1 check (max_devices between 1 and 20),
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table public.licenses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  product_id uuid not null references public.products(id) on delete restrict,
  status text not null default 'active' check (status in ('active', 'suspended', 'revoked')),
  valid_from timestamptz not null default now(),
  valid_until timestamptz not null,
  max_devices smallint check (max_devices between 1 and 20),
  created_at timestamptz not null default now(),
  check (valid_until > valid_from)
);
create index licenses_user_product_validity_idx on public.licenses (user_id, product_id, status, valid_until desc);

create table public.installations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  installation_key_hash text not null check (installation_key_hash ~ '^[0-9a-f]{64}$'),
  display_name text,
  last_seen_at timestamptz not null default now(),
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  unique (user_id, installation_key_hash)
);
create index installations_user_last_seen_idx on public.installations (user_id, last_seen_at desc) where revoked_at is null;

create table public.launcher_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  installation_id uuid not null references public.installations(id) on delete cascade,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  revoked_at timestamptz
);
create unique index launcher_sessions_one_active_per_user_idx on public.launcher_sessions (user_id) where revoked_at is null;
create index launcher_sessions_user_idx on public.launcher_sessions (user_id, created_at desc);

create table public.audit_events (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users(id) on delete set null,
  event_type text not null check (event_type in ('session_claimed', 'session_revoked', 'session_rejected', 'license_rejected')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index audit_events_user_created_idx on public.audit_events (user_id, created_at desc);

alter table public.profiles enable row level security;
alter table public.products enable row level security;
alter table public.licenses enable row level security;
alter table public.installations enable row level security;
alter table public.launcher_sessions enable row level security;
alter table public.audit_events enable row level security;

create policy profiles_select_own on public.profiles for select to authenticated using ((select auth.uid()) = id);
create policy licenses_select_own on public.licenses for select to authenticated using ((select auth.uid()) = user_id);
create policy installations_select_own on public.installations for select to authenticated using ((select auth.uid()) = user_id);
create policy launcher_sessions_select_own on public.launcher_sessions for select to authenticated using ((select auth.uid()) = user_id);

insert into public.products (code, name, max_devices)
values ('neko-family-proxy', 'Neko Family Proxy', 1)
on conflict (code) do nothing;
