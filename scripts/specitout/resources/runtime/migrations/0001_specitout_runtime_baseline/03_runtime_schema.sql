execute function bubble_mcp.enforce_active_export_pointer();

drop trigger if exists exports_active_pointer_state_guard on bubble_mcp.exports;
create constraint trigger exports_active_pointer_state_guard
after update of app_id, lifecycle_status, readiness_status
on bubble_mcp.exports
deferrable initially deferred
for each row
execute function bubble_mcp.enforce_export_state_for_active_pointer();

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where connamespace = 'bubble_mcp'::regnamespace
      and conname = 'ingestion_runs_export_phase_key'
  ) then
    alter table bubble_mcp.ingestion_runs
      add constraint ingestion_runs_export_phase_key unique (export_id, phase);
  end if;
end
$$;

create or replace function bubble_mcp.is_default_safe_export_readiness(
  target_status bubble_mcp.export_readiness_status
)
returns boolean
language sql
immutable
set search_path = bubble_mcp, public
as $$
  select target_status in ('searchable', 'embedding_pending', 'ready');
$$;

create or replace function bubble_mcp.cutover_replace_active_export(
  target_app_id uuid,
  replacement_export_id uuid
)
returns bubble_mcp.exports
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  owning_app bubble_mcp.apps%rowtype;
  previous_export bubble_mcp.exports%rowtype;
  replacement_export bubble_mcp.exports%rowtype;
  replacement_target_export_id uuid;
begin
  set constraints all deferred;

  select *
  into owning_app
  from bubble_mcp.apps
  where id = target_app_id
  for update;

  if not found then
    raise exception 'app % does not exist for replacement cutover', target_app_id;
  end if;

  if owning_app.active_export_id is null then
    raise exception 'app % has no active export to replace', target_app_id;
  end if;

  select *
  into previous_export
  from bubble_mcp.exports
  where id = owning_app.active_export_id
  for update;

  select *
  into replacement_export
  from bubble_mcp.exports
  where id = replacement_export_id
  for update;

  if not found then
    raise exception 'replacement export % does not exist', replacement_export_id;
  end if;

  if replacement_export.app_id <> owning_app.id then
    raise exception 'replacement export % does not belong to app %',
      replacement_export_id,
      owning_app.id;
  end if;

  replacement_target_export_id := replacement_export.supersedes_export_id;
  if replacement_target_export_id is null then
    begin
      replacement_target_export_id := nullif(
        replacement_export.metadata_json ->> 'pending_replacement_of_export_id',
        ''
      )::uuid;
    exception
      when invalid_text_representation then
        raise exception 'replacement export % has invalid pending replacement metadata',
          replacement_export_id;
    end;
  end if;

  if replacement_target_export_id is null then
    raise exception 'replacement export % does not declare a replacement target',
      replacement_export_id;
  end if;

  if owning_app.active_export_id is distinct from replacement_target_export_id then
    raise exception 'replacement export % was prepared to replace export %, not current active export %',
      replacement_export_id,
      replacement_target_export_id,
      owning_app.active_export_id;
  end if;

  if replacement_export.lifecycle_status <> 'candidate' then
    raise exception 'replacement export % must still be candidate, found %',
      replacement_export_id,
      replacement_export.lifecycle_status;
  end if;

  if not bubble_mcp.is_default_safe_export_readiness(replacement_export.readiness_status) then
    raise exception 'replacement export % is not ready for active cutover, found readiness %',
      replacement_export_id,
      replacement_export.readiness_status;
  end if;

  if coalesce(replacement_export.metadata_json -> 'verification' ->> 'status', '') <> 'passed' then
    raise exception 'replacement export % has not passed verification',
      replacement_export_id;
  end if;

  update bubble_mcp.exports
  set lifecycle_status = 'superseded'
  where id = previous_export.id;

  update bubble_mcp.exports
  set lifecycle_status = 'active'
  where id = replacement_export.id
  returning *
  into replacement_export;

  update bubble_mcp.apps
  set active_export_id = replacement_export.id
  where id = owning_app.id;

  set constraints all immediate;

  return replacement_export;
end
$$;

grant usage on schema bubble_mcp to service_role;

grant select, insert, update, delete
on all tables in schema bubble_mcp
to service_role;

grant usage, select
on all sequences in schema bubble_mcp
to service_role;

grant execute
on all functions in schema bubble_mcp
to service_role;

