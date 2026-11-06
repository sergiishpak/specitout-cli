from __future__ import annotations

import argparse
from typing import Any

from specitout.progress import report_active
from bubble_ingestion.backend_protocol import BackendProtocol
from bubble_ingestion.errors import IngestionError
from bubble_ingestion.ingestion_runs import record_phase
from bubble_ingestion.search_document_drafts import (
    build_local_semantic_indexes,
    build_relational_semantic_indexes,
    build_search_documents,
    decode_semantic_index_bytes,
)
from bubble_ingestion.verification import (
    failure_readiness_status,
    has_passed_verification,
    should_cutover_replacement_export,
)


SEARCH_DOCUMENT_PHASE = "search_document_generation"
ALLOWED_READINESS = frozenset({"ingesting", "searchable", "embedding_pending", "ready", "degraded"})


def _load_preserved_semantic_indexes(backend: BackendProtocol, export_id: str) -> dict[str, dict[str, Any]]:
    indexes: dict[str, dict[str, Any]] = {}
    for row in backend.list_source_evidence_rows(export_id=export_id):
        if row.get("evidence_role") != "semantic_index":
            continue
        metadata = dict(row.get("metadata_json") or {})
        index_name = metadata.get("index_name")
        if index_name not in {"permission_surface_index", "data_api_surface"}:
            continue
        inline_payload = metadata.get("inline_payload_json")
        if inline_payload is not None:
            indexes[str(index_name)] = dict(inline_payload)
            continue
        if metadata.get("evidence_location") == "local_only":
            continue
        payload = backend.download_object(
            bucket=str(row["storage_bucket"]),
            object_path=str(row["storage_object_path"]),
        )
        indexes[str(index_name)] = decode_semantic_index_bytes(payload)
    return indexes


def _next_readiness_status_after_rebuild(current_readiness_status: str | None) -> str:
    if current_readiness_status == "ingesting":
        return "searchable"
    if current_readiness_status == "ready":
        return "embedding_pending"
    if current_readiness_status == "degraded":
        return "searchable"
    return str(current_readiness_status)


def build_search_documents_with_backend(
    args: argparse.Namespace,
    backend: BackendProtocol,
    *,
    allow_cutover: bool = False,
) -> dict[str, Any]:
    app = backend.get_app(app_slug=args.app_slug)
    if app is None:
        raise IngestionError(f"Unknown app_slug {args.app_slug}")
    export = backend.get_export(app_id=str(app["id"]), version_label=args.version_label)
    if export is None:
        raise IngestionError(f"Unknown export version_label {args.version_label} for app_slug {args.app_slug}")
    if not has_passed_verification(export):
        raise IngestionError("build-search-documents requires a verification-passed export")
    if export.get("readiness_status") not in ALLOWED_READINESS:
        raise IngestionError(
            "build-search-documents only supports exports in ingesting, searchable, embedding_pending, ready, or degraded readiness"
        )

    record_phase(
        backend,
        export_id=str(export["id"]),
        phase=SEARCH_DOCUMENT_PHASE,
        import_mode=str(export.get("import_mode") or "append_new_version"),
        status="running",
    )
    try:
        report_active("search_document_inputs", 0, 0, "loading entity inputs; unit=rows count=unknown")
        entity_rows = backend.list_export_rows(table="entities", export_id=str(export["id"]))
        public_api_rows = backend.list_export_rows(table="public_api_workflow_index", export_id=str(export["id"]))
        permission_surface_rows = backend.list_export_rows(table="permission_surface_index", export_id=str(export["id"]))
        report_active("search_document_semantics", len(entity_rows), len(entity_rows), f"loaded {len(entity_rows)} entity rows; building semantic indexes; unit=input_rows")
        semantic_indexes = build_relational_semantic_indexes(
            entity_rows=entity_rows,
            public_api_rows=public_api_rows,
            permission_surface_rows=permission_surface_rows,
        )
        preserved_semantic_indexes = _load_preserved_semantic_indexes(backend, str(export["id"]))
        if not semantic_indexes["permission_surface_index"]["user_types"]:
            preserved_permission_surface = preserved_semantic_indexes.get("permission_surface_index")
            if preserved_permission_surface is not None:
                semantic_indexes["permission_surface_index"] = preserved_permission_surface
        if (
            not semantic_indexes["data_api_surface"].get("exposes_get_api")
            and not semantic_indexes["data_api_surface"].get("exposes_wf_api")
        ):
            preserved_data_api_surface = preserved_semantic_indexes.get("data_api_surface")
            if preserved_data_api_surface is not None:
                semantic_indexes["data_api_surface"] = preserved_data_api_surface
        report_active("search_document_drafts", 0, 0, "processing search document drafts; unit=documents count=unknown")
        drafts = build_search_documents(
            export_id=str(export["id"]),
            entity_rows=entity_rows,
            public_api_rows=public_api_rows,
            semantic_indexes=semantic_indexes,
        )
        if not drafts:
            raise IngestionError("build-search-documents generated zero search documents")

        document_rows = [draft.document for draft in drafts]
        association_rows = [assoc for draft in drafts for assoc in draft.associations]
        report_active("search_document_write", 0, len(document_rows), f"generated {len(document_rows)} documents and {len(association_rows)} associations; waiting to write; unit=documents")
        backend.replace_search_documents(export_id=str(export["id"]), documents=document_rows, associations=association_rows)

        report_active("search_document_readiness", 0, 0, "document transaction committed; updating export readiness")
        next_readiness_status = _next_readiness_status_after_rebuild(str(export.get("readiness_status")))
        export = backend.update_export(str(export["id"]), readiness_status=next_readiness_status, failure_reason=None)
        active_cutover_performed = False
        if allow_cutover and export.get("lifecycle_status") == "candidate" and should_cutover_replacement_export(
            export=export,
            import_mode=str(export.get("import_mode") or ""),
            verification_status="passed",
        ):
            export = backend.cutover_replace_active_export(app_id=str(app["id"]), replacement_export_id=str(export["id"]))
            active_cutover_performed = True

        record_phase(
            backend,
            export_id=str(export["id"]),
            phase=SEARCH_DOCUMENT_PHASE,
            import_mode=str(export.get("import_mode") or "append_new_version"),
            status="succeeded",
            stats_json={"search_documents": len(document_rows), "search_document_associations": len(association_rows)},
        )
        return {
            "app_id": app["id"],
            "export_id": export["id"],
            "readiness_status": export["readiness_status"],
            "lifecycle_status": export["lifecycle_status"],
            "active_cutover_performed": active_cutover_performed,
            "stats": {"search_documents": len(document_rows), "search_document_associations": len(association_rows)},
        }
    except Exception as exc:
        export = backend.update_export(
            str(export["id"]),
            readiness_status=failure_readiness_status(str(export.get("readiness_status"))),
            failure_reason=str(exc),
        )
        record_phase(
            backend,
            export_id=str(export["id"]),
            phase=SEARCH_DOCUMENT_PHASE,
            import_mode=str(export.get("import_mode") or "append_new_version"),
            status="failed",
            error_json={"message": str(exc)},
        )
        raise IngestionError(str(exc)) from exc
