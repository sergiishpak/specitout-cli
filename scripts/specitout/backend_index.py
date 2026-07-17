from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from bubble_ingestion.errors import IngestionError
from specitout.embedding_provider import EmbeddingProvider
from specitout.index_pipeline import run_index_rebuild_pipeline
from specitout.progress import IndexProgressReporter
from specitout.runtime import SpecItOutRuntimeError

FetchAll = Callable[[str, Mapping[str, object] | None], list[dict[str, object]]]
FetchOne = Callable[[str, Mapping[str, object] | None], dict[str, object] | None]

EXPORT_ROW_TABLES = frozenset(
    {
        "entities",
        "public_api_workflow_index",
        "permission_surface_index",
        "search_documents",
    }
)
EXPORT_ROW_ORDERINGS = {
    "entities": "entity_key asc",
    "public_api_workflow_index": "entity_key asc, workflow_name asc",
    "permission_surface_index": "entity_key asc",
    "search_documents": "document_key asc",
}
SEARCH_DOCUMENT_BATCH_SIZE = 1000


def get_app(*, fetch_one: FetchOne, app_slug: str) -> dict[str, object] | None:
    return fetch_one(
        """
select *
from specitout.apps
where slug = %(app_slug)s
limit 1
""",
        {"app_slug": app_slug},
    )


def get_export(*, fetch_one: FetchOne, app_id: str, version_label: str) -> dict[str, object] | None:
    return fetch_one(
        """
select
  id,
  app_id,
  version_label,
  readiness_status::text as readiness_status,
  lifecycle_status::text as lifecycle_status,
  supersedes_export_id,
  source_export_hash,
  registered_at,
  import_mode,
  metadata_json,
  failure_reason
from specitout.exports
where app_id = %(app_id)s and version_label = %(version_label)s
limit 1
""",
        {"app_id": app_id, "version_label": version_label},
    )


def get_embedding_stats(*, fetch_one: FetchOne, export_id: str) -> dict[str, object]:
    row = fetch_one(
        """
select
  count(*) filter (
    where embedding is not null
      and embedding_model is not null
      and embedding_dimensions is not null
      and embedded_at is not null
  ) as embedded_documents,
  count(*) filter (
    where embedding is null
      or embedding_model is null
      or embedding_dimensions is null
      or embedded_at is null
  ) as remaining_documents,
  count(*) as total_documents
from specitout.search_documents
where export_id = %(export_id)s
""",
        {"export_id": export_id},
    )
    return {
        "embedded_documents": int((row or {}).get("embedded_documents") or 0),
        "remaining_documents": int((row or {}).get("remaining_documents") or 0),
        "total_documents": int((row or {}).get("total_documents") or 0),
    }


def count_search_documents(*, fetch_one: FetchOne, export_id: str) -> int:
    row = fetch_one(
        """
select count(*) as total_documents
from specitout.search_documents
where export_id = %(export_id)s
""",
        {"export_id": export_id},
    )
    return int((row or {}).get("total_documents") or 0)


def count_pending_search_document_embeddings(*, fetch_one: FetchOne, export_id: str) -> int:
    row = fetch_one(
        """
select count(*) as remaining_documents
from specitout.search_documents
where export_id = %(export_id)s
  and (
    embedding is null
    or embedding_model is null
    or embedding_dimensions is null
    or embedded_at is null
  )
""",
        {"export_id": export_id},
    )
    return int((row or {}).get("remaining_documents") or 0)


def list_pending_search_document_embedding_inputs(
    *,
    fetch_all: FetchAll,
    export_id: str,
    limit: int,
    offset: int | None = None,
) -> list[dict[str, object]]:
    return fetch_all(
        """
select id, semantic_text
from specitout.search_documents
where export_id = %(export_id)s
  and (
    embedding is null
    or embedding_model is null
    or embedding_dimensions is null
    or embedded_at is null
  )
order by document_key asc
limit %(limit)s
offset %(offset)s
""",
        {"export_id": export_id, "limit": limit, "offset": offset or 0},
    )


