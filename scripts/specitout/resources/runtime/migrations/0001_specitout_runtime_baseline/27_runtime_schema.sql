  constraint embedding_jobs_finished_after_started_check check (
    finished_at is null or started_at is null or finished_at >= started_at
  )
);

create unique index if not exists embedding_jobs_one_active_per_export_idx
  on bubble_mcp.embedding_jobs(export_id)
  where status in ('queued', 'running', 'retry_wait');

create index if not exists embedding_jobs_status_next_run_idx
  on bubble_mcp.embedding_jobs(status, next_run_at asc, created_at asc);

create or replace function bubble_mcp._embedding_job_snapshot(
  p_job bubble_mcp.embedding_jobs
)
returns jsonb
language sql
stable
set search_path = bubble_mcp, public
as $$
  select jsonb_build_object(
    'job_id', p_job.id,
    'app_id', p_job.app_id,
    'export_id', p_job.export_id,
    'status', p_job.status,
    'requested_action', p_job.requested_action,
    'attempt_count', p_job.attempt_count,
    'max_attempts', p_job.max_attempts,
    'initial_limit', p_job.initial_limit,
    'current_limit', p_job.current_limit,
    'min_limit', p_job.min_limit,
    'failure_streak', p_job.failure_streak,
    'stagnant_pass_count', p_job.stagnant_pass_count,
    'embedded_documents', p_job.embedded_documents,
    'remaining_documents', p_job.remaining_documents,
    'status_message', p_job.status_message,
    'last_error', p_job.last_error,
    'next_run_at', p_job.next_run_at,
    'started_at', p_job.started_at,
    'finished_at', p_job.finished_at,
    'last_heartbeat_at', p_job.last_heartbeat_at,
    'summary_json', p_job.summary_json,
    'error_json', p_job.error_json
  );
$$;

