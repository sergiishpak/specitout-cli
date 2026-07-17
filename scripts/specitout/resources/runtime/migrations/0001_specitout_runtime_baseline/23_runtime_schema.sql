  if found then
    select surface.*
    into v_surface
    from bubble_mcp.permission_surface_index surface
    where surface.export_id = v_scope.export_id
      and surface.entity_key = v_target_entity.entity_key
    limit 1;
  end if;

  if not found then
    with display_matches as (
      select
        entity.entity_key,
        entity.display_name,
        entity.summary,
        surface.privacy_role_count
      from bubble_mcp.permission_surface_index surface
      join bubble_mcp.entities entity
        on entity.export_id = surface.export_id
       and entity.entity_key = surface.entity_key
      where surface.export_id = v_scope.export_id
        and entity.entity_type = 'user_type'
        and lower(entity.display_name) = lower(v_lookup)
      order by entity.entity_key
    )
    select coalesce(
      jsonb_agg(
        jsonb_build_object(
          'entity_key', candidate.entity_key,
          'display_name', candidate.display_name,
          'summary', candidate.summary,
          'privacy_role_count', candidate.privacy_role_count
        )
        order by candidate.entity_key
      ),
      '[]'::jsonb
    )
    into v_candidates
    from display_matches candidate;

    if jsonb_array_length(v_candidates) > 1 then
      return jsonb_build_object(
        'status', 'ambiguous',
        'app_slug', v_scope.app_slug,
        'resolved_export_id', v_scope.export_id,
        'export_selection_reason', v_scope.export_selection_reason,
        'candidates', v_candidates
      );
    end if;

    if jsonb_array_length(v_candidates) = 0 then
      select exists(
        select 1
        from bubble_mcp.source_evidence evidence
        where evidence.export_id = v_scope.export_id
          and evidence.evidence_role = 'semantic_index'
          and evidence.metadata_json ->> 'index_name' = 'permission_surface_index'
      )
      into v_preserved_surface_artifact;

      if v_preserved_surface_artifact then
        select exists(
          select 1
          from bubble_mcp.entities entity
          where entity.export_id = v_scope.export_id
            and entity.entity_type = 'user_type'
            and (
              entity.entity_key = v_lookup
              or lower(entity.display_name) = lower(v_lookup)
            )
        )
        into v_lookup_matches_user_type;

        if v_lookup_matches_user_type then
          return jsonb_build_object(
            'status', 'unavailable',
            'app_slug', v_scope.app_slug,
            'resolved_export_id', v_scope.export_id,
            'export_selection_reason', v_scope.export_selection_reason,
            'user_type_lookup', v_lookup,
            'reason', 'permission_surface_index_not_backfilled'
          );
        end if;
      end if;

      return jsonb_build_object(
        'status', 'not_found',
        'app_slug', v_scope.app_slug,
        'resolved_export_id', v_scope.export_id,
        'export_selection_reason', v_scope.export_selection_reason,
        'user_type_lookup', v_lookup
      );
    end if;

    select entity.*
    into v_target_entity
    from bubble_mcp.permission_surface_index surface
    join bubble_mcp.entities entity
      on entity.export_id = surface.export_id
     and entity.entity_key = surface.entity_key
    where surface.export_id = v_scope.export_id
      and entity.entity_type = 'user_type'
      and lower(entity.display_name) = lower(v_lookup)
    order by entity.entity_key
    limit 1;

    select surface.*
    into v_surface
    from bubble_mcp.permission_surface_index surface
    where surface.export_id = v_scope.export_id
      and surface.entity_key = v_target_entity.entity_key
    limit 1;
  end if;

  select coalesce(
    jsonb_agg(link order by link ->> 'kind', coalesce(link ->> 'source_path', '')),
    '[]'::jsonb
  )
  into v_evidence_links
  from (
    select jsonb_build_object(
      'entity_key', v_target_entity.entity_key,
      'kind', 'entity_source_path',
      'source_path', v_target_entity.source_path
    ) as link
    where nullif(btrim(coalesce(v_target_entity.source_path, '')), '') is not null

    union

    select jsonb_strip_nulls(
      jsonb_build_object(
        'entity_key', v_target_entity.entity_key,
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
        'overlay_type', overlay.overlay_type,
        'source_path', overlay.source_path,
        'overlay_json', overlay.overlay_json
      )
      order by overlay.overlay_type, overlay.source_path
    ),
    '[]'::jsonb
  )
  into v_overlay_links
  from bubble_mcp.overlay_links overlay
  where overlay.export_id = v_scope.export_id
    and overlay.entity_key = v_target_entity.entity_key;

  with role_rows as (
    select
      role.value as role_json,
      ordinality
    from jsonb_array_elements(v_surface.roles_json) with ordinality as role(value, ordinality)
  ),
  expanded_roles as (
    select jsonb_strip_nulls(
      role.role_json
      || jsonb_build_object(
        'condition_entity',
        case
          when condition.entity_key is null then null
          else jsonb_build_object(
            'entity_key', condition.entity_key,
            'entity_type', condition.entity_type,
            'display_name', condition.display_name,
            'summary', condition.summary,
            'source_path', condition.source_path
          )
        end
      )
    ) as role_payload,
    role.ordinality
    from role_rows role
    left join bubble_mcp.entities condition
      on condition.export_id = v_scope.export_id
     and condition.entity_key = role.role_json ->> 'condition_entity_key'
  )
  select coalesce(
    jsonb_agg(role_payload order by ordinality),
    '[]'::jsonb
  )
  into v_roles
  from expanded_roles;

  return jsonb_build_object(
    'status', 'found',
    'app_slug', v_scope.app_slug,
    'resolved_export_id', v_scope.export_id,
    'export_selection_reason', v_scope.export_selection_reason,
    'entity', jsonb_build_object(
      'entity_key', v_target_entity.entity_key,
      'entity_type', v_target_entity.entity_type,
      'display_name', v_target_entity.display_name,
      'summary', v_target_entity.summary,
      'source_path', v_surface.source_path
    ),
    'privacy_role_count', v_surface.privacy_role_count,
    'roles', v_roles,
    'evidence_links', v_evidence_links,
    'overlay_links', v_overlay_links
  );