alter default privileges in schema bubble_mcp
grant select, insert, update, delete
on tables to service_role;

alter default privileges in schema bubble_mcp
grant usage, select
on sequences to service_role;

alter default privileges in schema bubble_mcp
grant execute
on functions to service_role;

create or replace function bubble_mcp.delete_export_scoped_rows(
  target_table_name text,
  target_export_id uuid
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  batch_size integer := 5000;
  deleted_count integer := 0;
begin
  if target_table_name not in (
    'source_evidence',
    'entities',
    'edges',
    'entity_facets',
    'overlay_links',
    'public_api_workflow_index'
  ) then
    raise exception 'delete_export_scoped_rows does not support table %', target_table_name;
  end if;

  loop
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
    exit when deleted_count = 0;
  end loop;
end
$$;

grant execute on function bubble_mcp.delete_export_scoped_rows(text, uuid) to service_role;

create or replace function bubble_mcp.delete_export_scoped_rows(
  target_table_name text,
  target_export_id uuid
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  batch_size integer := 5000;
  deleted_count integer := 0;
  remaining_count integer := 0;
begin
  if target_table_name not in (
    'source_evidence',
    'entities',
    'edges',
    'entity_facets',
    'overlay_links',
    'public_api_workflow_index'
  ) then
    raise exception 'delete_export_scoped_rows does not support table %', target_table_name;
  end if;

  if target_table_name = 'entities' then
    loop
      execute format(
        'with doomed as (
           select e.ctid
           from bubble_mcp.entities e
           where e.export_id = $1
             and not exists (
               select 1
               from bubble_mcp.entities child
               where child.export_id = e.export_id
                 and child.parent_entity_key = e.entity_key
             )
           limit %s
         )
         delete from bubble_mcp.entities t
         using doomed
         where t.ctid = doomed.ctid',
        batch_size
      )
      using target_export_id;

      get diagnostics deleted_count = row_count;
      exit when deleted_count = 0;
    end loop;

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

    return;
  end if;

  loop
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
    exit when deleted_count = 0;
  end loop;
end
$$;

grant execute on function bubble_mcp.delete_export_scoped_rows(text, uuid) to service_role;

create or replace function bubble_mcp.delete_export_scoped_rows(
  target_table_name text,
  target_export_id uuid
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
declare
  batch_size integer := 5000;
  deleted_count integer := 0;
  remaining_count integer := 0;
begin
  if target_table_name not in (
    'source_evidence',
    'entities',
    'edges',
    'entity_facets',
    'overlay_links',
    'public_api_workflow_index'
  ) then
    raise exception 'delete_export_scoped_rows does not support table %', target_table_name;
  end if;

  if target_table_name = 'entities' then
    loop
      execute format(
        'with doomed as (
           select e.ctid
           from bubble_mcp.entities e
           where e.export_id = $1
             and not exists (
               select 1
               from bubble_mcp.entities child
               where child.export_id = e.export_id
                 and child.parent_entity_key = e.entity_key
             )
           limit %s
         )
         delete from bubble_mcp.entities t
         using doomed
         where t.ctid = doomed.ctid',
        batch_size
      )
      using target_export_id;

      get diagnostics deleted_count = row_count;
      exit when deleted_count = 0;
    end loop;

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

    return;
  end if;

  loop
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
    exit when deleted_count = 0;
  end loop;
end
$$;

grant execute on function bubble_mcp.delete_export_scoped_rows(text, uuid) to service_role;

create or replace function bubble_mcp.delete_export_scoped_rows(
  target_table_name text,
  target_export_id uuid,
  target_batch_size integer default 1000
)
returns integer
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
declare
  batch_size integer := greatest(coalesce(target_batch_size, 1000), 1);
  deleted_count integer := 0;
  remaining_count integer := 0;
begin
  if target_table_name not in (
    'source_evidence',
    'entities',
    'edges',
    'entity_facets',
    'overlay_links',
    'public_api_workflow_index'
  ) then
    raise exception 'delete_export_scoped_rows does not support table %', target_table_name;
  end if;

  if target_table_name = 'entities' then
    execute format(
      'with doomed as (
         select e.ctid
         from bubble_mcp.entities e
         where e.export_id = $1
           and not exists (
             select 1
             from bubble_mcp.entities child
             where child.export_id = e.export_id
               and child.parent_entity_key = e.entity_key
           )
         limit %s
       )
       delete from bubble_mcp.entities t
