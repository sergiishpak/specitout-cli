from __future__ import annotations


def render_export_diagnostic_lines(export: object) -> list[str]:
    if not isinstance(export, dict):
        return []
    failure_reason = export.get("failure_reason")
    if not failure_reason:
        return []
    return [f"failure reason: {failure_reason}"]


def render_pipeline_diagnostic_lines(pipeline_run: object) -> list[str]:
    if not isinstance(pipeline_run, dict):
        return []
    lines: list[str] = []
    status_message = pipeline_run.get("status_message")
    if status_message:
        lines.append(f"pipeline message: {status_message}")
    error_json = pipeline_run.get("error_json")
    if isinstance(error_json, dict) and error_json:
        stage = error_json.get("stage") or pipeline_run.get("current_stage")
        message = error_json.get("message") or error_json.get("error")
        details: list[str] = []
        if stage:
            details.append(f"stage={stage}")
        if message:
            details.append(f'message="{message}"')
        if details:
            lines.append("pipeline error: " + " ".join(details))
    return lines


def render_embedding_progress_lines(embedding_stats: object) -> list[str]:
    if not isinstance(embedding_stats, dict):
        return []
    if not any(key in embedding_stats for key in ("embedded_documents", "remaining_documents", "total_documents")):
        return []
    embedded = embedding_stats.get("embedded_documents", 0)
    remaining = embedding_stats.get("remaining_documents", 0)
    total = embedding_stats.get("total_documents")
    line = f"embeddings: embedded={embedded} remaining={remaining}"
    if total is not None:
        line += f" total={total}"
    return [line]
