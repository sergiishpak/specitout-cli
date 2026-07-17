from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from specitout.backend_protocol import LocalBackendProtocol
from specitout.bundle_service import BundleService
from specitout.contracts import CommandEnvelope
from specitout.index_resume import build_resume_envelope
from specitout.import_recovery import retry_import
from specitout.progress import ImportProgressReporter, IndexProgressReporter
from specitout.retrieval_service import RetrievalService
from specitout.runtime import SpecItOutRuntimeError
from specitout.status_actions import status_next_actions


def _service_backend_method(backend: LocalBackendProtocol, method_name: str) -> object:
    method = getattr(backend, method_name, None)
    if method is None:
        raise CliServiceError(f"{method_name} is not available for the current SpecItOut backend.")
    return method


class CliServiceError(SpecItOutRuntimeError):
    """Raised when a CLI-facing service cannot complete successfully."""


class ServiceNotImplementedError(CliServiceError):
    """Raised when a command family exists but is not implemented yet."""


def raise_not_implemented(command_path: str) -> None:
    raise ServiceNotImplementedError(f"{command_path} is not implemented yet")


def default_display_name(app_slug: str) -> str:
    return app_slug.replace("-", " ").title()


def _map_export_row(export: dict[str, object]) -> dict[str, object]:
    mapped = dict(export)
    readiness_state = mapped.pop("readiness_status", None)
    lifecycle_state = mapped.pop("lifecycle_status", None)
    if readiness_state is not None:
        mapped["readiness_state"] = readiness_state
    if lifecycle_state is not None:
        mapped["lifecycle_state"] = lifecycle_state
    return mapped


def _with_cutover_context(
    export: dict[str, object],
    *,
    active_export: dict[str, object] | None,
    default_query_version: str | None = None,
) -> dict[str, object]:
    mapped = _map_export_row(export)
    active_version = None
    active_export_id = None
    if active_export is not None:
        active_version = str(active_export.get("version_label") or "") or None
        active_export_id = str(active_export.get("id") or "") or None
    if default_query_version is None:
        default_query_version = active_version
    supersedes_export_id = str(mapped.get("supersedes_export_id") or "") or None
    is_active = bool(mapped.get("is_active"))
    pending_cutover = bool(
        not is_active
        and active_export_id is not None
        and supersedes_export_id == active_export_id
    )
    mapped["pending_cutover"] = pending_cutover
    mapped["replaces_active_version"] = active_version if pending_cutover else None
    mapped["default_query_version"] = default_query_version
    return mapped


class ApplicationCatalogService:
    def __init__(self, backend_factory: Callable[[], LocalBackendProtocol]) -> None:
        self._backend_factory = backend_factory

    def list(self) -> CommandEnvelope:
        applications = self._backend_factory().list_applications()
        return {
            "status": "ok",
            "command": "app list",
            "scope": {
                "app_slug": None,
                "version_label": None,
            },
            "data": {
                "state": "catalog_ready",
                "applications": applications,
                "application_count": len(applications),
            },
            "warnings": [],
            "degraded": False,
            "next_actions": ["app show --app <app-slug>", "import add --app <app-slug> --version <version> --export <path>"],
        }

    def show(self, *, app_slug: str) -> CommandEnvelope:
        application = self._backend_factory().get_application(app_slug=app_slug)
        if application is None:
            raise CliServiceError(f"Unknown application scope {app_slug}.")
        return {
            "status": "ok",
            "command": "app show",
            "scope": {
                "app_slug": app_slug,
                "version_label": str(application.get("active_export_version")) if application.get("active_export_version") else None,
            },
            "data": {
                "state": "catalog_ready",
                "application": application,
            },
            "warnings": [],
            "degraded": False,
            "next_actions": ["import list --app <app-slug>", "import add --app <app-slug> --version <version> --export <path>"],
        }


