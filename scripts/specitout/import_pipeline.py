from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from bubble_ingestion.compact_evidence import EVIDENCE_LOCATION_LOCAL_ONLY, LOCAL_ONLY_EVIDENCE_BUCKET
from bubble_ingestion.ingestion_runs import record_phase, record_phase_checkpoint
from bubble_ingestion.pipeline_runs import start_pipeline_run, update_pipeline_run
from specitout.import_graph import build_normalized_import_graph
from specitout.progress import ImportProgressReporter, progress_scope
from specitout.backend_writes import prepare_rows_for_upsert

IMPORT_PIPELINE_KIND = "specitout_import"
IMPORT_MODE = "append_new_version"
PIPELINE_STAGES = [
    "export_registration",
    "source_evidence_persistence",
    "parse_export_payload",
    "context_pack_build",
    "graph_normalization",
    "graph_load",
    "pipeline_tracking_ready",
]
GRAPH_TABLES = (
    "search_documents",
    "entities",
    "edges",
    "entity_facets",
    "overlay_links",
    "public_api_workflow_index",
    "permission_surface_index",
)


class ImportPipelineBackend(Protocol):
    def delete_export_scoped_rows(self, table: str, export_id: str) -> None: ...
    def upsert_rows(self, table: str, rows: list[dict[str, Any]]) -> None: ...
    def update_export(self, export_id: str, **changes: Any) -> dict[str, Any]: ...


def build_bubble_export_evidence_row(
    *,
    export_id: str,
    app_slug: str,
    version_label: str,
    export_path: Path,
    source_export_hash: str,
) -> dict[str, Any]:
    storage_object_path = f"{app_slug}/{version_label}/bubble-export.json"
    return {
        "export_id": export_id,
        "evidence_role": "bubble_export",
        "storage_bucket": LOCAL_ONLY_EVIDENCE_BUCKET,
        "storage_object_path": storage_object_path,
        "content_hash": source_export_hash,
        "source_path": str(export_path),
        "metadata_json": {
            "canonical": True,
            "evidence_location": EVIDENCE_LOCATION_LOCAL_ONLY,
            "logical_storage_object_path": storage_object_path,
            "source_export_path": str(export_path),
            "source_export_file_name": export_path.name,
            "source_export_size_bytes": export_path.stat().st_size,
        },
    }


def build_local_graph_verification_metadata(
    *,
    existing_metadata: dict[str, Any],
    graph_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        **existing_metadata,
        "verification": {
            "status": "passed",
            "source": "specitout_graph_load",
            "failed_checks": [],
            "summary": graph_summary,
        },
    }


