import re

from .constants import EDGE_FIELD_NAMES
from .shared import unique_list_of_dicts


def extract_edges(self):
    self.manual_edge_rows = []
    for entity in self.entities:
        rows = []
        self.scan_edges(entity, entity["_raw"], entity["source_path"], rows)
        self.scan_integration_refs(entity, entity["_raw"], entity["source_path"], rows)
        self.add_manual_parent_edges(entity, rows)
        rows = unique_list_of_dicts(rows)
        entity["outbound_refs"] = rows
        self.edge_rows.extend(rows)

    styles_rows = []
    for item in self.registry_items["styles"]:
        rows = []
        self.scan_edges(item, item["_raw"], item["source_path"], rows)
        styles_rows.extend(rows)
    self.edge_rows.extend(styles_rows)
    for edge in unique_list_of_dicts(self.manual_edge_rows):
        self.edge_rows.append(edge)
        from_entity = self.entity_lookup_by_key.get(edge["from_entity_key"])
        if from_entity is not None:
            from_entity["outbound_refs"] = unique_list_of_dicts(from_entity["outbound_refs"] + [edge])


def scan_edges(self, entity, value, current_path, rows):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "id":
                continue
            child_path = f"{current_path}.{key}" if current_path else key
            if key in EDGE_FIELD_NAMES:
                self.add_edge_candidate(entity, key, child, child_path, rows)
            else:
                self.scan_edges(entity, child, child_path, rows)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            self.scan_edges(entity, child, f"{current_path}[{index}]", rows)


def scan_integration_refs(self, entity, value, current_path, rows):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{current_path}.{key}" if current_path else key
            if isinstance(child, str):
                self.resolve_integration_reference(entity, key, child, child_path, rows)
            self.scan_integration_refs(entity, child, child_path, rows)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            self.scan_integration_refs(entity, child, f"{current_path}[{index}]", rows)


def add_manual_parent_edges(self, entity, rows):
    parent_entity_key = entity.get("parent_entity_key")
    parent_entity = self.entity_lookup_by_key.get(parent_entity_key) if parent_entity_key else None
    if entity["entity_type"] in {"api_connector_call", "app_connector_call"} and parent_entity:
        rows.append(
            {
                "from_entity_key": entity["entity_key"],
                "from_source_path": entity["source_path"],
                "relation": "connector_parent",
                "to_source_id": parent_entity["source_id"],
                "to_entity_key": parent_entity_key,
                "to_entity_type": parent_entity["entity_type"],
                "evidence_path": entity["source_path"],
            }
        )
    elif entity["entity_type"] == "plugin_action" and parent_entity:
        rows.append(
            {
                "from_entity_key": entity["entity_key"],
                "from_source_path": entity["source_path"],
                "relation": "plugin_installation",
                "to_source_id": parent_entity["source_id"],
                "to_entity_key": parent_entity_key,
                "to_entity_type": parent_entity["entity_type"],
                "evidence_path": entity["source_path"],
            }
        )
    elif parent_entity:
        relation = self.parent_child_relation(entity, parent_entity)
        if relation:
            self.manual_edge_rows.append(
                {
                    "from_entity_key": parent_entity["entity_key"],
                    "from_source_path": parent_entity["source_path"],
                    "relation": relation,
                    "to_source_id": entity["source_id"],
                    "to_entity_key": entity["entity_key"],
                    "to_entity_type": entity["entity_type"],
                    "evidence_path": entity["source_path"],
                }
            )

    if entity["entity_type"] == "app_settings":
        self.manual_edge_rows.extend(self.build_app_settings_edges(entity))