class ImportService:
    def __init__(
        self,
        backend_factory: Callable[[], LocalBackendProtocol],
        progress_reporter: ImportProgressReporter | None = None,
    ) -> None:
        self._backend_factory = backend_factory
        self._progress_reporter = progress_reporter

    def add(
        self,
        *,
        app_slug: str,
        version_label: str,
        export_path: str,
        display_name: str | None,
        source_system: str,
        external_app_id: str | None,
    ) -> CommandEnvelope:
        path = Path(export_path).expanduser().resolve()
        if not path.is_file():
            raise CliServiceError(f"Bubble export file was not found: {path}")
        source_export_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        resolved_external_app_id = external_app_id or _infer_external_app_id(path)
        backend = self._backend_factory()
        result = backend.register_import(
            app_slug=app_slug,
            version_label=version_label,
            source_export_hash=source_export_hash,
            export_path=path,
            display_name=display_name,
            source_system=source_system,
            external_app_id=resolved_external_app_id,
        )
        should_start_pipeline = bool(result["created"]) or str(result["export"].get("readiness_status") or "") in {
            "registered",
            "ingesting",
            "failed",
            "degraded",
        }
        active_export = result["active_export"]
        if should_start_pipeline:
            pipeline_result = backend.start_import_pipeline(
                app=result["app"],
                export=result["export"],
                export_path=path,
                source_export_hash=source_export_hash,
                progress_reporter=self._progress_reporter,
            )
        else:
            status = backend.import_status(app_slug=app_slug, version_label=version_label)
            pipeline_result = {
                "export": dict(status["data"]["export"]),
                "pipeline_run": dict(status["data"]["pipeline_run"]) if status["data"].get("pipeline_run") else None,
                "source_evidence": [],
            }
            active_export = status["data"].get("active_export")
        mapped_active_export = _map_export_row(dict(active_export)) if active_export else None
        export = _with_cutover_context(
            dict(pipeline_result["export"]),
            active_export=active_export,
            default_query_version=str(mapped_active_export.get("version_label")) if mapped_active_export else None,
        )
        return {
            "status": "ok",
            "command": "import add",
            "scope": {
                "app_slug": app_slug,
                "version_label": version_label,
            },
            "data": {
                "state": str(export.get("readiness_state") or "registered"),
                "app": result["app"],
                "export": export,
                "active_export": mapped_active_export,
                "created": result["created"],
                "pipeline_run": dict(pipeline_result["pipeline_run"]) if pipeline_result["pipeline_run"] else None,
                "source_evidence": [dict(row) for row in pipeline_result["source_evidence"]],
                "source_export_path": str(path),
                "source_export_hash": source_export_hash,
            },
            "warnings": [],
            "degraded": False,
            "next_actions": ["import list --app <app-slug>", "import status --app <app-slug>"],
        }

    def list(self, *, app_slug: str | None) -> CommandEnvelope:
        registrations = []
        for registration in self._backend_factory().list_imports(app_slug=app_slug):
            active_export = None
            active_export_id = str(registration.get("active_export_id") or "") or None
            active_export_version = str(registration.get("active_export_version") or "") or None
            active_export_readiness = str(registration.get("active_export_readiness") or "") or None
            if active_export_id is not None or active_export_version is not None:
                active_export = {
                    "id": active_export_id,
                    "version_label": active_export_version,
                    "readiness_status": active_export_readiness,
                }
            registrations.append(
                _with_cutover_context(
                    dict(registration),
                    active_export=active_export,
                    default_query_version=active_export_version,
                )
            )
        return {
            "status": "ok",
            "command": "import list",
            "scope": {
                "app_slug": app_slug,
                "version_label": None,
            },
            "data": {
                "state": "registration_ready",
                "registrations": registrations,
                "registration_count": len(registrations),
            },
            "warnings": [],
            "degraded": False,
            "next_actions": ["import add --app <app-slug> --version <version> --export <path>", "import status --app <app-slug>"],
        }

    def status(self, *, app_slug: str, version_label: str | None) -> CommandEnvelope:
        envelope = self._backend_factory().import_status(app_slug=app_slug, version_label=version_label)
        data = dict(envelope["data"])
        active_export = None
        if data.get("active_export") is not None:
            active_export = _map_export_row(dict(data["active_export"]))
            data["active_export"] = active_export
        export = _with_cutover_context(
            dict(envelope["data"]["export"]),
            active_export=data.get("active_export"),
            default_query_version=str(active_export.get("version_label")) if active_export else None,
        )
        data["export"] = export
        readiness_state = str(export.get("readiness_state") or data.get("state") or "registered")
        degraded = bool(envelope.get("degraded")) or readiness_state in {"degraded", "failed"}
        scope = dict(envelope.get("scope", {}))
        scope["app_slug"] = app_slug
        if scope.get("version_label") is None:
            scope["version_label"] = version_label
        return {
            **envelope,
            "scope": scope,
            "data": data,
            "degraded": degraded,
            "next_actions": status_next_actions(
                readiness_state=readiness_state,
                is_active=bool(export.get("is_active")),
                degraded=degraded,
            ),
        }

    def retry(self, *, app_slug: str, version_label: str, export_path: str | None) -> CommandEnvelope:
        result = retry_import(
            self._backend_factory(),
            app_slug=app_slug,
            version_label=version_label,
            export_path=export_path,
            progress_reporter=self._progress_reporter,
        )
        active_export = result["active_export"]
        mapped_active_export = _map_export_row(dict(active_export)) if active_export else None
        pipeline_result = dict(result["pipeline_result"])
        export = _with_cutover_context(
            dict(pipeline_result["export"]),
            active_export=active_export if isinstance(active_export, dict) else None,
            default_query_version=str(mapped_active_export.get("version_label")) if mapped_active_export else None,
        )
        return {
            "status": "ok",
            "command": "import retry",
            "scope": {"app_slug": app_slug, "version_label": version_label},
            "data": {
                "state": str(export.get("readiness_state") or "registered"),
                "app": result["app"],
                "export": export,
                "active_export": mapped_active_export,
                "pipeline_run": dict(pipeline_result["pipeline_run"]) if pipeline_result["pipeline_run"] else None,
                "source_evidence": [dict(row) for row in pipeline_result["source_evidence"]],
                "source_export_path": result["source_export_path"],
                "source_export_hash": result["source_export_hash"],
            },
            "warnings": [],
            "degraded": False,
            "next_actions": ["import status --app <app-slug> --version <version>", "index rebuild --app <app-slug> --version <version>"],
        }

    def activate(self, *, app_slug: str, version_label: str) -> CommandEnvelope:
        backend = self._backend_factory()
        result = _service_backend_method(backend, "activate_import")(
            app_slug=app_slug,
            version_label=version_label,
        )
        return {
            "status": "ok",
            "command": "import activate",
            "scope": {"app_slug": app_slug, "version_label": version_label},
            "data": {
                "state": str(result.get("readiness_status") or "active"),
                **dict(result),
            },
            "warnings": [],
            "degraded": False,
            "next_actions": ["query search --app <app-slug>"],
        }


