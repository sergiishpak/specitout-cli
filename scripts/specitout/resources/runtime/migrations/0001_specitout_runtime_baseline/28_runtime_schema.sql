      else null
    end,
    error_json = case
      when p_outcome in ('retry_wait', 'failed') and p_error_message is not null then
        coalesce(error_json, '{}'::jsonb) || jsonb_build_object('message', p_error_message)
      else
        error_json
    end,
    current_limit = coalesce(p_current_limit, current_limit),
    failure_streak = coalesce(p_failure_streak, failure_streak),
    stagnant_pass_count = coalesce(p_stagnant_pass_count, stagnant_pass_count),
    embedded_documents = coalesce(p_embedded_documents, embedded_documents),
    remaining_documents = coalesce(p_remaining_documents, remaining_documents),
    summary_json = summary_json || coalesce(p_summary_updates, '{}'::jsonb)
  where id = p_job_id
    and status = 'running'
    and lock_token = p_lock_token
  returning *
  into v_job;

  if not found then
    raise exception 'embedding job % is not running with the provided lock token', p_job_id;
  end if;

  if p_mark_export_degraded and p_outcome in ('retry_wait', 'failed') then
    update bubble_mcp.exports e
    set
      readiness_status = case
        when e.readiness_status in ('ready', 'degraded') then 'degraded'
        else 'embedding_pending'
      end,
      failure_reason = coalesce(p_error_message, e.failure_reason)
    where e.id = v_job.export_id;
  end if;

  return bubble_mcp._embedding_job_snapshot(v_job);
end
$$;

create or replace function bubble_mcp.enable_embedding_worker_schedule(
  p_worker_url text,
  p_worker_secret text,
  p_schedule text default '* * * * *',
  p_job_name text default 'bubble_mcp_embedding_worker_every_minute'
)
returns text
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_existing_job_id bigint;
  v_sql text;
  v_headers text;
begin
  if coalesce(btrim(p_worker_url), '') = '' then
    raise exception 'worker_url must be non-empty';
  end if;
  if coalesce(btrim(p_worker_secret), '') = '' then
    raise exception 'worker_secret must be non-empty';
  end if;
  if coalesce(btrim(p_schedule), '') = '' then
    raise exception 'schedule must be non-empty';
  end if;

  create extension if not exists pg_cron with schema extensions;
  create extension if not exists pg_net with schema extensions;

  select jobid
  into v_existing_job_id
  from cron.job
  where jobname = p_job_name
  limit 1;

  if found then
    perform cron.unschedule(v_existing_job_id);
  end if;

  v_headers := jsonb_build_object(
    'Content-Type', 'application/json',
    'x-embedding-worker-secret', p_worker_secret
  )::text;
  v_sql := format(
    'select net.http_post(url := %L, headers := %L::jsonb, body := %L::jsonb);',
    p_worker_url,
    v_headers,
    '{}'
  );
  perform cron.schedule(p_job_name, p_schedule, v_sql);
  return p_job_name;
end
$$;

create or replace function bubble_mcp.disable_embedding_worker_schedule(
  p_job_name text default 'bubble_mcp_embedding_worker_every_minute'
)
returns text
language plpgsql
security definer
set search_path = bubble_mcp, public
as $$
declare
  v_existing_job_id bigint;
begin
  create extension if not exists pg_cron with schema extensions;

  select jobid
  into v_existing_job_id
  from cron.job
  where jobname = p_job_name
  limit 1;

  if found then
    perform cron.unschedule(v_existing_job_id);
  end if;

  return p_job_name;
end
$$;

grant execute on function bubble_mcp.enqueue_embedding_job(text, text, integer, integer, integer) to service_role;
grant execute on function bubble_mcp.get_embedding_job_status(uuid, text, uuid, text) to service_role;
grant execute on function bubble_mcp.request_embedding_job_action(uuid, text) to service_role;
grant execute on function bubble_mcp.claim_next_embedding_job(text, integer) to service_role;
grant execute on function bubble_mcp.heartbeat_embedding_job(uuid, uuid, text, integer, integer, integer, integer, integer, jsonb) to service_role;
grant execute on function bubble_mcp.finalize_embedding_job(uuid, uuid, text, text, integer, integer, integer, integer, integer, integer, jsonb, boolean) to service_role;
grant execute on function bubble_mcp.enable_embedding_worker_schedule(text, text, text, text) to service_role;
grant execute on function bubble_mcp.disable_embedding_worker_schedule(text) to service_role;

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
  v_required_passes integer := 0;
  v_headroom integer := 100;
  v_auto_max_attempts integer := 300;
  v_effective_max_attempts integer := 300;
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
  if p_max_attempts is not null and p_max_attempts <= 0 then
    raise exception 'max_attempts must be positive when provided';
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

  v_required_passes := case
    when v_remaining <= 0 then 0
    else ceil(v_remaining::numeric / p_min_limit::numeric)::integer
  end;
  v_headroom := greatest(100, ceil(v_required_passes::numeric * 0.25)::integer);
  v_auto_max_attempts := v_required_passes + v_headroom;
  v_effective_max_attempts := greatest(coalesce(p_max_attempts, 0), v_auto_max_attempts, 300);

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
    v_effective_max_attempts,
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

  update bubble_mcp.embedding_jobs
  set
    status = 'failed',
    finished_at = coalesce(finished_at, now()),
    updated_at = now(),
    status_message = 'Maximum attempts reached',
    last_error = coalesce(last_error, 'maximum attempts reached')
  where status in ('queued', 'retry_wait')
    and attempt_count >= max_attempts;

  with candidate as (
    select id
    from bubble_mcp.embedding_jobs
    where status in ('queued', 'retry_wait')
      and requested_action is distinct from 'cancel'
      and attempt_count < max_attempts
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
      when p_outcome = 'retry_wait' and p_error_message is null then null
      when p_outcome = 'retry_wait' then coalesce(p_error_message, last_error)
      when p_outcome = 'failed' then coalesce(p_error_message, last_error)
      when p_outcome = 'canceled' then null
      else null
    end,
    error_json = case
      when p_outcome in ('retry_wait', 'failed') and p_error_message is not null then
        coalesce(error_json, '{}'::jsonb) || jsonb_build_object('message', p_error_message)
      else
        error_json
    end,
    current_limit = coalesce(p_current_limit, current_limit),
    failure_streak = coalesce(p_failure_streak, failure_streak),
    stagnant_pass_count = coalesce(p_stagnant_pass_count, stagnant_pass_count),
    embedded_documents = coalesce(p_embedded_documents, embedded_documents),
    remaining_documents = coalesce(p_remaining_documents, remaining_documents),
    summary_json = summary_json || coalesce(p_summary_updates, '{}'::jsonb)
  where id = p_job_id
    and status = 'running'
    and lock_token = p_lock_token
  returning *
  into v_job;

  if not found then
    raise exception 'embedding job % is not running with the provided lock token', p_job_id;
  end if;

  if p_mark_export_degraded and p_outcome in ('retry_wait', 'failed') then
    update bubble_mcp.exports e
    set
      readiness_status = case
        when e.readiness_status in ('ready', 'degraded') then 'degraded'
        else 'embedding_pending'
      end,
      failure_reason = coalesce(p_error_message, e.failure_reason)
    where e.id = v_job.export_id;
  end if;

  return bubble_mcp._embedding_job_snapshot(v_job);
