from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from bubble_ingestion.backend_protocol import BackendProtocol
from bubble_ingestion.compact_evidence import evidence_row_requires_storage_delete
from bubble_ingestion.constants import LIFECYCLE_DELETE_TABLES
from bubble_ingestion.errors import IngestionError


def build_lifecycle_action_payload(
    *,
    action: str,
    app: dict[str, Any],
    export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "target_kind": "export" if export is not None else "app",
        "target_app_id": app["id"],
        "target_app_slug": app["slug"],
        "target_export_id": None if export is None else export["id"],
        "target_version_label": None if export is None else export["version_label"],
        "status": "running",
        "actor": "cli:service-role",
        "details_json": {},
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_action_failed(backend: BackendProtocol, action_id: str, exc: Exception) -> None:
    backend.update_lifecycle_action(
        action_id,
        status="failed",
        details_json={"message": str(exc)},
        finished_at=utc_now_iso(),
    )


def _set_action_succeeded(
    backend: BackendProtocol,
    action_id: str,
    details_json: dict[str, Any],
) -> None:
    backend.update_lifecycle_action(
        action_id,
        status="succeeded",
        details_json=details_json,
        finished_at=utc_now_iso(),
    )


def _cleanup_export_scope(backend: BackendProtocol, export_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in LIFECYCLE_DELETE_TABLES:
        counts[table] = backend.count_export_rows(table=table, export_id=export_id)
        backend.delete_export_scoped_rows(table, export_id)
    return counts


def run_activate_export(backend: BackendProtocol, args: argparse.Namespace) -> dict[str, Any]:
    app = backend.get_app(app_slug=args.app_slug)
    if app is None:
        raise IngestionError(f"Unknown app_slug {args.app_slug}")

    export = backend.get_export(app_id=str(app["id"]), version_label=args.version_label)
    if export is None:
        raise IngestionError(
            f"Unknown export version_label {args.version_label} for app_slug {args.app_slug}"
        )

    action = backend.insert_lifecycle_action(
        build_lifecycle_action_payload(action="activate-export", app=app, export=export)
    )
    try:
        promoted = backend.activate_export(app_id=str(app["id"]), target_export_id=str(export["id"]))
    except Exception as exc:
        _set_action_failed(backend, str(action["id"]), exc)
        raise IngestionError(str(exc)) from exc

    _set_action_succeeded(backend, str(action["id"]), {"result_export_id": promoted["id"]})
    return {
        "action": "activate-export",
        "app_slug": app["slug"],
        "version_label": promoted["version_label"],
        "status": "succeeded",
        "db_cleanup_counts": {},
        "storage_object_count": 0,
        "audit_id": action["id"],
    }


def run_archive_export(backend: BackendProtocol, args: argparse.Namespace) -> dict[str, Any]:
    app = backend.get_app(app_slug=args.app_slug)
    if app is None:
        raise IngestionError(f"Unknown app_slug {args.app_slug}")
    export = backend.get_export(app_id=str(app["id"]), version_label=args.version_label)
    if export is None:
        raise IngestionError(
            f"Unknown export version_label {args.version_label} for app_slug {args.app_slug}"
        )

    action = backend.insert_lifecycle_action(
        build_lifecycle_action_payload(action="archive-export", app=app, export=export)
    )
    try:
        archived = backend.archive_export(app_id=str(app["id"]), target_export_id=str(export["id"]))
    except Exception as exc:
        _set_action_failed(backend, str(action["id"]), exc)
        raise IngestionError(str(exc)) from exc

    _set_action_succeeded(backend, str(action["id"]), {"result_export_id": archived["id"]})
    return {
        "action": "archive-export",
        "app_slug": app["slug"],
        "version_label": archived["version_label"],
        "status": "succeeded",
        "db_cleanup_counts": {},
        "storage_object_count": 0,
        "audit_id": action["id"],
    }


def run_delete_export(backend: BackendProtocol, args: argparse.Namespace) -> dict[str, Any]:
    app = backend.get_app(app_slug=args.app_slug)
    if app is None:
        raise IngestionError(f"Unknown app_slug {args.app_slug}")
    export = backend.get_export(app_id=str(app["id"]), version_label=args.version_label)
    if export is None:
        raise IngestionError(
            f"Unknown export version_label {args.version_label} for app_slug {args.app_slug}"
        )
    if export.get("lifecycle_status") not in {"superseded", "archived"}:
        raise IngestionError("delete-export only supports exports in superseded or archived lifecycle state")

    evidence_rows = backend.list_source_evidence_rows(export_id=str(export["id"]))
    managed_evidence_rows = [row for row in evidence_rows if evidence_row_requires_storage_delete(row)]
    action = backend.insert_lifecycle_action(
        build_lifecycle_action_payload(action="delete-export", app=app, export=export)
    )
    backend.update_export(str(export["id"]), lifecycle_status="pending_delete")

    try:
        for row in managed_evidence_rows:
            backend.delete_object(
                bucket=str(row["storage_bucket"]),
                object_path=str(row["storage_object_path"]),
            )
        cleanup_counts = _cleanup_export_scope(backend, str(export["id"]))
        backend.delete_export(export_id=str(export["id"]))
    except Exception as exc:
        _set_action_failed(backend, str(action["id"]), exc)
        raise IngestionError(str(exc)) from exc

    _set_action_succeeded(
        backend,
        str(action["id"]),
        {
            "deleted_export_id": export["id"],
            "storage_object_count": len(managed_evidence_rows),
            "db_cleanup_counts": cleanup_counts,
        },
    )
    return {
        "action": "delete-export",
        "app_slug": app["slug"],
        "version_label": export["version_label"],
        "status": "succeeded",
        "db_cleanup_counts": cleanup_counts,
        "storage_object_count": len(managed_evidence_rows),
        "audit_id": action["id"],
    }


def run_archive_app(backend: BackendProtocol, args: argparse.Namespace) -> dict[str, Any]:
    app = backend.get_app(app_slug=args.app_slug)
    if app is None:
        raise IngestionError(f"Unknown app_slug {args.app_slug}")

    exports = backend.list_exports(app_id=str(app["id"]))
    if app.get("active_export_id") is not None or any(
        export.get("lifecycle_status") == "active" for export in exports
    ):
        raise IngestionError("archive-app requires the app to have no active export")

    action = backend.insert_lifecycle_action(build_lifecycle_action_payload(action="archive-app", app=app))
    try:
        archived = backend.archive_app(app_id=str(app["id"]))
    except Exception as exc:
        _set_action_failed(backend, str(action["id"]), exc)
        raise IngestionError(str(exc)) from exc

    _set_action_succeeded(backend, str(action["id"]), {"archived_app_id": archived["id"]})
    return {
        "action": "archive-app",
        "app_slug": archived["slug"],
        "status": "succeeded",
        "db_cleanup_counts": {},
        "storage_object_count": 0,
        "audit_id": action["id"],
    }


def run_delete_app(backend: BackendProtocol, args: argparse.Namespace) -> dict[str, Any]:
    app = backend.get_app(app_slug=args.app_slug)
    if app is None:
        raise IngestionError(f"Unknown app_slug {args.app_slug}")

    exports = backend.list_exports(app_id=str(app["id"]))
    action = backend.insert_lifecycle_action(build_lifecycle_action_payload(action="delete-app", app=app))
    backend.prepare_app_for_delete(app_id=str(app["id"]))

    cleanup_counts = {table: 0 for table in LIFECYCLE_DELETE_TABLES}
    storage_object_count = 0
    try:
        for export in exports:
            evidence_rows = backend.list_source_evidence_rows(export_id=str(export["id"]))
            for row in evidence_rows:
                if not evidence_row_requires_storage_delete(row):
                    continue
                storage_object_count += 1
                backend.delete_object(
                    bucket=str(row["storage_bucket"]),
                    object_path=str(row["storage_object_path"]),
                )
            for table in cleanup_counts:
                cleanup_counts[table] += backend.count_export_rows(table=table, export_id=str(export["id"]))
        backend.finalize_delete_app(
            app_id=str(app["id"]),
            keep_lifecycle_action_id=str(action["id"]),
        )
    except Exception as exc:
        _set_action_failed(backend, str(action["id"]), exc)
        raise IngestionError(str(exc)) from exc

    _set_action_succeeded(
        backend,
        str(action["id"]),
        {
            "deleted_app_id": app["id"],
            "storage_object_count": storage_object_count,
            "db_cleanup_counts": cleanup_counts,
            "deleted_export_count": len(exports),
        },
    )
    return {
        "action": "delete-app",
        "app_slug": app["slug"],
        "status": "succeeded",
        "db_cleanup_counts": cleanup_counts,
        "storage_object_count": storage_object_count,
        "audit_id": action["id"],
    }
