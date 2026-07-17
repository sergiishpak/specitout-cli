from .constants import SYNTHETIC_ENTITY_FOLDERS, VIRTUAL_ENTITY_TYPE_FOLDERS
from .shared import (
    build_entity_key,
    canonical_hash,
    classify_index_path,
    make_synthetic_source_id,
    normalize_index_path_tokens,
    normalize_string,
    unique_list,
)


def make_manual_entity(
    self,
    entity_type,
    folder,
    source_domain,
    source_key,
    source_id,
    source_path,
    display_name,
    normalized_payload,
    raw_fragment_hash,
    raw,
    aliases,
    evidence_links,
    parent_entity_key=None,
    synthetic=False,
):
    entity_key = build_entity_key(entity_type, display_name, source_id, compact=synthetic)
    entity = {
        "entity_key": entity_key,
        "entity_type": entity_type,
        "source_domain": source_domain,
        "source_key": source_key,
        "source_id": str(source_id),
        "source_path": source_path,
        "name": display_name,
        "display_name": display_name,
        "normalized_payload": normalized_payload,
        "raw_fragment_hash": raw_fragment_hash,
        "outbound_refs": [],
        "evidence": {
            "source_file": str(self.export_path),
            "source_path": source_path,
            "overlay_links": evidence_links,
        },
        "_raw": raw,
        "_folder": folder,
        "_aliases": aliases,
    }
    if synthetic:
        entity["synthetic"] = True
    if parent_entity_key:
        entity["parent_entity_key"] = parent_entity_key
    self.entity_lookup_by_key[entity_key] = entity
    self.entity_lookup_by_id[str(source_id)].append(entity_key)
    self.path_registry[source_path] = entity_key
    self.add_id_registry_entry(
        str(source_id),
        {
            "entity_key": entity_key,
            "entity_type": entity_type,
            "artifact_path": f"structural/entities/{folder}/{entity_key}.json",
            "source_path": source_path,
            "parent_entity_key": parent_entity_key,
        },
    )
    for alias in aliases:
        self.alias_to_entity[normalize_string(alias)].append(entity_key)
    self.counts["emitted_entities"][entity_type] += 1
    if synthetic:
        self.synthetic_entity_keys.add(entity_key)
    return entity


def make_synthetic_entity(
    self,
    entity_type,
    parent_entity,
    source_path,
    display_name,
    raw,
    source_key=None,
    aliases=None,
    evidence_links=None,
):
    source_id = make_synthetic_source_id(entity_type, source_path)
    entity = self.make_manual_entity(
        entity_type=entity_type,
        folder=SYNTHETIC_ENTITY_FOLDERS[entity_type],
        source_domain=f"synthetic.{entity_type}",
        source_key=source_key or display_name,
        source_id=source_id,
        source_path=source_path,
        display_name=display_name,
        normalized_payload=self.normalize_payload(raw),
        raw_fragment_hash=canonical_hash(raw),
        raw=raw,
        aliases=unique_list([display_name, source_path, source_key, *((aliases or []))]),
        evidence_links=evidence_links or [],
        parent_entity_key=parent_entity["entity_key"] if parent_entity else None,
        synthetic=True,
    )
    self.entities.append(entity)
    return entity


def resolve_raw_by_source_path(self, source_path):
    if not source_path:
        return None
    tokens = normalize_index_path_tokens(source_path.split("."))
    if not tokens:
        return None

    root_token = tokens[0]
    if root_token == "%p3":
        current = self.data.get("pages")
    elif root_token == "%ed":
        current = self.data.get("element_definitions")
    else:
        current = self.data.get(root_token)
    if current is None:
        return None

    for token in tokens[1:]:
        token = "workflows" if token == "%wf" else "elements" if token == "%el" else token
        if not isinstance(current, dict):
            return None
        if token in current:
            current = current[token]
            continue
        matched_by_id = next(
            (
                value
                for value in current.values()
                if isinstance(value, dict) and str(value.get("id")) == token
            ),
            None,
        )
        if matched_by_id is None:
            return None
        current = matched_by_id
    return current


