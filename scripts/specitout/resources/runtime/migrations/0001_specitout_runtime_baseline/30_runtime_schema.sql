          'primary_entity_type', primary_entity_type,
          'matched_entity_keys', to_jsonb(coalesce(associated_entity_keys, array[]::text[])),
          'summary_text', summary_text,
          'ranking_score', round(ranking_score, 4),
          'ranking_reasons', ranking_reasons,
          'evidence_links', evidence_links
        )
        order by
          ranking_bucket,
          ranking_score desc,
          coalesce(primary_entity_display_name, ''),
          document_key
      ),
      '[]'::jsonb
    ),
    coalesce(bool_or(coalesce(semantic_score, 0) > 0), false)
  into
    v_results,
    v_semantic_used
  from limited_rows;

  return jsonb_build_object(
    'query_text', v_query_text,
    'search_mode', v_search_mode,
    'app_slug', v_scope.app_slug,
    'resolved_export_id', v_scope.export_id,
    'export_selection_reason', v_scope.export_selection_reason,
    'semantic_available', v_scope.semantic_available,
    'semantic_used', v_semantic_used,
    'results', v_results
  );
end
$$;

alter function bubble_mcp.search_entities(text, text, text, integer, uuid, extensions.vector, boolean)
  set statement_timeout = '60s';

alter function bubble_mcp.search_entities_core(text, text, text, integer, uuid, extensions.vector)
  set statement_timeout = '60s';

alter function bubble_mcp.build_context_bundle(text, uuid, text, text, text, integer, integer, integer, integer, extensions.vector, boolean)
  set statement_timeout = '60s';

alter function bubble_mcp.build_context_bundle_core(text, uuid, text, text, text, integer, integer, integer, integer, extensions.vector)
  set statement_timeout = '60s';

set statement_timeout = '0';

alter table bubble_mcp.search_documents
  rename column search_text to lexical_text;

alter table bubble_mcp.search_documents
  add column if not exists semantic_text text;

update bubble_mcp.search_documents
set semantic_text = lexical_text
where semantic_text is null;

alter table bubble_mcp.search_documents
  alter column semantic_text set not null;

alter table bubble_mcp.search_documents
  rename constraint search_documents_search_text_nonempty_check to search_documents_lexical_text_nonempty_check;

alter table bubble_mcp.search_documents
  add constraint search_documents_semantic_text_nonempty_check check (btrim(semantic_text) <> '');

alter index bubble_mcp.search_documents_search_text_trgm_idx
  rename to search_documents_lexical_text_trgm_idx;

alter index bubble_mcp.search_documents_root_search_text_trgm_idx
  rename to search_documents_root_lexical_text_trgm_idx;

alter index bubble_mcp.search_documents_deep_search_text_trgm_idx
  rename to search_documents_deep_lexical_text_trgm_idx;

alter table bubble_mcp.search_document_entities
  rename to search_document_associations;

alter table bubble_mcp.search_document_associations
  rename constraint search_document_entities_document_fkey to search_document_associations_document_fkey;

alter table bubble_mcp.search_document_associations
  rename constraint search_document_entities_entity_fkey to search_document_associations_entity_fkey;

alter table bubble_mcp.search_document_associations
  rename constraint search_document_entities_association_role_nonempty_check to search_document_associations_association_role_nonempty_check;

alter index bubble_mcp.search_document_entities_pkey
  rename to search_document_associations_pkey;

alter index bubble_mcp.search_document_entities_export_entity_idx
  rename to search_document_associations_export_entity_idx;

alter trigger search_document_entities_membership_guard
  on bubble_mcp.search_document_associations
  rename to search_document_associations_membership_guard;

create or replace function bubble_mcp.validate_search_document_membership(
  target_document_id uuid,
  target_export_id uuid
)
returns void
language plpgsql
set search_path = bubble_mcp, public
as $$
declare
  doc_primary_entity_key text;
  linked_entity_count bigint;
begin
  if target_document_id is null or target_export_id is null then
    return;
  end if;

  select
    sd.primary_entity_key,
    count(sda.entity_key)
  into
    doc_primary_entity_key,
    linked_entity_count
  from bubble_mcp.search_documents sd
  left join bubble_mcp.search_document_associations sda
    on sda.search_document_id = sd.id
   and sda.export_id = sd.export_id
  where sd.id = target_document_id
    and sd.export_id = target_export_id
  group by sd.primary_entity_key;

  if not found then
    return;
  end if;

  if linked_entity_count = 0 then
    raise exception 'search document % must reference at least one entity', target_document_id;
  end if;

  if doc_primary_entity_key is not null
     and not exists (
       select 1
       from bubble_mcp.search_document_associations sda
       where sda.search_document_id = target_document_id
         and sda.export_id = target_export_id
         and sda.entity_key = doc_primary_entity_key
     ) then
    raise exception 'search document % primary_entity_key must also appear in search_document_associations', target_document_id;
  end if;
end
$$;

create or replace function bubble_mcp.enforce_search_document_membership()
returns trigger
language plpgsql
set search_path = bubble_mcp, public
as $$
declare
  new_document_id uuid;
  new_export_id uuid;
  old_document_id uuid;
  old_export_id uuid;
