          traversal.entity_keys,
          traversal.edges,
          traversal.hop_count,
          array_to_string(traversal.entity_keys, ' > ') as path_key,
          array(
            select format(
              '%s|%s|%s|%s',
              edge.value ->> 'from_entity_key',
              edge.value ->> 'relation',
              edge.value ->> 'to_entity_key',
              edge.value ->> 'traversal_direction'
            )
            from jsonb_array_elements(traversal.edges) with ordinality as edge(value, ord)
            order by edge.ord
          ) as edge_signature,
          array(
            select coalesce(edge.value ->> 'evidence_path', '')
            from jsonb_array_elements(traversal.edges) with ordinality as edge(value, ord)
            order by edge.ord
          ) as evidence_signature
        from traversal
        where traversal.current_entity_key = v_to_entity_key
      ) path
      order by
        path.entity_keys,
        path.edge_signature,
        path.evidence_signature,
        path.hop_count,
        path.path_key
    ),
    bounded_paths as (
      select
        path.entity_keys,
        path.edges,
        path.hop_count,
        path.path_key
      from matched_paths path
      order by path.hop_count, path.path_key
      limit v_max_paths
    )
    select coalesce(
      jsonb_agg(
        jsonb_build_object(
          'hop_count', path.hop_count,
          'entities', (
            select jsonb_agg(
              jsonb_build_object(
                'entity_key', entity.entity_key,
                'entity_type', entity.entity_type,
                'display_name', entity.display_name,
                'source_path', entity.source_path,
                'summary', entity.summary
              )
              order by path_entity.ord
            )
            from unnest(path.entity_keys) with ordinality as path_entity(entity_key, ord)
            join bubble_mcp.entities entity
              on entity.export_id = v_scope.export_id
             and entity.entity_key = path_entity.entity_key
          ),
          'edges', path.edges
        )
        order by path.hop_count, path.path_key
      ),
      '[]'::jsonb
    )
    into v_paths
    from bounded_paths path;
  end if;

  v_status := case
    when jsonb_array_length(v_paths) > 0 then 'found'
    else 'no_path_within_bounds'
  end;

  return jsonb_build_object(
    'status', v_status,
    'app_slug', v_scope.app_slug,
    'resolved_export_id', v_scope.export_id,
    'export_selection_reason', v_scope.export_selection_reason,
    'from_anchor', v_from_entity,
    'to_anchor', v_to_entity,
    'direction', v_direction,
    'relation_filter', to_jsonb(v_relation_filter),
    'max_hops', v_max_hops,
    'max_paths', v_max_paths,
    'paths', v_paths,
    'path_count', jsonb_array_length(v_paths)
  );
end
$$;

grant execute on function bubble_mcp.get_neighbors(text, text, text, text, integer, uuid) to service_role;
grant execute on function bubble_mcp.find_paths(text, text, text, text, text, integer, integer, uuid) to service_role;

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
  query_embedding extensions.vector default null
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_scope record;
  v_query_text text := nullif(btrim(coalesce(p_query_text, '')), '');
  v_entity_key text := nullif(btrim(coalesce(p_entity_key, '')), '');
  v_search_mode text := lower(coalesce(nullif(btrim(p_search_mode), ''), 'root'));
  v_anchor_limit integer := greatest(1, least(coalesce(p_anchor_limit, 3), 10));
  v_max_hops integer := greatest(0, least(coalesce(p_max_hops, 1), 5));
  v_entity_limit integer := greatest(1, least(coalesce(p_entity_limit, 20), 50));
  v_edge_limit integer := greatest(1, least(coalesce(p_edge_limit, 30), 100));
  v_candidate_document_limit integer := least(greatest(v_anchor_limit * 8, v_anchor_limit + 1), 25);
  v_search_response jsonb := null;
  v_entity_response jsonb := null;
  v_resolved_anchors jsonb := '[]'::jsonb;
  v_selected_entities jsonb := '[]'::jsonb;
  v_related_edges jsonb := '[]'::jsonb;
  v_evidence_links jsonb := '[]'::jsonb;
  v_anchor_entity_keys text[] := array[]::text[];
  v_total_anchor_count integer := 0;
  v_total_entity_count integer := 0;
  v_total_edge_count integer := 0;
  v_semantic_available boolean := false;
  v_semantic_used boolean := false;
  v_degraded_mode boolean := false;
  v_hops_truncated boolean := false;
  v_notes text[] := array[]::text[];
  v_status text := 'found';
