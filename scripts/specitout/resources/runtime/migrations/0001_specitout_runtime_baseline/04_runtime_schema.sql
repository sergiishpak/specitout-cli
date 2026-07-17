       using doomed
       where t.ctid = doomed.ctid',
      batch_size
    )
    using target_export_id;

    get diagnostics deleted_count = row_count;

    if deleted_count = 0 then
      select count(*)
      into remaining_count
      from bubble_mcp.entities
      where export_id = target_export_id;

      if remaining_count > 0 then
        raise exception
          'delete_export_scoped_rows could not delete all entities for export %, % rows remain',
          target_export_id,
          remaining_count;
      end if;
    end if;

    return deleted_count;
  end if;

  execute format(
    'with doomed as (
       select ctid
       from bubble_mcp.%I
       where export_id = $1
       limit %s
     )
     delete from bubble_mcp.%I t
     using doomed
     where t.ctid = doomed.ctid',
    target_table_name,
    batch_size,
    target_table_name
  )
  using target_export_id;

  get diagnostics deleted_count = row_count;
  return deleted_count;
end
$$;

grant execute on function bubble_mcp.delete_export_scoped_rows(text, uuid, integer) to service_role;

create index if not exists entities_export_parent_entity_key_idx
on bubble_mcp.entities (export_id, parent_entity_key)
where parent_entity_key is not null;

do $$
begin
  if not exists (
    select 1
    from pg_type t
    where t.typnamespace = 'bubble_mcp'::regnamespace
      and t.typname = 'lifecycle_action_status'
  ) then
    create type bubble_mcp.lifecycle_action_status as enum (
      'running',
      'succeeded',
      'failed'
    );
  end if;
end
$$;

create table if not exists bubble_mcp.lifecycle_actions (
  id uuid primary key default extensions.gen_random_uuid(),
  action text not null,
  target_kind text not null,
  target_app_id uuid,
  target_app_slug text not null,
  target_export_id uuid,
  target_version_label text,
  status bubble_mcp.lifecycle_action_status not null default 'running',
  actor text not null default 'cli:service-role',
  details_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  constraint lifecycle_actions_action_nonempty_check check (btrim(action) <> ''),
  constraint lifecycle_actions_target_kind_check check (target_kind in ('app', 'export')),
  constraint lifecycle_actions_target_app_slug_nonempty_check check (btrim(target_app_slug) <> ''),
  constraint lifecycle_actions_actor_nonempty_check check (btrim(actor) <> ''),
  constraint lifecycle_actions_finished_after_created_check check (
    finished_at is null or finished_at >= created_at
  )
);

create index if not exists lifecycle_actions_target_app_slug_created_idx
  on bubble_mcp.lifecycle_actions (target_app_slug, created_at desc);

create index if not exists lifecycle_actions_target_export_created_idx
  on bubble_mcp.lifecycle_actions (target_export_id, created_at desc)
  where target_export_id is not null;

create or replace function bubble_mcp.validate_app_lifecycle_transition(
  current_status bubble_mcp.app_lifecycle_status,
  next_status bubble_mcp.app_lifecycle_status
)
returns void
language plpgsql
set search_path = bubble_mcp, public
as $$
begin
  if current_status = next_status then
    return;
  end if;

  if not (
    (current_status = 'active' and next_status in ('archived', 'pending_delete'))
    or (current_status = 'archived' and next_status = 'pending_delete')
  ) then
    raise exception 'illegal app lifecycle transition from % to %', current_status, next_status;
  end if;
end
$$;

create or replace function bubble_mcp.enforce_app_state_transition()
returns trigger
language plpgsql
set search_path = bubble_mcp, public
as $$
begin
  if tg_op <> 'UPDATE' then
    return new;
  end if;

  if new.lifecycle_status is distinct from old.lifecycle_status then
    perform bubble_mcp.validate_app_lifecycle_transition(old.lifecycle_status, new.lifecycle_status);

    case new.lifecycle_status
      when 'archived' then
        new.archived_at := now();
      when 'pending_delete' then
        new.pending_delete_at := now();
      else
        null;
    end case;
  end if;

  return new;
end
$$;

create or replace function bubble_mcp.enforce_active_export_pointer()
returns trigger
language plpgsql
set search_path = bubble_mcp, public
as $$
declare
  current_app bubble_mcp.apps%rowtype;
  target_export bubble_mcp.exports%rowtype;
  active_export bubble_mcp.exports%rowtype;
  allow_retirement boolean := current_setting('bubble_mcp.allow_app_retirement', true) = 'on';
begin
  select *
  into current_app
  from bubble_mcp.apps
  where id = new.id;

  if not found then
    raise exception 'app % does not exist for active export validation', new.id;
  end if;

  if current_app.active_export_id is not null then
    select *
    into target_export
    from bubble_mcp.exports
    where id = current_app.active_export_id;

    if not found then
      raise exception 'active_export_id % does not reference an existing export', current_app.active_export_id;
    end if;

    if target_export.app_id <> current_app.id then
      raise exception 'active_export_id % does not belong to app %', current_app.active_export_id, current_app.id;
    end if;

    if target_export.lifecycle_status <> 'active' then
      raise exception 'active_export_id % must point to an export in active lifecycle state', current_app.active_export_id;
    end if;

    if not bubble_mcp.is_query_eligible_export_readiness(target_export.readiness_status) then
      raise exception 'active_export_id % must point to a query-eligible export', current_app.active_export_id;
    end if;
  end if;

  select *
  into active_export
  from bubble_mcp.exports
  where app_id = current_app.id
    and lifecycle_status = 'active';

  if found then
    if current_app.lifecycle_status = 'active' then
      if current_app.active_export_id is distinct from active_export.id then
        raise exception 'app % must point active_export_id at active export %',
          current_app.id,
          active_export.id;
      end if;
    elsif not (
      current_app.lifecycle_status = 'pending_delete'
      and allow_retirement
      and current_app.active_export_id is null
    ) then
      raise exception 'app % cannot leave active lifecycle while export % remains active',
        current_app.id,
        active_export.id;
    end if;
  end if;

  return new;
