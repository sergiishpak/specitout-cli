from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from bubble_ingestion.backend_protocol import BackendProtocol


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def start_pipeline_run(
    backend: BackendProtocol,
    *,
    app_id: str,
    export_id: str,
    pipeline_kind: str,
    stage_names: list[str],
    summary_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "id": str(uuid4()),
        "app_id": app_id,
        "export_id": export_id,
        "pipeline_kind": pipeline_kind,
        "status": "running",
        "current_stage": stage_names[0] if stage_names else None,
        "stage_index": 1 if stage_names else 0,
        "stage_count": len(stage_names),
        "progress_percent": 0 if stage_names else 100,
        "status_message": "starting local import",
        "requested_action": None,
        "started_at": _utc_now_iso(),
        "finished_at": None,
        "last_heartbeat_at": _utc_now_iso(),
        "summary_json": {**(summary_json or {}), "progress_basis": "stages"},
        "error_json": {},
    }
    backend.upsert_rows("pipeline_runs", [row])
    return row


def update_pipeline_run(
    backend: BackendProtocol,
    *,
    pipeline_run: dict[str, Any],
    current_stage: str,
    stage_index: int,
    status_message: str,
    status: str = "running",
    summary_updates: dict[str, Any] | None = None,
    error_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = dict(pipeline_run)
    updated["current_stage"] = current_stage
    updated["stage_index"] = stage_index
    updated["status"] = status
    updated["status_message"] = status_message
    updated["progress_percent"] = 100 if updated["stage_count"] == 0 else round((stage_index / updated["stage_count"]) * 100)
    updated["last_heartbeat_at"] = _utc_now_iso()
    if status != "running":
        updated["finished_at"] = _utc_now_iso()
    if summary_updates:
        summary_json = dict(updated.get("summary_json") or {})
        summary_json.update(summary_updates)
        updated["summary_json"] = summary_json
    updated["summary_json"] = {**dict(updated.get("summary_json") or {}), "progress_basis": "stages"}
    if error_json is not None:
        updated["error_json"] = error_json
    backend.upsert_rows("pipeline_runs", [updated])
    return updated
