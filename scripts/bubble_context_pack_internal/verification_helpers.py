KNOWN_OVERLAY_KINDS = frozenset(
    {
        "privacy_rules_as_is",
        "backend_workflows_as_is",
        "schema_as_is",
        "database_schema_as_is",
    }
)


def overlay_links_are_valid(*, structural_records):
    for structural in structural_records.values():
        structural_evidence = structural.get("evidence") or {}
        overlay_links = structural_evidence.get("overlay_links") or []
        if not isinstance(overlay_links, list):
            return False
        for link in overlay_links:
            if not isinstance(link, dict):
                return False
            kind = link.get("kind")
            path = link.get("path")
            coverage = link.get("coverage")
            if not isinstance(path, str) or not path.strip():
                return False
            if kind == "source":
                continue
            if kind not in KNOWN_OVERLAY_KINDS:
                return False
            if coverage not in {None, "matched"}:
                return False
    return True


def summarize_verification_categories(
    *,
    registry_references_ok,
    entity_catalog_ok,
    path_registry_ok,
    outbound_edges_ok,
    synthetic_parents_ok,
    deterministic_synthetic_keys_ok,
    deterministic_synthetic_counts_ok,
    semantic_record_count_matches_entities,
    condition_chain_ok,
    permission_surface_ok,
    app_settings_ok,
    semantic_evidence_links_ok,
    overlay_coverage_complete,
    overlay_link_validation_complete=True,
    synthetic_paths_ok,
):
    return {
        "structural_completeness": all(
            (
                registry_references_ok,
                entity_catalog_ok,
                path_registry_ok,
                outbound_edges_ok,
                synthetic_parents_ok,
                deterministic_synthetic_keys_ok,
                deterministic_synthetic_counts_ok,
            )
        ),
        "semantic_completeness": all(
            (
                semantic_record_count_matches_entities,
                condition_chain_ok,
                permission_surface_ok,
                app_settings_ok,
            )
        ),
        "evidence_linkage": bool(semantic_evidence_links_ok),
        "augmentation_coverage": all((overlay_link_validation_complete, synthetic_paths_ok)),
    }


def semantic_evidence_links_map_to_structural_evidence(
    *,
    structural_records,
    semantic_records,
):
    for entity_key, structural in structural_records.items():
        semantic = semantic_records.get(entity_key)
        if semantic is None:
            return False
        semantic_links = semantic.get("evidence_links")
        if not isinstance(semantic_links, list) or not semantic_links:
            return False

        structural_evidence = structural.get("evidence") or {}
        valid_structural_links = {("source", structural_evidence.get("source_path"))}
        for link in structural_evidence.get("overlay_links") or []:
            kind = link.get("kind") if isinstance(link, dict) else None
            path = link.get("path") if isinstance(link, dict) else None
            if not kind or not path:
                return False
            valid_structural_links.add((kind, path))

        normalized_semantic_links = set()
        for link in semantic_links:
            if not isinstance(link, dict):
                return False
            kind = link.get("kind")
            path = link.get("path")
            if not kind or not path:
                return False
            normalized_semantic_links.add((kind, path))

        if not normalized_semantic_links:
            return False
        if normalized_semantic_links - valid_structural_links:
            return False

    return True
