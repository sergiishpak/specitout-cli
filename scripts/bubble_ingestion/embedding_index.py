from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from bubble_ingestion.backend_protocol import BackendProtocol
from bubble_ingestion.errors import IngestionError
from bubble_ingestion.ingestion_runs import record_phase, record_phase_checkpoint
from bubble_ingestion.verification import has_passed_verification, should_cutover_replacement_export
from specitout.embedding_provider import EmbeddingProvider


EMBEDDING_PHASE = "embedding_generation"
ALLOWED_READINESS = frozenset({"searchable", "embedding_pending", "ready", "degraded"})
INDEXED_EMBEDDING_DIMENSIONS = 1536
TRANSIENT_TRANSPORT_ERROR_MARKERS = ("broken pipe", "bad record mac", "eof occurred in violation of protocol", "connection reset by peer", "tlsv1 alert", "sslv3_alert")


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str
    base_url: str
    model: str
    dimensions: int | None
    batch_size: int
    timeout_seconds: float
    max_attempts: int
    backoff_seconds: float


def _load_config_from_env() -> EmbeddingConfig:
    api_key = os.getenv("SPECITOUT_OPENAI_API_KEY")
    if not api_key:
        raise IngestionError("Missing SPECITOUT_OPENAI_API_KEY")

    dimensions_raw = os.getenv("SPECITOUT_OPENAI_EMBEDDING_DIMENSIONS")
    dimensions = None
    if dimensions_raw:
        dimensions = int(dimensions_raw)
        if dimensions <= 0:
            raise IngestionError("SPECITOUT_OPENAI_EMBEDDING_DIMENSIONS must be a positive integer")
        if dimensions != INDEXED_EMBEDDING_DIMENSIONS:
            raise IngestionError(
                "SPECITOUT_OPENAI_EMBEDDING_DIMENSIONS must be unset or 1536 until the pgvector index supports other dimensions"
            )

    batch_size = int(os.getenv("SPECITOUT_OPENAI_EMBEDDING_BATCH_SIZE", "32"))
    if batch_size <= 0:
        raise IngestionError("SPECITOUT_OPENAI_EMBEDDING_BATCH_SIZE must be a positive integer")
    timeout_seconds = float(os.getenv("SPECITOUT_OPENAI_EMBEDDING_TIMEOUT_SECONDS", "60"))
    if timeout_seconds <= 0:
        raise IngestionError("SPECITOUT_OPENAI_EMBEDDING_TIMEOUT_SECONDS must be a positive number")
    max_attempts = int(os.getenv("SPECITOUT_OPENAI_EMBEDDING_MAX_ATTEMPTS", "6"))
    if max_attempts <= 0:
        raise IngestionError("SPECITOUT_OPENAI_EMBEDDING_MAX_ATTEMPTS must be a positive integer")
    backoff_seconds = float(os.getenv("SPECITOUT_OPENAI_EMBEDDING_BACKOFF_SECONDS", "1.0"))
    if backoff_seconds <= 0:
        raise IngestionError("SPECITOUT_OPENAI_EMBEDDING_BACKOFF_SECONDS must be a positive number")

    return EmbeddingConfig(
        api_key=api_key,
        base_url=os.getenv("SPECITOUT_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        model=os.getenv("SPECITOUT_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        dimensions=dimensions,
        batch_size=batch_size,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )


def _documents_requiring_embeddings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("embedding") is None
        or not row.get("embedding_model")
        or not row.get("embedding_dimensions")
        or not row.get("embedded_at")
    ]


def _embedding_source_text(row: dict[str, Any]) -> str:
    text = str(row.get("semantic_text") or "").strip()
    if not text:
        raise IngestionError("search document semantic_text cannot be empty when building embeddings")
    return text


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _retryable_http_status(status_code: int) -> bool:
    return status_code in {408, 409, 429} or status_code >= 500


