  p_from_anchor text,
  p_to_anchor text,
  p_direction text default 'bidirectional',
  p_relation_filter text default null,
  p_max_hops integer default 3,
  p_max_paths integer default 3,
  p_export_id uuid default null,
  p_allow_archived_app boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  if p_allow_archived_app then
    perform set_config('bubble_mcp.allow_archived_app', 'true', true);
  end if;

  return bubble_mcp.find_paths(
    p_app_slug,
    p_from_anchor,
    p_to_anchor,
    p_direction,
    p_relation_filter,
    p_max_hops,
    p_max_paths,
    p_export_id
  );
end
$$;

grant execute on function bubble_mcp.find_paths(text, text, text, text, text, integer, integer, uuid, boolean) to service_role;

create or replace function bubble_mcp.build_context_bundle(
  p_app_slug text,
  p_export_id uuid default null,
  p_query_text text default null,
  p_entity_key text default null,
  p_search_mode text default 'root',
  p_anchor_limit integer default 3,
  p_max_hops integer default 1,
  p_entity_limit integer default 20,
  p_edge_limit integer default 30,
  query_embedding extensions.vector default null,
  p_allow_archived_app boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  if p_allow_archived_app then
    perform set_config('bubble_mcp.allow_archived_app', 'true', true);
  end if;

  return bubble_mcp.build_context_bundle(
    p_app_slug,
    p_export_id,
    p_query_text,
    p_entity_key,
    p_search_mode,
    p_anchor_limit,
    p_max_hops,
    p_entity_limit,
    p_edge_limit,
    query_embedding
  );
end
$$;

grant execute on function bubble_mcp.build_context_bundle(text, uuid, text, text, text, integer, integer, integer, integer, extensions.vector, boolean) to service_role;

create or replace function bubble_mcp.get_public_api_workflows(
  p_app_slug text,
  p_export_id uuid default null,
  p_requires_auth boolean default null,
  p_accepts_request_data boolean default null,
  p_workflow_name text default null,
  p_allow_archived_app boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  if p_allow_archived_app then
    perform set_config('bubble_mcp.allow_archived_app', 'true', true);
  end if;

  return bubble_mcp.get_public_api_workflows(
    p_app_slug,
    p_export_id,
    p_requires_auth,
    p_accepts_request_data,
    p_workflow_name
  );
end
$$;

grant execute on function bubble_mcp.get_public_api_workflows(text, uuid, boolean, boolean, text, boolean) to service_role;

alter function bubble_mcp.search_entities(text, text, text, integer, uuid, extensions.vector)
  rename to search_entities_core;

alter function bubble_mcp.get_entity(text, text, uuid)
  rename to get_entity_core;

alter function bubble_mcp.get_neighbors(text, text, text, text, integer, uuid)
  rename to get_neighbors_core;

alter function bubble_mcp.find_paths(text, text, text, text, text, integer, integer, uuid)
  rename to find_paths_core;

alter function bubble_mcp.build_context_bundle(text, uuid, text, text, text, integer, integer, integer, integer, extensions.vector)
  rename to build_context_bundle_core;

alter function bubble_mcp.get_public_api_workflows(text, uuid, boolean, boolean, text)
  rename to get_public_api_workflows_core;

revoke execute on function bubble_mcp.search_entities_core(text, text, text, integer, uuid, extensions.vector) from service_role;
revoke execute on function bubble_mcp.get_entity_core(text, text, uuid) from service_role;
revoke execute on function bubble_mcp.get_neighbors_core(text, text, text, text, integer, uuid) from service_role;
revoke execute on function bubble_mcp.find_paths_core(text, text, text, text, text, integer, integer, uuid) from service_role;
revoke execute on function bubble_mcp.build_context_bundle_core(text, uuid, text, text, text, integer, integer, integer, integer, extensions.vector) from service_role;
revoke execute on function bubble_mcp.get_public_api_workflows_core(text, uuid, boolean, boolean, text) from service_role;

create or replace function bubble_mcp.search_entities(
  p_app_slug text,
  p_query_text text,
  p_search_mode text default 'root',
  p_limit integer default 10,
  p_export_id uuid default null,
  query_embedding extensions.vector default null,
  p_allow_archived_app boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  if p_allow_archived_app then
    perform set_config('bubble_mcp.allow_archived_app', 'true', true);
  end if;

  return bubble_mcp.search_entities_core(
    p_app_slug,
    p_query_text,
    p_search_mode,
    p_limit,
    p_export_id,
    query_embedding
  );
end
$$;

grant execute on function bubble_mcp.search_entities(text, text, text, integer, uuid, extensions.vector, boolean) to service_role;

create or replace function bubble_mcp.get_entity(
  p_app_slug text,
  p_entity_lookup text,
  p_export_id uuid default null,
  p_allow_archived_app boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  if p_allow_archived_app then
    perform set_config('bubble_mcp.allow_archived_app', 'true', true);
  end if;

  return bubble_mcp.get_entity_core(
    p_app_slug,
    p_entity_lookup,
    p_export_id
  );
end
$$;

grant execute on function bubble_mcp.get_entity(text, text, uuid, boolean) to service_role;

create or replace function bubble_mcp.get_neighbors(
  p_app_slug text,
  p_entity_key text,
  p_direction text default 'bidirectional',
  p_relation_filter text default null,
  p_limit integer default 10,
  p_export_id uuid default null,
  p_allow_archived_app boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  if p_allow_archived_app then
    perform set_config('bubble_mcp.allow_archived_app', 'true', true);
  end if;

  return bubble_mcp.get_neighbors_core(
    p_app_slug,
    p_entity_key,
    p_direction,
    p_relation_filter,
    p_limit,
    p_export_id
  );
end
$$;

grant execute on function bubble_mcp.get_neighbors(text, text, text, text, integer, uuid, boolean) to service_role;

create or replace function bubble_mcp.find_paths(
  p_app_slug text,
  p_from_anchor text,
  p_to_anchor text,
  p_direction text default 'bidirectional',
  p_relation_filter text default null,
  p_max_hops integer default 3,
  p_max_paths integer default 3,
  p_export_id uuid default null,
  p_allow_archived_app boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  if p_allow_archived_app then
    perform set_config('bubble_mcp.allow_archived_app', 'true', true);
  end if;

  return bubble_mcp.find_paths_core(
    p_app_slug,
    p_from_anchor,
    p_to_anchor,
    p_direction,
    p_relation_filter,
    p_max_hops,
    p_max_paths,
    p_export_id
  );
end
$$;

grant execute on function bubble_mcp.find_paths(text, text, text, text, text, integer, integer, uuid, boolean) to service_role;

create or replace function bubble_mcp.build_context_bundle(
  p_app_slug text,
  p_export_id uuid default null,
  p_query_text text default null,
  p_entity_key text default null,
  p_search_mode text default 'root',
  p_anchor_limit integer default 3,
  p_max_hops integer default 1,
  p_entity_limit integer default 20,
  p_edge_limit integer default 30,
  query_embedding extensions.vector default null,
  p_allow_archived_app boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  if p_allow_archived_app then
    perform set_config('bubble_mcp.allow_archived_app', 'true', true);
  end if;

  return bubble_mcp.build_context_bundle_core(
    p_app_slug,
    p_export_id,
    p_query_text,
    p_entity_key,
    p_search_mode,
    p_anchor_limit,
    p_max_hops,
    p_entity_limit,
    p_edge_limit,
    query_embedding
  );
end
$$;

grant execute on function bubble_mcp.build_context_bundle(text, uuid, text, text, text, integer, integer, integer, integer, extensions.vector, boolean) to service_role;

create or replace function bubble_mcp.get_public_api_workflows(
  p_app_slug text,
  p_export_id uuid default null,
  p_requires_auth boolean default null,
  p_accepts_request_data boolean default null,
  p_workflow_name text default null,
  p_allow_archived_app boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
begin
  if p_allow_archived_app then
    perform set_config('bubble_mcp.allow_archived_app', 'true', true);
  end if;

  return bubble_mcp.get_public_api_workflows_core(
    p_app_slug,
    p_export_id,
    p_requires_auth,
    p_accepts_request_data,
    p_workflow_name
  );
end
$$;

grant execute on function bubble_mcp.get_public_api_workflows(text, uuid, boolean, boolean, text, boolean) to service_role;

alter function bubble_mcp.persist_search_document_embeddings(uuid, jsonb) set statement_timeout = '0';

create or replace function bubble_mcp.append_export_source_evidence_batch(
  target_export_id uuid,
  source_evidence_payload jsonb
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
    raise exception 'export % does not exist for source evidence append', target_export_id;
  end if;

  if jsonb_typeof(source_evidence_payload) <> 'array' then
    raise exception 'source_evidence_payload must be a JSON array';
  end if;

  insert into bubble_mcp.source_evidence (
    export_id,
    evidence_role,
    storage_bucket,
    storage_object_path,
    content_hash,
    source_path,
    metadata_json
  )
  select
    target_export_id,
    btrim(item.evidence_role),
    btrim(item.storage_bucket),
    btrim(item.storage_object_path),
    nullif(btrim(coalesce(item.content_hash, '')), ''),
    nullif(btrim(coalesce(item.source_path, '')), ''),
    coalesce(item.metadata_json, '{}'::jsonb)
  from jsonb_to_recordset(source_evidence_payload) as item(
    evidence_role text,
    storage_bucket text,
    storage_object_path text,
    content_hash text,
    source_path text,
    metadata_json jsonb
  )
  on conflict (export_id, evidence_role, storage_bucket, storage_object_path) do update
  set
    content_hash = excluded.content_hash,
    source_path = excluded.source_path,
    metadata_json = excluded.metadata_json,
    captured_at = now();
end
$$;

create or replace function bubble_mcp.append_export_entities_batch(
  target_export_id uuid,
  entities_payload jsonb
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
    raise exception 'export % does not exist for entities append', target_export_id;
  end if;

  if jsonb_typeof(entities_payload) <> 'array' then
    raise exception 'entities_payload must be a JSON array';
  end if;

  insert into bubble_mcp.entities (
    export_id,
    entity_key,
    entity_type,
    display_name,
    source_id,
    source_path,
    parent_entity_key,
    is_synthetic,
    is_virtual,
    summary,
    structural_json,
    semantic_json
  )
  select
    target_export_id,
    btrim(item.entity_key),
    btrim(item.entity_type),
    btrim(item.display_name),
    nullif(btrim(coalesce(item.source_id, '')), ''),
    btrim(item.source_path),
    nullif(btrim(coalesce(item.parent_entity_key, '')), ''),
    coalesce(item.is_synthetic, false),
    coalesce(item.is_virtual, false),
    nullif(btrim(coalesce(item.summary, '')), ''),
    coalesce(item.structural_json, '{}'::jsonb),
    coalesce(item.semantic_json, '{}'::jsonb)
  from jsonb_to_recordset(entities_payload) as item(
    entity_key text,
    entity_type text,
    display_name text,
    source_id text,
    source_path text,
    parent_entity_key text,
    is_synthetic boolean,
    is_virtual boolean,
    summary text,
    structural_json jsonb,
    semantic_json jsonb