begin
  if tg_table_name = 'search_documents' then
    perform bubble_mcp.validate_search_document_membership(
      coalesce(new.id, old.id),
      coalesce(new.export_id, old.export_id)
    );
  else
    if tg_op <> 'DELETE' then
      new_document_id := new.search_document_id;
      new_export_id := new.export_id;
      perform bubble_mcp.validate_search_document_membership(new_document_id, new_export_id);
    end if;

    if tg_op <> 'INSERT' then
      old_document_id := old.search_document_id;
      old_export_id := old.export_id;

      if old_document_id is distinct from new_document_id
         or old_export_id is distinct from new_export_id then
        perform bubble_mcp.validate_search_document_membership(old_document_id, old_export_id);
      end if;
    end if;
  end if;

  return coalesce(new, old);
end
$$;

drop trigger if exists search_documents_membership_guard on bubble_mcp.search_documents;
create constraint trigger search_documents_membership_guard
after insert or update of primary_entity_key, export_id
on bubble_mcp.search_documents
deferrable initially deferred
for each row
execute function bubble_mcp.enforce_search_document_membership();

drop trigger if exists search_document_entities_membership_guard on bubble_mcp.search_document_associations;
drop trigger if exists search_document_associations_membership_guard on bubble_mcp.search_document_associations;
create constraint trigger search_document_associations_membership_guard
after insert or update or delete
on bubble_mcp.search_document_associations
deferrable initially deferred
for each row
execute function bubble_mcp.enforce_search_document_membership();

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
  actual_target_table_name text := case
    when target_table_name = 'search_document_entities' then 'search_document_associations'
    else target_table_name
  end;
begin
  if actual_target_table_name not in (
    'ingestion_runs',
    'source_evidence',
    'entities',
    'edges',
    'entity_facets',
    'search_document_associations',
    'search_documents',
    'bundle_cache',
    'overlay_links',
    'public_api_workflow_index',
    'permission_surface_index'
  ) then
    raise exception 'delete_export_scoped_rows does not support table %', target_table_name;
  end if;

  if actual_target_table_name = 'entities' then
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
    actual_target_table_name,
    batch_size,
    actual_target_table_name
  )
  using target_export_id;

  get diagnostics deleted_count = row_count;
  return deleted_count;
end
$$;

grant execute on function bubble_mcp.delete_export_scoped_rows(text, uuid, integer) to service_role;

create or replace function bubble_mcp.replace_export_search_documents(
  target_export_id uuid,
  documents_payload jsonb,
  document_entities_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
begin
  set constraints all deferred;

  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for search document replacement', target_export_id;
  end if;

  if jsonb_typeof(documents_payload) <> 'array' or jsonb_array_length(documents_payload) = 0 then
    raise exception 'documents_payload must be a non-empty JSON array';
  end if;

  if jsonb_typeof(document_entities_payload) <> 'array' then
    raise exception 'document_entities_payload must be a JSON array';
  end if;

  delete from bubble_mcp.search_document_associations
  where export_id = target_export_id;

  delete from bubble_mcp.search_documents
  where export_id = target_export_id;

  insert into bubble_mcp.search_documents (
    id,
    export_id,
    document_key,
    primary_entity_key,
    document_type,
    lexical_text,
    semantic_text,
    summary_text,
    rank_signals_json
  )
  select
    coalesce(nullif(doc ->> 'id', '')::uuid, extensions.gen_random_uuid()),
    target_export_id,
    btrim(doc ->> 'document_key'),
    nullif(btrim(coalesce(doc ->> 'primary_entity_key', '')), ''),
    btrim(doc ->> 'document_type'),
    btrim(coalesce(doc ->> 'lexical_text', doc ->> 'search_text')),
    btrim(coalesce(nullif(doc ->> 'semantic_text', ''), doc ->> 'lexical_text', doc ->> 'search_text')),
    nullif(btrim(coalesce(doc ->> 'summary_text', '')), ''),
    coalesce(doc -> 'rank_signals_json', '{}'::jsonb)
  from jsonb_array_elements(documents_payload) as doc;

  insert into bubble_mcp.search_document_associations (
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

grant execute on function bubble_mcp.replace_export_search_documents(uuid, jsonb, jsonb) to service_role;

create or replace function bubble_mcp.clear_export_search_documents(
  target_export_id uuid
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
begin
  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for search document clearing', target_export_id;
  end if;

  delete from bubble_mcp.search_document_associations
  where export_id = target_export_id;

  delete from bubble_mcp.search_documents
  where export_id = target_export_id;
end
$$;

grant execute on function bubble_mcp.clear_export_search_documents(uuid) to service_role;

create or replace function bubble_mcp.append_export_search_documents_batch(
  target_export_id uuid,
  documents_payload jsonb,
  document_entities_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
set statement_timeout = '0'
as $$
begin
  set constraints all deferred;

  if not exists (
    select 1
    from bubble_mcp.exports
    where id = target_export_id
  ) then
    raise exception 'export % does not exist for search document append', target_export_id;
  end if;

  if jsonb_typeof(documents_payload) <> 'array' then
    raise exception 'documents_payload must be a JSON array';
  end if;

  if jsonb_typeof(document_entities_payload) <> 'array' then
    raise exception 'document_entities_payload must be a JSON array';
  end if;

  if jsonb_array_length(documents_payload) = 0 and jsonb_array_length(document_entities_payload) = 0 then
    raise exception 'documents_payload and document_entities_payload cannot both be empty';
  end if;

  insert into bubble_mcp.search_documents (
    id,
    export_id,
    document_key,
    primary_entity_key,
    document_type,
    lexical_text,
    semantic_text,
    summary_text,
