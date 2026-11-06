from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from specitout.runtime import SpecItOutRuntimeError

FetchOne = Callable[[str, Mapping[str, object] | None], dict[str, object] | None]


def activate_import(
    *,
    connect: Callable[[], object],
    fetch_one: FetchOne,
    app_slug: str,
    version_label: str,
) -> dict[str, object]:
    app = fetch_one(
        "select * from specitout.apps where slug = %(app_slug)s limit 1",
        {"app_slug": app_slug},
    )
    if app is None:
        raise SpecItOutRuntimeError(f"Unknown application scope {app_slug}.")
    export = fetch_one(
        """
select *
from specitout.exports
where app_id = %(app_id)s and version_label = %(version_label)s
limit 1
""",
        {"app_id": app["id"], "version_label": version_label},
    )
    if export is None:
        raise SpecItOutRuntimeError(f"Unknown export version {version_label} for application scope {app_slug}.")

    if export.get("readiness_status") != "ready":
        raise SpecItOutRuntimeError(
            f"Export {version_label} is not ready for activation; finish indexing and verify readiness first."
        )

    with connect() as conn, conn.cursor() as cur:
        action = _insert_lifecycle_action(cur, app=app, export=export)
        try:
            cur.execute(
                "select * from specitout.activate_export(%s, %s)",
                (app["id"], export["id"]),
            )
            promoted = cur.fetchone()
        except Exception as exc:
            _update_lifecycle_action(cur, str(action["id"]), status="failed", details_json={"message": str(exc)})
            raise SpecItOutRuntimeError(str(exc)) from exc
        _update_lifecycle_action(
            cur,
            str(action["id"]),
            status="succeeded",
            details_json={"result_export_id": str(promoted["id"])},
        )
    return {
        "app_slug": app_slug,
        "version_label": str(promoted["version_label"]),
        "readiness_status": str(promoted["readiness_status"]),
        "lifecycle_status": str(promoted["lifecycle_status"]),
        "audit_id": str(action["id"]),
    }


def _insert_lifecycle_action(cur: object, *, app: dict[str, object], export: dict[str, object]) -> dict[str, object]:
    cur.execute(
        """
insert into specitout.lifecycle_actions (
  action,
  target_kind,
  target_app_id,
  target_app_slug,
  target_export_id,
  target_version_label,
  status,
  actor,
  details_json
)
values (
  'activate-export',
  'export',
  %(app_id)s,
  %(app_slug)s,
  %(export_id)s,
  %(version_label)s,
  'running',
  'cli:specitout',
  '{}'::jsonb
)
returning *
""",
        {
            "app_id": app["id"],
            "app_slug": app["slug"],
            "export_id": export["id"],
            "version_label": export["version_label"],
        },
    )
    return cur.fetchone()


def _update_lifecycle_action(
    cur: object,
    action_id: str,
    *,
    status: str,
    details_json: dict[str, Any],
) -> None:
    cur.execute(
        """
update specitout.lifecycle_actions
set status = %(status)s,
    details_json = %(details_json)s::jsonb,
    finished_at = %(finished_at)s
where id = %(action_id)s
""",
        {
            "action_id": action_id,
            "status": status,
            "details_json": _jsonb(details_json),
            "finished_at": datetime.now(timezone.utc),
        },
    )


def _jsonb(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError as exc:
        raise SpecItOutRuntimeError("psycopg is required for runtime-backed SpecItOut import activation.") from exc
    return Jsonb(value)
