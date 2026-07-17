from __future__ import annotations

from difflib import SequenceMatcher
import sqlite3

from specitout.search_spike import (
    FIXTURE_DOCUMENTS,
    SearchCapabilityReport,
    SearchSpikeDocument,
    SearchSpikeResult,
    build_result,
    default_capabilities,
)


class SqliteSearchSpikeAdapter:
    def __init__(self, *, database_path: str = ":memory:") -> None:
        self._connection = sqlite3.connect(database_path)
        self._connection.row_factory = sqlite3.Row
        self._fts_available = False

    def seed_fixture(self) -> None:
        self._connection.executescript(
            """
            create table if not exists applications (
              id text primary key,
              slug text not null unique
            );
            create table if not exists exports (
              id text primary key,
              application_id text not null references applications(id),
              version_label text not null
            );
            create table if not exists search_documents (
              export_id text not null references exports(id),
              document_key text primary key,
              identifier_text text not null,
              lexical_text text not null,
              semantic_text text not null,
              embedding_vector text not null
            );
            delete from search_documents;
            delete from exports;
            delete from applications;
            """
        )
        self._prepare_fts_table()
        self._connection.execute(
            "insert into applications (id, slug) values (?, ?)",
            ("app-1", "fixture-app"),
        )
        self._connection.execute(
            "insert into exports (id, application_id, version_label) values (?, ?, ?)",
            ("export-1", "app-1", "v1"),
        )
        for document in FIXTURE_DOCUMENTS:
            self._connection.execute(
                """
                insert into search_documents (
                  export_id,
                  document_key,
                  identifier_text,
                  lexical_text,
                  semantic_text,
                  embedding_vector
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    "export-1",
                    document["document_key"],
                    document["identifier_text"],
                    document["lexical_text"],
                    document["semantic_text"],
                    ",".join(str(value) for value in document["embedding_vector"]),
                ),
            )
        if self._fts_available:
            self._connection.execute("delete from search_documents_fts")
            for document in FIXTURE_DOCUMENTS:
                self._connection.execute(
                    """
                    insert into search_documents_fts (
                      document_key,
                      identifier_text,
                      lexical_text,
                      app_slug,
                      version_label
                    ) values (?, ?, ?, ?, ?)
                    """,
                    (
                        document["document_key"],
                        document["identifier_text"],
                        document["lexical_text"],
                        "fixture-app",
                        "v1",
                    ),
                )
        self._connection.commit()

    def search_exact(self, *, query_text: str, app_slug: str, version_label: str) -> SearchSpikeResult:
        rows = self._connection.execute(
            """
            select sd.document_key, sd.identifier_text
            from search_documents sd
            join exports e on e.id = sd.export_id
            join applications a on a.id = e.application_id
            where a.slug = ?
              and e.version_label = ?
              and lower(sd.identifier_text) = lower(?)
            order by sd.document_key asc
            """,
            (app_slug, version_label, query_text),
        ).fetchall()
        return build_result(
            query_text=query_text,
            app_slug=app_slug,
            version_label=version_label,
            results=[
                {
                    "document_key": str(row["document_key"]),
                    "identifier_text": str(row["identifier_text"]),
                    "match_stage": "exact",
                }
                for row in rows
            ],
            capabilities=self.capabilities(),
        )

    def search_lexical(self, *, query_text: str, app_slug: str, version_label: str) -> SearchSpikeResult:
        if not self._fts_available:
            return build_result(
                query_text=query_text,
                app_slug=app_slug,
                version_label=version_label,
                results=[],
                capabilities=self.capabilities(),
                warnings=["SQLite FTS5 is unavailable for the current spike adapter"],
                degraded=True,
            )
        rows = self._connection.execute(
            """
            select document_key, identifier_text
            from search_documents_fts
            where app_slug = ?
              and version_label = ?
              and search_documents_fts match ?
            order by bm25(search_documents_fts), document_key asc
            """,
            (app_slug, version_label, query_text),
        ).fetchall()
        return build_result(
            query_text=query_text,
            app_slug=app_slug,
            version_label=version_label,
            results=[self._to_document(row) for row in rows],
            capabilities=self.capabilities(),
        )

    def search_fuzzy(self, *, query_text: str, app_slug: str, version_label: str) -> SearchSpikeResult:
        rows = self._connection.execute(
            """
            select sd.document_key, sd.identifier_text
            from search_documents sd
            join exports e on e.id = sd.export_id
            join applications a on a.id = e.application_id
            where a.slug = ?
              and e.version_label = ?
            """,
            (app_slug, version_label),
        ).fetchall()
        ranked = sorted(
            rows,
            key=lambda row: (
                -SequenceMatcher(
                    None,
                    str(row["identifier_text"]).lower(),
                    query_text.lower(),
                ).ratio(),
                str(row["document_key"]),
            ),
        )
        return build_result(
            query_text=query_text,
            app_slug=app_slug,
            version_label=version_label,
            results=[
                {
                    "document_key": str(row["document_key"]),
                    "identifier_text": str(row["identifier_text"]),
                    "match_stage": "fuzzy",
                }
                for row in ranked[:5]
            ],
            capabilities=self.capabilities(),
        )

    def search_vector(
        self,
        *,
        query_text: str,
        query_embedding: list[float],
        app_slug: str,
        version_label: str,
    ) -> SearchSpikeResult:
        return build_result(
            query_text=query_text,
            app_slug=app_slug,
            version_label=version_label,
            results=[],
            capabilities=self.capabilities(),
            warnings=["vector search is unavailable for the current SQLite spike adapter"],
            degraded=True,
        )

    def capabilities(self) -> SearchCapabilityReport:
        return default_capabilities(
            fts="available" if self._fts_available else "unavailable",
            fuzzy_identifier="available",
            vector_search="unavailable",
            bulk_load="unavailable",
        )

    def _to_document(self, row: sqlite3.Row) -> SearchSpikeDocument:
        return {
            "document_key": str(row["document_key"]),
            "identifier_text": str(row["identifier_text"]),
            "match_stage": "lexical",
        }

    def _prepare_fts_table(self) -> None:
        try:
            self._connection.execute(
                """
                create virtual table if not exists search_documents_fts
                using fts5(
                  document_key,
                  identifier_text,
                  lexical_text,
                  app_slug unindexed,
                  version_label unindexed
                )
                """
            )
        except sqlite3.OperationalError:
            self._fts_available = False
            return
        self._fts_available = True
