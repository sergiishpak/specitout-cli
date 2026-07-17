from __future__ import annotations

import json

from specitout.runtime import AppOwnedPostgresRuntime
from specitout.search_spike import (
    FIXTURE_DOCUMENTS,
    SearchCapabilityReport,
    SearchSpikeDocument,
    SearchSpikeResult,
    build_result,
    default_capabilities,
)


class PostgresSearchSpikeAdapter:
    def __init__(self) -> None:
        self._runtime = AppOwnedPostgresRuntime()
        self._runtime_status = None

    def seed_fixture(self) -> None:
        runtime = self._ensure_runtime()
        sql = """
-- specitout_search_spike:seed_fixture
create schema if not exists specitout_search_spike;
create table if not exists specitout_search_spike.applications (
  id text primary key,
  slug text not null unique
);
create table if not exists specitout_search_spike.exports (
  id text primary key,
  application_id text not null references specitout_search_spike.applications(id),
  version_label text not null
);
create table if not exists specitout_search_spike.search_documents (
  export_id text not null references specitout_search_spike.exports(id),
  document_key text primary key,
  identifier_text text not null,
  lexical_text text not null,
  semantic_text text not null,
  embedding_vector vector(3)
);
delete from specitout_search_spike.search_documents;
delete from specitout_search_spike.exports;
delete from specitout_search_spike.applications;
insert into specitout_search_spike.applications (id, slug) values ('app-1', 'fixture-app');
insert into specitout_search_spike.exports (id, application_id, version_label) values ('export-1', 'app-1', 'v1');
"""
        for document in FIXTURE_DOCUMENTS:
            vector = document["embedding_vector"]
            sql += (
                "insert into specitout_search_spike.search_documents "
                "(export_id, document_key, identifier_text, lexical_text, semantic_text, embedding_vector) values "
                f"('export-1', '{self._escape(str(document['document_key']))}', "
                f"'{self._escape(str(document['identifier_text']))}', "
                f"'{self._escape(str(document['lexical_text']))}', "
                f"'{self._escape(str(document['semantic_text']))}', "
                f"'[{vector[0]},{vector[1]},{vector[2]}]');\n"
            )
        self._runtime._run_psql(runtime.psql_binary, runtime.port, runtime.database, sql)

    def search_exact(self, *, query_text: str, app_slug: str, version_label: str) -> SearchSpikeResult:
        runtime = self._ensure_runtime()
        sql = f"""
-- specitout_search_spike:search_exact
select coalesce(
  json_agg(
    json_build_object(
      'document_key', sd.document_key,
      'identifier_text', sd.identifier_text,
      'match_stage', 'exact'
    )
    order by sd.document_key asc
  )::text,
  '[]'
)
from specitout_search_spike.search_documents sd
join specitout_search_spike.exports e on e.id = sd.export_id
join specitout_search_spike.applications a on a.id = e.application_id
where a.slug = '{self._escape(app_slug)}'
  and e.version_label = '{self._escape(version_label)}'
  and lower(sd.identifier_text) = lower('{self._escape(query_text)}');
"""
        payload = self._runtime._run_psql(runtime.psql_binary, runtime.port, runtime.database, sql).strip() or "[]"
        results = json.loads(payload)
        return build_result(
            query_text=query_text,
            app_slug=app_slug,
            version_label=version_label,
            results=[self._to_document(row) for row in results],
            capabilities=self.capabilities(),
        )

    def search_lexical(self, *, query_text: str, app_slug: str, version_label: str) -> SearchSpikeResult:
        runtime = self._ensure_runtime()
        sql = f"""
-- specitout_search_spike:search_lexical
select coalesce(
  json_agg(
    json_build_object(
      'document_key', document_key,
      'identifier_text', identifier_text,
      'match_stage', 'lexical'
    )
    order by lexical_rank desc, document_key asc
  )::text,
  '[]'
)
from (
  select
    sd.document_key,
    sd.identifier_text,
    ts_rank(to_tsvector('simple', sd.lexical_text), plainto_tsquery('simple', '{self._escape(query_text)}')) as lexical_rank
  from specitout_search_spike.search_documents sd
  join specitout_search_spike.exports e on e.id = sd.export_id
  join specitout_search_spike.applications a on a.id = e.application_id
  where a.slug = '{self._escape(app_slug)}'
    and e.version_label = '{self._escape(version_label)}'
    and to_tsvector('simple', sd.lexical_text) @@ plainto_tsquery('simple', '{self._escape(query_text)}')
) ranked;
"""
        payload = self._runtime._run_psql(runtime.psql_binary, runtime.port, runtime.database, sql).strip() or "[]"
        results = json.loads(payload)
        return build_result(
            query_text=query_text,
            app_slug=app_slug,
            version_label=version_label,
            results=[self._to_document(row) for row in results],
            capabilities=self.capabilities(),
        )

    def search_fuzzy(self, *, query_text: str, app_slug: str, version_label: str) -> SearchSpikeResult:
        runtime = self._ensure_runtime()
        sql = f"""
-- specitout_search_spike:search_fuzzy
select coalesce(
  json_agg(
    json_build_object(
      'document_key', document_key,
      'identifier_text', identifier_text,
      'match_stage', 'fuzzy'
    )
    order by fuzzy_rank desc, document_key asc
  )::text,
  '[]'
)
from (
  select
    sd.document_key,
    sd.identifier_text,
    similarity(lower(sd.identifier_text), lower('{self._escape(query_text)}')) as fuzzy_rank
  from specitout_search_spike.search_documents sd
  join specitout_search_spike.exports e on e.id = sd.export_id
  join specitout_search_spike.applications a on a.id = e.application_id
  where a.slug = '{self._escape(app_slug)}'
    and e.version_label = '{self._escape(version_label)}'
  order by fuzzy_rank desc, sd.document_key asc
  limit 5
) ranked;
"""
        payload = self._runtime._run_psql(runtime.psql_binary, runtime.port, runtime.database, sql).strip() or "[]"
        results = json.loads(payload)
        return build_result(
            query_text=query_text,
            app_slug=app_slug,
            version_label=version_label,
            results=[self._to_document(row) for row in results],
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
            warnings=["vector search is unavailable for the current Postgres spike adapter"],
            degraded=True,
        )

    def capabilities(self) -> SearchCapabilityReport:
        return default_capabilities(
            fts="available",
            fuzzy_identifier="available",
            vector_search="unavailable",
            bulk_load="available",
        )

    def _ensure_runtime(self):
        if self._runtime_status is None:
            self._runtime_status = self._runtime.ensure_ready()
        binaries = self._runtime._resolve_binaries()
        return type(
            "RuntimeSession",
            (),
            {
                "database": self._runtime_status.database,
                "port": self._runtime_status.port,
                "psql_binary": binaries["psql"],
            },
        )()

    def _to_document(self, row: dict[str, str]) -> SearchSpikeDocument:
        return {
            "document_key": row["document_key"],
            "identifier_text": row["identifier_text"],
            "match_stage": row["match_stage"],
        }

    def _escape(self, value: str) -> str:
        return value.replace("'", "''")
