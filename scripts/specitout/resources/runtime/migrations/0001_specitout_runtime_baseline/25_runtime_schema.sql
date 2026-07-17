  )
  on conflict (export_id, entity_key) do update
  set
    entity_type = excluded.entity_type,
    display_name = excluded.display_name,
    source_id = excluded.source_id,
    source_path = excluded.source_path,
    parent_entity_key = excluded.parent_entity_key,
    is_synthetic = excluded.is_synthetic,
    is_virtual = excluded.is_virtual,
    summary = excluded.summary,
    structural_json = excluded.structural_json,
    semantic_json = excluded.semantic_json;
end
$$;

create or replace function bubble_mcp.append_export_edges_batch(
  target_export_id uuid,
  edges_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
begin
  set constraints all deferred;

  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for edges append', target_export_id;
  end if;

  if jsonb_typeof(edges_payload) <> 'array' then
    raise exception 'edges_payload must be a JSON array';
  end if;

  insert into bubble_mcp.edges (
    id,
    export_id,
    from_entity_key,
    relation,
    to_entity_key,
    is_resolved,
    evidence_path,
    edge_metadata_json
  )
  select
    item.id,
    target_export_id,
    btrim(item.from_entity_key),
    btrim(item.relation),
    btrim(item.to_entity_key),
    coalesce(item.is_resolved, false),
    nullif(btrim(coalesce(item.evidence_path, '')), ''),
    coalesce(item.edge_metadata_json, '{}'::jsonb)
  from jsonb_to_recordset(edges_payload) as item(
    id uuid,
    from_entity_key text,
    relation text,
    to_entity_key text,
    is_resolved boolean,
    evidence_path text,
    edge_metadata_json jsonb
  )
  on conflict (id) do update
  set
    export_id = excluded.export_id,
    from_entity_key = excluded.from_entity_key,
    relation = excluded.relation,
    to_entity_key = excluded.to_entity_key,
    is_resolved = excluded.is_resolved,
    evidence_path = excluded.evidence_path,
    edge_metadata_json = excluded.edge_metadata_json;
end
$$;

create or replace function bubble_mcp.append_export_entity_facets_batch(
  target_export_id uuid,
  entity_facets_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
begin
  set constraints all deferred;

  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for entity facet append', target_export_id;
  end if;

  if jsonb_typeof(entity_facets_payload) <> 'array' then
    raise exception 'entity_facets_payload must be a JSON array';
  end if;

  insert into bubble_mcp.entity_facets (
    export_id,
    entity_key,
    facet_type,
    facet_value
  )
  select
    target_export_id,
    btrim(item.entity_key),
    btrim(item.facet_type),
    btrim(item.facet_value)
  from jsonb_to_recordset(entity_facets_payload) as item(
    entity_key text,
    facet_type text,
    facet_value text
  )
  on conflict (export_id, entity_key, facet_type, facet_value) do nothing;
end
$$;

create or replace function bubble_mcp.append_export_overlay_links_batch(
  target_export_id uuid,
  overlay_links_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
begin
  set constraints all deferred;

  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for overlay link append', target_export_id;
  end if;

  if jsonb_typeof(overlay_links_payload) <> 'array' then
    raise exception 'overlay_links_payload must be a JSON array';
  end if;

  insert into bubble_mcp.overlay_links (
    export_id,
    overlay_type,
    entity_key,
    source_path,
    overlay_json
  )
  select
    target_export_id,
    btrim(item.overlay_type),
    btrim(item.entity_key),
    btrim(item.source_path),
    coalesce(item.overlay_json, '{}'::jsonb)
  from jsonb_to_recordset(overlay_links_payload) as item(
    overlay_type text,
    entity_key text,
    source_path text,
    overlay_json jsonb
  )
  on conflict (export_id, entity_key, overlay_type, source_path) do update
  set
    overlay_json = excluded.overlay_json;
end
$$;

create or replace function bubble_mcp.append_export_public_api_workflow_index_batch(
  target_export_id uuid,
  public_api_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
begin
  set constraints all deferred;

  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for public API workflow append', target_export_id;
  end if;

  if jsonb_typeof(public_api_payload) <> 'array' then
    raise exception 'public_api_payload must be a JSON array';
  end if;

  insert into bubble_mcp.public_api_workflow_index (
    export_id,
    entity_key,
    workflow_name,
    trigger_option,
    requires_auth,
    accepts_request_data,
    request_metadata_json
  )
  select
    target_export_id,
    btrim(item.entity_key),
    btrim(item.workflow_name),
    nullif(btrim(coalesce(item.trigger_option, '')), ''),
    coalesce(item.requires_auth, false),
    coalesce(item.accepts_request_data, false),
    coalesce(item.request_metadata_json, '{}'::jsonb)
  from jsonb_to_recordset(public_api_payload) as item(
    entity_key text,
    workflow_name text,
    trigger_option text,
    requires_auth boolean,
    accepts_request_data boolean,
    request_metadata_json jsonb
  )
  on conflict (export_id, entity_key, workflow_name) do update
  set
    trigger_option = excluded.trigger_option,
    requires_auth = excluded.requires_auth,
    accepts_request_data = excluded.accepts_request_data,
    request_metadata_json = excluded.request_metadata_json;
end
$$;

create or replace function bubble_mcp.append_export_permission_surface_index_batch(
  target_export_id uuid,
  permission_surface_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
begin
  set constraints all deferred;

  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for permission surface append', target_export_id;
  end if;

  if jsonb_typeof(permission_surface_payload) <> 'array' then
    raise exception 'permission_surface_payload must be a JSON array';
  end if;

  insert into bubble_mcp.permission_surface_index (
    export_id,
    entity_key,
    source_path,
    privacy_role_count,
    roles_json
  )
  select
    target_export_id,
    btrim(item.entity_key),
    btrim(item.source_path),
    greatest(coalesce(item.privacy_role_count, 0), 0),
    coalesce(item.roles_json, '[]'::jsonb)
  from jsonb_to_recordset(permission_surface_payload) as item(
    entity_key text,
    source_path text,
    privacy_role_count integer,
    roles_json jsonb
  )
  on conflict (export_id, entity_key) do update
  set
    source_path = excluded.source_path,
    privacy_role_count = excluded.privacy_role_count,
    roles_json = excluded.roles_json;
end
$$;

grant execute on function bubble_mcp.append_export_source_evidence_batch(uuid, jsonb) to service_role;
grant execute on function bubble_mcp.append_export_entities_batch(uuid, jsonb) to service_role;
grant execute on function bubble_mcp.append_export_edges_batch(uuid, jsonb) to service_role;
grant execute on function bubble_mcp.append_export_entity_facets_batch(uuid, jsonb) to service_role;
grant execute on function bubble_mcp.append_export_overlay_links_batch(uuid, jsonb) to service_role;
grant execute on function bubble_mcp.append_export_public_api_workflow_index_batch(uuid, jsonb) to service_role;
grant execute on function bubble_mcp.append_export_permission_surface_index_batch(uuid, jsonb) to service_role;

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
    'ingestion_runs',
    'source_evidence',
    'entities',
    'edges',
    'entity_facets',
    'search_document_entities',
    'search_documents',
    'bundle_cache',
    'overlay_links',
    'public_api_workflow_index',
    'permission_surface_index'
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

create or replace function bubble_mcp.append_export_search_documents_batch(
  target_export_id uuid,
  documents_payload jsonb,
  document_entities_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
begin
  set constraints all deferred;

  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for search document append', target_export_id;
  end if;

  if jsonb_typeof(documents_payload) <> 'array' then
    raise exception 'documents_payload must be a JSON array';
  end if;

  if jsonb_typeof(document_entities_payload) <> 'array' then
    raise exception 'document_entities_payload must be a JSON array';
  end if;

  if jsonb_array_length(documents_payload) = 0 and jsonb_array_length(document_entities_payload) = 0 then
    raise exception 'documents_payload and document_entities_payload cannot both be empty';
  end if;

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
  from jsonb_array_elements(documents_payload) as doc
  on conflict (export_id, document_key) do update
  set
    id = excluded.id,
    primary_entity_key = excluded.primary_entity_key,
    document_type = excluded.document_type,
    search_text = excluded.search_text,
