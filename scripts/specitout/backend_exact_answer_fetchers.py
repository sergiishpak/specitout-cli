from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from specitout.plugin_metadata import enrich_plugin_label
from specitout.runtime import SpecItOutRuntimeError

FetchOne = Callable[[str, Mapping[str, object] | None], dict[str, object] | None]


def fetch_unused_plugin_inventory(*, fetch_one: FetchOne, app_slug: str, export_id: str | None) -> dict[str, object]:
    row = fetch_one(
        """
select
  scope.export_id::text as resolved_export_id,
  e.version_label,
  scope.export_selection_reason::text as export_selection_reason,
  coalesce(jsonb_agg(ent.display_name order by ent.display_name) filter (where ent.entity_key is not null), '[]'::jsonb) as items,
  count(ent.entity_key)::int as total_count
from specitout.resolve_retrieval_scope(
  %(app_slug)s,
  %(export_id)s::uuid,
  %(allow_archived_app)s
) scope
join specitout.exports e on e.id = scope.export_id
left join specitout.entities ent
  on ent.export_id = scope.export_id
 and ent.entity_type = 'plugin_installation'
left join specitout.edges used_edges
  on used_edges.export_id = ent.export_id
 and used_edges.to_entity_key = ent.entity_key
where used_edges.to_entity_key is null
group by scope.export_id, e.version_label, scope.export_selection_reason
""",
        {"app_slug": app_slug, "export_id": export_id, "allow_archived_app": False},
    )
    if row is None:
        raise SpecItOutRuntimeError("Unused plugin inventory query returned no row.")
    items = _enriched_plugin_labels(row.get("items"))
    count = int(row.get("total_count") or len(items))
    return _exact_payload(
        row,
        app_slug=app_slug,
        answer_type="unused_plugin_inventory",
        answer=f"{count} unused plugins",
        count=count,
        items=items,
        evidence=["specitout.entities plugin_installation with no inbound edges"],
    )


def fetch_most_used_plugin_inventory(*, fetch_one: FetchOne, app_slug: str, export_id: str | None) -> dict[str, object]:
    row = fetch_one(
        """
with plugin_usage as (
  select
    scope.export_id::text as resolved_export_id,
    e.version_label,
    scope.export_selection_reason::text as export_selection_reason,
    ent.display_name,
    count(used_edges.id)::int as used_count,
    max(count(used_edges.id)) over () as max_used_count
  from specitout.resolve_retrieval_scope(
    %(app_slug)s,
    %(export_id)s::uuid,
    %(allow_archived_app)s
  ) scope
  join specitout.exports e on e.id = scope.export_id
  join specitout.entities ent
    on ent.export_id = scope.export_id
   and ent.entity_type = 'plugin_installation'
  left join specitout.edges used_edges
    on used_edges.export_id = ent.export_id
   and used_edges.to_entity_key = ent.entity_key
  group by scope.export_id, e.version_label, scope.export_selection_reason, ent.entity_key, ent.display_name
)
select
  resolved_export_id,
  version_label,
  export_selection_reason,
  coalesce(jsonb_agg(display_name order by display_name) filter (where used_count = max_used_count), '[]'::jsonb) as items,
  coalesce(max(max_used_count), 0)::int as total_count
from plugin_usage
group by resolved_export_id, version_label, export_selection_reason
""",
        {"app_slug": app_slug, "export_id": export_id, "allow_archived_app": False},
    )
    if row is None:
        raise SpecItOutRuntimeError("Most-used plugin inventory query returned no row.")
    items = _enriched_plugin_labels(row.get("items"))
    usage_count = int(row.get("total_count") or 0)
    item_count = len(items)
    answer = (
        f"{item_count} {_plural(item_count, 'plugin')} "
        f"{'tied for most usage' if item_count != 1 else 'used the most'}, "
        f"used by {usage_count} {_plural(usage_count, 'entity', 'entities')}"
    )
    return _exact_payload(
        row,
        app_slug=app_slug,
        answer_type="most_used_plugin_inventory",
        answer=answer,
        count=usage_count,
        items=items,
        evidence=["specitout.entities plugin_installation ranked by inbound edges"],
    )


def fetch_entity_type_count(
    *,
    fetch_one: FetchOne,
    app_slug: str,
    export_id: str | None,
    entity_type: str,
    counted_label: str,
) -> dict[str, object]:
    row = fetch_one(
        """
select
  scope.export_id::text as resolved_export_id,
  e.version_label,
  scope.export_selection_reason::text as export_selection_reason,
  count(ent.entity_key)::int as total_count
from specitout.resolve_retrieval_scope(
  %(app_slug)s,
  %(export_id)s::uuid,
  %(allow_archived_app)s
) scope
join specitout.exports e on e.id = scope.export_id
left join specitout.entities ent
  on ent.export_id = scope.export_id
 and ent.entity_type = %(entity_type)s
group by scope.export_id, e.version_label, scope.export_selection_reason
""",
        {"app_slug": app_slug, "export_id": export_id, "entity_type": entity_type, "allow_archived_app": False},
    )
    if row is None:
        raise SpecItOutRuntimeError("Entity type count query returned no row.")
    count = int(row.get("total_count") or 0)
    return {
        **_exact_payload(
            row,
            app_slug=app_slug,
            answer_type="entity_type_count",
            answer=f"{count} {counted_label}",
            count=count,
            items=[],
            evidence=[f"specitout.entities where entity_type={entity_type}"],
        ),
        "counted_entity_type": entity_type,
        "counted_label": counted_label,
    }


