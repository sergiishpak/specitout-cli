end
$$;

grant execute on function bubble_mcp.enqueue_embedding_job(text, text, integer, integer, integer) to service_role;
grant execute on function bubble_mcp.claim_next_embedding_job(text, integer) to service_role;
grant execute on function bubble_mcp.finalize_embedding_job(uuid, uuid, text, text, integer, integer, integer, integer, integer, integer, jsonb, boolean) to service_role;

set statement_timeout = '0';

alter table bubble_mcp.search_documents
  add column if not exists searchable_in_root boolean generated always as (
    case
      when jsonb_typeof(rank_signals_json -> 'search_modes') = 'array' then (rank_signals_json -> 'search_modes') ? 'root'
      else true
    end
  ) stored,
  add column if not exists searchable_in_deep boolean generated always as (
    case
      when jsonb_typeof(rank_signals_json -> 'search_modes') = 'array' then (rank_signals_json -> 'search_modes') ? 'deep'
      else false
    end
  ) stored;

create index if not exists search_documents_root_export_idx
  on bubble_mcp.search_documents (export_id, id)
  where searchable_in_root;

create index if not exists search_documents_deep_export_idx
  on bubble_mcp.search_documents (export_id, id)
  where searchable_in_deep;

create index if not exists search_documents_root_search_text_trgm_idx
  on bubble_mcp.search_documents
  using gin (search_text extensions.gin_trgm_ops)
  where searchable_in_root;

create index if not exists search_documents_deep_search_text_trgm_idx
  on bubble_mcp.search_documents
  using gin (search_text extensions.gin_trgm_ops)
  where searchable_in_deep;

