from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bubble_ingestion.backend_protocol import BackendProtocol


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def record_phase(
    backend: BackendProtocol,
    *,
    export_id: str,
    phase: str,
    import_mode: str,
    status: str,
    pipeline_run_id: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
    progress_unit: str | None = None,
    status_message: str | None = None,
    current_item_key: str | None = None,
    stats_json: dict[str, Any] | None = None,
    error_json: dict[str, Any] | None = None,
) -> None:
    now = _utc_now_iso()
    row = {
        "export_id": export_id,
        "phase": phase,
        "status": status,
        "requested_import_mode": import_mode,
        "pipeline_run_id": pipeline_run_id,
        "progress_current": progress_current,
        "progress_total": progress_total,
        "progress_unit": progress_unit,
        "status_message": status_message,
        "current_item_key": current_item_key,
        "last_heartbeat_at": now,
        "stats_json": stats_json or {},
        "error_json": error_json or {},
    }
    if status == "running":
        row["started_at"] = now
        row["finished_at"] = None
    elif status in {"succeeded", "failed", "skipped", "canceled"}:
        row["started_at"] = now
        row["finished_at"] = now
    backend.upsert_rows(
        "ingestion_runs",
        [row],
    )


def record_phase_checkpoint(
    backend: BackendProtocol,
    *,
    export_id: str,
    phase: str,
    import_mode: str,
    pipeline_run_id: str | None = None,
    progress_current: int,
    progress_total: int,
    progress_unit: str,
    status_message: str,
    current_item_key: str | None = None,
    stats_json: dict[str, Any] | None = None,
) -> None:
    record_phase(
        backend,
        export_id=export_id,
        phase=phase,
        import_mode=import_mode,
        status="running",
        pipeline_run_id=pipeline_run_id,
        progress_current=progress_current,
        progress_total=progress_total,
        progress_unit=progress_unit,
        status_message=status_message,
        current_item_key=current_item_key,
        stats_json=stats_json,
    )
