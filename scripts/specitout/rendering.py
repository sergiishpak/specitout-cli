from __future__ import annotations

import sys

from specitout.bundle_rendering import render_bundle_build
from specitout.contracts import CommandEnvelope
from specitout.status_rendering import (
    render_embedding_progress_lines,
    render_export_diagnostic_lines,
    render_pipeline_diagnostic_lines,
)


def render_envelope(envelope: CommandEnvelope) -> str:
    data = envelope["data"]
    if envelope["command"] == "query search":
        return _render_query_search(envelope)
    if envelope["command"] == "query entity":
        return _render_query_entity(envelope)
    if envelope["command"] == "query usage":
        return _render_query_usage(envelope)
    if envelope["command"] == "query paths":
        return _render_query_paths(envelope)
    if envelope["command"] == "bundle build":
        return render_bundle_build(envelope)
    if "applications" in data:
        return _render_app_list(envelope)
    if envelope["command"] == "app show":
        return _render_app_show(envelope)
    if envelope["command"] == "import add":
        return _render_import_add(envelope)
    if envelope["command"] == "import activate":
        return _render_import_activate(envelope)
    if envelope["command"] == "import status":
        return _render_import_status(envelope)
    if envelope["command"] == "index status":
        return _render_index_status(envelope)
    if envelope["command"] == "index rebuild":
        return _render_index_rebuild(envelope)
    if "registrations" in data:
        return _render_import_list(envelope)

    scope = envelope["scope"]
    warnings = envelope["warnings"]
    next_actions = envelope["next_actions"]
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={scope.get('app_slug') or '-'} version={scope.get('version_label') or '-'}",
        f"state: {data.get('state', 'unknown')}",
        f"degraded: {'yes' if envelope['degraded'] else 'no'}",
    ]
    if data.get("runtime_state"):
        lines.append(
            "runtime: "
            f"{data.get('runtime_state')} "
            f"root={data.get('data_root')} "
            f"db={data.get('database')} "
            f"port={data.get('port')}"
        )
    if data.get("bootstrap_action"):
        lines.append(
            "bootstrap: "
            f"{data.get('bootstrap_action')} "
            f"server={data.get('server_action')}"
        )
    if data.get("migrations"):
        lines.append(f"migrations: {data.get('migrations')}")
    if data.get("extensions"):
        lines.append(f"extensions: {data.get('extensions')}")
    if warnings:
        lines.append("warnings: " + "; ".join(warnings))
    if next_actions:
        lines.append("next: " + ", ".join(next_actions))
    lines.append("")
    return "\n".join(lines)


