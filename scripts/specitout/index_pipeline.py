from __future__ import annotations

from argparse import Namespace
from typing import Any

from bubble_ingestion.embedding_index import build_embeddings_with_backend
from bubble_ingestion.errors import IngestionError
from bubble_ingestion.pipeline_runs import start_pipeline_run, update_pipeline_run
from bubble_ingestion.search_index import build_search_documents_with_backend
from specitout.embedding_provider import EmbeddingProvider
from specitout.progress import IndexProgressReporter
from specitout.runtime import SpecItOutRuntimeError

INDEX_REBUILD_PIPELINE_KIND = "specitout_index_rebuild"
INDEX_REBUILD_STAGES = [
    "search_document_generation",
    "embedding_generation",
    "readiness_verification",
]


def run_index_rebuild_pipeline(
    backend: object,
    *,
    app_slug: str,
    version_label: str,
    embedding_provider: EmbeddingProvider,
    embedding_limit: int | None = None,
    progress_reporter: IndexProgressReporter | None = None,
) -> dict[str, Any]:
    app = backend.get_app(app_slug=app_slug)
    if app is None:
        raise SpecItOutRuntimeError(f"Unknown application scope {app_slug}.")
    export = backend.get_export(app_id=str(app["id"]), version_label=version_label)
    if export is None:
        raise SpecItOutRuntimeError(f"Unknown export version {version_label} for application scope {app_slug}.")

    pipeline_run = start_pipeline_run(
        backend,
        app_id=str(app["id"]),
        export_id=str(export["id"]),
        pipeline_kind=INDEX_REBUILD_PIPELINE_KIND,
        stage_names=INDEX_REBUILD_STAGES,
        summary_json={"app_slug": app_slug, "version_label": version_label},
    )
    args = Namespace(app_slug=app_slug, version_label=version_label, limit=embedding_limit)
    search_summary: dict[str, Any] | None = None
    embedding_summary: dict[str, Any] | None = None
    try:
        _report_progress(progress_reporter, "search_document_generation", 1, len(INDEX_REBUILD_STAGES), "building search documents")
        if str(export.get("readiness_status") or "") == "embedding_pending":
            _report_progress(progress_reporter, "search_document_generation", 1, len(INDEX_REBUILD_STAGES), "reusing committed search documents for embedding resume")
            search_summary = {
                "app_id": app["id"],
                "export_id": export["id"],
                "readiness_status": export["readiness_status"],
                "lifecycle_status": export["lifecycle_status"],
                "stats": {},
            }
        else:
            search_summary = build_search_documents_with_backend(args, backend, allow_cutover=False)
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="search_document_generation",
            stage_index=1,
            status_message="search documents generated",
            summary_updates={"search_document_generation": "succeeded"},
        )

        _report_progress(progress_reporter, "embedding_generation", 2, len(INDEX_REBUILD_STAGES), "generating local embeddings")
        embedding_summary = build_embeddings_with_backend(
            args,
            backend,
            embedding_provider=embedding_provider,
            allow_cutover=False,
            progress_reporter=progress_reporter,
        )
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="embedding_generation",
            stage_index=2,
            status_message="embeddings generated",
            summary_updates={"embedding_generation": "succeeded"},
        )

        _report_progress(progress_reporter, "readiness_verification", 3, len(INDEX_REBUILD_STAGES), "verifying searchable export readiness")
        stats = {
            **dict(search_summary.get("stats") or {}),
            **dict(embedding_summary.get("stats") or {}),
        }
        pipeline_run = update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="readiness_verification",
            stage_index=3,
            status="succeeded",
            status_message="index ready",
            summary_updates={"readiness_verification": "succeeded", "stats": stats},
        )
        return {
            "app_slug": app_slug,
            "version_label": version_label,
            "pipeline_run": pipeline_run,
            "stats": stats,
            **embedding_summary,
        }
    except IngestionError as exc:
        update_pipeline_run(
            backend,
            pipeline_run=pipeline_run,
            current_stage="embedding_generation" if search_summary is not None else "search_document_generation",
            stage_index=2 if search_summary is not None else 1,
            status="failed",
            status_message=str(exc),
            error_json={"message": str(exc)},
        )
        backend.get_export(app_id=str(app["id"]), version_label=version_label)
        raise SpecItOutRuntimeError(str(exc)) from exc


def _report_progress(
    progress_reporter: IndexProgressReporter | None,
    stage: str,
    current: int,
    total: int,
    message: str,
) -> None:
    if progress_reporter is not None:
        progress_reporter(stage, current, total, f"{message}; unit=index_stages")
