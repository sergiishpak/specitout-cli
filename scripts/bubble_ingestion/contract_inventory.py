from __future__ import annotations

from collections import Counter
from pathlib import Path

from bubble_ingestion.source_bundle import MaterializedSourceBundle
from bubble_ingestion_contract import (
    CANONICAL_UNIQUE_EVIDENCE_ROLES,
    EVIDENCE_ROLE_BUBBLE_EXPORT,
    EVIDENCE_ROLE_CONTEXT_PACK,
    EVIDENCE_ROLE_EDGE_INDEX,
    EVIDENCE_ROLE_ENTITY_CATALOG,
    EVIDENCE_ROLE_GAP_REPORT,
    EVIDENCE_ROLE_PLUGIN_SUPPLEMENT,
    EVIDENCE_ROLE_SOURCE_BUNDLE_MANIFEST,
    EVIDENCE_ROLE_UNRESOLVED_EDGES,
    EVIDENCE_ROLE_VERIFICATION_REPORT,
    LOAD_TARGET_BY_ROLE,
    PLUGIN_SUPPLEMENT_AUGMENTATION_TARGETS,
    PRESERVED_GAP_REPORT_PATHS,
    PRESERVED_SEMANTIC_INDEX_FILENAMES,
    IngestionInventory,
    artifact_record,
    load_json,
    load_jsonl,
    sort_artifacts,
    source_evidence_plan_from_artifact,
)

from bubble_ingestion.contract_artifacts import (
    build_overlay_artifacts,
    build_semantic_index_artifacts,
    collect_overlay_paths_from_structural_entities,
    validate_plugin_supplement,
)
from bubble_ingestion.contract_validation import (
    ValidationError,
    ensure_preserved_optional_files,
    ensure_required_pack_files,
    load_and_validate_entity_catalog,
    require_file,
    validate_manifest_counts,
    validate_verification_report,
)


