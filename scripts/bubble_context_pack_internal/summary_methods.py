from collections import Counter

from .constants import CAPABILITY_TAXONOMY, SYNTHETIC_ENTITY_TYPES, VIRTUAL_ENTITY_TYPES
from .shared import iter_named_collection, unique_list_of_dicts


def make_summary(self, entity, tags, domains, integrations, outbound_count, inbound_count):
    label = entity["display_name"]
    entity_type = entity["entity_type"].replace("_", " ")
    fragments = [f"{entity_type.title()} `{label}`"]
    if entity["entity_type"] == "application":
        fragments.append(f"describes the Bubble app export `{self.export_path.name}`")
    elif entity["entity_type"] == "app_settings":
        flags = entity["_raw"].get("client_safe_flags", {})
        fragments.append(f"captures app-level API/security settings (Data API exposed: {bool(flags.get('exposes_get_api'))}; Workflow API exposed: {bool(flags.get('exposes_wf_api'))})")
    elif entity["entity_type"] == "backend_workflow":
        workflow_type = entity["_raw"].get("type")
        action_count = len(iter_named_collection("actions", entity["_raw"].get("actions", {})))
        properties = entity["_raw"].get("properties", {})
        if workflow_type:
            fragments.append(f"is a {workflow_type} workflow")
        if workflow_type == "APIEvent" and properties.get("expose") is True:
            trigger = properties.get("trigger_option")
            auth_mode = "auth optional" if properties.get("auth_unecessary") else "auth required or inherited"
            fragments.append(f"is exposed as a public Bubble API workflow endpoint ({trigger or 'default'}; {auth_mode})")
        fragments.append(f"with {action_count} direct actions")
    elif entity["entity_type"] in {"page", "component"}:
        fragments.append(f"contains {self.count_ui_nodes(entity['_raw'])} UI nodes and {self.count_nested_workflows(entity['_raw'])} attached workflows")
    elif entity["entity_type"] == "user_type":
        fragments.append(f"defines {len(entity['_raw'].get('fields', {}))} fields and {len(entity['_raw'].get('privacy_role', {}))} privacy roles")
    elif entity["entity_type"] == "option_set":
        fragments.append(f"defines {len(entity['_raw'].get('values', {}))} option values")
    elif entity["entity_type"] == "field":
        list_flag = "list " if entity["_raw"].get("is_list") else ""
        fragments.append(f"declares a {list_flag}{entity['_raw'].get('value') or 'typed'} field")
    elif entity["entity_type"] == "option_value":
        fragments.append(f"is an option set value with {len(entity['_raw'].get('attributes', {}))} attributes")
    elif entity["entity_type"] == "custom_state":
        fragments.append(f"stores temporary UI state of type {entity['_raw'].get('value') or 'unknown'}")
        default_value = entity["_raw"].get("default_val")
        if default_value not in {None, ""}:
            fragments.append(f"default `{default_value}`")
    elif entity["entity_type"] == "event":
        family = entity["_raw"].get("event_family")
        fragments.append(f"is a {family or 'workflow'} trigger")
        if entity["_raw"].get("workflow_type"):
            fragments.append(f"workflow type {entity['_raw'].get('workflow_type')}")
    elif entity["entity_type"] == "element_state":
        property_names = sorted((entity["_raw"].get("properties") or {}).keys())
        if property_names:
            fragments.append(f"changes element properties: {', '.join(property_names[:4])}")
    elif entity["entity_type"] == "condition":
        profile = self.describe_expression(entity["_raw"])
        if profile["primary_source"]:
            fragments.append(f"guards behavior using {profile['primary_source']}")
        if profile["operators"]:
            fragments.append(f"operators: {', '.join(profile['operators'][:4])}")
    elif entity["entity_type"] == "dynamic_expression":
        profile = self.describe_expression(entity["_raw"])
        if profile["primary_source"]:
            fragments.append(f"starts from {profile['primary_source']}")
        if profile["operators"]:
            fragments.append(f"operator chain includes {', '.join(profile['operators'][:4])}")
    elif entity["entity_type"] == "data_source":
        fragments.append(f"is a runtime data source node of type {entity['_raw'].get('type')}")
        if entity["_raw"].get("properties", {}).get("name"):
            fragments.append(f"named `{entity['_raw'].get('properties', {}).get('name')}`")
    elif entity["entity_type"] == "api_connector":
        client = entity["_raw"].get("client_safe", {})
        if client.get("human"):
            fragments.append(f"describes the external connector `{client.get('human')}`")
        fragments.append(f"with {len((client or {}).get('calls', {}))} configured API Connector calls")
    elif entity["entity_type"] == "api_connector_call":
        client = entity["_raw"].get("client_safe", {})
        if client.get("method") and client.get("url"):
            fragments.append(f"calls {client.get('method').upper()} {client.get('url')}")
        if client.get("publish_as"):
            fragments.append(f"published in Bubble as {client.get('publish_as')}")
    elif entity["entity_type"] == "app_connector":
        client = entity["_raw"].get("client_safe", {})
        if client.get("domain"):
            fragments.append(f"connects to Bubble app domain `{client.get('domain')}`")
        fragments.append(f"with {len((client or {}).get('calls', {}))} app connector calls")
    elif entity["entity_type"] == "app_connector_call":
        client = entity["_raw"].get("client_safe", {})
        if client.get("type"):
            fragments.append(f"is an app connector call of type {client.get('type')}")
        if client.get("auth"):
            fragments.append(f"using auth mode {client.get('auth')}")
    elif entity["entity_type"] == "plugin_installation" and entity["_raw"].get("plugin_kind"):
        fragments.append(f"is a {entity['_raw'].get('plugin_kind')} plugin installation")
    elif entity["entity_type"] == "plugin_action":
        if entity["_raw"].get("plugin_id"):
            fragments.append(f"belongs to plugin `{entity['_raw'].get('plugin_id')}`")
        fragments.append(f"observed in {entity['_raw'].get('observed_count', 0)} workflow/action locations")
    elif entity["entity_type"] == "workflow_action" and entity["_raw"].get("type"):
        fragments.append(f"is a workflow action of type {entity['_raw'].get('type')}")
    elif entity["entity_type"] == "ui_workflow":
        workflow_type = entity["_raw"].get("type")
        if workflow_type:
            fragments.append(f"is a UI workflow of type {workflow_type}")
        fragments.append(f"with {len(iter_named_collection('actions', entity['_raw'].get('actions', {})))} direct actions")
    elif entity["entity_type"] in {"page_node", "component_node", "mobile_view_node", "backend_workflow_node"}:
        node_type = entity["_raw"].get("type") if isinstance(entity["_raw"], dict) else None
        child_count = len(iter_named_collection("elements", entity["_raw"].get("elements", {}))) if isinstance(entity["_raw"], dict) else 0
        workflow_count = len(iter_named_collection("workflows", entity["_raw"].get("workflows", {}))) if isinstance(entity["_raw"], dict) else 0
        if node_type:
            fragments.append(f"is a nested node of type {node_type}")
        if child_count or workflow_count:
            fragments.append(f"contains {child_count} child elements and {workflow_count} child workflows")
    if tags:
        fragments.append(f"Tags: {', '.join(sorted(tags))}")
    if integrations:
        fragments.append(f"Integrations: {', '.join(sorted(integrations))}")
    fragments.append(f"Depends on {outbound_count} linked entities and is used by {inbound_count} entities")
    return ". ".join(fragment for fragment in fragments if fragment) + "."


