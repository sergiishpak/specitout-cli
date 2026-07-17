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
       from bubble_mcp.search_document_entities sde
       where sde.search_document_id = target_document_id
         and sde.export_id = target_export_id
         and sde.entity_key = doc_primary_entity_key
     ) then
    raise exception 'search document % primary_entity_key must also appear in search_document_entities', target_document_id;
  end if;
end
$$;

create or replace function bubble_mcp.enforce_active_export_pointer()
returns trigger
language plpgsql
set search_path = bubble_mcp, public
as $$
declare
  target_export bubble_mcp.exports%rowtype;
begin
  if new.active_export_id is null then
    return new;
  end if;

  select *
  into target_export
  from bubble_mcp.exports
  where id = new.active_export_id;

  if not found then
    raise exception 'active_export_id % does not reference an existing export', new.active_export_id;
  end if;

  if target_export.app_id <> new.id then
    raise exception 'active_export_id % does not belong to app %', new.active_export_id, new.id;
  end if;

  if target_export.lifecycle_status <> 'active' then
    raise exception 'active_export_id % must point to an export in active lifecycle state', new.active_export_id;
  end if;

  if target_export.readiness_status not in ('searchable', 'embedding_pending', 'ready', 'degraded') then
    raise exception 'active_export_id % must point to a query-eligible export', new.active_export_id;
  end if;

  return new;
end
$$;

create or replace function bubble_mcp.enforce_export_state_for_active_pointer()
returns trigger
language plpgsql
set search_path = bubble_mcp, public
as $$
begin
  if exists (
    select 1
    from bubble_mcp.apps a
    where a.active_export_id = new.id
      and (
        new.app_id <> a.id
        or new.lifecycle_status <> 'active'
        or new.readiness_status not in ('searchable', 'embedding_pending', 'ready', 'degraded')
      )
  ) then
    raise exception 'export % cannot remain an active app pointer with lifecycle % and readiness %',
      new.id,
      new.lifecycle_status,
      new.readiness_status;
  end if;

  return new;
end
$$;

create or replace function bubble_mcp.block_direct_export_delete()
returns trigger
language plpgsql
set search_path = bubble_mcp, public
as $$
begin
  raise exception 'direct delete of export % is blocked; use coordinated lifecycle commands instead', old.id;
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

drop trigger if exists apps_active_export_pointer_guard on bubble_mcp.apps;
create constraint trigger apps_active_export_pointer_guard
after insert or update of active_export_id
on bubble_mcp.apps
deferrable initially deferred
for each row
execute function bubble_mcp.enforce_active_export_pointer();

drop trigger if exists exports_active_pointer_state_guard on bubble_mcp.exports;
create constraint trigger exports_active_pointer_state_guard
after update of app_id, lifecycle_status, readiness_status
on bubble_mcp.exports
deferrable initially deferred
for each row
execute function bubble_mcp.enforce_export_state_for_active_pointer();

drop trigger if exists exports_block_direct_delete_guard on bubble_mcp.exports;
create trigger exports_block_direct_delete_guard
before delete
on bubble_mcp.exports
for each row
execute function bubble_mcp.block_direct_export_delete();

drop trigger if exists search_documents_membership_guard on bubble_mcp.search_documents;
create constraint trigger search_documents_membership_guard
after insert or update of primary_entity_key, export_id
on bubble_mcp.search_documents
deferrable initially deferred
for each row
execute function bubble_mcp.enforce_search_document_membership();

drop trigger if exists search_document_entities_membership_guard on bubble_mcp.search_document_entities;
create constraint trigger search_document_entities_membership_guard
after insert or update or delete
on bubble_mcp.search_document_entities
deferrable initially deferred
for each row
execute function bubble_mcp.enforce_search_document_membership();

create or replace function bubble_mcp.is_query_eligible_export_readiness(
  target_status bubble_mcp.export_readiness_status
)
returns boolean
language sql
immutable
set search_path = bubble_mcp, public
as $$
  select target_status in ('searchable', 'embedding_pending', 'ready', 'degraded');
