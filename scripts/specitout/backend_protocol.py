from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from specitout.contracts import CommandEnvelope
from specitout.progress import ImportProgressReporter, IndexProgressReporter


class LocalBackendProtocol(Protocol):
    def import_status(self, *, app_slug: str, version_label: str | None) -> CommandEnvelope:
        ...

    def index_status(self, *, app_slug: str | None, version_label: str | None) -> CommandEnvelope:
        ...

    def list_applications(self) -> list[dict[str, object]]:
        ...

    def get_application(self, *, app_slug: str) -> dict[str, object] | None:
        ...

    def register_import(self, *, app_slug: str, version_label: str, source_export_hash: str, export_path: Path, display_name: str | None, source_system: str, external_app_id: str | None) -> dict[str, object]:
        ...

    def list_imports(self, *, app_slug: str | None) -> list[dict[str, object]]:
        ...

    def delete_export_scoped_rows(self, table: str, export_id: str) -> None:
        ...

    def upsert_rows(self, table: str, rows: list[dict[str, object]]) -> None:
        ...

    def start_import_pipeline(self, *, app: dict[str, object], export: dict[str, object], export_path: Path, source_export_hash: str, progress_reporter: ImportProgressReporter | None = None) -> dict[str, object]:
        ...

    def rebuild_index(self, *, app_slug: str, version_label: str, embedding_limit: int | None = None, progress_reporter: IndexProgressReporter | None = None) -> dict[str, object]:
        ...

    def persist_search_document_embeddings(self, *, export_id: str, embeddings: list[dict[str, Any]]) -> None:
        ...

    def activate_import(self, *, app_slug: str, version_label: str) -> dict[str, object]:
        ...

    def query_search(self, *, app_slug: str, query_text: str, version_label: str | None, mode: str, limit: int, export_id: str | None = None) -> dict[str, object]:
        ...

    def query_entity(self, *, app_slug: str, entity_lookup: str, version_label: str | None, export_id: str | None = None) -> dict[str, object]:
        ...

    def query_usage(self, *, app_slug: str, entity_lookup: str, version_label: str | None, direction: str, relation: str | None, limit: int, export_id: str | None = None) -> dict[str, object]:
        ...

    def query_paths(self, *, app_slug: str, from_lookup: str, to_lookup: str, version_label: str | None, direction: str, relation: str | None, max_hops: int, max_paths: int, export_id: str | None = None) -> dict[str, object]:
        ...

    def build_bundle(self, *, app_slug: str, query_text: str | None, entity_key: str | None, version_label: str | None, mode: str, anchor_limit: int, max_hops: int, entity_limit: int, edge_limit: int, export_id: str | None = None) -> dict[str, object]:
        ...