def count_ui_nodes(self, root):
    count = 0

    def visit(node):
        nonlocal count
        if isinstance(node, dict):
            if node.get("type"):
                count += 1
            for _, child in iter_named_collection("elements", node.get("elements", {})):
                visit(child)

    visit(root)
    return count


def count_nested_workflows(self, root):
    count = 0

    def visit(node):
        nonlocal count
        if isinstance(node, dict):
            count += len(iter_named_collection("workflows", node.get("workflows", {})))
            for _, child in iter_named_collection("elements", node.get("elements", {})):
                visit(child)

    visit(root)
    return count


def build_reverse_usage_index(self):
    index = {}
    for entity_key, semantic in self.semantic_lookup.items():
        index[entity_key] = {
            "display_name": semantic["display_name"],
            "entity_type": semantic["entity_type"],
            "used_by": [
                {
                    "from_entity_key": edge["from_entity_key"],
                    "relation": edge["relation"],
                    "evidence_path": edge["evidence_path"],
                }
                for edge in self.reverse_usage.get(entity_key, [])
            ],
        }
    return index


def build_glossary(self):
    return {
        "terms": {term: unique_list_of_dicts(entries) for term, entries in sorted(self.glossary_terms.items()) if len(term) >= 3},
        "taxonomy_synonyms": {capability: config["keywords"] for capability, config in CAPABILITY_TAXONOMY.items()},
    }


