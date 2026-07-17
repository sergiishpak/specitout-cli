
  update bubble_mcp.search_documents sd
  set
    embedding = (payload.item -> 'embedding')::text::extensions.vector,
    embedding_model = nullif(btrim(coalesce(payload.item ->> 'embedding_model', '')), ''),
    embedding_dimensions = coalesce(
      nullif(payload.item ->> 'embedding_dimensions', '')::integer,
      extensions.vector_dims((payload.item -> 'embedding')::text::extensions.vector)
    ),
    embedded_at = coalesce(
      nullif(payload.item ->> 'embedded_at', '')::timestamptz,
      now()
    )
  from (
    select jsonb_array_elements(embeddings_payload) as item
  ) as payload
  where sd.export_id = target_export_id
    and sd.id = (payload.item ->> 'search_document_id')::uuid;
end
$$;

grant execute on function bubble_mcp.persist_search_document_embeddings(uuid, jsonb) to service_role;

create or replace function bubble_mcp.resolve_retrieval_scope(
  p_app_slug text,
  p_export_id uuid default null
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

  if v_app.lifecycle_status <> 'active' then
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

create or replace function bubble_mcp.search_entities(
  p_app_slug text,
  p_query_text text,
  p_search_mode text default 'root',
  p_limit integer default 10,
  p_export_id uuid default null,
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
  v_search_mode text := lower(coalesce(nullif(btrim(p_search_mode), ''), 'root'));
  v_limit integer := greatest(1, least(coalesce(p_limit, 10), 25));
  v_query_embedding_dimensions integer;
  v_results jsonb := '[]'::jsonb;
  v_semantic_used boolean := false;
begin
  if v_query_text is null then
    raise exception 'query_text must not be empty';
  end if;

  if v_search_mode not in ('root', 'deep') then
    raise exception 'search_mode must be root or deep, found %', v_search_mode;
  end if;

  select *
  into v_scope
  from bubble_mcp.resolve_retrieval_scope(p_app_slug, p_export_id);

  if query_embedding is not null then
    v_query_embedding_dimensions := extensions.vector_dims(query_embedding);
  end if;

  with base_documents as (
    select
      sd.id as search_document_id,
      sd.document_key,
      sd.document_type,
      sd.search_text,
      coalesce(sd.summary_text, primary_entity.summary) as summary_text,
      sd.rank_signals_json,
      sd.embedding,
      sd.embedding_dimensions,
      sd.primary_entity_key,
      primary_entity.display_name as primary_entity_display_name,
      primary_entity.entity_type as primary_entity_type,
      array_remove(array_agg(distinct sde.entity_key order by sde.entity_key), null) as associated_entity_keys
    from bubble_mcp.search_documents sd
    left join bubble_mcp.entities primary_entity
      on primary_entity.export_id = sd.export_id
     and primary_entity.entity_key = sd.primary_entity_key
    left join bubble_mcp.search_document_entities sde
      on sde.search_document_id = sd.id
     and sde.export_id = sd.export_id
    where sd.export_id = v_scope.export_id
      and exists (
        select 1
        from jsonb_array_elements_text(
          case
            when jsonb_typeof(sd.rank_signals_json -> 'search_modes') = 'array' then sd.rank_signals_json -> 'search_modes'
            else '["root"]'::jsonb
          end
        ) as mode(mode_name)
        where mode.mode_name = v_search_mode
      )
    group by
      sd.id,
      sd.document_key,
      sd.document_type,
      sd.search_text,
      sd.summary_text,
      sd.rank_signals_json,
      sd.embedding,
      sd.embedding_dimensions,
      sd.primary_entity_key,
      primary_entity.display_name,
      primary_entity.entity_type,
      primary_entity.summary
  ),
  exact_entity_key_lane as (
    select bd.search_document_id
    from base_documents bd
    where v_query_text = bd.primary_entity_key
  ),
  exact_display_name_candidates as (
    select
      bd.search_document_id,
      count(*) over () as exact_display_name_match_count
    from base_documents bd
    where lower(coalesce(bd.primary_entity_display_name, '')) = lower(v_query_text)
  ),
  exact_display_name_lane as (
    select c.search_document_id
    from exact_display_name_candidates c
    where c.exact_display_name_match_count = 1
  ),
  ambiguous_display_name_lane as (
    select c.search_document_id
    from exact_display_name_candidates c
    where c.exact_display_name_match_count > 1
  ),
  supporting_entity_key_lane as (
    select bd.search_document_id
    from base_documents bd
    where v_query_text = any(coalesce(bd.associated_entity_keys, array[]::text[]))
      and coalesce(bd.primary_entity_key, '') <> v_query_text
  ),
  supporting_display_name_lane as (
    select bd.search_document_id
    from base_documents bd
    where lower(coalesce(bd.primary_entity_display_name, '')) <> lower(v_query_text)
      and exists (
        select 1
        from bubble_mcp.entities e
        where e.export_id = v_scope.export_id
          and e.entity_key = any(coalesce(bd.associated_entity_keys, array[]::text[]))
          and lower(e.display_name) = lower(v_query_text)
      )
  ),
  facet_lane as (
    select
      bd.search_document_id,
      count(*)::integer as facet_match_count
    from base_documents bd
    join bubble_mcp.entity_facets ef
      on ef.export_id = v_scope.export_id
     and ef.entity_key = any(coalesce(bd.associated_entity_keys, array[]::text[]))
    where lower(ef.facet_value) = lower(v_query_text)
       or ef.facet_value ilike '%' || v_query_text || '%'
    group by bd.search_document_id
  ),
  lexical_lane as (
    select
      bd.search_document_id,
      greatest(
        case when bd.search_text ilike '%' || v_query_text || '%' then 0.90 else 0.0 end,
        extensions.similarity(lower(bd.search_text), lower(v_query_text)),
        extensions.word_similarity(lower(v_query_text), lower(bd.search_text))
      ) as lexical_score
    from base_documents bd
    where bd.search_text ilike '%' || v_query_text || '%'
       or extensions.similarity(lower(bd.search_text), lower(v_query_text)) >= 0.10
       or extensions.word_similarity(lower(v_query_text), lower(bd.search_text)) >= 0.20
  ),
  semantic_ranked as (
    select
      bd.search_document_id,
      1 - (bd.embedding OPERATOR(extensions.<=>) query_embedding) as semantic_score,
      row_number() over (
        order by
          bd.embedding OPERATOR(extensions.<=>) query_embedding asc,
          bd.document_key
      ) as semantic_rank
    from base_documents bd
    where v_scope.semantic_available
      and query_embedding is not null
      and bd.embedding is not null
      and bd.embedding_dimensions is not null
      and bd.embedding_dimensions = v_query_embedding_dimensions
  ),
  semantic_lane as (
    select
      search_document_id,
      semantic_score
    from semantic_ranked
    where semantic_rank <= greatest(v_limit * 8, 20)
      and semantic_score >= 0.55
  ),
  candidate_ids as (
    select search_document_id from exact_entity_key_lane
    union
    select search_document_id from exact_display_name_lane
    union
    select search_document_id from ambiguous_display_name_lane
    union
    select search_document_id from supporting_entity_key_lane
    union
    select search_document_id from supporting_display_name_lane
    union
    select search_document_id from facet_lane
    union
    select search_document_id from lexical_lane
    union
    select search_document_id from semantic_lane
  ),
  scored as (
    select
      bd.*,
      exists(
        select 1
        from exact_entity_key_lane x
        where x.search_document_id = bd.search_document_id
      ) as exact_entity_key_hit,
      exists(
        select 1
        from exact_display_name_lane x
        where x.search_document_id = bd.search_document_id
      ) as exact_display_name_hit,
      exists(
        select 1
        from ambiguous_display_name_lane x
        where x.search_document_id = bd.search_document_id
      ) as ambiguous_display_name_hit,
      exists(
        select 1
        from supporting_entity_key_lane x
        where x.search_document_id = bd.search_document_id
      ) as supporting_entity_key_hit,
      exists(
        select 1
        from supporting_display_name_lane x
        where x.search_document_id = bd.search_document_id
      ) as supporting_display_name_hit,
      coalesce(
        (
          select x.facet_match_count
          from facet_lane x
          where x.search_document_id = bd.search_document_id
        ),
        0
      ) as facet_match_count,
      (
        select x.lexical_score
        from lexical_lane x
        where x.search_document_id = bd.search_document_id
      ) as lexical_score,
      (
        select x.semantic_score
        from semantic_lane x
        where x.search_document_id = bd.search_document_id
      ) as semantic_score
    from base_documents bd
    join candidate_ids c
      on c.search_document_id = bd.search_document_id
  ),
  ranked as (
    select
      s.*,
      case
        when s.exact_entity_key_hit then 0
        when s.exact_display_name_hit then 1
        when s.supporting_entity_key_hit then 2
        when s.supporting_display_name_hit then 3
        else 4
      end as ranking_bucket,
      case
        when s.exact_entity_key_hit then 1000::numeric
        when s.exact_display_name_hit then 900::numeric
        when s.supporting_entity_key_hit then 800::numeric
        when s.supporting_display_name_hit then 700::numeric
        else (
          greatest(
            coalesce(s.semantic_score, 0)::numeric,
            coalesce(s.lexical_score, 0)::numeric
          )
          + least(
            coalesce(s.semantic_score, 0)::numeric,
            coalesce(s.lexical_score, 0)::numeric
          ) * 0.25
          + least(s.facet_match_count, 3)::numeric * 0.05
          + case
              when cardinality(coalesce(s.associated_entity_keys, array[]::text[])) > 1
                or s.document_type in ('endpoint_surface', 'permission_surface')
                then 0.03
              else 0
            end
        )
      end as ranking_score
    from scored s
  ),
  final_rows as (
    select
      r.*,
      coalesce(evidence.evidence_links, '[]'::jsonb) as evidence_links,
      (
        (case when r.exact_entity_key_hit then jsonb_build_array(jsonb_build_object('type', 'exact_entity_key')) else '[]'::jsonb end)
        || (case when r.exact_display_name_hit then jsonb_build_array(jsonb_build_object('type', 'exact_display_name')) else '[]'::jsonb end)
        || (case when r.ambiguous_display_name_hit then jsonb_build_array(jsonb_build_object('type', 'ambiguous_display_name')) else '[]'::jsonb end)
        || (case when r.supporting_entity_key_hit then jsonb_build_array(jsonb_build_object('type', 'supporting_entity_key')) else '[]'::jsonb end)
        || (case when r.supporting_display_name_hit then jsonb_build_array(jsonb_build_object('type', 'supporting_display_name')) else '[]'::jsonb end)
        || (case when r.facet_match_count > 0 then jsonb_build_array(jsonb_build_object('type', 'facet_match', 'count', r.facet_match_count)) else '[]'::jsonb end)
        || (case when coalesce(r.lexical_score, 0) > 0 then jsonb_build_array(jsonb_build_object('type', 'lexical_match', 'score', round(r.lexical_score::numeric, 4))) else '[]'::jsonb end)
        || (case when coalesce(r.semantic_score, 0) > 0 then jsonb_build_array(jsonb_build_object('type', 'semantic_similarity', 'score', round(r.semantic_score::numeric, 4))) else '[]'::jsonb end)
        || jsonb_build_array(jsonb_build_object('type', 'mode_match', 'mode', v_search_mode))
        || (case
              when cardinality(coalesce(r.associated_entity_keys, array[]::text[])) > 1
                or r.document_type in ('endpoint_surface', 'permission_surface')
                then jsonb_build_array(jsonb_build_object('type', 'composite_surface'))
              else '[]'::jsonb
            end)
      ) as ranking_reasons
    from ranked r
    left join lateral (
      with associated_entities as (
        select distinct
          e.entity_key,
          e.source_path,
          e.semantic_json
        from bubble_mcp.entities e
        where e.export_id = v_scope.export_id