def parent_child_relation(self, entity, parent_entity):
    relation_map = {
        "app_settings": "application_settings",
        "custom_state": "owner_custom_state",
        "field": "defines_field",
        "option_value": "defines_option_value",
        "event": "workflow_event",
        "element_state": "element_state",
        "condition": "element_state_condition" if parent_entity["entity_type"] == "element_state" else "condition",
        "dynamic_expression": "condition_expression" if parent_entity["entity_type"] == "condition" else "dynamic_expression",
        "data_source": "expression_data_source",
    }
    return relation_map.get(entity["entity_type"])


def build_app_settings_edges(self, app_settings_entity):
    rows = []
    for workflow in self.public_api_workflows:
        rows.append(
            {
                "from_entity_key": app_settings_entity["entity_key"],
                "from_source_path": app_settings_entity["source_path"],
                "relation": "workflow_api_exposure",
                "to_source_id": workflow["source_id"],
                "to_entity_key": workflow["entity_key"],
                "to_entity_type": "backend_workflow",
                "evidence_path": app_settings_entity["source_path"],
            }
        )
    for entity in self.entities:
        if entity["entity_type"] == "user_type":
            rows.append(
                {
                    "from_entity_key": app_settings_entity["entity_key"],
                    "from_source_path": app_settings_entity["source_path"],
                    "relation": "data_api_surface",
                    "to_source_id": entity["source_id"],
                    "to_entity_key": entity["entity_key"],
                    "to_entity_type": entity["entity_type"],
                    "evidence_path": app_settings_entity["source_path"],
                }
            )
    return rows


def resolve_integration_reference(self, entity, key, candidate, evidence_path, rows):
    for match in self.match_integration_reference(candidate):
        target = self.entity_lookup_by_key.get(match["entity_key"])
        if target:
            rows.append(
                {
                    "from_entity_key": entity["entity_key"],
                    "from_source_path": entity["source_path"],
                    "relation": match["relation"],
                    "to_source_id": target["source_id"],
                    "to_entity_key": target["entity_key"],
                    "to_entity_type": target["entity_type"],
                    "evidence_path": evidence_path,
                }
            )


def match_integration_reference(self, candidate):
    matches = []
    if candidate in self.integration_ref_lookup:
        entity_key = self.integration_ref_lookup[candidate]
        target = self.entity_lookup_by_key.get(entity_key)
        if target:
            matches.append({"entity_key": entity_key, "relation": target["entity_type"]})

    if candidate.startswith("api.apiconnector2."):
        parts = candidate.split(".")
        if len(parts) >= 4:
            alias = ".".join(parts[:4])
            entity_key = self.integration_ref_lookup.get(alias)
            target = self.entity_lookup_by_key.get(entity_key) if entity_key else None
            if target:
                matches.append({"entity_key": entity_key, "relation": target["entity_type"]})

    if "api_apiconnector2_" in candidate:
        for connector_id, call_id in re.findall(r"api_apiconnector2_([A-Za-z0-9]+)_([A-Za-z0-9]+)", candidate):
            alias = f"apiconnector2.{connector_id}.{call_id}"
            entity_key = self.integration_ref_lookup.get(alias)
            target = self.entity_lookup_by_key.get(entity_key) if entity_key else None
            if target:
                matches.append({"entity_key": entity_key, "relation": target["entity_type"]})

    if candidate.startswith("api.appconnector."):
        exact = self.integration_ref_lookup.get(candidate)
        target = self.entity_lookup_by_key.get(exact) if exact else None
        if target:
            matches.append({"entity_key": exact, "relation": target["entity_type"]})

    return unique_list_of_dicts(matches)


def add_edge_candidate(self, entity, relation, candidate, evidence_path, rows):
    if isinstance(candidate, str):
        self.resolve_edge(entity, relation, candidate, evidence_path, rows)
    elif isinstance(candidate, dict):
        for nested_key, nested_value in candidate.items():
            self.add_edge_candidate(entity, relation, nested_value, f"{evidence_path}.{nested_key}", rows)
    elif isinstance(candidate, list):
        for index, nested_value in enumerate(candidate):
            self.add_edge_candidate(entity, relation, nested_value, f"{evidence_path}[{index}]", rows)


