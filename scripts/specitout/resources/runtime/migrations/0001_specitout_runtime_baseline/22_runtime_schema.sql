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

create table if not exists bubble_mcp.permission_surface_index (
  id uuid primary key default extensions.gen_random_uuid(),
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  entity_key text not null,
  source_path text not null,
  privacy_role_count integer not null default 0,
  roles_json jsonb not null default '[]'::jsonb,
  constraint permission_surface_index_export_entity_fkey
    foreign key (export_id, entity_key)
    references bubble_mcp.entities(export_id, entity_key)
    on delete cascade,
  constraint permission_surface_index_unique_key unique (export_id, entity_key),
  constraint permission_surface_index_source_path_nonempty_check check (btrim(source_path) <> ''),
  constraint permission_surface_index_privacy_role_count_nonnegative_check check (privacy_role_count >= 0),
  constraint permission_surface_index_roles_json_array_check check (jsonb_typeof(roles_json) = 'array')
);

create index if not exists permission_surface_index_export_role_count_idx
  on bubble_mcp.permission_surface_index (export_id, privacy_role_count desc, entity_key);

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

create or replace function bubble_mcp.get_public_api_workflows(
  p_app_slug text,
  p_export_id uuid default null,
  p_requires_auth boolean default null,
  p_accepts_request_data boolean default null,
  p_workflow_name text default null
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_scope record;
  v_workflow_name text := nullif(btrim(coalesce(p_workflow_name, '')), '');
  v_workflows jsonb := '[]'::jsonb;
begin
  select *
  into v_scope
  from bubble_mcp.resolve_retrieval_scope(p_app_slug, p_export_id);

  with workflow_rows as (
    select
      idx.entity_key,
      entity.display_name,
      entity.entity_type,
      entity.summary,
      entity.source_path as entity_source_path,
      idx.workflow_name,
      idx.trigger_option,
      idx.requires_auth,
      idx.accepts_request_data,
      idx.request_metadata_json,
      coalesce(evidence.evidence_links, '[]'::jsonb) as evidence_links
    from bubble_mcp.public_api_workflow_index idx
    join bubble_mcp.entities entity
      on entity.export_id = idx.export_id
     and entity.entity_key = idx.entity_key
    left join lateral (
      with source_links as (
        select jsonb_build_object(
          'entity_key', entity.entity_key,
          'kind', 'entity_source_path',
          'source_path', entity.source_path
        ) as link
        where nullif(btrim(coalesce(entity.source_path, '')), '') is not null
      ),
      semantic_links as (
        select jsonb_strip_nulls(
          jsonb_build_object(
            'entity_key', entity.entity_key,
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
      overlay_links as (
        select jsonb_build_object(
          'entity_key', overlay.entity_key,
          'kind', 'overlay_link',
          'overlay_type', overlay.overlay_type,
          'source_path', overlay.source_path
        ) as link
        from bubble_mcp.overlay_links overlay
        where overlay.export_id = entity.export_id
          and overlay.entity_key = entity.entity_key
      ),
      combined as (
        select link from source_links
        union
        select link from semantic_links
        union
        select link from overlay_links
      )
      select coalesce(
        jsonb_agg(link order by link ->> 'kind', coalesce(link ->> 'source_path', '')),
        '[]'::jsonb
      ) as evidence_links
      from combined
    ) as evidence on true
    where idx.export_id = v_scope.export_id
      and (p_requires_auth is null or idx.requires_auth = p_requires_auth)
      and (p_accepts_request_data is null or idx.accepts_request_data = p_accepts_request_data)
      and (
        v_workflow_name is null
        or lower(idx.workflow_name) = lower(v_workflow_name)
      )
  )
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'entity_key', workflow.entity_key,
        'display_name', workflow.display_name,
        'entity_type', workflow.entity_type,
        'summary', workflow.summary,
        'workflow_name', workflow.workflow_name,
        'trigger_option', workflow.trigger_option,
        'requires_auth', workflow.requires_auth,
        'accepts_request_data', workflow.accepts_request_data,
        'exposure_status',
          case
            when workflow.requires_auth then 'semi_public'
            else 'public'
          end,
        'request_metadata', workflow.request_metadata_json,
        'evidence_links', workflow.evidence_links
      )
      order by workflow.workflow_name, workflow.entity_key
    ),
    '[]'::jsonb
  )
  into v_workflows
  from workflow_rows workflow;

  return jsonb_build_object(
    'app_slug', v_scope.app_slug,
    'resolved_export_id', v_scope.export_id,
    'export_selection_reason', v_scope.export_selection_reason,
    'filters', jsonb_strip_nulls(
      jsonb_build_object(
        'requires_auth', p_requires_auth,
        'accepts_request_data', p_accepts_request_data,
        'workflow_name', v_workflow_name
      )
    ),
    'workflows', v_workflows
  );
end
$$;

create or replace function bubble_mcp.get_permission_surface(
  p_app_slug text,
  p_user_type_lookup text,
  p_export_id uuid default null
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_scope record;
  v_lookup text := nullif(btrim(coalesce(p_user_type_lookup, '')), '');
  v_target_entity bubble_mcp.entities%rowtype;
  v_surface bubble_mcp.permission_surface_index%rowtype;
  v_candidates jsonb := '[]'::jsonb;
  v_roles jsonb := '[]'::jsonb;
  v_evidence_links jsonb := '[]'::jsonb;
  v_overlay_links jsonb := '[]'::jsonb;
  v_preserved_surface_artifact boolean := false;
  v_lookup_matches_user_type boolean := false;
begin
  if v_lookup is null then
    raise exception 'user_type_lookup must not be empty';
  end if;

  select *
  into v_scope
  from bubble_mcp.resolve_retrieval_scope(p_app_slug, p_export_id);

  select entity.*
  into v_target_entity
  from bubble_mcp.permission_surface_index surface
  join bubble_mcp.entities entity
    on entity.export_id = surface.export_id
   and entity.entity_key = surface.entity_key
  where surface.export_id = v_scope.export_id
    and entity.entity_type = 'user_type'
    and entity.entity_key = v_lookup
  limit 1;
