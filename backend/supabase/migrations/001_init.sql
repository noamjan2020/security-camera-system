begin;

create extension if not exists pgcrypto;

create table if not exists public.devices (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 100),
  device_type text not null check (device_type in ('windows_agent','android')),
  public_key text,
  revoked_at timestamptz,
  last_seen_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.cameras (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  name text not null,
  is_enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.events (
  id uuid primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  camera_id uuid references public.cameras(id) on delete set null,
  occurred_at timestamptz not null,
  expires_at timestamptz not null,
  person_confidence real not null check (person_confidence between 0 and 1),
  face_result text not null check (face_result in ('unknown','whitelisted','no_face')),
  person_name text,
  media_path text,
  viewed_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists events_owner_occurred_idx on public.events(owner_id, occurred_at desc);
create index if not exists events_expiry_idx on public.events(expires_at);

create table if not exists public.push_tokens (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  token text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.remote_commands (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  target_device_id uuid not null references public.devices(id) on delete cascade,
  command_type text not null check (command_type in ('play_audio','stop_audio','start_stream','stop_stream')),
  payload jsonb not null default '{}'::jsonb,
  nonce text not null unique,
  expires_at timestamptz not null,
  status text not null default 'pending' check (status in ('pending','received','executing','completed','failed','expired')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists remote_commands_target_idx on public.remote_commands(target_device_id, created_at desc);

create table if not exists public.audit_logs (
  id bigint generated always as identity primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  device_id uuid references public.devices(id) on delete set null,
  action text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.devices enable row level security;
alter table public.cameras enable row level security;
alter table public.events enable row level security;
alter table public.push_tokens enable row level security;
alter table public.remote_commands enable row level security;
alter table public.audit_logs enable row level security;

create policy "owners manage devices" on public.devices for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy "owners manage cameras" on public.cameras for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy "owners manage events" on public.events for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy "owners manage push tokens" on public.push_tokens for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy "owners manage commands" on public.remote_commands for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy "owners read audit logs" on public.audit_logs for select using (owner_id = auth.uid());
create policy "owners insert audit logs" on public.audit_logs for insert with check (owner_id = auth.uid());

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('event-media', 'event-media', false, 10000000, array['image/jpeg','audio/wav'])
on conflict (id) do nothing;

create policy "owners read own media" on storage.objects for select using (
  bucket_id = 'event-media' and (storage.foldername(name))[1] = auth.uid()::text
);
create policy "owners upload own media" on storage.objects for insert with check (
  bucket_id = 'event-media' and (storage.foldername(name))[1] = auth.uid()::text
);
create policy "owners delete own media" on storage.objects for delete using (
  bucket_id = 'event-media' and (storage.foldername(name))[1] = auth.uid()::text
);

commit;