create or replace function bubble_mcp.search_entities_core(
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

  with scoped_documents as not materialized (
    select
      sd.id as search_document_id,
      sd.document_key,
      sd.document_type,
      sd.search_text,
      sd.summary_text,
      sd.embedding,
      sd.embedding_dimensions,
      sd.primary_entity_key
    from bubble_mcp.search_documents sd
    where sd.export_id = v_scope.export_id
      and case
        when v_search_mode = 'root' then sd.searchable_in_root
        else sd.searchable_in_deep
      end
  ),
  exact_entity_key_lane as (
    select sd.search_document_id
    from scoped_documents sd
    where v_query_text = sd.primary_entity_key
  ),
  exact_display_name_candidates as (
    select
      sd.search_document_id,
      count(*) over () as exact_display_name_match_count
    from scoped_documents sd
    join bubble_mcp.entities primary_entity
      on primary_entity.export_id = v_scope.export_id
     and primary_entity.entity_key = sd.primary_entity_key
    where lower(coalesce(primary_entity.display_name, '')) = lower(v_query_text)
  ),
  exact_display_name_lane as (
    select candidate.search_document_id
    from exact_display_name_candidates candidate
    where candidate.exact_display_name_match_count = 1
  ),
  ambiguous_display_name_lane as (
    select candidate.search_document_id
    from exact_display_name_candidates candidate
    where candidate.exact_display_name_match_count > 1
  ),
  supporting_entity_key_lane as (
    select distinct sd.search_document_id
    from scoped_documents sd
    join bubble_mcp.search_document_entities sde
      on sde.search_document_id = sd.search_document_id
     and sde.export_id = v_scope.export_id
    where sde.entity_key = v_query_text
      and coalesce(sd.primary_entity_key, '') <> v_query_text
  ),
  supporting_display_name_lane as (
    select distinct sd.search_document_id
    from scoped_documents sd
    join bubble_mcp.search_document_entities sde
      on sde.search_document_id = sd.search_document_id
     and sde.export_id = v_scope.export_id
    join bubble_mcp.entities matched_entity
      on matched_entity.export_id = v_scope.export_id
     and matched_entity.entity_key = sde.entity_key
    where lower(matched_entity.display_name) = lower(v_query_text)
      and not exists (
        select 1
        from bubble_mcp.entities primary_entity
        where primary_entity.export_id = v_scope.export_id
          and primary_entity.entity_key = sd.primary_entity_key
          and lower(primary_entity.display_name) = lower(v_query_text)
      )
  ),
  facet_lane as (
    select
      sd.search_document_id,
      count(*)::integer as facet_match_count
    from scoped_documents sd
    join bubble_mcp.search_document_entities sde
      on sde.search_document_id = sd.search_document_id
     and sde.export_id = v_scope.export_id
    join bubble_mcp.entity_facets ef
      on ef.export_id = v_scope.export_id
     and ef.entity_key = sde.entity_key
    where lower(ef.facet_value) = lower(v_query_text)
       or ef.facet_value ilike '%' || v_query_text || '%'
    group by sd.search_document_id
  ),
  lexical_ilike_lane as (
    select
      sd.search_document_id,
      greatest(
        0.90::double precision,
        extensions.similarity(sd.search_text, v_query_text),
        extensions.word_similarity(v_query_text, sd.search_text)
      ) as lexical_score
    from scoped_documents sd
    where sd.search_text ilike '%' || v_query_text || '%'
  ),
  lexical_ilike_summary as (
    select count(*)::integer as ilike_match_count
    from lexical_ilike_lane
  ),
  lexical_similarity_lane as (
    select
      sd.search_document_id,
      greatest(
        extensions.similarity(sd.search_text, v_query_text),
        extensions.word_similarity(v_query_text, sd.search_text)
      ) as lexical_score
    from scoped_documents sd
    where (
      select summary.ilike_match_count
      from lexical_ilike_summary summary
    ) < greatest(v_limit * 2, 10)
      and (
        extensions.similarity(sd.search_text, v_query_text) >= 0.10
        or extensions.word_similarity(v_query_text, sd.search_text) >= 0.20
      )
  ),
  lexical_lane as (
    select * from lexical_ilike_lane
    union
    select * from lexical_similarity_lane
  ),
  semantic_ranked as (
    select
      sd.search_document_id,
      1 - (sd.embedding OPERATOR(extensions.<=>) query_embedding) as semantic_score,
      row_number() over (
        order by
          sd.embedding OPERATOR(extensions.<=>) query_embedding asc,
          sd.document_key
      ) as semantic_rank
    from scoped_documents sd
    where v_scope.semantic_available
      and query_embedding is not null
      and sd.embedding is not null
      and sd.embedding_dimensions is not null
      and sd.embedding_dimensions = v_query_embedding_dimensions
  ),
  semantic_lane as (
    select
      ranked.search_document_id,
      ranked.semantic_score
    from semantic_ranked ranked
    where ranked.semantic_rank <= greatest(v_limit * 8, 20)
      and ranked.semantic_score >= 0.55
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
  candidate_documents as (
    select
      sd.id as search_document_id,
      sd.document_key,
      sd.document_type,
      sd.search_text,
      coalesce(sd.summary_text, primary_entity.summary) as summary_text,
      sd.primary_entity_key,
      primary_entity.display_name as primary_entity_display_name,
      primary_entity.entity_type as primary_entity_type
    from bubble_mcp.search_documents sd
    join candidate_ids candidate
      on candidate.search_document_id = sd.id
    left join bubble_mcp.entities primary_entity
      on primary_entity.export_id = sd.export_id
     and primary_entity.entity_key = sd.primary_entity_key
    where sd.export_id = v_scope.export_id
      and case
        when v_search_mode = 'root' then sd.searchable_in_root
        else sd.searchable_in_deep
      end
  ),
  candidate_associations as (
    select
      candidate.search_document_id,
      array_remove(array_agg(distinct sde.entity_key order by sde.entity_key), null) as associated_entity_keys
    from candidate_ids candidate
    left join bubble_mcp.search_document_entities sde
      on sde.search_document_id = candidate.search_document_id
     and sde.export_id = v_scope.export_id
    group by candidate.search_document_id
  ),
  scored as (
    select
      document.search_document_id,
      document.document_key,
      document.document_type,
      document.summary_text,
      document.primary_entity_key,
      document.primary_entity_display_name,
      document.primary_entity_type,
      coalesce(
        associations.associated_entity_keys,
        array_remove(array[document.primary_entity_key], null)
      ) as associated_entity_keys,
      exact_entity_key.search_document_id is not null as exact_entity_key_hit,
      exact_display_name.search_document_id is not null as exact_display_name_hit,
      ambiguous_display_name.search_document_id is not null as ambiguous_display_name_hit,
      supporting_entity_key.search_document_id is not null as supporting_entity_key_hit,
      supporting_display_name.search_document_id is not null as supporting_display_name_hit,
      coalesce(facet.facet_match_count, 0) as facet_match_count,
      lexical.lexical_score,
      semantic.semantic_score
    from candidate_documents document
    left join candidate_associations associations
      on associations.search_document_id = document.search_document_id
    left join exact_entity_key_lane exact_entity_key
      on exact_entity_key.search_document_id = document.search_document_id
    left join exact_display_name_lane exact_display_name
      on exact_display_name.search_document_id = document.search_document_id
    left join ambiguous_display_name_lane ambiguous_display_name
      on ambiguous_display_name.search_document_id = document.search_document_id
    left join supporting_entity_key_lane supporting_entity_key
      on supporting_entity_key.search_document_id = document.search_document_id
    left join supporting_display_name_lane supporting_display_name
      on supporting_display_name.search_document_id = document.search_document_id
    left join facet_lane facet
      on facet.search_document_id = document.search_document_id
    left join lexical_lane lexical
      on lexical.search_document_id = document.search_document_id
    left join semantic_lane semantic
      on semantic.search_document_id = document.search_document_id
  ),
  ranked as (
    select
      scored.*,
      case
        when scored.exact_entity_key_hit then 0
        when scored.exact_display_name_hit then 1
        when scored.supporting_entity_key_hit then 2
        when scored.supporting_display_name_hit then 3
        else 4
      end as ranking_bucket,
      case
        when scored.exact_entity_key_hit then 1000::numeric
        when scored.exact_display_name_hit then 900::numeric
        when scored.supporting_entity_key_hit then 800::numeric
        when scored.supporting_display_name_hit then 700::numeric
        else (
          greatest(
            coalesce(scored.semantic_score, 0)::numeric,
            coalesce(scored.lexical_score, 0)::numeric
          )
          + least(
            coalesce(scored.semantic_score, 0)::numeric,
            coalesce(scored.lexical_score, 0)::numeric
          ) * 0.25
          + least(scored.facet_match_count, 3)::numeric * 0.05
          + case
              when cardinality(coalesce(scored.associated_entity_keys, array[]::text[])) > 1
                or scored.document_type in ('endpoint_surface', 'permission_surface')
                then 0.03
              else 0
            end
        )
      end as ranking_score
    from scored
  ),
  final_rows as (
    select
      ranked.*,
      coalesce(evidence.evidence_links, '[]'::jsonb) as evidence_links,
      (
        (case when ranked.exact_entity_key_hit then jsonb_build_array(jsonb_build_object('type', 'exact_entity_key')) else '[]'::jsonb end)
        || (case when ranked.exact_display_name_hit then jsonb_build_array(jsonb_build_object('type', 'exact_display_name')) else '[]'::jsonb end)
        || (case when ranked.ambiguous_display_name_hit then jsonb_build_array(jsonb_build_object('type', 'ambiguous_display_name')) else '[]'::jsonb end)
        || (case when ranked.supporting_entity_key_hit then jsonb_build_array(jsonb_build_object('type', 'supporting_entity_key')) else '[]'::jsonb end)
        || (case when ranked.supporting_display_name_hit then jsonb_build_array(jsonb_build_object('type', 'supporting_display_name')) else '[]'::jsonb end)
        || (case when ranked.facet_match_count > 0 then jsonb_build_array(jsonb_build_object('type', 'facet_match', 'count', ranked.facet_match_count)) else '[]'::jsonb end)
        || (case when coalesce(ranked.lexical_score, 0) > 0 then jsonb_build_array(jsonb_build_object('type', 'lexical_match', 'score', round(ranked.lexical_score::numeric, 4))) else '[]'::jsonb end)
        || (case when coalesce(ranked.semantic_score, 0) > 0 then jsonb_build_array(jsonb_build_object('type', 'semantic_similarity', 'score', round(ranked.semantic_score::numeric, 4))) else '[]'::jsonb end)
        || jsonb_build_array(jsonb_build_object('type', 'mode_match', 'mode', v_search_mode))
        || (case
              when cardinality(coalesce(ranked.associated_entity_keys, array[]::text[])) > 1
                or ranked.document_type in ('endpoint_surface', 'permission_surface')
                then jsonb_build_array(jsonb_build_object('type', 'composite_surface'))
              else '[]'::jsonb
            end)
      ) as ranking_reasons
    from ranked
    left join lateral (
      with associated_entities as (
        select distinct
          entity.entity_key,
          entity.source_path,
          entity.semantic_json
        from bubble_mcp.entities entity
        where entity.export_id = v_scope.export_id
          and entity.entity_key = any(coalesce(ranked.associated_entity_keys, array[]::text[]))
      ),
      source_links as (
        select jsonb_build_object(
          'entity_key', associated.entity_key,
          'kind', 'entity_source_path',
          'source_path', associated.source_path
        ) as link
        from associated_entities associated
        where nullif(btrim(coalesce(associated.source_path, '')), '') is not null
      ),
      semantic_links as (
        select jsonb_strip_nulls(
          jsonb_build_object(
            'entity_key', associated.entity_key,
            'kind', coalesce(link.value ->> 'kind', 'semantic_evidence'),
            'source_path', nullif(btrim(coalesce(link.value ->> 'path', '')), '')
          )
        ) as link
        from associated_entities associated
        join lateral jsonb_array_elements(
          case
            when jsonb_typeof(associated.semantic_json -> 'evidence_links') = 'array' then associated.semantic_json -> 'evidence_links'
            else '[]'::jsonb
          end
        ) as link(value) on true
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
        where overlay.export_id = v_scope.export_id
          and overlay.entity_key = any(coalesce(ranked.associated_entity_keys, array[]::text[]))
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
