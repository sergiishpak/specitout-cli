from collections import Counter

from .bundle import bundle_context_from_records
from .constants import SYNTHETIC_ENTITY_TYPES
from .verification_helpers import (
    semantic_evidence_links_map_to_structural_evidence,
    overlay_links_are_valid,
    summarize_verification_categories,
)


def build_manifest(self):
    overlay_coverage = self.overlay_manager.finalize_coverage()
    unique_entity_counts = Counter(entity["entity_type"] for entity in self.unique_entities())
    entity_catalog = self.build_entity_catalog()
    if self.source_export_ref:
        source_export = self.source_export_ref
    else:
        try:
            source_export = self.export_path.relative_to(self.repo_root).as_posix()
        except ValueError:
            source_export = str(self.export_path)
    manifest = {
        "generated_at": self.now_iso(),
        "source_export": source_export,
        "entity_counts": dict(unique_entity_counts),
        "synthetic_entity_counts": {
            entity_type: count
            for entity_type, count in sorted(unique_entity_counts.items())
            if entity_type in SYNTHETIC_ENTITY_TYPES
        },
        "synthetic_entity_count": sum(
            count for entity_type, count in unique_entity_counts.items() if entity_type in SYNTHETIC_ENTITY_TYPES
        ),
        "entity_catalog_count": len(entity_catalog),
        "registry_counts": self.counts["emitted_registries"],
        "source_domain_counts": self.counts["source_domains"],
        "id_registry_count": sum(len(entries) for entries in self.id_registry.values()),
        "id_registry_key_count": len(self.id_registry),
        "path_registry_count": len(self.path_registry),
        "edge_count": len(self.edge_rows),
        "unresolved_edge_count": len(self.unresolved_edges),
        "public_api_workflow_count": len(self.public_api_workflows),
        "permission_surface_index_count": self.build_permission_surface_index()["count"],
        "overlay_coverage": overlay_coverage,
        "artifact_roots": {
            "structural": "structural",
            "semantic": "semantic",
            "reports": "reports",
            "bundles": "bundles",
        },
    }
    if self.source_bundle_manifest_ref:
        manifest["source_bundle_manifest"] = self.source_bundle_manifest_ref
    return manifest


def build_gap_report(self):
    manifest = self.build_manifest()
    bullets = [
        "Bubble export context is sufficient for graph navigation and question answering, but not for faithful application rebuilds on its own.",
        "API Connector and Bubble App Connector definitions are represented, but plugin internals and custom plugin behavior remain incomplete.",
        "Runtime auth/session behavior and some live-editor protocol semantics remain outside the export-derived pack.",
        "Bubble privacy rules are represented, but they are not directly equivalent to Supabase RLS and need later translation.",
        "Workflow structure is present, but migration-grade execution intent still needs a target-stack intermediate representation.",
        "UI tree extraction helps trace flows and controls, but does not guarantee complete rendering and layout fidelity.",
        "Existing backend workflow AST coverage in the repo is partial and should be treated as an overlay, not a completeness proof.",
    ]
    markdown = [
        "# Bubble Context Pack Gap Report",
        "",
        f"- Generated at: `{manifest['generated_at']}`",
        f"- Source export: `{self.export_path}`",
        f"- Structural entities: `{sum(manifest['entity_counts'].values())}`",
        f"- Resolved edges: `{len(self.edge_rows)}`",
        f"- Unresolved edges: `{len(self.unresolved_edges)}`",
        "",
        "## Critical Gaps",
        *[f"- {bullet}" for bullet in bullets],
        "",
        "## Overlay Coverage",
    ]
    for overlay_name, stats in manifest["overlay_coverage"].items():
        markdown.append(f"- `{overlay_name}`: matched `{stats['matched']}`, unmatched `{stats['unmatched']}`")
    markdown.extend(["", "## Unresolved Reference Summary"])
    relation_counts = Counter(edge["relation"] for edge in self.unresolved_edges)
    if relation_counts:
        markdown.extend([f"- `{relation}`: `{count}` unresolved targets" for relation, count in relation_counts.most_common()])
    else:
        markdown.append("- No unresolved edge targets were detected.")

    return {
        "generated_at": manifest["generated_at"],
        "critical_gaps": bullets,
        "overlay_coverage": manifest["overlay_coverage"],
        "unresolved_edge_count": len(self.unresolved_edges),
        "unresolved_edge_relations": dict(relation_counts),
        "markdown": "\n".join(markdown) + "\n",
    }


