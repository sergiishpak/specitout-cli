          'primary_entity_type', primary_entity_type,
          'matched_entity_keys', to_jsonb(coalesce(associated_entity_keys, array[]::text[])),
          'summary_text', summary_text,
          'ranking_score', round(ranking_score, 4),
          'ranking_reasons', ranking_reasons,
          'evidence_links', evidence_links
        )
        order by
          ranking_bucket,
          ranking_score desc,
          coalesce(primary_entity_display_name, ''),
          document_key
      ),
      '[]'::jsonb
    ),
    coalesce(bool_or(coalesce(semantic_score, 0) > 0), false)
  into
    v_results,
    v_semantic_used
  from limited_rows;

  return jsonb_build_object(
    'query_text', v_query_text,
    'search_mode', v_search_mode,
    'app_slug', v_scope.app_slug,
    'resolved_export_id', v_scope.export_id,
    'export_selection_reason', v_scope.export_selection_reason,
    'semantic_available', v_scope.semantic_available,
    'semantic_used', v_semantic_used,
    'results', v_results
  );
end
$$;

grant execute on function bubble_mcp.search_entities(text, text, text, integer, uuid, extensions.vector, boolean) to service_role;

alter function bubble_mcp.search_entities(text, text, text, integer, uuid, extensions.vector, boolean)
  set statement_timeout = '60s';

alter function bubble_mcp.search_entities_core(text, text, text, integer, uuid, extensions.vector)
  set statement_timeout = '60s';

set statement_timeout = '0';

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
  actual_target_table_name text := target_table_name;
begin
  if actual_target_table_name not in (
    'ingestion_runs',
    'source_evidence',
    'entities',
    'edges',
    'entity_facets',
    'search_document_associations',
    'search_documents',
    'bundle_cache',
    'overlay_links',
    'public_api_workflow_index',
    'permission_surface_index'
  ) then
    raise exception 'delete_export_scoped_rows does not support table %', target_table_name;
  end if;

  if actual_target_table_name = 'entities' then
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
    actual_target_table_name,
    batch_size,
    actual_target_table_name
  )
  using target_export_id;

  get diagnostics deleted_count = row_count;
  return deleted_count;
end
$$;

grant execute on function bubble_mcp.delete_export_scoped_rows(text, uuid, integer) to service_role;

drop function if exists bubble_mcp.replace_export_search_documents(uuid, jsonb, jsonb);

create or replace function bubble_mcp.replace_export_search_documents(
  target_export_id uuid,
  documents_payload jsonb,
  document_associations_payload jsonb
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
    raise exception 'export % does not exist for search document replacement', target_export_id;
  end if;

  if jsonb_typeof(documents_payload) <> 'array' or jsonb_array_length(documents_payload) = 0 then
    raise exception 'documents_payload must be a non-empty JSON array';
  end if;

  if jsonb_typeof(document_associations_payload) <> 'array' then
    raise exception 'document_associations_payload must be a JSON array';
  end if;

  delete from bubble_mcp.search_document_associations
  where export_id = target_export_id;

  delete from bubble_mcp.search_documents
  where export_id = target_export_id;

  insert into bubble_mcp.search_documents (
    id,
    export_id,
    document_key,
    primary_entity_key,
    document_type,
    lexical_text,
    semantic_text,
    summary_text,
    rank_signals_json
  )
  select
    coalesce(nullif(doc ->> 'id', '')::uuid, extensions.gen_random_uuid()),
    target_export_id,
    btrim(doc ->> 'document_key'),
    nullif(btrim(coalesce(doc ->> 'primary_entity_key', '')), ''),
    btrim(doc ->> 'document_type'),
    btrim(doc ->> 'lexical_text'),
    btrim(doc ->> 'semantic_text'),
    nullif(btrim(coalesce(doc ->> 'summary_text', '')), ''),
    coalesce(doc -> 'rank_signals_json', '{}'::jsonb)
  from jsonb_array_elements(documents_payload) as doc;

  insert into bubble_mcp.search_document_associations (
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
  from jsonb_array_elements(document_associations_payload) as assoc;
end
$$;

grant execute on function bubble_mcp.replace_export_search_documents(uuid, jsonb, jsonb) to service_role;

drop function if exists bubble_mcp.append_export_search_documents_batch(uuid, jsonb, jsonb);

create or replace function bubble_mcp.append_export_search_documents_batch(
  target_export_id uuid,
  documents_payload jsonb,
  document_associations_payload jsonb
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

  if jsonb_typeof(document_associations_payload) <> 'array' then
    raise exception 'document_associations_payload must be a JSON array';
  end if;

  if jsonb_array_length(documents_payload) = 0 and jsonb_array_length(document_associations_payload) = 0 then
    raise exception 'documents_payload and document_associations_payload cannot both be empty';
  end if;

  insert into bubble_mcp.search_documents (
    id,
    export_id,
    document_key,
    primary_entity_key,
    document_type,
    lexical_text,
    semantic_text,
    summary_text,
    rank_signals_json
  )
  select
    coalesce(nullif(doc ->> 'id', '')::uuid, extensions.gen_random_uuid()),
    target_export_id,
    btrim(doc ->> 'document_key'),
    nullif(btrim(coalesce(doc ->> 'primary_entity_key', '')), ''),
    btrim(doc ->> 'document_type'),
    btrim(doc ->> 'lexical_text'),
    btrim(doc ->> 'semantic_text'),
    nullif(btrim(coalesce(doc ->> 'summary_text', '')), ''),
    coalesce(doc -> 'rank_signals_json', '{}'::jsonb)
  from jsonb_array_elements(documents_payload) as doc
  on conflict (export_id, document_key) do update
  set
    id = excluded.id,
    primary_entity_key = excluded.primary_entity_key,
    document_type = excluded.document_type,
    lexical_text = excluded.lexical_text,
    semantic_text = excluded.semantic_text,
    summary_text = excluded.summary_text,
    rank_signals_json = excluded.rank_signals_json;

  insert into bubble_mcp.search_document_associations (
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
  from jsonb_array_elements(document_associations_payload) as assoc
  on conflict (search_document_id, entity_key) do update
  set association_role = excluded.association_role;
end
$$;

grant execute on function bubble_mcp.append_export_search_documents_batch(uuid, jsonb, jsonb) to service_role;