class IndexService:
    def __init__(
        self,
        backend_factory: Callable[[], LocalBackendProtocol],
        progress_reporter: IndexProgressReporter | None = None,
    ) -> None:
        self._backend_factory = backend_factory
        self._progress_reporter = progress_reporter

    def status(self, *, app_slug: str | None, version_label: str | None) -> CommandEnvelope:
        if version_label is not None and app_slug is None:
            raise CliServiceError("index status requires --app when --version is provided.")
        backend = self._backend_factory()
        return backend.index_status(app_slug=app_slug, version_label=version_label)

    def rebuild(self, *, app_slug: str, version_label: str, limit: int | None = None) -> CommandEnvelope:
        if limit is not None and limit <= 0:
            raise CliServiceError("--limit must be positive.")
        result = _service_backend_method(self._backend_factory(), "rebuild_index")(
            app_slug=app_slug,
            version_label=version_label,
            embedding_limit=limit,
            progress_reporter=self._progress_reporter,
        )
        readiness_status = str(result.get("readiness_status") or "searchable")
        return {
            "status": "ok",
            "command": "index rebuild",
            "scope": {"app_slug": app_slug, "version_label": version_label},
            "data": {
                "state": readiness_status,
                **dict(result),
            },
            "warnings": [],
            "degraded": readiness_status in {"failed", "degraded"},
            "next_actions": ["import activate --app <app-slug> --version <version>", "query search --app <app-slug>"],
        }

    def resume(self, *, app_slug: str, version_label: str, initial_limit: int, min_limit: int, max_passes: int, stuck_pass_threshold: int, sleep_seconds: float) -> CommandEnvelope:
        return build_resume_envelope(
            self._backend_factory(),
            app_slug=app_slug,
            version_label=version_label,
            initial_limit=initial_limit,
            min_limit=min_limit,
            max_passes=max_passes,
            stuck_pass_threshold=stuck_pass_threshold,
            sleep_seconds=sleep_seconds,
            progress_reporter=self._progress_reporter,
            emit=lambda line: print(line, flush=True),
        )


