-- SpecItOut runtime baseline generated from the current immutable development migration stack.
-- Development migration history remains authoritative outside packaged runtime assets.


-- P1.1 bootstrap only:
-- - enable required extensions
-- - provision private storage buckets
-- P1.2 starts the retrieval schema, constraints, and indexes.

create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm with schema extensions;

insert into storage.buckets (id, name, public)
values
  ('bubble-source-artifacts', 'bubble-source-artifacts', false),
  ('bubble-processed-artifacts', 'bubble-processed-artifacts', false)
on conflict (id) do update
set
  name = excluded.name,
  public = excluded.public;

create extension if not exists pgcrypto with schema extensions;

create schema if not exists bubble_mcp;

do $$
begin
  if not exists (
    select 1
    from pg_type t
    join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = 'bubble_mcp'
      and t.typname = 'app_lifecycle_status'
  ) then
    create type bubble_mcp.app_lifecycle_status as enum (
      'active',
      'archived',
      'pending_delete',
      'deleted'
    );
  end if;

  if not exists (
    select 1
    from pg_type t
    join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = 'bubble_mcp'
      and t.typname = 'export_readiness_status'
  ) then
    create type bubble_mcp.export_readiness_status as enum (
      'registered',
      'ingesting',
      'searchable',
      'embedding_pending',
      'ready',
      'degraded',
      'failed'
    );
  end if;

  if not exists (
    select 1
    from pg_type t
    join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = 'bubble_mcp'
      and t.typname = 'export_lifecycle_status'
  ) then
    create type bubble_mcp.export_lifecycle_status as enum (
      'candidate',
      'active',
      'superseded',
      'archived',
      'pending_delete',
      'deleted'
    );
  end if;

  if not exists (
    select 1
    from pg_type t
    join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = 'bubble_mcp'
      and t.typname = 'ingestion_phase'
  ) then
    create type bubble_mcp.ingestion_phase as enum (
      'registration',
      'artifact_upload',
      'graph_load',
      'verification',
      'embedding',
      'rebuild',
      'cleanup'
    );
  end if;

  if not exists (
    select 1
    from pg_type t
    join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = 'bubble_mcp'
      and t.typname = 'ingestion_run_status'
  ) then
    create type bubble_mcp.ingestion_run_status as enum (
      'queued',
      'running',
      'succeeded',
      'failed',
      'cancelled'
    );
  end if;

  if not exists (
    select 1
    from pg_type t
    join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = 'bubble_mcp'
      and t.typname = 'import_mode'
  ) then
    create type bubble_mcp.import_mode as enum (
      'append_new_version',
      'replace_active_version',
      'retry_existing_export'
    );
  end if;
end
$$;

create table if not exists bubble_mcp.apps (
  id uuid primary key default extensions.gen_random_uuid(),
  slug text not null,
  display_name text not null,
  external_app_id text,
  lifecycle_status bubble_mcp.app_lifecycle_status not null default 'active',
  active_export_id uuid,
  source_system text not null,
  created_at timestamptz not null default now(),
  archived_at timestamptz,
  pending_delete_at timestamptz,
  deleted_at timestamptz,
  constraint apps_slug_key unique (slug),
  constraint apps_slug_lowercase_check check (slug = lower(slug)),
  constraint apps_slug_format_check check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  constraint apps_source_system_nonempty_check check (btrim(source_system) <> ''),
  constraint apps_display_name_nonempty_check check (btrim(display_name) <> '')
);

create table if not exists bubble_mcp.exports (
  id uuid primary key default extensions.gen_random_uuid(),
  app_id uuid not null references bubble_mcp.apps(id) on delete restrict,
  version_label text not null,
  source_export_hash text not null,
  context_pack_version text,
  readiness_status bubble_mcp.export_readiness_status not null default 'registered',
  lifecycle_status bubble_mcp.export_lifecycle_status not null default 'candidate',
  supersedes_export_id uuid,
  import_mode bubble_mcp.import_mode not null,
  registered_at timestamptz not null default now(),
  activated_at timestamptz,
  searchable_at timestamptz,
  ready_at timestamptz,
  failed_at timestamptz,
  archived_at timestamptz,
  pending_delete_at timestamptz,
  deleted_at timestamptz,
  retention_until timestamptz,
  failure_reason text,
  metadata_json jsonb not null default '{}'::jsonb,
  constraint exports_app_version_label_key unique (app_id, version_label),
  constraint exports_app_id_id_key unique (app_id, id),
  constraint exports_supersedes_same_app_fkey
    foreign key (app_id, supersedes_export_id)
    references bubble_mcp.exports(app_id, id)
    on delete restrict,
  constraint exports_version_label_nonempty_check check (btrim(version_label) <> ''),
  constraint exports_source_export_hash_nonempty_check check (btrim(source_export_hash) <> '')
);

alter table bubble_mcp.apps
  add constraint apps_active_export_same_app_fkey
  foreign key (id, active_export_id)
  references bubble_mcp.exports(app_id, id)
  on delete restrict
  deferrable initially deferred;

