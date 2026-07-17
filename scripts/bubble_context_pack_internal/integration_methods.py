import re
from collections import defaultdict

from .constants import INTEGRATION_ENTITY_FOLDERS
from .shared import canonical_hash, merge_redacted_records, safe_json_loads, unique_list


def build_registries(self):
    self.collect_registry_items()
    self.counts["emitted_registries"]["styles"] = len(self.registry_items["styles"])
    self.counts["emitted_registries"]["comments"] = len(self.registry_items["comments"])


def collect_integration_entities(self):
    self.collect_plugin_entities()
    self.collect_api_connector_entities()
    self.collect_app_connector_entities()
    self.collect_public_api_workflows()


def collect_plugin_entities(self):
    plugins = self.data.get("settings", {}).get("client_safe", {}).get("plugins", {})
    if not isinstance(plugins, dict):
        return
    self.counts["source_domains"]["settings.client_safe.plugins"] = {
        "total_entries": len(plugins),
        "real_entries": len(plugins),
    }
    for plugin_key, plugin_value in plugins.items():
        payload = {
            "plugin_key": plugin_key,
            "installed_value": plugin_value,
            "plugin_kind": "builtin" if isinstance(plugin_value, bool) else "marketplace",
        }
        entity = self.make_manual_entity(
            entity_type="plugin_installation",
            folder=INTEGRATION_ENTITY_FOLDERS["plugin_installation"],
            source_domain="settings.client_safe.plugins",
            source_key=plugin_key,
            source_id=str(plugin_key),
            source_path=f"settings.client_safe.plugins.{plugin_key}",
            display_name=str(plugin_key),
            normalized_payload=payload,
            raw_fragment_hash=canonical_hash(payload),
            raw=payload,
            aliases=unique_list([str(plugin_key), f"plugin {plugin_key}"]),
            evidence_links=[],
        )
        self.entities.append(entity)

    for entity in self.collect_observed_plugin_action_entities():
        self.entities.append(entity)


def collect_observed_plugin_action_entities(self):
    observed = defaultdict(list)

    def visit(value, path=""):
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key
                if key == "type" and isinstance(child, str) and re.match(r"^\d{10,}x\d+-[A-Za-z0-9]+$", child):
                    observed[child].append(child_path)
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(self.data)
    entities = []
    for action_type, paths in observed.items():
        plugin_id, _, action_suffix = action_type.rpartition("-")
        payload = {
            "plugin_id": plugin_id,
            "action_suffix": action_suffix,
            "observed_count": len(paths),
            "observed_paths": paths[:50],
        }
        entity = self.make_manual_entity(
            entity_type="plugin_action",
            folder=INTEGRATION_ENTITY_FOLDERS["plugin_action"],
            source_domain="observed.plugin_actions",
            source_key=action_type,
            source_id=action_type,
            source_path=f"observed.plugin_actions.{action_type}",
            display_name=action_type,
            normalized_payload=payload,
            raw_fragment_hash=canonical_hash(payload),
            raw=payload,
            aliases=unique_list([action_type, plugin_id, action_suffix]),
            evidence_links=[],
            parent_entity_key=self.find_integration_entity_key(plugin_id, "plugin_installation"),
        )
        self.integration_ref_lookup[action_type] = entity["entity_key"]
        entities.append(entity)
    return entities


