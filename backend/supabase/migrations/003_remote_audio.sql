begin;

-- Allow an explicit stopped result for remote stop commands and interrupted audio.
alter table public.remote_commands
  drop constraint if exists remote_commands_status_check;
alter table public.remote_commands
  add constraint remote_commands_status_check
  check (status in ('pending','received','executing','completed','stopped','failed','expired'));

-- Prevent users from linking commands to a device owned by a different account.
create or replace function public.prevent_cross_owner_command_links()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
begin
  if not exists (
    select 1 from public.devices
    where id = new.target_device_id and owner_id = new.owner_id and revoked_at is null
  ) then
    raise exception 'Target device is not active or owned by this account';
  end if;
  return new;
end;
$$;

drop trigger if exists remote_commands_owner_guard on public.remote_commands;
create trigger remote_commands_owner_guard
before insert or update on public.remote_commands
for each row execute function public.prevent_cross_owner_command_links();

create index if not exists remote_commands_pending_poll_idx
on public.remote_commands(target_device_id, status, created_at)
where status = 'pending';

commit;
