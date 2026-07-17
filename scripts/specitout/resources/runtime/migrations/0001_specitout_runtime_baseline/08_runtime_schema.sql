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

grant execute on function bubble_mcp.clear_export_search_documents(uuid) to service_role;
grant execute on function bubble_mcp.append_export_search_documents_batch(uuid, jsonb, jsonb) to service_role;

create or replace function bubble_mcp.resolve_entity_anchor(
  p_export_id uuid,
  p_anchor text
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_anchor text := nullif(btrim(coalesce(p_anchor, '')), '');
  v_entity bubble_mcp.entities%rowtype;
  v_match_count integer := 0;
  v_candidates jsonb := '[]'::jsonb;
begin
  if v_anchor is null then
    raise exception 'anchor must not be empty';
  end if;

  select *
  into v_entity
  from bubble_mcp.entities
  where export_id = p_export_id
    and entity_key = v_anchor;

  if found then
    return jsonb_build_object(
      'status', 'found',
      'match_type', 'entity_key',
      'entity', jsonb_build_object(
        'entity_key', v_entity.entity_key,
        'entity_type', v_entity.entity_type,
        'display_name', v_entity.display_name,
        'source_path', v_entity.source_path,
        'summary', v_entity.summary
      )
    );
  end if;

  with display_matches as (
    select
      e.entity_key,
      e.entity_type,
      e.display_name,
      e.source_path,
      e.summary
    from bubble_mcp.entities e
    where e.export_id = p_export_id
      and lower(e.display_name) = lower(v_anchor)
    order by e.entity_type, e.entity_key
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
    v_match_count,
    v_candidates
  from match_count mc
  left join lateral (
    select *
    from display_matches
    limit 10
  ) as dm on true
  group by mc.total_matches;

  if v_match_count = 1 then
    select *
    into v_entity
    from bubble_mcp.entities
    where export_id = p_export_id
      and lower(display_name) = lower(v_anchor)
    order by entity_key
    limit 1;

    return jsonb_build_object(
      'status', 'found',
      'match_type', 'display_name',
      'entity', jsonb_build_object(
        'entity_key', v_entity.entity_key,
        'entity_type', v_entity.entity_type,
        'display_name', v_entity.display_name,
        'source_path', v_entity.source_path,
        'summary', v_entity.summary
      )
    );
  end if;

  if v_match_count > 1 then
    return jsonb_build_object(
      'status', 'ambiguous',
      'anchor', v_anchor,
      'candidates', v_candidates
    );
  end if;

  return jsonb_build_object(
    'status', 'not_found',
    'anchor', v_anchor
  );
end
$$;

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
  bounded_edges as (
    select *
    from selected_edges
    order by display_name, direction, relation, coalesce(evidence_path, '')
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
      order by edge.display_name, edge.direction, edge.relation, coalesce(edge.evidence_path, '')
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
        where v_direction in ('outbound', 'bidirectional')
          and edge.export_id = v_scope.export_id
          and edge.from_entity_key = traversal.current_entity_key
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