def _render_query_search(envelope: CommandEnvelope) -> str:
    data = envelope["data"]
    scope = envelope["scope"]
    results = data.get("results", [])
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={scope.get('app_slug') or '-'} version={scope.get('version_label') or '-'}",
        f"state: {data.get('state', 'unknown')}",
        f"degraded: {'yes' if envelope['degraded'] else 'no'}",
    ]
    if data.get("answer_type"):
        if data.get("answer") is not None:
            lines.append(f"answer: {data['answer']}")
        if data.get("count") is not None:
            lines.append(f"count: {data['count']}")
        items = data.get("items")
        if isinstance(items, list) and items:
            lines.append("items:")
            lines.extend(f"- {item}" for item in items)
        if data.get("counted_entity_type") is not None:
            lines.append(f"count entity type: {data['counted_entity_type']}")
        unresolved = data.get("unresolved_items")
        if isinstance(unresolved, list) and unresolved:
            lines.append("unresolved: " + ", ".join(str(item) for item in unresolved))
        if data.get("fallback_reason"):
            lines.append(f"fallback: {data['fallback_reason']}")
        evidence = data.get("evidence")
        if isinstance(evidence, list):
            for item in evidence:
                if item:
                    lines.append(f"evidence: {item}")
        elif evidence:
            lines.append(f"evidence: {evidence}")
        lines.extend(_render_tail(envelope))
        return "\n".join(lines)
    lines.append(f"results: {len(results) if isinstance(results, list) else 0}")
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            lines.append(
                "- "
                f"{result.get('entity_key') or result.get('key') or '-'} "
                f"type={result.get('entity_type') or result.get('type') or '-'} "
                f"match={result.get('match_type') or result.get('search_mode') or '-'} "
                f"score={result.get('score') if result.get('score') is not None else '-'} "
                f"name=\"{result.get('canonical_name') or result.get('name') or '-'}\""
            )
            if result.get("evidence"):
                lines.append(f"  evidence: {result['evidence']}")
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_query_entity(envelope: CommandEnvelope) -> str:
    data = envelope["data"]
    scope = envelope["scope"]
    entity = data.get("entity") if isinstance(data.get("entity"), dict) else {}
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={scope.get('app_slug') or '-'} version={scope.get('version_label') or '-'}",
        f"state: {data.get('state', 'unknown')}",
        f"degraded: {'yes' if envelope['degraded'] else 'no'}",
        (
            "entity: "
            f"{entity.get('entity_key') or entity.get('key') or '-'} "
            f"type={entity.get('entity_type') or entity.get('type') or '-'} "
            f"name=\"{entity.get('canonical_name') or entity.get('name') or '-'}\""
        ),
    ]
    if entity.get("summary"):
        lines.append(f"summary: {entity['summary']}")
    evidence = data.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                label = item.get("label") or "evidence"
                text = item.get("text") or item.get("evidence") or ""
                if text:
                    lines.append(f"evidence: {label}: {text}")
            elif item:
                lines.append(f"evidence: {item}")
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_query_usage(envelope: CommandEnvelope) -> str:
    data = envelope["data"]
    scope = envelope["scope"]
    entity = data.get("entity") if isinstance(data.get("entity"), dict) else {}
    relations = data.get("relations")
    relation_count = len(relations) if isinstance(relations, list) else 0
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={scope.get('app_slug') or '-'} version={scope.get('version_label') or '-'}",
        f"state: {data.get('state', 'unknown')}",
        f"degraded: {'yes' if envelope['degraded'] else 'no'}",
        f"entity: {entity.get('entity_key') or entity.get('key') or '-'} name=\"{entity.get('canonical_name') or entity.get('name') or '-'}\"",
        f"relations: {relation_count}",
    ]
    if isinstance(relations, list):
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            lines.append(
                "- "
                f"{relation.get('direction') or '-'} "
                f"{relation.get('relation_type') or relation.get('relation') or '-'} "
                f"{relation.get('entity_key') or relation.get('target_entity_key') or '-'} "
                f"name=\"{relation.get('canonical_name') or relation.get('name') or '-'}\""
            )
            if relation.get("evidence"):
                lines.append(f"  evidence: {relation['evidence']}")
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_query_paths(envelope: CommandEnvelope) -> str:
    data = envelope["data"]
    scope = envelope["scope"]
    paths = data.get("paths")
    path_count = len(paths) if isinstance(paths, list) else 0
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={scope.get('app_slug') or '-'} version={scope.get('version_label') or '-'}",
        f"state: {data.get('state', 'unknown')}",
        f"degraded: {'yes' if envelope['degraded'] else 'no'}",
        f"paths: {path_count}",
    ]
    if isinstance(paths, list):
        for path in paths:
            if not isinstance(path, dict):
                continue
            entities = path.get("entities")
            rendered_entities = " -> ".join(str(entity) for entity in entities) if isinstance(entities, list) else "-"
            hops = path.get("length")
            if hops is None:
                hops = max(len(entities) - 1, 0) if isinstance(entities, list) else "-"
            lines.append(f"- hops={hops} {rendered_entities}")
            if path.get("evidence"):
                lines.append(f"  evidence: {path['evidence']}")
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_app_list(envelope: CommandEnvelope) -> str:
    applications = envelope["data"]["applications"]
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"applications: {envelope['data']['application_count']}",
    ]
    for application in applications:
        lines.append(
            "- "
            f"{application['app_slug']} "
            f"display=\"{application['display_name']}\" "
            f"source={application['source_system']} "
            f"active={application.get('active_export_version') or '-'} "
            f"readiness={application.get('active_export_readiness') or '-'} "
            f"exports={application['export_count']}"
        )
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_app_show(envelope: CommandEnvelope) -> str:
    application = envelope["data"]["application"]
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"app: {application['app_slug']}",
        f"display: {application['display_name']}",
        f"source: {application['source_system']}",
        f"external app id: {application.get('external_app_id') or '-'}",
        f"active export: {application.get('active_export_version') or '-'}",
        f"active readiness: {application.get('active_export_readiness') or '-'}",
        f"exports: {application['export_count']}",
    ]
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_import_add(envelope: CommandEnvelope) -> str:
    app = envelope["data"]["app"]
    export = envelope["data"]["export"]
    active_export = envelope["data"].get("active_export")
    pipeline_run = envelope["data"].get("pipeline_run")
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={envelope['scope'].get('app_slug') or '-'} version={envelope['scope'].get('version_label') or '-'}",
        f"state: {envelope['data']['state']}",
        f"app: {app['slug']} display=\"{app['display_name']}\" source={app['source_system']}",
        (
            "export: "
            f"{export['version_label']} "
            f"lifecycle={export['lifecycle_state']} "
            f"readiness={export['readiness_state']}"
        ),
        f"active export: {active_export.get('version_label') if active_export else '-'}",
        f"pending cutover: {'yes' if export.get('pending_cutover') else 'no'}",
        f"replaces active version: {export.get('replaces_active_version') or '-'}",
        f"default query version: {export.get('default_query_version') or '-'}",
        f"source export: {envelope['data']['source_export_path']}",
        _render_pipeline_line(pipeline_run),
    ]
    next_stage = render_next_stage_line(pipeline_run)
    if next_stage is not None:
        lines.append(next_stage)
    lines.extend(render_pipeline_summary_lines(pipeline_run))
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_import_list(envelope: CommandEnvelope) -> str:
    registrations = envelope["data"]["registrations"]
    scope = envelope["scope"]
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={scope.get('app_slug') or '-'} version=-",
        f"registrations: {envelope['data']['registration_count']}",
    ]
    for registration in registrations:
        lines.append(
            "- "
            f"{registration['app_slug']} "
            f"version={registration['version_label']} "
            f"lifecycle={registration['lifecycle_state']} "
            f"readiness={registration['readiness_state']} "
            f"active={'yes' if registration['is_active'] else 'no'} "
            f"pending_cutover={'yes' if registration.get('pending_cutover') else 'no'} "
            f"replaces={registration.get('replaces_active_version') or '-'} "
            f"default_query={registration.get('default_query_version') or '-'} "
            f"registered={registration['registered_at']}"
        )
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_import_status(envelope: CommandEnvelope) -> str:
    app = envelope["data"]["app"]
    export = envelope["data"]["export"]
    pipeline_run = envelope["data"].get("pipeline_run")
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"app: {app['app_slug']}",
        f"version: {export['version_label']}",
        f"readiness: {export['readiness_state']}",
        f"lifecycle: {export['lifecycle_state']}",
        f"active: {'yes' if export.get('is_active') else 'no'}",
        f"pending cutover: {'yes' if export.get('pending_cutover') else 'no'}",
        f"replaces active version: {export.get('replaces_active_version') or '-'}",
        f"default query version: {export.get('default_query_version') or '-'}",
        _render_pipeline_line(pipeline_run),
    ]
    lines.extend(render_export_diagnostic_lines(export))
    lines.extend(render_pipeline_diagnostic_lines(pipeline_run))
    lines.extend(render_embedding_progress_lines(envelope["data"].get("embedding_stats")))
    next_stage = render_next_stage_line(pipeline_run)
    if next_stage is not None:
        lines.append(next_stage)
    lines.extend(render_pipeline_summary_lines(pipeline_run))
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_import_activate(envelope: CommandEnvelope) -> str:
    data = envelope["data"]
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={envelope['scope'].get('app_slug') or '-'} version={envelope['scope'].get('version_label') or '-'}",
        f"state: {data.get('state', 'unknown')}",
        f"lifecycle: {data.get('lifecycle_status') or '-'}",
        f"readiness: {data.get('readiness_status') or '-'}",
    ]
    if data.get("audit_id"):
        lines.append(f"audit: {data['audit_id']}")
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_index_status(envelope: CommandEnvelope) -> str:
    data = envelope["data"]
    export = data.get("export")
    app = data.get("app")
    pipeline_run = data.get("pipeline_run")
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={envelope['scope'].get('app_slug') or '-'} version={envelope['scope'].get('version_label') or '-'}",
        f"state: {data.get('state', 'unknown')}",
        f"degraded: {'yes' if envelope['degraded'] else 'no'}",
    ]
    if data.get("runtime_state"):
        lines.append(
            "runtime: "
            f"{data.get('runtime_state')} "
            f"root={data.get('data_root')} "
            f"db={data.get('database')} "
            f"port={data.get('port')}"
        )
    if data.get("backend"):
        lines.append(f"backend: {data.get('backend')} sqlite-fallback={data.get('sqlite_fallback', '-')}")
    if export is not None:
        export_app_slug = "-"
        if isinstance(export, dict):
            export_app_slug = (
                str(export.get("app_slug") or "")
                or (str(app.get("app_slug") or "") if isinstance(app, dict) else "")
                or (str(app.get("slug") or "") if isinstance(app, dict) else "")
                or str(envelope["scope"].get("app_slug") or "-")
            )
            lines.append(f"app: {export_app_slug}")
            lines.append(f"version: {export.get('version_label') or envelope['scope'].get('version_label') or '-'}")
            lines.append(f"readiness: {export.get('readiness_state') or export.get('readiness_status') or '-'}")
        lines.append(_render_pipeline_line(pipeline_run))
        lines.extend(render_export_diagnostic_lines(export))
        lines.extend(render_pipeline_diagnostic_lines(pipeline_run))
        lines.extend(render_embedding_progress_lines(data.get("embedding_stats")))
        next_stage = render_next_stage_line(pipeline_run)
        if next_stage is not None:
            lines.append(next_stage)
        lines.extend(render_pipeline_summary_lines(pipeline_run))
    if data.get("bootstrap_action"):
        lines.append(
            "bootstrap: "
            f"{data.get('bootstrap_action')} "
            f"server={data.get('server_action')}"
        )
    if data.get("migrations"):
        lines.append(f"migrations: {data.get('migrations')}")
    if data.get("extensions"):
        lines.append(f"extensions: {data.get('extensions')}")
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_index_rebuild(envelope: CommandEnvelope) -> str:
    data = envelope["data"]
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    lines = [
        f"{envelope['command']}: {envelope['status']}",
        f"scope: app={envelope['scope'].get('app_slug') or '-'} version={envelope['scope'].get('version_label') or '-'}",
        f"state: {data.get('state', 'unknown')}",
        f"readiness: {data.get('readiness_status') or '-'}",
        f"lifecycle: {data.get('lifecycle_status') or '-'}",
        f"search documents: {stats.get('search_documents', 0)}",
        f"associations: {stats.get('search_document_associations', 0)}",
    ]
    if "embedded_documents" in stats:
        lines.append(f"embedded documents: {stats.get('embedded_documents', 0)}")
    if "remaining_documents" in stats:
        lines.append(f"remaining embeddings: {stats.get('remaining_documents', 0)}")
    if stats.get("embedding_model"):
        lines.append(f"embedding model: {stats['embedding_model']}")
    if stats.get("embedding_dimensions"):
        lines.append(f"embedding dimensions: {stats['embedding_dimensions']}")
    lines.extend(_render_tail(envelope))
    return "\n".join(lines)


