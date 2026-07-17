from __future__ import annotations

from collections.abc import Callable

from specitout.backend_protocol import LocalBackendProtocol
from specitout.contracts import CommandEnvelope
from specitout.runtime import SpecItOutRuntimeError


class RetrievalService:
    def __init__(self, backend_factory: Callable[[], LocalBackendProtocol]) -> None:
        self._backend_factory = backend_factory

    def search(
        self,
        *,
        app_slug: str,
        query_text: str,
        version_label: str | None,
        mode: str,
        limit: int,
    ) -> CommandEnvelope:
        if limit < 1:
            raise SpecItOutRuntimeError("query search requires --limit to be at least 1.")
        result = self._backend_factory().query_search(
            app_slug=app_slug,
            query_text=query_text,
            version_label=version_label,
            mode=mode,
            limit=limit,
        )
        resolved_version = result.get("version_label") or version_label
        semantic_available = bool(result.get("semantic_available"))
        semantic_used = bool(result.get("semantic_used"))
        is_exact_answer = bool(result.get("answer_type"))
        return {
            "status": "ok",
            "command": "query search",
            "scope": {
                "app_slug": app_slug,
                "version_label": str(resolved_version) if resolved_version else None,
            },
            "data": {
                "state": str(result.get("state") or "search_ready"),
                "query_text": query_text,
                "mode": mode,
                "limit": limit,
                "semantic_available": semantic_available,
                "semantic_used": semantic_used,
                "answer_type": result.get("answer_type"),
                "answer": result.get("answer"),
                "count": result.get("count"),
                "items": list(result.get("items") or []),
                "counted_entity_type": result.get("counted_entity_type"),
                "counted_label": result.get("counted_label"),
                "basis": result.get("basis"),
                "details": list(result.get("details") or []),
                "fallback_reason": result.get("fallback_reason"),
                "unresolved_items": list(result.get("unresolved_items") or []),
                "evidence": result.get("evidence"),
                "results": _normalize_search_results(result.get("results")),
            },
            "warnings": list(result.get("warnings") or []),
            "degraded": bool(result.get("degraded", False)) if is_exact_answer else not semantic_available or (semantic_available and not semantic_used),
            "next_actions": [] if is_exact_answer else ["query entity --app <app-slug> --entity <entity-key>"],
        }

    def entity(
        self,
        *,
        app_slug: str,
        entity_lookup: str,
        version_label: str | None,
    ) -> CommandEnvelope:
        result = self._backend_factory().query_entity(
            app_slug=app_slug,
            entity_lookup=entity_lookup,
            version_label=version_label,
        )
        status = str(result.get("status") or "found")
        if status == "ambiguous":
            candidates = result.get("candidates") or []
            rendered = ", ".join(str(candidate.get("entity_key") or candidate) for candidate in candidates)
            raise SpecItOutRuntimeError(
                "Entity lookup is ambiguous. "
                f"Candidates: {rendered}. "
                "Use query search, then rerun query entity with a canonical entity key."
            )
        if status == "not_found":
            raise SpecItOutRuntimeError(f"No entity matched {entity_lookup}. Use query search to find candidates.")
        resolved_version = result.get("version_label") or version_label
        return {
            "status": "ok",
            "command": "query entity",
            "scope": {
                "app_slug": app_slug,
                "version_label": str(resolved_version) if resolved_version else None,
            },
            "data": {
                "state": "entity_found",
                "entity": _normalize_entity(result.get("entity")),
                "evidence": _normalize_evidence(result.get("evidence"), result.get("evidence_links")),
            },
            "warnings": list(result.get("warnings") or []),
            "degraded": bool(result.get("degraded", False)),
            "next_actions": [
                "query usage --app <app-slug> --entity <entity-key>",
                "query paths --app <app-slug> --from <entity-key> --to <entity-key>",
            ],
        }

    def usage(
        self,
        *,
        app_slug: str,
        entity_lookup: str,
        version_label: str | None,
        direction: str,
        relation: str | None,
        limit: int,
    ) -> CommandEnvelope:
        if limit < 1:
            raise SpecItOutRuntimeError("query usage requires --limit to be at least 1.")
        result = self._backend_factory().query_usage(
            app_slug=app_slug,
            entity_lookup=entity_lookup,
            version_label=version_label,
            direction=direction,
            relation=relation,
            limit=limit,
        )
        resolved_version = result.get("version_label") or version_label
        return {
            "status": "ok",
            "command": "query usage",
            "scope": {
                "app_slug": app_slug,
                "version_label": str(resolved_version) if resolved_version else None,
            },
            "data": {
                "state": "usage_ready",
                "entity": _normalize_entity(result.get("entity")),
                "direction": direction,
                "relation": relation,
                "relations": _normalize_usage_relations(result.get("relations"), result.get("neighbors")),
            },
            "warnings": list(result.get("warnings") or []),
            "degraded": bool(result.get("degraded", False)),
            "next_actions": ["query paths --app <app-slug> --from <entity-key> --to <entity-key>"],
        }

    def paths(
        self,
        *,
        app_slug: str,
        from_lookup: str,
        to_lookup: str,
        version_label: str | None,
        direction: str,
        relation: str | None,
        max_hops: int,
        max_paths: int,
    ) -> CommandEnvelope:
        if max_hops < 1:
            raise SpecItOutRuntimeError("query paths requires --max-hops to be at least 1.")
        if max_paths < 1:
            raise SpecItOutRuntimeError("query paths requires --max-paths to be at least 1.")
        result = self._backend_factory().query_paths(
            app_slug=app_slug,
            from_lookup=from_lookup,
            to_lookup=to_lookup,
            version_label=version_label,
            direction=direction,
            relation=relation,
            max_hops=max_hops,
            max_paths=max_paths,
        )
        resolved_version = result.get("version_label") or version_label
        _raise_for_targeted_lookup_status(
            result,
            command="Path",
            lookup="anchor",
            candidate_keys=_path_candidate_keys(result),
        )
        return {
            "status": "ok",
            "command": "query paths",
            "scope": {
                "app_slug": app_slug,
                "version_label": str(resolved_version) if resolved_version else None,
            },
            "data": {
                "state": "paths_ready",
                "from_lookup": from_lookup,
                "to_lookup": to_lookup,
                "direction": direction,
                "relation": relation,
                "max_hops": max_hops,
                "max_paths": max_paths,
                "paths": _normalize_paths(result.get("paths")),
            },
            "warnings": list(result.get("warnings") or []),
            "degraded": bool(result.get("degraded", False)),
            "next_actions": ["query entity --app <app-slug> --entity <entity-key>"],
        }


