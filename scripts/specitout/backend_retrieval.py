from __future__ import annotations

import re

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from bubble_context_pack_internal.source_paths import ROOT_ALIASES, enrich_payload_source_paths
from specitout.backend_exact_answers import exact_search_answer
from specitout.backend_status import resolve_export_scope
from specitout.embedding_provider import EmbeddingProvider
from specitout.runtime import SpecItOutRuntimeError
from specitout.retrieval_candidates import annotate_name_hints, canonical_candidates, requests_deprecated

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
    export = _resolve_export(
        fetch_one=fetch_one,
        get_application=get_application,
        app_slug=app_slug,
        version_label=version_label,
        export_id=export_id,
    )
    resolved_export_id = str(export["id"])
    exact_answer = None if requests_deprecated(query_text) else exact_search_answer(
        fetch_one=fetch_one,
        app_slug=app_slug,
        export_id=resolved_export_id,
        query_text=query_text,
    )
    if exact_answer is not None:
        return _with_scope(exact_answer, export, fetch_one=fetch_one, version_label=version_label, explicit_export_id=export_id)
    query_embedding, embedding_warnings = _scoped_query_embedding(
        fetch_one, app_slug, export, query_text, embedding_provider,
    )
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
            # The existing RPC caps document candidates at 25. Fetch that pool once
            # so duplicates and name hints cannot exhaust a small entity limit.
            "limit": 25,
            "export_id": resolved_export_id,
            "query_embedding": _vector_literal(query_embedding),
            "allow_archived_app": False,
        },
        "search_entities",
    )
    documents = payload.get("results")
    candidates = canonical_candidates(documents, query_text=query_text)
    payload["results"] = candidates[:limit]
    payload["candidate_document_limit"] = 25
    payload["ranking_policy"] = (
        "RPC relevance order; scores are unchanged." if requests_deprecated(query_text) else
        "Exact name/key matches first, then names without deprecation hints; RPC relevance order within each tier and scores are unchanged."
    )
    payload["semantic_used"] = query_embedding is not None and any(
        reason.get("type") == "semantic_similarity"
        for candidate in payload["results"]
        for document in candidate.get("matched_documents", [])
        for reason in document.get("ranking_reasons", [])
        if isinstance(reason, Mapping)
    )
    if len(candidates) < limit and isinstance(documents, list) and len(documents) >= 25:
        payload["warnings"] = [*list(payload.get("warnings") or []),
            f"Only {len(candidates)} unique entities found within the 25-document candidate cap; refine the query for more results."]
    if embedding_warnings:
        payload["warnings"] = [*list(payload.get("warnings") or []), *embedding_warnings]
        payload["degraded"] = True
    return _with_scope(payload, export, fetch_one=fetch_one, version_label=version_label, explicit_export_id=export_id)


def query_entity(
    *,
    fetch_one: FetchOne,
    get_application: GetApplication,
    app_slug: str,
    entity_lookup: str,
    version_label: str | None,
    export_id: str | None,
) -> dict[str, object]:
    export = _resolve_export(fetch_one=fetch_one, get_application=get_application,
                             app_slug=app_slug, version_label=version_label, export_id=export_id)
    payload = _fetch_entity(fetch_one, app_slug, entity_lookup, str(export["id"]))
    return _with_scope(payload, export, fetch_one=fetch_one, version_label=version_label, explicit_export_id=export_id)


def _fetch_entity(fetch_one: FetchOne, app_slug: str, entity_lookup: str, export_id: str) -> dict[str, object]:
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
            "export_id": export_id,
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
    export = _resolve_export(fetch_one=fetch_one, get_application=get_application,
                             app_slug=app_slug, version_label=version_label, export_id=export_id)
    entity_payload = _fetch_entity(fetch_one, app_slug, entity_lookup, str(export["id"]))
    _raise_if_target_lookup_failed(entity_payload, lookup=entity_lookup)
    entity = entity_payload.get("entity")
    if not isinstance(entity, Mapping) or not entity.get("entity_key"):
        raise SpecItOutRuntimeError(f"Entity lookup {entity_lookup} did not resolve to one entity.")
    resolved_export_id = str(export["id"])
    payload = _fetch_jsonb(
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
    return _with_scope(payload, export, fetch_one=fetch_one, version_label=version_label, explicit_export_id=export_id)


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
    export = _resolve_export(fetch_one=fetch_one, get_application=get_application,
                             app_slug=app_slug, version_label=version_label, export_id=export_id)
    payload = _fetch_jsonb(
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
            "export_id": str(export["id"]),
            "allow_archived_app": False,
        },
        "find_paths",
    )
    return _with_scope(payload, export, fetch_one=fetch_one, version_label=version_label, explicit_export_id=export_id)


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
    export = _resolve_export(fetch_one=fetch_one, get_application=get_application,
                             app_slug=app_slug, version_label=version_label, export_id=export_id)
    query_embedding, embedding_warnings = _scoped_query_embedding(
        fetch_one, app_slug, export, query_text, embedding_provider,
    ) if query_text else (None, [])
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
            "export_id": str(export["id"]),
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
    if query_embedding is None:
        payload["semantic_used"] = False
    return _with_scope(payload, export, fetch_one=fetch_one, version_label=version_label, explicit_export_id=export_id)


