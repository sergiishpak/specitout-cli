from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from specitout.backend_exact_answers import exact_search_answer
from specitout.backend_status import resolve_export_scope
from specitout.embedding_provider import EmbeddingProvider
from specitout.runtime import SpecItOutRuntimeError

FetchOne = Callable[[str, Mapping[str, object] | None], dict[str, object] | None]
GetApplication = Callable[[str], dict[str, object] | None]


def query_search(
    *,
    fetch_one: FetchOne,
    get_application: GetApplication,
    app_slug: str,
    query_text: str,
    version_label: str | None,
    export_id: str | None,
    mode: str,
    limit: int,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, object]:
    resolved_export_id = _resolve_export_id(
        fetch_one=fetch_one,
        get_application=get_application,
        app_slug=app_slug,
        version_label=version_label,
        export_id=export_id,
    )
    exact_answer = exact_search_answer(
        fetch_one=fetch_one,
        app_slug=app_slug,
        export_id=resolved_export_id,
        query_text=query_text,
    )
    if exact_answer is not None:
        return exact_answer
    query_embedding, embedding_warnings = _query_embedding(query_text, embedding_provider)
    payload = _fetch_jsonb(
        fetch_one,
        """
select specitout.search_entities(
  %(app_slug)s,
  %(query_text)s,
  %(mode)s,
  %(limit)s,
  %(export_id)s,
  %(query_embedding)s::extensions.vector,
  %(allow_archived_app)s
) as search_entities
""",
        {
            "app_slug": app_slug,
            "query_text": query_text,
            "mode": mode,
            "limit": limit,
            "export_id": resolved_export_id,
            "query_embedding": _vector_literal(query_embedding),
            "allow_archived_app": False,
        },
        "search_entities",
    )
    if embedding_warnings:
        payload["warnings"] = [*list(payload.get("warnings") or []), *embedding_warnings]
        payload["degraded"] = True
    return payload


def query_entity(
    *,
    fetch_one: FetchOne,
    get_application: GetApplication,
    app_slug: str,
    entity_lookup: str,
    version_label: str | None,
    export_id: str | None,
) -> dict[str, object]:
    return _fetch_jsonb(
        fetch_one,
        """
select specitout.get_entity(
  %(app_slug)s,
  %(entity_lookup)s,
  %(export_id)s,
  %(allow_archived_app)s
) as get_entity
""",
        {
            "app_slug": app_slug,
            "entity_lookup": entity_lookup,
            "export_id": _resolve_export_id(
                fetch_one=fetch_one,
                get_application=get_application,
                app_slug=app_slug,
                version_label=version_label,
                export_id=export_id,
            ),
            "allow_archived_app": False,
        },
        "get_entity",
    )


def query_usage(
    *,
    fetch_one: FetchOne,
    get_application: GetApplication,
    app_slug: str,
    entity_lookup: str,
    version_label: str | None,
    export_id: str | None,
    direction: str,
    relation: str | None,
    limit: int,
) -> dict[str, object]:
    entity_payload = query_entity(
        fetch_one=fetch_one,
        get_application=get_application,
        app_slug=app_slug,
        entity_lookup=entity_lookup,
        version_label=version_label,
        export_id=export_id,
    )
    _raise_if_target_lookup_failed(entity_payload, lookup=entity_lookup)
    entity = entity_payload.get("entity")
    if not isinstance(entity, Mapping) or not entity.get("entity_key"):
        raise SpecItOutRuntimeError(f"Entity lookup {entity_lookup} did not resolve to one entity.")
    resolved_export_id = export_id or _string_or_none(entity_payload.get("resolved_export_id"))
    return _fetch_jsonb(
        fetch_one,
        """
select specitout.get_neighbors(
  %(app_slug)s,
  %(entity_key)s,
  %(direction)s,
  %(relation)s,
  %(limit)s,
  %(export_id)s,
  %(allow_archived_app)s
) as get_neighbors
""",
        {
            "app_slug": app_slug,
            "entity_key": str(entity["entity_key"]),
            "direction": direction,
            "relation": relation,
            "limit": limit,
            "export_id": resolved_export_id,
            "allow_archived_app": False,
        },
        "get_neighbors",
    )


def query_paths(
    *,
    fetch_one: FetchOne,
    get_application: GetApplication,
    app_slug: str,
    from_lookup: str,
    to_lookup: str,
    version_label: str | None,
    export_id: str | None,
    direction: str,
    relation: str | None,
    max_hops: int,
    max_paths: int,
) -> dict[str, object]:
    return _fetch_jsonb(
        fetch_one,
        """
select specitout.find_paths(
  %(app_slug)s,
  %(from_lookup)s,
  %(to_lookup)s,
  %(direction)s,
  %(relation)s,
  %(max_hops)s,
  %(max_paths)s,
  %(export_id)s,
  %(allow_archived_app)s
) as find_paths
""",
        {
            "app_slug": app_slug,
            "from_lookup": from_lookup,
            "to_lookup": to_lookup,
            "direction": direction,
            "relation": relation,
            "max_hops": max_hops,
            "max_paths": max_paths,
            "export_id": _resolve_export_id(
                fetch_one=fetch_one,
                get_application=get_application,
                app_slug=app_slug,
                version_label=version_label,
                export_id=export_id,
            ),
            "allow_archived_app": False,
        },
        "find_paths",
    )


