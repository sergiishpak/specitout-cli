from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from bubble_ingestion.source_bundle import MaterializedSourceBundle
from bubble_ingestion_contract import (
    EVIDENCE_ROLE_OVERLAY_ARTIFACT,
    EVIDENCE_ROLE_PLUGIN_SUPPLEMENT,
    EVIDENCE_ROLE_SEMANTIC_INDEX,
    OVERLAY_TYPE_BY_KIND,
    PLUGIN_SUPPLEMENT_AUGMENTATION_TARGETS,
    artifact_record,
    load_json,
)

from bubble_ingestion.contract_validation import ValidationError, require_file


def collect_overlay_paths_from_structural_entities(
    pack_dir: Path,
) -> tuple[dict[str, set[str]], dict[str, int]]:
    overlay_paths_by_kind: dict[str, set[str]] = defaultdict(set)
    overlay_link_counts: dict[str, int] = defaultdict(int)
    entities_root = pack_dir / "structural/entities"
    for path in sorted(entities_root.rglob("*.json")):
        entity = load_json(path)
        links = ((entity.get("evidence") or {}).get("overlay_links")) or []
        for link in links:
            kind = link.get("kind")
            overlay_path = link.get("path")
            if not kind or kind == "source" or not overlay_path:
                continue
            overlay_paths_by_kind[kind].add(overlay_path)
            overlay_link_counts[kind] += 1
    return overlay_paths_by_kind, dict(overlay_link_counts)


def build_overlay_artifacts(
    *,
    app_slug: str,
    version_label: str,
    source_bundle: MaterializedSourceBundle,
    overlay_paths_by_kind: dict[str, set[str]],
    overlay_link_counts: dict[str, int],
) -> tuple[list[Any], dict[str, int]]:
    artifacts = []
    coverage = {}
    known_kinds = set(OVERLAY_TYPE_BY_KIND)

    recorded_overlay_paths = {
        kind: set(paths)
        for kind, paths in overlay_paths_by_kind.items()
    }
    unknown_kinds = sorted(set(recorded_overlay_paths) - known_kinds)
    if unknown_kinds:
        raise ValidationError(
            f"Unsupported overlay kind referenced by structural evidence: {', '.join(unknown_kinds)}"
        )

    for kind in sorted(known_kinds):
        expected_entry = source_bundle.overlay_entries_by_kind.get(kind)
        expected_path = source_bundle.overlay_paths_by_kind.get(kind)
        recorded_paths = recorded_overlay_paths.get(kind, set())
        if recorded_paths and expected_entry is None:
            raise ValidationError(f"overlay kind {kind} is referenced by structural evidence but missing from the source bundle")
        if expected_entry is not None and recorded_paths and recorded_paths != {str(expected_entry["logical_path"])}:
            raise ValidationError(
                f"overlay kind {kind} references {sorted(recorded_paths)!r} "
                f"but the preserved artifact is {expected_entry['logical_path']!r}"
            )
        if recorded_paths:
            assert expected_path is not None
            require_file(expected_path, f"overlay artifact for {kind}")
            coverage[kind] = overlay_link_counts.get(kind, 0)
        elif expected_path is not None and expected_path.exists():
            coverage[kind] = 0
        else:
            continue

        assert expected_entry is not None
        assert expected_path is not None
        artifacts.append(
            artifact_record(
                role=EVIDENCE_ROLE_OVERLAY_ARTIFACT,
                path=expected_path,
                app_slug=app_slug,
                version_label=version_label,
                source_path=str(expected_entry["logical_path"]),
                storage_bucket=str(expected_entry["storage_bucket"]),
                storage_object_path=str(expected_entry["storage_object_path"]),
                content_hash=str(expected_entry["content_hash"]),
                metadata_json={
                    "overlay_kind": kind,
                    "overlay_type": OVERLAY_TYPE_BY_KIND[kind],
                    "matched_entity_link_count": coverage[kind],
                    "evidence_location": (
                        "external_object"
                        if expected_entry.get("location_kind") == "storage_object"
                        else "local_only"
                    ),
                },
            )
        )
    return artifacts, coverage


def validate_plugin_supplement(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValidationError(f"plugin supplement must contain a JSON object: {path}")
    if payload.get("supplement_type") != "plugin_supplement":
        raise ValidationError(
            f"plugin supplement {path} must declare supplement_type='plugin_supplement'"
        )
    if not payload.get("plugin_key"):
        raise ValidationError(f"plugin supplement {path} is missing plugin_key")
    if not payload.get("summary") and not payload.get("artifacts"):
        raise ValidationError(
            f"plugin supplement {path} must provide summary text or artifacts describing the augmentation"
        )
    artifacts = payload.get("artifacts") or []
    artifact_count = len(artifacts) if isinstance(artifacts, list) else 0
    return {
        "plugin_key": payload["plugin_key"],
        "supplement_type": payload["supplement_type"],
        "captured_from": payload.get("captured_from"),
        "artifact_count": artifact_count,
        "extends_context_pack": True,
        "augmentation_targets": list(PLUGIN_SUPPLEMENT_AUGMENTATION_TARGETS),
    }


def build_semantic_index_artifacts(
    *,
    app_slug: str,
    version_label: str,
    pack_dir: Path,
    semantic_index_filenames: tuple[str, ...],
) -> list[Any]:
    artifacts = []
    for filename in semantic_index_filenames:
        path = require_file(pack_dir / "semantic/indexes" / filename, f"semantic index {filename}")
        artifacts.append(
            artifact_record(
                role=EVIDENCE_ROLE_SEMANTIC_INDEX,
                path=path,
                app_slug=app_slug,
                version_label=version_label,
                pack_dir=pack_dir,
                metadata_json={"index_name": path.stem},
            )
        )
    return artifacts