def resolve_edge(self, entity, relation, target_source_id, evidence_path, rows):
    if target_source_id == entity["source_id"]:
        return
    registry_candidates = self.select_edge_candidates(relation, str(target_source_id))
    if registry_candidates:
        for registry_entry in registry_candidates:
            rows.append(
                {
                    "from_entity_key": entity["entity_key"],
                    "from_source_path": entity["source_path"],
                    "relation": relation,
                    "to_source_id": str(target_source_id),
                    "to_entity_key": registry_entry["entity_key"],
                    "to_entity_type": registry_entry["entity_type"],
                    "evidence_path": evidence_path,
                }
            )
        return

    resolved_path_target = self.resolve_path_like_target(str(target_source_id))
    if resolved_path_target:
        for registry_entry in resolved_path_target:
            rows.append(
                {
                    "from_entity_key": entity["entity_key"],
                    "from_source_path": entity["source_path"],
                    "relation": relation,
                    "to_source_id": str(target_source_id),
                    "to_entity_key": registry_entry["entity_key"],
                    "to_entity_type": registry_entry["entity_type"],
                    "evidence_path": evidence_path,
                }
            )
        return

    self.unresolved_edges.append(
        {
            "from_entity_key": entity["entity_key"],
            "relation": relation,
            "to_source_id": str(target_source_id),
            "evidence_path": evidence_path,
        }
    )


def select_edge_candidates(self, relation, target_source_id):
    candidates = self.get_id_registry_entries(target_source_id)
    if not candidates:
        return []
    allowed_types = self.allowed_target_types_for_relation(relation)
    filtered = [candidate for candidate in candidates if candidate["entity_type"] in allowed_types]
    return filtered or candidates


def allowed_target_types_for_relation(self, relation):
    if relation == "style":
        return {"style"}
    if relation in {"api_event", "custom_event", "workflow_api_exposure"}:
        return {"backend_workflow"}
    if relation == "workflow_event":
        return {"event"}
    if relation == "data_api_surface":
        return {"user_type"}
    if relation == "action_id":
        return {"workflow_action"}
    if relation == "event_id":
        return {"backend_workflow", "ui_workflow", "event"}
    if relation == "owner_custom_state":
        return {"custom_state"}
    if relation == "defines_field":
        return {"field"}
    if relation == "defines_option_value":
        return {"option_value"}
    if relation == "element_state":
        return {"element_state"}
    if relation in {"condition", "element_state_condition"}:
        return {"condition"}
    if relation in {"condition_expression", "dynamic_expression"}:
        return {"dynamic_expression"}
    if relation == "expression_data_source":
        return {"data_source"}
    if relation in {"element_id", "current_parent", "cell_main_axis_id", "reference", "page", "success_page", "failure_page"}:
        return {"page", "component", "mobile_view", "page_node", "component_node", "mobile_view_node"}
    return {entry["entity_type"] for entries in self.id_registry.values() for entry in entries}


def resolve_path_like_target(self, target_source_id):
    if "." not in target_source_id:
        return []
    source_id, suffix = target_source_id.split(".", 1)
    normalized_suffix = ".".join(self.normalize_index_path_tokens(suffix.split(".")))
    resolved = []
    for entry in self.get_id_registry_entries(source_id):
        source_path = entry.get("source_path")
        if not source_path:
            continue
        derived_path = f"{source_path}.{normalized_suffix}"
        entity_key = self.path_registry.get(derived_path)
        if not entity_key:
            continue
        for candidate_entries in self.id_registry.values():
            for candidate in candidate_entries:
                if candidate["entity_key"] == entity_key:
                    resolved.append(candidate)
    return unique_list_of_dicts(resolved)


def attach_reverse_usage(self):
    for edge in self.edge_rows:
        self.reverse_usage[edge["to_entity_key"]].append(edge)
