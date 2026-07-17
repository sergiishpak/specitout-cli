from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from specitout.runtime import SpecItOutRuntimeError


class RegistrationBackend(Protocol):
    def _connect(self) -> object: ...
    def _normalize_row(self, row: object) -> dict[str, object] | None: ...


def default_display_name(app_slug: str) -> str:
    return app_slug.replace("-", " ").title()


def register_import(
    backend: RegistrationBackend,
    *,
    app_slug: str,
    version_label: str,
    source_export_hash: str,
    export_path: Path,
    display_name: str | None,
    source_system: str,
    external_app_id: str | None,
) -> dict[str, object]:
    with backend._connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
select id, slug, display_name, source_system, external_app_id, active_export_id
from specitout.apps
where slug = %(app_slug)s
""",
            {"app_slug": app_slug},
        )
        app = backend._normalize_row(cur.fetchone())
        if app is None:
            cur.execute(
                """
insert into specitout.apps (slug, display_name, source_system, external_app_id)
values (%(app_slug)s, %(display_name)s, %(source_system)s, %(external_app_id)s)
returning id, slug, display_name, source_system, external_app_id, active_export_id
""",
                {
                    "app_slug": app_slug,
                    "display_name": display_name or default_display_name(app_slug),
                    "source_system": source_system,
                    "external_app_id": external_app_id,
                },
            )
            app = backend._normalize_row(cur.fetchone())
        else:
            app = _maybe_update_app(
                backend,
                cur,
                app=app,
                display_name=display_name,
                source_system=source_system,
                external_app_id=external_app_id,
            )

        assert app is not None
        cur.execute(
            """
select
  id,
  version_label,
  readiness_status::text as readiness_status,
  lifecycle_status::text as lifecycle_status,
  supersedes_export_id,
  import_mode,
  source_export_hash,
  registered_at
from specitout.exports
where app_id = %(app_id)s and version_label = %(version_label)s
""",
            {"app_id": app["id"], "version_label": version_label},
        )
        export = backend._normalize_row(cur.fetchone())
        created = False
        if export is None:
            cur.execute(
                """
insert into specitout.exports (
  app_id,
  version_label,
  source_export_hash,
  readiness_status,
  lifecycle_status,
  supersedes_export_id,
  import_mode,
  metadata_json
)
values (
  %(app_id)s,
  %(version_label)s,
  %(source_export_hash)s,
  'registered',
  'candidate',
  %(supersedes_export_id)s,
  'append_new_version',
  %(metadata_json)s::jsonb
)
returning
  id,
  version_label,
  readiness_status::text as readiness_status,
  lifecycle_status::text as lifecycle_status,
  supersedes_export_id,
  import_mode,
  source_export_hash,
  registered_at
""",
                {
                    "app_id": app["id"],
                    "version_label": version_label,
                    "source_export_hash": source_export_hash,
                    "supersedes_export_id": app.get("active_export_id"),
                    "metadata_json": json.dumps(
                        {
                            "registration": {
                                "source_export_path": str(export_path),
                                "source_export_file_name": export_path.name,
                                "source_export_size_bytes": export_path.stat().st_size,
                            }
                        }
                    ),
                },
            )
            export = backend._normalize_row(cur.fetchone())
            created = True
        elif export["source_export_hash"] != source_export_hash:
            raise SpecItOutRuntimeError(
                "An export with this application and version already exists, "
                "but it points at a different Bubble export payload."
            )

        cur.execute(
            """
select
  id,
  version_label,
  readiness_status::text as readiness_status,
  lifecycle_status::text as lifecycle_status
from specitout.exports
where id = %(active_export_id)s
""",
            {"active_export_id": app.get("active_export_id")},
        )
        active_export = backend._normalize_row(cur.fetchone())
        return {
            "app": app,
            "export": export,
            "active_export": active_export,
            "created": created,
        }


def _maybe_update_app(
    backend: RegistrationBackend,
    cur: object,
    *,
    app: dict[str, object],
    display_name: str | None,
    source_system: str,
    external_app_id: str | None,
) -> dict[str, object]:
    changes: dict[str, object] = {}
    if display_name and display_name != app["display_name"]:
        changes["display_name"] = display_name
    if source_system != app["source_system"]:
        changes["source_system"] = source_system
    if external_app_id is not None and external_app_id != app["external_app_id"]:
        changes["external_app_id"] = external_app_id
    if not changes:
        return app
    assignments = ", ".join(f"{key} = %({key})s" for key in changes)
    cur.execute(
        f"""
update specitout.apps
set {assignments}
where id = %(app_id)s
returning id, slug, display_name, source_system, external_app_id, active_export_id
""",
        {"app_id": app["id"], **changes},
    )
    updated = backend._normalize_row(cur.fetchone())
    assert updated is not None
    return updated
