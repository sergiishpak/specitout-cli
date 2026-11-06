from __future__ import annotations

import time
from collections.abc import Callable

from specitout.contracts import CommandEnvelope
from specitout.progress import IndexProgressReporter
from specitout.runtime import SpecItOutRuntimeError
from specitout.status_actions import status_next_actions

ResumeEmitter = Callable[[str], None]


def resume_index(
    backend: object,
    *,
    app_slug: str,
    version_label: str,
    initial_limit: int,
    min_limit: int,
    max_passes: int,
    stuck_pass_threshold: int,
    sleep_seconds: float,
    progress_reporter: IndexProgressReporter | None = None,
    emit: ResumeEmitter | None = None,
) -> dict[str, object]:
    limit = initial_limit
    if progress_reporter is not None:
        progress_reporter("resume_verification", 0, 0, "waiting for target export readiness and database embedding counts")
    initial_status = _embedding_status(backend, app_slug=app_slug, version_label=version_label)
    if initial_status is not None:
        stats = dict(initial_status["stats"])
        total = _int_stat(stats, "total_documents")
        embedded = _int_stat(stats, "embedded_documents")
        remaining = _int_stat(stats, "remaining_documents")
        _emit(emit, f"progress: index resume verified readiness={initial_status['readiness_status']} overall_embedded={embedded} overall_remaining={remaining} overall_total={total} unit=documents")
        if initial_status["readiness_status"] == "ready" and total > 0 and embedded == total and remaining == 0:
            return {"state": "ready", "passes": 0, "limit": limit, "last_result": initial_status}
        if initial_status["readiness_status"] == "ready":
            raise SpecItOutRuntimeError("Ready index has inconsistent embedding counters; inspect status before explicitly rebuilding. Existing vectors were preserved.")
    failure_streak = 0
    stagnant_streak = 0
    last_remaining: int | None = None
    last_result: dict[str, object] = {"readiness_status": "embedding_pending", "stats": {}}
    last_error: str | None = None

    for attempt in range(1, max_passes + 1):
        try:
            result = backend.rebuild_index(
                app_slug=app_slug,
                version_label=version_label,
                embedding_limit=limit,
                progress_reporter=progress_reporter,
            )
            last_result = dict(result)
            last_error = None
            failure_streak = 0
        except SpecItOutRuntimeError as exc:
            result = {}
            last_error = str(exc)
            failure_streak += 1

        stats = dict(result.get("stats") or last_result.get("stats") or {})
        readiness = str(result.get("readiness_status") or last_result.get("readiness_status") or "embedding_pending")
        remaining = _int_stat(stats, "remaining_documents")
        embedded = _int_stat(stats, "embedded_documents")
        if last_remaining is None or remaining < last_remaining:
            stagnant_streak = 0
        else:
            stagnant_streak += 1
        last_remaining = remaining

        overall = _embedding_status(backend, app_slug=app_slug, version_label=version_label)
        overall_message = ""
        if overall is not None:
            overall_stats = dict(overall["stats"])
            overall_message = f" overall_embedded={_int_stat(overall_stats, 'embedded_documents')} overall_remaining={_int_stat(overall_stats, 'remaining_documents')} overall_total={_int_stat(overall_stats, 'total_documents')}"
        _emit(emit, f"progress: index resume pass={attempt} readiness={readiness} pass_embedded={embedded} remaining={remaining} limit={limit}{overall_message} unit=documents")
        if last_error:
            _emit(emit, f"progress: index resume pass={attempt} error={last_error}")
        if last_error is None and readiness == "ready":
            return {"state": "ready", "passes": attempt, "limit": limit, "last_result": last_result}

        if failure_streak >= 3 and limit > min_limit:
            limit = max(min_limit, limit // 2)
            failure_streak = 0
            _emit(emit, f"progress: index resume lowering-limit={limit}")
        if stagnant_streak >= stuck_pass_threshold and limit > min_limit:
            limit = max(min_limit, limit // 2)
            stagnant_streak = 0
            _emit(emit, f"progress: index resume lowering-limit={limit}")
        if attempt < max_passes:
            if progress_reporter is not None:
                progress_reporter("resume_backoff", attempt, max_passes, f"waiting {sleep_seconds:g}s before next pass; unit=passes")
            time.sleep(sleep_seconds)

    return {"state": "max_passes_reached", "passes": max_passes, "limit": limit, "last_result": last_result, "last_error": last_error}


def build_resume_envelope(
    backend: object,
    *,
    app_slug: str,
    version_label: str,
    initial_limit: int,
    min_limit: int,
    max_passes: int,
    stuck_pass_threshold: int,
    sleep_seconds: float,
    progress_reporter: IndexProgressReporter | None,
    emit: ResumeEmitter | None,
) -> CommandEnvelope:
    validate_resume_args(
        initial_limit=initial_limit,
        min_limit=min_limit,
        max_passes=max_passes,
        stuck_pass_threshold=stuck_pass_threshold,
        sleep_seconds=sleep_seconds,
    )
    result = resume_index(
        backend,
        app_slug=app_slug,
        version_label=version_label,
        initial_limit=initial_limit,
        min_limit=min_limit,
        max_passes=max_passes,
        stuck_pass_threshold=stuck_pass_threshold,
        sleep_seconds=sleep_seconds,
        progress_reporter=progress_reporter,
        emit=emit,
    )
    last_result = dict(result.get("last_result") or {})
    readiness_status = str(last_result.get("readiness_status") or result.get("state") or "embedding_pending")
    return {
        "status": "ok" if result["state"] == "ready" else "warning",
        "command": "index resume",
        "scope": {"app_slug": app_slug, "version_label": version_label},
        "data": {
            "state": result["state"],
            "readiness_status": readiness_status,
            **last_result,
            "passes": result["passes"],
            "limit": result["limit"],
        },
        "warnings": [str(result["last_error"])] if result.get("last_error") else [],
        "degraded": result["state"] != "ready",
        "next_actions": status_next_actions(
            readiness_state=readiness_status, is_active=bool(last_result.get("is_active")),
            degraded=result["state"] != "ready", app_slug=app_slug, version_label=version_label,
        ),
    }


def validate_resume_args(*, initial_limit: int, min_limit: int, max_passes: int, stuck_pass_threshold: int, sleep_seconds: float) -> None:
    if initial_limit <= 0:
        raise SpecItOutRuntimeError("--initial-limit must be positive.")
    if min_limit <= 0:
        raise SpecItOutRuntimeError("--min-limit must be positive.")
    if max_passes <= 0:
        raise SpecItOutRuntimeError("--max-passes must be positive.")
    if stuck_pass_threshold <= 0:
        raise SpecItOutRuntimeError("--stuck-pass-threshold must be positive.")
    if sleep_seconds < 0:
        raise SpecItOutRuntimeError("--sleep-seconds must be zero or positive.")
    if min_limit > initial_limit:
        raise SpecItOutRuntimeError("--min-limit cannot be greater than --initial-limit.")


def _int_stat(stats: dict[str, object], key: str) -> int:
    return int(stats.get(key) or 0)


def _emit(emit: ResumeEmitter | None, line: str) -> None:
    if emit is not None:
        emit(line)


def _embedding_status(backend: object, *, app_slug: str, version_label: str) -> dict[str, object] | None:
    status_method = getattr(backend, "import_status", None)
    if status_method is None:
        return None
    status = status_method(app_slug=app_slug, version_label=version_label)
    data = dict(status.get("data") or {})
    export = dict(data.get("export") or {})
    if export.get("version_label") != version_label:
        raise SpecItOutRuntimeError("Index resume status returned an unexpected export version.")
    stats = dict(data.get("embedding_stats") or {})
    required = {"total_documents", "embedded_documents", "remaining_documents"}
    if not required.issubset(stats):
        raise SpecItOutRuntimeError("Index resume requires complete embedding counts for the target export.")
    return {"readiness_status": export.get("readiness_status"), "is_active": bool(export.get("is_active")), "stats": stats}