def start_initial_import_pipeline(
    backend: ImportPipelineBackend,
    *,
    app: dict[str, Any],
    export: dict[str, Any],
    export_path: Path,
    source_export_hash: str,
    progress_reporter: ImportProgressReporter | None = None,
) -> dict[str, Any]:
    export_id = str(export["id"])
    total_stages = len(PIPELINE_STAGES)
    pipeline_run = start_pipeline_run(
        backend,
        app_id=str(app["id"]),
        export_id=export_id,
        pipeline_kind=IMPORT_PIPELINE_KIND,
        stage_names=list(PIPELINE_STAGES),
        summary_json={
            "next_stage": "graph_normalization",
            "source_export_hash": source_export_hash,
        },
    )
    try:
        _report_progress(progress_reporter, "export_registration", 1, total_stages, "registering export metadata")
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="export_registration",
            stage_index=1,
            status_message="registered export metadata",
        )
        record_phase_checkpoint(
            backend,
            export_id=export_id,
            phase="registration",
            import_mode=IMPORT_MODE,
            pipeline_run_id=str(pipeline_run["id"]),
            progress_current=1,
            progress_total=len(PIPELINE_STAGES),
            progress_unit="stage",
            status_message="registered export metadata",
            current_item_key=f"export:{export_id}",
            stats_json={"registered_export": True},
        )
        record_phase(
            backend,
            export_id=export_id,
            phase="registration",
            import_mode=IMPORT_MODE,
            status="succeeded",
            pipeline_run_id=str(pipeline_run["id"]),
            progress_current=1,
            progress_total=len(PIPELINE_STAGES),
            progress_unit="stage",
            status_message="registered export metadata",
            current_item_key=f"export:{export_id}",
            stats_json={"registered_export": True},
        )

        _report_progress(progress_reporter, "source_evidence_persistence", 2, total_stages, "persisting local export evidence")
        evidence_row = build_bubble_export_evidence_row(
            export_id=export_id,
            app_slug=str(app["slug"]),
            version_label=str(export["version_label"]),
            export_path=export_path,
            source_export_hash=source_export_hash,
        )
        backend.upsert_rows("source_evidence", [evidence_row])
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="source_evidence_persistence",
            stage_index=2,
            status_message="persisted local export evidence",
            summary_updates={"source_evidence_count": 1},
        )
        record_phase_checkpoint(
            backend,
            export_id=export_id,
            phase="artifact_upload",
            import_mode=IMPORT_MODE,
            pipeline_run_id=str(pipeline_run["id"]),
            progress_current=2,
            progress_total=len(PIPELINE_STAGES),
            progress_unit="stage",
            status_message="persisted local export evidence",
            current_item_key=f"source_evidence:{evidence_row['evidence_role']}",
            stats_json={"source_evidence": 1},
        )
        record_phase(
            backend,
            export_id=export_id,
            phase="artifact_upload",
            import_mode=IMPORT_MODE,
            status="succeeded",
            pipeline_run_id=str(pipeline_run["id"]),
            progress_current=2,
            progress_total=len(PIPELINE_STAGES),
            progress_unit="stage",
            status_message="persisted local export evidence",
            current_item_key=f"source_evidence:{evidence_row['evidence_role']}",
            stats_json={"source_evidence": 1},
        )
        updated_export = backend.update_export(export_id, readiness_status="ingesting", failure_reason=None)

        _report_progress(progress_reporter, "parse_export_payload", 3, total_stages, "parsing raw Bubble export payload")
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="parse_export_payload",
            stage_index=3,
            status_message="waiting to parse raw bubble export payload",
        )
        record_phase_checkpoint(
            backend,
            export_id=export_id,
            phase="graph_load",
            import_mode=IMPORT_MODE,
            pipeline_run_id=str(pipeline_run["id"]),
            progress_current=3,
            progress_total=len(PIPELINE_STAGES),
            progress_unit="stage",
            status_message="waiting to parse raw bubble export payload",
            current_item_key=f"export:{export_id}",
            stats_json={"source_export_hash": source_export_hash},
        )

        _report_progress(progress_reporter, "context_pack_build", 4, total_stages, "building temporary context pack")
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="context_pack_build",
            stage_index=4,
            status_message="building temporary context pack",
        )
        graph = build_normalized_import_graph(
            export_id=export_id,
            app_slug=str(app["slug"]),
            version_label=str(export["version_label"]),
            export_path=export_path,
            source_export_hash=source_export_hash,
            progress_reporter=progress_reporter,
        )

        _report_progress(progress_reporter, "graph_normalization", 5, total_stages, "normalizing graph rows")
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="graph_normalization",
            stage_index=5,
            status_message="normalized graph rows",
            summary_updates=graph.summary(),
        )
        record_phase_checkpoint(
            backend,
            export_id=export_id,
            phase="graph_load",
            import_mode=IMPORT_MODE,
            pipeline_run_id=str(pipeline_run["id"]),
            progress_current=5,
            progress_total=len(PIPELINE_STAGES),
            progress_unit="stage",
            status_message="normalized graph rows",
            current_item_key=f"export:{export_id}",
            stats_json=graph.summary(),
        )

        for table in GRAPH_TABLES:
            _report_progress(progress_reporter, "graph_load.clear", 0, 0, f"clearing prior {table} rows; unit=rows count=unknown")
            with progress_scope(progress_reporter):
                backend.delete_export_scoped_rows(table, export_id)

        _report_progress(progress_reporter, "graph_load", 6, total_stages, "loading normalized graph rows")
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="graph_load",
            stage_index=6,
            status_message="loading normalized graph rows",
        )
        for table, rows in (
            ("entities", graph.entities),
            ("edges", graph.edges),
            ("entity_facets", graph.entity_facets),
            ("overlay_links", graph.overlay_links),
            ("public_api_workflow_index", graph.public_api_workflow_index),
            ("permission_surface_index", graph.permission_surface_index),
        ):
            rows = prepare_rows_for_upsert(table, rows)
            _report_progress(progress_reporter, f"graph_load.{table}", 0, len(rows), f"loading {len(rows)} {table} rows; unit=rows")
            with progress_scope(progress_reporter):
                backend.upsert_rows(table, rows)
            _report_progress(progress_reporter, f"graph_load.{table}", len(rows), len(rows), f"loaded {len(rows)} {table} rows; unit=rows")
        record_phase(
            backend,
            export_id=export_id,
            phase="graph_load",
            import_mode=IMPORT_MODE,
            status="succeeded",
            pipeline_run_id=str(pipeline_run["id"]),
            progress_current=6,
            progress_total=len(PIPELINE_STAGES),
            progress_unit="stage",
            status_message="loaded normalized graph rows",
            current_item_key=f"export:{export_id}",
            stats_json=graph.summary(),
        )

        updated_export = backend.update_export(
            export_id,
            metadata_json=build_local_graph_verification_metadata(
                existing_metadata=dict(updated_export.get("metadata_json") or {}),
                graph_summary=graph.summary(),
            ),
        )
        _report_progress(progress_reporter, "pipeline_tracking_ready", 7, total_stages, "recording import pipeline completion")
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="pipeline_tracking_ready",
            stage_index=7,
            status="succeeded",
            status_message="ready for search_document_generation",
            summary_updates={
                **graph.summary(),
                "next_stage": "search_document_generation",
            },
        )
        return {
            "export": updated_export,
            "pipeline_run": pipeline_run,
            "source_evidence": [evidence_row],
        }
    except Exception as exc:
        backend.update_export(export_id, readiness_status="failed", failure_reason=str(exc))
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage=str(pipeline_run.get("current_stage") or "pipeline_tracking_ready"),
            stage_index=int(pipeline_run.get("stage_index") or 0),
            status="failed",
            status_message=f"import failed: {exc}",
            error_json={"message": str(exc)},
        )
        record_phase(
            backend,
            export_id=export_id,
            phase="graph_load",
            import_mode=IMPORT_MODE,
            status="failed",
            pipeline_run_id=str(pipeline_run["id"]),
            progress_current=int(pipeline_run.get("stage_index") or 0),
            progress_total=len(PIPELINE_STAGES),
            progress_unit="stage",
            status_message=f"import failed: {exc}",
            current_item_key=f"export:{export_id}",
            error_json={"message": str(exc)},
        )
        raise


def _report_progress(
    progress_reporter: ImportProgressReporter | None,
    stage: str,
    current: int,
    total: int,
    message: str,
) -> None:
    if progress_reporter is not None:
        progress_reporter(stage, current, total, f"{message}; unit=import_stages" if stage in PIPELINE_STAGES else message)
