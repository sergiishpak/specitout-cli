import json
from collections import defaultdict
from pathlib import Path

from .constants import RELATION_WEIGHTS
from .shared import load_json, normalize_string, now_iso, tokenize_text, unique_list, unique_list_of_dicts


def load_edge_index(path):
    rows = []
    with Path(path).open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def is_anchorable(semantic_record, search_mode="root", entity_type_filters=None):
    entity_type_filters = set(entity_type_filters or [])
    if entity_type_filters and semantic_record["entity_type"] not in entity_type_filters:
        return False
    if search_mode == "deep":
        return semantic_record.get("searchable_in_deep", True)
    return semantic_record.get("searchable_in_root", semantic_record.get("searchable", True))


def score_entity(query_terms, semantic_record, search_mode="root", entity_type_filters=None):
    if not is_anchorable(semantic_record, search_mode=search_mode, entity_type_filters=entity_type_filters):
        return 0, []
    score = 0
    reasons = []
    haystacks = {
        "aliases": [normalize_string(value) for value in semantic_record["aliases"]],
        "keywords": [normalize_string(value) for value in semantic_record["keywords"]],
        "tags": [normalize_string(value) for value in semantic_record["tags"]],
        "domains": [normalize_string(value) for value in semantic_record["domains"]],
        "integrations": [normalize_string(value) for value in semantic_record["external_integrations"]],
        "display_name": normalize_string(semantic_record["display_name"]),
    }
    query_normalized = normalize_string(" ".join(query_terms))
    if query_normalized and query_normalized == haystacks["display_name"]:
        score += 120
        reasons.append("exact display name match")
    for term in query_terms:
        normalized = normalize_string(term)
        if not normalized:
            continue
        if normalized == semantic_record["entity_key"]:
            score += 150
            reasons.append("exact entity key match")
        if normalized in haystacks["display_name"]:
            score += 60
            reasons.append(f"display name contains `{term}`")
        if normalized in haystacks["aliases"]:
            score += 50
            reasons.append(f"alias match `{term}`")
        if normalized in haystacks["tags"]:
            score += 35
            reasons.append(f"tag match `{term}`")
        if normalized in haystacks["domains"]:
            score += 30
            reasons.append(f"domain match `{term}`")
        if normalized in haystacks["integrations"]:
            score += 30
            reasons.append(f"integration match `{term}`")
        if normalized in haystacks["keywords"]:
            score += 15
            reasons.append(f"keyword match `{term}`")
    if search_mode == "deep" and (semantic_record.get("synthetic") or semantic_record.get("virtual")):
        score -= 5
        reasons.append("deep-search entity")
    return score, unique_list(reasons)


def gather_query_terms(query, query_hints):
    terms = tokenize_text(query)
    query_normalized = normalize_string(query)
    for hint_query, hint_config in query_hints.items():
        if normalize_string(hint_query) in query_normalized:
            terms.extend(tokenize_text(" ".join(hint_config.get("terms", []))))
    return unique_list(terms)