def collect_api_connector_entities(self):
    client = self.data.get("settings", {}).get("client_safe", {}).get("apiconnector2", {})
    secure = self.data.get("settings", {}).get("secure", {}).get("apiconnector2", {})
    self.counts["source_domains"]["settings.client_safe.apiconnector2"] = {
        "total_entries": len(client) if isinstance(client, dict) else 0,
        "real_entries": len(client) if isinstance(client, dict) else 0,
    }
    self.counts["source_domains"]["settings.secure.apiconnector2"] = {
        "total_entries": len(secure) if isinstance(secure, dict) else 0,
        "real_entries": len(secure) if isinstance(secure, dict) else 0,
    }
    connector_ids = sorted(set(client.keys()) | set(secure.keys()))
    for connector_id in connector_ids:
        client_value = client.get(connector_id, {})
        secure_value = secure.get(connector_id, {})
        human_name = client_value.get("human") if isinstance(client_value, dict) else None
        display_name = human_name or client_value.get("name") if isinstance(client_value, dict) else connector_id
        payload = merge_redacted_records(
            self.normalize_integration_payload(client_value),
            self.normalize_integration_payload(secure_value),
        )
        connector_entity = self.make_manual_entity(
            entity_type="api_connector",
            folder=INTEGRATION_ENTITY_FOLDERS["api_connector"],
            source_domain="settings.apiconnector2",
            source_key=connector_id,
            source_id=connector_id,
            source_path=f"settings.client_safe.apiconnector2.{connector_id}",
            display_name=display_name or connector_id,
            normalized_payload=payload,
            raw_fragment_hash=canonical_hash(payload),
            raw=payload,
            aliases=unique_list([connector_id, display_name, human_name, "apiconnector2"]),
            evidence_links=[
                {"kind": "source", "path": f"settings.client_safe.apiconnector2.{connector_id}"},
                {"kind": "source", "path": f"settings.secure.apiconnector2.{connector_id}"},
            ],
        )
        self.entities.append(connector_entity)
        self.integration_ref_lookup[f"apiconnector2.{connector_id}"] = connector_entity["entity_key"]

        client_calls = client_value.get("calls", {}) if isinstance(client_value, dict) else {}
        secure_calls = secure_value.get("calls", {}) if isinstance(secure_value, dict) else {}
        for call_id in sorted(set(client_calls.keys()) | set(secure_calls.keys())):
            client_call = client_calls.get(call_id, {})
            secure_call = secure_calls.get(call_id, {})
            call_name = client_call.get("name") if isinstance(client_call, dict) else None
            payload = merge_redacted_records(
                self.normalize_integration_payload(client_call),
                self.normalize_integration_payload(secure_call),
            )
            call_entity = self.make_manual_entity(
                entity_type="api_connector_call",
                folder=INTEGRATION_ENTITY_FOLDERS["api_connector_call"],
                source_domain="settings.apiconnector2.calls",
                source_key=call_id,
                source_id=call_id,
                source_path=f"settings.client_safe.apiconnector2.{connector_id}.calls.{call_id}",
                display_name=call_name or call_id,
                normalized_payload=payload,
                raw_fragment_hash=canonical_hash(payload),
                raw=payload,
                aliases=unique_list(
                    [
                        call_id,
                        call_name or call_id,
                        f"apiconnector2-{connector_id}.{call_id}",
                        f"apiconnector2.{connector_id}.{call_id}",
                        f"api.apiconnector2.{connector_id}.{call_id}",
                        client_call.get("ret_value") if isinstance(client_call, dict) else None,
                        client_call.get("url") if isinstance(client_call, dict) else None,
                    ]
                ),
                evidence_links=[
                    {"kind": "source", "path": f"settings.client_safe.apiconnector2.{connector_id}.calls.{call_id}"},
                    {"kind": "source", "path": f"settings.secure.apiconnector2.{connector_id}.calls.{call_id}"},
                ],
                parent_entity_key=connector_entity["entity_key"],
            )
            self.entities.append(call_entity)
            self.integration_ref_lookup[f"apiconnector2-{connector_id}.{call_id}"] = call_entity["entity_key"]
            self.integration_ref_lookup[f"apiconnector2.{connector_id}.{call_id}"] = call_entity["entity_key"]
            self.integration_ref_lookup[f"api.apiconnector2.{connector_id}.{call_id}"] = call_entity["entity_key"]
            ret_value = client_call.get("ret_value") if isinstance(client_call, dict) else None
            if isinstance(ret_value, str):
                self.integration_ref_lookup[ret_value] = call_entity["entity_key"]


def normalize_integration_payload(self, value):
    value = self.normalize_payload(value)
    if not isinstance(value, dict):
        return value
    if "private_key" in value:
        value["private_key"] = self.redact_secret_value(value["private_key"])
    return value


def find_integration_entity_key(self, source_id, entity_type):
    for entry in self.get_id_registry_entries(source_id):
        if entry["entity_type"] == entity_type:
            return entry["entity_key"]
    return None
