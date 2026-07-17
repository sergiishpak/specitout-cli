from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from specitout.runtime import SpecItOutRuntimeError

FetchOne = Callable[[str, Mapping[str, object] | None], dict[str, object] | None]


def fetch_unused_option_set_inventory(*, fetch_one: FetchOne, app_slug: str, export_id: str | None) -> dict[str, object]:
    row = fetch_one(
        """
with scope as (
  select
    resolved.export_id,
    resolved.export_id::text as resolved_export_id,
    e.version_label,
    resolved.export_selection_reason::text as export_selection_reason
  from specitout.resolve_retrieval_scope(
    %(app_slug)s,
    %(export_id)s::uuid,
    %(allow_archived_app)s
  ) resolved
  join specitout.exports e on e.id = resolved.export_id
),
option_sets as (
  select opt.*
  from scope
  join specitout.entities opt
    on opt.export_id = scope.export_id
   and opt.entity_type = 'option_set'
),
text_refs as (
  select distinct lower(match[1]) as source_id
  from scope
  join specitout.entities ref
    on ref.export_id = scope.export_id
  cross join lateral regexp_matches(
    lower(
      coalesce(ref.summary, '') || ' ' ||
      coalesce(ref.structural_json::text, '') || ' ' ||
      coalesce(ref.semantic_json::text, '')
    ),
    'option\\.([a-z0-9_]+)',
    'g'
  ) as match
  where ref.entity_type not in ('option_set', 'option_value', 'app_connector', 'app_connector_call')
),
attribute_refs as (
  select distinct parent.entity_key
  from option_sets parent
  join specitout.edges def
    on def.export_id = parent.export_id
   and def.from_entity_key = parent.entity_key
   and def.relation = 'defines_option_value'
  join specitout.entities option_value
    on option_value.export_id = def.export_id
   and option_value.entity_key = def.to_entity_key
   and option_value.entity_type = 'option_value'
  join specitout.entities ref_value
    on ref_value.export_id = parent.export_id
   and ref_value.entity_type = 'option_value'
   and ref_value.parent_entity_key <> parent.entity_key
   and lower(coalesce(ref_value.structural_json #>> '{normalized_payload,type1}', '')) in (
     lower(option_value.display_name),
     lower(coalesce(option_value.structural_json #>> '{normalized_payload,db_value}', ''))
   )
),
used_option_sets as (
  select opt.entity_key
  from option_sets opt
  join text_refs ref on ref.source_id = lower(opt.source_id)
  union
  select entity_key from attribute_refs
),
unused_option_sets as (
  select opt.display_name
  from option_sets opt
  left join used_option_sets used on used.entity_key = opt.entity_key
  where used.entity_key is null
)
select
  scope.resolved_export_id,
  scope.version_label,
  scope.export_selection_reason,
  coalesce(jsonb_agg(unused_option_sets.display_name order by unused_option_sets.display_name)
    filter (where unused_option_sets.display_name is not null), '[]'::jsonb) as items,
  count(unused_option_sets.display_name)::int as total_count,
  (select count(*)::int from used_option_sets) as used_count,
  (select count(*)::int from option_sets) as option_set_count
from scope
left join unused_option_sets on true
group by scope.resolved_export_id, scope.version_label, scope.export_selection_reason
""",
        {"app_slug": app_slug, "export_id": export_id, "allow_archived_app": False},
    )
    if row is None:
        raise SpecItOutRuntimeError("Unused option set inventory query returned no row.")
    items = _string_list(row.get("items"))
    count = int(row.get("total_count") or len(items))
    used_count = int(row.get("used_count") or 0)
    total = int(row.get("option_set_count") or count + used_count)
    return _exact_payload(
        row,
        app_slug=app_slug,
        answer_type="unused_option_set_inventory",
        answer=f"{count} option sets with 0 usage",
        count=count,
        items=items,
        evidence=[
            "specitout.entities option_set references outside own definitions",
            f"count basis: {total} total option sets, {used_count} with detected references, {count} with zero references",
        ],
    )


