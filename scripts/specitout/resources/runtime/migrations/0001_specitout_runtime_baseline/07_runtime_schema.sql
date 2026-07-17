          and e.entity_key = any(coalesce(r.associated_entity_keys, array[]::text[]))
      ),
      source_links as (
        select jsonb_build_object(
          'entity_key', ae.entity_key,
          'kind', 'entity_source_path',
          'source_path', ae.source_path
        ) as link
        from associated_entities ae
        where nullif(btrim(coalesce(ae.source_path, '')), '') is not null
      ),
      semantic_links as (
        select jsonb_strip_nulls(
          jsonb_build_object(
            'entity_key', ae.entity_key,
            'kind', coalesce(link.value ->> 'kind', 'semantic_evidence'),
            'source_path', nullif(btrim(coalesce(link.value ->> 'path', '')), '')
          )
        ) as link
        from associated_entities ae
        join lateral jsonb_array_elements(
          case
            when jsonb_typeof(ae.semantic_json -> 'evidence_links') = 'array' then ae.semantic_json -> 'evidence_links'
            else '[]'::jsonb
          end
        ) as link(value) on true
        where nullif(btrim(coalesce(link.value ->> 'path', '')), '') is not null
      ),
      overlay_links as (
        select jsonb_build_object(
          'entity_key', ol.entity_key,
          'kind', 'overlay_link',
          'overlay_type', ol.overlay_type,
          'source_path', ol.source_path
        ) as link
        from bubble_mcp.overlay_links ol
        where ol.export_id = v_scope.export_id
          and ol.entity_key = any(coalesce(r.associated_entity_keys, array[]::text[]))
      ),
      combined as (
        select link from source_links
        union
        select link from semantic_links
        union
        select link from overlay_links
      )
      select coalesce(
        jsonb_agg(link order by link ->> 'entity_key', link ->> 'kind', coalesce(link ->> 'source_path', '')),
        '[]'::jsonb
      ) as evidence_links
      from combined
    ) as evidence on true
  ),
  limited_rows as (
    select *
    from final_rows
    order by
      ranking_bucket,
      ranking_score desc,
      coalesce(primary_entity_display_name, ''),
      document_key
    limit v_limit
  )
  select
    coalesce(
      jsonb_agg(
        jsonb_build_object(
          'document_key', document_key,
          'document_type', document_type,
          'primary_entity_key', primary_entity_key,
          'primary_entity_display_name', primary_entity_display_name,
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

create or replace function bubble_mcp.get_entity(
  p_app_slug text,
  p_entity_lookup text,
  p_export_id uuid default null
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_scope record;
  v_lookup text := nullif(btrim(coalesce(p_entity_lookup, '')), '');
  v_exact_entity bubble_mcp.entities%rowtype;
  v_target_entity bubble_mcp.entities%rowtype;
  v_display_match_count integer := 0;
  v_candidates jsonb := '[]'::jsonb;
  v_evidence_links jsonb := '[]'::jsonb;
  v_overlay_links jsonb := '[]'::jsonb;
  v_parent jsonb := null;
  v_outbound_neighbors jsonb := '[]'::jsonb;
  v_inbound_neighbors jsonb := '[]'::jsonb;
begin
  if v_lookup is null then
    raise exception 'entity_lookup must not be empty';
  end if;

  select *
  into v_scope
  from bubble_mcp.resolve_retrieval_scope(p_app_slug, p_export_id);

  select *
  into v_exact_entity
  from bubble_mcp.entities
  where export_id = v_scope.export_id
    and entity_key = v_lookup;

  if found then
    v_target_entity := v_exact_entity;
  else
    with display_matches as (
      select
        e.entity_key,
        e.entity_type,
        e.display_name,
        e.source_path,
        e.summary
      from bubble_mcp.entities e
      where e.export_id = v_scope.export_id
        and lower(e.display_name) = lower(v_lookup)
      order by
        e.entity_type,
        e.entity_key
    ),
    match_count as (
      select count(*)::integer as total_matches
      from display_matches
    )
    select
      mc.total_matches,
      coalesce(
        jsonb_agg(
          jsonb_build_object(
            'entity_key', dm.entity_key,
            'entity_type', dm.entity_type,
            'display_name', dm.display_name,
            'source_path', dm.source_path,
            'summary', dm.summary
          )
          order by dm.entity_type, dm.entity_key
        ),
        '[]'::jsonb
      )
    into
      v_display_match_count,
      v_candidates
    from match_count mc
    left join lateral (
      select *
      from display_matches
      limit 10
    ) as dm on true
    group by mc.total_matches;

    if v_display_match_count = 1 then
      select *
      into v_target_entity
      from bubble_mcp.entities
      where export_id = v_scope.export_id
        and lower(display_name) = lower(v_lookup)
      order by entity_key
      limit 1;
    elsif v_display_match_count > 1 then
      return jsonb_build_object(
        'status', 'ambiguous',
        'app_slug', v_scope.app_slug,
        'resolved_export_id', v_scope.export_id,
        'export_selection_reason', v_scope.export_selection_reason,
        'candidates', v_candidates
      );
    else
      return jsonb_build_object(
        'status', 'not_found',
        'app_slug', v_scope.app_slug,
        'resolved_export_id', v_scope.export_id,
        'export_selection_reason', v_scope.export_selection_reason,
        'entity_lookup', v_lookup
      );
    end if;
  end if;

  select coalesce(
    jsonb_agg(link order by link ->> 'kind', coalesce(link ->> 'source_path', '')),
    '[]'::jsonb
  )
  into v_evidence_links
  from (
    select jsonb_build_object(
      'kind', 'entity_source_path',
      'source_path', v_target_entity.source_path
    ) as link
    where nullif(btrim(coalesce(v_target_entity.source_path, '')), '') is not null

    union

    select jsonb_strip_nulls(
      jsonb_build_object(
        'kind', coalesce(link.value ->> 'kind', 'semantic_evidence'),
        'source_path', nullif(btrim(coalesce(link.value ->> 'path', '')), '')
      )
    ) as link
    from jsonb_array_elements(
      case
        when jsonb_typeof(v_target_entity.semantic_json -> 'evidence_links') = 'array' then v_target_entity.semantic_json -> 'evidence_links'
        else '[]'::jsonb
      end
    ) as link(value)
    where nullif(btrim(coalesce(link.value ->> 'path', '')), '') is not null
  ) evidence;

  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'overlay_type', ol.overlay_type,
        'source_path', ol.source_path,
        'overlay_json', ol.overlay_json
      )
      order by ol.overlay_type, ol.source_path
    ),
    '[]'::jsonb
  )
  into v_overlay_links
  from bubble_mcp.overlay_links ol
  where ol.export_id = v_scope.export_id
    and ol.entity_key = v_target_entity.entity_key;

  select case
    when parent.entity_key is null then null
    else jsonb_build_object(
      'entity_key', parent.entity_key,
      'entity_type', parent.entity_type,
      'display_name', parent.display_name,
      'summary', parent.summary
    )
  end
  into v_parent
  from bubble_mcp.entities parent
  where parent.export_id = v_scope.export_id
    and parent.entity_key = v_target_entity.parent_entity_key;

  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'relation', neighbor.relation,
        'evidence_path', neighbor.evidence_path,
        'entity', jsonb_build_object(
          'entity_key', neighbor.entity_key,
          'entity_type', neighbor.entity_type,
          'display_name', neighbor.display_name,
          'summary', neighbor.summary
        )
      )
      order by neighbor.display_name, neighbor.relation, coalesce(neighbor.evidence_path, '')
    ),
    '[]'::jsonb
  )
  into v_outbound_neighbors
  from (
    select distinct on (edge.to_entity_key, edge.relation)
      edge.relation,
      edge.evidence_path,
      target.entity_key,
      target.entity_type,
      target.display_name,
      target.summary
    from bubble_mcp.edges edge
    join bubble_mcp.entities target
      on target.export_id = edge.export_id
     and target.entity_key = edge.to_entity_key
    where edge.export_id = v_scope.export_id
      and edge.from_entity_key = v_target_entity.entity_key
    order by
      edge.to_entity_key,
      edge.relation,
      edge.evidence_path nulls last
    limit 10
  ) as neighbor;

  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'relation', neighbor.relation,
        'evidence_path', neighbor.evidence_path,
        'entity', jsonb_build_object(
          'entity_key', neighbor.entity_key,
          'entity_type', neighbor.entity_type,
          'display_name', neighbor.display_name,
          'summary', neighbor.summary
        )
      )
      order by neighbor.display_name, neighbor.relation, coalesce(neighbor.evidence_path, '')
    ),
    '[]'::jsonb
  )
  into v_inbound_neighbors
  from (
    select distinct on (edge.from_entity_key, edge.relation)
      edge.relation,
      edge.evidence_path,
      source.entity_key,
      source.entity_type,
      source.display_name,
      source.summary
    from bubble_mcp.edges edge
    join bubble_mcp.entities source
      on source.export_id = edge.export_id
     and source.entity_key = edge.from_entity_key
    where edge.export_id = v_scope.export_id
      and edge.to_entity_key = v_target_entity.entity_key
    order by
      edge.from_entity_key,
      edge.relation,
      edge.evidence_path nulls last
    limit 10
  ) as neighbor;

  return jsonb_build_object(
    'status', 'found',
    'app_slug', v_scope.app_slug,
    'resolved_export_id', v_scope.export_id,
    'export_selection_reason', v_scope.export_selection_reason,
    'entity', jsonb_build_object(
      'entity_key', v_target_entity.entity_key,
      'entity_type', v_target_entity.entity_type,
      'display_name', v_target_entity.display_name,
      'source_id', v_target_entity.source_id,
      'source_path', v_target_entity.source_path,
      'parent_entity_key', v_target_entity.parent_entity_key,
      'is_synthetic', v_target_entity.is_synthetic,
      'is_virtual', v_target_entity.is_virtual,
      'summary', v_target_entity.summary,
      'structural_json', v_target_entity.structural_json,
      'semantic_json', v_target_entity.semantic_json
    ),
    'evidence_links', v_evidence_links,
    'overlay_links', v_overlay_links,
    'parent', v_parent,
    'outbound_neighbors', v_outbound_neighbors,
    'inbound_neighbors', v_inbound_neighbors
  );
end
$$;

grant execute on function bubble_mcp.resolve_retrieval_scope(text, uuid) to service_role;
grant execute on function bubble_mcp.search_entities(text, text, text, integer, uuid, extensions.vector) to service_role;
grant execute on function bubble_mcp.get_entity(text, text, uuid) to service_role;

alter function bubble_mcp.replace_export_search_documents(uuid, jsonb, jsonb) set statement_timeout = '0';

create or replace function bubble_mcp.clear_export_search_documents(
  target_export_id uuid
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
begin
  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for search document clearing', target_export_id;
  end if;

  delete from bubble_mcp.search_document_entities
  where export_id = target_export_id;

  delete from bubble_mcp.search_documents
  where export_id = target_export_id;
end
$$;

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

  if jsonb_typeof(documents_payload) <> 'array' or jsonb_array_length(documents_payload) = 0 then
    raise exception 'documents_payload must be a non-empty JSON array';
  end if;

  if jsonb_typeof(document_entities_payload) <> 'array' then
    raise exception 'document_entities_payload must be a JSON array';
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
