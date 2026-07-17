as $$
declare
  target_export bubble_mcp.exports%rowtype;
begin
  select *
  into target_export
  from bubble_mcp.exports
  where id = target_export_id
  for update;

  if not found then
    raise exception 'target export % does not exist for delete finalization', target_export_id;
  end if;

  if target_export.lifecycle_status <> 'pending_delete' then
    raise exception 'target export % must be pending_delete before delete finalization, found %',
      target_export_id,
      target_export.lifecycle_status;
  end if;

  perform set_config('bubble_mcp.allow_export_delete', 'on', true);

  delete from bubble_mcp.exports
  where id = target_export_id;
end
$$;

create or replace function bubble_mcp.finalize_delete_export_for_app_retirement(
  target_app_id uuid,
  target_export_id uuid
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  target_app bubble_mcp.apps%rowtype;
  target_export bubble_mcp.exports%rowtype;
begin
  select *
  into target_app
  from bubble_mcp.apps
  where id = target_app_id
  for update;

  if not found then
    raise exception 'app % does not exist for retirement delete', target_app_id;
  end if;

  if target_app.lifecycle_status <> 'pending_delete' then
    raise exception 'app % must be pending_delete before retirement export deletion, found %',
      target_app_id,
      target_app.lifecycle_status;
  end if;

  select *
  into target_export
  from bubble_mcp.exports
  where id = target_export_id
  for update;

  if not found then
    raise exception 'target export % does not exist for retirement delete', target_export_id;
  end if;

  if target_export.app_id <> target_app_id then
    raise exception 'target export % does not belong to app %',
      target_export_id,
      target_app_id;
  end if;

  perform set_config('bubble_mcp.allow_export_delete', 'on', true);

  delete from bubble_mcp.exports
  where id = target_export_id;
end
$$;

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
    'search_documents',
    'bundle_cache',
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

drop trigger if exists apps_state_transition_guard on bubble_mcp.apps;
create trigger apps_state_transition_guard
before update of lifecycle_status
on bubble_mcp.apps
for each row
execute function bubble_mcp.enforce_app_state_transition();

grant select, insert, update on bubble_mcp.lifecycle_actions to service_role;
grant execute on function bubble_mcp.activate_export(uuid, uuid) to service_role;
grant execute on function bubble_mcp.archive_export(uuid, uuid) to service_role;
grant execute on function bubble_mcp.archive_app(uuid) to service_role;
grant execute on function bubble_mcp.prepare_app_for_delete(uuid) to service_role;
grant execute on function bubble_mcp.finalize_delete_export(uuid) to service_role;
grant execute on function bubble_mcp.finalize_delete_export_for_app_retirement(uuid, uuid) to service_role;
grant execute on function bubble_mcp.delete_export_scoped_rows(text, uuid, integer) to service_role;

create or replace function bubble_mcp.replace_export_search_documents(
  target_export_id uuid,
  documents_payload jsonb,
  document_entities_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  set constraints all deferred;

  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for search document replacement', target_export_id;
  end if;

  if jsonb_typeof(documents_payload) <> 'array' or jsonb_array_length(documents_payload) = 0 then
    raise exception 'documents_payload must be a non-empty JSON array';
  end if;

  if jsonb_typeof(document_entities_payload) <> 'array' then
    raise exception 'document_entities_payload must be a JSON array';
  end if;

  delete from bubble_mcp.search_documents
  where export_id = target_export_id;

  delete from bubble_mcp.search_document_entities
  where export_id = target_export_id;

  insert into bubble_mcp.search_documents (
    id,
    export_id,
    document_key,
    primary_entity_key,
    document_type,
    search_text,
    summary_text,
    rank_signals_json
  )
  select
    coalesce(nullif(doc ->> 'id', '')::uuid, extensions.gen_random_uuid()),
    target_export_id,
    btrim(doc ->> 'document_key'),
    nullif(btrim(coalesce(doc ->> 'primary_entity_key', '')), ''),
    btrim(doc ->> 'document_type'),
    btrim(doc ->> 'search_text'),
    nullif(btrim(coalesce(doc ->> 'summary_text', '')), ''),
    coalesce(doc -> 'rank_signals_json', '{}'::jsonb)
  from jsonb_array_elements(documents_payload) as doc;

  insert into bubble_mcp.search_document_entities (
    search_document_id,
    export_id,
    entity_key,
    association_role
  )
  select
    (assoc ->> 'search_document_id')::uuid,
    target_export_id,
    btrim(assoc ->> 'entity_key'),
    coalesce(nullif(btrim(coalesce(assoc ->> 'association_role', '')), ''), 'supporting')
  from jsonb_array_elements(document_entities_payload) as assoc;
end
$$;

grant execute on function bubble_mcp.replace_export_search_documents(uuid, jsonb, jsonb) to service_role;

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
    'search_document_entities',
    'search_documents',
    'bundle_cache',
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

do $$
begin
  if not exists (
    select 1
    from pg_enum e
    join pg_type t on t.oid = e.enumtypid
    join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = 'bubble_mcp'
      and t.typname = 'ingestion_phase'
      and e.enumlabel = 'search_document_generation'
  ) then
    alter type bubble_mcp.ingestion_phase
      add value 'search_document_generation' after 'verification';
  end if;
end
$$;

alter function bubble_mcp.is_query_eligible_export_readiness(
  bubble_mcp.export_readiness_status
)
set search_path = bubble_mcp, public;

alter function bubble_mcp.validate_export_readiness_transition(
  bubble_mcp.export_readiness_status,
  bubble_mcp.export_readiness_status
)
set search_path = bubble_mcp, public;

alter function bubble_mcp.validate_export_lifecycle_transition(
  bubble_mcp.export_lifecycle_status,
  bubble_mcp.export_lifecycle_status
)
set search_path = bubble_mcp, public;

alter function bubble_mcp.enforce_active_export_pointer()
set search_path = bubble_mcp, public;

alter function bubble_mcp.enforce_export_state_transition()
set search_path = bubble_mcp, public;

alter function bubble_mcp.enforce_export_state_for_active_pointer()
set search_path = bubble_mcp, public;

alter function bubble_mcp.is_default_safe_export_readiness(
  bubble_mcp.export_readiness_status
)
set search_path = bubble_mcp, public;

alter function bubble_mcp.validate_search_document_membership(
  uuid,
  uuid
)
set search_path = bubble_mcp, public;

alter function bubble_mcp.enforce_search_document_membership()
set search_path = bubble_mcp, public;

alter function bubble_mcp.validate_app_lifecycle_transition(
  bubble_mcp.app_lifecycle_status,
  bubble_mcp.app_lifecycle_status
)
set search_path = bubble_mcp, public;

alter function bubble_mcp.enforce_app_state_transition()
set search_path = bubble_mcp, public;

alter function bubble_mcp.block_direct_export_delete()
set search_path = bubble_mcp, public;

do $$
begin
  if not exists (
    select 1
    from pg_enum e
    join pg_type t on t.oid = e.enumtypid
    join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = 'bubble_mcp'
      and t.typname = 'ingestion_phase'
      and e.enumlabel = 'embedding_generation'
  ) then
    alter type bubble_mcp.ingestion_phase
      add value 'embedding_generation' after 'search_document_generation';
  end if;
end
$$;

create or replace function bubble_mcp.persist_search_document_embeddings(
  target_export_id uuid,
  embeddings_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  if jsonb_typeof(embeddings_payload) <> 'array' then
    raise exception 'embeddings_payload must be a JSON array';
  end if;
