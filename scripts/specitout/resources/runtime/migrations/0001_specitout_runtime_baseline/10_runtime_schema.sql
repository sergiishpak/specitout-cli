          edge.is_resolved,
          edge.edge_metadata_json,
          'inbound'::text as traversal_direction,
          edge.from_entity_key as next_entity_key
        from bubble_mcp.edges edge
        join bubble_mcp.entities source
          on source.export_id = edge.export_id
         and source.entity_key = edge.from_entity_key
        where v_direction in ('inbound', 'bidirectional')
          and edge.export_id = v_scope.export_id
          and edge.to_entity_key = traversal.current_entity_key
          and edge.is_resolved
          and (v_relation_filter is null or edge.relation = v_relation_filter)
      ) as next_step on true
      where traversal.hop_count < v_max_hops
        and not next_step.next_entity_key = any(traversal.entity_keys)
    ),
    matched_paths as (
      select
        traversal.entity_keys,
        traversal.edges,
        traversal.hop_count,
        array_to_string(traversal.entity_keys, ' > ') as path_key
      from traversal
      where traversal.current_entity_key = v_to_entity_key
      order by traversal.hop_count, path_key
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
    from matched_paths path;
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

grant execute on function bubble_mcp.find_paths(text, text, text, text, text, integer, integer, uuid) to service_role;

create or replace function bubble_mcp.get_neighbors(
  p_app_slug text,
  p_entity_key text,
  p_direction text default 'bidirectional',
  p_relation_filter text default null,
  p_limit integer default 10,
  p_export_id uuid default null
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_scope record;
  v_entity_key text := nullif(btrim(coalesce(p_entity_key, '')), '');
  v_direction text := lower(coalesce(nullif(btrim(p_direction), ''), 'bidirectional'));
  v_relation_filter text := nullif(btrim(coalesce(p_relation_filter, '')), '');
  v_limit integer := greatest(1, least(coalesce(p_limit, 10), 25));
  v_target_entity bubble_mcp.entities%rowtype;
  v_neighbors jsonb := '[]'::jsonb;
begin
  if v_entity_key is null then
    raise exception 'entity_key must not be empty';
  end if;

  if v_direction not in ('inbound', 'outbound', 'bidirectional') then
    raise exception 'direction must be inbound, outbound, or bidirectional, found %', v_direction;
  end if;

  select *
  into v_scope
  from bubble_mcp.resolve_retrieval_scope(p_app_slug, p_export_id);

  select *
  into v_target_entity
  from bubble_mcp.entities
  where export_id = v_scope.export_id
    and entity_key = v_entity_key;

  if not found then
    return jsonb_build_object(
      'status', 'not_found',
      'app_slug', v_scope.app_slug,
      'resolved_export_id', v_scope.export_id,
      'export_selection_reason', v_scope.export_selection_reason,
      'entity_key', v_entity_key,
      'direction', v_direction,
      'relation_filter', to_jsonb(v_relation_filter),
      'limit', v_limit,
      'neighbors', '[]'::jsonb,
      'neighbor_count', 0
    );
  end if;

  with selected_edges as (
    select
      'outbound'::text as direction,
      target.entity_key,
      target.entity_type,
      target.display_name,
      target.source_path,
      target.summary,
      edge.from_entity_key,
      edge.to_entity_key,
      edge.relation,
      edge.evidence_path,
      edge.is_resolved,
      edge.edge_metadata_json
    from bubble_mcp.edges edge
    join bubble_mcp.entities target
      on target.export_id = edge.export_id
     and target.entity_key = edge.to_entity_key
    where v_direction in ('outbound', 'bidirectional')
      and edge.export_id = v_scope.export_id
      and edge.from_entity_key = v_entity_key
      and (v_relation_filter is null or edge.relation = v_relation_filter)

    union all

    select
      'inbound'::text as direction,
      source.entity_key,
      source.entity_type,
      source.display_name,
      source.source_path,
      source.summary,
      edge.from_entity_key,
      edge.to_entity_key,
      edge.relation,
      edge.evidence_path,
      edge.is_resolved,
      edge.edge_metadata_json
    from bubble_mcp.edges edge
    join bubble_mcp.entities source
      on source.export_id = edge.export_id
     and source.entity_key = edge.from_entity_key
    where v_direction in ('inbound', 'bidirectional')
      and edge.export_id = v_scope.export_id
      and edge.to_entity_key = v_entity_key
      and (v_relation_filter is null or edge.relation = v_relation_filter)
  ),
  deduplicated_edges as (
    select *
    from (
      select
        edge.*,
        row_number() over (
          partition by edge.direction, edge.entity_key, edge.relation
          order by
            case when edge.is_resolved then 0 else 1 end,
            coalesce(edge.evidence_path, ''),
            edge.from_entity_key,
            edge.to_entity_key
        ) as edge_rank
      from selected_edges edge
    ) ranked_edges
    where edge_rank = 1
  ),
  bounded_edges as (
    select *
    from deduplicated_edges
    order by display_name, direction, relation, coalesce(evidence_path, ''), entity_key
    limit v_limit
  )
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'direction', edge.direction,
        'relation', edge.relation,
        'entity', jsonb_build_object(
          'entity_key', edge.entity_key,
          'entity_type', edge.entity_type,
          'display_name', edge.display_name,
          'source_path', edge.source_path,
          'summary', edge.summary
        ),
        'edge', jsonb_build_object(
          'from_entity_key', edge.from_entity_key,
          'to_entity_key', edge.to_entity_key,
          'relation', edge.relation,
          'evidence_path', edge.evidence_path,
          'is_resolved', edge.is_resolved,
          'edge_metadata_json', edge.edge_metadata_json
        )
      )
      order by edge.display_name, edge.direction, edge.relation, coalesce(edge.evidence_path, ''), edge.entity_key
    ),
    '[]'::jsonb
  )
  into v_neighbors
  from bounded_edges edge;

  return jsonb_build_object(
    'status', 'found',
    'app_slug', v_scope.app_slug,
    'resolved_export_id', v_scope.export_id,
    'export_selection_reason', v_scope.export_selection_reason,
    'entity', jsonb_build_object(
      'entity_key', v_target_entity.entity_key,
      'entity_type', v_target_entity.entity_type,
      'display_name', v_target_entity.display_name,
      'source_path', v_target_entity.source_path,
      'summary', v_target_entity.summary
    ),
    'direction', v_direction,
    'relation_filter', to_jsonb(v_relation_filter),
    'limit', v_limit,
    'neighbors', v_neighbors,
    'neighbor_count', jsonb_array_length(v_neighbors)
  );