def _normalize_search_results(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [_normalize_search_result(result) for result in value if isinstance(result, dict)]


def _normalize_search_result(result: dict[str, object]) -> dict[str, object]:
    reasons = result.get("ranking_reasons")
    return {
        "entity_key": _first_present(result, "entity_key", "primary_entity_key", "key"),
        "entity_type": _first_present(result, "entity_type", "primary_entity_type", "type"),
        "canonical_name": _first_present(result, "canonical_name", "primary_entity_display_name", "display_name", "name"),
        "match_type": _search_match_type(reasons, result),
        "score": _first_present(result, "score", "ranking_score"),
        "evidence": _format_evidence_links(result.get("evidence_links")) or result.get("evidence"),
    }


def _normalize_entity(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    entity = dict(value)
    if "canonical_name" not in entity and entity.get("display_name") is not None:
        entity["canonical_name"] = entity["display_name"]
    return entity


def _normalize_evidence(evidence: object, evidence_links: object) -> list[object]:
    if isinstance(evidence, list) and evidence:
        return evidence
    rendered_links = _format_evidence_links(evidence_links)
    if rendered_links:
        return [rendered_links]
    return []


def _normalize_usage_relations(relations: object, neighbors: object) -> list[dict[str, object]]:
    if isinstance(relations, list) and relations:
        return [relation for relation in relations if isinstance(relation, dict)]
    if not isinstance(neighbors, list):
        return []
    normalized: list[dict[str, object]] = []
    for neighbor in neighbors:
        if not isinstance(neighbor, dict):
            continue
        entity = neighbor.get("entity")
        edge = neighbor.get("edge")
        entity_data = entity if isinstance(entity, dict) else {}
        edge_data = edge if isinstance(edge, dict) else {}
        normalized.append(
            {
                "direction": neighbor.get("direction"),
                "relation_type": neighbor.get("relation") or edge_data.get("relation"),
                "entity_key": entity_data.get("entity_key") or neighbor.get("entity_key"),
                "entity_type": entity_data.get("entity_type") or neighbor.get("entity_type"),
                "canonical_name": _first_present(entity_data, "canonical_name", "display_name", "name"),
                "evidence": edge_data.get("evidence_path") or neighbor.get("evidence"),
            }
        )
    return normalized


def _normalize_paths(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [_normalize_path(path) for path in value if isinstance(path, dict)]


def _normalize_path(path: dict[str, object]) -> dict[str, object]:
    normalized = dict(path)
    entities = path.get("entities")
    if isinstance(entities, list):
        normalized["entities"] = [_path_entity_label(entity) for entity in entities]
    if "length" not in normalized and path.get("hop_count") is not None:
        normalized["length"] = path["hop_count"]
    evidence = _path_evidence(path.get("edges"))
    if evidence and not normalized.get("evidence"):
        normalized["evidence"] = evidence
    return normalized


def _path_entity_label(entity: object) -> str:
    if isinstance(entity, dict):
        value = _first_present(entity, "entity_key", "key", "canonical_name", "display_name", "name")
        return str(value) if value is not None else "-"
    return str(entity)


def _path_evidence(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    rendered: list[str] = []
    for edge in value:
        if not isinstance(edge, dict):
            continue
        evidence = edge.get("evidence_path") or edge.get("evidence")
        if evidence:
            rendered.append(str(evidence))
    return "; ".join(rendered) if rendered else None


def _raise_for_targeted_lookup_status(
    result: dict[str, object],
    *,
    command: str,
    lookup: str,
    candidate_keys: list[str],
) -> None:
    status = str(result.get("status") or "found")
    if "ambiguous" in status:
        rendered = ", ".join(candidate_keys) if candidate_keys else "multiple candidates"
        raise SpecItOutRuntimeError(
            f"{command} lookup is ambiguous for {lookup}. "
            f"Candidates: {rendered}. "
            "Use query search, then rerun with canonical entity keys."
        )
    if "not_found" in status:
        raise SpecItOutRuntimeError(f"{command} lookup did not resolve {lookup}. Use query search to find candidates.")


def _path_candidate_keys(result: dict[str, object]) -> list[str]:
    keys: list[str] = []
    for resolution_key in ("from_anchor_resolution", "to_anchor_resolution"):
        resolution = result.get(resolution_key)
        if not isinstance(resolution, dict):
            continue
        candidates = resolution.get("candidates")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("entity_key") is not None:
                keys.append(str(candidate["entity_key"]))
    return keys


def _search_match_type(reasons: object, result: dict[str, object]) -> object:
    direct = _first_present(result, "match_type", "search_mode")
    if direct:
        return direct
    if not isinstance(reasons, list):
        return None
    reason_types = [str(reason.get("type")) for reason in reasons if isinstance(reason, dict) and reason.get("type")]
    if any(reason_type.startswith("exact_") for reason_type in reason_types):
        return "exact"
    if "semantic_similarity" in reason_types:
        return "semantic"
    if "lexical_match" in reason_types:
        return "lexical"
    return reason_types[0] if reason_types else None


def _format_evidence_links(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    rendered: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind") or item.get("type") or "evidence"
        path = item.get("source_path") or item.get("path")
        if path:
            rendered.append(f"{kind}: {path}")
    return "; ".join(rendered) if rendered else None


def _first_present(mapping: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None
