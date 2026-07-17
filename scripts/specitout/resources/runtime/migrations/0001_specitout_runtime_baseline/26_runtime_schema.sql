    summary_text = excluded.summary_text,
    rank_signals_json = excluded.rank_signals_json;

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
  from jsonb_array_elements(document_entities_payload) as assoc
  on conflict (search_document_id, entity_key) do update
  set association_role = excluded.association_role;
end
$$;

grant execute on function bubble_mcp.append_export_search_documents_batch(uuid, jsonb, jsonb) to service_role;

create table if not exists bubble_mcp.pipeline_runs (
  id uuid primary key default extensions.gen_random_uuid(),
  app_id uuid not null references bubble_mcp.apps(id) on delete restrict,
  export_id uuid not null references bubble_mcp.exports(id) on delete restrict,
  pipeline_kind text not null,
  status text not null,
  current_stage text,
  stage_index integer not null default 0,
  stage_count integer not null default 0,
  progress_percent integer not null default 0,
  status_message text,
  requested_action text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  last_heartbeat_at timestamptz not null default now(),
  summary_json jsonb not null default '{}'::jsonb,
  error_json jsonb not null default '{}'::jsonb,
  constraint pipeline_runs_pipeline_kind_nonempty_check check (btrim(pipeline_kind) <> ''),
  constraint pipeline_runs_status_nonempty_check check (btrim(status) <> ''),
  constraint pipeline_runs_stage_index_nonnegative_check check (stage_index >= 0),
  constraint pipeline_runs_stage_count_nonnegative_check check (stage_count >= 0),
  constraint pipeline_runs_progress_percent_range_check check (progress_percent between 0 and 100),
  constraint pipeline_runs_finished_after_started_check check (
    finished_at is null or finished_at >= started_at
  )
);

create index if not exists pipeline_runs_app_started_at_idx
  on bubble_mcp.pipeline_runs (app_id, started_at desc);

create index if not exists pipeline_runs_export_started_at_idx
  on bubble_mcp.pipeline_runs (export_id, started_at desc);

alter table bubble_mcp.ingestion_runs
  add column if not exists pipeline_run_id uuid references bubble_mcp.pipeline_runs(id) on delete set null,
  add column if not exists progress_current integer,
  add column if not exists progress_total integer,
  add column if not exists progress_unit text,
  add column if not exists status_message text,
  add column if not exists current_item_key text,
  add column if not exists last_heartbeat_at timestamptz not null default now();

create index if not exists ingestion_runs_pipeline_run_idx
  on bubble_mcp.ingestion_runs (pipeline_run_id, started_at desc);

alter table bubble_mcp.ingestion_runs
  drop constraint if exists ingestion_runs_progress_nonnegative_check;

alter table bubble_mcp.ingestion_runs
  add constraint ingestion_runs_progress_nonnegative_check check (
    progress_current is null or progress_current >= 0
  );

alter table bubble_mcp.ingestion_runs
  drop constraint if exists ingestion_runs_progress_total_nonnegative_check;

alter table bubble_mcp.ingestion_runs
  add constraint ingestion_runs_progress_total_nonnegative_check check (
    progress_total is null or progress_total >= 0
  );

alter table bubble_mcp.ingestion_runs
  drop constraint if exists ingestion_runs_progress_order_check;

alter table bubble_mcp.ingestion_runs
  add constraint ingestion_runs_progress_order_check check (
    progress_current is null
    or progress_total is null
    or progress_current <= progress_total
  );

