begin;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.device_pairings (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  initiator_device_id uuid not null references public.devices(id) on delete cascade,
  claimed_device_id uuid references public.devices(id) on delete set null,
  code_hash text not null unique,
  expires_at timestamptz not null,
  claimed_at timestamptz,
  created_at timestamptz not null default now(),
  constraint device_pairings_expiry_after_create check (expires_at > created_at),
  constraint device_pairings_claim_consistency check (
    (claimed_at is null and claimed_device_id is null) or
    (claimed_at is not null and claimed_device_id is not null)
  )
);
create index if not exists device_pairings_owner_expiry_idx on public.device_pairings(owner_id, expires_at desc);

create table if not exists public.event_media (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  event_id uuid not null references public.events(id) on delete cascade,
  storage_bucket text not null default 'event-media',
  storage_path text not null,
  media_type text not null check (media_type in ('screenshot','face_crop')),
  size_bytes bigint not null check (size_bytes between 1 and 10000000),
  sha256 text,
  created_at timestamptz not null default now(),
  unique(event_id, media_type),
  unique(storage_bucket, storage_path)
);
create index if not exists event_media_owner_event_idx on public.event_media(owner_id, event_id);

create table if not exists public.voice_messages (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  source_device_id uuid not null references public.devices(id) on delete cascade,
  target_device_id uuid not null references public.devices(id) on delete cascade,
  storage_path text not null unique,
  duration_ms integer not null check (duration_ms between 1 and 30000),
  size_bytes integer not null check (size_bytes between 1 and 5000000),
  status text not null default 'uploaded' check (status in ('uploaded','received','playing','completed','stopped','failed','expired')),
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists voice_messages_target_idx on public.voice_messages(target_device_id, created_at desc);
create index if not exists voice_messages_expiry_idx on public.voice_messages(expires_at);

create table if not exists public.command_receipts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  command_id uuid not null references public.remote_commands(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  status text not null check (status in ('received','executing','completed','stopped','failed','expired')),
  detail text not null default '',
  created_at timestamptz not null default now(),
  unique(command_id, status)
);
create index if not exists command_receipts_command_idx on public.command_receipts(command_id, created_at);

create table if not exists public.stream_sessions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  camera_device_id uuid not null references public.devices(id) on delete cascade,
  viewer_device_id uuid not null references public.devices(id) on delete cascade,
  status text not null default 'active' check (status in ('active','closed','expired')),
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint stream_session_devices_differ check (camera_device_id <> viewer_device_id),
  constraint stream_session_expiry_after_create check (expires_at > created_at)
);
create index if not exists stream_sessions_owner_active_idx on public.stream_sessions(owner_id, status, expires_at);

create table if not exists public.push_delivery_attempts (
  id bigint generated always as identity primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  event_id uuid not null references public.events(id) on delete cascade,
  push_token_id uuid references public.push_tokens(id) on delete set null,
  status text not null check (status in ('queued','sent','failed','invalid_token')),
  provider_message_id text,
  error_detail text,
  created_at timestamptz not null default now()
);
create index if not exists push_delivery_event_idx on public.push_delivery_attempts(event_id, created_at);