def bundle_context_from_records(
    pack_root,
    manifest,
    semantic_records,
    structural_records,
    edge_rows,
    reverse_usage_index,
    glossary,
    capability_index,
    integration_index,
    query_hints,
    query=None,
    entity_key=None,
    max_hops=1,
    search_mode="root",
    entity_type_filters=None,
    anchor_limit=5,
):
    query_terms = gather_query_terms(query or entity_key or "", query_hints)
    resolved_anchors = []
    candidate_scores = []
    entity_type_filters = set(entity_type_filters or [])
    if entity_key:
        record = semantic_records.get(entity_key)
        if record and is_anchorable(record, search_mode=search_mode, entity_type_filters=entity_type_filters):
            resolved_anchors.append({"entity_key": entity_key, "display_name": record["display_name"], "score": 999, "reasons": ["explicit entity key"]})
    else:
        for record in semantic_records.values():
            score, reasons = score_entity(query_terms, record, search_mode=search_mode, entity_type_filters=entity_type_filters)
            if score > 0:
                candidate_scores.append((score, record["entity_key"], reasons))
        for term in query_terms:
            normalized = normalize_string(term)
            for glossary_hit in glossary["terms"].get(normalized, []):
                record = semantic_records.get(glossary_hit["entity_key"])
                if record and is_anchorable(record, search_mode=search_mode, entity_type_filters=entity_type_filters):
                    candidate_scores.append((40, glossary_hit["entity_key"], [f"glossary match `{term}`"]))
            for capability_hit in capability_index.get(normalized, []):
                record = semantic_records.get(capability_hit["entity_key"])
                if record and is_anchorable(record, search_mode=search_mode, entity_type_filters=entity_type_filters):
                    candidate_scores.append((50, capability_hit["entity_key"], [f"capability match `{term}`"]))
            for integration_hit in integration_index.get(normalized, []):
                record = semantic_records.get(integration_hit["entity_key"])
                if record and is_anchorable(record, search_mode=search_mode, entity_type_filters=entity_type_filters):
                    candidate_scores.append((50, integration_hit["entity_key"], [f"integration match `{term}`"]))
        best_scores = {}
        best_reasons = defaultdict(list)
        for score, entity_key_candidate, reasons in candidate_scores:
            if score > best_scores.get(entity_key_candidate, 0):
                best_scores[entity_key_candidate] = score
            best_reasons[entity_key_candidate].extend(reasons)
        ranked = sorted(best_scores.items(), key=lambda item: (-item[1], item[0]))[:anchor_limit]
        for entity_key_candidate, score in ranked:
            resolved_anchors.append(
                {
                    "entity_key": entity_key_candidate,
                    "display_name": semantic_records[entity_key_candidate]["display_name"],
                    "score": score,
                    "reasons": unique_list(best_reasons[entity_key_candidate]),
                }
            )

    selected_entities = {}
    related_edges = []
    queue = [(anchor["entity_key"], 0) for anchor in resolved_anchors]
    seen = set()
    inbound_lookup = defaultdict(list)
    outbound_lookup = defaultdict(list)
    for edge in edge_rows:
        outbound_lookup[edge["from_entity_key"]].append(edge)
        inbound_lookup[edge["to_entity_key"]].append(edge)
    while queue:
        current_entity_key, depth = queue.pop(0)
        if current_entity_key in seen or current_entity_key not in semantic_records:
            continue
        seen.add(current_entity_key)
        selected_entities[current_entity_key] = {
            "semantic": semantic_records[current_entity_key],
            "structural": structural_records.get(current_entity_key),
        }
        if depth >= max_hops:
            continue
        edges_to_visit = outbound_lookup.get(current_entity_key, []) + inbound_lookup.get(current_entity_key, [])
        edges_to_visit = sorted(edges_to_visit, key=lambda edge: (-RELATION_WEIGHTS.get(edge["relation"], 1), edge["relation"], edge["to_entity_key"]))
        for edge in edges_to_visit[:20]:
            related_edges.append(edge)
            neighbor_key = edge["to_entity_key"] if edge["from_entity_key"] == current_entity_key else edge["from_entity_key"]
            queue.append((neighbor_key, depth + 1))

    overlay_links = unique_list_of_dicts(
        [
            link
            for record in selected_entities.values()
            for link in (record["structural"] or {}).get("evidence", {}).get("overlay_links", [])
        ]
    )
    bundle = {
        "query": query,
        "entity_key": entity_key,
        "generated_at": now_iso(),
        "pack_root": str(pack_root),
        "resolved_anchors": resolved_anchors,
        "selected_entities": [
            {
                "entity_key": key,
                "display_name": value["semantic"]["display_name"],
                "entity_type": value["semantic"]["entity_type"],
                "summary": value["semantic"]["summary"],
                "tags": value["semantic"]["tags"],
                "domains": value["semantic"]["domains"],
                "external_integrations": value["semantic"]["external_integrations"],
                "synthetic": value["semantic"].get("synthetic", False),
                "virtual": value["semantic"].get("virtual", False),
                "used_by": value["semantic"]["used_by"],
                "depends_on": value["semantic"]["depends_on"],
                "evidence_links": value["semantic"]["evidence_links"],
            }
            for key, value in sorted(
                selected_entities.items(),
                key=lambda item: (next((anchor["score"] for anchor in resolved_anchors if anchor["entity_key"] == item[0]), 0), item[1]["semantic"]["display_name"]),
                reverse=True,
            )
        ],
        "related_edges": unique_list_of_dicts(related_edges),
        "overlay_links": overlay_links,
        "unresolved": {
            "anchor_count": len(resolved_anchors),
            "selected_entity_count": len(selected_entities),
            "related_edge_count": len(unique_list_of_dicts(related_edges)),
            "notes": [] if resolved_anchors else ["No strong anchor entities were resolved from the query."],
        },
        "metadata": {
            "manifest_generated_at": manifest["generated_at"],
            "max_hops": max_hops,
            "search_mode": search_mode,
            "entity_type_filters": sorted(entity_type_filters),
            "anchor_limit": anchor_limit,
            "query_terms": query_terms,
        },
    }
    bundle["markdown_summary"] = render_bundle_markdown(bundle, reverse_usage_index)
    return bundle


