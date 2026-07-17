from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from bubble_ingestion_contract import OVERLAY_TYPE_BY_KIND, load_json, load_jsonl

from bubble_ingestion.constants import FACET_FIELDS
from bubble_ingestion.errors import IngestionError

EDGE_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "bubble-mcp/edge")


def normalize_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) >= 3}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _build_edge_id(
    *,
    edge_id_scope: str,
    from_entity_key: str,
    relation: str,
    to_entity_key: str,
    is_resolved: bool,
    evidence_path: str | None,
    edge_metadata_json: dict[str, Any],
) -> str:
    canonical_payload = _canonical_json(
        {
            "edge_id_scope": edge_id_scope,
            "from_entity_key": from_entity_key,
            "relation": relation,
            "to_entity_key": to_entity_key,
            "is_resolved": is_resolved,
            "evidence_path": evidence_path,
            "edge_metadata_json": edge_metadata_json,
        }
    )
    return str(uuid.uuid5(EDGE_ID_NAMESPACE, canonical_payload))


def build_plugin_supplement_records(inventory: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for artifact in inventory.artifacts:
        if artifact.role != "plugin_supplement":
            continue
        payload = load_json(Path(artifact.local_path))
        records.append(
            {
                "source_path": artifact.source_path,
                "plugin_key": str(payload["plugin_key"]),
                "summary": str(payload.get("summary") or ""),
                "captured_from": payload.get("captured_from"),
                "artifact_count": len(payload.get("artifacts") or []),
                "artifacts": payload.get("artifacts") or [],
                "token_set": normalize_tokens(str(payload["plugin_key"])),
            }
        )
    return records


def summarize_plugin_supplements(
    records: list[dict[str, Any]],
    *,
    matched_entity_keys: set[str] | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "count": len(records),
        "plugin_keys": sorted({record["plugin_key"] for record in records}),
        "augmentation_targets": ["context_pack", "entities", "semantic_layer", "verification"],
    }
    if matched_entity_keys is not None:
        summary["matched_entity_keys"] = sorted(matched_entity_keys)
        matched_plugins = {record["plugin_key"] for record in records if record.get("matched_entity_keys")}
        summary["matched_plugin_keys"] = sorted(matched_plugins)
        summary["unmatched_plugin_keys"] = sorted(
            {record["plugin_key"] for record in records if not record.get("matched_entity_keys")}
        )
    return summary


def build_entities(
    export_id: str,
    pack_dir: Path,
    *,
    plugin_supplements: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    rows = []
    matched_entity_keys: set[str] = set()
    for catalog_row in load_jsonl(pack_dir / "structural/indexes/entity_catalog.jsonl"):
        structural = load_json(pack_dir / catalog_row["artifact_path"])
        semantic = dict(load_json(pack_dir / catalog_row["semantic_artifact_path"]))
        display_name = (
            semantic.get("display_name")
            or structural.get("display_name")
            or structural.get("name")
            or catalog_row["entity_key"]
        )

        candidate_tokens = set()
        for value in (
            [catalog_row["entity_key"], str(display_name), semantic.get("summary") or ""]
            + list(semantic.get("aliases") or [])
            + list(semantic.get("keywords") or [])
            + list(semantic.get("external_integrations") or [])
        ):
            candidate_tokens.update(normalize_tokens(str(value)))

        derived_supplements = []
        for supplement in plugin_supplements or []:
            if not supplement["token_set"] or supplement["token_set"].isdisjoint(candidate_tokens):
                continue
            matched_entity_keys.add(catalog_row["entity_key"])
            supplement.setdefault("matched_entity_keys", set()).add(catalog_row["entity_key"])
            derived_supplements.append(
                {
                    "plugin_key": supplement["plugin_key"],
                    "summary": supplement["summary"],
                    "captured_from": supplement.get("captured_from"),
                    "artifact_count": supplement["artifact_count"],
                    "source_path": supplement["source_path"],
                }
            )
        if derived_supplements:
            semantic["supplemental_evidence"] = derived_supplements

        rows.append(
            {
                "export_id": export_id,
                "entity_key": catalog_row["entity_key"],
                "entity_type": catalog_row["entity_type"],
                "display_name": str(display_name),
                "source_id": catalog_row.get("source_id"),
                "source_path": catalog_row["source_path"],
                "parent_entity_key": catalog_row.get("parent_entity_key"),
                "is_synthetic": bool(catalog_row.get("is_synthetic")),
                "is_virtual": bool(catalog_row.get("is_virtual")),
                "summary": semantic.get("summary"),
                "structural_json": structural,
                "semantic_json": semantic,
            }
        )
    return rows, matched_entity_keys


def build_edges(
    export_id: str,
    pack_dir: Path,
    *,
    edge_id_scope: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    edge_id_scope = edge_id_scope or export_id
    for edge in load_jsonl(pack_dir / "structural/indexes/edge_index.jsonl"):
        edge_metadata_json = dict(edge)
        rows.append(
            {
                "id": _build_edge_id(
                    edge_id_scope=edge_id_scope,
                    from_entity_key=edge["from_entity_key"],
                    relation=edge["relation"],
                    to_entity_key=edge["to_entity_key"],
                    is_resolved=True,
                    evidence_path=edge.get("evidence_path"),
                    edge_metadata_json=edge_metadata_json,
                ),
                "export_id": export_id,
                "from_entity_key": edge["from_entity_key"],
                "relation": edge["relation"],
                "to_entity_key": edge["to_entity_key"],
                "is_resolved": True,
                "evidence_path": edge.get("evidence_path"),
                "edge_metadata_json": edge_metadata_json,
            }
        )
    for edge in load_json(pack_dir / "structural/indexes/unresolved_edges.json"):
        unresolved_target = edge.get("to_entity_key") or edge.get("to_source_id")
        if unresolved_target is None:
            raise IngestionError("unresolved edge must include to_entity_key or to_source_id")
        edge_metadata_json = dict(edge)
        rows.append(
            {
                "id": _build_edge_id(
                    edge_id_scope=edge_id_scope,
                    from_entity_key=edge["from_entity_key"],
                    relation=edge["relation"],
                    to_entity_key=unresolved_target,
                    is_resolved=False,
                    evidence_path=edge.get("evidence_path"),
                    edge_metadata_json=edge_metadata_json,
                ),
                "export_id": export_id,
                "from_entity_key": edge["from_entity_key"],
                "relation": edge["relation"],
                "to_entity_key": unresolved_target,
                "is_resolved": False,
                "evidence_path": edge.get("evidence_path"),
                "edge_metadata_json": edge_metadata_json,
            }
        )
    return rows


def build_entity_facets(export_id: str, entity_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    facets = []
    seen = set()
    for entity in entity_rows:
        semantic = entity["semantic_json"] or {}
        for facet_type, field_name in FACET_FIELDS:
            for value in semantic.get(field_name) or []:
                value_text = str(value).strip()
                if not value_text:
                    continue
                key = (entity["entity_key"], facet_type, value_text)
                if key in seen:
                    continue
                seen.add(key)
                facets.append(
                    {
                        "export_id": export_id,
                        "entity_key": entity["entity_key"],
                        "facet_type": facet_type,
                        "facet_value": value_text,
                    }
                )
    return facets


def order_entity_rows_for_upsert(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = list(rows)
    emitted: list[dict[str, Any]] = []
    emitted_keys: set[str] = set()
    available_keys = {str(row["entity_key"]) for row in rows}
    deferred_orphans: list[dict[str, Any]] = []
    while pending:
        progress = False
        next_pending: list[dict[str, Any]] = []
        for row in pending:
            parent_entity_key = row.get("parent_entity_key")
            if not parent_entity_key or parent_entity_key in emitted_keys:
                emitted.append(row)
                emitted_keys.add(str(row["entity_key"]))
                progress = True
                continue
            if parent_entity_key not in available_keys:
                deferred_orphans.append(row)
                progress = True
                continue
            next_pending.append(row)
        if not progress:
            emitted.extend(next_pending)
            break
        pending = next_pending
    emitted.extend(deferred_orphans)
    return emitted


def normalize_entity_parent_keys(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    available_keys = {str(row["entity_key"]) for row in rows}
    normalized = []
    for row in rows:
        item = dict(row)
        if item.get("parent_entity_key") and item["parent_entity_key"] not in available_keys:
            item["parent_entity_key"] = None
        normalized.append(item)
    return normalized


def build_overlay_links(export_id: str, entity_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for entity in entity_rows:
        evidence = (entity["structural_json"] or {}).get("evidence") or {}
        for link in evidence.get("overlay_links") or []:
            kind = link.get("kind")
            source_path = link.get("path")
            if not kind or kind == "source" or not source_path:
                continue
            dedupe_key = (entity["entity_key"], OVERLAY_TYPE_BY_KIND[kind], source_path)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rows.append(
                {
                    "export_id": export_id,
                    "overlay_type": OVERLAY_TYPE_BY_KIND[kind],
                    "entity_key": entity["entity_key"],
                    "source_path": source_path,
                    "overlay_json": link,
                }
            )
    return rows


def build_public_api_workflow_index(export_id: str, pack_dir: Path) -> list[dict[str, Any]]:
    payload = load_json(pack_dir / "semantic/indexes/public_api_workflows.json")
    rows = []
    for workflow in payload.get("workflows") or []:
        rows.append(
            {
                "export_id": export_id,
                "entity_key": workflow["entity_key"],
                "workflow_name": workflow["workflow_name"],
                "trigger_option": workflow.get("trigger_option"),
                "requires_auth": not bool(workflow.get("auth_unecessary")),
                "accepts_request_data": bool(workflow.get("waiting_for_data"))
                or int(workflow.get("parameter_count") or 0) > 0,
                "request_metadata_json": {
                    key: value
                    for key, value in workflow.items()
                    if key not in {"entity_key", "workflow_name", "display_name"}
                },
            }
        )
    return rows


def build_permission_surface_rows(export_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for user_type in payload.get("user_types") or []:
        rows.append(
            {
                "export_id": export_id,
                "entity_key": user_type["entity_key"],
                "source_path": user_type.get("source_path"),
                "privacy_role_count": int(user_type.get("privacy_role_count") or 0),
                "roles_json": list(user_type.get("roles") or []),
            }
        )
    return rows


def build_permission_surface_index(export_id: str, pack_dir: Path) -> list[dict[str, Any]]:
    payload = load_json(pack_dir / "semantic/indexes/permission_surface_index.json")
    return build_permission_surface_rows(export_id, payload)


def build_source_evidence_rows(export_id: str, inventory: Any) -> list[dict[str, Any]]:
    return [
        {
            "export_id": export_id,
            "evidence_role": row.role,
            "storage_bucket": row.storage_bucket,
            "storage_object_path": row.storage_object_path,
            "content_hash": row.content_hash,
            "source_path": row.source_path,
            "metadata_json": dict(row.metadata_json),
        }
        for row in inventory.source_evidence_plan
    ]
