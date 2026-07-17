from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from specitout.runtime import SpecItOutRuntimeError

FetchOne = Callable[[str, Mapping[str, object] | None], dict[str, object] | None]


def fetch_page_analysis_inventory(*, fetch_one: FetchOne, app_slug: str, export_id: str | None) -> dict[str, object]:
    row = _fetch_page_analysis_row(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    details = _page_analysis_details(row.get("items"))
    count = int(row.get("total_count") or len(details))
    return _exact_payload(
        row,
        app_slug=app_slug,
        answer_type="page_analysis_inventory",
        answer=f"{count} pages analyzed",
        count=count,
        items=[str(item["display_name"]) for item in details],
        evidence=["specitout.entities page descendants, outbound dependency edges, and inbound page references"],
        extra={
            "basis": "page analysis metrics from structural descendants and dependency edges",
            "details": details,
        },
    )


def fetch_most_complex_page_inventory(*, fetch_one: FetchOne, app_slug: str, export_id: str | None) -> dict[str, object]:
    row = _fetch_page_analysis_row(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    details = _page_analysis_details(row.get("items"))
    if not details:
        return _exact_payload(
            row,
            app_slug=app_slug,
            answer_type="most_complex_page_inventory",
            answer="0 pages analyzed",
            count=0,
            items=[],
            evidence=["specitout.entities page structural metrics"],
            extra={"basis": "page complexity score from structural descendants and dependency edges", "details": []},
        )
    max_score = max(_int_detail(item, "complexity_score") for item in details)
    winners = [item for item in details if _int_detail(item, "complexity_score") == max_score]
    names = [str(item["display_name"]) for item in winners]
    answer = (
        f"{names[0]} is the most complex page with score {max_score}"
        if len(names) == 1
        else f"{len(names)} pages tied for most complexity with score {max_score}"
    )
    return _exact_payload(
        row,
        app_slug=app_slug,
        answer_type="most_complex_page_inventory",
        answer=answer,
        count=max_score,
        items=names,
        evidence=[
            "weighted score: ui nodes + workflows*8 + actions*5 + conditions*3 + expressions*2 + custom states*4 + data sources*2 + integration edges*5 + referenced entities",
        ],
        extra={
            "basis": "page complexity score from structural descendants and dependency edges",
            "details": winners,
        },
    )


def fetch_stale_page_inventory(*, fetch_one: FetchOne, app_slug: str, export_id: str | None) -> dict[str, object]:
    row = _fetch_page_analysis_row(fetch_one=fetch_one, app_slug=app_slug, export_id=export_id)
    candidates = [_with_stale_reason(item) for item in _page_analysis_details(row.get("items")) if _is_stale_candidate(item)]
    count = len(candidates)
    return _exact_payload(
        row,
        app_slug=app_slug,
        answer_type="stale_page_inventory",
        answer=f"{count} stale page {_plural(count, 'candidate')}",
        count=count,
        items=[str(item["display_name"]) for item in candidates],
        evidence=[
            "export-only stale means non-entry pages with no inbound app references, or pages with deprecated/test/old naming hints",
            f"count basis: {int(row.get('total_count') or 0)} pages analyzed",
        ],
        extra={
            "basis": "export-only stale candidates: non-entry pages with no inbound app references or deprecated-looking names",
            "details": candidates,
        },
    )


def _fetch_page_analysis_row(*, fetch_one: FetchOne, app_slug: str, export_id: str | None) -> dict[str, object]:
    row = fetch_one(
        """
with recursive scope as (
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
pages as (
  select page.*
  from scope
  join specitout.entities page
    on page.export_id = scope.export_id
   and page.entity_type = 'page'
),
page_descendants(page_key, child_key, child_type, depth) as (
  select page.entity_key, child.entity_key, child.entity_type, 1
  from pages page
  join specitout.entities child
    on child.export_id = page.export_id
   and child.parent_entity_key = page.entity_key
  union all
  select descendants.page_key, child.entity_key, child.entity_type, descendants.depth + 1
  from page_descendants descendants
  join scope on true
  join specitout.entities child
    on child.export_id = scope.export_id
   and child.parent_entity_key = descendants.child_key
),
page_family as (
  select entity_key as page_key, entity_key from pages
  union
  select page_key, child_key from page_descendants
),
entity_metrics as (
  select
    page.entity_key,
    count(distinct descendant.child_key) filter (where descendant.child_type = 'page_node')::int as ui_node_count,
    count(distinct descendant.child_key) filter (where descendant.child_type = 'ui_workflow')::int as workflow_count,
    count(distinct descendant.child_key) filter (where descendant.child_type = 'workflow_action')::int as workflow_action_count,
    count(distinct descendant.child_key) filter (where descendant.child_type = 'condition')::int as condition_count,
    count(distinct descendant.child_key) filter (where descendant.child_type = 'dynamic_expression')::int as dynamic_expression_count,
    count(distinct descendant.child_key) filter (where descendant.child_type = 'custom_state')::int as custom_state_count,
    count(distinct descendant.child_key) filter (where descendant.child_type = 'data_source')::int as data_source_count
  from pages page
  left join page_descendants descendant on descendant.page_key = page.entity_key
  group by page.entity_key
),
edge_metrics as (
  select
    family.page_key,
    count(distinct edge.id)::int as dependency_edge_count,
    count(distinct edge.to_entity_key)::int as referenced_entity_count,
    count(distinct edge.id) filter (
      where edge.relation in ('api_connector_call', 'app_connector_call', 'plugin_action', 'plugin_installation')
         or target.entity_type in ('api_connector_call', 'app_connector_call', 'plugin_action', 'plugin_installation')
    )::int as integration_edge_count
  from page_family family
  left join specitout.edges edge
    on edge.export_id = (select export_id from scope)
   and edge.from_entity_key = family.entity_key
  left join specitout.entities target
    on target.export_id = edge.export_id
   and target.entity_key = edge.to_entity_key
  group by family.page_key
),
navigation_refs as (
  select
    page.entity_key,
    count(distinct edge.id)::int as inbound_reference_count
  from pages page
  left join specitout.edges edge
    on edge.export_id = page.export_id
   and edge.to_entity_key = page.entity_key
   and edge.relation in ('page', 'success_page', 'failure_page', 'reference')
   and not exists (
     select 1
     from page_family family
     where family.page_key = page.entity_key
       and family.entity_key = edge.from_entity_key
   )
  group by page.entity_key
),
scored_pages as (
  select
    page.display_name,
    page.entity_key,
    page.source_id,
    page.source_path,
    entity_metrics.ui_node_count,
    entity_metrics.workflow_count,
    entity_metrics.workflow_action_count,
    entity_metrics.condition_count,
    entity_metrics.dynamic_expression_count,
    entity_metrics.custom_state_count,
    entity_metrics.data_source_count,
    coalesce(edge_metrics.dependency_edge_count, 0) as dependency_edge_count,
    coalesce(edge_metrics.referenced_entity_count, 0) as referenced_entity_count,
    coalesce(edge_metrics.integration_edge_count, 0) as integration_edge_count,
    coalesce(navigation_refs.inbound_reference_count, 0) as inbound_reference_count,
    lower(coalesce(page.display_name, '') || ' ' || coalesce(page.source_id, '') || ' ' || coalesce(page.source_path, '')) ~
      '(^|[^a-z])(index|home|login|signup|reset|404)([^a-z]|$)' as entrypoint_like,
    lower(coalesce(page.display_name, '') || ' ' || coalesce(page.source_id, '') || ' ' || coalesce(page.source_path, '')) ~
      '(^|[^a-z])(old|deprecated|backup|copy|test|unused|legacy|archive)([^a-z]|$)' as deprecated_name_hint
  from pages page
  join entity_metrics on entity_metrics.entity_key = page.entity_key
  left join edge_metrics on edge_metrics.page_key = page.entity_key
  left join navigation_refs on navigation_refs.entity_key = page.entity_key
),
ranked_pages as (
  select
    *,
    (
      ui_node_count +
      workflow_count * 8 +
      workflow_action_count * 5 +
      condition_count * 3 +
      dynamic_expression_count * 2 +
      custom_state_count * 4 +
      data_source_count * 2 +
      integration_edge_count * 5 +
      referenced_entity_count
    )::int as complexity_score
  from scored_pages
)
select
  scope.resolved_export_id,
  scope.version_label,
  scope.export_selection_reason,
  coalesce(jsonb_agg(
    jsonb_build_object(
      'display_name', ranked_pages.display_name,
      'entity_key', ranked_pages.entity_key,
      'complexity_score', ranked_pages.complexity_score,
      'ui_node_count', ranked_pages.ui_node_count,
      'workflow_count', ranked_pages.workflow_count,
      'workflow_action_count', ranked_pages.workflow_action_count,
      'condition_count', ranked_pages.condition_count,
      'dynamic_expression_count', ranked_pages.dynamic_expression_count,
      'custom_state_count', ranked_pages.custom_state_count,
      'data_source_count', ranked_pages.data_source_count,
      'dependency_edge_count', ranked_pages.dependency_edge_count,
      'referenced_entity_count', ranked_pages.referenced_entity_count,
      'integration_edge_count', ranked_pages.integration_edge_count,
      'inbound_reference_count', ranked_pages.inbound_reference_count,
      'entrypoint_like', ranked_pages.entrypoint_like,
      'deprecated_name_hint', ranked_pages.deprecated_name_hint
    )
    order by ranked_pages.complexity_score desc, ranked_pages.display_name
  ) filter (where ranked_pages.entity_key is not null), '[]'::jsonb) as items,
  count(ranked_pages.entity_key)::int as total_count
from scope
left join ranked_pages on true
group by scope.resolved_export_id, scope.version_label, scope.export_selection_reason
""",
        {"app_slug": app_slug, "export_id": export_id, "allow_archived_app": False},
    )
    if row is None:
        raise SpecItOutRuntimeError("Page analysis inventory query returned no row.")
    return row


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


def _dict_list(value: Any) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _page_analysis_details(value: Any) -> list[dict[str, object]]:
    details = _dict_list(value)
    return sorted(
        details,
        key=lambda item: (-_int_detail(item, "complexity_score"), str(item.get("display_name") or "")),
    )


def _int_detail(item: Mapping[str, object], key: str) -> int:
    try:
        return int(item.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _is_stale_candidate(item: Mapping[str, object]) -> bool:
    if bool(item.get("deprecated_name_hint")):
        return True
    return _int_detail(item, "inbound_reference_count") == 0 and not bool(item.get("entrypoint_like"))


def _with_stale_reason(item: Mapping[str, object]) -> dict[str, object]:
    enriched = dict(item)
    reasons = []
    if _int_detail(item, "inbound_reference_count") == 0:
        reasons.append("no inbound page navigation/reference edges")
    if bool(item.get("deprecated_name_hint")):
        reasons.append("deprecated-looking name")
    enriched["reason"] = "; ".join(reasons) if reasons else "stale candidate"
    return enriched


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural or f"{singular}s"
