from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from specitout.backend_exact_answer_catalogs import (
    fetch_most_used_option_set_inventory,
    fetch_public_api_workflow_inventory,
    fetch_unused_option_set_inventory,
)
from specitout.backend_page_analysis_catalog import (
    fetch_most_complex_page_inventory,
    fetch_page_analysis_inventory,
    fetch_stale_page_inventory,
)
from specitout.backend_exact_answer_fetchers import (
    fetch_entity_type_count,
    fetch_entity_type_inventory,
    fetch_most_used_plugin_inventory,
    fetch_option_set_value_inventory,
    fetch_plugin_usage_inventory,
    fetch_unused_plugin_inventory,
)
from specitout.plugin_metadata import enrich_plugin_label, known_plugin_id_for_label

FetchOne = Callable[[str, Mapping[str, object] | None], dict[str, object] | None]


def exact_search_answer(
    *,
    fetch_one: FetchOne,
    app_slug: str,
    export_id: str | None,
    query_text: str,
) -> dict[str, object] | None:
    option_value_intent = _option_set_value_inventory_intent(query_text)
    if option_value_intent is not None:
        return fetch_option_set_value_inventory(
            fetch_one=fetch_one,
            app_slug=app_slug,
            export_id=export_id,
            option_set_lookup=option_value_intent["option_set_lookup"],
        )
    if _public_api_workflow_inventory_intent(query_text):
        return fetch_public_api_workflow_inventory(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    if _unused_option_set_inventory_intent(query_text):
        return fetch_unused_option_set_inventory(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    if _most_used_option_set_inventory_intent(query_text):
        return fetch_most_used_option_set_inventory(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    if _most_complex_page_inventory_intent(query_text):
        return fetch_most_complex_page_inventory(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    if _stale_page_inventory_intent(query_text):
        return fetch_stale_page_inventory(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    if _page_analysis_inventory_intent(query_text):
        return fetch_page_analysis_inventory(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    most_used_intent = _most_used_plugin_inventory_intent(query_text)
    if most_used_intent:
        return fetch_most_used_plugin_inventory(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    inventory_intent = _unused_plugin_inventory_intent(query_text)
    if inventory_intent:
        return fetch_unused_plugin_inventory(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    plugin_usage_intent = _plugin_usage_intent(query_text)
    if plugin_usage_intent is not None:
        return fetch_plugin_usage_inventory(
            fetch_one=fetch_one,
            app_slug=app_slug,
            export_id=export_id,
            plugin_lookup=plugin_usage_intent["plugin_lookup"],
            plugin_id=plugin_usage_intent.get("plugin_id"),
            plugin_label=plugin_usage_intent["plugin_label"],
        )
    entity_inventory_intent = _entity_inventory_intent(query_text)
    if entity_inventory_intent is not None:
        return fetch_entity_type_inventory(
            fetch_one=fetch_one,
            app_slug=app_slug,
            export_id=export_id,
            entity_type=entity_inventory_intent["entity_type"],
            counted_label=entity_inventory_intent["counted_label"],
            answer_type=entity_inventory_intent["answer_type"],
        )
    count_intent = _schema_count_intent(query_text)
    if count_intent is None:
        return None
    return fetch_entity_type_count(
        fetch_one=fetch_one,
        app_slug=app_slug,
        export_id=export_id,
        entity_type=count_intent["entity_type"],
        counted_label=count_intent["counted_label"],
    )


def _entity_inventory_intent(query_text: str) -> dict[str, str] | None:
    normalized = _normalize_query(query_text)
    inventory_terms = ("list", "show", "which", "what are", "inventory")
    if not any(term in normalized for term in inventory_terms):
        return None
    inventory_entity_types = (
        {
            "terms": ("page", "pages", "screen", "screens", "route", "routes"),
            "entity_type": "page",
            "counted_label": "pages",
            "answer_type": "page_inventory",
        },
        {
            "terms": ("reusable", "reusables", "reusable element", "reusable elements", "component", "components"),
            "entity_type": "component",
            "counted_label": "reusable elements",
            "answer_type": "component_inventory",
        },
        {
            "terms": ("backend workflow", "backend workflows", "api workflow", "api workflows"),
            "entity_type": "backend_workflow",
            "counted_label": "backend workflows",
            "answer_type": "backend_workflow_inventory",
        },
        {
            "terms": (
                "table",
                "tables",
                "data type",
                "data types",
                "datatype",
                "datatypes",
                "user type",
                "user types",
            ),
            "entity_type": "user_type",
            "counted_label": "tables",
            "answer_type": "user_type_inventory",
        },
        {
            "terms": ("option set", "option sets", "optionset", "optionsets"),
            "entity_type": "option_set",
            "counted_label": "option sets",
            "answer_type": "option_set_inventory",
        },
    )
    for inventory_type in inventory_entity_types:
        if any(term in normalized for term in inventory_type["terms"]):
            return {
                "entity_type": inventory_type["entity_type"],
                "counted_label": inventory_type["counted_label"],
                "answer_type": inventory_type["answer_type"],
            }
    return None


def _option_set_value_inventory_intent(query_text: str) -> dict[str, str] | None:
    normalized = _normalize_query(query_text)
    if "option set" not in normalized or "value" not in normalized:
        return None
    lookup = _capture_before_phrase(query_text, (" option set",), ("what values are in ", "list values for "))
    return {"option_set_lookup": lookup} if lookup else None


def _public_api_workflow_inventory_intent(query_text: str) -> bool:
    normalized = _normalize_query(query_text)
    workflow_terms = ("workflow", "workflows", "endpoint", "endpoints")
    public_terms = ("public api", "api workflow", "api workflows", "exposed backend", "workflow api")
    inventory_terms = ("list", "show", "which", "what are", "inventory", "exist", "how many", "count", "number of")
    return (
        any(term in normalized for term in workflow_terms)
        and any(term in normalized for term in public_terms)
        and any(term in normalized for term in inventory_terms)
    )


def _plugin_usage_intent(query_text: str) -> dict[str, str] | None:
    normalized = _normalize_query(query_text)
    if "plugin" not in normalized or not any(term in normalized for term in ("used", "usage", "where")):
        return None
    lookup = _capture_before_phrase(query_text, (" plugin",), ("where is ", "where are ", "show usage for "))
    if not lookup:
        return None
    plugin_id = known_plugin_id_for_label(lookup)
    return {
        "plugin_lookup": lookup,
        "plugin_label": _known_plugin_display_name(plugin_id) or lookup,
        **({"plugin_id": plugin_id} if plugin_id else {}),
    }


def _schema_count_intent(query_text: str) -> dict[str, str] | None:
    normalized = _normalize_query(query_text)
    count_terms = ("how many", "total number", "number of", "count")
    if not any(term in normalized for term in count_terms):
        return None
    countable_entity_types = (
        {
            "terms": ("page", "pages", "screen", "screens", "route", "routes"),
            "entity_type": "page",
            "counted_label": "pages",
        },
        {
            "terms": ("reusable", "reusables", "reusable element", "reusable elements", "component", "components"),
            "entity_type": "component",
            "counted_label": "reusable elements",
        },
        {
            "terms": ("backend workflow", "backend workflows", "api workflow", "api workflows"),
            "entity_type": "backend_workflow",
            "counted_label": "backend workflows",
        },
        {
            "terms": (
                "table",
                "tables",
                "data type",
                "data types",
                "datatype",
                "datatypes",
                "user type",
                "user types",
            ),
            "entity_type": "user_type",
            "counted_label": "tables",
        },
        {
            "terms": ("option set", "option sets", "optionset", "optionsets"),
            "entity_type": "option_set",
            "counted_label": "option sets",
        },
    )
    for countable in countable_entity_types:
        if any(term in normalized for term in countable["terms"]):
            return {"entity_type": countable["entity_type"], "counted_label": countable["counted_label"]}
    return None


def _unused_plugin_inventory_intent(query_text: str) -> bool:
    normalized = _normalize_query(query_text)
    plugin_terms = ("plugin", "plugins", "plugin installation", "plugin installations")
    unused_terms = ("not used", "unused", "used by 0", "used by zero", "not used at all")
    return any(term in normalized for term in plugin_terms) and any(term in normalized for term in unused_terms)


def _unused_option_set_inventory_intent(query_text: str) -> bool:
    normalized = _normalize_query(query_text)
    option_set_terms = ("option set", "option sets", "optionset", "optionsets")
    unused_terms = ("not used", "unused", "used by 0", "used by zero", "0 usage", "zero usage", "not used at all")
    return any(term in normalized for term in option_set_terms) and any(term in normalized for term in unused_terms)


def _most_used_plugin_inventory_intent(query_text: str) -> bool:
    normalized = _normalize_query(query_text)
    plugin_terms = ("plugin", "plugins", "plugin installation", "plugin installations")
    most_terms = ("used the most", "most used", "used most", "highest usage", "most usage")
    return any(term in normalized for term in plugin_terms) and any(term in normalized for term in most_terms)


def _most_used_option_set_inventory_intent(query_text: str) -> bool:
    normalized = _normalize_query(query_text)
    option_set_terms = ("option set", "option sets", "optionset", "optionsets")
    most_terms = ("used the most", "most used", "used most", "highest usage", "most usage", "most referenced")
    return any(term in normalized for term in option_set_terms) and any(term in normalized for term in most_terms)


def _page_analysis_inventory_intent(query_text: str) -> bool:
    normalized = _normalize_query(query_text)
    page_terms = ("page", "pages", "screen", "screens", "route", "routes")
    analysis_terms = ("analysis", "analyze", "metrics", "inventory", "profile", "scores", "ranking")
    return any(term in normalized for term in page_terms) and any(term in normalized for term in analysis_terms)


def _most_complex_page_inventory_intent(query_text: str) -> bool:
    normalized = _normalize_query(query_text)
    page_terms = ("page", "pages", "screen", "screens", "route", "routes")
    complexity_terms = (
        "most complex",
        "highest complexity",
        "most complicated",
        "hardest to migrate",
        "hardest page",
        "biggest page",
        "largest page",
    )
    return any(term in normalized for term in page_terms) and any(term in normalized for term in complexity_terms)


def _stale_page_inventory_intent(query_text: str) -> bool:
    normalized = _normalize_query(query_text)
    page_terms = ("page", "pages", "screen", "screens", "route", "routes")
    stale_terms = (
        "stale",
        "unused",
        "not used",
        "unreachable",
        "orphan",
        "dead",
        "deprecated",
        "legacy",
        "old page",
    )
    return any(term in normalized for term in page_terms) and any(term in normalized for term in stale_terms)


def _normalize_query(query_text: str) -> str:
    return " ".join(query_text.replace("_", " ").replace("-", " ").lower().split())


def _capture_before_phrase(query_text: str, endings: tuple[str, ...], prefixes: tuple[str, ...]) -> str | None:
    lowered = query_text.strip().rstrip("?").strip()
    normalized = lowered.lower()
    for prefix in prefixes:
        if normalized.startswith(prefix):
            lowered = lowered[len(prefix) :]
            normalized = normalized[len(prefix) :]
            break
    for ending in endings:
        index = normalized.find(ending)
        if index > 0:
            return _strip_leading_article(lowered[:index])
    match = re.search(r"\b([A-Za-z0-9_! -]+)\b", lowered)
    return _strip_leading_article(match.group(1)) if match else None


def _strip_leading_article(value: str) -> str:
    return re.sub(r"^(?:the|a|an)\s+", "", value.strip(), flags=re.IGNORECASE)


def _known_plugin_display_name(plugin_id: str | None) -> str | None:
    if plugin_id is None:
        return None
    label = enrich_plugin_label(plugin_id)
    return label.split(" (", 1)[0]