def build_inventory(
    *,
    app_slug: str,
    version_label: str,
    pack_dir: Path,
    source_bundle: MaterializedSourceBundle,
) -> IngestionInventory:
    ensure_required_pack_files(pack_dir)
    optional_paths = ensure_preserved_optional_files(
        pack_dir,
        optional_paths=PRESERVED_GAP_REPORT_PATHS,
    )

    manifest = load_json(pack_dir / "structural/indexes/manifest.json")
    entity_catalog_rows, entity_type_counts = load_and_validate_entity_catalog(pack_dir)
    edge_rows = load_jsonl(pack_dir / "structural/indexes/edge_index.jsonl")
    unresolved_edges = load_json(pack_dir / "structural/indexes/unresolved_edges.json")
    public_api_workflows = load_json(pack_dir / "semantic/indexes/public_api_workflows.json")
    permission_surface = load_json(pack_dir / "semantic/indexes/permission_surface_index.json")
    verification_report = validate_verification_report(pack_dir / "reports/verification_report.json")
    validate_manifest_counts(
        manifest=manifest,
        entity_catalog_rows=entity_catalog_rows,
        entity_type_counts=entity_type_counts,
        edge_rows=edge_rows,
        unresolved_edges=unresolved_edges,
        public_api_workflows=public_api_workflows,
        permission_surface_index=permission_surface,
        expected_source_export=str(source_bundle.export_entry["storage_ref"]),
        expected_source_bundle_manifest=source_bundle.manifest_ref,
    )

    overlay_paths_by_kind, overlay_link_counts = collect_overlay_paths_from_structural_entities(pack_dir)
    overlay_artifacts, overlay_coverage = build_overlay_artifacts(
        app_slug=app_slug,
        version_label=version_label,
        source_bundle=source_bundle,
        overlay_paths_by_kind=overlay_paths_by_kind,
        overlay_link_counts=overlay_link_counts,
    )

    artifacts = [
        artifact_record(
            role=EVIDENCE_ROLE_SOURCE_BUNDLE_MANIFEST,
            path=source_bundle.manifest_local_path,
            app_slug=app_slug,
            version_label=version_label,
            source_path=source_bundle.manifest_logical_path,
            storage_bucket=source_bundle.manifest_storage_bucket,
            storage_object_path=source_bundle.manifest_storage_object_path,
            content_hash=source_bundle.manifest_content_hash,
            metadata_json={
                "manifest_ref": source_bundle.manifest_ref,
                "evidence_location": (
                    "external_object"
                    if source_bundle.manifest.get("manifest_location_kind") == "storage_object"
                    else "local_only"
                ),
            },
        ),
        artifact_record(
            role=EVIDENCE_ROLE_SOURCE_BUNDLE_MANIFEST,
            path=source_bundle.manifest_local_path,
            app_slug=app_slug,
            version_label=version_label,
            source_path=source_bundle.manifest_logical_path,
            storage_bucket=source_bundle.manifest_storage_bucket,
            storage_object_path=source_bundle.manifest_alias_storage_object_path,
            content_hash=source_bundle.manifest_content_hash,
            metadata_json={
                "manifest_ref": source_bundle.manifest_ref,
                "manifest_alias_ref": source_bundle.manifest_alias_ref,
                "alias": True,
                "evidence_location": (
                    "external_object"
                    if source_bundle.manifest.get("manifest_location_kind") == "storage_object"
                    else "local_only"
                ),
            },
        ),
        artifact_record(
            role=EVIDENCE_ROLE_BUBBLE_EXPORT,
            path=require_file(source_bundle.export_path, "Bubble export"),
            app_slug=app_slug,
            version_label=version_label,
            source_path=str(source_bundle.export_entry["logical_path"]),
            storage_bucket=str(source_bundle.export_entry["storage_bucket"]),
            storage_object_path=str(source_bundle.export_entry["storage_object_path"]),
            content_hash=str(source_bundle.export_entry["content_hash"]),
            canonical=True,
            metadata_json={
                "source_system": "bubble_export",
                "evidence_location": (
                    "external_object"
                    if source_bundle.export_entry.get("location_kind") == "storage_object"
                    else "local_only"
                ),
            },
        ),
        artifact_record(
            role=EVIDENCE_ROLE_CONTEXT_PACK,
            path=pack_dir / "structural/indexes/manifest.json",
            app_slug=app_slug,
            version_label=version_label,
            pack_dir=pack_dir,
            canonical=True,
            metadata_json={"pack_relative_path": "structural/indexes/manifest.json"},
        ),
        artifact_record(
            role=EVIDENCE_ROLE_VERIFICATION_REPORT,
            path=pack_dir / "reports/verification_report.json",
            app_slug=app_slug,
            version_label=version_label,
            pack_dir=pack_dir,
            metadata_json={"report_kind": "verification_report"},
        ),
        artifact_record(
            role=EVIDENCE_ROLE_ENTITY_CATALOG,
            path=pack_dir / "structural/indexes/entity_catalog.jsonl",
            app_slug=app_slug,
            version_label=version_label,
            pack_dir=pack_dir,
            metadata_json={"pack_relative_path": "structural/indexes/entity_catalog.jsonl"},
        ),
        artifact_record(
            role=EVIDENCE_ROLE_EDGE_INDEX,
            path=pack_dir / "structural/indexes/edge_index.jsonl",
            app_slug=app_slug,
            version_label=version_label,
            pack_dir=pack_dir,
            metadata_json={"pack_relative_path": "structural/indexes/edge_index.jsonl"},
        ),
        artifact_record(
            role=EVIDENCE_ROLE_UNRESOLVED_EDGES,
            path=pack_dir / "structural/indexes/unresolved_edges.json",
            app_slug=app_slug,
            version_label=version_label,
            pack_dir=pack_dir,
            metadata_json={"pack_relative_path": "structural/indexes/unresolved_edges.json"},
        ),
    ]

    for relative_path, path in sorted(optional_paths.items()):
        artifacts.append(
            artifact_record(
                role=EVIDENCE_ROLE_GAP_REPORT,
                path=path,
                app_slug=app_slug,
                version_label=version_label,
                pack_dir=pack_dir,
                metadata_json={"pack_relative_path": relative_path},
            )
        )

    artifacts.extend(
        build_semantic_index_artifacts(
            app_slug=app_slug,
            version_label=version_label,
            pack_dir=pack_dir,
            semantic_index_filenames=PRESERVED_SEMANTIC_INDEX_FILENAMES,
        )
    )
    artifacts.extend(overlay_artifacts)

    for supplement_entry, supplement_path in zip(
        source_bundle.plugin_supplement_entries,
        source_bundle.plugin_supplement_paths,
        strict=True,
    ):
        supplement_metadata = validate_plugin_supplement(supplement_path)
        artifacts.append(
            artifact_record(
                role=EVIDENCE_ROLE_PLUGIN_SUPPLEMENT,
                path=require_file(supplement_path, "plugin supplement"),
                app_slug=app_slug,
                version_label=version_label,
                source_path=str(supplement_entry["logical_path"]),
                storage_bucket=str(supplement_entry["storage_bucket"]),
                storage_object_path=str(supplement_entry["storage_object_path"]),
                content_hash=str(supplement_entry["content_hash"]),
                metadata_json={
                    "supplement_name": supplement_path.name,
                    "evidence_location": (
                        "external_object"
                        if supplement_entry.get("location_kind") == "storage_object"
                        else "local_only"
                    ),
                    **supplement_metadata,
                },
            )
        )

    artifacts = sort_artifacts(artifacts)
    source_evidence_plan = [source_evidence_plan_from_artifact(artifact) for artifact in artifacts]

    role_counts = Counter(artifact.role for artifact in artifacts)
    for canonical_role in CANONICAL_UNIQUE_EVIDENCE_ROLES:
        if role_counts[canonical_role] != 1:
            raise ValidationError(
                f"Expected exactly one {canonical_role} artifact, found {role_counts[canonical_role]}"
            )

    relational_load_plan = {
        "entities": {
            "load_target": "entities",
            "structural_json_source": "entity_catalog",
            "semantic_json_source": "entity_catalog",
            "summary_source": "semantic entity files",
            "entity_count": len(entity_catalog_rows),
            "entity_types": dict(sorted(entity_type_counts.items())),
        },
        "edges": {
            "load_target": "edges",
            "resolved_edges_source": "structural/indexes/edge_index.jsonl",
            "unresolved_edges_source": "structural/indexes/unresolved_edges.json",
            "resolved_edge_count": len(edge_rows),
            "unresolved_edge_count": len(unresolved_edges),
        },
        "overlay_links": {
            "load_target": "overlay_links",
            "source": "structural entity evidence.overlay_links",
            "overlay_kinds": dict(sorted(overlay_coverage.items())),
        },
        "public_api_workflow_index": {
            "load_target": "public_api_workflow_index",
            "source": "semantic/indexes/public_api_workflows.json",
            "row_count": public_api_workflows.get("count", 0),
        },
        "permission_surface_index": {
            "load_target": "permission_surface_index",
            "source": "semantic/indexes/permission_surface_index.json",
            "row_count": permission_surface.get("count", 0),
        },
        "plugin_supplements": {
            "load_target": "context_pack_augmentation",
            "source": "staged source-bundle plugin supplement files",
            "augmentation_targets": list(PLUGIN_SUPPLEMENT_AUGMENTATION_TARGETS),
            "count": role_counts.get(EVIDENCE_ROLE_PLUGIN_SUPPLEMENT, 0),
        },
        "artifact_roles": {role: LOAD_TARGET_BY_ROLE[role] for role in sorted(role_counts)},
    }

    validation_summary = {
        "required_pack_paths_checked": list(
            (
                "structural/indexes/manifest.json",
                "structural/indexes/entity_catalog.jsonl",
                "structural/indexes/edge_index.jsonl",
                "structural/indexes/unresolved_edges.json",
                "reports/verification_report.json",
            )
        ),
        "optional_pack_paths_checked": sorted(optional_paths.keys()),
        "entity_catalog_count": len(entity_catalog_rows),
        "edge_count": len(edge_rows),
        "unresolved_edge_count": len(unresolved_edges),
        "overlay_kinds": dict(sorted(overlay_coverage.items())),
        "verification_check_count": len(verification_report.get("checks") or {}),
        "artifact_count_by_role": dict(sorted(role_counts.items())),
    }

    return IngestionInventory(
        app_slug=app_slug,
        version_label=version_label,
        export_path=str(source_bundle.export_entry["logical_path"]),
        pack_dir=pack_dir.resolve().as_posix(),
        canonical_evidence_roles=sorted(CANONICAL_UNIQUE_EVIDENCE_ROLES),
        artifacts=artifacts,
        source_evidence_plan=source_evidence_plan,
        relational_load_plan=relational_load_plan,
        validation_summary=validation_summary,
    )
