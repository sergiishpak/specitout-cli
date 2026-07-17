from .constants import ROOT_ENTITY_FOLDERS, SYNTHETIC_ENTITY_FOLDERS
from .shared import (
    canonical_hash,
    classify_data_source_node,
    iter_named_collection,
    looks_like_expression_node,
    normalize_string,
    redact_secret_value,
    unique_list,
)


def collect_app_connector_entities(self):
    client = self.data.get("settings", {}).get("client_safe", {}).get("appconnector", {})
    secure = self.data.get("settings", {}).get("secure", {}).get("appconnector", {})
    self.counts["source_domains"]["settings.client_safe.appconnector"] = {
        "total_entries": len(client) if isinstance(client, dict) else 0,
        "real_entries": len(client) if isinstance(client, dict) else 0,
    }
    self.counts["source_domains"]["settings.secure.appconnector"] = {
        "total_entries": len(secure) if isinstance(secure, dict) else 0,
        "real_entries": len(secure) if isinstance(secure, dict) else 0,
    }
    connector_ids = sorted(set(client.keys()) | set(secure.keys()))
    for connector_id in connector_ids:
        client_value = client.get(connector_id, {})
        secure_value = secure.get(connector_id, {})
        display_name = client_value.get("name") if isinstance(client_value, dict) else connector_id
        payload = self.merge_redacted_records(
            self.normalize_integration_payload(client_value),
            self.normalize_integration_payload(secure_value),
        )
        connector_entity = self.make_manual_entity(
            entity_type="app_connector",
            folder=self.INTEGRATION_ENTITY_FOLDERS["app_connector"],
            source_domain="settings.appconnector",
            source_key=connector_id,
            source_id=connector_id,
            source_path=f"settings.client_safe.appconnector.{connector_id}",
            display_name=display_name or connector_id,
            normalized_payload=payload,
            raw_fragment_hash=canonical_hash(payload),
            raw=payload,
            aliases=unique_list(
                [
                    connector_id,
                    display_name,
                    client_value.get("domain") if isinstance(client_value, dict) else None,
                    "appconnector",
                ]
            ),
            evidence_links=[
                {"kind": "source", "path": f"settings.client_safe.appconnector.{connector_id}"},
                {"kind": "source", "path": f"settings.secure.appconnector.{connector_id}"},
            ],
        )
        self.entities.append(connector_entity)
        self.integration_ref_lookup[f"appconnector.{connector_id}"] = connector_entity["entity_key"]

        client_calls = client_value.get("calls", {}) if isinstance(client_value, dict) else {}
        for call_id in sorted(client_calls.keys()):
            client_call = client_calls.get(call_id, {})
            call_name = client_call.get("name") if isinstance(client_call, dict) else None
            payload = {"client_safe": self.normalize_integration_payload(client_call)}
            meta_data = self.safe_json_loads(client_value.get("meta_data")) if isinstance(client_value, dict) else None
            if meta_data:
                payload["connector_meta_data"] = meta_data
            call_entity = self.make_manual_entity(
                entity_type="app_connector_call",
                folder=self.INTEGRATION_ENTITY_FOLDERS["app_connector_call"],
                source_domain="settings.appconnector.calls",
                source_key=call_id,
                source_id=call_id,
                source_path=f"settings.client_safe.appconnector.{connector_id}.calls.{call_id}",
                display_name=call_name or call_id,
                normalized_payload=payload,
                raw_fragment_hash=canonical_hash(payload),
                raw=payload,
                aliases=unique_list(
                    [
                        call_id,
                        call_name or call_id,
                        f"appconnector.{call_id}",
                        f"api.appconnector.{connector_id}_{call_name}" if call_name else None,
                        client_value.get("domain") if isinstance(client_value, dict) else None,
                    ]
                ),
                evidence_links=[
                    {"kind": "source", "path": f"settings.client_safe.appconnector.{connector_id}.calls.{call_id}"},
                ],
                parent_entity_key=connector_entity["entity_key"],
            )
            self.entities.append(call_entity)
            self.integration_ref_lookup[f"appconnector.{call_id}"] = call_entity["entity_key"]
            if call_name:
                self.integration_ref_lookup[f"api.appconnector.{connector_id}_{call_name}"] = call_entity["entity_key"]


