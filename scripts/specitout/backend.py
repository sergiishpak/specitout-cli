from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from specitout import backend_index, backend_lifecycle, backend_retrieval
from specitout.backend_gate import build_backend_gate_status
from specitout.backend_registration import register_import as persist_import_registration
from specitout.backend_protocol import LocalBackendProtocol
from specitout.backend_status import fetch_latest_pipeline_run, resolve_export_scope
from specitout.backend_writes import coerce_db_value, delete_export_scoped_rows as delete_export_scoped_rows_via_rpc
from specitout.backend_writes import upsert_rows as upsert_rows_via_sql
from specitout.contracts import CommandEnvelope
from specitout.embedding_provider import EmbeddingProvider, create_local_embedding_provider
from specitout.import_pipeline import start_initial_import_pipeline
from specitout.progress import ImportProgressReporter, IndexProgressReporter
from specitout.runtime import AppOwnedPostgresRuntime, SpecItOutRuntimeError, RuntimeStatus


class PostgresLocalBackend:
    def __init__(
        self,
        *,
        runtime_status: RuntimeStatus,
        embedding_provider_factory: Any | None = None,
    ) -> None:
        self._runtime_status = runtime_status
        self._embedding_provider_factory = embedding_provider_factory or create_local_embedding_provider
        self._embedding_provider: EmbeddingProvider | None = None

    def import_status(self, *, app_slug: str, version_label: str | None) -> CommandEnvelope:
        scope = resolve_export_scope(
            fetch_one=self._fetch_one,
            get_application=lambda slug: self.get_application(app_slug=slug),
            app_slug=app_slug,
            version_label=version_label,
        )
        export = scope["export"]
        return {
            "status": "ok",
            "command": "import status",
            "scope": {
                "app_slug": app_slug,
                "version_label": str(export.get("version_label")) if export.get("version_label") else version_label,
            },
            "data": {
                "state": str(export.get("readiness_status") or "registered"),
                "app": scope["app"],
                "export": export,
                "active_export": scope["active_export"],
                "pipeline_run": fetch_latest_pipeline_run(fetch_one=self._fetch_one, export_id=export["id"]),
                "embedding_stats": backend_index.get_embedding_stats(
                    fetch_one=self._fetch_one,
                    export_id=str(export["id"]),
                ),
            },
            "warnings": [],
            "degraded": str(export.get("readiness_status") or "") in {"degraded", "failed"},
            "next_actions": [],
        }

    def index_status(self, *, app_slug: str | None, version_label: str | None) -> CommandEnvelope:
        runtime = self._runtime_status
        warnings: list[str] = []
        degraded = False
        data: dict[str, object] = {
            "state": runtime.state,
            "runtime_state": runtime.state,
            "data_root": runtime.data_root,
            "bootstrap_action": runtime.bootstrap_action,
            "server_action": runtime.server_action,
            "migrations": runtime.migrations,
            "extensions": runtime.extensions,
            "database": runtime.database,
            "port": runtime.port,
            **build_backend_gate_status(),
        }
        if app_slug is not None:
            try:
                scope = resolve_export_scope(
                    fetch_one=self._fetch_one,
                    get_application=lambda slug: self.get_application(app_slug=slug),
                    app_slug=app_slug,
                    version_label=version_label,
                )
            except SpecItOutRuntimeError as exc:
                warnings.append(str(exc))
            else:
                export_readiness = str(scope["export"].get("readiness_status") or "")
                pipeline_run = fetch_latest_pipeline_run(fetch_one=self._fetch_one, export_id=scope["export"]["id"])
                pipeline_status = str(pipeline_run.get("status") or "") if pipeline_run is not None else ""
                degraded = export_readiness in {"degraded", "failed"} or pipeline_status == "failed"
                data.update(
                    {
                        "app": scope["app"],
                        "export": scope["export"],
                        "active_export": scope["active_export"],
                        "pipeline_run": pipeline_run,
                        "embedding_stats": backend_index.get_embedding_stats(
                            fetch_one=self._fetch_one,
                            export_id=str(scope["export"]["id"]),
                        ),
                    }
                )
        return {
            "status": "ok",
            "command": "index status",
            "scope": {
                "app_slug": app_slug,
                "version_label": version_label,
            },
            "data": data,
            "warnings": warnings,
            "degraded": degraded,
            "next_actions": ["import add"],
        }

    def list_applications(self) -> list[dict[str, object]]:
        query = """
select
  a.slug as app_slug,
  a.display_name,
  a.source_system,
  active.version_label as active_export_version,
  active.readiness_status::text as active_export_readiness,
  count(e.id)::int as export_count
from specitout.apps a
left join specitout.exports active on active.id = a.active_export_id
left join specitout.exports e on e.app_id = a.id
where a.lifecycle_status <> 'deleted'
group by a.id, a.slug, a.display_name, a.source_system, active.version_label, active.readiness_status
order by a.slug asc
"""
        return self._fetch_all(query)

    def get_application(self, *, app_slug: str) -> dict[str, object] | None:
        query = """
select
  a.id,
  a.slug as app_slug,
  a.display_name,
  a.source_system,
  a.external_app_id,
  a.created_at,
  active.version_label as active_export_version,
  active.readiness_status::text as active_export_readiness,
  count(e.id)::int as export_count
from specitout.apps a
left join specitout.exports active on active.id = a.active_export_id
left join specitout.exports e on e.app_id = a.id
where a.slug = %(app_slug)s
group by a.id, a.slug, a.display_name, a.source_system, a.external_app_id, a.created_at, active.version_label, active.readiness_status
"""
        return self._fetch_one(query, {"app_slug": app_slug})

    def register_import(
        self,
        *,
        app_slug: str,
        version_label: str,
        source_export_hash: str,
        export_path: Path,
        display_name: str | None,
        source_system: str,
        external_app_id: str | None,
    ) -> dict[str, object]:
        return persist_import_registration(
            self,
            app_slug=app_slug,
            version_label=version_label,
            source_export_hash=source_export_hash,
            export_path=export_path,
            display_name=display_name,
            source_system=source_system,
            external_app_id=external_app_id,
        )

    def list_imports(self, *, app_slug: str | None) -> list[dict[str, object]]:
        query = """
select
  a.slug as app_slug,
  a.display_name as app_display_name,
  e.version_label,
  e.readiness_status::text as readiness_status,
  e.lifecycle_status::text as lifecycle_status,
  e.supersedes_export_id,
  e.import_mode,
  e.registered_at,
  (a.active_export_id = e.id) as is_active,
  active.id as active_export_id,
  active.version_label as active_export_version,
  active.readiness_status::text as active_export_readiness
from specitout.exports e
join specitout.apps a on a.id = e.app_id
left join specitout.exports active on active.id = a.active_export_id
where (%(app_slug)s::text is null or a.slug = %(app_slug)s::text)
  and a.lifecycle_status <> 'deleted'
order by a.slug asc, e.registered_at asc, e.version_label asc
"""
        return self._fetch_all(query, {"app_slug": app_slug})

    def start_import_pipeline(
        self,
        *,
        app: dict[str, object],
        export: dict[str, object],
        export_path: Path,
        source_export_hash: str,
        progress_reporter: ImportProgressReporter | None = None,
    ) -> dict[str, object]:
        return start_initial_import_pipeline(
            self,
            app=app,
            export=export,
            export_path=export_path,
            source_export_hash=source_export_hash,
            progress_reporter=progress_reporter,
        )

    def update_export(self, export_id: str, **changes: Any) -> dict[str, object]:
        if not changes:
            export = self._fetch_one(
                """
select
  id,
  app_id,
  version_label,
  readiness_status::text as readiness_status,
  lifecycle_status::text as lifecycle_status,
  supersedes_export_id,
  source_export_hash,
  registered_at,
  metadata_json,
  import_mode
from specitout.exports
where id = %(export_id)s
limit 1
""",
                {"export_id": export_id},
            )
            if export is None:
                raise KeyError(export_id)
            return export
        assignments = ", ".join(f"{key} = %({key})s" for key in changes)
        query = f"""
update specitout.exports
set {assignments}
where id = %(export_id)s
returning
  id,
  app_id,
  version_label,
  readiness_status::text as readiness_status,
  lifecycle_status::text as lifecycle_status,
  supersedes_export_id,
  source_export_hash,
  registered_at,
  metadata_json,
  import_mode
"""
        params = {"export_id": export_id, **{key: coerce_db_value(value) for key, value in changes.items()}}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        updated = self._normalize_row(row)
        if updated is None:
            raise KeyError(export_id)
        return updated

    def delete_export_scoped_rows(self, table: str, export_id: str) -> None:
        delete_export_scoped_rows_via_rpc(connect=self._connect, table=table, export_id=export_id)

    def upsert_rows(self, table: str, rows: list[dict[str, Any]]) -> None:
        upsert_rows_via_sql(connect=self._connect, table=table, rows=rows)

    def get_app(self, *, app_slug: str) -> dict[str, object] | None:
        return backend_index.get_app(fetch_one=self._fetch_one, app_slug=app_slug)

    def get_export(self, *, app_id: str, version_label: str) -> dict[str, object] | None:
        return backend_index.get_export(fetch_one=self._fetch_one, app_id=app_id, version_label=version_label)

    def list_export_rows(self, *, table: str, export_id: str) -> list[dict[str, object]]:
        return backend_index.list_export_rows(fetch_all=self._fetch_all, table=table, export_id=export_id)

    def count_search_documents(self, *, export_id: str) -> int:
        return backend_index.count_search_documents(fetch_one=self._fetch_one, export_id=export_id)

    def count_pending_search_document_embeddings(self, *, export_id: str) -> int:
        return backend_index.count_pending_search_document_embeddings(fetch_one=self._fetch_one, export_id=export_id)

    def list_pending_search_document_embedding_inputs(
        self,
        *,
        export_id: str,
        limit: int,
        offset: int | None = None,
    ) -> list[dict[str, object]]:
        return backend_index.list_pending_search_document_embedding_inputs(
            fetch_all=self._fetch_all,
            export_id=export_id,
            limit=limit,
            offset=offset,
        )

    def list_source_evidence_rows(self, *, export_id: str) -> list[dict[str, object]]:
        return backend_index.list_source_evidence_rows(fetch_all=self._fetch_all, export_id=export_id)

    def download_object(self, *, bucket: str, object_path: str) -> bytes:
        return backend_index.download_object(bucket=bucket, object_path=object_path)

    def replace_search_documents(
        self,
        *,
        export_id: str,
        documents: list[dict[str, Any]],
        associations: list[dict[str, Any]],
    ) -> None:
        backend_index.replace_search_documents(
            connect=self._connect,
            export_id=export_id,
            documents=documents,
            associations=associations,
        )

    def rebuild_index(
        self,
        *,
        app_slug: str,
        version_label: str,
        embedding_limit: int | None = None,
        progress_reporter: IndexProgressReporter | None = None,
    ) -> dict[str, object]:
        return backend_index.rebuild_index(
            self,
            app_slug=app_slug,
            version_label=version_label,
            embedding_limit=embedding_limit,
            embedding_provider=self._get_embedding_provider(),
            progress_reporter=progress_reporter,
        )

    def persist_search_document_embeddings(self, *, export_id: str, embeddings: list[dict[str, Any]]) -> None:
        backend_index.persist_search_document_embeddings(
            connect=self._connect,
            export_id=export_id,
            embeddings=embeddings,
        )

    def activate_import(self, *, app_slug: str, version_label: str) -> dict[str, object]:
        return backend_lifecycle.activate_import(
            connect=self._connect,
            fetch_one=self._fetch_one,
            app_slug=app_slug,
            version_label=version_label,
        )

    def query_search(
        self,
        *,
        app_slug: str,
        query_text: str,
        version_label: str | None,
        mode: str,
        limit: int,
        export_id: str | None = None,
    ) -> dict[str, object]:
        return backend_retrieval.query_search(
            fetch_one=self._fetch_one,
            get_application=lambda slug: self.get_application(app_slug=slug),
            app_slug=app_slug,
            query_text=query_text,
            version_label=version_label,
            export_id=export_id,
            mode=mode,
            limit=limit,
            embedding_provider=self._get_embedding_provider(),
        )

    def query_entity(self, *, app_slug: str, entity_lookup: str, version_label: str | None, export_id: str | None = None) -> dict[str, object]:
        return backend_retrieval.query_entity(
            fetch_one=self._fetch_one,
            get_application=lambda slug: self.get_application(app_slug=slug),
            app_slug=app_slug,
            entity_lookup=entity_lookup,
            version_label=version_label,
            export_id=export_id,
        )

    def query_usage(self, *, app_slug: str, entity_lookup: str, version_label: str | None, direction: str, relation: str | None, limit: int, export_id: str | None = None) -> dict[str, object]:
        return backend_retrieval.query_usage(
            fetch_one=self._fetch_one,
            get_application=lambda slug: self.get_application(app_slug=slug),
            app_slug=app_slug,
            entity_lookup=entity_lookup,
            version_label=version_label,
            export_id=export_id,
            direction=direction,
            relation=relation,
            limit=limit,
        )

    def query_paths(self, *, app_slug: str, from_lookup: str, to_lookup: str, version_label: str | None, direction: str, relation: str | None, max_hops: int, max_paths: int, export_id: str | None = None) -> dict[str, object]:
        return backend_retrieval.query_paths(
            fetch_one=self._fetch_one,
            get_application=lambda slug: self.get_application(app_slug=slug),
            app_slug=app_slug,
            from_lookup=from_lookup,
            to_lookup=to_lookup,
            version_label=version_label,
            export_id=export_id,
            direction=direction,
            relation=relation,
            max_hops=max_hops,
            max_paths=max_paths,
        )

    def build_bundle(self, *, app_slug: str, query_text: str | None, entity_key: str | None, version_label: str | None, mode: str, anchor_limit: int, max_hops: int, entity_limit: int, edge_limit: int, export_id: str | None = None) -> dict[str, object]:
        return backend_retrieval.build_context_bundle(
            fetch_one=self._fetch_one,
            get_application=lambda slug: self.get_application(app_slug=slug),
            app_slug=app_slug,
            query_text=query_text,
            entity_key=entity_key,
            version_label=version_label,
            export_id=export_id,
            mode=mode,
            anchor_limit=anchor_limit,
            max_hops=max_hops,
            entity_limit=entity_limit,
            edge_limit=edge_limit,
            embedding_provider=self._get_embedding_provider() if query_text else None,
        )

    def _fetch_all(
        self,
        query: str,
        params: Mapping[str, object] | None = None,
    ) -> list[dict[str, object]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params or {})
            rows = cur.fetchall()
        return [self._normalize_row(row) for row in rows]

    def _fetch_one(
        self,
        query: str,
        params: Mapping[str, object] | None = None,
    ) -> dict[str, object] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params or {})
            row = cur.fetchone()
        return self._normalize_row(row)

    def _connect(self) -> object:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:
            raise SpecItOutRuntimeError(
                "psycopg is required for runtime-backed SpecItOut catalog commands. "
                "Install project dependencies before running app or import commands."
            ) from exc
        try:
            return psycopg.connect(
                host="127.0.0.1",
                port=self._runtime_status.port,
                dbname=self._runtime_status.database,
                user="postgres",
                row_factory=dict_row,
            )
        except Exception as exc:
            raise SpecItOutRuntimeError(
                "failed to connect to the local SpecItOut catalog database. "
                f"Confirm the app-owned runtime is running on 127.0.0.1:{self._runtime_status.port}."
            ) from exc

    def _get_embedding_provider(self) -> EmbeddingProvider:
        if self._embedding_provider is None:
            self._embedding_provider = self._embedding_provider_factory()
        return self._embedding_provider

    def _normalize_row(self, row: Mapping[str, object] | None) -> dict[str, object] | None:
        if row is None:
            return None
        normalized: dict[str, object] = {}
        for key, value in row.items():
            if isinstance(value, (datetime, date)):
                normalized[key] = value.isoformat()
            elif isinstance(value, Mapping):
                normalized[key] = dict(value)
            else:
                normalized[key] = value
        return normalized

def build_local_backend() -> LocalBackendProtocol:
    runtime_status = AppOwnedPostgresRuntime().ensure_ready()
    return PostgresLocalBackend(runtime_status=runtime_status)