def _retryable_transport_exception(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(needle in message for needle in TRANSIENT_TRANSPORT_ERROR_MARKERS)


def _retry_delay_seconds(*, attempt: int, config: EmbeddingConfig) -> float:
    return min(config.backoff_seconds * (2 ** max(attempt - 1, 0)), 16.0)


def _request_embeddings(
    *,
    texts: list[str],
    config: EmbeddingConfig,
) -> tuple[list[list[float]], str | None]:
    normalized_texts = [str(text) for text in texts]
    if not normalized_texts:
        raise IngestionError("OpenAI embeddings input cannot be empty")
    if any(not text.strip() for text in normalized_texts):
        raise IngestionError("OpenAI embeddings input cannot be empty or whitespace")

    payload: dict[str, Any] = {"input": normalized_texts, "model": config.model}
    if config.dimensions is not None:
        payload["dimensions"] = config.dimensions
    request = urllib.request.Request(
        url=f"{config.base_url}/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    raw = b""
    request_id = None
    for attempt in range(1, config.max_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                raw = response.read()
                request_id = response.headers.get("x-request-id")
                break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = f"OpenAI embeddings request failed with {exc.code}: {detail}"
            if attempt >= config.max_attempts or not _retryable_http_status(exc.code):
                raise IngestionError(message) from exc
            time.sleep(_retry_delay_seconds(attempt=attempt, config=config))
        except Exception as exc:  # pragma: no cover - exercised via tests with synthetic exceptions
            if attempt >= config.max_attempts or not _retryable_transport_exception(exc):
                raise IngestionError(str(exc)) from exc
            time.sleep(_retry_delay_seconds(attempt=attempt, config=config))

    decoded = json.loads(raw.decode("utf-8"))
    data = list(decoded.get("data") or [])
    ordered = sorted(data, key=lambda item: int(item["index"]))
    embeddings = [list(item["embedding"]) for item in ordered]
    if len(embeddings) != len(texts):
        raise IngestionError("OpenAI embeddings response count did not match the submitted inputs")
    return embeddings, request_id


def _expected_embedding_dimensions(config: EmbeddingConfig) -> int:
    return config.dimensions or INDEXED_EMBEDDING_DIMENSIONS


def _validate_embedding_dimensions(*, embeddings: list[list[float]], config: EmbeddingConfig) -> None:
    expected_dimensions = _expected_embedding_dimensions(config)
    for embedding in embeddings:
        if len(embedding) != expected_dimensions:
            raise IngestionError(
                f"OpenAI embeddings response dimensions must be {expected_dimensions} to match the pgvector index"
            )


def _failure_status(current_readiness: str) -> str:
    if current_readiness in {"ready", "degraded"}:
        return "degraded"
    return "embedding_pending"


def _missing_embedding_error_message() -> str:
    return "build-embeddings cannot mark export ready while search_documents are still missing embeddings"


def _is_embedding_pending_transition_conflict(exc: Exception) -> bool:
    message = str(exc)
    return "illegal export readiness transition" in message and "embedding_pending" in message


def _requested_limit(args: argparse.Namespace) -> int | None:
    raw_limit = getattr(args, "limit", None)
    if raw_limit is None:
        return None
    limit = int(raw_limit)
    if limit <= 0:
        raise IngestionError("build-embeddings --limit must be a positive integer")
    return limit


def _count_search_documents(backend: BackendProtocol, *, export_id: str) -> int:
    if hasattr(backend, "count_search_documents"):
        return backend.count_search_documents(export_id=export_id)
    if hasattr(backend, "count_export_rows"):
        return backend.count_export_rows(table="search_documents", export_id=export_id)
    return len(backend.list_export_rows(table="search_documents", export_id=export_id))


def _count_pending_search_document_embeddings(backend: BackendProtocol, *, export_id: str) -> int:
    if hasattr(backend, "count_pending_search_document_embeddings"):
        return backend.count_pending_search_document_embeddings(export_id=export_id)
    documents = backend.list_export_rows(table="search_documents", export_id=export_id)
    return len(_documents_requiring_embeddings(documents))


def _list_pending_embedding_inputs(
    backend: BackendProtocol,
    *,
    export_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    if hasattr(backend, "list_pending_search_document_embedding_inputs"):
        return backend.list_pending_search_document_embedding_inputs(export_id=export_id, limit=limit)
    documents = backend.list_export_rows(table="search_documents", export_id=export_id)
    return [
        {"id": row["id"], "semantic_text": row["semantic_text"]}
        for row in _documents_requiring_embeddings(documents)[:limit]
    ]


def build_embedding_payloads(
    document_rows: list[dict[str, Any]],
    *,
    limit: int | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pending = _documents_requiring_embeddings(document_rows)
    if limit is not None:
        if limit <= 0:
            raise IngestionError("embedding limit must be a positive integer")
        pending = pending[:limit]

    provider_request_ids: list[str] = []
    provider_requests = 0
    embedded_documents = 0
    embedding_rows: list[dict[str, Any]] = []
    if pending:
        if embedding_provider is not None:
            embeddings = embedding_provider.embed_documents([_embedding_source_text(row) for row in pending])
            timestamp = _utc_now_iso()
            return [
                {
                    "search_document_id": row["id"],
                    "embedding": embedding,
                    "embedding_model": embedding_provider.model_name,
                    "embedding_dimensions": embedding_provider.dimensions,
                    "embedded_at": timestamp,
                }
                for row, embedding in zip(pending, embeddings, strict=True)
            ], {
                "embedded_documents": len(pending),
                "remaining_documents": max(len(_documents_requiring_embeddings(document_rows)) - len(pending), 0),
                "provider_requests": 1,
                "provider_request_ids": [],
                "embedding_model": embedding_provider.model_name,
                "embedding_dimensions": embedding_provider.dimensions,
            }
        config = _load_config_from_env()
        for start in range(0, len(pending), config.batch_size):
            batch = pending[start : start + config.batch_size]
            texts = [_embedding_source_text(row) for row in batch]
            embeddings, request_id = _request_embeddings(texts=texts, config=config)
            _validate_embedding_dimensions(embeddings=embeddings, config=config)
            if request_id:
                provider_request_ids.append(request_id)
            provider_requests += 1
            embedded_documents += len(batch)
            timestamp = _utc_now_iso()
            embedding_rows.extend(
                {
                    "search_document_id": row["id"],
                    "embedding": embedding,
                    "embedding_model": config.model,
                    "embedding_dimensions": len(embedding),
                    "embedded_at": timestamp,
                }
                for row, embedding in zip(batch, embeddings, strict=True)
            )
        embedding_model = config.model
        embedding_dimensions = _expected_embedding_dimensions(config)
    else:
        embedding_model = None
        embedding_dimensions = None

    remaining_documents = max(len(_documents_requiring_embeddings(document_rows)) - embedded_documents, 0)
    return embedding_rows, {
        "embedded_documents": embedded_documents,
        "remaining_documents": remaining_documents,
        "provider_requests": provider_requests,
        "provider_request_ids": provider_request_ids,
        "embedding_model": embedding_model,
        "embedding_dimensions": embedding_dimensions,
    }


def build_embeddings_with_backend(
    args: argparse.Namespace,
    backend: BackendProtocol,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    allow_cutover: bool = True,
    progress_reporter: Callable[[str, int, int, str], None] | None = None,
) -> dict[str, Any]:
    app = backend.get_app(app_slug=args.app_slug)
    if app is None:
        raise IngestionError(f"Unknown app_slug {args.app_slug}")
    export = backend.get_export(app_id=str(app["id"]), version_label=args.version_label)
    if export is None:
        raise IngestionError(
            f"Unknown export version_label {args.version_label} for app_slug {args.app_slug}"
        )
    if not has_passed_verification(export):
        raise IngestionError("build-embeddings requires a verification-passed export")

    current_readiness = str(export.get("readiness_status") or "")
    if current_readiness not in ALLOWED_READINESS:
        raise IngestionError(
            "build-embeddings only supports exports in searchable, embedding_pending, ready, or degraded readiness"
        )

    record_phase(
        backend,
        export_id=str(export["id"]),
        phase=EMBEDDING_PHASE,
        import_mode=str(export.get("import_mode") or "append_new_version"),
        status="running",
    )

    try:
        export_id = str(export["id"])
        total_documents = _count_search_documents(backend, export_id=export_id)
        if total_documents == 0:
            raise IngestionError("build-embeddings requires search_documents for the target export")

        limit = _requested_limit(args)

        if current_readiness == "searchable":
            try:
                export = backend.update_export(export_id, readiness_status="embedding_pending", failure_reason=None)
                current_readiness = str(export["readiness_status"])
            except Exception as exc:
                refreshed_export = backend.get_export(app_id=str(app["id"]), version_label=args.version_label)
                refreshed_readiness = str(refreshed_export.get("readiness_status") or "") if refreshed_export else ""
                if (
                    refreshed_export is not None
                    and refreshed_readiness in {"embedding_pending", "ready", "degraded"}
                    and _is_embedding_pending_transition_conflict(exc)
                ):
                    export = refreshed_export
                    current_readiness = refreshed_readiness
                else:
                    raise

        pending_documents = _count_pending_search_document_embeddings(backend, export_id=export_id)
        progress_total = min(pending_documents, limit) if limit is not None else pending_documents
        provider_request_ids: list[str] = []
        provider_requests = 0
        embedded_documents = 0
        embedding_model = None
        embedding_dimensions = None
        if progress_reporter is not None:
            progress_reporter(EMBEDDING_PHASE, 0, progress_total, f"starting embedding pass; unit=pass_documents; overall_embedded={total_documents - pending_documents} overall_remaining={pending_documents} overall_total={total_documents}")
        if progress_total:
            config = None if embedding_provider is not None else _load_config_from_env()
            batch_size = embedding_provider.batch_size if embedding_provider is not None else config.batch_size
            while embedded_documents < progress_total:
                batch_limit = min(batch_size, progress_total - embedded_documents)
                batch = _list_pending_embedding_inputs(
                    backend,
                    export_id=export_id,
                    limit=batch_limit,
                )
                if not batch:
                    break
                if progress_reporter is not None:
                    progress_reporter(EMBEDDING_PHASE, embedded_documents, progress_total, f"processing next batch of {len(batch)} documents; unit=pass_documents; overall_committed={total_documents - pending_documents + embedded_documents}/{total_documents}")
                texts = [_embedding_source_text(row) for row in batch]
                if embedding_provider is not None:
                    embeddings = embedding_provider.embed_documents(texts)
                    request_id = None
                    embedding_model = embedding_provider.model_name
                    embedding_dimensions = embedding_provider.dimensions
                else:
                    assert config is not None
                    embeddings, request_id = _request_embeddings(texts=texts, config=config)
                    _validate_embedding_dimensions(embeddings=embeddings, config=config)
                    embedding_model = config.model
                    embedding_dimensions = _expected_embedding_dimensions(config)
                timestamp = _utc_now_iso()
                batch_rows = [
                    {
                        "search_document_id": row["id"],
                        "embedding": embedding,
                        "embedding_model": embedding_model,
                        "embedding_dimensions": len(embedding),
                        "embedded_at": timestamp,
                    }
                    for row, embedding in zip(batch, embeddings, strict=True)
                ]
                if batch_rows:
                    backend.persist_search_document_embeddings(
                        export_id=export_id,
                        embeddings=batch_rows,
                    )
                provider_requests += 1
                embedded_documents += len(batch)
                if request_id:
                    provider_request_ids.append(request_id)
                if progress_reporter is not None:
                    progress_reporter(
                        EMBEDDING_PHASE,
                        embedded_documents,
                        progress_total,
                        f"committed {embedded_documents}/{progress_total} embeddings this pass; unit=pass_documents; overall_committed={total_documents - pending_documents + embedded_documents}/{total_documents}",
                    )
                record_phase_checkpoint(
                    backend,
                    export_id=export_id,
                    phase=EMBEDDING_PHASE,
                    import_mode=str(export.get("import_mode") or "append_new_version"),
                    progress_current=embedded_documents,
                    progress_total=progress_total,
                    progress_unit="documents",
                    status_message=f"Embedded {embedded_documents}/{progress_total} search documents",
                    current_item_key=str(batch[-1]["id"]),
                    stats_json={
                        "embedded_documents": embedded_documents,
                        "provider_requests": provider_requests,
                        "provider_request_ids": provider_request_ids,
                        "embedding_model": embedding_model,
                        "embedding_dimensions": embedding_dimensions,
                    },
                )

        stats = {
            "embedded_documents": embedded_documents,
            "remaining_documents": 0,
            "provider_requests": provider_requests,
            "provider_request_ids": provider_request_ids,
            "embedding_model": embedding_model,
            "embedding_dimensions": embedding_dimensions,
        }

        if progress_reporter is not None:
            progress_reporter("embedding_verification", 0, 0, "waiting for final database embedding counts and readiness update")
        remaining_documents = _count_pending_search_document_embeddings(backend, export_id=export_id)
        if remaining_documents == 0:
            export = backend.update_export(export_id, readiness_status="ready", failure_reason=None)
        else:
            if limit is None:
                raise IngestionError(_missing_embedding_error_message())
            export = backend.update_export(export_id, readiness_status="embedding_pending", failure_reason=None)
        if allow_cutover and export.get("lifecycle_status") == "candidate" and should_cutover_replacement_export(
            export=export,
            import_mode=str(export.get("import_mode") or ""),
            verification_status="passed",
        ):
            export = backend.cutover_replace_active_export(
                app_id=str(app["id"]),
                replacement_export_id=str(export["id"]),
            )
        stats["remaining_documents"] = remaining_documents
        record_phase(
            backend,
            export_id=export_id,
            phase=EMBEDDING_PHASE,
            import_mode=str(export.get("import_mode") or "append_new_version"),
            status="succeeded",
            stats_json=stats,
        )
        return {
            "app_id": app["id"],
            "export_id": export["id"],
            "readiness_status": export["readiness_status"],
            "lifecycle_status": export["lifecycle_status"],
            "stats": stats,
        }
    except Exception as exc:
        export = backend.update_export(
            str(export["id"]),
            readiness_status=_failure_status(current_readiness),
            failure_reason=str(exc),
        )
        record_phase(
            backend,
            export_id=str(export["id"]),
            phase=EMBEDDING_PHASE,
            import_mode=str(export.get("import_mode") or "append_new_version"),
            status="failed",
            error_json={"message": str(exc)},
        )
        raise IngestionError(str(exc)) from exc