def collect_public_api_workflows(self):
    rows = []
    folder_lookup = self.settings_client_safe.get("api_wf_folder_list", {})
    for entity in self.entities:
        if entity["entity_type"] != "backend_workflow":
            continue
        raw = entity["_raw"]
        properties = raw.get("properties", {}) if isinstance(raw, dict) else {}
        if raw.get("type") != "APIEvent" or properties.get("expose") is not True:
            continue
        rows.append(
            {
                "entity_key": entity["entity_key"],
                "source_id": entity["source_id"],
                "display_name": entity["display_name"],
                "workflow_name": properties.get("wf_name") or entity["display_name"],
                "folder": properties.get("wf_folder"),
                "folder_name": folder_lookup.get(properties.get("wf_folder")),
                "trigger_option": properties.get("trigger_option"),
                "auth_unecessary": properties.get("auth_unecessary"),
                "include_headers": properties.get("include_headers"),
                "waiting_for_data": properties.get("waiting_for_data"),
                "return_200_if_not_run": properties.get("return_200_if_not_run"),
                "raw_data": properties.get("raw_data"),
                "data_type": properties.get("data_type"),
                "parameter_count": len(iter_named_collection("parameters", properties.get("parameters", {}))),
                "source_path": entity["source_path"],
            }
        )
    self.public_api_workflows = sorted(rows, key=lambda row: row["workflow_name"] or row["display_name"])


def collect_application_entities(self):
    self.counts["source_domains"]["application"] = {"total_entries": 1, "real_entries": 1}
    self.counts["source_domains"]["settings"] = {"total_entries": len(self.settings), "real_entries": len(self.settings)}
    app_display_name = (
        self.settings_client_safe.get("name")
        or self.settings_client_safe.get("appname")
        or self.export_path.stem
    )
    app_payload = {
        "export_file": self.export_path.name,
        "top_level_keys": sorted(self.data.keys()),
        "indexed_path_count": len(self.id_to_path),
        "source_domains": sorted(self.ENTITY_DOMAINS.keys()),
        "integration_domains": ["apiconnector2", "appconnector", "plugins"],
    }
    application = self.make_manual_entity(
        entity_type="application",
        folder=ROOT_ENTITY_FOLDERS["application"],
        source_domain="application",
        source_key="application",
        source_id=f"application::{self.export_path.name}",
        source_path="application",
        display_name=app_display_name,
        normalized_payload=app_payload,
        raw_fragment_hash=canonical_hash(app_payload),
        raw=app_payload,
        aliases=unique_list([app_display_name, self.export_path.stem, "bubble application"]),
        evidence_links=[],
    )
    self.entities.append(application)

    settings_payload = self.build_app_settings_payload()
    app_settings = self.make_manual_entity(
        entity_type="app_settings",
        folder=ROOT_ENTITY_FOLDERS["app_settings"],
        source_domain="settings",
        source_key="settings",
        source_id=f"app_settings::{self.export_path.name}",
        source_path="settings",
        display_name="App Settings",
        normalized_payload=settings_payload,
        raw_fragment_hash=canonical_hash(settings_payload),
        raw=settings_payload,
        aliases=unique_list(["settings", "app settings", "workflow api", "data api", "privacy", "api tokens"]),
        evidence_links=[
            {"kind": "source", "path": "settings.client_safe"},
            {"kind": "source", "path": "settings.secure"},
        ],
        parent_entity_key=application["entity_key"],
    )
    self.entities.append(app_settings)


def build_app_settings_payload(self):
    return {
        "client_safe_flags": {
            "exposes_get_api": self.settings_client_safe.get("exposes_get_api"),
            "exposes_wf_api": self.settings_client_safe.get("exposes_wf_api"),
            "first_popup_data_added": self.settings_client_safe.get("first_popup_data_added"),
            "first_repeating_group_data_added": self.settings_client_safe.get("first_repeating_group_data_added"),
        },
        "api_workflow_folders": self.normalize_payload(self.settings_client_safe.get("api_wf_folder_list", {})),
        "plugin_count": len(self.settings_client_safe.get("plugins", {})) if isinstance(self.settings_client_safe.get("plugins", {}), dict) else 0,
        "api_token_count": len(self.settings_secure.get("api_tokens", {})) if isinstance(self.settings_secure.get("api_tokens", {}), dict) else 0,
        "client_safe_keys": sorted(self.settings_client_safe.keys()),
        "secure_keys": sorted(self.settings_secure.keys()),
        "secure_redacted": redact_secret_value(
            {
                "api_tokens": self.settings_secure.get("api_tokens", {}),
                "zapier": self.settings_secure.get("zapier"),
            }
        ),
    }


def collect_synthetic_entities(self):
    base_entities = list(self.entities)
    self.collect_field_entities(base_entities)
    self.collect_option_value_entities(base_entities)
    self.collect_custom_state_entities(base_entities)
    self.collect_event_entities(base_entities)
    self.collect_element_state_entities(base_entities)
    self.collect_condition_entities(list(self.entities))
    self.collect_dynamic_expression_entities(list(self.entities))
    self.collect_data_source_entities(
        [entity for entity in self.entities if entity["entity_type"] == "dynamic_expression"]
    )


