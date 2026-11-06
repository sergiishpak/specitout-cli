"""Canonical search candidates and explicitly uncertain hints from export names."""
from __future__ import annotations

import re
from collections.abc import Mapping

_DEPRECATION = re.compile(r"(?<![a-z0-9])(?:deprecated|depr|obsolete)(?:\?)?(?![a-z0-9])", re.IGNORECASE)
_NAME_DEPRECATION = re.compile(r"^[\s\[\](){}/!#_*:.-]*(?P<marker>(?:deprecated|depr|obsolete)(?:\?)?)(?![a-z0-9])", re.IGNORECASE)


def requests_deprecated(query_text: str) -> bool:
    return bool(_DEPRECATION.search(query_text))


def name_hints(name: object) -> list[dict[str, object]]:
    match = _NAME_DEPRECATION.search(str(name or ""))
    if match is None:
        return []
    marker = match.group("marker")
    return [{"kind": "deprecation", "marker": marker, "uncertain": "?" in marker,
             "basis": "name_only"}]


def annotate_name_hints(value: object) -> bool:
    """Annotate retrieval entities, keeping stored source fragments intact."""
    found = False
    if isinstance(value, list):
        for item in value:
            found = annotate_name_hints(item) or found
        return found
    if not isinstance(value, dict):
        return False
    name = next((value.get(key) for key in ("canonical_name", "primary_entity_display_name", "display_name") if value.get(key)), None)
    hints = name_hints(name)
    if hints:
        value["name_hints"] = hints
        found = True
    for key, item in list(value.items()):
        if key not in {"normalized_payload", "_raw", "raw_fragment", "source_excerpt", "name_hints"}:
            found = annotate_name_hints(item) or found
    return found


def canonical_candidates(documents: object, *, query_text: str) -> list[dict[str, object]]:
    if not isinstance(documents, list):
        return []
    grouped: dict[str, dict[str, object]] = {}
    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            continue
        entity_key = document.get("entity_key") or document.get("primary_entity_key")
        key = str(entity_key or document.get("document_key") or f"unresolved:{index}")
        if key not in grouped:
            grouped[key] = {**document, "matched_documents": [], "evidence_links": []}
        candidate = grouped[key]
        candidate["matched_documents"].append(dict(document))
        for link in document.get("evidence_links") or []:
            if link not in candidate["evidence_links"]:
                candidate["evidence_links"].append(link)
    candidates = list(grouped.values())
    annotate_name_hints(candidates)
    if requests_deprecated(query_text):
        return candidates
    query = query_text.strip().casefold()

    def discovery_tier(candidate: Mapping[str, object]) -> int:
        names = (candidate.get("entity_key"), candidate.get("primary_entity_key"),
                 candidate.get("canonical_name"), candidate.get("primary_entity_display_name"), candidate.get("display_name"))
        if any(str(value).casefold() == query for value in names if value is not None):
            return 0
        return 2 if candidate.get("name_hints") else 1

    # Stable tiers preserve the RPC's relevance ordering and original scores within each tier.
    return sorted(candidates, key=discovery_tier)
