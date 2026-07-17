from collections import Counter

from .constants import CAPABILITY_TAXONOMY, DEEP_SEARCH_ENTITY_TYPES, QUERY_HINTS, VIRTUAL_ENTITY_TYPES
from .shared import keyword_matches, normalize_string, tokenize_text, unique_list


def build_semantics(self):
    self.query_hints = {
        query: {
            "terms": terms,
            "capabilities": [
                capability
                for capability, config in CAPABILITY_TAXONOMY.items()
                if any(term in " ".join(config["keywords"]) for term in terms)
            ],
        }
        for query, terms in QUERY_HINTS.items()
    }
    for entity in self.entities:
        semantic = self.make_semantic_record(entity)
        self.semantic_records.append(semantic)
        self.semantic_lookup[entity["entity_key"]] = semantic
    for semantic in self.semantic_records:
        self.collect_glossary_terms(semantic)


def collect_glossary_terms(self, semantic):
    for term in unique_list(semantic["aliases"] + semantic["keywords"] + semantic["tags"] + semantic["domains"]):
        normalized = normalize_string(term)
        if normalized:
            self.glossary_terms[normalized].append(
                {
                    "entity_key": semantic["entity_key"],
                    "display_name": semantic["display_name"],
                    "entity_type": semantic["entity_type"],
                }
            )


def make_semantic_record(self, entity):
    text_sources = self.collect_text_sources(entity)
    tokens = Counter()
    for text in text_sources:
        tokens.update(tokenize_text(text))

    tags = set()
    domains = set()
    integrations = set()
    normalized_full_text = normalize_string(" ".join(text_sources).lower())
    token_set = set(tokens.keys())
    for capability, config in CAPABILITY_TAXONOMY.items():
        if any(keyword_matches(keyword, token_set, normalized_full_text) for keyword in config["keywords"]):
            tags.add(capability)
            domains.update(config["domains"])
            integrations.update(config["integrations"])
            self.capability_index[capability].append(self.capability_entry(entity, capability))

    inferred_integrations = self.infer_integrations(normalized_full_text)
    integrations.update(inferred_integrations)
    for integration in inferred_integrations:
        self.integration_index[integration].append(self.capability_entry(entity, integration))

    outbound = entity["outbound_refs"]
    inbound = self.reverse_usage.get(entity["entity_key"], [])
    summary = self.make_summary(entity, tags, domains, integrations, len(outbound), len(inbound))

    return {
        "entity_key": entity["entity_key"],
        "entity_type": entity["entity_type"],
        "display_name": entity["display_name"],
        "summary": summary,
        "aliases": entity["_aliases"],
        "keywords": [token for token, _ in tokens.most_common(20)],
        "tags": sorted(tags),
        "domains": sorted(domains),
        "external_integrations": sorted(integrations),
        "inbound_ref_count": len(inbound),
        "outbound_ref_count": len(outbound),
        "used_by": unique_list([edge["from_entity_key"] for edge in inbound]),
        "depends_on": unique_list([edge["to_entity_key"] for edge in outbound]),
        "evidence_links": [{"kind": "source", "path": entity["source_path"]}, *entity["evidence"]["overlay_links"]],
        "searchable": entity["entity_type"] not in DEEP_SEARCH_ENTITY_TYPES,
        "searchable_in_root": entity["entity_type"] not in DEEP_SEARCH_ENTITY_TYPES,
        "searchable_in_deep": True,
        "synthetic": entity.get("synthetic", False),
        "virtual": entity.get("virtual", False),
    }


def capability_entry(self, entity, label):
    return {
        "entity_key": entity["entity_key"],
        "display_name": entity["display_name"],
        "source_path": entity["source_path"],
        "label": label,
    }


def infer_integrations(self, text):
    integrations = set()
    if "openai" in text or "chatgpt" in text or "assistant" in text:
        integrations.add("openai")
    if "mews" in text:
        integrations.add("mews")
    if "mailgun" in text or "email" in text:
        integrations.add("email")
    if "sms" in text or "twilio" in text:
        integrations.add("sms")
    if "webhook" in text or "http" in text or "rest" in text:
        integrations.add("external_api")
    if "file" in text or "image" in text or "video" in text or "asset" in text:
        integrations.add("files")
    return integrations