def build_capability_index(self):
    return {capability: unique_list_of_dicts(entries) for capability, entries in sorted(self.capability_index.items())}


def build_integration_index(self):
    return {integration: unique_list_of_dicts(entries) for integration, entries in sorted(self.integration_index.items())}


def build_entity_type_index(self, entity_type):
    entries = []
    for semantic in self.unique_semantic_records():
        if semantic["entity_type"] == entity_type:
            entries.append(
                {
                    "entity_key": semantic["entity_key"],
                    "display_name": semantic["display_name"],
                    "entity_type": semantic["entity_type"],
                    "summary": semantic["summary"],
                    "source_path": next((link["path"] for link in semantic["evidence_links"] if link.get("kind") == "source"), None),
                    "synthetic": semantic.get("synthetic", False),
                    "virtual": semantic.get("virtual", False),
                }
            )
    return {"count": len(entries), "entities": entries}


def build_permission_surface_index(self):
    rows = []
    for entity in self.unique_entities():
        if entity["entity_type"] != "user_type":
            continue
        roles = []
        for role_key, role_payload in iter_named_collection("privacy_role", entity["_raw"].get("privacy_role", {})):
            permissions = (role_payload or {}).get("permissions", {}) if isinstance(role_payload, dict) else {}
            condition_path = f"{entity['source_path']}.privacy_role.{role_key}.condition"
            roles.append(
                {
                    "role_key": role_key,
                    "display": (role_payload or {}).get("display") if isinstance(role_payload, dict) else role_key,
                    "permissions": permissions,
                    "has_condition": isinstance((role_payload or {}).get("condition"), dict) if isinstance(role_payload, dict) else False,
                    "condition_entity_key": self.path_registry.get(condition_path),
                }
            )
        rows.append(
            {
                "entity_key": entity["entity_key"],
                "display_name": entity["display_name"],
                "source_path": entity["source_path"],
                "privacy_role_count": len(roles),
                "roles": roles,
            }
        )
    return {"count": len(rows), "user_types": rows}


def build_data_api_surface(self):
    return {
        "exposes_get_api": bool(self.settings_client_safe.get("exposes_get_api")),
        "exposes_wf_api": bool(self.settings_client_safe.get("exposes_wf_api")),
        "public_workflow_count": len(self.public_api_workflows),
        "user_type_count": sum(1 for entity in self.entities if entity["entity_type"] == "user_type"),
        "public_workflow_entity_keys": [row["entity_key"] for row in self.public_api_workflows],
    }


def build_app_settings_summary(self):
    flags = self.settings_client_safe
    return {
        "display_name": "App Settings",
        "exposes_get_api": bool(flags.get("exposes_get_api")),
        "exposes_wf_api": bool(flags.get("exposes_wf_api")),
        "api_workflow_folder_count": len(flags.get("api_wf_folder_list", {})) if isinstance(flags.get("api_wf_folder_list", {}), dict) else 0,
        "plugin_count": len(flags.get("plugins", {})) if isinstance(flags.get("plugins", {}), dict) else 0,
        "api_token_count": len(self.settings_secure.get("api_tokens", {})) if isinstance(self.settings_secure.get("api_tokens", {}), dict) else 0,
    }


def build_public_api_workflows_index(self):
    return {"count": len(self.public_api_workflows), "workflows": self.public_api_workflows}


def build_entity_catalog(self):
    rows = []
    for entity in self.unique_entities():
        folder = entity.get("_folder")
        rows.append(
            {
                "entity_key": entity["entity_key"],
                "entity_type": entity["entity_type"],
                "artifact_path": f"structural/entities/{folder}/{entity['entity_key']}.json" if folder else None,
                "semantic_artifact_path": f"semantic/entities/{folder}/{entity['entity_key']}.json" if folder else None,
                "source_id": entity.get("source_id"),
                "source_path": entity.get("source_path"),
                "parent_entity_key": entity.get("parent_entity_key"),
                "is_synthetic": bool(entity.get("synthetic")),
                "is_virtual": entity["entity_type"] in VIRTUAL_ENTITY_TYPES,
            }
        )
    return rows