begin
  if (v_query_text is null and v_entity_key is null)
     or (v_query_text is not null and v_entity_key is not null) then
    raise exception 'requests must provide exactly one of query_text or entity_key';
  end if;

  if v_search_mode not in ('root', 'deep') then
    raise exception 'search_mode must be root or deep, found %', v_search_mode;
  end if;

  select *
  into v_scope
  from bubble_mcp.resolve_retrieval_scope(p_app_slug, p_export_id);

  v_semantic_available := coalesce(v_scope.semantic_available, false);

  if v_query_text is not null then
    v_search_response := bubble_mcp.search_entities(
      p_app_slug,
      v_query_text,
      v_search_mode,
      v_candidate_document_limit,
      v_scope.export_id,
      query_embedding
    );

    v_semantic_available := coalesce((v_search_response ->> 'semantic_available')::boolean, false);
    v_semantic_used := coalesce((v_search_response ->> 'semantic_used')::boolean, false);
    v_degraded_mode := not v_semantic_available;
    with candidate_anchors as (
      select
        anchor.result,
        anchor.ord,
        anchor.result ->> 'primary_entity_key' as entity_key
      from jsonb_array_elements(coalesce(v_search_response -> 'results', '[]'::jsonb))
        with ordinality as anchor(result, ord)
      where nullif(btrim(coalesce(anchor.result ->> 'primary_entity_key', '')), '') is not null
    ),
    deduplicated_anchors as (
      select
        anchor.result,
        anchor.ord,
        anchor.entity_key
      from (
        select
          anchor.*,
          row_number() over (
            partition by anchor.entity_key
            order by anchor.ord
          ) as anchor_rank
        from candidate_anchors anchor
      ) anchor
      where anchor.anchor_rank = 1
    ),
    counted_anchors as (
      select count(*)::integer as total_count
      from deduplicated_anchors
    ),
    limited_anchors as (
      select *
      from deduplicated_anchors
      order by ord
      limit least(v_anchor_limit, v_entity_limit)
    ),
    ranked_limited_anchors as (
      select
        anchor.result,
        anchor.ord,
        anchor.entity_key,
        row_number() over (order by anchor.ord) as anchor_rank
      from limited_anchors anchor
    )
    select
      coalesce(max(counted_anchors.total_count), 0),
      coalesce(
        jsonb_agg(
          jsonb_build_object(
            'anchor_kind', 'query_result',
            'anchor_rank', anchor.anchor_rank,
            'entity_key', anchor.entity_key,
            'display_name', anchor.result ->> 'primary_entity_display_name',
            'entity_type', anchor.result ->> 'primary_entity_type',
            'document_key', anchor.result ->> 'document_key',
            'document_type', anchor.result ->> 'document_type',
            'summary_text', anchor.result ->> 'summary_text',
            'ranking_score', anchor.result -> 'ranking_score',
            'ranking_reasons', coalesce(anchor.result -> 'ranking_reasons', '[]'::jsonb),
            'evidence_links', coalesce(anchor.result -> 'evidence_links', '[]'::jsonb)
          )
          order by anchor.ord
        ),
        '[]'::jsonb
      ),
      coalesce(
        array_agg(anchor.entity_key order by anchor.ord),
        array[]::text[]
      )
    into
      v_total_anchor_count,
      v_resolved_anchors,
      v_anchor_entity_keys
    from ranked_limited_anchors anchor
    cross join counted_anchors;

    if coalesce(array_length(v_anchor_entity_keys, 1), 0) = 0 then
      v_status := 'no_anchor_results';
      v_notes := array_append(v_notes, 'No anchors resolved from the scoped query.');
      if v_degraded_mode then
        v_notes := array_append(v_notes, 'Semantic anchors are unavailable for the resolved export, so bundle assembly stayed lexical-only.');
      end if;

      return jsonb_build_object(
        'status', v_status,
        'app_slug', v_scope.app_slug,
        'resolved_export_id', v_scope.export_id,
        'export_selection_reason', v_scope.export_selection_reason,
        'search_mode', v_search_mode,
        'semantic_available', v_semantic_available,
        'semantic_used', v_semantic_used,
        'degraded_mode', v_degraded_mode,
        'anchor_request', jsonb_build_object('query_text', v_query_text, 'entity_key', null),
        'resolved_anchors', v_resolved_anchors,
        'selected_entities', '[]'::jsonb,
        'related_edges', '[]'::jsonb,
        'evidence_links', '[]'::jsonb,
        'truncation', jsonb_build_object(
          'anchors_truncated', false,
          'entities_truncated', false,
          'edges_truncated', false,
          'hops_truncated', false
        ),
        'bundle_metadata', jsonb_build_object(
          'anchor_limit', v_anchor_limit,
          'max_hops', v_max_hops,
          'entity_limit', v_entity_limit,
          'edge_limit', v_edge_limit,
          'resolved_anchor_count', 0,
          'selected_entity_count', 0,
          'related_edge_count', 0,
          'notes', to_jsonb(v_notes)
        )
      );
    end if;

    v_degraded_mode := not v_semantic_available;

    if v_degraded_mode then
      v_notes := array_append(v_notes, 'Semantic anchors are unavailable for the resolved export, so bundle assembly stayed lexical-only.');
    end if;
  else
    v_entity_response := bubble_mcp.get_entity(
      p_app_slug,
      v_entity_key,
      v_scope.export_id
    );

    v_status := coalesce(v_entity_response ->> 'status', 'not_found');
    if v_status <> 'found' then
      return jsonb_build_object(
        'status', v_status,
        'app_slug', v_scope.app_slug,
        'resolved_export_id', v_scope.export_id,
        'export_selection_reason', v_scope.export_selection_reason,
        'search_mode', v_search_mode,
        'semantic_available', v_semantic_available,
        'semantic_used', false,
        'degraded_mode', false,
        'anchor_request', jsonb_build_object('query_text', null, 'entity_key', v_entity_key),
        'anchor_resolution', jsonb_strip_nulls(
          jsonb_build_object(
            'entity_lookup', v_entity_key,
            'candidates', v_entity_response -> 'candidates'
          )
        ),
        'resolved_anchors', '[]'::jsonb,
        'selected_entities', '[]'::jsonb,
        'related_edges', '[]'::jsonb,
        'evidence_links', '[]'::jsonb,
        'truncation', jsonb_build_object(
          'anchors_truncated', false,
          'entities_truncated', false,
          'edges_truncated', false,
          'hops_truncated', false
        ),
        'bundle_metadata', jsonb_build_object(
          'anchor_limit', v_anchor_limit,
          'max_hops', v_max_hops,
          'entity_limit', v_entity_limit,
          'edge_limit', v_edge_limit,
          'resolved_anchor_count', 0,
          'selected_entity_count', 0,
          'related_edge_count', 0,
          'notes', to_jsonb(array['Explicit entity anchor did not resolve to a single entity.'])
        )
      );
    end if;

    v_anchor_entity_keys := array[v_entity_response #>> '{entity,entity_key}'];
    v_total_anchor_count := 1;
    v_resolved_anchors := jsonb_build_array(
      jsonb_build_object(
        'anchor_kind', 'explicit_entity',
        'anchor_rank', 1,
        'entity_key', v_entity_response #>> '{entity,entity_key}',
        'display_name', v_entity_response #>> '{entity,display_name}',
        'entity_type', v_entity_response #>> '{entity,entity_type}',
        'summary_text', v_entity_response #>> '{entity,summary}',
        'resolution_reason',
          case
            when v_entity_key = v_entity_response #>> '{entity,entity_key}' then 'exact_entity_key'
            when lower(v_entity_key) = lower(coalesce(v_entity_response #>> '{entity,display_name}', '')) then 'exact_display_name'
            else 'resolved_entity'
          end,
        'ranking_reasons', jsonb_build_array(
          jsonb_build_object(
            'type',
            case
              when v_entity_key = v_entity_response #>> '{entity,entity_key}' then 'exact_entity_key'
              when lower(v_entity_key) = lower(coalesce(v_entity_response #>> '{entity,display_name}', '')) then 'exact_display_name'
              else 'resolved_entity'
            end
          )
        ),
        'evidence_links', coalesce(v_entity_response -> 'evidence_links', '[]'::jsonb)
      )
    );
  end if;

  with recursive anchor_seed as (
    select
      anchor.entity_key,
      anchor.anchor_rank
    from unnest(v_anchor_entity_keys) with ordinality as anchor(entity_key, anchor_rank)
  ),
  traversal as (
    select
      seed.entity_key as current_entity_key,
      seed.anchor_rank,
      0::integer as depth,
      array[seed.entity_key]::text[] as path_entity_keys
    from anchor_seed seed

    union all

    select
      next_step.next_entity_key,
      traversal.anchor_rank,
      traversal.depth + 1,
      traversal.path_entity_keys || next_step.next_entity_key
    from traversal
    join lateral (
      with candidate_edges as (
        select
          edge.to_entity_key as next_entity_key,
          edge.from_entity_key,
          edge.to_entity_key,
          edge.relation,
          edge.evidence_path
        from bubble_mcp.edges edge
        join bubble_mcp.entities target
          on target.export_id = edge.export_id
         and target.entity_key = edge.to_entity_key
        where edge.export_id = v_scope.export_id
          and edge.is_resolved
          and edge.from_entity_key = traversal.current_entity_key

        union all

        select
          edge.from_entity_key as next_entity_key,
          edge.from_entity_key,
          edge.to_entity_key,
          edge.relation,
          edge.evidence_path
        from bubble_mcp.edges edge
        join bubble_mcp.entities source
          on source.export_id = edge.export_id
         and source.entity_key = edge.from_entity_key
        where edge.export_id = v_scope.export_id
          and edge.is_resolved
          and edge.to_entity_key = traversal.current_entity_key
      )
      select
        candidate.next_entity_key
      from (
        select
          candidate.*,
          row_number() over (
            partition by
              candidate.from_entity_key,
              candidate.to_entity_key,
              candidate.relation,
              coalesce(candidate.evidence_path, '')
            order by candidate.next_entity_key
          ) as edge_rank
        from candidate_edges candidate
      ) candidate
      where candidate.edge_rank = 1
    ) as next_step on true
    where traversal.depth < v_max_hops
      and not next_step.next_entity_key = any(traversal.path_entity_keys)
  ),
  entity_candidates as (
    select
      traversal.current_entity_key as entity_key,
      min(traversal.depth) as min_depth,
      min(traversal.anchor_rank) filter (where traversal.depth = 0) as anchor_rank
    from traversal
    group by traversal.current_entity_key
  ),
  ordered_entities as (
    select