$$;

create or replace function bubble_mcp.validate_export_readiness_transition(
  current_status bubble_mcp.export_readiness_status,
  next_status bubble_mcp.export_readiness_status
)
returns void
language plpgsql
set search_path = bubble_mcp, public
as $$
begin
  if current_status = next_status then
    return;
  end if;

  if not (
    (current_status = 'registered' and next_status = 'ingesting')
    or (current_status = 'ingesting' and next_status in ('searchable', 'failed'))
    or (current_status = 'searchable' and next_status in ('embedding_pending', 'degraded'))
    or (current_status = 'embedding_pending' and next_status in ('ready', 'degraded'))
    or (current_status = 'ready' and next_status = 'degraded')
    or (current_status = 'degraded' and next_status = 'ready')
    or (current_status = 'failed' and next_status = 'ingesting')
  ) then
    raise exception 'illegal export readiness transition from % to %', current_status, next_status;
  end if;
end
$$;

create or replace function bubble_mcp.validate_export_lifecycle_transition(
  current_status bubble_mcp.export_lifecycle_status,
  next_status bubble_mcp.export_lifecycle_status
)
returns void
language plpgsql
set search_path = bubble_mcp, public
as $$
begin
  if current_status = next_status then
    return;
  end if;

  if not (
    (current_status = 'candidate' and next_status in ('active', 'archived', 'pending_delete'))
    or (current_status = 'active' and next_status = 'superseded')
    or (current_status = 'superseded' and next_status in ('archived', 'pending_delete'))
    or (current_status = 'archived' and next_status = 'pending_delete')
  ) then
    raise exception 'illegal export lifecycle transition from % to %', current_status, next_status;
  end if;
end
$$;

create or replace function bubble_mcp.enforce_active_export_pointer()
returns trigger
language plpgsql
set search_path = bubble_mcp, public
as $$
declare
  current_app bubble_mcp.apps%rowtype;
  target_export bubble_mcp.exports%rowtype;
  active_export bubble_mcp.exports%rowtype;
begin
  select *
  into current_app
  from bubble_mcp.apps
  where id = new.id;

  if not found then
    raise exception 'app % does not exist for active export validation', new.id;
  end if;

  if current_app.active_export_id is not null then
    select *
    into target_export
    from bubble_mcp.exports
    where id = current_app.active_export_id;

    if not found then
      raise exception 'active_export_id % does not reference an existing export', current_app.active_export_id;
    end if;

    if target_export.app_id <> current_app.id then
      raise exception 'active_export_id % does not belong to app %', current_app.active_export_id, current_app.id;
    end if;

    if target_export.lifecycle_status <> 'active' then
      raise exception 'active_export_id % must point to an export in active lifecycle state', current_app.active_export_id;
    end if;

    if not bubble_mcp.is_query_eligible_export_readiness(target_export.readiness_status) then
      raise exception 'active_export_id % must point to a query-eligible export', current_app.active_export_id;
    end if;
  end if;

  select *
  into active_export
  from bubble_mcp.exports
  where app_id = current_app.id
    and lifecycle_status = 'active';

  if found then
    if current_app.lifecycle_status <> 'active' then
      raise exception 'app % cannot leave active lifecycle while export % remains active',
        current_app.id,
        active_export.id;
    end if;

    if current_app.active_export_id is distinct from active_export.id then
      raise exception 'app % must point active_export_id at active export %',
        current_app.id,
        active_export.id;
    end if;
  end if;

  return new;
end
$$;

alter table bubble_mcp.exports
  drop constraint if exists exports_failure_reason_required_check;

alter table bubble_mcp.exports
  add constraint exports_failure_reason_required_check check (
    readiness_status not in ('failed', 'degraded')
    or nullif(btrim(failure_reason), '') is not null
  );

create or replace function bubble_mcp.enforce_export_state_transition()
returns trigger
language plpgsql
set search_path = bubble_mcp, public
as $$
declare
  owning_app bubble_mcp.apps%rowtype;