create table if not exists bubble_mcp.source_evidence (
  id uuid primary key default extensions.gen_random_uuid(),
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  evidence_role text not null,
  storage_bucket text not null,
  storage_object_path text not null,
  content_hash text,
  source_path text,
  metadata_json jsonb not null default '{}'::jsonb,
  captured_at timestamptz not null default now(),
  constraint source_evidence_unique_key unique (export_id, evidence_role, storage_bucket, storage_object_path),
  constraint source_evidence_role_nonempty_check check (btrim(evidence_role) <> ''),
  constraint source_evidence_role_format_check check (evidence_role = lower(evidence_role)),
  constraint source_evidence_storage_bucket_nonempty_check check (btrim(storage_bucket) <> ''),
  constraint source_evidence_storage_object_path_nonempty_check check (btrim(storage_object_path) <> '')
);

create table if not exists bubble_mcp.ingestion_runs (
  id uuid primary key default extensions.gen_random_uuid(),
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  phase bubble_mcp.ingestion_phase not null,
  status bubble_mcp.ingestion_run_status not null,
  requested_import_mode bubble_mcp.import_mode,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  stats_json jsonb not null default '{}'::jsonb,
  error_json jsonb not null default '{}'::jsonb,
  constraint ingestion_runs_finished_after_started_check check (
    finished_at is null or finished_at >= started_at
  )
);

create table if not exists bubble_mcp.entities (
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  entity_key text not null,
  entity_type text not null,
  display_name text not null,
  source_id text,
  source_path text not null,
  parent_entity_key text,
  is_synthetic boolean not null default false,
  is_virtual boolean not null default false,
  summary text,
  structural_json jsonb not null default '{}'::jsonb,
  semantic_json jsonb not null default '{}'::jsonb,
  primary key (export_id, entity_key),
  constraint entities_entity_type_nonempty_check check (btrim(entity_type) <> ''),
  constraint entities_display_name_nonempty_check check (btrim(display_name) <> ''),
  constraint entities_source_path_nonempty_check check (btrim(source_path) <> '')
);

alter table bubble_mcp.entities
  add constraint entities_parent_entity_fkey
  foreign key (export_id, parent_entity_key)
  references bubble_mcp.entities(export_id, entity_key)
  on delete set null
  deferrable initially deferred;

create table if not exists bubble_mcp.edges (
  id uuid primary key default extensions.gen_random_uuid(),
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  from_entity_key text not null,
  relation text not null,
  to_entity_key text not null,
  is_resolved boolean not null default true,
  evidence_path text,
  edge_metadata_json jsonb not null default '{}'::jsonb,
  constraint edges_from_entity_key_nonempty_check check (btrim(from_entity_key) <> ''),
  constraint edges_relation_nonempty_check check (btrim(relation) <> ''),
  constraint edges_to_entity_key_nonempty_check check (btrim(to_entity_key) <> '')
);

create table if not exists bubble_mcp.entity_facets (
  id uuid primary key default extensions.gen_random_uuid(),
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  entity_key text not null,
  facet_type text not null,
  facet_value text not null,
  constraint entity_facets_export_entity_fkey
    foreign key (export_id, entity_key)
    references bubble_mcp.entities(export_id, entity_key)
    on delete cascade,
  constraint entity_facets_unique_key unique (export_id, entity_key, facet_type, facet_value),
  constraint entity_facets_facet_type_nonempty_check check (btrim(facet_type) <> ''),
  constraint entity_facets_facet_value_nonempty_check check (btrim(facet_value) <> '')
);

create table if not exists bubble_mcp.search_documents (
  id uuid primary key default extensions.gen_random_uuid(),
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  document_key text not null,
  primary_entity_key text,
  document_type text not null,
  search_text text not null,
  summary_text text,
  embedding extensions.vector,
  embedding_model text,
  embedding_dimensions integer,
  embedded_at timestamptz,
  rank_signals_json jsonb not null default '{}'::jsonb,
  constraint search_documents_unique_key unique (export_id, document_key),
  constraint search_documents_id_export_key unique (id, export_id),
  constraint search_documents_primary_entity_fkey
    foreign key (export_id, primary_entity_key)
    references bubble_mcp.entities(export_id, entity_key)
    on delete set null
    deferrable initially deferred,
  constraint search_documents_document_key_nonempty_check check (btrim(document_key) <> ''),
  constraint search_documents_document_type_nonempty_check check (btrim(document_type) <> ''),
  constraint search_documents_search_text_nonempty_check check (btrim(search_text) <> ''),
  constraint search_documents_embedding_dimensions_check check (
    embedding_dimensions is null or embedding_dimensions > 0
  ),
  constraint search_documents_embedding_dimension_match_check check (
    embedding is null
    or (
      embedding_dimensions is not null
      and extensions.vector_dims(embedding) = embedding_dimensions
    )
  )
);