def bundle_context_pack(pack_dir, query=None, entity_key=None, max_hops=1, search_mode="root", entity_type_filters=None, anchor_limit=5):
    pack_dir = Path(pack_dir)
    semantic_root = pack_dir / "semantic"
    structural_root = pack_dir / "structural"
    manifest = load_json(structural_root / "indexes" / "manifest.json")
    edge_rows = load_edge_index(structural_root / "indexes" / "edge_index.jsonl")
    reverse_usage_index = load_json(semantic_root / "indexes" / "reverse_usage_index.json")
    glossary = load_json(semantic_root / "indexes" / "glossary.json")
    capability_index = load_json(semantic_root / "indexes" / "capability_index.json")
    integration_index = load_json(semantic_root / "indexes" / "integration_index.json")
    query_hints = load_json(semantic_root / "indexes" / "query_hints.json")
    semantic_records = {record["entity_key"]: record for path in (semantic_root / "entities").rglob("*.json") for record in [load_json(path)]}
    structural_records = {record["entity_key"]: record for path in (structural_root / "entities").rglob("*.json") for record in [load_json(path)]}
    return bundle_context_from_records(
        pack_root=pack_dir,
        manifest=manifest,
        semantic_records=semantic_records,
        structural_records=structural_records,
        edge_rows=edge_rows,
        reverse_usage_index=reverse_usage_index,
        glossary=glossary,
        capability_index=capability_index,
        integration_index=integration_index,
        query_hints=query_hints,
        query=query,
        entity_key=entity_key,
        max_hops=max_hops,
        search_mode=search_mode,
        entity_type_filters=entity_type_filters,
        anchor_limit=anchor_limit,
    )


def render_bundle_markdown(bundle, reverse_usage_index):
    lines = ["# Context Bundle", ""]
    if bundle.get("query"):
        lines.append(f"- Query: `{bundle['query']}`")
    if bundle.get("entity_key"):
        lines.append(f"- Entity key: `{bundle['entity_key']}`")
    lines.append(f"- Search mode: `{bundle['metadata'].get('search_mode', 'root')}`")
    lines.append(f"- Anchors: `{len(bundle['resolved_anchors'])}`")
    lines.append(f"- Selected entities: `{len(bundle['selected_entities'])}`")
    lines.append("")
    lines.append("## Anchor Resolution")
    if bundle["resolved_anchors"]:
        for anchor in bundle["resolved_anchors"]:
            semantic = next((item for item in bundle["selected_entities"] if item["entity_key"] == anchor["entity_key"]), None)
            flags = []
            if semantic and semantic.get("synthetic"):
                flags.append("synthetic")
            if semantic and semantic.get("virtual"):
                flags.append("virtual")
            flag_suffix = f" [{' / '.join(flags)}]" if flags else ""
            lines.append(f"- `{anchor['display_name']}` ({anchor['entity_key']}){flag_suffix} — score `{anchor['score']}`; {', '.join(anchor['reasons'])}")
    else:
        lines.append("- No anchor entities were resolved.")
    lines.extend(["", "## Selected Entities"])
    for entity in bundle["selected_entities"][:15]:
        flags = []
        if entity.get("synthetic"):
            flags.append("synthetic")
        if entity.get("virtual"):
            flags.append("virtual")
        suffix = f" [{' / '.join(flags)}]" if flags else ""
        lines.append(f"- `{entity['display_name']}` ({entity['entity_type']}){suffix}")
        lines.append(f"  Summary: {entity['summary']}")
        if entity["used_by"]:
            lines.append(f"  Used by: {', '.join(entity['used_by'][:5])}")
        if entity["depends_on"]:
            lines.append(f"  Depends on: {', '.join(entity['depends_on'][:5])}")
        usage = reverse_usage_index.get(entity["entity_key"], {})
        if usage.get("used_by"):
            lines.append(f"  Reverse usage edges: {len(usage['used_by'])}")
    lines.extend(["", "## Related Edges"])
    for edge in bundle["related_edges"][:20]:
        lines.append(f"- `{edge['from_entity_key']}` --`{edge['relation']}`--> `{edge['to_entity_key']}` (evidence: `{edge['evidence_path']}`)")
    return "\n".join(lines) + "\n"