create or replace function bubble_mcp.enqueue_embedding_job(
  p_app_slug text,
  p_version_label text,
  p_initial_limit integer default 256,
  p_min_limit integer default 16,
  p_max_attempts integer default 100
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_app bubble_mcp.apps%rowtype;
  v_export bubble_mcp.exports%rowtype;
  v_existing bubble_mcp.embedding_jobs%rowtype;
  v_job bubble_mcp.embedding_jobs%rowtype;
  v_embedded integer := 0;
  v_remaining integer := 0;
begin
  if p_initial_limit is null or p_initial_limit <= 0 then
    raise exception 'initial_limit must be positive';
  end if;
  if p_min_limit is null or p_min_limit <= 0 then
    raise exception 'min_limit must be positive';
  end if;
  if p_min_limit > p_initial_limit then
    raise exception 'min_limit cannot be greater than initial_limit';
  end if;
  if p_max_attempts is null or p_max_attempts <= 0 then
    raise exception 'max_attempts must be positive';
  end if;

  select *
  into v_app
  from bubble_mcp.apps
  where slug = p_app_slug
  limit 1;

  if not found then
    raise exception 'unknown app_slug %', p_app_slug;
  end if;

  select *
  into v_export
  from bubble_mcp.exports
  where app_id = v_app.id
    and version_label = p_version_label
  limit 1;

  if not found then
    raise exception 'unknown export version_label % for app_slug %', p_version_label, p_app_slug;
  end if;

  if coalesce(v_export.metadata_json #>> '{verification,status}', '') <> 'passed' then
    raise exception 'enqueue-embeddings requires a verification-passed export';
  end if;

  select *
  into v_existing
  from bubble_mcp.embedding_jobs
  where export_id = v_export.id
    and status in ('queued', 'running', 'retry_wait')
  order by created_at desc
  limit 1;

  if found then
    return bubble_mcp._embedding_job_snapshot(v_existing);
  end if;

  select count(*)
  into v_embedded
  from bubble_mcp.search_documents sd
  where sd.export_id = v_export.id
    and sd.embedding is not null
    and sd.embedding_model is not null
    and sd.embedding_dimensions is not null
    and sd.embedded_at is not null;

  select count(*)
  into v_remaining
  from bubble_mcp.search_documents sd
  where sd.export_id = v_export.id
    and (
      sd.embedding is null
      or sd.embedding_model is null
      or sd.embedding_dimensions is null
      or sd.embedded_at is null
    );

  insert into bubble_mcp.embedding_jobs (
    app_id,
    export_id,
    status,
    max_attempts,
    initial_limit,
    current_limit,
    min_limit,
    embedded_documents,
    remaining_documents,
    next_run_at,
    created_at,
    updated_at,
    last_heartbeat_at,
    status_message
  )
  values (
    v_app.id,
    v_export.id,
    case when v_remaining = 0 then 'succeeded' else 'queued' end,
    p_max_attempts,
    p_initial_limit,
    p_initial_limit,
    p_min_limit,
    v_embedded,
    v_remaining,
    now(),
    now(),
    now(),
    now(),
    case when v_remaining = 0 then 'No missing embeddings' else 'Queued for embedding worker' end
  )
  returning *
  into v_job;

  return bubble_mcp._embedding_job_snapshot(v_job);
end
$$;

create or replace function bubble_mcp.get_embedding_job_status(
  p_job_id uuid default null,
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
  v_job bubble_mcp.embedding_jobs%rowtype;
  v_app bubble_mcp.apps%rowtype;
  v_export bubble_mcp.exports%rowtype;
begin
  if p_job_id is not null then
    select *
    into v_job
    from bubble_mcp.embedding_jobs
    where id = p_job_id
    limit 1;
  elsif p_export_id is not null then
    select *
    into v_job
    from bubble_mcp.embedding_jobs
    where export_id = p_export_id
    order by created_at desc
    limit 1;
  elsif p_app_slug is not null and p_version_label is not null then
    select *
    into v_app
    from bubble_mcp.apps
    where slug = p_app_slug
    limit 1;
    if not found then
      raise exception 'unknown app_slug %', p_app_slug;
    end if;

    select *
    into v_export
    from bubble_mcp.exports
    where app_id = v_app.id
      and version_label = p_version_label
    limit 1;
    if not found then
      raise exception 'unknown export version_label % for app_slug %', p_version_label, p_app_slug;
    end if;

    select *
    into v_job
    from bubble_mcp.embedding_jobs
    where export_id = v_export.id
    order by created_at desc
    limit 1;
  else
    raise exception 'embedding job selector requires p_job_id, p_export_id, or app+version';
  end if;

  if not found then
    raise exception 'embedding job not found';
  end if;

  return bubble_mcp._embedding_job_snapshot(v_job);
end
$$;

create or replace function bubble_mcp.request_embedding_job_action(
  p_job_id uuid,
  p_requested_action text
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_job bubble_mcp.embedding_jobs%rowtype;
begin
  if coalesce(p_requested_action, '') <> 'cancel' then
    raise exception 'requested action must be cancel';
  end if;

  update bubble_mcp.embedding_jobs
  set
    requested_action = p_requested_action,
    updated_at = now()
  where id = p_job_id
  returning *
  into v_job;

  if not found then
    raise exception 'embedding job % not found', p_job_id;
  end if;

  return bubble_mcp._embedding_job_snapshot(v_job);
end
$$;

create or replace function bubble_mcp.claim_next_embedding_job(
  p_worker_id text default null,
  p_stale_after_seconds integer default 600
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_job bubble_mcp.embedding_jobs%rowtype;
begin
  if p_stale_after_seconds is null or p_stale_after_seconds <= 0 then
    raise exception 'stale_after_seconds must be positive';
  end if;

  update bubble_mcp.embedding_jobs
  set
    status = 'canceled',
    requested_action = null,
    finished_at = coalesce(finished_at, now()),
    updated_at = now(),
    status_message = 'Canceled before execution'
  where status in ('queued', 'retry_wait')
    and requested_action = 'cancel';

  update bubble_mcp.embedding_jobs
  set
    status = 'retry_wait',
    lock_token = null,
    lock_acquired_at = null,
    requested_action = null,
    next_run_at = now(),
    updated_at = now(),
    status_message = 'Stale heartbeat timeout; requeued',
    last_error = coalesce(last_error, 'stale heartbeat timeout'),
    error_json = coalesce(error_json, '{}'::jsonb) || jsonb_build_object('message', coalesce(last_error, 'stale heartbeat timeout'))
  where status = 'running'
    and (last_heartbeat_at is null or last_heartbeat_at < now() - make_interval(secs => p_stale_after_seconds));

  with candidate as (
    select id
    from bubble_mcp.embedding_jobs
    where status in ('queued', 'retry_wait')
      and requested_action is distinct from 'cancel'
      and next_run_at <= now()
    order by next_run_at asc, created_at asc
    for update skip locked
    limit 1
  )
  update bubble_mcp.embedding_jobs j
  set
    status = 'running',
    requested_action = null,
    lock_token = extensions.gen_random_uuid(),
    lock_acquired_at = now(),
    started_at = coalesce(j.started_at, now()),
    last_heartbeat_at = now(),
    attempt_count = j.attempt_count + 1,
    updated_at = now(),
    status_message = coalesce(
      case when p_worker_id is null then null else format('claimed by worker %s', p_worker_id) end,
      j.status_message
    )
  from candidate
  where j.id = candidate.id
  returning j.*
  into v_job;

  if not found then
    return null;
  end if;

  return bubble_mcp._embedding_job_snapshot(v_job) || jsonb_build_object('lock_token', v_job.lock_token);
end
$$;

create or replace function bubble_mcp.heartbeat_embedding_job(
  p_job_id uuid,
  p_lock_token uuid,
  p_status_message text default null,
  p_embedded_documents integer default null,
  p_remaining_documents integer default null,
  p_current_limit integer default null,
  p_failure_streak integer default null,
  p_stagnant_pass_count integer default null,
  p_summary_updates jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_job bubble_mcp.embedding_jobs%rowtype;
begin
  update bubble_mcp.embedding_jobs
  set
    last_heartbeat_at = now(),
    updated_at = now(),
    status_message = coalesce(p_status_message, status_message),
    embedded_documents = coalesce(p_embedded_documents, embedded_documents),
    remaining_documents = coalesce(p_remaining_documents, remaining_documents),
    current_limit = coalesce(p_current_limit, current_limit),
    failure_streak = coalesce(p_failure_streak, failure_streak),
    stagnant_pass_count = coalesce(p_stagnant_pass_count, stagnant_pass_count),
    summary_json = summary_json || coalesce(p_summary_updates, '{}'::jsonb)
  where id = p_job_id
    and status = 'running'
    and lock_token = p_lock_token
  returning *
  into v_job;

  if not found then
    raise exception 'embedding job % is not running with the provided lock token', p_job_id;
  end if;

  return bubble_mcp._embedding_job_snapshot(v_job) || jsonb_build_object('lock_token', v_job.lock_token);
end
$$;

create or replace function bubble_mcp.finalize_embedding_job(
  p_job_id uuid,
  p_lock_token uuid,
  p_outcome text,
  p_error_message text default null,
  p_next_run_seconds integer default null,
  p_current_limit integer default null,
  p_failure_streak integer default null,
  p_stagnant_pass_count integer default null,
  p_embedded_documents integer default null,
  p_remaining_documents integer default null,
  p_summary_updates jsonb default '{}'::jsonb,
  p_mark_export_degraded boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_job bubble_mcp.embedding_jobs%rowtype;
begin
  if p_outcome not in ('retry_wait', 'succeeded', 'failed', 'canceled') then
    raise exception 'unsupported embedding job outcome %', p_outcome;
  end if;

  update bubble_mcp.embedding_jobs
  set
    status = p_outcome,
    lock_token = null,
    lock_acquired_at = null,
    requested_action = null,
    updated_at = now(),
    last_heartbeat_at = now(),
    finished_at = case
      when p_outcome in ('succeeded', 'failed', 'canceled') then now()
      else null
    end,
    next_run_at = case
      when p_outcome = 'retry_wait' then now() + make_interval(secs => greatest(coalesce(p_next_run_seconds, 0), 0))
      else now()
    end,
    status_message = coalesce(
      case
        when p_outcome = 'retry_wait' then 'Retry scheduled'
        when p_outcome = 'succeeded' then 'Embedding job completed'
        when p_outcome = 'failed' then 'Embedding job failed'
        when p_outcome = 'canceled' then 'Embedding job canceled'
      end,
      status_message
    ),
    last_error = case
      when p_outcome = 'retry_wait' then coalesce(p_error_message, last_error)
      when p_outcome = 'failed' then coalesce(p_error_message, last_error)
      when p_outcome = 'canceled' then null