end
$$;

create or replace function bubble_mcp.find_paths(
  p_app_slug text,
  p_from_anchor text,
  p_to_anchor text,
  p_direction text default 'bidirectional',
  p_relation_filter text default null,
  p_max_hops integer default 3,
  p_max_paths integer default 3,
  p_export_id uuid default null
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_scope record;
  v_direction text := lower(coalesce(nullif(btrim(p_direction), ''), 'bidirectional'));
  v_relation_filter text := nullif(btrim(coalesce(p_relation_filter, '')), '');
  v_max_hops integer := greatest(1, least(coalesce(p_max_hops, 3), 5));
  v_max_paths integer := greatest(1, least(coalesce(p_max_paths, 3), 10));
  v_from_resolution jsonb;
  v_to_resolution jsonb;
  v_from_entity jsonb;
  v_to_entity jsonb;
  v_from_entity_key text;
  v_to_entity_key text;
  v_paths jsonb := '[]'::jsonb;
  v_status text;
begin
  if nullif(btrim(coalesce(p_from_anchor, '')), '') is null then
    raise exception 'from_anchor must not be empty';
  end if;

  if nullif(btrim(coalesce(p_to_anchor, '')), '') is null then
    raise exception 'to_anchor must not be empty';
  end if;

  if v_direction not in ('inbound', 'outbound', 'bidirectional') then
    raise exception 'direction must be inbound, outbound, or bidirectional, found %', v_direction;
  end if;

  select *
  into v_scope
  from bubble_mcp.resolve_retrieval_scope(p_app_slug, p_export_id);

  v_from_resolution := bubble_mcp.resolve_entity_anchor(v_scope.export_id, p_from_anchor);
  v_to_resolution := bubble_mcp.resolve_entity_anchor(v_scope.export_id, p_to_anchor);

  if v_from_resolution ->> 'status' <> 'found' then
    return jsonb_build_object(
      'status', 'from_' || (v_from_resolution ->> 'status'),
      'app_slug', v_scope.app_slug,
      'resolved_export_id', v_scope.export_id,
      'export_selection_reason', v_scope.export_selection_reason,
      'direction', v_direction,
      'relation_filter', to_jsonb(v_relation_filter),
      'max_hops', v_max_hops,
      'max_paths', v_max_paths,
      'from_anchor_lookup', p_from_anchor,
      'from_anchor_resolution', v_from_resolution,
      'to_anchor_lookup', p_to_anchor
    );
  end if;

  if v_to_resolution ->> 'status' <> 'found' then
    return jsonb_build_object(
      'status', 'to_' || (v_to_resolution ->> 'status'),
      'app_slug', v_scope.app_slug,
      'resolved_export_id', v_scope.export_id,
      'export_selection_reason', v_scope.export_selection_reason,
      'direction', v_direction,
      'relation_filter', to_jsonb(v_relation_filter),
      'max_hops', v_max_hops,
      'max_paths', v_max_paths,
      'from_anchor_lookup', p_from_anchor,
      'to_anchor_lookup', p_to_anchor,
      'to_anchor_resolution', v_to_resolution
    );
  end if;

  v_from_entity := v_from_resolution -> 'entity';
  v_to_entity := v_to_resolution -> 'entity';
  v_from_entity_key := v_from_entity ->> 'entity_key';
  v_to_entity_key := v_to_entity ->> 'entity_key';

  if v_from_entity_key = v_to_entity_key then
    v_paths := jsonb_build_array(
      jsonb_build_object(
        'hop_count', 0,
        'entities', jsonb_build_array(v_from_entity),
        'edges', '[]'::jsonb
      )
    );
  else
    with recursive traversal as (
      select
        v_from_entity_key as current_entity_key,
        array[v_from_entity_key]::text[] as entity_keys,
        '[]'::jsonb as edges,
        0::integer as hop_count

      union all

      select
        next_step.next_entity_key,
        traversal.entity_keys || next_step.next_entity_key,
        traversal.edges || jsonb_build_array(
          jsonb_build_object(
            'from_entity_key', next_step.from_entity_key,
            'to_entity_key', next_step.to_entity_key,
            'relation', next_step.relation,
            'evidence_path', next_step.evidence_path,
            'is_resolved', next_step.is_resolved,
            'edge_metadata_json', next_step.edge_metadata_json,
            'traversal_direction', next_step.traversal_direction
          )
        ),
        traversal.hop_count + 1
      from traversal
      join lateral (
        select
          edge.from_entity_key,
          edge.to_entity_key,
          edge.relation,
          edge.evidence_path,
          edge.is_resolved,
          edge.edge_metadata_json,
          'outbound'::text as traversal_direction,
          edge.to_entity_key as next_entity_key
        from bubble_mcp.edges edge
        join bubble_mcp.entities target
          on target.export_id = edge.export_id
         and target.entity_key = edge.to_entity_key
        where v_direction in ('outbound', 'bidirectional')
          and edge.export_id = v_scope.export_id
          and edge.from_entity_key = traversal.current_entity_key
          and edge.is_resolved
          and (v_relation_filter is null or edge.relation = v_relation_filter)

        union all

        select
          edge.from_entity_key,
          edge.to_entity_key,
          edge.relation,
          edge.evidence_path,
          edge.is_resolved,
          edge.edge_metadata_json,
          'inbound'::text as traversal_direction,
          edge.from_entity_key as next_entity_key
        from bubble_mcp.edges edge
        join bubble_mcp.entities source
          on source.export_id = edge.export_id
         and source.entity_key = edge.from_entity_key
        where v_direction in ('inbound', 'bidirectional')
          and edge.export_id = v_scope.export_id
          and edge.to_entity_key = traversal.current_entity_key
          and edge.is_resolved
          and (v_relation_filter is null or edge.relation = v_relation_filter)
      ) as next_step on true
      where traversal.hop_count < v_max_hops
        and not next_step.next_entity_key = any(traversal.entity_keys)
    ),
    matched_paths as (
      select distinct on (path.entity_keys, path.edge_signature)
        path.entity_keys,
        path.edges,
        path.hop_count,
        path.path_key,
        path.evidence_signature
      from (
        select
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
