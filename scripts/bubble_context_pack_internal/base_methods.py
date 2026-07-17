from .constants import ENTITY_DOMAINS, REGISTRY_DOMAINS
from .shared import build_entity_key, canonical_hash, iter_named_collection, unique_list


def collect_entities(self):
    for domain, (entity_type, folder) in ENTITY_DOMAINS.items():
        source = self.data.get(domain, {})
        actual_count = 0
        for source_key, raw in source.items():
            if not isinstance(raw, dict):
                continue
            actual_count += 1
            entity = self.make_entity(domain, entity_type, folder, source_key, raw)
            self.entities.append(entity)
        self.counts["source_domains"][domain] = {
            "total_entries": len(source) if isinstance(source, dict) else 0,
            "real_entries": actual_count,
        }


def add_id_registry_entry(self, source_id, entry):
    existing_keys = {item["entity_key"] for item in self.id_registry[source_id]}
    if entry["entity_key"] not in existing_keys:
        self.id_registry[source_id].append(entry)


def get_id_registry_entries(self, source_id):
    return list(self.id_registry.get(str(source_id), []))


def collect_registry_items(self):
    for domain in REGISTRY_DOMAINS:
        source = self.data.get(domain, {})
        actual_count = 0
        for source_key, raw in source.items():
            if not isinstance(raw, dict):
                continue
            actual_count += 1
            registry_item = self.make_registry_item(domain, source_key, raw)
            self.registry_items[domain].append(registry_item)
        self.counts["source_domains"][domain] = {
            "total_entries": len(source) if isinstance(source, dict) else 0,
            "real_entries": actual_count,
        }


def make_entity(self, domain, entity_type, folder, source_key, raw):
    source_id = self.derive_source_id(domain, source_key, raw)
    display_name = self.derive_display_name(domain, source_key, raw)
    source_path = self.derive_source_path(domain, source_key, source_id)
    entity_key = build_entity_key(entity_type, display_name, source_id)
    normalized_payload = self.normalize_payload(raw)
    overlay_links = self.overlay_manager.resolve_for_entity(entity_type, source_key, display_name)
    aliases = self.derive_aliases(domain, source_key, source_id, raw, display_name)
    entity = {
        "entity_key": entity_key,
        "entity_type": entity_type,
        "source_domain": domain,
        "source_key": source_key,
        "source_id": source_id,
        "source_path": source_path,
        "name": raw.get("name") or source_key,
        "display_name": display_name,
        "normalized_payload": normalized_payload,
        "raw_fragment_hash": canonical_hash(raw),
        "outbound_refs": [],
        "evidence": {
            "source_file": str(self.export_path),
            "source_path": source_path,
            "overlay_links": overlay_links,
        },
        "_raw": raw,
        "_folder": folder,
        "_aliases": aliases,
    }
    self.entity_lookup_by_key[entity_key] = entity
    self.entity_lookup_by_id[source_id].append(entity_key)
    self.path_registry[source_path] = entity_key
    self.add_id_registry_entry(
        source_id,
        {
            "entity_key": entity_key,
            "entity_type": entity_type,
            "artifact_path": f"structural/entities/{folder}/{entity_key}.json",
            "source_path": source_path,
        },
    )
    self.root_artifact_paths[entity["source_path"]] = f"structural/entities/{folder}/{entity_key}.json"
    aliases = [alias for alias in aliases if alias not in {None, ""}]
    entity["_aliases"] = aliases
    for alias in aliases:
        self.alias_to_entity[self.normalize_string(alias)].append(entity_key)
    self.counts["emitted_entities"][entity_type] += 1
    return entity


def make_registry_item(self, domain, source_key, raw):
    entity_type = REGISTRY_DOMAINS[domain]
    source_id = self.derive_source_id(domain, source_key, raw)
    display_name = self.derive_display_name(domain, source_key, raw)
    source_path = self.derive_source_path(domain, source_key, source_id)
    entity_key = build_entity_key(entity_type, display_name, source_id)
    normalized_payload = self.normalize_payload(raw)
    item = {
        "entity_key": entity_key,
        "entity_type": entity_type,
        "source_domain": domain,
        "source_key": source_key,
        "source_id": source_id,
        "source_path": source_path,
        "display_name": display_name,
        "normalized_payload": normalized_payload,
        "raw_fragment_hash": canonical_hash(raw),
        "evidence": {
            "source_file": str(self.export_path),
            "source_path": source_path,
        },
        "_raw": raw,
    }
    registry_path = f"structural/registries/{domain}.json#/{source_key}"
    self.add_id_registry_entry(
        source_id,
        {
            "entity_key": entity_key,
            "entity_type": entity_type,
            "artifact_path": registry_path,
            "source_path": source_path,
        },
    )
    self.path_registry[source_path] = entity_key
    self.entity_lookup_by_id[source_id].append(entity_key)
    return item


def derive_source_id(self, domain, source_key, raw):
    if isinstance(raw, dict) and raw.get("id"):
        return str(raw["id"])
    return str(source_key)


def derive_display_name(self, domain, source_key, raw):
    if domain == "api":
        return (
            raw.get("name")
            or raw.get("properties", {}).get("wf_name")
            or raw.get("properties", {}).get("event_name")
            or raw.get("default_name")
            or source_key
        )
    if domain == "user_types":
        return raw.get("display") or source_key
    if domain == "option_sets":
        return raw.get("display") or source_key
    if domain == "styles":
        return raw.get("display") or raw.get("id") or source_key
    if domain == "comments":
        return raw.get("type") or source_key
    return raw.get("name") or raw.get("default_name") or raw.get("display") or source_key


def derive_source_path(self, domain, source_key, source_id):
    if source_id in self.id_to_path:
        return self.id_to_path[source_id]
    if domain == "pages":
        return f"%p3.{source_id}"
    if domain == "element_definitions":
        return f"%ed.{source_id}"
    return f"{domain}.{source_key}"


def derive_aliases(self, domain, source_key, source_id, raw, display_name):
    candidates = [
        source_key,
        source_id,
        display_name,
        raw.get("name"),
        raw.get("default_name"),
        raw.get("display"),
        raw.get("properties", {}).get("wf_name") if isinstance(raw, dict) else None,
        raw.get("properties", {}).get("event_name") if isinstance(raw, dict) else None,
    ]
    if domain == "api":
        properties = raw.get("properties", {})
        for param_key, param_value in iter_named_collection("parameters", properties.get("parameters", {})):
            candidates.append(param_key)
            if isinstance(param_value, dict):
                candidates.append(param_value.get("key"))
    aliases = [candidate for candidate in candidates if candidate]
    return unique_list([str(alias) for alias in aliases])


def normalize_payload(self, value, parent_key=None):
    if isinstance(value, dict):
        normalized = {}
        for key, child in value.items():
            if key == "id":
                continue
            normalized[key] = self.normalize_payload(child, parent_key=key)
        return normalized
    if isinstance(value, list):
        return [self.normalize_payload(item, parent_key=parent_key) for item in value]
    if isinstance(value, str) and parent_key in {"api_tokens", "private_key", "secret", "token"}:
        return self.redact_secret_value(value)
    return value