create table if not exists public.user_settings (
  owner_id uuid primary key references auth.users(id) on delete cascade,
  retention_minutes integer not null default 60 check (retention_minutes between 15 and 525600),
  push_enabled boolean not null default true,
  push_sound boolean not null default true,
  push_vibration boolean not null default true,
  biometric_unlock boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.prevent_cross_owner_device_links()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
declare
  mismatch_count integer;
begin
  select count(*) into mismatch_count
  from public.devices
  where id in (new.source_device_id, new.target_device_id)
    and owner_id <> new.owner_id;
  if mismatch_count > 0 then
    raise exception 'Cross-owner device link rejected';
  end if;
  return new;
end;
$$;

create or replace function public.prevent_cross_owner_stream_links()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
declare
  mismatch_count integer;
begin
  select count(*) into mismatch_count
  from public.devices
  where id in (new.camera_device_id, new.viewer_device_id)
    and owner_id <> new.owner_id;
  if mismatch_count > 0 then
    raise exception 'Cross-owner stream link rejected';
  end if;
  return new;
end;
$$;

drop trigger if exists voice_messages_owner_guard on public.voice_messages;
create trigger voice_messages_owner_guard
before insert or update on public.voice_messages
for each row execute function public.prevent_cross_owner_device_links();

drop trigger if exists stream_sessions_owner_guard on public.stream_sessions;
create trigger stream_sessions_owner_guard
before insert or update on public.stream_sessions
for each row execute function public.prevent_cross_owner_stream_links();

drop trigger if exists voice_messages_updated_at on public.voice_messages;
create trigger voice_messages_updated_at before update on public.voice_messages
for each row execute function public.set_updated_at();

drop trigger if exists stream_sessions_updated_at on public.stream_sessions;
create trigger stream_sessions_updated_at before update on public.stream_sessions
for each row execute function public.set_updated_at();

drop trigger if exists user_settings_updated_at on public.user_settings;
create trigger user_settings_updated_at before update on public.user_settings
for each row execute function public.set_updated_at();

alter table public.device_pairings enable row level security;
alter table public.event_media enable row level security;
alter table public.voice_messages enable row level security;
alter table public.command_receipts enable row level security;
alter table public.stream_sessions enable row level security;
alter table public.push_delivery_attempts enable row level security;
alter table public.user_settings enable row level security;

create policy "owners manage pairings" on public.device_pairings
for all using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy "owners manage event media" on public.event_media
for all using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy "owners manage voice messages" on public.voice_messages
for all using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy "owners read command receipts" on public.command_receipts
for select using ((select auth.uid()) = owner_id);
create policy "owners insert command receipts" on public.command_receipts
for insert with check ((select auth.uid()) = owner_id);
create policy "owners manage stream sessions" on public.stream_sessions
for all using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy "owners read push delivery" on public.push_delivery_attempts
for select using ((select auth.uid()) = owner_id);
create policy "owners manage settings" on public.user_settings
for all using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('voice-media', 'voice-media', false, 5000000, array['audio/wav'])
on conflict (id) do update set public = false, file_size_limit = 5000000, allowed_mime_types = array['audio/wav'];

create policy "owners read own voice media" on storage.objects for select using (
  bucket_id = 'voice-media' and (storage.foldername(name))[1] = (select auth.uid())::text
);
create policy "owners upload own voice media" on storage.objects for insert with check (
  bucket_id = 'voice-media' and (storage.foldername(name))[1] = (select auth.uid())::text
);
create policy "owners delete own voice media" on storage.objects for delete using (
  bucket_id = 'voice-media' and (storage.foldername(name))[1] = (select auth.uid())::text
);

create or replace function public.cleanup_expired_homeguard_rows()
returns table(deleted_events bigint, deleted_voice_messages bigint, expired_commands bigint, expired_streams bigint)
language plpgsql
security definer
set search_path = public
as $$
declare
  events_count bigint;
  voice_count bigint;
  commands_count bigint;
  streams_count bigint;
begin
  delete from public.events where expires_at < now();
  get diagnostics events_count = row_count;
  delete from public.voice_messages where expires_at < now();
  get diagnostics voice_count = row_count;
  update public.remote_commands set status = 'expired', updated_at = now()
    where status in ('pending','received') and expires_at < now();
  get diagnostics commands_count = row_count;
  update public.stream_sessions set status = 'expired', updated_at = now()
    where status = 'active' and expires_at < now();
  get diagnostics streams_count = row_count;
  return query select events_count, voice_count, commands_count, streams_count;
end;
$$;
revoke all on function public.cleanup_expired_homeguard_rows() from public, anon, authenticated;

grant select, insert, update, delete on public.device_pairings to authenticated;
grant select, insert, update, delete on public.event_media to authenticated;
grant select, insert, update, delete on public.voice_messages to authenticated;
grant select, insert on public.command_receipts to authenticated;
grant select, insert, update, delete on public.stream_sessions to authenticated;
grant select on public.push_delivery_attempts to authenticated;
grant select, insert, update, delete on public.user_settings to authenticated;

commit;