def collect_text_sources(self, entity):
    texts = [entity["display_name"], entity["source_key"], entity["source_id"], entity["source_path"], *entity["_aliases"]]
    raw = entity["_raw"]
    if entity["entity_type"] == "application":
        texts.extend(raw.get("top_level_keys", []))
    if entity["entity_type"] == "app_settings":
        texts.extend(raw.get("client_safe_keys", []))
        texts.extend(raw.get("secure_keys", []))
        texts.extend(list((raw.get("client_safe_flags") or {}).keys()))
    if entity["entity_type"] == "backend_workflow":
        texts.extend([raw.get("type"), raw.get("properties", {}).get("wf_name"), raw.get("properties", {}).get("event_name")])
    if entity["entity_type"] == "user_type":
        texts.extend(list(raw.get("fields", {}).keys()))
        texts.extend(list(raw.get("privacy_role", {}).keys()))
    if entity["entity_type"] == "option_set":
        texts.extend(list(raw.get("values", {}).keys())[:20])
    if entity["entity_type"] == "field":
        texts.extend([raw.get("display"), raw.get("value"), "list" if raw.get("is_list") else None])
    if entity["entity_type"] == "option_value":
        texts.extend([raw.get("display"), raw.get("name"), *list((raw.get("attributes") or {}).keys())[:10]])
    if entity["entity_type"] == "custom_state":
        texts.extend([raw.get("display"), raw.get("value"), raw.get("default_val")])
    if entity["entity_type"] == "event":
        texts.extend([raw.get("workflow_type"), raw.get("event_family"), *(raw.get("properties") or {}).keys()])
    if entity["entity_type"] == "element_state":
        texts.extend(list((raw.get("properties") or {}).keys()))
    if entity["entity_type"] in {"condition", "dynamic_expression"}:
        profile = self.describe_expression(raw)
        texts.extend(profile["operators"])
        texts.extend(profile["sources"])
    if entity["entity_type"] == "data_source":
        texts.extend([raw.get("type"), raw.get("properties", {}).get("name"), raw.get("properties", {}).get("param_id"), raw.get("properties", {}).get("element_id")])
    if entity["entity_type"] in {"page", "component", "mobile_view"}:
        texts.extend([raw.get("type"), raw.get("properties", {}).get("title")])
    if entity["entity_type"] == "api_connector":
        texts.extend([raw.get("client_safe", {}).get("human"), raw.get("client_safe", {}).get("auth")])
        texts.extend(list((raw.get("client_safe", {}) or {}).get("calls", {}).keys())[:20])
    if entity["entity_type"] == "api_connector_call":
        client = raw.get("client_safe", {})
        texts.extend([client.get("name"), client.get("url"), client.get("method"), client.get("publish_as"), client.get("ret_value")])
    if entity["entity_type"] == "app_connector":
        texts.extend([raw.get("client_safe", {}).get("name"), raw.get("client_safe", {}).get("domain")])
    if entity["entity_type"] == "app_connector_call":
        client = raw.get("client_safe", {})
        texts.extend([client.get("name"), client.get("type"), client.get("auth")])
    if entity["entity_type"] == "plugin_installation":
        texts.extend([raw.get("plugin_key"), raw.get("plugin_kind")])
    if entity["entity_type"] == "plugin_action":
        texts.extend([raw.get("plugin_id"), raw.get("action_suffix")])
    if entity["entity_type"] in VIRTUAL_ENTITY_TYPES and isinstance(raw, dict):
        texts.extend([raw.get("type"), raw.get("name"), raw.get("default_name")])
        if isinstance(raw.get("properties"), dict):
            texts.extend(list(raw.get("properties", {}).keys())[:20])
    return [str(text) for text in texts if isinstance(text, (str, int, float, bool))]
