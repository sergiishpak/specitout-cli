from dataclasses import fields
from pathlib import Path

from .application_methods import *
from .base_methods import *
from .constants import ENTITY_DOMAINS, INTEGRATION_ENTITY_FOLDERS
from .edge_methods import *
from .entity_support_methods import *
from .integration_methods import *
from .output_methods import write_outputs
from .overlay import OverlayManager
from .report_methods import *
from .semantic_methods import *
from .shared import (
    merge_redacted_records,
    normalize_index_path_tokens,
    normalize_string,
    redact_secret_value,
    safe_json_loads,
)
from .state import make_dependencies, make_initial_state
from .summary_methods import *


STATE_FIELD_NAMES = {field.name for field in fields(make_initial_state({}, None))}


class ContextPackBuilder:
    ENTITY_DOMAINS = ENTITY_DOMAINS
    INTEGRATION_ENTITY_FOLDERS = INTEGRATION_ENTITY_FOLDERS
    normalize_string = staticmethod(normalize_string)
    redact_secret_value = staticmethod(redact_secret_value)
    safe_json_loads = staticmethod(safe_json_loads)
    normalize_index_path_tokens = staticmethod(normalize_index_path_tokens)
    merge_redacted_records = staticmethod(merge_redacted_records)

    def __init__(
        self,
        export_path,
        output_dir,
        repo_root,
        *,
        app_slug=None,
        source_export_ref=None,
        source_bundle_manifest_ref=None,
        export_loader=None,
        overlay_manager_factory=None,
        clock=None,
        json_writer=None,
        jsonl_writer=None,
        text_writer=None,
    ):
        if overlay_manager_factory is None and not app_slug:
            raise ValueError("ContextPackBuilder requires app_slug when using the default overlay manager")
        object.__setattr__(self, "export_path", Path(export_path))
        object.__setattr__(self, "output_dir", Path(output_dir))
        object.__setattr__(self, "repo_root", Path(repo_root))
        object.__setattr__(self, "app_slug", app_slug)
        object.__setattr__(self, "source_export_ref", source_export_ref)
        object.__setattr__(self, "source_bundle_manifest_ref", source_bundle_manifest_ref)
        resolved_overlay_manager_factory = overlay_manager_factory or (
            lambda repo_root: OverlayManager(repo_root, app_slug=app_slug)
        )
        dependencies = make_dependencies(
            export_loader=export_loader,
            overlay_manager_factory=resolved_overlay_manager_factory,
            clock=clock,
            json_writer=json_writer,
            jsonl_writer=jsonl_writer,
            text_writer=text_writer,
        )
        object.__setattr__(self, "dependencies", dependencies)
        data = dependencies.export_loader(self.export_path)
        overlay_manager = dependencies.overlay_manager_factory(self.repo_root)
        object.__setattr__(self, "state", make_initial_state(data, overlay_manager))

    def __getattr__(self, name):
        if name in STATE_FIELD_NAMES:
            return getattr(self.state, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in {
            "export_path",
            "output_dir",
            "repo_root",
            "app_slug",
            "source_export_ref",
            "source_bundle_manifest_ref",
            "dependencies",
            "state",
        }:
            object.__setattr__(self, name, value)
            return
        if "state" in self.__dict__ and name in STATE_FIELD_NAMES:
            setattr(self.state, name, value)
            return
        object.__setattr__(self, name, value)

    def now_iso(self):
        return self.dependencies.clock()

    def unique_entities(self):
        return [self.entity_lookup_by_key[key] for key in sorted(self.entity_lookup_by_key.keys())]

    def unique_semantic_records(self):
        return [self.semantic_lookup[key] for key in sorted(self.semantic_lookup.keys())]

    def build(self):
        self.assemble_graph()
        placeholder_verification = {
            "generated_at": self.now_iso(),
            "checks": {},
            "counts": {},
            "overlay_coverage": {},
            "sample_query_bundles": [],
        }
        self.write_outputs(placeholder_verification)
        verification = self.build_verification_report()
        self.dependencies.json_writer(self.output_dir / "reports" / "verification_report.json", verification)
        return verification

    def assemble_graph(self):
        self.collect_entities()
        self.build_registries()
        self.collect_integration_entities()
        self.collect_application_entities()
        self.register_virtual_nodes_from_index()
        self.collect_synthetic_entities()
        self.extract_edges()
        self.attach_reverse_usage()
        self.build_semantics()


for _method_name in [
    "collect_entities",
    "add_id_registry_entry",
    "get_id_registry_entries",
    "collect_registry_items",
    "make_entity",
    "make_registry_item",
    "derive_source_id",
    "derive_display_name",
    "derive_source_path",
    "derive_aliases",
    "normalize_payload",
    "build_registries",
    "collect_integration_entities",
    "collect_plugin_entities",
    "collect_observed_plugin_action_entities",
    "collect_api_connector_entities",
    "normalize_integration_payload",
    "find_integration_entity_key",
    "collect_app_connector_entities",
    "collect_public_api_workflows",
    "collect_application_entities",
    "build_app_settings_payload",
    "collect_synthetic_entities",
    "collect_field_entities",
    "collect_option_value_entities",
    "collect_custom_state_entities",
    "classify_event_family",
    "collect_event_entities",
    "collect_element_state_entities",
    "collect_condition_entities",
    "find_condition_nodes",
    "derive_condition_display_name",
    "collect_dynamic_expression_entities",
    "find_expression_roots",
    "describe_expression",
    "derive_expression_display_name",
    "collect_data_source_entities",
    "find_data_source_nodes",
    "derive_data_source_display_name",
    "make_manual_entity",
    "make_synthetic_entity",
    "resolve_raw_by_source_path",
    "build_virtual_entity",
    "derive_virtual_display_name",
    "virtual_parent_path_aliases",
    "register_virtual_nodes_from_index",
    "classify_virtual_entity_type",
    "extract_edges",
    "scan_edges",
    "scan_integration_refs",
    "add_manual_parent_edges",
    "parent_child_relation",
    "build_app_settings_edges",
    "resolve_integration_reference",
    "match_integration_reference",
    "add_edge_candidate",
    "resolve_edge",
    "select_edge_candidates",
    "allowed_target_types_for_relation",
    "resolve_path_like_target",
    "attach_reverse_usage",
    "build_semantics",
    "collect_glossary_terms",
    "make_semantic_record",
    "capability_entry",
    "infer_integrations",
    "collect_text_sources",
    "make_summary",
    "count_ui_nodes",
    "count_nested_workflows",
    "build_reverse_usage_index",
    "build_glossary",
    "build_capability_index",
    "build_integration_index",
    "build_entity_type_index",
    "build_permission_surface_index",
    "build_data_api_surface",
    "build_app_settings_summary",
    "build_public_api_workflows_index",
    "build_entity_catalog",
    "build_manifest",
    "build_gap_report",
    "synthetic_repeatability_snapshot",
    "build_verification_report",
    "strip_private_fields",
    "write_outputs",
]:
    setattr(ContextPackBuilder, _method_name, globals()[_method_name])