def _resolve_export(
    *,
    fetch_one: FetchOne,
    get_application: GetApplication,
    app_slug: str,
    version_label: str | None,
    export_id: str | None,
) -> dict[str, object]:
    if export_id is not None:
        app = get_application(app_slug)
        if app is None:
            raise SpecItOutRuntimeError(f"Unknown application scope {app_slug}.")
        export = fetch_one(
            "select id, version_label, readiness_status::text as readiness_status from specitout.exports "
            "where id = %(export_id)s and app_id = %(app_id)s",
            {"export_id": export_id, "app_id": app["id"]},
        )
        if export is None:
            raise SpecItOutRuntimeError(f"Unknown export {export_id} for application scope {app_slug}.")
        if version_label is not None and str(export["version_label"]) != version_label:
            raise SpecItOutRuntimeError("Export ID and version label select different versions.")
        return export
    scope = resolve_export_scope(fetch_one=fetch_one, get_application=get_application,
                                 app_slug=app_slug, version_label=version_label)
    export = scope["export"]
    if export is None:
        raise SpecItOutRuntimeError(f"Unknown export version {version_label} for application scope {app_slug}.")
    return export


def _with_scope(payload: dict[str, object], export: Mapping[str, object], *, fetch_one: FetchOne,
                version_label: str | None, explicit_export_id: str | None) -> dict[str, object]:
    payload["resolved_export_id"] = str(export["id"])
    payload["version_label"] = str(export["version_label"])
    payload["export_selection_reason"] = "explicit_export" if explicit_export_id else "explicit_version" if version_label else "active_export"
    if annotate_name_hints(payload):
        payload["warnings"] = [*list(payload.get("warnings") or []),
            "Deprecation hints come from entity names only; they do not establish runtime inactivity. Question marks indicate uncertainty in the name."]
    aliases = _source_root_aliases(fetch_one, str(export["id"]), payload)
    return enrich_payload_source_paths(payload, root_aliases=aliases)


def _source_root_aliases(fetch_one: FetchOne, export_id: str, payload: Mapping[str, object]) -> dict[str, str]:
    root_paths: set[str] = set()
    pattern = re.compile(r"(?:%p3|%ed|pages|element_definitions|mobile_views)\.[^.;|\s,]+")

    def collect(value: object) -> None:
        if isinstance(value, str):
            root_paths.update(match.group() for match in pattern.finditer(value))
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, Mapping):
            for key, item in value.items():
                if key not in {"normalized_payload", "_raw", "raw_fragment", "source_excerpt"} and not key.endswith("_alias"):
                    collect(item)

    collect(payload)
    if not root_paths:
        return {}
    row = fetch_one(
        """
select coalesce(jsonb_agg(jsonb_build_object(
  'source_path', source_path,
  'source_id', source_id,
  'source_domain', coalesce(nullif(structural_json ->> 'source_domain', ''),
    case entity_type when 'page' then 'pages' when 'component' then 'element_definitions' when 'mobile_view' then 'mobile_views' end),
  'source_key', structural_json ->> 'source_key'
)), '[]'::jsonb) as source_root_entities
from specitout.entities
where export_id = %(export_id)s
  and entity_type in ('page', 'component', 'mobile_view')
  and (source_path = any(%(root_paths)s::text[])
    or source_id = any(%(root_ids)s::text[])
    or structural_json ->> 'source_key' = any(%(root_ids)s::text[]))
""",
        {"export_id": export_id, "root_paths": sorted(root_paths),
         "root_ids": sorted({path.split('.', 1)[1] for path in root_paths})},
    )
    aliases: dict[str, str] = {}
    for root in (row or {}).get("source_root_entities") or []:
        domain, key = root.get("source_domain"), root.get("source_key")
        if domain not in {"pages", "element_definitions", "mobile_views"} or key is None:
            continue
        canonical = f"{domain}.{key}"
        if root.get("source_path"):
            aliases[str(root["source_path"])] = canonical
        prefixes = [domain, *(alias for alias, target in ROOT_ALIASES.items() if target == domain)]
        for prefix in prefixes:
            for identifier in (root.get("source_id"), key):
                if identifier is not None:
                    aliases[f"{prefix}.{identifier}"] = canonical
    return aliases


def _scoped_query_embedding(fetch_one: FetchOne, app_slug: str, export: Mapping[str, object],
                            query_text: str, embedding_provider: EmbeddingProvider | None) -> tuple[list[float] | None, list[str]]:
    if embedding_provider is None:
        return None, []
    if export.get("readiness_status") not in {"ready", "degraded"}:
        return None, ["Semantic search unavailable for this export readiness; using lexical search without loading the embedding model."]
    scope = fetch_one(
        "select semantic_available from specitout.resolve_retrieval_scope(%(app_slug)s, %(export_id)s)",
        {"app_slug": app_slug, "export_id": str(export["id"])},
    )
    if not scope or not scope.get("semantic_available"):
        return None, ["No indexed semantic vectors available; using lexical search without loading the embedding model."]
    return _query_embedding(query_text, embedding_provider)


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