begin
  if tg_op <> 'UPDATE' then
    return new;
  end if;

  if new.readiness_status is distinct from old.readiness_status then
    perform bubble_mcp.validate_export_readiness_transition(old.readiness_status, new.readiness_status);

    if old.readiness_status in ('failed', 'degraded')
       and new.readiness_status not in ('failed', 'degraded') then
      new.failure_reason := null;
    end if;

    case new.readiness_status
      when 'searchable' then
        new.searchable_at := now();
      when 'ready' then
        new.ready_at := now();
      when 'failed' then
        new.failed_at := now();
      when 'ingesting' then
        if old.readiness_status = 'failed' then
          new.failed_at := null;
        end if;
      else
        null;
    end case;
  end if;

  if new.lifecycle_status is distinct from old.lifecycle_status then
    perform bubble_mcp.validate_export_lifecycle_transition(old.lifecycle_status, new.lifecycle_status);

    case new.lifecycle_status
      when 'active' then
        select *
        into owning_app
        from bubble_mcp.apps
        where id = new.app_id;

        if not found then
          raise exception 'export % must belong to an existing app before activation', new.id;
        end if;

        if owning_app.lifecycle_status <> 'active' then
          raise exception 'export % cannot be activated while app % has lifecycle %',
            new.id,
            new.app_id,
            owning_app.lifecycle_status;
        end if;

        if not bubble_mcp.is_query_eligible_export_readiness(new.readiness_status) then
          raise exception 'export % cannot be activated with readiness %',
            new.id,
            new.readiness_status;
        end if;

        new.activated_at := now();
      when 'archived' then
        new.archived_at := now();
      when 'pending_delete' then
        new.pending_delete_at := now();
      else
        null;
    end case;
  end if;

  return new;
end
$$;

create or replace function bubble_mcp.enforce_export_state_for_active_pointer()
returns trigger
language plpgsql
set search_path = bubble_mcp, public
as $$
declare
  owning_app bubble_mcp.apps%rowtype;
begin
  if new.lifecycle_status = 'active' then
    select *
    into owning_app
    from bubble_mcp.apps
    where id = new.app_id;

    if not found then
      raise exception 'active export % must belong to an existing app', new.id;
    end if;

    if owning_app.lifecycle_status <> 'active' then
      raise exception 'active export % cannot belong to app % with lifecycle %',
        new.id,
        new.app_id,
        owning_app.lifecycle_status;
    end if;

    if owning_app.active_export_id is distinct from new.id then
      raise exception 'active export % must also be the active_export_id for app %',
        new.id,
        new.app_id;
    end if;

    if not bubble_mcp.is_query_eligible_export_readiness(new.readiness_status) then
      raise exception 'active export % must remain query-eligible, found readiness %',
        new.id,
        new.readiness_status;
    end if;
  end if;

  if exists (
    select 1
    from bubble_mcp.apps a
    where a.active_export_id = new.id
      and (
        new.app_id <> a.id
        or a.lifecycle_status <> 'active'
        or new.lifecycle_status <> 'active'
        or not bubble_mcp.is_query_eligible_export_readiness(new.readiness_status)
      )
  ) then
    raise exception 'export % cannot remain an active app pointer with app %, lifecycle %, and readiness %',
      new.id,
      new.app_id,
      new.lifecycle_status,
      new.readiness_status;
  end if;

  return new;
end
$$;

drop trigger if exists exports_state_transition_guard on bubble_mcp.exports;
create trigger exports_state_transition_guard
before update of app_id, readiness_status, lifecycle_status, failure_reason
on bubble_mcp.exports
for each row
execute function bubble_mcp.enforce_export_state_transition();

drop trigger if exists apps_active_export_pointer_guard on bubble_mcp.apps;
create constraint trigger apps_active_export_pointer_guard
after insert or update of active_export_id, lifecycle_status
on bubble_mcp.apps
deferrable initially deferred
for each row
