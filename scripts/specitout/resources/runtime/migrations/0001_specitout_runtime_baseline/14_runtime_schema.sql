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
          and (
            v_search_mode <> 'root'
            or coalesce(
              (target.semantic_json ->> 'searchable_in_root')::boolean,
              coalesce((target.semantic_json ->> 'searchable')::boolean, true)
            )
          )

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
          and (
            v_search_mode <> 'root'
            or coalesce(
              (source.semantic_json ->> 'searchable_in_root')::boolean,
              coalesce((source.semantic_json ->> 'searchable')::boolean, true)
            )
          )
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
      entity.entity_key,
      entity.entity_type,
      entity.display_name,
      entity.source_path,
      entity.parent_entity_key,
      entity.is_synthetic,
      entity.is_virtual,
      entity.summary,
      entity.semantic_json,
      candidate.min_depth,
      candidate.anchor_rank,
      case
        when candidate.anchor_rank is not null then 0
        when v_search_mode = 'root'
          and not coalesce(
            (entity.semantic_json ->> 'searchable_in_root')::boolean,
            coalesce((entity.semantic_json ->> 'searchable')::boolean, true)
          )
          then 1
        else 0
      end as deep_penalty
    from entity_candidates candidate
    join bubble_mcp.entities entity
      on entity.export_id = v_scope.export_id
     and entity.entity_key = candidate.entity_key
    where candidate.anchor_rank is not null
       or v_search_mode <> 'root'
       or coalesce(
         (entity.semantic_json ->> 'searchable_in_root')::boolean,
         coalesce((entity.semantic_json ->> 'searchable')::boolean, true)
       )
  ),
  counted_entities as (
    select count(*)::integer as total_count
    from ordered_entities
  ),
  limited_entities as (
    select *
    from ordered_entities
    order by
      case when anchor_rank is null then 1 else 0 end,
      anchor_rank,
      min_depth,
      deep_penalty,
      display_name,
      entity_key
    limit v_entity_limit
  )
  select
    coalesce(max(counted_entities.total_count), 0),
    coalesce(
      jsonb_agg(
        jsonb_build_object(
          'entity_key', entity.entity_key,
          'entity_type', entity.entity_type,
          'display_name', entity.display_name,
          'source_path', entity.source_path,
          'parent_entity_key', entity.parent_entity_key,
          'summary', entity.summary,
          'is_synthetic', entity.is_synthetic,
          'is_virtual', entity.is_virtual,
          'distance', entity.min_depth,
          'is_anchor', entity.anchor_rank is not null,
          'evidence_links', coalesce(evidence.evidence_links, '[]'::jsonb),
          'overlay_links', coalesce(overlays.overlay_links, '[]'::jsonb)
        )
        order by
          case when entity.anchor_rank is null then 1 else 0 end,
          entity.anchor_rank,
          entity.min_depth,
          entity.deep_penalty,
          entity.display_name,
          entity.entity_key
      ),
      '[]'::jsonb
    )
  into
    v_total_entity_count,
    v_selected_entities
  from limited_entities entity
  cross join counted_entities
  left join lateral (
    with source_links as (
      select jsonb_build_object(
        'kind', 'entity_source_path',
        'source_path', entity.source_path
      ) as link
      where nullif(btrim(coalesce(entity.source_path, '')), '') is not null
    ),
    semantic_links as (
      select jsonb_strip_nulls(
        jsonb_build_object(
          'kind', coalesce(link.value ->> 'kind', 'semantic_evidence'),
          'source_path', nullif(btrim(coalesce(link.value ->> 'path', '')), '')
        )
      ) as link
      from jsonb_array_elements(
        case
          when jsonb_typeof(entity.semantic_json -> 'evidence_links') = 'array' then entity.semantic_json -> 'evidence_links'
          else '[]'::jsonb
        end
      ) as link(value)
      where nullif(btrim(coalesce(link.value ->> 'path', '')), '') is not null
    ),
    combined as (
      select link from source_links
      union
      select link from semantic_links
    )
    select coalesce(
      jsonb_agg(link order by link ->> 'kind', coalesce(link ->> 'source_path', '')),
      '[]'::jsonb
    ) as evidence_links
    from combined
  ) as evidence on true
  left join lateral (
    select coalesce(
      jsonb_agg(
        jsonb_build_object(
          'overlay_type', overlay.overlay_type,
          'source_path', overlay.source_path
        )
        order by overlay.overlay_type, overlay.source_path
      ),
      '[]'::jsonb
    ) as overlay_links
    from bubble_mcp.overlay_links overlay
    where overlay.export_id = v_scope.export_id
      and overlay.entity_key = entity.entity_key
  ) as overlays on true;

  with selected_entity_keys as (
    select entity.value ->> 'entity_key' as entity_key
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
