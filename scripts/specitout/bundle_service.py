from __future__ import annotations

from collections.abc import Callable

from specitout.backend_protocol import LocalBackendProtocol
from specitout.contracts import CommandEnvelope
from specitout.runtime import SpecItOutRuntimeError


class BundleService:
    def __init__(self, backend_factory: Callable[[], LocalBackendProtocol]) -> None:
        self._backend_factory = backend_factory

    def build(
        self,
        *,
        app_slug: str,
        query_text: str | None,
        entity_key: str | None,
        version_label: str | None,
        mode: str,
        anchor_limit: int,
        max_hops: int,
        entity_limit: int,
        edge_limit: int,
    ) -> CommandEnvelope:
        query_text = _clean_optional(query_text)
        entity_key = _clean_optional(entity_key)
        if (query_text is None) == (entity_key is None):
            raise SpecItOutRuntimeError("bundle build requires exactly one of --query or --entity.")
        _require_at_least_one("--anchor-limit", anchor_limit)
        _require_at_least_one("--max-hops", max_hops)
        _require_at_least_one("--entity-limit", entity_limit)
        _require_at_least_one("--edge-limit", edge_limit)
        result = self._backend_factory().build_bundle(
            app_slug=app_slug,
            query_text=query_text,
            entity_key=entity_key,
            version_label=version_label,
            mode=mode,
            anchor_limit=anchor_limit,
            max_hops=max_hops,
            entity_limit=entity_limit,
            edge_limit=edge_limit,
        )
        resolved_version = result.get("version_label") or version_label
        semantic_available = bool(result.get("semantic_available"))
        semantic_used = bool(result.get("semantic_used"))
        degraded = bool(result.get("degraded_mode") or result.get("degraded"))
        if query_text and (not semantic_available or (semantic_available and not semantic_used)):
            degraded = True
        anchors = _normalize_anchors(result.get("resolved_anchors"))
        entities = _normalize_entities(result.get("selected_entities"))
        edges = _normalize_edges(result.get("related_edges"))
        evidence = _normalize_evidence(result.get("evidence_links"))
        notes = _metadata_notes(result.get("bundle_metadata"))
        state = str(result.get("status") or "bundle_ready")
        return {
            "status": "ok",
            "command": "bundle build",
            "scope": {
                "app_slug": app_slug,
                "version_label": str(resolved_version) if resolved_version else None,
                "export_id": str(result["resolved_export_id"]) if result.get("resolved_export_id") else None,
            },
            "data": {
                "state": state,
                "query_text": query_text,
                "entity_key": entity_key,
                "mode": mode,
                "limits": {
                    "anchor_limit": anchor_limit,
                    "max_hops": max_hops,
                    "entity_limit": entity_limit,
                    "edge_limit": edge_limit,
                },
                "semantic_available": semantic_available,
                "semantic_used": semantic_used,
                "anchors": anchors,
                "entities": entities,
                "edges": edges,
                "candidates": _normalize_candidates(result.get("anchor_resolution")),
                "evidence": evidence,
                "truncation": _normalize_truncation(result.get("truncation")),
                "notes": notes,
            },
            "warnings": [str(warning) for warning in result.get("warnings") or []],
            "degraded": degraded,
            "next_actions": _next_actions(state, anchors, query_text=query_text, entity_key=entity_key),
        }


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _require_at_least_one(flag: str, value: int) -> None:
    if value < 1:
        raise SpecItOutRuntimeError(f"bundle build requires {flag} to be at least 1.")


def _normalize_anchors(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    anchors: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        anchors.append(
            {
                "entity_key": _first_present(item, "entity_key", "key"),
                "entity_type": _first_present(item, "entity_type", "type"),
                "canonical_name": _first_present(item, "canonical_name", "display_name", "name"),
                "match_type": _first_present(item, "resolution_reason", "anchor_kind", "match_type"),
                "evidence": _anchor_evidence(item),
                "name_hints": list(item.get("name_hints") or []),
            }
        )
    return anchors


def _normalize_entities(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    entities: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entities.append(_normalize_entity(item))
    return entities


def _normalize_entity(item: dict[str, object]) -> dict[str, object]:
    return {
        "entity_key": _first_present(item, "entity_key", "key"),
        "entity_type": _first_present(item, "entity_type", "type"),
        "canonical_name": _first_present(item, "canonical_name", "display_name", "name"),
        "summary": item.get("summary"),
        "name_hints": list(item.get("name_hints") or []),
    }


def _normalize_edges(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _normalize_candidates(value: object) -> list[dict[str, object]]:
    if not isinstance(value, dict):
        return []
    candidates = value.get("candidates")
    if not isinstance(candidates, list):
        return []
    return [_normalize_entity(candidate) for candidate in candidates if isinstance(candidate, dict)]


def _anchor_evidence(anchor: dict[str, object]) -> str | None:
    direct = _format_evidence_links(anchor.get("evidence_links"))
    if direct:
        return direct
    documents = anchor.get("matched_documents")
    if not isinstance(documents, list):
        return None
    evidence: list[str] = []
    for document in documents:
        if isinstance(document, dict):
            rendered = _format_evidence_links(document.get("evidence_links"))
            if rendered:
                evidence.append(rendered)
    return "; ".join(evidence) if evidence else None


def _normalize_evidence(value: object) -> list[str]:
    rendered = _format_evidence_links(value)
    return [rendered] if rendered else []


def _format_evidence_links(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    rendered: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind") or item.get("type") or "evidence"
        path = item.get("source_path") or item.get("path") or item.get("evidence_path")
        if path:
            rendered.append(f"{kind}: {path}")
    return "; ".join(rendered) if rendered else None


def _normalize_truncation(value: object) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    return {str(key): bool(item) for key, item in value.items()}


def _metadata_notes(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    notes = value.get("notes")
    if not isinstance(notes, list):
        return []
    return [str(note) for note in notes if note]


def _next_actions(
    state: str,
    anchors: list[dict[str, object]],
    *,
    query_text: str | None,
    entity_key: str | None,
) -> list[str]:
    if state in {"ambiguous", "not_found", "no_anchor_results"}:
        return ["query search --app <app-slug> --query <query>"]
    if anchors or entity_key:
        return [
            "query entity --app <app-slug> --entity <entity-key>",
            "query usage --app <app-slug> --entity <entity-key>",
        ]
    if query_text:
        return ["query search --app <app-slug> --query <query>"]
    return ["query search --app <app-slug> --query <query>"]


def _first_present(mapping: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None