end
$$;

create or replace function bubble_mcp.activate_export(
  target_app_id uuid,
  target_export_id uuid
)
returns bubble_mcp.exports
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  owning_app bubble_mcp.apps%rowtype;
  previous_export bubble_mcp.exports%rowtype;
  target_export bubble_mcp.exports%rowtype;
begin
  set constraints all deferred;

  select *
  into owning_app
  from bubble_mcp.apps
  where id = target_app_id
  for update;

  if not found then
    raise exception 'app % does not exist for activation', target_app_id;
  end if;

  if owning_app.lifecycle_status <> 'active' then
    raise exception 'app % must be active to activate an export, found %',
      target_app_id,
      owning_app.lifecycle_status;
  end if;

  select *
  into target_export
  from bubble_mcp.exports
  where id = target_export_id
  for update;

  if not found then
    raise exception 'target export % does not exist', target_export_id;
  end if;

  if target_export.app_id <> owning_app.id then
    raise exception 'target export % does not belong to app %',
      target_export_id,
      owning_app.id;
  end if;

  if target_export.lifecycle_status not in ('candidate', 'superseded') then
    raise exception 'target export % must be candidate or superseded, found %',
      target_export_id,
      target_export.lifecycle_status;
  end if;

  if not bubble_mcp.is_query_eligible_export_readiness(target_export.readiness_status) then
    raise exception 'target export % is not query-eligible, found readiness %',
      target_export_id,
      target_export.readiness_status;
  end if;

  if owning_app.active_export_id is not null then
    select *
    into previous_export
    from bubble_mcp.exports
    where id = owning_app.active_export_id
    for update;

    if previous_export.id is distinct from target_export.id then
      update bubble_mcp.exports
      set lifecycle_status = 'superseded'
      where id = previous_export.id;
    end if;
  end if;

  update bubble_mcp.exports
  set lifecycle_status = 'active'
  where id = target_export.id
  returning *
  into target_export;

  update bubble_mcp.apps
  set active_export_id = target_export.id
  where id = owning_app.id;

  set constraints all immediate;

  return target_export;
end
$$;

create or replace function bubble_mcp.archive_export(
  target_app_id uuid,
  target_export_id uuid
)
returns bubble_mcp.exports
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  owning_app bubble_mcp.apps%rowtype;
  target_export bubble_mcp.exports%rowtype;
begin
  select *
  into owning_app
  from bubble_mcp.apps
  where id = target_app_id;

  if not found then
    raise exception 'app % does not exist for archive', target_app_id;
  end if;

  select *
  into target_export
  from bubble_mcp.exports
  where id = target_export_id;

  if not found then
    raise exception 'target export % does not exist', target_export_id;
  end if;

  if target_export.app_id <> owning_app.id then
    raise exception 'target export % does not belong to app %',
      target_export_id,
      owning_app.id;
  end if;

  if target_export.lifecycle_status not in ('candidate', 'superseded') then
    raise exception 'target export % must be candidate or superseded to archive, found %',
      target_export_id,
      target_export.lifecycle_status;
  end if;

  update bubble_mcp.exports
  set lifecycle_status = 'archived'
  where id = target_export.id
  returning *
  into target_export;

  return target_export;
end
$$;

create or replace function bubble_mcp.archive_app(
  target_app_id uuid
)
returns bubble_mcp.apps
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  target_app bubble_mcp.apps%rowtype;
begin
  select *
  into target_app
  from bubble_mcp.apps
  where id = target_app_id
  for update;

  if not found then
    raise exception 'app % does not exist for archive', target_app_id;
  end if;

  if target_app.active_export_id is not null then
    raise exception 'app % still has an active export pointer', target_app_id;
  end if;

  if exists (
    select 1
    from bubble_mcp.exports
    where app_id = target_app.id
      and lifecycle_status = 'active'
  ) then
    raise exception 'app % still has an active export', target_app_id;
  end if;

  update bubble_mcp.apps
  set lifecycle_status = 'archived'
  where id = target_app.id
  returning *
  into target_app;

  return target_app;
end
$$;

create or replace function bubble_mcp.prepare_app_for_delete(
  target_app_id uuid
)
returns bubble_mcp.apps
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  target_app bubble_mcp.apps%rowtype;
begin
  perform set_config('bubble_mcp.allow_app_retirement', 'on', true);

  update bubble_mcp.apps
  set active_export_id = null,
      lifecycle_status = 'pending_delete'
  where id = target_app_id
  returning *
  into target_app;

  if not found then
    raise exception 'app % does not exist for delete preparation', target_app_id;
  end if;

  return target_app;
end
$$;

create or replace function bubble_mcp.block_direct_export_delete()
returns trigger
language plpgsql
set search_path = bubble_mcp, public
as $$
begin
  if current_setting('bubble_mcp.allow_export_delete', true) = 'on' then
    return old;
  end if;

  raise exception 'direct delete of export % is blocked; use coordinated lifecycle commands instead', old.id;
end
$$;

create or replace function bubble_mcp.finalize_delete_export(
  target_export_id uuid
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
