    from jsonb_array_elements(v_selected_entities) as entity(value)
  ),
  edge_candidates as (
    select
      edge.from_entity_key,
      edge.to_entity_key,
      edge.relation,
      edge.evidence_path,
      edge.is_resolved,
      edge.edge_metadata_json
    from bubble_mcp.edges edge
    join selected_entity_keys from_entity
      on from_entity.entity_key = edge.from_entity_key
    join selected_entity_keys to_entity
      on to_entity.entity_key = edge.to_entity_key
    where edge.export_id = v_scope.export_id
      and edge.is_resolved
  ),
  deduplicated_edges as (
    select
      edge.from_entity_key,
      edge.to_entity_key,
      edge.relation,
      edge.evidence_path,
      edge.is_resolved,
      edge.edge_metadata_json
    from (
      select
        edge.*,
        row_number() over (
          partition by
            edge.from_entity_key,
            edge.to_entity_key,
            edge.relation,
            coalesce(edge.evidence_path, '')
          order by edge.from_entity_key
        ) as edge_rank
      from edge_candidates edge
    ) edge
    where edge.edge_rank = 1
  ),
  counted_edges as (
    select count(*)::integer as total_count
    from deduplicated_edges
  ),
  ordered_edges as (
    select *
    from deduplicated_edges
    order by
      from_entity_key,
      relation,
      to_entity_key,
      coalesce(evidence_path, '')
    limit v_edge_limit
  )
  select
    coalesce(max(counted_edges.total_count), 0),
    coalesce(
      jsonb_agg(
        jsonb_build_object(
          'from_entity_key', edge.from_entity_key,
          'to_entity_key', edge.to_entity_key,
          'relation', edge.relation,
          'evidence_path', edge.evidence_path,
          'is_resolved', edge.is_resolved,
          'edge_metadata_json', edge.edge_metadata_json
        )
        order by
          edge.from_entity_key,
          edge.relation,
          edge.to_entity_key,
          coalesce(edge.evidence_path, '')
      ),
      '[]'::jsonb
    )
  into
    v_total_edge_count,
    v_related_edges
  from ordered_edges edge
  cross join counted_edges;

  with selected_entity_keys as (
    select entity.value ->> 'entity_key' as entity_key
    from jsonb_array_elements(v_selected_entities) as entity(value)
  ),
  frontier_entities as (
    select
      entity.value ->> 'entity_key' as entity_key,
      coalesce((entity.value ->> 'distance')::integer, 0) as distance
    from jsonb_array_elements(v_selected_entities) as entity(value)
  )
  select exists (
    select 1
    from frontier_entities frontier
    where frontier.distance = v_max_hops
      and exists (
        select 1
        from (
          select edge.to_entity_key as next_entity_key
          from bubble_mcp.edges edge
          where edge.export_id = v_scope.export_id
            and edge.is_resolved
            and edge.from_entity_key = frontier.entity_key

          union

          select edge.from_entity_key as next_entity_key
          from bubble_mcp.edges edge
          where edge.export_id = v_scope.export_id
            and edge.is_resolved
            and edge.to_entity_key = frontier.entity_key
        ) frontier_step
        where frontier_step.next_entity_key not in (
          select entity_key from selected_entity_keys
        )
      )
  )
  into v_hops_truncated;

  with selected_entity_keys as (
    select entity.value ->> 'entity_key' as entity_key
    from jsonb_array_elements(v_selected_entities) as entity(value)
  ),
  entity_evidence as (
    select jsonb_build_object(
      'entity_key', entity.entity_key,
      'kind', 'entity_source_path',
      'source_path', entity.source_path
    ) as link
    from bubble_mcp.entities entity
    join selected_entity_keys selected
      on selected.entity_key = entity.entity_key
    where entity.export_id = v_scope.export_id
      and nullif(btrim(coalesce(entity.source_path, '')), '') is not null

    union

    select jsonb_strip_nulls(
      jsonb_build_object(
        'entity_key', entity.entity_key,
        'kind', coalesce(link.value ->> 'kind', 'semantic_evidence'),
        'source_path', nullif(btrim(coalesce(link.value ->> 'path', '')), '')
      )
    ) as link
    from bubble_mcp.entities entity
    join selected_entity_keys selected
      on selected.entity_key = entity.entity_key
    join lateral jsonb_array_elements(
      case
        when jsonb_typeof(entity.semantic_json -> 'evidence_links') = 'array' then entity.semantic_json -> 'evidence_links'
        else '[]'::jsonb
      end
    ) as link(value) on true
    where entity.export_id = v_scope.export_id
      and nullif(btrim(coalesce(link.value ->> 'path', '')), '') is not null
  ),
  overlay_evidence as (
    select jsonb_build_object(
      'entity_key', overlay.entity_key,
      'kind', 'overlay_link',
      'overlay_type', overlay.overlay_type,
      'source_path', overlay.source_path
    ) as link
    from bubble_mcp.overlay_links overlay
    join selected_entity_keys selected
      on selected.entity_key = overlay.entity_key
    where overlay.export_id = v_scope.export_id
  ),
  edge_evidence as (
    select jsonb_build_object(
      'kind', 'edge_evidence_path',
      'source_path', edge.value ->> 'evidence_path'
    ) as link
    from jsonb_array_elements(v_related_edges) as edge(value)
    where nullif(btrim(coalesce(edge.value ->> 'evidence_path', '')), '') is not null
  ),
  combined as (
    select link from entity_evidence
    union
    select link from overlay_evidence
    union
    select link from edge_evidence
  )
  select coalesce(
    jsonb_agg(link order by coalesce(link ->> 'entity_key', ''), link ->> 'kind', coalesce(link ->> 'source_path', '')),
    '[]'::jsonb
  )
  into v_evidence_links
  from combined;

  if v_total_entity_count > jsonb_array_length(v_selected_entities) then
    v_notes := array_append(v_notes, 'Selected entities were truncated to the requested entity_limit.');
  end if;

  if v_total_edge_count > jsonb_array_length(v_related_edges) then
    v_notes := array_append(v_notes, 'Related edges were truncated to the requested edge_limit.');
  end if;

  if v_hops_truncated then
    v_notes := array_append(v_notes, 'Graph expansion stopped at max_hops before exhausting all reachable neighbors.');
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
    'anchor_request', jsonb_build_object(
      'query_text', v_query_text,
      'entity_key', v_entity_key
    ),
    'resolved_anchors', v_resolved_anchors,
    'selected_entities', v_selected_entities,
    'related_edges', v_related_edges,
    'evidence_links', v_evidence_links,
    'truncation', jsonb_build_object(
      'anchors_truncated', v_total_anchor_count > jsonb_array_length(v_resolved_anchors),
      'entities_truncated', v_total_entity_count > jsonb_array_length(v_selected_entities),
      'edges_truncated', v_total_edge_count > jsonb_array_length(v_related_edges),
      'hops_truncated', v_hops_truncated
    ),
    'bundle_metadata', jsonb_build_object(
      'anchor_limit', v_anchor_limit,
      'max_hops', v_max_hops,
      'entity_limit', v_entity_limit,
      'edge_limit', v_edge_limit,
      'resolved_anchor_count', jsonb_array_length(v_resolved_anchors),
      'selected_entity_count', jsonb_array_length(v_selected_entities),
      'related_edge_count', jsonb_array_length(v_related_edges),
      'notes', to_jsonb(v_notes)
    )
  );
