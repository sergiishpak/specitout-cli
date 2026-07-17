from __future__ import annotations

from typing import Any


LOCAL_ONLY_EVIDENCE_BUCKET = "local-prepared"
EVIDENCE_LOCATION_EXTERNAL_OBJECT = "external_object"
EVIDENCE_LOCATION_LOCAL_ONLY = "local_only"

EXTERNAL_OBJECT_EVIDENCE_ROLES = frozenset(
    {
        "bubble_export",
        "source_bundle_manifest",
        "overlay_artifact",
        "plugin_supplement",
    }
)


def build_compact_source_evidence_rows(export_id: str, inventory: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in inventory.artifacts:
        metadata_json = dict(artifact.metadata_json)
        evidence_location = str(metadata_json.get("evidence_location") or "")
        if not evidence_location and artifact.role in EXTERNAL_OBJECT_EVIDENCE_ROLES:
            evidence_location = EVIDENCE_LOCATION_EXTERNAL_OBJECT
        else:
            evidence_location = evidence_location or EVIDENCE_LOCATION_LOCAL_ONLY

        if evidence_location == EVIDENCE_LOCATION_EXTERNAL_OBJECT:
            storage_bucket = artifact.storage_bucket
            storage_object_path = artifact.storage_object_path
        else:
            storage_bucket = LOCAL_ONLY_EVIDENCE_BUCKET
            storage_object_path = artifact.storage_object_path
            metadata_json.setdefault("logical_storage_object_path", artifact.storage_object_path)
        metadata_json["evidence_location"] = evidence_location
        metadata_json.setdefault("canonical", bool(artifact.canonical))
        rows.append(
            {
                "export_id": export_id,
                "evidence_role": artifact.role,
                "storage_bucket": storage_bucket,
                "storage_object_path": storage_object_path,
                "content_hash": artifact.content_hash,
                "source_path": artifact.source_path,
                "metadata_json": metadata_json,
            }
        )
    return rows


def evidence_row_requires_storage_delete(row: dict[str, Any]) -> bool:
    metadata_json = dict(row.get("metadata_json") or {})
    location = metadata_json.get("evidence_location")
    if location is None:
        return True
    return location == EVIDENCE_LOCATION_EXTERNAL_OBJECT
