from __future__ import annotations

from collections.abc import Callable, Mapping

from specitout.runtime import SpecItOutRuntimeError

FetchOne = Callable[[str, Mapping[str, object] | None], dict[str, object] | None]
GetApplication = Callable[[str], dict[str, object] | None]


def resolve_export_scope(
    *,
    fetch_one: FetchOne,
    get_application: GetApplication,
    app_slug: str,
    version_label: str | None,
) -> dict[str, dict[str, object] | None]:
    app = get_application(app_slug)
    if app is None:
        raise SpecItOutRuntimeError(f"Unknown application scope {app_slug}.")
    active_export = fetch_active_export(fetch_one=fetch_one, app_id=app["id"])
    export = fetch_export(fetch_one=fetch_one, app_id=app["id"], version_label=version_label)
    if export is None and version_label is None:
        latest_export = fetch_latest_export(fetch_one=fetch_one, app_id=app["id"])
        if latest_export is not None:
            latest_version = latest_export["version_label"]
            raise SpecItOutRuntimeError(
                f"Application scope {app_slug} does not have an active export yet. "
                f"Use import list --app {app_slug} to inspect registered versions, or rerun "
                f"import status --app {app_slug} --version {latest_version}."
            )
        raise SpecItOutRuntimeError(f"Application scope {app_slug} does not have an active export yet.")
    if export is None:
        raise SpecItOutRuntimeError(f"Unknown export version {version_label} for application scope {app_slug}.")
    export["is_active"] = bool(active_export is not None and active_export["id"] == export["id"])
    if active_export is not None:
        active_export["is_active"] = True
    return {
        "app": app,
        "export": export,
        "active_export": active_export,
    }


def fetch_active_export(*, fetch_one: FetchOne, app_id: object) -> dict[str, object] | None:
    return fetch_one(
        """
select
  id,
  app_id,
  version_label,
  readiness_status::text as readiness_status,
  lifecycle_status::text as lifecycle_status,
  supersedes_export_id,
  import_mode,
  source_export_hash,
  failure_reason,
  metadata_json,
  registered_at
from specitout.exports
where app_id = %(app_id)s
  and lifecycle_status = 'active'
order by registered_at desc
limit 1
""",
        {"app_id": app_id},
    )


def fetch_export(*, fetch_one: FetchOne, app_id: object, version_label: str | None) -> dict[str, object] | None:
    if version_label is None:
        return fetch_active_export(fetch_one=fetch_one, app_id=app_id)
    return fetch_one(
        """
select
  id,
  app_id,
  version_label,
  readiness_status::text as readiness_status,
  lifecycle_status::text as lifecycle_status,
  supersedes_export_id,
  import_mode,
  source_export_hash,
  failure_reason,
  metadata_json,
  registered_at
from specitout.exports
where app_id = %(app_id)s
  and version_label = %(version_label)s
limit 1
""",
        {"app_id": app_id, "version_label": version_label},
    )


def fetch_latest_export(*, fetch_one: FetchOne, app_id: object) -> dict[str, object] | None:
    return fetch_one(
        """
select
  id,
  app_id,
  version_label,
  readiness_status::text as readiness_status,
  lifecycle_status::text as lifecycle_status,
  supersedes_export_id,
  import_mode,
  source_export_hash,
  failure_reason,
  metadata_json,
  registered_at
from specitout.exports
where app_id = %(app_id)s
order by registered_at desc
limit 1
""",
        {"app_id": app_id},
    )


def fetch_latest_pipeline_run(*, fetch_one: FetchOne, export_id: object) -> dict[str, object] | None:
    return fetch_one(
        """
select
  id,
  export_id,
  pipeline_kind,
  status,
  current_stage,
  stage_index,
  stage_count,
  progress_percent,
  status_message,
  requested_action,
  started_at,
  finished_at,
  last_heartbeat_at,
  summary_json,
  error_json
from specitout.pipeline_runs
where export_id = %(export_id)s
order by started_at desc
limit 1
""",
        {"export_id": export_id},
    )
