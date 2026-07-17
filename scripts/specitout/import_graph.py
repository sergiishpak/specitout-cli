from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bubble_context_pack_internal import ContextPackBuilder
from bubble_ingestion.transforms import (
    build_edges,
    build_entities,
    build_entity_facets,
    build_overlay_links,
    build_permission_surface_index,
    build_public_api_workflow_index,
    normalize_entity_parent_keys,
    order_entity_rows_for_upsert,
)
from specitout.backend_writes import prepare_rows_for_upsert


class _NullOverlayManager:
    def __init__(self) -> None:
        self.coverage = {
            "privacy_rules": {"matched": 0, "unmatched": 0},
            "backend_workflows_as_is": {"matched": 0, "unmatched": 0},
            "schema_prisma": {"matched": 0, "unmatched": 0},
        }

    def resolve_for_entity(self, entity_type: str, source_key: str, display_name: str) -> list[dict[str, Any]]:
        del entity_type, source_key, display_name
        return []

    def finalize_coverage(self) -> dict[str, dict[str, int]]:
        return self.coverage


@dataclass(frozen=True, slots=True)
class NormalizedImportGraph:
    entities: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    entity_facets: list[dict[str, Any]]
    overlay_links: list[dict[str, Any]]
    public_api_workflow_index: list[dict[str, Any]]
    permission_surface_index: list[dict[str, Any]]

    def summary(self) -> dict[str, int]:
        entities = prepare_rows_for_upsert("entities", self.entities)
        edges = prepare_rows_for_upsert("edges", self.edges)
        entity_facets = prepare_rows_for_upsert("entity_facets", self.entity_facets)
        overlay_links = prepare_rows_for_upsert("overlay_links", self.overlay_links)
        public_api_workflow_index = prepare_rows_for_upsert(
            "public_api_workflow_index",
            self.public_api_workflow_index,
        )
        permission_surface_index = prepare_rows_for_upsert(
            "permission_surface_index",
            self.permission_surface_index,
        )
        return {
            "entity_count": len(entities),
            "edge_count": len(edges),
            "unresolved_edge_count": sum(1 for row in edges if not bool(row.get("is_resolved", True))),
            "entity_facet_count": len(entity_facets),
            "overlay_link_count": len(overlay_links),
            "public_api_workflow_count": len(public_api_workflow_index),
            "permission_surface_count": len(permission_surface_index),
        }


def build_normalized_import_graph(
    *,
    export_id: str,
    app_slug: str,
    version_label: str,
    export_path: Path,
    source_export_hash: str,
) -> NormalizedImportGraph:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pack_dir = root / "pack"
        repo_root = root / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        (repo_root / app_slug).mkdir(parents=True, exist_ok=True)

        builder = ContextPackBuilder(
            export_path,
            pack_dir,
            repo_root,
            app_slug=app_slug,
            overlay_manager_factory=lambda _repo_root: _NullOverlayManager(),
        )
        builder.build()

        entity_rows, _matched_supplement_entities = build_entities(export_id, pack_dir)
        entity_rows = order_entity_rows_for_upsert(normalize_entity_parent_keys(entity_rows))
        edge_rows = build_edges(
            export_id,
            pack_dir,
            edge_id_scope=f"{app_slug}:{version_label}:{source_export_hash}",
        )
        return NormalizedImportGraph(
            entities=entity_rows,
            edges=edge_rows,
            entity_facets=build_entity_facets(export_id, entity_rows),
            overlay_links=build_overlay_links(export_id, entity_rows),
            public_api_workflow_index=build_public_api_workflow_index(export_id, pack_dir),
            permission_surface_index=build_permission_surface_index(export_id, pack_dir),
        )