end
$$;

grant execute on function bubble_mcp.build_context_bundle(text, uuid, text, text, text, integer, integer, integer, integer, extensions.vector) to service_role;

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
  v_explicit_entity_searchable boolean := false;
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
    v_degraded_mode := not v_semantic_available or not v_semantic_used;

    with candidate_anchors as (
      select
        anchor.result,
        anchor.ord,
        anchor.result ->> 'primary_entity_key' as entity_key,
        jsonb_build_object(
          'document_key', anchor.result ->> 'document_key',
          'document_type', anchor.result ->> 'document_type',
          'summary_text', anchor.result ->> 'summary_text',
          'ranking_score', anchor.result -> 'ranking_score',
          'ranking_reasons', coalesce(anchor.result -> 'ranking_reasons', '[]'::jsonb),
          'evidence_links', coalesce(anchor.result -> 'evidence_links', '[]'::jsonb)
        ) as document_entry
      from jsonb_array_elements(coalesce(v_search_response -> 'results', '[]'::jsonb))
        with ordinality as anchor(result, ord)
      where nullif(btrim(coalesce(anchor.result ->> 'primary_entity_key', '')), '') is not null
    ),
    grouped_anchors as (
      select
        anchor.entity_key,
        min(anchor.ord) as ord,
        jsonb_agg(anchor.result order by anchor.ord) -> 0 as best_result,
        jsonb_agg(anchor.document_entry order by anchor.ord) as matched_documents
      from candidate_anchors anchor
      group by anchor.entity_key
    ),
    counted_anchors as (
      select count(*)::integer as total_count
      from grouped_anchors
    ),
    limited_anchors as (
      select *
      from grouped_anchors anchor_group
      order by anchor_group.ord
      limit least(v_anchor_limit, v_entity_limit)
    ),
    ranked_limited_anchors as (
      select
        anchor_group.entity_key,
        anchor_group.ord,
        anchor_group.best_result,
        anchor_group.matched_documents,
        anchor_group.matched_documents -> 0 as primary_document,
        row_number() over (order by anchor_group.ord) as anchor_rank
      from limited_anchors anchor_group
    )
    select
      coalesce(max(counted_anchors.total_count), 0),
      coalesce(
        jsonb_agg(
          jsonb_build_object(
            'anchor_kind', 'query_result',
            'anchor_rank', anchor.anchor_rank,
            'entity_key', anchor.entity_key,
            'display_name', anchor.best_result ->> 'primary_entity_display_name',
            'entity_type', anchor.best_result ->> 'primary_entity_type',
            'document_key', anchor.primary_document ->> 'document_key',
            'document_type', anchor.primary_document ->> 'document_type',
            'summary_text', anchor.primary_document ->> 'summary_text',
            'ranking_score', anchor.primary_document -> 'ranking_score',
            'ranking_reasons', coalesce(anchor.primary_document -> 'ranking_reasons', '[]'::jsonb),
            'evidence_links', coalesce(anchor.primary_document -> 'evidence_links', '[]'::jsonb),
            'matched_documents', anchor.matched_documents
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
        v_notes := array_append(
          v_notes,
          case
            when not v_semantic_available then 'Semantic anchors are unavailable for the resolved export, so bundle assembly stayed lexical-only.'
            else 'Semantic ranking did not contribute to this bundle, so bundle assembly stayed lexical-only.'
          end
        );
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

    v_degraded_mode := not v_semantic_available or not v_semantic_used;

    if v_degraded_mode then
      v_notes := array_append(
        v_notes,
        case
          when not v_semantic_available then 'Semantic anchors are unavailable for the resolved export, so bundle assembly stayed lexical-only.'
          else 'Semantic ranking did not contribute to this bundle, so bundle assembly stayed lexical-only.'
        end
      );