def fetch_option_set_value_inventory(
    *,
    fetch_one: FetchOne,
    app_slug: str,
    export_id: str | None,
    option_set_lookup: str,
) -> dict[str, object]:
    row = fetch_one(
        """
with matched_option_set as (
  select
    scope.export_id::text as resolved_export_id,
    e.version_label,
    scope.export_selection_reason::text as export_selection_reason,
    ent.entity_key,
    ent.display_name
  from specitout.resolve_retrieval_scope(
    %(app_slug)s,
    %(export_id)s::uuid,
    %(allow_archived_app)s
  ) scope
  join specitout.exports e on e.id = scope.export_id
  join specitout.entities ent
    on ent.export_id = scope.export_id
   and ent.entity_type = 'option_set'
  where lower(ent.display_name) = lower(%(option_set_lookup)s)
     or lower(ent.entity_key) = lower(%(option_set_lookup)s)
     or lower(coalesce(ent.source_id, '')) = lower(%(option_set_lookup)s)
  order by
    case when lower(ent.display_name) = lower(%(option_set_lookup)s) then 0 else 1 end,
    ent.display_name
  limit 1
)
select
  matched_option_set.resolved_export_id,
  matched_option_set.version_label,
  matched_option_set.export_selection_reason,
  matched_option_set.display_name as option_set_label,
  coalesce(jsonb_agg(child.display_name order by child.display_name) filter (where child.entity_key is not null), '[]'::jsonb) as items,
  count(child.entity_key)::int as total_count
from matched_option_set
left join specitout.edges edge
  on edge.export_id::text = matched_option_set.resolved_export_id
 and edge.from_entity_key = matched_option_set.entity_key
 and edge.relation = 'defines_option_value'
left join specitout.entities child
  on child.export_id::text = matched_option_set.resolved_export_id
 and child.entity_key = edge.to_entity_key
 and child.entity_type = 'option_value'
group by
  matched_option_set.resolved_export_id,
  matched_option_set.version_label,
  matched_option_set.export_selection_reason,
  matched_option_set.display_name
""",
        {"app_slug": app_slug, "export_id": export_id, "option_set_lookup": option_set_lookup, "allow_archived_app": False},
    )
    if row is None:
        raise SpecItOutRuntimeError(f"Option set {option_set_lookup} did not resolve to indexed values.")
    items = _string_list(row.get("items"))
    count = int(row.get("total_count") or len(items))
    option_set_label = str(row.get("option_set_label") or option_set_lookup)
    return _exact_payload(
        row,
        app_slug=app_slug,
        answer_type="option_set_value_inventory",
        answer=f"{option_set_label} has {count} {_plural(count, 'value')}",
        count=count,
        items=items,
        evidence=[f"specitout.entities option_set {option_set_label} values"],
    )