def collect_field_entities(self, base_entities):
    for entity in base_entities:
        if entity["entity_type"] != "user_type":
            continue
        for field_key, field_value in iter_named_collection("fields", entity["_raw"].get("fields", {})):
            if isinstance(field_value, dict):
                source_path = f"{entity['source_path']}.fields.{field_key}"
                display_name = field_value.get("display") or field_key
                aliases = [field_key, display_name, field_value.get("value"), "list" if field_value.get("is_list") else None]
                self.make_synthetic_entity("field", entity, source_path, display_name, field_value, source_key=field_key, aliases=aliases)


def collect_option_value_entities(self, base_entities):
    for entity in base_entities:
        if entity["entity_type"] != "option_set":
            continue
        for value_key, value_payload in iter_named_collection("values", entity["_raw"].get("values", {})):
            if isinstance(value_payload, dict):
                source_path = f"{entity['source_path']}.values.{value_key}"
                display_name = value_payload.get("display") or value_payload.get("name") or value_key
                aliases = [value_key, display_name, value_payload.get("name")]
                self.make_synthetic_entity("option_value", entity, source_path, display_name, value_payload, source_key=value_key, aliases=aliases)


def collect_custom_state_entities(self, base_entities):
    for entity in base_entities:
        raw = entity.get("_raw")
        if not isinstance(raw, dict):
            continue
        for state_key, state_value in iter_named_collection("custom_states", raw.get("custom_states", {})):
            if isinstance(state_value, dict):
                source_path = f"{entity['source_path']}.custom_states.{state_key}"
                display_name = state_value.get("display") or state_key
                aliases = [state_key, display_name, state_value.get("value"), state_value.get("default_val")]
                self.make_synthetic_entity("custom_state", entity, source_path, display_name, state_value, source_key=state_key, aliases=aliases)


def classify_event_family(self, workflow_type):
    if workflow_type == "APIEvent":
        return "api_workflow"
    if workflow_type == "DatabaseTriggerEvent":
        return "database_trigger"
    if workflow_type and "custom" in normalize_string(workflow_type):
        return "custom_event"
    return "ui_event"


def collect_event_entities(self, base_entities):
    for entity in base_entities:
        if entity["entity_type"] not in {"backend_workflow", "ui_workflow"}:
            continue
        raw = entity.get("_raw", {})
        properties = raw.get("properties", {}) if isinstance(raw, dict) else {}
        workflow_type = raw.get("type")
        payload = {
            "workflow_type": workflow_type,
            "event_family": self.classify_event_family(workflow_type),
            "properties": self.normalize_payload(properties),
        }
        display_name = properties.get("event_name") or properties.get("wf_name") or workflow_type or entity["display_name"]
        source_path = f"{entity['source_path']}.event"
        aliases = [display_name, workflow_type, properties.get("event_name"), properties.get("wf_name")]
        self.make_synthetic_entity("event", entity, source_path, display_name, payload, source_key="event", aliases=aliases)


def collect_element_state_entities(self, base_entities):
    eligible_types = {"page_node", "component_node", "mobile_view_node"}
    for entity in base_entities:
        if entity["entity_type"] not in eligible_types:
            continue
        raw = entity.get("_raw", {})
        for state_key, state_value in iter_named_collection("states", raw.get("states", {})):
            if isinstance(state_value, dict):
                source_path = f"{entity['source_path']}.states.{state_key}"
                property_names = sorted((state_value.get("properties") or {}).keys())
                display_name = ", ".join(property_names[:2]) if property_names else f"State {state_key}"
                aliases = [state_key, display_name, state_value.get("type"), *property_names[:5]]
                self.make_synthetic_entity("element_state", entity, source_path, display_name, state_value, source_key=state_key, aliases=aliases)


def collect_condition_entities(self, base_entities):
    for entity in base_entities:
        if entity["entity_type"] == "element_state":
            scan_value = entity.get("_raw")
            scan_path = entity["source_path"]
        elif entity["entity_type"] == "workflow_action":
            scan_value = entity.get("_raw", {}).get("properties", {})
            scan_path = f"{entity['source_path']}.properties"
        elif entity["entity_type"] == "user_type":
            scan_value = entity.get("_raw", {}).get("privacy_role", {})
            scan_path = f"{entity['source_path']}.privacy_role"
        else:
            continue
        for condition_path, condition_value in self.find_condition_nodes(scan_value, scan_path):
            if isinstance(condition_value, dict):
                self.make_synthetic_entity(
                    "condition",
                    entity,
                    condition_path,
                    self.derive_condition_display_name(condition_value, condition_path),
                    condition_value,
                    source_key=condition_path.rsplit(".", 1)[-1],
                    aliases=[condition_path],
                )


