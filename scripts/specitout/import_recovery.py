from __future__ import annotations

import hashlib
from pathlib import Path

from specitout.progress import ImportProgressReporter
from specitout.runtime import SpecItOutRuntimeError

RETRYABLE_READINESS = {"registered", "ingesting", "failed", "degraded"}


def retry_import(
    backend: object,
    *,
    app_slug: str,
    version_label: str,
    export_path: str | None,
    progress_reporter: ImportProgressReporter | None = None,
) -> dict[str, object]:
    status = backend.import_status(app_slug=app_slug, version_label=version_label)
    data = dict(status["data"])
    export = dict(data["export"])
    readiness = str(export.get("readiness_status") or "")
    if readiness not in RETRYABLE_READINESS:
        raise SpecItOutRuntimeError(f"Export {version_label} is {readiness}; only retryable imports can be retried.")

    path = _resolve_retry_export_path(export=export, explicit_export_path=export_path)
    source_export_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    expected_hash = str(export.get("source_export_hash") or "")
    if expected_hash and expected_hash != source_export_hash:
        raise SpecItOutRuntimeError("Retry export file does not match the registered source_export_hash.")

    app = dict(data["app"])
    app.setdefault("slug", app.get("app_slug") or app_slug)
    pipeline_result = backend.start_import_pipeline(
        app=app,
        export=export,
        export_path=path,
        source_export_hash=source_export_hash,
        progress_reporter=progress_reporter,
    )
    return {
        "app": app,
        "active_export": data.get("active_export"),
        "pipeline_result": pipeline_result,
        "source_export_path": str(path),
        "source_export_hash": source_export_hash,
    }


def _resolve_retry_export_path(*, export: dict[str, object], explicit_export_path: str | None) -> Path:
    if explicit_export_path:
        path = Path(explicit_export_path).expanduser().resolve()
    else:
        metadata = dict(export.get("metadata_json") or {})
        registration = dict(metadata.get("registration") or {})
        stored_path = str(registration.get("source_export_path") or "")
        if not stored_path:
            raise SpecItOutRuntimeError("Retry needs --export because no source_export_path is stored for this export.")
        path = Path(stored_path).expanduser().resolve()
    if not path.is_file():
        raise SpecItOutRuntimeError(f"Bubble export file was not found: {path}")
    return path