def fetch_plugin_usage_inventory(
    *,
    fetch_one: FetchOne,
    app_slug: str,
    export_id: str | None,
    plugin_lookup: str,
    plugin_id: str | None,
    plugin_label: str,
) -> dict[str, object]:
    row = fetch_one(
        """
with matched_plugin as (
  select
    scope.export_id::text as resolved_export_id,
    e.version_label,
    scope.export_selection_reason::text as export_selection_reason,
    ent.entity_key,
    ent.display_name
  from specitout.resolve_retrieval_scope(
    %(app_slug)s,
    %(export_id)s::uuid,
    %(allow_archived_app)s
  ) scope
  join specitout.exports e on e.id = scope.export_id
  join specitout.entities ent
    on ent.export_id = scope.export_id
   and ent.entity_type = 'plugin_installation'
  where (%(plugin_id)s::text is not null and (ent.display_name = %(plugin_id)s::text or ent.entity_key = %(plugin_id)s::text))
     or lower(ent.display_name) = lower(%(plugin_lookup)s)
     or lower(ent.entity_key) = lower(%(plugin_lookup)s)
  order by
    case when %(plugin_id)s::text is not null and ent.display_name = %(plugin_id)s::text then 0 else 1 end,
    ent.display_name
  limit 1
)
select
  matched_plugin.resolved_export_id,
  matched_plugin.version_label,
  matched_plugin.export_selection_reason,
  matched_plugin.display_name as plugin_label,
  coalesce(jsonb_agg(
    coalesce(source.entity_key || ' ' || source.display_name, edge.from_entity_key)
    order by coalesce(source.display_name, edge.from_entity_key)
  ) filter (where edge.id is not null), '[]'::jsonb) as items,
  count(edge.id)::int as total_count
from matched_plugin
left join specitout.edges edge
  on edge.export_id::text = matched_plugin.resolved_export_id
 and edge.to_entity_key = matched_plugin.entity_key
left join specitout.entities source
  on source.export_id::text = matched_plugin.resolved_export_id
 and source.entity_key = edge.from_entity_key
group by
  matched_plugin.resolved_export_id,
  matched_plugin.version_label,
  matched_plugin.export_selection_reason,
  matched_plugin.display_name
""",
        {
            "app_slug": app_slug,
            "export_id": export_id,
            "plugin_lookup": plugin_lookup,
            "plugin_id": plugin_id,
            "allow_archived_app": False,
        },
    )
    if row is None:
        return _exact_payload(
            {},
            app_slug=app_slug,
            answer_type="plugin_usage_inventory",
            answer=f"{plugin_label} did not resolve to an indexed plugin installation",
            count=0,
            items=[],
            evidence=["specitout.entities plugin_installation lookup"],
            degraded=True,
            fallback_reason="No indexed plugin installation matched the requested plugin.",
            unresolved_items=[plugin_lookup],
        )
    items = _string_list(row.get("items"))
    count = int(row.get("total_count") or len(items))
    resolved_plugin_label = _plugin_answer_label(plugin_id, plugin_label, row.get("plugin_label"))
    return _exact_payload(
        row,
        app_slug=app_slug,
        answer_type="plugin_usage_inventory",
        answer=f"{resolved_plugin_label} is used by {count} {_plural(count, 'entity', 'entities')}",
        count=count,
        items=items,
        evidence=[f"specitout.edges inbound to plugin_installation:{plugin_id or row.get('plugin_label') or plugin_lookup}"],
    )


def fetch_entity_type_inventory(
    *,
    fetch_one: FetchOne,
    app_slug: str,
    export_id: str | None,
    entity_type: str,
    counted_label: str,
    answer_type: str,
) -> dict[str, object]:
    row = fetch_one(
        """
select
  scope.export_id::text as resolved_export_id,
  e.version_label,
  scope.export_selection_reason::text as export_selection_reason,
  coalesce(jsonb_agg(ent.display_name order by ent.display_name) filter (where ent.entity_key is not null), '[]'::jsonb) as items,
  count(ent.entity_key)::int as total_count
from specitout.resolve_retrieval_scope(
  %(app_slug)s,
  %(export_id)s::uuid,
  %(allow_archived_app)s
) scope
join specitout.exports e on e.id = scope.export_id
left join specitout.entities ent
  on ent.export_id = scope.export_id
 and ent.entity_type = %(entity_type)s
group by scope.export_id, e.version_label, scope.export_selection_reason
""",
        {"app_slug": app_slug, "export_id": export_id, "entity_type": entity_type, "allow_archived_app": False},
    )
    if row is None:
        raise SpecItOutRuntimeError("Entity type inventory query returned no row.")
    items = _string_list(row.get("items"))
    count = int(row.get("total_count") or len(items))
    return {
        **_exact_payload(
            row,
            app_slug=app_slug,
            answer_type=answer_type,
            answer=f"{count} {counted_label}",
            count=count,
            items=items,
            evidence=[f"specitout.entities where entity_type={entity_type}"],
        ),
        "counted_entity_type": entity_type,
        "counted_label": counted_label,
    }


def _exact_payload(
    row: Mapping[str, object],
    *,
    app_slug: str,
    answer_type: str,
    answer: str,
    count: int,
    items: list[str],
    evidence: list[str],
    degraded: bool = False,
    fallback_reason: str | None = None,
    unresolved_items: list[str] | None = None,
) -> dict[str, object]:
    return {
        "app_slug": app_slug,
        "version_label": row.get("version_label"),
        "resolved_export_id": row.get("resolved_export_id"),
        "export_selection_reason": row.get("export_selection_reason"),
        "state": "exact_answer_ready",
        "answer_type": answer_type,
        "answer": answer,
        "count": count,
        "items": items,
        "semantic_available": True,
        "semantic_used": False,
        "degraded": degraded,
        "fallback_reason": fallback_reason,
        "unresolved_items": unresolved_items or [],
        "results": [],
        "evidence": evidence,
    }


def _plugin_answer_label(plugin_id: str | None, plugin_label: str, row_label: object) -> str:
    known_label = _known_plugin_display_name(plugin_id)
    if known_label:
        return known_label
    if row_label is not None:
        return enrich_plugin_label(str(row_label))
    return plugin_label


def _known_plugin_display_name(plugin_id: str | None) -> str | None:
    if plugin_id is None:
        return None
    return enrich_plugin_label(plugin_id).split(" (", 1)[0]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _enriched_plugin_labels(value: Any) -> list[str]:
    return [enrich_plugin_label(plugin_id) for plugin_id in _string_list(value)]


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else plural or f"{singular}s"
