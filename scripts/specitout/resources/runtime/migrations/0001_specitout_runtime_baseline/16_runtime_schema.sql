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
          join bubble_mcp.entities target
            on target.export_id = edge.export_id
           and target.entity_key = edge.to_entity_key
          where edge.export_id = v_scope.export_id
            and edge.is_resolved
            and edge.from_entity_key = frontier.entity_key
            and (
              v_search_mode <> 'root'
              or coalesce(
                (target.semantic_json ->> 'searchable_in_root')::boolean,
                coalesce((target.semantic_json ->> 'searchable')::boolean, true)
              )
            )

          union

          select edge.from_entity_key as next_entity_key
          from bubble_mcp.edges edge
          join bubble_mcp.entities source
            on source.export_id = edge.export_id
           and source.entity_key = edge.from_entity_key
          where edge.export_id = v_scope.export_id
            and edge.is_resolved
            and edge.to_entity_key = frontier.entity_key
            and (
              v_search_mode <> 'root'
              or coalesce(
                (source.semantic_json ->> 'searchable_in_root')::boolean,
                coalesce((source.semantic_json ->> 'searchable')::boolean, true)
              )
            )
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