class TaskService:
    def start(self) -> CommandEnvelope:
        raise_not_implemented("task start")

    def finish(self) -> CommandEnvelope:
        raise_not_implemented("task finish")


class LicenseService:
    def activate(self) -> CommandEnvelope:
        raise_not_implemented("license activate")

    def deactivate(self) -> CommandEnvelope:
        raise_not_implemented("license deactivate")

    def status(self) -> CommandEnvelope:
        raise_not_implemented("license status")


class TrialService:
    def status(self) -> CommandEnvelope:
        raise_not_implemented("trial status")


ParserFactory = Callable[[], argparse.ArgumentParser]


class HelpService:
    def __init__(self, *, parser_factory: ParserFactory) -> None:
        self._parser_factory = parser_factory

    def render_root(self) -> str:
        parser = self._parser_factory()
        return parser.format_help()

    def render_topic(self, topic: list[str]) -> str:
        if not topic:
            return self.render_root()

        parser = self._parser_factory()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            try:
                parser.parse_args([*topic, "--help"])
            except SystemExit as exc:
                if exc.code not in (0, None):
                    raise
        return buffer.getvalue()


@dataclass(frozen=True)
class CliServices:
    app: ApplicationCatalogService
    import_: ImportService
    index: IndexService
    task: TaskService
    retrieval: RetrievalService
    bundle: BundleService
    license: LicenseService
    trial: TrialService
    help: HelpService


def build_cli_services(
    *,
    backend_factory: Callable[[], LocalBackendProtocol],
    parser_factory: ParserFactory,
) -> CliServices:
    return CliServices(
        app=ApplicationCatalogService(backend_factory),
        import_=ImportService(backend_factory, progress_reporter=_print_import_progress),
        index=IndexService(backend_factory, progress_reporter=_print_index_progress),
        task=TaskService(),
        retrieval=RetrievalService(backend_factory),
        bundle=BundleService(backend_factory),
        license=LicenseService(),
        trial=TrialService(),
        help=HelpService(parser_factory=parser_factory),
    )


def _print_import_progress(stage: str, current: int, total: int, message: str) -> None:
    print(f"progress: import add {current}/{total} {stage} - {message}", flush=True)


def _print_index_progress(stage: str, current: int, total: int, message: str) -> None:
    print(f"progress: index rebuild {current}/{total} {stage} - {message}", flush=True)


def _infer_external_app_id(export_path: Path) -> str | None:
    try:
        payload = export_path.read_text()
    except OSError as exc:
        raise CliServiceError(f"Failed to read Bubble export file {export_path}: {exc}") from exc
    try:
        import json

        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if isinstance(decoded, dict):
        raw = decoded.get("_id")
        if raw:
            return str(raw)
    return None