create or replace function bubble_mcp.get_pipeline_run_status(
  p_pipeline_run_id uuid default null,
  p_app_slug text default null,
  p_export_id uuid default null,
  p_version_label text default null
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_pipeline bubble_mcp.pipeline_runs%rowtype;
  v_export_id uuid;
  v_phases jsonb;
begin
  if p_pipeline_run_id is not null then
    select *
      into v_pipeline
      from bubble_mcp.pipeline_runs
     where id = p_pipeline_run_id;
  else
    v_export_id := p_export_id;

    if v_export_id is null and p_app_slug is not null and p_version_label is not null then
      select e.id
        into v_export_id
        from bubble_mcp.exports e
        join bubble_mcp.apps a on a.id = e.app_id
       where a.slug = p_app_slug
         and e.version_label = p_version_label
       limit 1;
    end if;

    if v_export_id is null then
      raise exception 'pipeline run status requires pipeline_run_id, export_id, or app_slug with version_label';
    end if;

    select *
      into v_pipeline
      from bubble_mcp.pipeline_runs
     where export_id = v_export_id
     order by started_at desc
     limit 1;
  end if;

  if not found then
    raise exception 'pipeline run not found';
  end if;

  select coalesce(
           jsonb_agg(
             jsonb_build_object(
               'phase', ir.phase,
               'status', ir.status,
               'progress_current', ir.progress_current,
               'progress_total', ir.progress_total,
               'progress_unit', ir.progress_unit,
               'status_message', ir.status_message,
               'current_item_key', ir.current_item_key,
               'last_heartbeat_at', ir.last_heartbeat_at,
               'started_at', ir.started_at,
               'finished_at', ir.finished_at,
               'error_json', coalesce(ir.error_json, '{}'::jsonb),
               'stats_json', coalesce(ir.stats_json, '{}'::jsonb)
             )
             order by ir.started_at asc
           ),
           '[]'::jsonb
         )
    into v_phases
    from bubble_mcp.ingestion_runs ir
   where ir.pipeline_run_id = v_pipeline.id;

  return jsonb_build_object(
    'id', v_pipeline.id,
    'app_id', v_pipeline.app_id,
    'export_id', v_pipeline.export_id,
    'pipeline_kind', v_pipeline.pipeline_kind,
    'status', v_pipeline.status,
    'current_stage', v_pipeline.current_stage,
    'stage_index', v_pipeline.stage_index,
    'stage_count', v_pipeline.stage_count,
    'progress_percent', v_pipeline.progress_percent,
    'status_message', v_pipeline.status_message,
    'requested_action', v_pipeline.requested_action,
    'started_at', v_pipeline.started_at,
    'finished_at', v_pipeline.finished_at,
    'last_heartbeat_at', v_pipeline.last_heartbeat_at,
    'summary_json', coalesce(v_pipeline.summary_json, '{}'::jsonb),
    'error_json', coalesce(v_pipeline.error_json, '{}'::jsonb),
    'can_cancel', (v_pipeline.status = 'running' and coalesce(v_pipeline.requested_action, '') <> 'cancel'),
    'phases', v_phases
  );
end;
$$;

create or replace function bubble_mcp.request_pipeline_run_action(
  p_pipeline_run_id uuid,
  p_requested_action text
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_pipeline bubble_mcp.pipeline_runs%rowtype;
begin
  if p_requested_action is null or btrim(p_requested_action) = '' then
    raise exception 'requested action must be cancel';
  end if;

  if lower(btrim(p_requested_action)) <> 'cancel' then
    raise exception 'requested action must be cancel';
  end if;

  update bubble_mcp.pipeline_runs
     set requested_action = 'cancel'
   where id = p_pipeline_run_id
     and status = 'running'
   returning * into v_pipeline;

  if not found then
    if exists (select 1 from bubble_mcp.pipeline_runs where id = p_pipeline_run_id) then
      raise exception 'pipeline run is not running';
    end if;
    raise exception 'pipeline run not found';
  end if;

  return bubble_mcp.get_pipeline_run_status(p_pipeline_run_id => v_pipeline.id);
end;
$$;

grant execute on function bubble_mcp.get_pipeline_run_status(uuid, text, uuid, text) to service_role;
grant execute on function bubble_mcp.request_pipeline_run_action(uuid, text) to service_role;

do $$
begin
  if not exists (
    select 1
    from pg_type t
    join pg_enum e on e.enumtypid = t.oid
    where t.typnamespace = 'bubble_mcp'::regnamespace
      and t.typname = 'ingestion_run_status'
      and e.enumlabel = 'canceled'
  ) then
    alter type bubble_mcp.ingestion_run_status add value 'canceled';
  end if;
end
$$;

alter table bubble_mcp.exports
  drop constraint if exists exports_app_id_fkey;

alter table bubble_mcp.exports
  add constraint exports_app_id_fkey
  foreign key (app_id)
  references bubble_mcp.apps(id)
  on delete cascade;

alter table bubble_mcp.source_evidence
  drop constraint if exists source_evidence_export_id_fkey;

alter table bubble_mcp.source_evidence
  add constraint source_evidence_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

alter table bubble_mcp.ingestion_runs
  drop constraint if exists ingestion_runs_export_id_fkey;

alter table bubble_mcp.ingestion_runs
  add constraint ingestion_runs_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

alter table bubble_mcp.entities
  drop constraint if exists entities_export_id_fkey;

alter table bubble_mcp.entities
  add constraint entities_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

alter table bubble_mcp.edges
  drop constraint if exists edges_export_id_fkey;

alter table bubble_mcp.edges
  add constraint edges_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

alter table bubble_mcp.entity_facets
  drop constraint if exists entity_facets_export_id_fkey;

alter table bubble_mcp.entity_facets
  add constraint entity_facets_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

alter table bubble_mcp.search_documents
  drop constraint if exists search_documents_export_id_fkey;

alter table bubble_mcp.search_documents
  add constraint search_documents_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

alter table bubble_mcp.overlay_links
  drop constraint if exists overlay_links_export_id_fkey;

alter table bubble_mcp.overlay_links
  add constraint overlay_links_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

alter table bubble_mcp.public_api_workflow_index
  drop constraint if exists public_api_workflow_index_export_id_fkey;

alter table bubble_mcp.public_api_workflow_index
  add constraint public_api_workflow_index_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

alter table bubble_mcp.bundle_cache
  drop constraint if exists bundle_cache_export_id_fkey;

alter table bubble_mcp.bundle_cache
  add constraint bundle_cache_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

alter table bubble_mcp.permission_surface_index
  drop constraint if exists permission_surface_index_export_id_fkey;

alter table bubble_mcp.permission_surface_index
  add constraint permission_surface_index_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

alter table bubble_mcp.pipeline_runs
  drop constraint if exists pipeline_runs_app_id_fkey;

alter table bubble_mcp.pipeline_runs
  add constraint pipeline_runs_app_id_fkey
  foreign key (app_id)
  references bubble_mcp.apps(id)
  on delete cascade;

alter table bubble_mcp.pipeline_runs
  drop constraint if exists pipeline_runs_export_id_fkey;

alter table bubble_mcp.pipeline_runs
  add constraint pipeline_runs_export_id_fkey
  foreign key (export_id)
  references bubble_mcp.exports(id)
  on delete cascade;

create or replace function bubble_mcp.finalize_delete_app(
  p_target_app_id uuid,
  p_keep_lifecycle_action_id uuid default null
)
returns void
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  target_app bubble_mcp.apps%rowtype;
begin
  select *
  into target_app
  from bubble_mcp.apps
  where id = p_target_app_id
  for update;

  if not found then
    raise exception 'app % does not exist for delete finalization', p_target_app_id;
  end if;

  if target_app.lifecycle_status <> 'pending_delete' then
    raise exception 'app % must be pending_delete before delete finalization, found %',
      p_target_app_id,
      target_app.lifecycle_status;
  end if;

  perform set_config('bubble_mcp.allow_export_delete', 'on', true);

  update bubble_mcp.apps
  set active_export_id = null
  where id = p_target_app_id;

  delete from bubble_mcp.lifecycle_actions
  where target_app_id = p_target_app_id
    and (
      p_keep_lifecycle_action_id is null
      or id <> p_keep_lifecycle_action_id
    );

  delete from bubble_mcp.apps
  where id = p_target_app_id;
end
$$;

grant execute on function bubble_mcp.finalize_delete_app(uuid, uuid) to service_role;

create table if not exists bubble_mcp.embedding_jobs (
  id uuid primary key default extensions.gen_random_uuid(),
  app_id uuid not null references bubble_mcp.apps(id) on delete cascade,
  export_id uuid not null references bubble_mcp.exports(id) on delete cascade,
  status text not null default 'queued',
  requested_action text,
  attempt_count integer not null default 0,
  max_attempts integer not null default 100,
  initial_limit integer not null default 256,
  current_limit integer not null default 256,
  min_limit integer not null default 16,
  failure_streak integer not null default 0,
  stagnant_pass_count integer not null default 0,
  embedded_documents integer not null default 0,
  remaining_documents integer not null default 0,
  lock_token uuid,
  lock_acquired_at timestamptz,
  next_run_at timestamptz not null default now(),
  status_message text,
  last_error text,
  started_at timestamptz,
  finished_at timestamptz,
  last_heartbeat_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  summary_json jsonb not null default '{}'::jsonb,
  error_json jsonb not null default '{}'::jsonb,
  constraint embedding_jobs_status_check check (
    status in ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'canceled')
  ),
  constraint embedding_jobs_requested_action_check check (
    requested_action is null or requested_action in ('cancel')
  ),
  constraint embedding_jobs_attempt_count_nonnegative_check check (attempt_count >= 0),
  constraint embedding_jobs_limits_positive_check check (
    initial_limit > 0 and current_limit > 0 and min_limit > 0 and min_limit <= initial_limit
  ),
  constraint embedding_jobs_progress_nonnegative_check check (
    embedded_documents >= 0 and remaining_documents >= 0
  ),