def fetch_public_api_workflow_inventory(*, fetch_one: FetchOne, app_slug: str, export_id: str | None) -> dict[str, object]:
    row = fetch_one(
        """
select
  scope.export_id::text as resolved_export_id,
  e.version_label,
  scope.export_selection_reason::text as export_selection_reason,
  coalesce(jsonb_agg(workflow.display_name order by workflow.display_name)
    filter (where workflow.entity_key is not null), '[]'::jsonb) as items,
  count(workflow.entity_key)::int as total_count
from specitout.resolve_retrieval_scope(
  %(app_slug)s,
  %(export_id)s::uuid,
  %(allow_archived_app)s
) scope
join specitout.exports e on e.id = scope.export_id
left join specitout.edges exposure
  on exposure.export_id = scope.export_id
 and exposure.relation = 'workflow_api_exposure'
left join specitout.entities workflow
  on workflow.export_id = scope.export_id
 and workflow.entity_key = exposure.to_entity_key
 and workflow.entity_type = 'backend_workflow'
group by scope.export_id, e.version_label, scope.export_selection_reason
""",
        {"app_slug": app_slug, "export_id": export_id, "allow_archived_app": False},
    )
    if row is None:
        raise SpecItOutRuntimeError("Public API workflow inventory query returned no row.")
    items = _string_list(row.get("items"))
    count = int(row.get("total_count") or len(items))
    return _exact_payload(
        row,
        app_slug=app_slug,
        answer_type="public_api_workflow_inventory",
        answer=f"{count} public API workflows",
        count=count,
        items=items,
        evidence=["specitout.edges relation=workflow_api_exposure"],
    )


def fetch_most_used_option_set_inventory(
    *,
    fetch_one: FetchOne,
    app_slug: str,
    export_id: str | None,
) -> dict[str, object]:
    row = fetch_one(
        """
select
  scope.export_id::text as resolved_export_id,
  e.version_label,
  scope.export_selection_reason::text as export_selection_reason,
  e.metadata_json #>> '{registration,source_export_path}' as source_export_path,
  coalesce(jsonb_agg(
    jsonb_build_object('display_name', opt.display_name, 'source_id', opt.source_id)
    order by opt.display_name
  ) filter (where opt.entity_key is not null), '[]'::jsonb) as option_sets
from specitout.resolve_retrieval_scope(
  %(app_slug)s,
  %(export_id)s::uuid,
  %(allow_archived_app)s
) scope
join specitout.exports e on e.id = scope.export_id
left join specitout.entities opt
  on opt.export_id = scope.export_id
 and opt.entity_type = 'option_set'
group by scope.export_id, e.version_label, scope.export_selection_reason, e.metadata_json
""",
        {"app_slug": app_slug, "export_id": export_id, "allow_archived_app": False},
    )
    if row is None:
        raise SpecItOutRuntimeError("Most-used option set inventory query returned no row.")
    source_export_path = str(row.get("source_export_path") or "")
    export_text = _read_source_export_text(source_export_path)
    ranking = _rank_option_sets_by_raw_references(row.get("option_sets"), export_text)
    if not ranking:
        return _exact_payload(
            row,
            app_slug=app_slug,
            answer_type="most_used_option_set_inventory",
            answer="0 option set references detected",
            count=0,
            items=[],
            evidence=["registered Bubble export raw option references outside option-set inventory"],
        )
    max_count = ranking[0][1]
    winners = [display_name for display_name, count in ranking if count == max_count]
    answer = (
        f"{winners[0]} used by {max_count} references"
        if len(winners) == 1
        else f"{len(winners)} option sets tied for most usage, used by {max_count} references"
    )
    return _exact_payload(
        row,
        app_slug=app_slug,
        answer_type="most_used_option_set_inventory",
        answer=answer,
        count=max_count,
        items=winners,
        evidence=["registered Bubble export raw option.<key> references"],
    )


def _exact_payload(
    row: Mapping[str, object],
    *,
    app_slug: str,
    answer_type: str,
    answer: str,
    count: int,
    items: list[str],
    evidence: list[str],
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload = {
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
        "degraded": False,
        "fallback_reason": None,
        "unresolved_items": [],
        "results": [],
        "evidence": evidence,
    }
    if extra:
        payload.update(extra)
    return payload


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _read_source_export_text(source_export_path: str) -> str:
    if not source_export_path:
        raise SpecItOutRuntimeError("Most-used option set inventory requires a registered source export path.")
    path = Path(source_export_path)
    if not path.exists():
        raise SpecItOutRuntimeError(f"Registered source export file no longer exists: {source_export_path}")
    return path.read_text()


def _rank_option_sets_by_raw_references(value: Any, export_text: str) -> list[tuple[str, int]]:
    if not isinstance(value, list):
        return []
    ranked: list[tuple[str, int]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        display_name = str(item.get("display_name") or "")
        source_id = str(item.get("source_id") or "")
        if not display_name or not source_id:
            continue
        count = len(re.findall(rf"option\.{re.escape(source_id)}\b", export_text, flags=re.IGNORECASE))
        if count > 0:
            ranked.append((display_name, count))
    return sorted(ranked, key=lambda pair: (-pair[1], pair[0]))