def list_export_rows(*, fetch_all: FetchAll, table: str, export_id: str) -> list[dict[str, object]]:
    if table not in EXPORT_ROW_TABLES:
        raise SpecItOutRuntimeError(f"Unsupported export row table for index rebuild: {table}")
    ordering = EXPORT_ROW_ORDERINGS[table]
    return fetch_all(
        f"""
select *
from specitout.{table}
where export_id = %(export_id)s
order by {ordering}
""",
        {"export_id": export_id},
    )


def list_source_evidence_rows(*, fetch_all: FetchAll, export_id: str) -> list[dict[str, object]]:
    return fetch_all(
        """
select *
from specitout.source_evidence
where export_id = %(export_id)s
order by evidence_role asc, storage_bucket asc, storage_object_path asc
""",
        {"export_id": export_id},
    )


def replace_search_documents(
    *,
    connect: Callable[[], object],
    export_id: str,
    documents: list[dict[str, Any]],
    associations: list[dict[str, Any]],
) -> None:
    documents = _dedupe_search_documents(documents)
    document_ids = {str(document["id"]) for document in documents}
    associations = [
        association
        for association in associations
        if str(association["search_document_id"]) in document_ids
    ]
    associations_by_document_id: dict[str, list[dict[str, Any]]] = {}
    for association in associations:
        associations_by_document_id.setdefault(str(association["search_document_id"]), []).append(association)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select specitout.clear_export_search_documents(%s)", (export_id,))
        for document_batch in _batched(documents, SEARCH_DOCUMENT_BATCH_SIZE):
            document_ids = {str(document["id"]) for document in document_batch}
            association_batch = [
                association
                for document_id in document_ids
                for association in associations_by_document_id.get(document_id, [])
            ]
            cur.execute(
                "select specitout.append_export_search_documents_batch(%s, %s, %s)",
                (export_id, _jsonb(document_batch), _jsonb(association_batch)),
            )


def _dedupe_search_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for document in documents:
        key = (str(document["export_id"]), str(document["document_key"]))
        if key in deduped:
            del deduped[key]
        deduped[key] = document
    return list(deduped.values())


def persist_search_document_embeddings(
    *,
    connect: Callable[[], object],
    export_id: str,
    embeddings: list[dict[str, Any]],
) -> None:
    with connect() as conn, conn.cursor() as cur:
        for batch in _batched(embeddings, SEARCH_DOCUMENT_BATCH_SIZE):
            cur.execute(
                "select specitout.persist_search_document_embeddings(%s, %s)",
                (export_id, _jsonb(batch)),
            )


def rebuild_index(
    backend: object,
    *,
    app_slug: str,
    version_label: str,
    embedding_provider: EmbeddingProvider,
    embedding_limit: int | None = None,
    progress_reporter: IndexProgressReporter | None = None,
) -> dict[str, object]:
    try:
        return run_index_rebuild_pipeline(
            backend,
            app_slug=app_slug,
            version_label=version_label,
            embedding_provider=embedding_provider,
            embedding_limit=embedding_limit,
            progress_reporter=progress_reporter,
        )
    except IngestionError as exc:
        raise SpecItOutRuntimeError(str(exc)) from exc


def download_object(*, bucket: str, object_path: str) -> bytes:
    raise SpecItOutRuntimeError(
        "SpecItOut local index rebuild cannot download remote evidence objects yet; "
        f"encountered {bucket}/{object_path}."
    )


def _jsonb(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError as exc:
        raise SpecItOutRuntimeError("psycopg is required for runtime-backed SpecItOut index rebuilds.") from exc
    return Jsonb(_json_ready(value))


def _json_ready(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def _batched(rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + batch_size] for index in range(0, len(rows), batch_size)]