def build_context_bundle(
    *,
    fetch_one: FetchOne,
    get_application: GetApplication,
    app_slug: str,
    query_text: str | None,
    entity_key: str | None,
    version_label: str | None,
    export_id: str | None,
    mode: str,
    anchor_limit: int,
    max_hops: int,
    entity_limit: int,
    edge_limit: int,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, object]:
    query_embedding, embedding_warnings = _query_embedding(query_text, embedding_provider) if query_text else (None, [])
    payload = _fetch_jsonb(
        fetch_one,
        """
select specitout.build_context_bundle(
  %(app_slug)s,
  %(export_id)s,
  %(query_text)s,
  %(entity_key)s,
  %(mode)s,
  %(anchor_limit)s,
  %(max_hops)s,
  %(entity_limit)s,
  %(edge_limit)s,
  %(query_embedding)s::extensions.vector,
  %(allow_archived_app)s
) as build_context_bundle
""",
        {
            "app_slug": app_slug,
            "export_id": _resolve_export_id(
                fetch_one=fetch_one,
                get_application=get_application,
                app_slug=app_slug,
                version_label=version_label,
                export_id=export_id,
            ),
            "query_text": query_text,
            "entity_key": entity_key,
            "mode": mode,
            "anchor_limit": anchor_limit,
            "max_hops": max_hops,
            "entity_limit": entity_limit,
            "edge_limit": edge_limit,
            "query_embedding": _vector_literal(query_embedding),
            "allow_archived_app": False,
        },
        "build_context_bundle",
    )
    if embedding_warnings:
        payload["warnings"] = [*list(payload.get("warnings") or []), *embedding_warnings]
        payload["degraded"] = True
        payload["degraded_mode"] = True
    return payload


def _resolve_export_id(
    *,
    fetch_one: FetchOne,
    get_application: GetApplication,
    app_slug: str,
    version_label: str | None,
    export_id: str | None,
) -> str | None:
    if export_id is not None:
        return export_id
    if version_label is None:
        return None
    scope = resolve_export_scope(
        fetch_one=fetch_one,
        get_application=get_application,
        app_slug=app_slug,
        version_label=version_label,
    )
    export = scope["export"]
    if export is None:
        raise SpecItOutRuntimeError(f"Unknown export version {version_label} for application scope {app_slug}.")
    return str(export["id"])


def _string_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


def _query_embedding(query_text: str, embedding_provider: EmbeddingProvider | None) -> tuple[list[float] | None, list[str]]:
    if embedding_provider is None:
        return None, []
    try:
        return embedding_provider.embed_query(query_text), []
    except Exception as exc:
        return None, [f"Semantic query embedding unavailable; falling back to lexical search. {exc}"]


def _vector_literal(embedding: list[float] | None) -> str | None:
    if embedding is None:
        return None
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def _fetch_jsonb(
    fetch_one: FetchOne,
    query: str,
    params: Mapping[str, object],
    column: str,
) -> dict[str, object]:
    try:
        row = fetch_one(query, params)
    except SpecItOutRuntimeError:
        raise
    except Exception as exc:
        detail = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
        raise SpecItOutRuntimeError(f"Retrieval RPC {column} failed: {detail}") from exc
    if row is None:
        raise SpecItOutRuntimeError(f"Retrieval RPC {column} returned no row.")
    payload = row.get(column)
    if not isinstance(payload, Mapping):
        raise SpecItOutRuntimeError(f"Retrieval RPC {column} returned an invalid payload.")
    return _normalize_json(payload)


def _raise_if_target_lookup_failed(payload: Mapping[str, object], *, lookup: str) -> None:
    status = str(payload.get("status") or "found")
    if status == "ambiguous":
        candidates = payload.get("candidates")
        rendered = _render_candidate_keys(candidates)
        raise SpecItOutRuntimeError(
            f"Entity lookup {lookup} is ambiguous. "
            f"Candidates: {rendered}. "
            "Use query search, then rerun query usage with a canonical entity key."
        )
    if status == "not_found":
        raise SpecItOutRuntimeError(f"No entity matched {lookup}. Use query search to find candidates.")


def _render_candidate_keys(value: object) -> str:
    if not isinstance(value, list):
        return "multiple candidates"
    keys: list[str] = []
    for candidate in value:
        if isinstance(candidate, Mapping) and candidate.get("entity_key") is not None:
            keys.append(str(candidate["entity_key"]))
    return ", ".join(keys) if keys else "multiple candidates"


def _normalize_json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _normalize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    return value
