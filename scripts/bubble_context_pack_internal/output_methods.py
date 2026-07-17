def write_outputs(self, verification):
    structural_root = self.output_dir / "structural"
    semantic_root = self.output_dir / "semantic"
    reports_root = self.output_dir / "reports"

    for entity in self.unique_entities():
        folder = entity.pop("_folder")
        raw = entity.pop("_raw")
        aliases = entity.pop("_aliases")
        entity_path = structural_root / "entities" / folder / f"{entity['entity_key']}.json"
        self.dependencies.json_writer(entity_path, entity)
        semantic = self.semantic_lookup[entity["entity_key"]]
        semantic_path = semantic_root / "entities" / folder / f"{entity['entity_key']}.json"
        self.dependencies.json_writer(semantic_path, semantic)
        entity["_folder"] = folder
        entity["_raw"] = raw
        entity["_aliases"] = aliases

    self.dependencies.json_writer(
        structural_root / "registries" / "styles.json",
        {"registry_type": "styles", "items": [self.strip_private_fields(item) for item in self.registry_items["styles"]]},
    )
    self.dependencies.json_writer(
        structural_root / "registries" / "comments.json",
        {"registry_type": "comments", "items": [self.strip_private_fields(item) for item in self.registry_items["comments"]]},
    )
    self.dependencies.json_writer(structural_root / "indexes" / "id_registry.json", self.id_registry)
    self.dependencies.json_writer(structural_root / "indexes" / "path_registry.json", self.path_registry)
    self.dependencies.jsonl_writer(structural_root / "indexes" / "entity_catalog.jsonl", self.build_entity_catalog())
    self.dependencies.jsonl_writer(structural_root / "indexes" / "edge_index.jsonl", self.edge_rows)
    self.dependencies.json_writer(structural_root / "indexes" / "manifest.json", self.build_manifest())
    self.dependencies.json_writer(structural_root / "indexes" / "unresolved_edges.json", self.unresolved_edges)

    self.dependencies.json_writer(semantic_root / "indexes" / "glossary.json", self.build_glossary())
    self.dependencies.json_writer(semantic_root / "indexes" / "capability_index.json", self.build_capability_index())
    self.dependencies.json_writer(semantic_root / "indexes" / "integration_index.json", self.build_integration_index())
    self.dependencies.json_writer(semantic_root / "indexes" / "public_api_workflows.json", self.build_public_api_workflows_index())
    self.dependencies.json_writer(semantic_root / "indexes" / "reverse_usage_index.json", self.build_reverse_usage_index())
    self.dependencies.json_writer(semantic_root / "indexes" / "query_hints.json", self.query_hints)
    self.dependencies.json_writer(semantic_root / "indexes" / "custom_state_index.json", self.build_entity_type_index("custom_state"))
    self.dependencies.json_writer(semantic_root / "indexes" / "field_index.json", self.build_entity_type_index("field"))
    self.dependencies.json_writer(semantic_root / "indexes" / "option_value_index.json", self.build_entity_type_index("option_value"))
    self.dependencies.json_writer(semantic_root / "indexes" / "event_index.json", self.build_entity_type_index("event"))
    self.dependencies.json_writer(semantic_root / "indexes" / "condition_index.json", self.build_entity_type_index("condition"))
    self.dependencies.json_writer(semantic_root / "indexes" / "expression_index.json", self.build_entity_type_index("dynamic_expression"))
    self.dependencies.json_writer(semantic_root / "indexes" / "data_source_index.json", self.build_entity_type_index("data_source"))
    self.dependencies.json_writer(semantic_root / "indexes" / "permission_surface_index.json", self.build_permission_surface_index())
    self.dependencies.json_writer(semantic_root / "indexes" / "data_api_surface.json", self.build_data_api_surface())
    self.dependencies.json_writer(semantic_root / "indexes" / "app_settings_summary.json", self.build_app_settings_summary())

    gap_report = self.build_gap_report()
    self.dependencies.json_writer(reports_root / "gap_report.json", {k: v for k, v in gap_report.items() if k != "markdown"})
    self.dependencies.text_writer(reports_root / "gap_report.md", gap_report["markdown"])
    self.dependencies.json_writer(reports_root / "verification_report.json", verification)