def build_virtual_entity(self, source_id, source_path, virtual_type, parent_entity_key):
    raw = self.resolve_raw_by_source_path(source_path)
    if raw is None:
        return None
    folder = VIRTUAL_ENTITY_TYPE_FOLDERS.get(virtual_type, f"{virtual_type}s")
    display_name = self.derive_virtual_display_name(source_id, source_path, raw, virtual_type)
    entity_key = build_entity_key(virtual_type, display_name, source_id)
    aliases = unique_list([str(source_id), source_path, display_name])
    return {
        "entity_key": entity_key,
        "entity_type": virtual_type,
        "source_domain": "virtual",
        "source_key": str(source_id),
        "source_id": str(source_id),
        "source_path": source_path,
        "name": display_name,
        "display_name": display_name,
        "parent_entity_key": parent_entity_key,
        "normalized_payload": self.normalize_payload(raw),
        "raw_fragment_hash": canonical_hash(raw),
        "outbound_refs": [],
        "evidence": {
            "source_file": str(self.export_path),
            "source_path": source_path,
            "overlay_links": [],
        },
        "_raw": raw,
        "_folder": folder,
        "_aliases": aliases,
        "virtual": True,
    }


def derive_virtual_display_name(self, source_id, source_path, raw, virtual_type):
    if not isinstance(raw, dict):
        return str(source_id)
    if virtual_type == "workflow_action":
        return raw.get("type") or raw.get("name") or raw.get("default_name") or str(source_id)
    if virtual_type == "ui_workflow":
        return (
            raw.get("name")
            or raw.get("properties", {}).get("event_name")
            or raw.get("properties", {}).get("wf_name")
            or raw.get("type")
            or str(source_id)
        )
    return raw.get("name") or raw.get("default_name") or raw.get("display") or raw.get("type") or str(source_id)


def virtual_parent_path_aliases(self, entity):
    aliases = [entity["source_path"]]
    if entity["entity_type"] == "page":
        aliases.append(f"%p3.{entity['source_id']}")
    if entity["entity_type"] == "component":
        aliases.append(f"%ed.{entity['source_id']}")
    return unique_list(aliases)


def register_virtual_nodes_from_index(self):
    root_paths = []
    for source_path, artifact_path in self.root_artifact_paths.items():
        parent_entity_key = self.path_registry.get(source_path)
        entity = self.entity_lookup_by_key.get(parent_entity_key)
        if entity is None:
            continue
        for alias_path in self.virtual_parent_path_aliases(entity):
            root_paths.append((alias_path, parent_entity_key, artifact_path))
    root_paths.sort(key=lambda item: len(item[0]), reverse=True)

    for source_id, path in self.id_to_path.items():
        if self.get_id_registry_entries(source_id):
            continue
        parent_entity_key = None
        parent_artifact_path = None
        for root_path, candidate_parent_entity_key, artifact_path in root_paths:
            if path == root_path or path.startswith(root_path + ".") or path.startswith(root_path + "%") or path.startswith(root_path + "["):
                parent_entity_key = candidate_parent_entity_key
                parent_artifact_path = artifact_path
                break
        if not parent_artifact_path:
            continue
        virtual_type = self.classify_virtual_entity_type(path)
        virtual_entity = self.build_virtual_entity(source_id, path, virtual_type, parent_entity_key)
        if not virtual_entity:
            continue
        self.entities.append(virtual_entity)
        self.entity_lookup_by_key[virtual_entity["entity_key"]] = virtual_entity
        self.entity_lookup_by_id[str(source_id)].append(virtual_entity["entity_key"])
        self.path_registry[path] = virtual_entity["entity_key"]
        self.add_id_registry_entry(
            str(source_id),
            {
                "entity_key": virtual_entity["entity_key"],
                "entity_type": virtual_type,
                "artifact_path": f"structural/entities/{virtual_entity['_folder']}/{virtual_entity['entity_key']}.json",
                "source_path": path,
                "parent_entity_key": parent_entity_key,
            },
        )
        self.counts["emitted_entities"][virtual_type] += 1


def classify_virtual_entity_type(self, path):
    if ".actions." in path:
        return "workflow_action"
    if ".%wf." in path:
        return "ui_workflow"
    if path.startswith("%p3."):
        return "page_node"
    if path.startswith("%ed."):
        return "component_node"
    if path.startswith("mobile_views."):
        return "mobile_view_node"
    if path.startswith("api."):
        return "backend_workflow_node"
    return f"{classify_index_path(path)}_node"