create table if not exists bubble_mcp.search_document_entities (
  search_document_id uuid not null,
  export_id uuid not null,
  entity_key text not null,
  association_role text not null default 'supporting',
  created_at timestamptz not null default now(),
  primary key (search_document_id, entity_key),
  constraint search_document_entities_document_fkey
    foreign key (search_document_id, export_id)
    references bubble_mcp.search_documents(id, export_id)
    on delete cascade,
  constraint search_document_entities_entity_fkey
    foreign key (export_id, entity_key)
    references bubble_mcp.entities(export_id, entity_key)
    on delete cascade,
  constraint search_document_entities_association_role_nonempty_check check (btrim(association_role) <> '')
);

create table if not exists bubble_mcp.overlay_links (
  id uuid primary key default extensions.gen_random_uuid(),
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  overlay_type text not null,
  entity_key text not null,
  source_path text not null,
  overlay_json jsonb not null default '{}'::jsonb,
  constraint overlay_links_export_entity_fkey
    foreign key (export_id, entity_key)
    references bubble_mcp.entities(export_id, entity_key)
    on delete cascade,
  constraint overlay_links_unique_key unique (export_id, entity_key, overlay_type, source_path),
  constraint overlay_links_overlay_type_nonempty_check check (btrim(overlay_type) <> ''),
  constraint overlay_links_source_path_nonempty_check check (btrim(source_path) <> '')
);

create table if not exists bubble_mcp.public_api_workflow_index (
  id uuid primary key default extensions.gen_random_uuid(),
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  entity_key text not null,
  workflow_name text not null,
  trigger_option text,
  requires_auth boolean not null default false,
  accepts_request_data boolean not null default false,
  request_metadata_json jsonb not null default '{}'::jsonb,
  constraint public_api_workflow_index_export_entity_fkey
    foreign key (export_id, entity_key)
    references bubble_mcp.entities(export_id, entity_key)
    on delete cascade,
  constraint public_api_workflow_index_unique_key unique (export_id, entity_key, workflow_name),
  constraint public_api_workflow_index_workflow_name_nonempty_check check (btrim(workflow_name) <> '')
);

create table if not exists bubble_mcp.bundle_cache (
  id uuid primary key default extensions.gen_random_uuid(),
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  bundle_key text not null,
  query_text text,
  search_mode text not null default 'root',
  bundle_json jsonb not null,
  created_at timestamptz not null default now(),
  constraint bundle_cache_unique_key unique (export_id, bundle_key),
  constraint bundle_cache_bundle_key_nonempty_check check (btrim(bundle_key) <> ''),
  constraint bundle_cache_search_mode_nonempty_check check (btrim(search_mode) <> '')
);

create unique index if not exists apps_source_system_external_app_id_key
  on bubble_mcp.apps (source_system, external_app_id)
  where external_app_id is not null;

create unique index if not exists source_evidence_one_bubble_export_per_export_idx
  on bubble_mcp.source_evidence (export_id)
  where evidence_role = 'bubble_export';

create unique index if not exists source_evidence_one_context_pack_per_export_idx
  on bubble_mcp.source_evidence (export_id)
  where evidence_role = 'context_pack';

create index if not exists source_evidence_export_role_idx
  on bubble_mcp.source_evidence (export_id, evidence_role);

create index if not exists apps_active_export_id_idx
  on bubble_mcp.apps (active_export_id);

create index if not exists exports_app_lifecycle_readiness_registered_idx
  on bubble_mcp.exports (app_id, lifecycle_status, readiness_status, registered_at desc);

create unique index if not exists exports_one_active_per_app_idx
  on bubble_mcp.exports (app_id)
  where lifecycle_status = 'active';

create index if not exists entities_export_entity_type_idx
  on bubble_mcp.entities (export_id, entity_type);

create index if not exists entities_export_display_name_idx
  on bubble_mcp.entities (export_id, display_name);

create index if not exists edges_export_from_entity_key_idx
  on bubble_mcp.edges (export_id, from_entity_key);

create index if not exists edges_export_to_entity_key_idx
  on bubble_mcp.edges (export_id, to_entity_key);

create index if not exists entity_facets_export_facet_lookup_idx
  on bubble_mcp.entity_facets (export_id, facet_type, facet_value);

create index if not exists search_document_entities_export_entity_idx
  on bubble_mcp.search_document_entities (export_id, entity_key);

create index if not exists search_documents_search_text_trgm_idx
  on bubble_mcp.search_documents
  using gin (search_text extensions.gin_trgm_ops);

create index if not exists search_documents_embedding_hnsw_idx
  on bubble_mcp.search_documents
  using hnsw ((embedding::extensions.vector(1536)) extensions.vector_cosine_ops)
  where embedding is not null
    and embedding_dimensions = 1536;

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
    count(sde.entity_key)
  into
    doc_primary_entity_key,
    linked_entity_count
  from bubble_mcp.search_documents sd
  left join bubble_mcp.search_document_entities sde
    on sde.search_document_id = sd.id
   and sde.export_id = sd.export_id
  where sd.id = target_document_id
    and sd.export_id = target_export_id