end
$$;

grant execute on function bubble_mcp.delete_export_scoped_rows(text, uuid, integer) to service_role;
grant execute on function bubble_mcp.get_public_api_workflows(text, uuid, boolean, boolean, text) to service_role;
grant execute on function bubble_mcp.get_permission_surface(text, text, uuid) to service_role;

drop function if exists bubble_mcp.resolve_retrieval_scope(text, uuid);

create or replace function bubble_mcp.resolve_retrieval_scope(
  p_app_slug text,
  p_export_id uuid default null,
  p_allow_archived_app boolean default false
)
returns table(
  app_id uuid,
  app_slug text,
  app_display_name text,
  export_id uuid,
  export_selection_reason text,
  semantic_available boolean
)
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_app bubble_mcp.apps%rowtype;
  v_export bubble_mcp.exports%rowtype;
  v_selection_reason text;
begin
  p_allow_archived_app := coalesce(p_allow_archived_app, false)
    or lower(coalesce(current_setting('bubble_mcp.allow_archived_app', true), 'false')) = 'true';

  if nullif(btrim(coalesce(p_app_slug, '')), '') is null then
    raise exception 'app_slug is required';
  end if;

  select *
  into v_app
  from bubble_mcp.apps
  where slug = lower(btrim(p_app_slug));

  if not found then
    raise exception 'app % does not exist', lower(btrim(p_app_slug));
  end if;

  if v_app.lifecycle_status = 'archived' and not p_allow_archived_app then
    raise exception 'app % is not queryable because lifecycle_status is %',
      v_app.slug,
      v_app.lifecycle_status;
  end if;

  if v_app.lifecycle_status not in ('active', 'archived') then
    raise exception 'app % is not queryable because lifecycle_status is %',
      v_app.slug,
      v_app.lifecycle_status;
  end if;

  if p_export_id is not null then
    select *
    into v_export
    from bubble_mcp.exports e
    where e.id = p_export_id
      and e.app_id = v_app.id;

    if not found then
      raise exception 'export % does not exist for app %', p_export_id, v_app.slug;
    end if;

    if v_export.lifecycle_status in ('archived', 'pending_delete', 'deleted') then
      raise exception 'export % is not queryable because lifecycle_status is %',
        v_export.id,
        v_export.lifecycle_status;
    end if;

    if not bubble_mcp.is_query_eligible_export_readiness(v_export.readiness_status) then
      raise exception 'export % is not query-eligible because readiness_status is %',
        v_export.id,
        v_export.readiness_status;
    end if;

    v_selection_reason := 'explicit_export';
  else
    if v_app.active_export_id is not null then
      select *
      into v_export
      from bubble_mcp.exports e
      where e.id = v_app.active_export_id
        and e.app_id = v_app.id
        and e.lifecycle_status not in ('archived', 'pending_delete', 'deleted')
        and bubble_mcp.is_query_eligible_export_readiness(e.readiness_status);

      if found then
        v_selection_reason := 'active_export';
      end if;
    end if;

    if v_selection_reason is null then
      select *
      into v_export
      from bubble_mcp.exports e
      where e.app_id = v_app.id
        and e.lifecycle_status not in ('archived', 'pending_delete', 'deleted')
        and bubble_mcp.is_query_eligible_export_readiness(e.readiness_status)
      order by
        case e.lifecycle_status
          when 'active' then 0
          when 'candidate' then 1
          when 'superseded' then 2
          else 3
        end,
        e.registered_at desc,
        e.id desc
      limit 1;

      if not found then
        raise exception 'no queryable knowledge version is available for app %', v_app.slug;
      end if;

      v_selection_reason := 'latest_queryable_fallback';
    end if;
  end if;

  return query
  select
    v_app.id,
    v_app.slug,
    v_app.display_name,
    v_export.id,
    v_selection_reason,
    exists(
      select 1
      from bubble_mcp.search_documents sd
      where sd.export_id = v_export.id
        and sd.embedding is not null
    )
    and v_export.readiness_status in ('ready', 'degraded');
end
$$;

grant execute on function bubble_mcp.resolve_retrieval_scope(text, uuid, boolean) to service_role;

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

  -- from bubble_mcp.resolve_retrieval_scope(p_app_slug, p_export_id, p_allow_archived_app);
  return bubble_mcp.search_entities(
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

  return bubble_mcp.get_entity(
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

  return bubble_mcp.get_neighbors(
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
