from __future__ import annotations

from specitout.contracts import CommandEnvelope


def render_bundle_build(envelope: CommandEnvelope) -> str:
    data = envelope["data"]
    scope = envelope["scope"]
    anchors = _list(data.get("anchors"))
    entities = _list(data.get("entities"))
    edges = _list(data.get("edges"))
    candidates = _list(data.get("candidates"))
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={scope.get('app_slug') or '-'} version={scope.get('version_label') or '-'}",
        f"state: {data.get('state', 'unknown')}",
        f"degraded: {'yes' if envelope['degraded'] else 'no'}",
        f"anchors: {len(anchors)}",
    ]
    for anchor in anchors:
        lines.append(
            "- "
            f"{anchor.get('entity_key') or '-'} "
            f"type={anchor.get('entity_type') or '-'} "
            f"match={anchor.get('match_type') or '-'} "
            f"name=\"{anchor.get('canonical_name') or '-'}\""
        )
        if anchor.get("evidence"):
            lines.append(f"  evidence: {anchor['evidence']}")
    lines.append(f"entities: {len(entities)}")
    for entity in entities:
        lines.append(
            "- "
            f"{entity.get('entity_key') or '-'} "
            f"type={entity.get('entity_type') or '-'} "
            f"name=\"{entity.get('canonical_name') or '-'}\""
        )
        if entity.get("summary"):
            lines.append(f"  summary: {entity['summary']}")
    lines.append(f"edges: {len(edges)}")
    for edge in edges:
        lines.append(
            "- "
            f"{edge.get('from_entity_key') or edge.get('from_key') or '-'} "
            f"{edge.get('relation') or edge.get('relation_type') or '-'} "
            f"{edge.get('to_entity_key') or edge.get('to_key') or '-'}"
        )
        evidence = edge.get("evidence_path") or edge.get("evidence")
        if evidence:
            lines.append(f"  evidence: {evidence}")
    if candidates:
        lines.append(f"candidates: {len(candidates)}")
        for candidate in candidates:
            lines.append(
                "- "
                f"{candidate.get('entity_key') or '-'} "
                f"type={candidate.get('entity_type') or '-'} "
                f"name=\"{candidate.get('canonical_name') or '-'}\""
            )
    evidence_items = data.get("evidence")
    if isinstance(evidence_items, list):
        for evidence in evidence_items:
            if evidence:
                lines.append(f"evidence: {evidence}")
    truncation = _truncated_labels(data.get("truncation"))
    if truncation:
        lines.append("truncation: " + ", ".join(truncation))
    notes = data.get("notes")
    if isinstance(notes, list) and notes:
        lines.append("notes: " + "; ".join(str(note) for note in notes))
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _truncated_labels(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    labels: list[str] = []
    for key, is_truncated in value.items():
        if is_truncated:
            labels.append(str(key).removesuffix("_truncated"))
    return labels


def _render_tail(envelope: CommandEnvelope) -> list[str]:
    lines: list[str] = []
    warnings = envelope["warnings"]
    next_actions = envelope["next_actions"]
    if warnings:
        lines.append("warnings: " + "; ".join(warnings))
    if next_actions:
        lines.append("next: " + ", ".join(next_actions))
    lines.append("")
    return lines