def _render_tail(envelope: CommandEnvelope) -> list[str]:
    lines: list[str] = []
    if envelope["warnings"]:
        lines.append("warnings: " + "; ".join(envelope["warnings"]))
    if envelope["next_actions"]:
        lines.append("next: " + ", ".join(envelope["next_actions"]))
    lines.append("")
    return lines


def _render_pipeline_line(pipeline_run: object) -> str:
    if not isinstance(pipeline_run, dict):
        return "pipeline: not started"
    status = str(pipeline_run.get("status") or "unknown")
    stage = pipeline_run.get("current_stage")
    progress = pipeline_run.get("progress_percent")
    details: list[str] = [status]
    if stage:
        details.append(f"stage={stage}")
    if progress is not None:
        details.append(f"progress={progress}%")
    return "pipeline: " + " ".join(details)


def coerce_exit_code(code: object) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(str(code), file=sys.stderr)
    return 1


def render_next_stage_line(pipeline_run: object) -> str | None:
    if not isinstance(pipeline_run, dict):
        return None
    summary_json = pipeline_run.get("summary_json")
    if not isinstance(summary_json, dict):
        return None
    next_stage = summary_json.get("next_stage")
    if not next_stage:
        return None
    return f"next stage: {next_stage}"


def render_pipeline_summary_lines(pipeline_run: object) -> list[str]:
    if not isinstance(pipeline_run, dict):
        return []
    summary_json = pipeline_run.get("summary_json")
    if not isinstance(summary_json, dict):
        return []
    if not any(key in summary_json for key in ("entity_count", "edge_count", "unresolved_edge_count")):
        return []
    return [
        "graph counts: "
        f"entities={summary_json.get('entity_count', 0)} "
        f"edges={summary_json.get('edge_count', 0)} "
        f"unresolved={summary_json.get('unresolved_edge_count', 0)}"
    ]