def find_condition_nodes(self, value, current_path):
    rows = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else key
                if key == "condition" and isinstance(child, dict):
                    rows.append((child_path, child))
                walk(child, child_path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")

    walk(value, current_path)
    return rows


def derive_condition_display_name(self, raw, source_path):
    profile = self.describe_expression(raw)
    label = f"{profile['primary_source'] or 'condition'} condition"
    if profile["operators"]:
        label = f"{label} {profile['operators'][0]}"
    return label


def collect_dynamic_expression_entities(self, base_entities):
    eligible = {
        "page",
        "component",
        "mobile_view",
        "page_node",
        "component_node",
        "mobile_view_node",
        "backend_workflow",
        "ui_workflow",
        "event",
        "field",
        "option_value",
        "custom_state",
    }
    for entity in base_entities:
        if entity["entity_type"] == "condition":
            roots = [("", entity["_raw"])] if looks_like_expression_node(entity["_raw"]) else []
        elif entity["entity_type"] == "workflow_action":
            roots = self.find_expression_roots(entity["_raw"].get("properties", {}), "properties", skip_keys={"condition"})
        elif entity["entity_type"] in eligible:
            roots = self.find_expression_roots(entity["_raw"].get("properties", {}), "properties")
        else:
            roots = []

        for relative_path, expression in roots:
            if isinstance(expression, dict):
                source_path = entity["source_path"] if not relative_path else f"{entity['source_path']}.{relative_path}"
                if source_path == entity["source_path"]:
                    source_path = f"{source_path}.expression"
                aliases = [relative_path, expression.get("type"), *self.describe_expression(expression)["operators"][:3]]
                self.make_synthetic_entity(
                    "dynamic_expression",
                    entity,
                    source_path,
                    self.derive_expression_display_name(expression, relative_path),
                    expression,
                    source_key=relative_path or "expression",
                    aliases=aliases,
                )


def find_expression_roots(self, value, current_path, skip_keys=None):
    rows = []
    skip_keys = set(skip_keys or [])

    def walk(node, path, parent_is_expression=False):
        if isinstance(node, dict):
            is_expression = looks_like_expression_node(node)
            if is_expression and not parent_is_expression:
                rows.append((path, node))
                return
            for key, child in node.items():
                if key not in skip_keys:
                    child_path = f"{path}.{key}" if path else key
                    walk(child, child_path, parent_is_expression=is_expression or parent_is_expression)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                child_path = f"{path}[{index}]" if path else f"[{index}]"
                walk(child, child_path, parent_is_expression=parent_is_expression)

    walk(value, current_path, parent_is_expression=False)
    return rows


def describe_expression(self, value):
    operators = []
    sources = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "Message" and node.get("name"):
                operators.append(str(node.get("name")))
            source_type = classify_data_source_node(node)
            if source_type:
                sources.append(source_type)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    unique_sources = unique_list(sources)
    return {
        "operators": unique_list(operators),
        "sources": unique_sources,
        "primary_source": unique_sources[0] if unique_sources else None,
    }


def derive_expression_display_name(self, raw, relative_path):
    profile = self.describe_expression(raw)
    label = f"{profile['primary_source'] or raw.get('type') or 'expression'} expression"
    if profile["operators"]:
        label = f"{label} {profile['operators'][0]}"
    if relative_path:
        tail = relative_path.rsplit(".", 1)[-1]
        if tail not in {"properties", "expression"}:
            label = f"{label} {tail}"
    return label


def collect_data_source_entities(self, expression_entities):
    for entity in expression_entities:
        for relative_path, source_node, source_kind in self.find_data_source_nodes(entity["_raw"]):
            source_path = entity["source_path"] if not relative_path else f"{entity['source_path']}.{relative_path}"
            if source_path == entity["source_path"]:
                source_path = f"{source_path}.source"
            aliases = [source_kind, source_node.get("properties", {}).get("name"), relative_path]
            self.make_synthetic_entity(
                "data_source",
                entity,
                source_path,
                self.derive_data_source_display_name(source_node, source_kind),
                source_node,
                source_key=relative_path or "source",
                aliases=aliases,
            )


def find_data_source_nodes(self, value):
    rows = []

    def walk(node, path):
        if isinstance(node, dict):
            source_kind = classify_data_source_node(node)
            if source_kind:
                rows.append((path, node, source_kind))
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else key
                walk(child, child_path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                child_path = f"{path}[{index}]" if path else f"[{index}]"
                walk(child, child_path)

    walk(value, "")
    return rows


def derive_data_source_display_name(self, raw, source_kind):
    properties = raw.get("properties", {}) if isinstance(raw, dict) else {}
    label = properties.get("name") or properties.get("param_id") or properties.get("element_id")
    return f"{source_kind} {label}" if label else source_kind