def synthetic_repeatability_snapshot(self):
    synthetic_entities = [entity for entity in self.unique_entities() if entity.get("synthetic")]
    return {
        "keys": sorted(self.synthetic_entity_keys),
        "counts": {
            entity_type: count
            for entity_type, count in Counter(entity["entity_type"] for entity in synthetic_entities).items()
            if entity_type in SYNTHETIC_ENTITY_TYPES
        },
    }


def build_verification_report(self):
    manifest = self.build_manifest()
    unique_entities = self.unique_entities()
    unique_semantics = self.unique_semantic_records()
    entity_count = len(unique_entities)
    semantic_count = len(unique_semantics)
    registered_entity_keys = {entry["entity_key"] for entries in self.id_registry.values() for entry in entries}
    entity_catalog = self.build_entity_catalog()
    entity_catalog_keys = [row["entity_key"] for row in entity_catalog]
    registry_references_ok = {entity["entity_key"] for entity in unique_entities}.issubset(registered_entity_keys)
    entity_catalog_ok = (
        len(entity_catalog) == entity_count
        and len(entity_catalog_keys) == len(set(entity_catalog_keys))
        and set(entity_catalog_keys) == {entity["entity_key"] for entity in unique_entities}
    )
    path_registry_ok = all(entity["source_path"] in self.path_registry for entity in unique_entities)
    outbound_edges_ok = all(
        all(edge["to_entity_key"] in registered_entity_keys for edge in entity["outbound_refs"])
        for entity in unique_entities
    )
    synthetic_entities = [entity for entity in unique_entities if entity.get("synthetic")]
    synthetic_parents_ok = all(entity.get("parent_entity_key") for entity in synthetic_entities)
    synthetic_paths_ok = all(entity.get("source_path") and entity.get("raw_fragment_hash") for entity in synthetic_entities)
    repeatability_snapshot = self.synthetic_repeatability_snapshot()
    deterministic_synthetic_keys_ok = repeatability_snapshot == self.synthetic_repeatability_snapshot()
    deterministic_synthetic_counts_ok = repeatability_snapshot["counts"] == self.synthetic_repeatability_snapshot()["counts"]
    permission_surface = self.build_permission_surface_index()
    permission_surface_ok = permission_surface["count"] == sum(1 for entity in unique_entities if entity["entity_type"] == "user_type")
    app_settings_summary = self.build_app_settings_summary()
    app_settings_ok = (
        app_settings_summary["exposes_get_api"] == bool(self.settings_client_safe.get("exposes_get_api"))
        and app_settings_summary["exposes_wf_api"] == bool(self.settings_client_safe.get("exposes_wf_api"))
    )
    chain_relations = Counter(edge["relation"] for edge in self.edge_rows)
    condition_chain_ok = chain_relations["condition_expression"] > 0 and chain_relations["expression_data_source"] > 0
    semantic_records = {record["entity_key"]: record for record in unique_semantics}
    structural_records = {entity["entity_key"]: entity for entity in unique_entities}
    semantic_evidence_links_ok = semantic_evidence_links_map_to_structural_evidence(
        structural_records=structural_records,
        semantic_records=semantic_records,
    )
    overlay_coverage_complete = all(stats.get("unmatched", 0) == 0 for stats in (manifest.get("overlay_coverage") or {}).values())
    overlay_link_validation_complete = overlay_links_are_valid(
        structural_records=structural_records,
    )
    reverse_usage_index = self.build_reverse_usage_index()
    glossary = self.build_glossary()
    capability_index = self.build_capability_index()
    integration_index = self.build_integration_index()
    verification_categories = summarize_verification_categories(
        registry_references_ok=registry_references_ok,
        entity_catalog_ok=entity_catalog_ok,
        path_registry_ok=path_registry_ok,
        outbound_edges_ok=outbound_edges_ok,
        synthetic_parents_ok=synthetic_parents_ok,
        deterministic_synthetic_keys_ok=deterministic_synthetic_keys_ok,
        deterministic_synthetic_counts_ok=deterministic_synthetic_counts_ok,
        semantic_record_count_matches_entities=semantic_count == entity_count,
        condition_chain_ok=condition_chain_ok,
        permission_surface_ok=permission_surface_ok,
        app_settings_ok=app_settings_ok,
        semantic_evidence_links_ok=semantic_evidence_links_ok,
        overlay_coverage_complete=overlay_coverage_complete,
        overlay_link_validation_complete=overlay_link_validation_complete,
        synthetic_paths_ok=synthetic_paths_ok,
    )
    sample_queries = [
        {"query": "login functionality", "search_mode": "root"},
        {"query": "what is connected to ChatGPT/OpenAI", "search_mode": "root"},
        {"query": "who uses workflow Create Daily report URL", "search_mode": "root"},
        {"query": "describe the message guest chat schema", "search_mode": "root"},
        {"query": "where is custom state VisibleGroup used", "search_mode": "deep"},
        {"query": "why is this element visible", "search_mode": "deep"},
        {"query": "what fields can be modified via api", "search_mode": "deep"},
        {"query": "what drives this repeating group", "search_mode": "deep"},
        {"query": "how is current user used in this flow", "search_mode": "deep"},
    ]
    smoke_bundles = []
    for query_config in sample_queries:
        bundle = bundle_context_from_records(
            pack_root=self.output_dir,
            manifest=manifest,
            semantic_records=semantic_records,
            structural_records=structural_records,
            edge_rows=self.edge_rows,
            reverse_usage_index=reverse_usage_index,
            glossary=glossary,
            capability_index=capability_index,
            integration_index=integration_index,
            query_hints=self.query_hints,
            query=query_config["query"],
            max_hops=2,
            search_mode=query_config["search_mode"],
        )
        smoke_bundles.append(
            {
                "query": query_config["query"],
                "search_mode": query_config["search_mode"],
                "anchor_count": len(bundle["resolved_anchors"]),
                "entity_count": len(bundle["selected_entities"]),
                "edge_count": len(bundle["related_edges"]),
            }
        )

    return {
        "generated_at": manifest["generated_at"],
        "checks": {
            **verification_categories,
            "entity_registry_complete": registry_references_ok,
            "entity_catalog_complete": entity_catalog_ok,
            "path_registry_complete": path_registry_ok,
            "semantic_record_count_matches_entities": semantic_count == entity_count,
            "edge_targets_resolve_or_are_flagged": outbound_edges_ok,
            "synthetic_entities_have_parents": synthetic_parents_ok,
            "synthetic_entities_have_evidence": synthetic_paths_ok,
            "synthetic_ids_are_repeatable": deterministic_synthetic_keys_ok,
            "synthetic_counts_are_repeatable": deterministic_synthetic_counts_ok,
            "condition_expression_data_source_chain_present": condition_chain_ok,
            "permission_surface_index_reconciles": permission_surface_ok,
            "app_settings_summary_reconciles": app_settings_ok,
            "semantic_evidence_links_map_to_structural_evidence": semantic_evidence_links_ok,
            "overlay_coverage_complete": overlay_coverage_complete,
            "overlay_link_validation_complete": overlay_link_validation_complete,
        },
        "counts": {
            "entities": entity_count,
            "semantic_records": semantic_count,
            "edges": len(self.edge_rows),
            "unresolved_edges": len(self.unresolved_edges),
            "synthetic_entities": len(synthetic_entities),
        },
        "overlay_coverage": manifest["overlay_coverage"],
        "sample_query_bundles": smoke_bundles,
    }


def strip_private_fields(self, item):
    return {key: value for key, value in item.items() if not key.startswith("_")}
